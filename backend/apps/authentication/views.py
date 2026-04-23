"""Authentication views: register, login, logout, profile, email verification, MFA."""

import base64
import io
import logging
import os
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from django.contrib.auth import authenticate as django_authenticate
from apps.core.throttles import (
    CheckVerificationRateThrottle,
    LoginRateThrottle,
    MFAVerifyRateThrottle,
    PasswordChangeRateThrottle,
    PasswordResetConfirmRateThrottle,
    PasswordResetRequestRateThrottle,
    PingRateThrottle,
    RegisterRateThrottle,
    ResendVerificationRateThrottle,
    TokenRefreshRateThrottle,
)
from apps.core.utils import get_client_ip

from .models import PasswordResetOTP
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
VERIFICATION_MAX_AGE = 900         # 15 minutes
MFA_CHALLENGE_MAX_AGE = 300        # 5 minutes


def _issue_tokens(user):
    """Return {access, refresh} JWT strings for a user."""
    refresh = RefreshToken.for_user(user)
    refresh["token_version"] = user.token_version
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def _send_verification_email(user, request=None):
    """Sign the user's PK and email a time-limited verification link.

    The link points directly to the Django backend endpoint which returns
    a styled HTML page — works for desktop/mobile apps with no hosted frontend.
    """
    token = TimestampSigner().sign(str(user.pk))
    if request is not None:
        link = request.build_absolute_uri(f"/api/v1/auth/verify-email/?token={token}")
    else:
        backend_url = getattr(settings, "BACKEND_URL", "http://localhost:8000")
        link = f"{backend_url}/api/v1/auth/verify-email/?token={token}"
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "info@auditytechnologies.com")
    name = user.first_name or user.email
    plain = (
        f"Hi {name},\n\n"
        f"Click the link below to verify your Audity email address.\n"
        f"This link expires in 15 minutes.\n\n"
        f"{link}\n\n"
        f"If you didn't create an Audity account you can safely ignore this email.\n\n"
        f"— The Audity Team"
    )
    html = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;background:#f8fafc;margin:0;padding:32px;">
<div style="max-width:520px;margin:auto;background:#fff;border-radius:8px;padding:40px;box-shadow:0 2px 8px rgba(0,0,0,.08);">
  <h2 style="color:#1e293b;margin-top:0;">Verify your Audity account</h2>
  <p style="color:#475569;">Hi {name},</p>
  <p style="color:#475569;">Click the button below to verify your email address. This link expires in <strong>15 minutes</strong>.</p>
  <div style="text-align:center;margin:32px 0;">
    <a href="{link}" style="background:#6366f1;color:#fff;padding:14px 32px;border-radius:6px;text-decoration:none;font-weight:bold;display:inline-block;">Verify Email Address</a>
  </div>
  <p style="color:#94a3b8;font-size:13px;">If the button doesn't work, copy and paste this link into your browser:<br>
    <a href="{link}" style="color:#6366f1;word-break:break-all;">{link}</a>
  </p>
  <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;">
  <p style="color:#94a3b8;font-size:12px;">If you didn't create an Audity account you can safely ignore this email.</p>
</div>
</body></html>"""
    try:
        msg = EmailMultiAlternatives(
            subject="Verify your Audity account",
            body=plain,
            from_email=from_email,
            to=[user.email],
        )
        msg.attach_alternative(html, "text/html")
        msg.send(fail_silently=False)
    except Exception as e:
        logger.error("Failed to send verification email to %s: %s", user.email, e)
        raise


class RegisterView(APIView):
    """
    POST /api/v1/auth/register/

    Creates a new user and sends a verification email.
    The user must verify their email before they can log in.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [RegisterRateThrottle]

    def post(self, request):
        email = (request.data.get("email") or "").lower().strip()
        # Guard: reject immediately if a verified or active user already owns this email.
        # Only orphaned (unverified, no memberships) accounts are cleaned up to allow
        # the same person to retry a failed registration attempt.
        if email:
            try:
                existing = User.objects.get(email=email)
                has_orgs = existing.memberships.filter(is_active=True).exists()
                if existing.is_verified or has_orgs:
                    # Real account — do NOT delete, return clear error
                    return Response(
                        {"error": {"code": "email_taken", "message": "An account with this email address already exists. Please sign in or use a different email."}},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                # Orphaned unverified account with no orgs — safe to purge so the
                # user can retry registration (e.g. after a failed email delivery).
                existing.delete()
                logger.info("Deleted orphaned unverified user %s to allow re-registration", email)
            except User.DoesNotExist:
                pass

        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()  # is_verified=False by default

        # Store referral code on user for post-verification linking
        referral_code = (request.data.get("referral_code") or "").strip().upper()
        if referral_code:
            user.referred_by_code = referral_code
            user.save(update_fields=["referred_by_code"])

        try:
            _send_verification_email(user, request)
        except Exception:
            # Email failed — delete the user so they can retry later
            user.delete()
            return Response(
                {"error": {"code": "email_failed", "message": "Could not send verification email. Please try again."}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Issue a short-lived polling token tied to this registration session.
        # check-verification requires this token — prevents unauthenticated callers
        # from receiving JWT tokens for arbitrary verified users (CRIT-01).
        polling_token = TimestampSigner().sign(str(user.pk))

        logger.info("New user registered (pending verification): %s from %s", user.email, get_client_ip(request))
        return Response(
            {
                "message": "Account created! Check your email to verify your address before signing in.",
                "polling_token": polling_token,
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyEmailView(APIView):
    """
    GET /api/v1/auth/verify-email/?token=<signed_token>

    Verifies a signed email token (15-minute expiry). Sets is_verified=True
    and returns JWT tokens so the user is logged in immediately.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        token = request.query_params.get("token", "")

        def _html(title, heading, body_html, success=True):
            color = "#16a34a" if success else "#dc2626"
            icon = "✅" if success else "❌"
            return HttpResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — Audity</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         background:#0f172a;color:#e2e8f0;min-height:100vh;
         display:flex;align-items:center;justify-content:center;padding:24px}}
    .card{{background:#1e293b;border:1px solid #334155;border-radius:16px;
           padding:48px 40px;max-width:480px;width:100%;text-align:center;
           box-shadow:0 25px 50px rgba(0,0,0,.5)}}
    .logo{{font-size:22px;font-weight:700;color:#38bdf8;margin-bottom:32px;
           letter-spacing:-.5px}}
    .icon{{font-size:56px;margin-bottom:20px}}
    h1{{font-size:24px;font-weight:700;color:{color};margin-bottom:12px}}
    p{{color:#94a3b8;line-height:1.6;margin-bottom:8px}}
    .hint{{margin-top:28px;padding:16px;background:#0f172a;border-radius:10px;
           font-size:14px;color:#64748b}}
    .hint strong{{color:#94a3b8}}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">Audity</div>
    <div class="icon">{icon}</div>
    <h1>{heading}</h1>
    {body_html}
    <div class="hint"><strong>What's next?</strong><br>Open the Audity desktop app and log in with your email and password.</div>
  </div>
</body>
</html>""", content_type="text/html")

        if not token:
            return _html("Error", "Missing Token",
                         "<p>No verification token was provided.</p>", success=False)

        try:
            user_pk = TimestampSigner().unsign(token, max_age=VERIFICATION_MAX_AGE)
        except SignatureExpired:
            return _html("Link Expired", "Verification Link Expired",
                         "<p>This link has expired (valid for 15 minutes).</p>"
                         "<p>Open Audity and use <strong>Resend verification email</strong> to get a new link.</p>",
                         success=False)
        except BadSignature:
            return _html("Invalid Link", "Invalid Verification Link",
                         "<p>This link is invalid or has already been used.</p>", success=False)

        try:
            user = User.objects.get(pk=user_pk)
        except User.DoesNotExist:
            return _html("Invalid Link", "Invalid Verification Link",
                         "<p>This link is invalid.</p>", success=False)

        if not user.is_verified:
            user.is_verified = True
            user.save(update_fields=["is_verified"])
            logger.info("Email verified for user: %s", user.email)

        return _html(
            "Email Verified",
            "Email Verified!",
            f"<p>Your account for <strong>{user.email}</strong> is now active.</p>"
            f"<p style='margin-top:12px;'>The Audity app will automatically take you to the next step.</p>"
            f"<p style='margin-top:8px;font-size:13px;color:#64748b;'>You can close this browser tab and return to Audity.</p>"
            f"<script>setTimeout(function(){{window.close();}}, 4000);</script>",
        )


class ResendVerificationView(APIView):
    """
    POST /api/v1/auth/resend-verification/
    Body: { "email": "..." }

    Resends the verification email. Always returns 200 to avoid email enumeration.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ResendVerificationRateThrottle]

    def post(self, request):
        email = (request.data.get("email") or "").lower().strip()
        try:
            user = User.objects.get(email=email, is_active=True, is_verified=False)
            _send_verification_email(user, request)
            logger.info("Verification email resent to: %s", email)
        except User.DoesNotExist:
            pass  # Don't reveal whether the email exists or is already verified
        except Exception as e:
            logger.error("Failed to resend verification email to %s: %s", email, e)

        return Response({"message": "If that email is registered and unverified, a new verification link has been sent."})


class CheckVerificationView(APIView):
    """
    POST /api/v1/auth/check-verification/
    Body: { "email": "user@example.com" }

    Lightweight polling endpoint for the "Check your email" screen.
    The app calls this every 5 seconds; when is_verified flips to True
    (user clicked the email link), we issue fresh JWTs so the app can
    log the user in immediately without requiring manual sign-in.

    Returns consistent shape to avoid email enumeration timing attacks.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [CheckVerificationRateThrottle]

    def post(self, request):
        email = (request.data.get("email") or "").lower().strip()
        polling_token = request.data.get("polling_token", "")

        if not email:
            return Response({"verified": False})

        # Require a valid polling token issued at registration time.
        # Without this, any caller who knows a victim's email could receive
        # their JWT tokens (CRIT-01 auth bypass).
        if not polling_token:
            return Response(
                {"error": {"code": "missing_polling_token", "message": "polling_token is required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verify the token and extract the user PK (max 30 min — enough to check email)
        try:
            token_pk = TimestampSigner().unsign(polling_token, max_age=1800)
        except SignatureExpired:
            return Response(
                {"error": {"code": "polling_token_expired", "message": "Registration session expired. Please register again."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except BadSignature:
            return Response(
                {"error": {"code": "invalid_polling_token", "message": "Invalid polling token."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            return Response({"verified": False})

        # Ensure the token belongs to the same user as the email
        if str(user.pk) != str(token_pk):
            return Response(
                {"error": {"code": "invalid_polling_token", "message": "Invalid polling token."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not user.is_verified:
            return Response({"verified": False})

        # Verified — issue tokens so the app can auto-login
        tokens = _issue_tokens(user)
        return Response({
            "verified": True,
            "user": UserProfileSerializer(user, context={"request": request}).data,
            "tokens": tokens,
        })


class LoginView(TokenObtainPairView):
    """
    POST /api/v1/auth/login/

    Returns access + refresh JWT with embedded tenant/role claims.
    - Enforces email verification (HTTP 403 with code=email_not_verified)
    - Enforces account lockout after MAX_LOGIN_ATTEMPTS failures.
    - If MFA is enabled, returns mfa_required=true with a short-lived challenge token.
    - Tracks last login IP for security auditing.
    """

    authentication_classes = []   # stale Bearer tokens must not block login
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [LoginRateThrottle]

    def post(self, request, *args, **kwargs):
        email = request.data.get("email", "").lower().strip()
        ip = get_client_ip(request)

        # Phase 1: check lockout BEFORE attempting authentication
        # Use a generic message to avoid confirming that an account exists
        # (prevents email enumeration via lockout response timing/content).
        try:
            user = User.objects.get(email=email)
            if user.is_locked:
                logger.warning("Blocked locked login attempt: %s from %s", email, ip)
                return Response(
                    {
                        "error": {
                            "code": "account_locked",
                            "message": "Too many failed attempts. Please try again in 30 minutes.",
                        }
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
        except User.DoesNotExist:
            pass  # Unknown email — let super() return the standard 401
        except Exception as _phase1_err:
            # Catch DB-level errors (e.g. missing column from unapplied migration).
            # Log and skip the lockout check — Phase 2 authentication will fail
            # with the correct error if credentials are wrong.
            logger.error("Phase-1 user lookup failed for %s: %s", email, _phase1_err)

        # Phase 2: attempt authentication via SimpleJWT
        auth_exception = None
        try:
            response = super().post(request, *args, **kwargs)
        except Exception as exc:
            auth_exception = exc
            response = None

        auth_succeeded = response is not None and response.status_code == 200

        # Phase 3: post-auth bookkeeping
        try:
            user = User.objects.get(email=email)
            if auth_succeeded:
                # Clear failure counter first
                user.last_login_ip = ip
                user.failed_login_attempts = 0
                user.locked_until = None
                user.save(update_fields=["last_login_ip", "failed_login_attempts", "locked_until"])
                logger.info("User authenticated: %s from %s", email, ip)

                # Block unverified users — they must click the email link
                if not user.is_verified:
                    logger.warning("Blocked unverified login: %s", email)
                    return Response(
                        {
                            "error": {
                                "code": "email_not_verified",
                                "message": "Please verify your email address before signing in.",
                            }
                        },
                        status=status.HTTP_403_FORBIDDEN,
                    )

                # Block sub-accounts — they must use /auth/staff-login/
                if user.is_sub_account:
                    return Response(
                        {"error": {"code": "use_staff_login", "message": "Team member accounts must sign in using the staff login page."}},
                        status=status.HTTP_403_FORBIDDEN,
                    )

                # If MFA is enabled, issue a short-lived challenge token instead of JWT
                if user.mfa_enabled:
                    mfa_token = TimestampSigner().sign(str(user.pk))
                    logger.info("MFA challenge issued for: %s", email)
                    return Response({"mfa_required": True, "mfa_token": mfa_token})

                # Normal login — attach full user profile
                response.data["user"] = UserProfileSerializer(user).data
                try:
                    from apps.core.models import AuditLog as _AL
                    _AL.log(
                        action=_AL.LOGIN,
                        user=user,
                        organisation=None,
                        model_name='User',
                        object_id=str(user.id),
                        object_repr=user.email,
                        request=request,
                    )
                except Exception:
                    pass
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
        except Exception as _phase3_err:
            logger.error("Phase-3 bookkeeping failed for %s: %s", email, _phase3_err)

        if auth_exception is not None:
            if isinstance(auth_exception, APIException):
                # DRF exception (wrong credentials, invalid token, etc.) — re-raise
                # so the standard exception handler converts it to a proper 401/403.
                raise auth_exception
            # Non-DRF exception: DB schema error (missing column from unapplied
            # migration), network failure, import error, etc.  Returning a raw 500
            # shows users a confusing "unexpected error" message.  Return 503 so
            # the client retries and Railway logs show the real stacktrace.
            logger.error(
                "Authentication system error for %s: %s",
                email, auth_exception, exc_info=True,
            )
            return Response(
                {
                    "error": {
                        "code": "auth_unavailable",
                        "message": (
                            "Authentication is temporarily unavailable. "
                            "Please try again in a moment."
                        ),
                    }
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return response


# ─── MFA Views ────────────────────────────────────────────────────────────────

def _generate_backup_codes():
    """Generate 8 random one-time backup codes."""
    return [os.urandom(5).hex() for _ in range(8)]


def _hash_code(code: str) -> str:
    from django.contrib.auth.hashers import make_password
    return make_password(code, salt="audity-backup", hasher="pbkdf2_sha256")


def _check_code(plain: str, stored_hash: str) -> bool:
    from django.contrib.auth.hashers import check_password
    return check_password(plain, stored_hash)


class MFASetupView(APIView):
    """
    POST /api/v1/auth/mfa/setup/

    Generates a TOTP secret and returns a QR code data URL.
    The secret is stored as pending until confirmed.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        import pyotp
        import qrcode
        user = request.user
        secret = pyotp.random_base32()
        user.mfa_secret_pending = secret
        user.save(update_fields=["mfa_secret_pending"])

        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(
            name=user.email,
            issuer_name="Audity",
        )

        # Generate QR code as base64 PNG data URL
        qr = qrcode.QRCode(box_size=6, border=2)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

        return Response({"provisioning_uri": provisioning_uri, "qr_data_url": qr_data_url})


class MFAConfirmSetupView(APIView):
    """
    POST /api/v1/auth/mfa/confirm-setup/
    Body: { "code": "123456" }

    Confirms the TOTP setup by verifying the first code.
    Returns one-time backup codes (shown only once).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        import pyotp
        user = request.user
        code = str(request.data.get("code", "")).strip()

        if not user.mfa_secret_pending:
            return Response(
                {"error": {"code": "no_pending_setup", "message": "No pending MFA setup. Please start setup first."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        totp = pyotp.TOTP(user.mfa_secret_pending)
        if not totp.verify(code, valid_window=1):
            return Response(
                {"error": {"code": "invalid_code", "message": "Invalid authenticator code. Please try again."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Generate backup codes
        plain_codes = _generate_backup_codes()
        hashed_codes = [_hash_code(c) for c in plain_codes]

        user.mfa_secret = user.mfa_secret_pending
        user.mfa_secret_pending = ""
        user.mfa_enabled = True
        user.mfa_backup_codes = hashed_codes
        user.save(update_fields=["mfa_secret", "mfa_secret_pending", "mfa_enabled", "mfa_backup_codes"])

        logger.info("MFA enabled for user: %s", user.email)
        # Backup codes are returned ONCE at enable-time over HTTPS.
        # They are never stored in plain text — only hashed copies are kept.
        # The frontend must prompt the user to save these immediately.
        return Response({
            "message": "MFA enabled successfully. Save your backup codes — they will not be shown again.",
            "backup_codes": plain_codes,
            "backup_codes_warning": "Store these codes in a safe place. Each can only be used once.",
        })


class MFAVerifyView(APIView):
    """
    POST /api/v1/auth/mfa/verify/
    Body: { "mfa_token": "...", "code": "123456" }

    Completes MFA login. Verifies the TOTP code (or a backup code)
    and returns full JWT tokens.
    """
    # No authentication_classes: a stale Bearer token in the request header
    # must NOT cause DRF to reject this endpoint before the view runs.
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [MFAVerifyRateThrottle]

    def post(self, request):
        import pyotp
        mfa_token = request.data.get("mfa_token", "")
        code = str(request.data.get("code", "")).strip()

        if not mfa_token or not code:
            return Response(
                {"error": {"code": "missing_fields", "message": "mfa_token and code are required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user_pk = TimestampSigner().unsign(mfa_token, max_age=MFA_CHALLENGE_MAX_AGE)
        except SignatureExpired:
            return Response(
                {"error": {"code": "token_expired", "message": "MFA session expired. Please log in again."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except BadSignature:
            return Response(
                {"error": {"code": "invalid_token", "message": "Invalid MFA token."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(pk=user_pk, is_active=True)
        except User.DoesNotExist:
            return Response(
                {"error": {"code": "invalid_token", "message": "Invalid MFA token."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Try TOTP first
        totp = pyotp.TOTP(user.mfa_secret)
        if totp.verify(code, valid_window=1):
            logger.info("MFA TOTP verified for: %s", user.email)
            return Response({
                "user": UserProfileSerializer(user).data,
                "tokens": _issue_tokens(user),
            })

        # Try backup codes — locked transaction prevents two simultaneous requests
        # from consuming the same code (race condition / replay).
        from django.db import transaction as _tx
        with _tx.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)
            backup_codes = list(user.mfa_backup_codes or [])
            for stored_hash in backup_codes:
                if _check_code(code, stored_hash):
                    backup_codes.remove(stored_hash)
                    user.mfa_backup_codes = backup_codes
                    user.save(update_fields=["mfa_backup_codes"])
                    logger.info("MFA backup code used for: %s (%d remaining)", user.email, len(backup_codes))
                    return Response({
                        "user": UserProfileSerializer(user).data,
                        "tokens": _issue_tokens(user),
                        "backup_code_used": True,
                        "backup_codes_remaining": len(backup_codes),
                    })

        return Response(
            {"error": {"code": "invalid_code", "message": "Invalid authenticator code."}},
            status=status.HTTP_400_BAD_REQUEST,
        )


class PingView(APIView):
    """Lightweight connectivity probe used by the Tauri offline-detection probe."""
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PingRateThrottle]

    def get(self, _request):
        return Response({"ok": True})


class MFADisableView(APIView):
    """
    POST /api/v1/auth/mfa/disable/
    Body: { "code": "123456" }

    Disables MFA after verifying the current TOTP code (or a backup code).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        import pyotp
        user = request.user
        code = str(request.data.get("code", "")).strip()
        current_password = str(request.data.get("current_password", "")).strip()

        if not user.mfa_enabled:
            return Response(
                {"error": {"code": "mfa_not_enabled", "message": "MFA is not currently enabled."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Require current password as first factor before disabling second factor
        if not current_password or not user.check_password(current_password):
            return Response(
                {"error": {"code": "invalid_password", "message": "Current password is required to disable MFA."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verify TOTP or backup code before disabling
        totp = pyotp.TOTP(user.mfa_secret)
        backup_codes = list(user.mfa_backup_codes or [])
        valid = totp.verify(code, valid_window=1) or any(
            _check_code(code, h) for h in backup_codes
        )

        if not valid:
            return Response(
                {"error": {"code": "invalid_code", "message": "Invalid authenticator code."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.mfa_enabled = False
        user.mfa_secret = ""
        user.mfa_secret_pending = ""
        user.mfa_backup_codes = []
        user.save(update_fields=["mfa_enabled", "mfa_secret", "mfa_secret_pending", "mfa_backup_codes"])
        logger.info("MFA disabled for user: %s", user.email)
        return Response({"message": "MFA disabled successfully."})


# ─── Standard views (unchanged) ───────────────────────────────────────────────

class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/

    Blacklists the refresh token, effectively invalidating the session.
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
        try:
            from apps.core.models import AuditLog as _AL
            _AL.log(
                action=_AL.LOGOUT,
                user=request.user,
                organisation=None,
                model_name='User',
                object_id=str(request.user.id),
                object_repr=request.user.email,
                request=request,
            )
        except Exception:
            pass
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


class UploadAvatarView(APIView):
    """
    POST /api/v1/auth/upload_avatar/
    Body: raw image binary.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.core.files.base import ContentFile
        from apps.core.validators import sniff_image_bytes

        _MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB
        body = request.body
        if not body:
            return Response({"error": {"message": "No file data received."}}, status=status.HTTP_400_BAD_REQUEST)
        if len(body) > _MAX_AVATAR_BYTES:
            return Response({"error": {"message": "File too large. Maximum size is 5 MB."}}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        detected_mime = sniff_image_bytes(body[:261])
        if detected_mime is None:
            return Response({"error": {"message": "File is not a valid image."}}, status=status.HTTP_400_BAD_REQUEST)
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(detected_mime, ".jpg")
        user = request.user
        if user.avatar:
            user.avatar.delete(save=False)
        user.avatar.save(f"avatar_{user.id}{ext}", ContentFile(body), save=True)
        return Response(UserProfileSerializer(user).data)


class ChangePasswordView(APIView):
    """POST /api/v1/auth/change-password/"""

    permission_classes = [IsAuthenticated]
    throttle_classes = [PasswordChangeRateThrottle]

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
        user.token_version = (user.token_version or 0) + 1
        update_fields = ["password", "token_version"]
        if user.must_change_password:
            user.must_change_password = False
            update_fields.append("must_change_password")
        user.save(update_fields=update_fields)

        logger.info("Password changed for user: %s", user.email)
        return Response({"message": "Password changed successfully. Please log in again."})


class TokenRefreshCustomView(TokenRefreshView):
    """POST /api/v1/auth/token/refresh/ — Standard JWT refresh."""
    throttle_classes = [TokenRefreshRateThrottle]


class PasswordResetRequestView(APIView):
    """
    POST /api/v1/auth/password-reset/
    Body: { "email": "user@example.com" }
    """

    authentication_classes = []   # expired tokens must not block this public endpoint
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetRequestRateThrottle]

    def post(self, request):
        email = request.data.get("email", "").lower().strip()
        _DUMMY_HASH = 'pbkdf2_sha256$870000$audity_dummy_reset$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='
        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            # Constant-time dummy work so response time doesn't reveal whether email exists
            from django.contrib.auth.hashers import check_password as _cp
            _cp('x', _DUMMY_HASH)
            return Response({"message": "If that email is registered, a reset code has been sent."})

        code = PasswordResetOTP.generate(user)
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@auditytechnologies.com")

        try:
            plain = (
                f"Hi {user.first_name},\n\n"
                f"Your password reset code is: {code}\n\n"
                f"This code expires in 15 minutes. If you didn't request a reset, "
                f"you can safely ignore this email.\n\n"
                f"— The Audity Team"
            )
            html = (
                f"<p>Hi {user.first_name},</p>"
                f"<p>Your password reset code is: <strong style='font-size:24px;letter-spacing:4px'>{code}</strong></p>"
                f"<p>This code expires in <strong>15 minutes</strong>. "
                f"If you didn't request a reset, you can safely ignore this email.</p>"
                f"<p>— The Audity Team</p>"
            )
            msg = EmailMultiAlternatives(
                subject="Your Audity password reset code",
                body=plain,
                from_email=from_email,
                to=[user.email],
            )
            msg.attach_alternative(html, "text/html")
            msg.send(fail_silently=False)
        except Exception as e:
            logger.error("Failed to send password reset email to %s: %s", email, e)
            return Response(
                {"error": {"code": "email_failed", "message": "Could not send reset email. Please try again."}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        logger.info("Password reset OTP sent to: %s", email)
        return Response({"message": "If that email is registered, a reset code has been sent."})


class PasswordResetConfirmView(APIView):
    """
    POST /api/v1/auth/password-reset/confirm/
    Body: { "email": "...", "code": "123456", "new_password": "...", "confirm_password": "..." }
    """

    authentication_classes = []   # expired tokens must not block this public endpoint
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetConfirmRateThrottle]

    def post(self, request):
        email = request.data.get("email", "").lower().strip()
        code = str(request.data.get("code", "")).strip()
        new_password = request.data.get("new_password", "")
        confirm_password = request.data.get("confirm_password", "")

        if not all([email, code, new_password, confirm_password]):
            return Response(
                {"error": {"code": "missing_fields", "message": "All fields are required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_password != confirm_password:
            return Response(
                {"error": {"code": "password_mismatch", "message": "Passwords do not match."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(new_password) < 10:
            return Response(
                {"error": {"code": "password_too_short", "message": "Password must be at least 10 characters."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            return Response(
                {"error": {"code": "invalid_code", "message": "Invalid or expired reset code."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp = (
            PasswordResetOTP.objects.filter(user=user, used=False)
            .order_by("-created_at")
            .first()
        )

        if not otp or not otp.verify(code):
            return Response(
                {"error": {"code": "invalid_code", "message": "Invalid or expired reset code."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp.used = True
        otp.save(update_fields=["used"])

        user.set_password(new_password)
        user.token_version = (user.token_version or 0) + 1
        user.failed_login_attempts = 0
        user.locked_until = None
        user.save(update_fields=["password", "token_version", "failed_login_attempts", "locked_until"])

        logger.info("Password reset successful for: %s", email)
        return Response({"message": "Password reset successfully. You can now log in."})


class SubAccountLoginView(APIView):
    """
    POST /api/v1/auth/staff-login/
    Body: { "username": "john", "org_slug": "acme-corp", "password": "..." }

    Dedicated login endpoint for sub-accounts (team members).

    Security:
      - Resolves email as username@org_slug — never exposes direct email lookup.
      - Generic error message prevents username/org enumeration.
      - Applies same lockout logic as main LoginView.
      - Verifies: user is_sub_account, membership is_active, org subscription not canceled.
      - Sub-accounts are pre-verified (no email check needed).
    """
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        from apps.tenancy.models import Membership

        username = (request.data.get("username") or "").strip().lower()
        org_slug = (request.data.get("org_slug") or "").strip().lower()
        password = request.data.get("password", "")
        ip = get_client_ip(request)

        if not username or not org_slug or not password:
            return Response(
                {"error": {"code": "invalid_credentials", "message": "Username, workspace, and password are required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate slug format to prevent injection.
        # Run a constant-time dummy hash even on format failure to prevent
        # timing-oracle attacks (invalid format fails fast; valid format hits
        # the DB — measurable difference reveals valid username/org pairs).
        import re
        if not re.match(r'^[a-z0-9\-]{1,100}$', org_slug) or not re.match(r'^[a-z0-9_\-\.]{1,100}$', username):
            from django.contrib.auth.hashers import check_password
            check_password(password, 'pbkdf2_sha256$870000$dummy$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')
            return Response(
                {"error": {"code": "invalid_credentials", "message": "Invalid username, workspace, or password."}},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        email = f"{username}@{org_slug}"
        # Generic denial — never reveals which field is wrong
        _deny = Response(
            {"error": {"code": "invalid_credentials", "message": "Invalid username, workspace, or password."}},
            status=status.HTTP_401_UNAUTHORIZED,
        )

        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            logger.warning("Staff login: unknown email %s from %s", email, ip)
            return _deny

        # Only sub-accounts may use this endpoint — owner tries → use main login
        if not user.is_sub_account:
            logger.warning("Non-sub-account tried staff login endpoint: %s from %s", email, ip)
            return _deny

        # Lockout check
        if user.is_locked:
            seconds_left = int((user.locked_until - timezone.now()).total_seconds())
            minutes_left = max(1, (seconds_left + 59) // 60)
            return Response(
                {"error": {"code": "account_locked", "message": f"Too many failed attempts. Account locked for {minutes_left} more minute(s)."}},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # Authenticate password
        auth_user = django_authenticate(request, username=email, password=password)
        if auth_user is None: 
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
                user.locked_until = timezone.now() + timedelta(minutes=LOCKOUT_MINUTES)
                logger.warning("Staff account locked after %d failures: %s from %s", user.failed_login_attempts, email, ip)
            user.save(update_fields=["failed_login_attempts", "locked_until"])
            return _deny

        # Clear failure counter
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_ip = ip
        user.save(update_fields=["failed_login_attempts", "locked_until", "last_login_ip"])

        # Find active membership
        memberships = Membership.objects.filter(
            user=user, is_active=True
        ).select_related("organisation__subscription").order_by("-created_at")

        if not memberships.exists():
            logger.warning("Staff login: no active membership for %s", email)
            return Response(
                {"error": {"code": "no_access", "message": "Your account has been deactivated. Contact your administrator."}},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Check parent org subscription — block if expired, canceled, or unpaid.
        # Uses the Subscription.is_active property which also checks period_end/trial_end
        # so sub-accounts are blocked the moment the owner's subscription lapses.
        org = memberships.first().organisation
        try:
            sub = org.subscription
            if sub is not None and not sub.is_active:  # type: ignore[union-attr]
                logger.warning("Staff login blocked — org subscription %s for %s", sub.status, email)  # type: ignore[union-attr]
                return Response(
                    {"error": {"code": "subscription_inactive", "message": "Your workspace subscription has expired or been canceled. Contact your administrator to renew access."}},
                    status=status.HTTP_403_FORBIDDEN,
                )
        except Exception:
            pass  # No subscription record = unrestricted (free/legacy)

        tokens = _issue_tokens(user)
        logger.info("Staff account authenticated: %s from %s", email, ip)

        return Response({
            "access": tokens["access"],
            "refresh": tokens["refresh"],
            "user": UserProfileSerializer(user).data,
        })
