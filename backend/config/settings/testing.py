"""Test settings - uses SQLite for speed, disables caching."""

from .base import *  # noqa: F401, F403

# Use fast SQLite for unit tests; integration tests should use Postgres
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Disable caching in tests
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.dummy.DummyCache",
    }
}

# Fast password hashing
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Celery always eager in tests
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Use in-memory email backend — prevents anymail / SMTP from firing in tests
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
# Satisfy anymail app checks without a real API key
ANYMAIL = {"BREVO_API_KEY": "test-key-not-used"}

# Suppress logs in tests unless DEBUG
LOGGING["root"]["level"] = "CRITICAL"  # noqa: F405
