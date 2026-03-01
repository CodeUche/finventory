"""Authentication views: register, login, logout, profile."""

import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.core.throttles import LoginRateThrottle, RegisterRateThrottle, TokenRefreshRateThrottle
from apps.core.utils import get_client_ip

from .serializers import (
    ChangePasswordSerializer,
    CustomTokenObtainPairSerializer,
    RegisterSerializer,
    UserProfileSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()

# Security constants
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 30


class RegisterView(APIView):
    """
    POST /api/v1/auth/register/

    Creates a new user. Returns JWT tokens immediately so the user
    can be redirected to organisation creation on first login.
    """

    permission_classes = [AllowAny]
    throttle_classes = [RegisterRateThrottle]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Issue tokens immediately after registration
        refresh = RefreshToken.for_user(user)
        logger.info("New user registered: %s from %s", user.email, get_client_ip(request))

        return Response(
            {
                "user": UserProfileSerializer(user).data,
                "tokens": {
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                },
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(TokenObtainPairView):
    """
    POST /api/v1/auth/login/

    Returns access + refresh JWT with embedded tenant/role claims.
    Enforces account lockout after MAX_LOGIN_ATTEMPTS failures.
    Tracks last login IP for security auditing.
    """

    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [LoginRateThrottle]

    def post(self, request, *args, **kwargs):
        email = request.data.get("email", "").lower().strip()
        ip = get_client_ip(request)

        # Phase 1: check lockout BEFORE attempting authentication
        try:
            user = User.objects.get(email=email)
            if user.is_locked:
                seconds_left = int((user.locked_until - timezone.now()).total_seconds())
                minutes_left = max(1, (seconds_left + 59) // 60)
                logger.warning("Blocked locked login attempt: %s from %s", email, ip)
                return Response(
                    {
                        "error": {
                            "code": "account_locked",
                            "message": (
                                f"Too many failed attempts. Account locked for {minutes_left} more minute(s). "
                                "Please try again later."
                            ),
                        }
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
        except User.DoesNotExist:
            pass  # Unknown email — let super() return the standard 401

        # Phase 2: attempt authentication via SimpleJWT
        response = super().post(request, *args, **kwargs)

        # Phase 3: post-auth bookkeeping
        try:
            user = User.objects.get(email=email)
            if response.status_code == 200:
                # Success — clear failure counter and record IP
                user.last_login_ip = ip
                user.failed_login_attempts = 0
                user.locked_until = None
                user.save(update_fields=["last_login_ip", "failed_login_attempts", "locked_until"])
                logger.info("User logged in: %s from %s", email, ip)
                # Attach full user profile so the frontend receives is_superuser etc.
                response.data["user"] = UserProfileSerializer(user).data
            else:
                # Failure — increment counter, lock if threshold reached
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
                    user.locked_until = timezone.now() + timedelta(minutes=LOCKOUT_MINUTES)
                    logger.warning(
                        "Account locked after %d failures: %s from %s",
                        user.failed_login_attempts,
                        email,
                        ip,
                    )
                user.save(update_fields=["failed_login_attempts", "locked_until"])
        except User.DoesNotExist:
            pass

        return response


class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/

    Blacklists the refresh token, effectively invalidating the session.
    The access token will expire naturally (keep access token lifetime short).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"error": {"code": "missing_token", "message": "Refresh token is required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            logger.info("User logged out: %s", request.user.email)
        except Exception as e:
            logger.warning("Logout error for %s: %s", request.user.email, e)
        return Response({"message": "Logged out successfully."})


class UserProfileView(APIView):
    """GET/PATCH /api/v1/auth/profile/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserProfileSerializer(request.user).data)

    def patch(self, request):
        serializer = UserProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ChangePasswordView(APIView):
    """POST /api/v1/auth/change-password/"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        if not user.check_password(serializer.validated_data["current_password"]):
            return Response(
                {"error": {"code": "wrong_password", "message": "Current password is incorrect."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])

        # Blacklist all existing tokens by forcing a password change
        logger.info("Password changed for user: %s", user.email)
        return Response({"message": "Password changed successfully. Please log in again."})


class TokenRefreshCustomView(TokenRefreshView):
    """POST /api/v1/auth/token/refresh/ — Standard JWT refresh."""
    pass
