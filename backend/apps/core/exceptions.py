"""
Custom exception handling.

Wraps all DRF exceptions into a consistent JSON envelope:
{
    "error": {
        "code": "validation_error",
        "message": "Human-readable summary",
        "detail": <DRF detail>
    }
}

This prevents leaking internal stack traces and gives frontend
developers a predictable error shape.
"""

import logging

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)

# Map exception types to error codes for programmatic handling
EXCEPTION_CODE_MAP = {
    ValidationError: "validation_error",
    AuthenticationFailed: "authentication_failed",
    NotAuthenticated: "not_authenticated",
    PermissionDenied: "permission_denied",
    Http404: "not_found",
}


def custom_exception_handler(exc, context):
    """
    Global DRF exception handler.

    Returns structured error responses.
    Logs 5xx errors for monitoring.
    """
    # Let DRF build the initial response
    response = exception_handler(exc, context)

    if response is None:
        # Unhandled exception → 500
        logger.exception("Unhandled exception in view %s", context.get("view"))
        return Response(
            {
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred. Please try again later.",
                    "detail": None,
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    error_code = EXCEPTION_CODE_MAP.get(type(exc), "error")
    message = str(exc.detail) if hasattr(exc, "detail") else str(exc)

    response.data = {
        "error": {
            "code": error_code,
            "message": message,
            "detail": response.data,
        }
    }

    return response


class BusinessLogicError(APIException):
    """Raise for domain rule violations (e.g., credit limit exceeded)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "business_logic_error"

    def __init__(self, detail=None, code=None):
        super().__init__(detail=detail, code=code or self.default_code)


class TenantViolationError(APIException):
    """Raise when a cross-tenant data access is detected."""

    status_code = status.HTTP_403_FORBIDDEN
    default_code = "tenant_violation"
    default_detail = "You do not have permission to access this resource."


class SubscriptionRequiredError(APIException):
    """Raise when a feature requires a higher subscription plan."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "subscription_required"
    default_detail = "Please upgrade your subscription to access this feature."
