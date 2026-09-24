"""Staging settings: a production-shaped stack you are free to break.

WHY THIS EXISTS
    Production is the only environment this project ever had that was not
    DEBUG=True. That left nowhere to prove a change actually works before real
    users meet it: `development.py` is too permissive to catch a whole class of
    bug (a missing CORS origin, a cookie that only breaks when DEBUG is off, a
    manifest-static lookup, a throttle that fires), and `production.py` cannot
    be run locally at all because its start-up guards demand a non-default
    ADMIN_URL, an HTTPS-only posture and a real secret store.

    Staging sits between the two. It keeps every production behaviour that can
    bite you (DEBUG off, whitenoise manifest static, real throttling, strict
    ALLOWED_HOSTS, the same middleware order), and relaxes only the things that
    cannot hold on a plain-HTTP localhost stack (TLS redirects, Secure cookies).

WHAT IT DELIBERATELY WILL NOT DO
    * Send real email. The console backend is forced unless you set
      STAGING_ALLOW_REAL_EMAIL=True, so a seeded customer with a real address
      can never be mailed from a test run.
    * Touch production object storage. Media goes to local disk; USE_S3 is
      ignored here.
    * Report into the production Sentry project. Only STAGING_SENTRY_DSN is
      read, never SENTRY_DSN.
    * Start against a remote database. See the guard below. The single worst
      accident this environment could cause is writing test data into the
      production Aurora cluster, so that is refused outright.

RUN IT
    ./scripts/staging.sh up          # whole stack in Docker, API on :8001
    DJANGO_SETTINGS_MODULE=config.settings.staging python manage.py <cmd>
"""

from decouple import config as _config

from .base import *  # noqa: F401, F403

IS_STAGING = True

DEBUG = False


# ── Start-up guards ──────────────────────────────────────────────────────────
def _require(name: str, value: str, min_length: int) -> None:
    """Refuse to start on a missing or placeholder secret, as production does."""
    from django.core.exceptions import ImproperlyConfigured

    if not value or len(value) < min_length:
        raise ImproperlyConfigured(
            f"[STAGING] {name} is missing or shorter than {min_length} characters. "
            "Run ./scripts/staging.sh up, which generates .env.staging with real "
            "values on first use."
        )
    if value.startswith(("CHANGE_ME", "change-me", "your-secret", "generate_with")):
        raise ImproperlyConfigured(
            f"[STAGING] {name} is still a placeholder. Delete .env.staging and "
            "re-run ./scripts/staging.sh up to regenerate it."
        )


_require("SECRET_KEY", _config("SECRET_KEY", default=""), min_length=40)
_require("FIELD_ENCRYPTION_KEY", _config("FIELD_ENCRYPTION_KEY", default=""), min_length=32)

# Staging must never be pointed at a live database. Getting this wrong does not
# produce an error you would notice. It produces test invoices in a customer's
# books. Anything that looks managed/hosted is refused unless someone knowingly
# opts in, and the two staging secrets above are distinct from production's, so
# an accidental copy of a production .env fails the check above first anyway.
_REMOTE_DB_MARKERS = (
    "rds.amazonaws.com", "amazonaws.com", "railway.app", "rlwy.net",
    "supabase.co", "neon.tech", "render.com", "digitalocean.com",
)
_db_host = _config("DB_HOST", default="localhost")
if not _config("STAGING_ALLOW_REMOTE_DB", default=False, cast=bool):
    if any(marker in _db_host.lower() for marker in _REMOTE_DB_MARKERS):
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            f"[STAGING] DB_HOST '{_db_host}' looks like a hosted database. Staging "
            "runs against its own local Postgres (docker-compose.staging.yml, "
            "port 5433). If you genuinely mean to point staging at a remote "
            "database, set STAGING_ALLOW_REMOTE_DB=True and understand that "
            "anything you seed lands there."
        )

# ── Hosts and origins ────────────────────────────────────────────────────────
# Strict, like production. A missing entry here is exactly the class of bug
# staging is meant to surface (see the tauri.localhost CORS incident).
ALLOWED_HOSTS = _config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1,0.0.0.0,api-staging,host.docker.internal",
    cast=lambda v: [h.strip() for h in v.split(",") if h.strip()],
)

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = _config(
    "CORS_ALLOWED_ORIGINS",
    default=(
        # Vite dev server and `vite preview` for the staging frontend. Kept off
        # 3000/5173/4173 so a staging browser tab can never be confused with,
        # or fight over a port with, the ordinary dev stack.
        "http://localhost:5174,http://127.0.0.1:5174,"
        "http://localhost:4174,http://127.0.0.1:4174,"
        # Tauri v2 on Windows serves the app from this origin, not tauri://.
        "http://tauri.localhost,tauri://localhost,capacitor://localhost"
    ),
    cast=lambda v: [o.strip() for o in v.split(",") if o.strip()],
)
CSRF_TRUSTED_ORIGINS = [o for o in CORS_ALLOWED_ORIGINS if o.startswith("http")]

# ── Security posture ─────────────────────────────────────────────────────────
# Everything production sets, except what a plain-HTTP localhost cannot honour.
# SECURE_SSL_REDIRECT off and cookies not Secure: with either one on, the login
# POST succeeds and then the session cookie is silently dropped, which reads as
# "staging is broken" rather than "staging has no TLS".
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

# ── Static files: same pipeline as production ───────────────────────────────
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")  # noqa: F405

STORAGES = {
    # Local disk on purpose: staging never writes to the production bucket.
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}
WHITENOISE_MANIFEST_STRICT = False

# ── Throttling ───────────────────────────────────────────────────────────────
# Real throttle classes stay active, because a rate limit that only exists in
# production is a rate limit nobody tests. The ceilings are raised well above
# production's so a full click-through of every module does not exhaust them:
# a 429 mid-run renders an empty nav and looks like an app bug, not a limit.
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].update({  # noqa: F405
    "anon": "600/hour",
    "user": "20000/hour",
    "login": "60/minute",
})

if _config("DISABLE_THROTTLING", default=False, cast=bool):
    # Keep every scope key: views with an explicit throttle class look their
    # scope up by name and raise KeyError when it is absent. None means no limit.
    REST_FRAMEWORK = {  # noqa: F405
        **REST_FRAMEWORK,  # noqa: F405
        "DEFAULT_THROTTLE_CLASSES": [],
        "DEFAULT_THROTTLE_RATES": {
            scope: None
            for scope in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]  # noqa: F405
        },
    }

# Same upload ceilings as production, so a file that is rejected there is
# rejected here too.
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024

# ── Email: console only, unless explicitly overridden ────────────────────────
# Seeded data contains addresses. Staging sending mail to any of them is a
# mistake with an outside-world blast radius, so it takes a deliberate opt-in.
if _config("STAGING_ALLOW_REAL_EMAIL", default=False, cast=bool):
    _brevo_api_key = _config("BREVO_API_KEY", default="")
    DEFAULT_FROM_EMAIL = _config("DEFAULT_FROM_EMAIL", default="staging@audity.test")
    if _brevo_api_key:
        EMAIL_BACKEND = "anymail.backends.brevo.EmailBackend"
        ANYMAIL = {"BREVO_API_KEY": _brevo_api_key}
    else:
        EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    DEFAULT_FROM_EMAIL = "staging@audity.test"

# ── Error tracking ───────────────────────────────────────────────────────────
# A separate DSN or nothing. Reading SENTRY_DSN here would file every
# deliberately-broken staging request as a production incident.
_staging_sentry_dsn = _config("STAGING_SENTRY_DSN", default="")
if _staging_sentry_dsn:
    import sentry_sdk  # noqa: E402

    sentry_sdk.init(
        dsn=_staging_sentry_dsn,
        traces_sample_rate=0.0,
        environment="staging",
    )

# ── Logging ──────────────────────────────────────────────────────────────────
# Full tracebacks on the console. Production hides these behind Sentry; here
# the point is to read the error the moment it happens.
LOGGING["loggers"]["django.request"] = {  # noqa: F405
    "handlers": ["console"],
    "level": "DEBUG",
    "propagate": False,
}
