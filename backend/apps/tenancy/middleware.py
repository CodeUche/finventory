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

    logger.info(
        "resolve_organisation: user=%s raw_org_id=%s header=%s param=%s",
        getattr(request.user, "id", "anon"),
        org_id,
        request.META.get(HEADER_NAME, "MISSING"),
        request.GET.get(QUERY_PARAM, "MISSING"),
    )

    if org_id:
        # Proactively set the PostgreSQL RLS session variable to the requested
        # org BEFORE any DB query.  RLSMiddleware may have been given SENTINEL
        # (all-zeros UUID) if the X-Organisation-ID header was stripped by the
        # Tauri HTTP adapter and only the ?org= query param arrived.  Without
        # this call the tenancy_membership RLS policy would filter out every
        # membership row, making is_member always False.
        try:
            from apps.core.middleware import _set_org
            _set_org(str(org_id))
        except Exception:
            pass

        try:
            org = Organisation.objects.get(id=org_id, is_active=True)
            # Superusers can access any organisation without a membership record
            if request.user.is_superuser:
                request.organisation = org
                _sync_rls(org)
                return org
            # Raw SQL membership check (bypasses Django ORM but still subject to
            # PostgreSQL RLS — which is now set correctly by the _set_org call above).
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
        except Exception as exc:
            logger.error("resolve_organisation(org_id=%s) failed: %s", org_id, exc)
            return None

    # Fallback: user's first active organisation (no org ID in request).
    #
    # Strategy: query ONLY tenancy_membership (no RLS issue — not filtered by
    # app.current_org_id) to get the org UUID, then call _set_org() BEFORE
    # fetching the Organisation object.  Joining tenancy_organisation in the
    # same query failed because tenancy_organisation IS subject to RLS, so the
    # INNER JOIN returned zero rows while app.current_org_id = SENTINEL.
    # This two-step approach mirrors what OrganisationViewSet.get_queryset()
    # does: it queries memberships first, then filters orgs — and it works.

    # DIAGNOSTIC — remove after confirming fix
    try:
        from django.db import connection as _diag_conn
        with _diag_conn.cursor() as _cur:
            _cur.execute("SELECT current_user, current_setting('app.current_org_id', TRUE)")
            _db_user, _cur_org = _cur.fetchone()
            _cur.execute("SELECT COUNT(*) FROM tenancy_membership WHERE user_id = %s", [str(request.user.pk)])
            _raw_count = _cur.fetchone()[0]
            _cur.execute("SELECT COUNT(*) FROM tenancy_membership WHERE user_id = %s AND is_active = TRUE", [str(request.user.pk)])
            _active_count = _cur.fetchone()[0]
            _cur.execute("SELECT COUNT(*) FROM pg_policies WHERE tablename = 'tenancy_membership' AND policyname = 'membership_bootstrap'")
            _policy_exists = _cur.fetchone()[0]
            _cur.execute("SELECT relrowsecurity FROM pg_class WHERE relname = 'tenancy_membership'")
            _rls_row = _cur.fetchone()
            _rls_enabled = _rls_row[0] if _rls_row else 'table-not-found'
        logger.warning(
            "DIAG fallback: db_user=%s cur_org=%s raw_membership_count=%s active_count=%s bootstrap_policy=%s rls_enabled=%s user_pk=%s",
            _db_user, _cur_org, _raw_count, _active_count, _policy_exists, _rls_enabled, request.user.pk,
        )
    except Exception as _diag_exc:
        logger.warning("DIAG failed: %s", _diag_exc)

    try:
        org_ids = list(
            request.user.memberships
            .filter(is_active=True)
            .order_by("created_at")
            .values_list("organisation_id", flat=True)[:1]
        )
        if org_ids:
            found_org_id = str(org_ids[0])
            # Correct the RLS session variable BEFORE querying tenancy_organisation.
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
