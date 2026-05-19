"""
PostHog analytics middleware.

Captures server-side API events for authenticated users.
Skips health checks, static files, media files, and token refresh endpoints
to avoid noise in the analytics data.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Paths that should not be tracked
_SKIP_PREFIXES = (
    "/static/",
    "/media/",
    "/api/v1/auth/token/",   # token refresh — too frequent, no business signal
    "/api/v1/ping/",
    "/favicon",
    "/__debug__/",
)


def _get_posthog_client():
    """Return a lazily-initialised PostHog client, or None if not configured."""
    api_key = getattr(settings, "POSTHOG_API_KEY", "")
    if not api_key:
        return None
    try:
        import posthog as _posthog
        _posthog.api_key = api_key
        _posthog.host = getattr(settings, "POSTHOG_HOST", "")
        return _posthog
    except ImportError:
        logger.warning("posthog package not installed — analytics disabled")
        return None


_posthog_client = None


def _client():
    global _posthog_client
    if _posthog_client is None:
        _posthog_client = _get_posthog_client()
    return _posthog_client


class PostHogMiddleware:
    """
    Middleware that fires a server-side PostHog event for each API request
    made by an authenticated user.

    Event name: ``api_request``
    Properties captured:
        - method       HTTP verb
        - path         Request path (no query string)
        - status_code  HTTP response status
        - org_id       Organisation UUID (from X-Organisation-ID header)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Only track API paths
        path = request.path
        if not path.startswith("/api/"):
            return response

        # Skip noisy / internal paths
        for prefix in _SKIP_PREFIXES:
            if path.startswith(prefix):
                return response

        # Only track authenticated users
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return response

        ph = _client()
        if ph is None:
            return response

        try:
            org_id = request.headers.get("X-Organisation-ID", "") or request.GET.get("org", "")
            ph.capture(
                str(user.id),
                event="api_request",
                properties={
                    "method": request.method,
                    "path": path,
                    "status_code": response.status_code,
                    "org_id": org_id or None,
                },
            )
        except Exception:
            # Never let analytics errors affect the response
            logger.debug("PostHog capture failed", exc_info=True)

        return response
