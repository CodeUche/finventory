"""
Tenant resolution middleware.

Architecture note on DRF + JWT compatibility:
    Django middleware runs BEFORE DRF's authentication layer. This means when
    TenantMiddleware executes, `request.user` is still the session-based
    AnonymousUser, not the JWT-authenticated user.

    Resolution strategy:
        1. Middleware sets `request._raw_org_id` from the header/query param.
        2. TenantFilterMixin (in views, after DRF auth) calls resolve_organisation()
           which uses the authenticated request.user to validate membership.

    This two-phase approach ensures:
        - Organisation ID is captured from the request
        - Membership validation happens after DRF knows who the user is
        - No circular dependency between middleware and DRF auth

Security:
    - Membership is always validated before org is attached to request.
    - Cross-tenant access raises TenantViolationError (403).
"""

import logging

from django.http import JsonResponse

logger = logging.getLogger(__name__)

HEADER_NAME = "HTTP_X_ORGANISATION_ID"
QUERY_PARAM = "org"

EXEMPT_PATHS = (
    "/api/v1/auth/",
    "/api/v1/health/",
    "/api/schema/",
    "/api/docs/",
    "/api/redoc/",
    "/admin/",
)


class TenantMiddleware:
    """
    Phase 1: Capture org ID from request for later DRF-layer resolution.

    Sets request._raw_org_id if the header/param is present.
    Sets request.organisation = None (will be populated by TenantFilterMixin).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.organisation = None
        request._raw_org_id = None

        if not self._is_exempt(request.path):
            # Capture org ID now; validate after DRF auth in the view layer
            org_id = request.META.get(HEADER_NAME) or request.GET.get(QUERY_PARAM)
            if org_id:
                request._raw_org_id = org_id

        return self.get_response(request)

    def _is_exempt(self, path: str) -> bool:
        return any(path.startswith(p) for p in EXEMPT_PATHS)


def _sync_rls(org):
    """
    Update the PostgreSQL session variable so RLS policies allow queries for
    this organisation.  Called immediately after org is validated so that the
    DB session is always in sync, regardless of which code path resolved it.

    This is belt-and-suspenders on top of RLSMiddleware: when no
    X-Organisation-ID header is sent, RLSMiddleware sets the SENTINEL, but
    resolve_organisation() picks the user's first org via fallback.  Without
    this call the RLS variable would remain SENTINEL and every tenant query
    would return empty / raise PermissionDenied.
    """
    try:
        from apps.core.middleware import _set_org
        _set_org(str(org.id))
    except Exception:
        pass


def resolve_organisation(request):
    """
    Phase 2: Resolve and validate organisation after DRF authentication.

    Called by TenantFilterMixin.get_queryset() after the user is authenticated.
    Also called by permission classes (IsStaff, etc.) during has_permission().

    Always calls _sync_rls() on success so the PostgreSQL RLS session variable
    is updated even when no X-Organisation-ID header was sent (fallback path).

    Returns Organisation or None.
    Raises nothing — callers handle None case.
    """
    from apps.tenancy.models import Organisation

    if not request.user or not request.user.is_authenticated:
        return None

    org_id = request._raw_org_id

    if org_id:
        try:
            org = Organisation.objects.get(id=org_id, is_active=True)
            # Superusers can access any organisation without a membership record
            if request.user.is_superuser:
                request.organisation = org
                _sync_rls(org)
                return org
            # Use raw SQL to check membership so the RLS tenant_isolation policy
            # on tenancy_membership (which gates on app.current_org_id = SENTINEL
            # for requests without a header) does not block the lookup.
            from django.db import connection as _conn
            with _conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM tenancy_membership WHERE user_id = %s AND organisation_id = %s AND is_active = TRUE LIMIT 1",
                    [request.user.pk, str(org.id)],
                )
                is_member = cur.fetchone() is not None
            if is_member:
                request.organisation = org
                _sync_rls(org)
                return org
            logger.warning(
                "User %s attempted to access org %s without membership",
                request.user.id,
                org_id,
            )
            return None
        except Exception:
            return None

    # Fallback: user's first active organisation.
    # NOTE: use raw SQL to bypass the RLS tenant_isolation policy on
    # tenancy_membership (which blocks rows when app.current_org_id is SENTINEL).
    # This path only executes when no X-Organisation-ID header was provided, so
    # we are allowed to use the user's own membership as the authoritative source.
    from django.db import connection
    try:
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT o.id FROM tenancy_organisation o
                INNER JOIN tenancy_membership m
                    ON m.organisation_id = o.id
                WHERE m.user_id = %s
                  AND m.is_active = TRUE
                  AND o.is_active  = TRUE
                ORDER BY m.created_at
                LIMIT 1
                """,
                [request.user.pk],
            )
            row = cur.fetchone()
        if row:
            from apps.tenancy.models import Organisation
            org = Organisation.objects.get(id=row[0])
            request.organisation = org
            _sync_rls(org)
            return org
    except Exception:
        pass
    return None
