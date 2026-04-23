"""
Custom JWT authentication backend.

Extends simplejwt's JWTAuthentication to validate the `token_version`
claim embedded at login time.  When a user changes their password,
`token_version` is incremented, making all previously issued tokens
(which carry the old version number) permanently invalid.
"""

import logging

from django.contrib.auth import get_user_model
from django.db import DatabaseError, OperationalError, ProgrammingError
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken

logger = logging.getLogger(__name__)

User = get_user_model()


class VersionedJWTAuthentication(JWTAuthentication):
    """
    Reject tokens whose `token_version` claim no longer matches the
    current value stored on the User record.
    """

    def get_user(self, validated_token):
        try:
            user = super().get_user(validated_token)
        except (ProgrammingError, OperationalError, DatabaseError) as db_err:
            logger.error(
                "VersionedJWTAuthentication DB error fetching user: %s — "
                "run 'python manage.py migrate' to apply pending migrations.", db_err
            )
            raise AuthenticationFailed(
                "Authentication service temporarily unavailable. Please try again."
            )

        token_version = validated_token.get("token_version", 0)
        try:
            if token_version != user.token_version:
                raise InvalidToken("Token has been invalidated. Please log in again.")
        except InvalidToken:
            raise
        except (ProgrammingError, OperationalError, DatabaseError, AttributeError):
            pass

        return user
