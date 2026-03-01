"""
Base Django settings for Finventory SaaS Platform.

This module contains settings shared across all environments.
Environment-specific overrides live in development.py / production.py.

Architecture note:
    - All secrets loaded via python-decouple (never hardcoded)
    - Apps are organised by domain under apps/
    - Logging uses structlog for structured, machine-parseable output
"""

import os
from pathlib import Path

from decouple import Csv, config

# ─── Paths ────────────────────────────────────────────────────────────────────
# BASE_DIR points to the `backend/` folder (one level above this settings pkg)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ─── Core ─────────────────────────────────────────────────────────────────────
SECRET_KEY = config("SECRET_KEY", default="change-me-in-production-never-commit-real-key")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS: list[str] = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# ─── Third-party API keys ──────────────────────────────────────────────────────
# Paystack secret key — used for NUBAN account name resolution on the employee form.
# Get yours at https://dashboard.paystack.com/#/settings/developers
PAYSTACK_SECRET_KEY = config("PAYSTACK_SECRET_KEY", default="")

# ─── Application Definition ───────────────────────────────────────────────────
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
]

LOCAL_APPS = [
    "apps.core",
    "apps.tenancy",
    "apps.authentication",
    "apps.subscriptions",
    "apps.inventory",
    "apps.suppliers",
    "apps.purchases",
    "apps.sales",
    "apps.customers",
    "apps.credits",
    "apps.expenses",
    "apps.tax",
    "apps.reports",
    "apps.quotes",
    "apps.bills",
    "apps.accounting",
    "apps.payroll",
    "apps.payments",
    "apps.budgets",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ─── Middleware ────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",          # must be before CommonMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Custom tenant resolution middleware
    "apps.tenancy.middleware.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ─── Database ─────────────────────────────────────────────────────────────────
# Scaling note: Use connection pooling (PgBouncer) in production.
# The DATABASE_URL pattern makes cloud deployments trivial.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="finventory"),
        "USER": config("DB_USER", default="postgres"),
        "PASSWORD": config("DB_PASSWORD", default="postgres"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=60, cast=int),
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }
}

# ─── Custom Auth Model ────────────────────────────────────────────────────────
AUTH_USER_MODEL = "authentication.User"

# ─── Password Validation ──────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ─── Internationalisation ──────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = config("TIME_ZONE", default="UTC")
USE_I18N = True
USE_TZ = True

# ─── Static & Media Files ─────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ─── Default Primary Key ──────────────────────────────────────────────────────
# Using UUID throughout for tenant-safety and horizontal scale.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── Django REST Framework ────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    # Global pagination prevents accidental full-table dumps
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Structured error responses across the board
    "EXCEPTION_HANDLER": "apps.core.exceptions.custom_exception_handler",
    # Rate limiting — per-scope limits applied on auth endpoints
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "200/hour",
        "user": "2000/hour",
        "login": "10/minute",       # LoginRateThrottle
        "register": "5/hour",       # RegisterRateThrottle
        "token_refresh": "20/minute",  # TokenRefreshRateThrottle
    },
}

# ─── JWT Configuration ────────────────────────────────────────────────────────
from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=config("JWT_ACCESS_MINUTES", default=60, cast=int)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=config("JWT_REFRESH_DAYS", default=30, cast=int)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,           # requires token_blacklist app
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": config("SECRET_KEY", default="change-me"),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    # Include tenant + role claims for single-request authorization
    "TOKEN_OBTAIN_SERIALIZER": "apps.authentication.serializers.CustomTokenObtainPairSerializer",
}

# ─── CORS ─────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS: list[str] = config(
    "CORS_ALLOWED_ORIGINS",
    # tauri://localhost  → Tauri v2 desktop app origin
    # capacitor://localhost → Capacitor Android/iOS WebView origin
    # http://localhost  → Capacitor Android http scheme fallback
    default=(
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "tauri://localhost,"
        "capacitor://localhost,"
        "http://localhost"
    ),
    cast=Csv(),
)
CORS_ALLOW_CREDENTIALS = True

# Extend default headers to include the tenant header used by all API requests
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "x-organisation-id",   # required for tenant resolution
]

# Trusted origins for CSRF — mirrors CORS list so packaged apps can POST
CSRF_TRUSTED_ORIGINS: list[str] = config(
    "CSRF_TRUSTED_ORIGINS",
    default=(
        "http://localhost:3000,"
        "tauri://localhost,"
        "capacitor://localhost,"
        "http://localhost"
    ),
    cast=Csv(),
)

# ─── Security Headers ─────────────────────────────────────────────────────────
# These are enforced in production by Django's SecurityMiddleware.
# Safe to set in all environments — browsers will honour them regardless of DEBUG.
X_FRAME_OPTIONS = "DENY"                          # Prevent clickjacking
SECURE_CONTENT_TYPE_NOSNIFF = True                # Prevent MIME-type sniffing
SECURE_BROWSER_XSS_FILTER = True                  # Legacy IE XSS filter header
REFERRER_POLICY = "strict-origin-when-cross-origin"
PERMISSIONS_POLICY = "geolocation=(), microphone=(), camera=()"

# ─── Caching (Redis) ──────────────────────────────────────────────────────────
REDIS_URL = config("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
        },
        "KEY_PREFIX": "finventory",
    }
}

# ─── Celery ───────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True

# ─── OpenAPI / Spectacular ────────────────────────────────────────────────────
SPECTACULAR_SETTINGS = {
    "TITLE": "Finventory API",
    "DESCRIPTION": "Production-grade Accounting & Inventory Management SaaS",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# ─── Logging ──────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "level": "WARNING",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "finventory.log",
            "maxBytes": 1024 * 1024 * 10,  # 10 MB
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}
