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


def resolve_organisation(request):
    """
    Phase 2: Resolve and validate organisation after DRF authentication.

    Called by TenantFilterMixin.get_queryset() after the user is authenticated.

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
            if request.user.memberships.filter(organisation=org, is_active=True).exists():
                request.organisation = org
                return org
            else:
                logger.warning(
                    "User %s attempted to access org %s without membership",
                    request.user.id,
                    org_id,
                )
                return None
        except Exception:
            return None

    # Fallback: user's first active organisation
    membership = (
        request.user.memberships
        .select_related("organisation")
        .filter(is_active=True, organisation__is_active=True)
        .order_by("created_at")
        .first()
    )
    if membership:
        request.organisation = membership.organisation
        return membership.organisation
    return None
