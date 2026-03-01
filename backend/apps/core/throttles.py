"""
Custom DRF throttle classes for authentication endpoints.

Scopes are configured in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] in settings.
"""

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    """10 login attempts per minute per IP."""
    scope = "login"


class RegisterRateThrottle(AnonRateThrottle):
    """5 registration attempts per hour per IP."""
    scope = "register"


class TokenRefreshRateThrottle(UserRateThrottle):
    """20 token refresh calls per minute per user."""
    scope = "token_refresh"
