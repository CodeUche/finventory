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

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
