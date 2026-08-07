"""Development settings - DEBUG on, relaxed security."""

from .base import *  # noqa: F401, F403

DEBUG = True

# Restrict to known local origins only — prevents host-header injection even in dev.
# host.docker.internal lets the local observability stack (Prometheus/blackbox in
# Docker) scrape the host-run dev server without tripping DisallowedHost.
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal"]

# Whitelist only known local origins in development
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    # :5183/:8010 is the throwaway browser-E2E stack (kept off :3000/:8000 so
    # it never collides with whatever else is already running on the default
    # ports) — see finventory/frontend/e2e/today.setup.ts.
    "http://localhost:5183",
    "http://127.0.0.1:5183",
    "tauri://localhost",
    # Tauri v2's actual runtime origin is the http://tauri.localhost custom
    # hostname, not the tauri://localhost URL-scheme string Tauri v1 used —
    # the old entry above never matches a real v2 app's Origin header, which
    # silently breaks the local desktop build's login (fetch falls back from
    # the Rust IPC proxy to a plain WebView fetch and hits CORS). Discovered
    # while browser-CDP-testing the desktop build; kept the v1 entry too in
    # case anything still relies on it.
    "http://tauri.localhost",
    "capacitor://localhost",
]

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

# ─── E2E: opt-out of API throttling (development only) ────────────────────────
# Browser E2E drives many requests from one IP, and the local observability stack
# also polls /api/v1/health/, which together exhaust the anon (60/hour) and user
# (1000/hour) throttles. Requests then 429 and the app renders a blank nav — a
# test-harness artifact that looks like an app bug.
# Set DISABLE_THROTTLING=True in the local .env (or the E2E run command) to lift
# the limits. This is read only by development settings; production is unaffected.
if _cfg("DISABLE_THROTTLING", default=False, cast=bool):
    # Keep every scope key — views that declare an explicit throttle class (e.g.
    # LoginRateThrottle, scope 'login') look their scope up by name and raise
    # KeyError if it is missing. A rate of None is DRF's "unlimited".
    REST_FRAMEWORK = {  # noqa: F405
        **REST_FRAMEWORK,  # noqa: F405
        "DEFAULT_THROTTLE_CLASSES": [],
        "DEFAULT_THROTTLE_RATES": {
            scope: None
            for scope in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]  # noqa: F405
        },
    }
