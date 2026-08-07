"""
API key authentication for the Zapier-compatible endpoints.

Deliberately resolves `request.organisation` FROM THE KEY ITSELF, never from
a client-supplied X-Organisation-ID header — that header is only trustworthy
under session/JWT auth where org membership was verified at login. An API
key must carry its own org identity or any caller could spoof the header to
read/write another org's data.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import OrganisationAPIKey

API_KEY_HEADER = "HTTP_X_API_KEY"
API_KEY_PREFIX_LEN = 12


class APIKeyUser:
    """
    Minimal stand-in for request.user under API-key auth — this scheme
    authenticates an ORGANISATION, not a human user, so there is no Django
    User object backing the request.
    """

    is_authenticated = True
    is_anonymous = False
    is_active = True

    def __init__(self, api_key: OrganisationAPIKey):
        self.api_key = api_key
        # DRF's UserRateThrottle reads request.user.pk to build a cache key —
        # use the API key's own id so per-key throttling works instead of
        # crashing with AttributeError.
        self.id = api_key.id
        self.pk = api_key.id

    def __str__(self):
        return f"APIKeyUser({self.api_key.key_prefix}…)"


class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    Expects header: X-API-Key: audk_xxxxxxxxxxxx...

    On success, sets request.organisation directly (bypassing the normal
    X-Organisation-ID / middleware resolution path entirely) so downstream
    views never need to know which auth scheme was used.
    """

    def authenticate(self, request):
        raw_key = request.META.get(API_KEY_HEADER, "").strip()
        if not raw_key:
            return None

        prefix = raw_key[:API_KEY_PREFIX_LEN]
        candidates = OrganisationAPIKey.objects.filter(key_prefix=prefix, is_active=True).select_related(
            "organisation"
        )

        matched = None
        for candidate in candidates:
            if candidate.check_key(raw_key):
                matched = candidate
                break

        if matched is None:
            raise exceptions.AuthenticationFailed("Invalid API key.")

        matched.last_used_at = timezone.now()
        matched.save(update_fields=["last_used_at", "updated_at"])

        # Set organisation directly from the key — ignore any X-Organisation-ID
        # header the client may have sent, by design.
        request.organisation = matched.organisation

        return (APIKeyUser(matched), matched)

    def authenticate_header(self, request):
        # Required so a failed/missing-key AuthenticationFailed maps to HTTP
        # 401 (not DRF's 403 fallback, which is what happens when no
        # authenticator on the request implements this method).
        return "X-API-Key"
