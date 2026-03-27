"""Development settings - DEBUG on, relaxed security."""

from .base import *  # noqa: F401, F403

DEBUG = True

# Allow all hosts in development
ALLOWED_HOSTS = ["*"]

# Allow all CORS origins in development (covers tauri://, capacitor://, localhost)
CORS_ALLOW_ALL_ORIGINS = True

# Show SQL queries in development
LOGGING["loggers"]["django.db.backends"] = {  # noqa: F405
    "handlers": ["console"],
    "level": "DEBUG",
    "propagate": False,
}

# Debug toolbar
INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405
INTERNAL_IPS = ["127.0.0.1", "localhost"]

# Use real SMTP if EMAIL_HOST is configured in .env, otherwise fall back to console
from decouple import config as _cfg  # noqa: E402
_email_host = _cfg("EMAIL_HOST", default="")
if _email_host:
    EMAIL_BACKEND     = "apps.core.email_backend.CertifiEmailBackend"
    EMAIL_HOST        = _email_host
    EMAIL_PORT        = _cfg("EMAIL_PORT", default=587, cast=int)
    EMAIL_USE_TLS     = True
    EMAIL_USE_SSL     = False
    EMAIL_TIMEOUT     = 10
    EMAIL_HOST_USER   = _cfg("EMAIL_HOST_USER", default="")
    EMAIL_HOST_PASSWORD = _cfg("EMAIL_HOST_PASSWORD", default="")
    DEFAULT_FROM_EMAIL = _cfg("DEFAULT_FROM_EMAIL", default="")
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
