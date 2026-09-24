"""
Custom DRF throttle classes for Audity endpoints.

All scopes are registered in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] in settings.

IP-based (AnonRateThrottle subclasses) — used for unauthenticated / public endpoints.
User-based (UserRateThrottle subclasses) — keyed per authenticated user ID.

Django's cache backend counts requests; in production this must be Redis so
limits are shared across multiple worker processes.
"""

from django.conf import settings
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


# ── Global authenticated catch-all ─────────────────────────────────────────────

class ThrottleExemptionMixin:
    """
    The "user" catch-all, with an allow-list of accounts that skip it.

    Exists for the E2E smoke account. A full suite run loads ~68 pages, each
    firing 30-40 API calls, which measured 2,594 requests in 8 minutes against
    a 3000/hour ceiling — so the suite throttled ITSELF and the affected tests
    failed as "the page didn't load", reading like application faults. Measured
    2026-09-24.

    Deliberately narrow: this exempts only the global per-user rate. Login,
    registration, password reset and every other named scope still apply to
    these accounts, so the brute-force and spam guards are untouched. The
    allow-list is env-driven and empty by default, so no deployment is exempt
    unless someone sets THROTTLE_EXEMPT_EMAILS explicitly.
    """

    def allow_request(self, request, view):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            email = (getattr(user, "email", "") or "").strip().lower()
            if email and email in getattr(settings, "THROTTLE_EXEMPT_EMAILS", frozenset()):
                return True
        return super().allow_request(request, view)


class ExemptibleUserRateThrottle(ThrottleExemptionMixin, UserRateThrottle):
    """The global "user" catch-all, honouring the allow-list."""


# ── Authentication endpoints ───────────────────────────────────────────────────

class LoginRateThrottle(AnonRateThrottle):
    """5 login attempts per minute per IP — brute-force protection."""
    scope = "login"


class RegisterRateThrottle(AnonRateThrottle):
    """3 registration attempts per hour per IP — prevents account-creation spam."""
    scope = "register"


class TokenRefreshRateThrottle(UserRateThrottle):
    """10 token refresh calls per minute per authenticated user."""
    scope = "token_refresh"


class PasswordChangeRateThrottle(UserRateThrottle):
    """3 password change attempts per hour per user."""
    scope = "password_change"


class PasswordResetRequestRateThrottle(AnonRateThrottle):
    """5 reset-code requests per hour per IP — prevents email flooding."""
    scope = "password_reset_request"


class PasswordResetConfirmRateThrottle(AnonRateThrottle):
    """10 reset confirmations per hour per IP — brute-force OTP protection."""
    scope = "password_reset_confirm"


class ResendVerificationRateThrottle(AnonRateThrottle):
    """3 resend-verification emails per hour per IP — prevents email flooding."""
    scope = "resend_verification"


class CheckVerificationRateThrottle(AnonRateThrottle):
    """30 verification status polls per minute per IP — allows polling every 2s."""
    scope = "check_verification"


class MFAVerifyRateThrottle(AnonRateThrottle):
    """10 MFA verify attempts per minute per IP — brute-force OTP protection."""
    scope = "mfa_verify"


class OfflineVerifierRateThrottle(UserRateThrottle):
    """
    5 offline-verifier issuances per hour per authenticated user.

    Issuance requires re-entering the account password, so this throttle is
    the brute-force guard for an attacker holding only a stolen access
    token — 5 guesses/hour makes online password guessing through this
    endpoint useless, mirroring the login lockout philosophy.
    """
    scope = "offline_verifier"


# ── Business endpoints ─────────────────────────────────────────────────────────

class BankResolveRateThrottle(UserRateThrottle):
    """
    20 Paystack bank-account resolve calls per minute per user.

    This endpoint proxies to Paystack's API, so we rate-limit it to prevent
    a single user exhausting the platform's Paystack quota.
    """
    scope = "bank_resolve"


class InvitationRateThrottle(UserRateThrottle):
    """
    10 invitation / subaccount-creation calls per hour per user.

    Prevents a compromised admin account from mass-creating team members.
    """
    scope = "invitation"


class WebhookRateThrottle(AnonRateThrottle):
    """
    300 webhook calls per minute per IP.

    High enough to absorb legitimate Paystack event bursts but blocks
    replay / flood attacks from a single source. Paystack retries on
    non-2xx so we always return 200 — the throttle is a silent drop.
    """
    scope = "webhook"


class PublicReadRateThrottle(AnonRateThrottle):
    """
    30 requests per minute per IP on public read-only endpoints
    (e.g., subscription plan listing).
    """
    scope = "public_read"


class PingRateThrottle(AnonRateThrottle):
    """120 pings per minute per IP — allows Tauri's 15s probe but blocks flood attacks."""
    scope = "ping"


class AISupportRateThrottle(AnonRateThrottle):
    """20 support chat messages per minute per IP — public support widget abuse guard."""
    scope = "ai_support"


class FinancialWriteThrottle(ThrottleExemptionMixin, UserRateThrottle):
    """
    60 financial write operations per minute per authenticated user.

    Applied to invoice creation, payment recording, expense creation, and bill
    payment. Prevents automated double-submit attacks while allowing normal
    business throughput (1 transaction/second is well within limits).
    """
    scope = "financial_write"
