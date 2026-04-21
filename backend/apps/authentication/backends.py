"""
Custom JWT authentication backend.

Extends simplejwt's JWTAuthentication to validate the `token_version`
claim embedded at login time.  When a user changes their password,
`token_version` is incremented, making all previously issued tokens
(which carry the old version number) permanently invalid.
"""

from django.contrib.auth import get_user_model
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

User = get_user_model()


class VersionedJWTAuthentication(JWTAuthentication):
    """
    Reject tokens whose `token_version` claim no longer matches the
    current value stored on the User record.
    """

    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        # Tokens without the claim were issued before this feature; treat as version 0.
        # They stay valid until the user changes their password (which sets version ≥ 1).
        token_version = validated_token.get("token_version", 0)
        if token_version != user.token_version:
            raise InvalidToken("Token has been invalidated. Please log in again.")
        return user
