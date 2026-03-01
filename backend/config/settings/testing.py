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

# Suppress logs in tests unless DEBUG
LOGGING["root"]["level"] = "CRITICAL"  # noqa: F405
