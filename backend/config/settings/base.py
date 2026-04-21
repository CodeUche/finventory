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

# Ensure the logs directory exists so RotatingFileHandler can write to it.
# This is a no-op if the directory already exists.
Path(__file__).resolve().parent.parent.parent.joinpath("logs").mkdir(exist_ok=True)

from decouple import Csv, config

# ─── Paths ────────────────────────────────────────────────────────────────────
# BASE_DIR points to the `backend/` folder (one level above this settings pkg)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ─── Core ─────────────────────────────────────────────────────────────────────
# Never use this default in production — production.py raises ImproperlyConfigured if it detects it
SECRET_KEY = config("SECRET_KEY", default="change-me-in-production-never-commit-real-key")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS: list[str] = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# ─── Third-party API keys ──────────────────────────────────────────────────────
# Paystack secret key — used for NUBAN account name resolution on the employee form.
# Get yours at https://dashboard.paystack.com/#/settings/developers
PAYSTACK_SECRET_KEY = config("PAYSTACK_SECRET_KEY", default="")
PAYSTACK_PUBLIC_KEY = config("PAYSTACK_PUBLIC_KEY", default="")

# Frontend base URL (kept for reference; verify-email now uses backend URL directly)
FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:3000")
# Backend public URL — used to build email verification links for desktop app
BACKEND_URL = config("BACKEND_URL", default="http://localhost:8000")

# Groq AI key — powers the "Explain My Money" AI assistant (free globally)
# Get yours free at https://console.groq.com/keys
GROQ_API_KEY = config("GROQ_API_KEY", default="")

# NOTE: AI bank reconciliation reuses GROQ_API_KEY defined below

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
    "django_celery_beat",
    "anymail",
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
    "apps.ai",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ─── Middleware ────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.security_middleware.SecurityHeadersMiddleware",  # security headers on every response
    "corsheaders.middleware.CorsMiddleware",          # must be before CommonMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # PostgreSQL RLS — MUST come before TenantMiddleware so the session variable
    # is set before TenantMiddleware queries tenancy_organisation (which is RLS-protected).
    "apps.core.middleware.RLSMiddleware",
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
        # Default to empty string — production.py will raise if this is missing/weak
        "PASSWORD": config("DB_PASSWORD", default=""),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=60, cast=int),
        "OPTIONS": {
            "connect_timeout": 10,
            # Enforce SSL for all DB connections in any environment that provides a cert
            # (Railway sets sslmode=require automatically via DATABASE_URL)
        },
    }
}

# ─── Custom Auth Model ────────────────────────────────────────────────────────
AUTH_USER_MODEL = "authentication.User"

# ─── Password Hashing ─────────────────────────────────────────────────────────
# Argon2id is the OWASP-recommended winner of the Password Hashing Competition.
# It is memory-hard (resists GPU/ASIC attacks) and is the strongest hasher
# available in Django. Existing PBKDF2 hashes are transparently upgraded to
# Argon2 on next login.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",   # primary — all new passwords
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",   # legacy — upgrades on login
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]

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
        "apps.authentication.backends.VersionedJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
        "apps.core.permissions.IsVerified",
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
        # ── Global fallback limits ─────────────────────────────────────────
        "anon": "60/hour",             # Unauthenticated catch-all
        "user": "1000/hour",           # Authenticated catch-all
        # ── Auth endpoints (per-IP) ────────────────────────────────────────
        "login": "20/minute",          # LoginRateThrottle — brute-force guard
        "register": "3/hour",          # RegisterRateThrottle — signup spam guard
        "token_refresh": "10/minute",  # TokenRefreshRateThrottle
        "password_change": "3/hour",   # PasswordChangeRateThrottle
        "password_reset_request": "5/hour",   # PasswordResetRequestRateThrottle
        "password_reset_confirm": "10/hour",  # PasswordResetConfirmRateThrottle
        "resend_verification": "3/hour",      # ResendVerificationRateThrottle
        "check_verification": "30/minute",    # CheckVerificationRateThrottle
        "mfa_verify": "10/minute",            # MFAVerifyRateThrottle
        # ── Business endpoints ─────────────────────────────────────────────
        "bank_resolve": "20/minute",   # BankResolveRateThrottle — Paystack proxy
        "invitation": "10/hour",       # InvitationRateThrottle — team management
        "webhook": "300/minute",       # WebhookRateThrottle — Paystack inbound events
        "public_read": "30/minute",    # PublicReadRateThrottle — plan listing etc.
        "ping": "120/minute",          # PingRateThrottle — Tauri offline probe (15s interval)
        "ai_support": "20/minute",     # AISupportRateThrottle — public support chat widget
    },
}

# ─── JWT Configuration ────────────────────────────────────────────────────────
from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=config("JWT_ACCESS_MINUTES", default=15, cast=int)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=config("JWT_REFRESH_DAYS", default=7, cast=int)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,           # requires token_blacklist app
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": config("SECRET_KEY", default="change-me-in-production-never-commit-real-key"),
    # Explicitly reject all other algorithms — prevents algorithm-confusion attacks
    "ALLOWED_ALGORITHMS": ["HS256"],
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    # Prevent token reuse after a user is deactivated
    "CHECK_REVOCATION_ON_AUTHENTICATION": False,  # handled by BLACKLIST_AFTER_ROTATION
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

# ─── Admin URL ────────────────────────────────────────────────────────────────
# Obfuscate the admin path via environment variable — never use the default /admin/
# in production. Generate a random path: python -c "import secrets; print(secrets.token_hex(8))"
ADMIN_URL = config("ADMIN_URL", default="admin/")

# ─── File Upload Limits ───────────────────────────────────────────────────────
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024   # 10 MB max request body
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024    # 5 MB max file upload

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

# Windows-compatible worker pool.
# Celery's default prefork pool uses POSIX semaphores which Windows (WinError 5)
# rejects. 'solo' runs tasks in the same process — fine for a single-server dev
# or staging setup. On Linux/Mac the default 'prefork' is used automatically.
import sys as _sys  # noqa: E402
if _sys.platform == "win32":
    CELERY_WORKER_POOL = "solo"

# ─── Celery Beat (Periodic Tasks) ─────────────────────────────────────────────
# Start the beat scheduler alongside the worker:
#   celery -A config.celery beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
# Or with a simple file-based scheduler for single-server deployments:
#   celery -A config.celery beat --loglevel=info
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    # Mark overdue invoices daily at 00:05
    "mark-overdue-invoices-daily": {
        "task": "sales.mark_overdue_invoices",
        "schedule": crontab(hour=0, minute=5),
    },
    # Generate recurring invoices daily at 00:10
    "generate-recurring-invoices-daily": {
        "task": "sales.generate_recurring_invoices",
        "schedule": crontab(hour=0, minute=10),
    },
    # Run monthly depreciation on the 1st of each month at 01:00
    "run-monthly-depreciation": {
        "task": "accounting.run_monthly_depreciation",
        "schedule": crontab(hour=1, minute=0, day_of_month=1),
    },
    # Create year-archive folders on Jan 1 at 00:30 (invoices) and 00:35 (bills)
    "create-invoice-year-archive": {
        "task": "sales.create_year_archive_folders",
        "schedule": crontab(hour=0, minute=30, month_of_year=1, day_of_month=1),
    },
    "create-bill-year-archive": {
        "task": "bills.create_year_archive_folders",
        "schedule": crontab(hour=0, minute=35, month_of_year=1, day_of_month=1),
    },
    # Check for expired trials and subscriptions every hour
    "expire-subscriptions-hourly": {
        "task": "subscriptions.expire_subscriptions",
        "schedule": crontab(hour="*", minute=0),
    },
}

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
            "delay": True,  # Don't open the file until the first log message — safe in CI/test envs where logs/ may not exist
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
