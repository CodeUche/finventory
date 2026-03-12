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

_secret_key   = _config("SECRET_KEY",   default="")
_db_password  = _config("DB_PASSWORD",  default="")
_database_url = _config("DATABASE_URL", default="")  # Railway / Render provide this directly
_admin_url    = _config("ADMIN_URL",    default="admin/")

_check_required("SECRET_KEY", _secret_key, min_length=40)

# DB_PASSWORD check is skipped when a full DATABASE_URL is provided (cloud platforms
# like Railway embed the password inside the URL automatically).
if not _database_url:
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

# ─── Media / User-upload file storage ────────────────────────────────────────
# In production, user-uploaded files (logos, letterheads, receipts) must be
# stored in object storage — not local disk — because cloud servers are
# ephemeral and local media/ would be wiped on every redeploy.
#
# We use django-storages with an S3-compatible backend (works with AWS S3,
# Cloudflare R2, DigitalOcean Spaces, Backblaze B2, etc.).
#
# Set USE_S3=True in .env to activate. All other S3_* vars are then required.
_use_s3 = config("USE_S3", default=False, cast=bool)
if _use_s3:
    # Required env vars when USE_S3=True
    AWS_ACCESS_KEY_ID = config("S3_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = config("S3_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = config("S3_BUCKET_NAME")
    AWS_S3_REGION_NAME = config("S3_REGION", default="auto")  # 'auto' works for Cloudflare R2
    # For non-AWS providers set the endpoint URL:
    #   Cloudflare R2:  https://<account_id>.r2.cloudflarestorage.com
    #   DigitalOcean:   https://<region>.digitaloceanspaces.com
    AWS_S3_ENDPOINT_URL = config("S3_ENDPOINT_URL", default="")  # leave blank for AWS S3
    AWS_S3_CUSTOM_DOMAIN = config("S3_CUSTOM_DOMAIN", default="")  # CDN domain (optional)
    AWS_DEFAULT_ACL = None          # Cloudflare R2 / private bucket — no public ACL
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=86400"}
    AWS_QUERYSTRING_AUTH = True     # Signed URLs — prevents direct public access
    AWS_QUERYSTRING_EXPIRE = 3600   # Signed URL TTL: 1 hour

    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"
    # Media files go under the media/ prefix in the bucket
    MEDIA_URL = (
        f"https://{AWS_S3_CUSTOM_DOMAIN}/media/"
        if AWS_S3_CUSTOM_DOMAIN
        else f"{AWS_S3_ENDPOINT_URL}/{AWS_STORAGE_BUCKET_NAME}/media/"
    )

# ─── Cloud platform database / redis URL parsing ──────────────────────────────
# Railway, Render, Heroku etc. expose a single DATABASE_URL connection string.
# dj-database-url parses it into Django's DATABASES dict format automatically.
if _database_url:
    import dj_database_url  # noqa: E402
    DATABASES["default"] = dj_database_url.parse(  # noqa: F405
        _database_url,
        conn_max_age=config("DB_CONN_MAX_AGE", default=60, cast=int),
        conn_health_checks=True,
    )

# Railway exposes REDIS_URL automatically when you add a Redis service.
_redis_url = config("REDIS_URL", default="")
if _redis_url:
    CELERY_BROKER_URL = _redis_url  # noqa: F405
    CELERY_RESULT_BACKEND = _redis_url  # noqa: F405
    CACHES["default"]["LOCATION"] = _redis_url  # noqa: F405

# ─── ALLOWED_HOSTS: auto-include Railway deployment domain ────────────────────
# Railway sets RAILWAY_PUBLIC_DOMAIN to your app's URL (e.g. myapp.up.railway.app)
_railway_domain = config("RAILWAY_PUBLIC_DOMAIN", default="")
if _railway_domain:
    ALLOWED_HOSTS.append(_railway_domain)  # noqa: F405
    CSRF_TRUSTED_ORIGINS.append(f"https://{_railway_domain}")  # noqa: F405

# ─── Production throttle overrides ───────────────────────────────────────────
# Redis-backed throttling is already active via CACHES = django_redis.
# Raise the authenticated user limit so active users are never false-blocked.
# Anonymous limit stays tight to resist unauthenticated probing / DDoS.
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].update({  # noqa: F405
    "anon": "60/hour",
    "user": "3000/hour",      # per-user; many users never share this quota
    "login": "5/minute",
})

# Raise upload ceiling for production (logos, PDF invoices, receipts)
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024   # 20 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024   # 15 MB

# Email
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = config("EMAIL_HOST", default="smtp.sendgrid.net")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@finventory.app")
