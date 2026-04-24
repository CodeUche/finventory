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

    Sets app.current_user_id FIRST (from the verified request.user) so the
    membership_select RLS policy can expose the user's own membership rows
    even when app.current_org_id is still SENTINEL.

    Returns Organisation or None.  Raises nothing — callers handle None case.
    """
    from apps.tenancy.models import Organisation

    if not request.user or not request.user.is_authenticated:
        return None

    # Set the DB-level user identity from the DRF-verified user.  This must
    # happen BEFORE any membership query so the membership_select RLS policy
    # (which uses app.current_user_id for the SENTINEL bootstrap branch) can
    # return the user's own rows.
    try:
        from apps.core.middleware import _set_user
        _set_user(str(request.user.pk))
    except Exception:
        pass

    org_id = request._raw_org_id

    logger.info(
        "resolve_organisation: user=%s raw_org_id=%s header=%s param=%s",
        getattr(request.user, "id", "anon"),
        org_id,
        request.META.get(HEADER_NAME, "MISSING"),
        request.GET.get(QUERY_PARAM, "MISSING"),
    )

    if org_id:
        # Set org RLS context before querying the org or memberships.
        try:
            from apps.core.middleware import _set_org
            _set_org(str(org_id))
        except Exception:
            pass

        try:
            org = Organisation.objects.get(id=org_id, is_active=True)
            # Superusers can access any organisation without a membership record.
            if request.user.is_superuser:
                request.organisation = org
                _sync_rls(org)
                return org
            # Membership check via raw SQL (RLS is now set to org_id above).
            from django.db import connection as _conn
            with _conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM tenancy_membership"
                    " WHERE user_id = %s AND organisation_id = %s AND is_active = TRUE LIMIT 1",
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
        except Exception as exc:
            logger.error("resolve_organisation(org_id=%s) failed: %s", org_id, exc)
            return None

    # Fallback: no org ID in request — find the user's first active org.
    #
    # Two-step approach:
    #   1. Query tenancy_membership (membership_select RLS now allows this
    #      via app.current_user_id set above) to get the org UUID.
    #   2. Call _set_org() to update app.current_org_id BEFORE querying
    #      tenancy_organisation (which requires a matching org_id).
    try:
        org_ids = list(
            request.user.memberships
            .filter(is_active=True)
            .order_by("created_at")
            .values_list("organisation_id", flat=True)[:1]
        )
        if org_ids:
            found_org_id = str(org_ids[0])
            try:
                from apps.core.middleware import _set_org
                _set_org(found_org_id)
            except Exception:
                pass
            org = Organisation.objects.get(id=found_org_id, is_active=True)
            request.organisation = org
            _sync_rls(org)
            logger.info(
                "resolve_organisation fallback: resolved org %s for user %s",
                found_org_id, request.user.id,
            )
            return org
    except Exception as exc:
        logger.error("resolve_organisation fallback failed: %s", exc)
    return None
