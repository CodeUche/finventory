"""Production settings - hardened security, performance-tuned."""

from decouple import config as _config

from .base import *  # noqa: F401, F403

# ── Fail-fast production guards ───────────────────────────────────────────────
# These checks run at import time (Django startup). The server refuses to start
# if any critical security value is missing or left at its placeholder default.
_PLACEHOLDER_PREFIXES = ("CHANGE_ME", "change-me", "your-secret", "generate_with")

def _check_required(name: str, value: str, min_length: int = 20) -> None:
    """Raise ImproperlyConfigured with a clear message if a secret is unsafe."""
    from django.core.exceptions import ImproperlyConfigured
    if not value or len(value) < min_length:
        raise ImproperlyConfigured(
            f"[PRODUCTION] {name} is not set or too short (minimum {min_length} chars). "
            "Set a strong random value in the server .env file and restart."
        )
    if any(value.startswith(p) for p in _PLACEHOLDER_PREFIXES):
        raise ImproperlyConfigured(
            f"[PRODUCTION] {name} still contains a placeholder value ('{value[:20]}...'). "
            "Generate a real secret and set it in the server .env file."
        )

_secret_key = _config("SECRET_KEY", default="")
_db_password = _config("DB_PASSWORD", default="")
_admin_url   = _config("ADMIN_URL",   default="admin/")

_check_required("SECRET_KEY", _secret_key, min_length=40)
_check_required("DB_PASSWORD", _db_password, min_length=12)

if _db_password.lower() in ("postgres", "password", "123456", "admin"):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        "[PRODUCTION] DB_PASSWORD is a well-known default. "
        "Use a strong random password in the server .env file."
    )

if _admin_url in ("admin/", "admin"):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        "[PRODUCTION] ADMIN_URL is still the default 'admin/'. "
        "Generate a random path: python -c \"import secrets; print(secrets.token_hex(8) + '/')\""
        " and set ADMIN_URL in the server .env file."
    )

if _config("DEBUG", default=False, cast=bool):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured(
        "[PRODUCTION] DEBUG=True is set in the environment. "
        "Set DEBUG=False (or remove it entirely) in the server .env file."
    )
# ─────────────────────────────────────────────────────────────────────────────

DEBUG = False

# Security headers
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Whitenoise for static files
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")  # noqa: F405
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Sentry error tracking
import sentry_sdk  # noqa: E402
from decouple import config  # noqa: E402

SENTRY_DSN = config("SENTRY_DSN", default="")
if SENTRY_DSN:
    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.1)

# Email
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("EMAIL_HOST", default="smtp.sendgrid.net")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@finventory.app")
