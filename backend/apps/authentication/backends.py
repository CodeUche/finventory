"""
Custom JWT authentication backend.

Extends simplejwt's JWTAuthentication to catch database errors during user
lookup and return a clean AuthenticationFailed instead of a raw 500.
"""

import logging

from django.contrib.auth import get_user_model
from django.db import DatabaseError, OperationalError, ProgrammingError
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

logger = logging.getLogger(__name__)

User = get_user_model()


class VersionedJWTAuthentication(JWTAuthentication):
    """
    Wraps super().get_user() to catch DB errors (e.g. unapplied migration)
    and raise AuthenticationFailed instead of propagating a raw 500.
    """

    def get_user(self, validated_token):
        try:
            return super().get_user(validated_token)
        except (ProgrammingError, OperationalError, DatabaseError) as db_err:
            logger.error(
                "VersionedJWTAuthentication DB error fetching user: %s — "
                "run 'python manage.py migrate' to apply pending migrations.", db_err
            )
            raise AuthenticationFailed(
                "Authentication service temporarily unavailable. Please try again."
            )
