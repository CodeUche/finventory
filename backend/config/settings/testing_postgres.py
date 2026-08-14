"""
Postgres-backed test settings — the only place RLS can actually be tested.

Why this exists
---------------
``config.settings.testing`` runs on SQLite, which has no row-level security.
Every RLS policy in ``apps/core/migrations/0002_enable_rls.py`` is therefore
invisible to the default test suite: ``_set_org()`` is a no-op on SQLite, and
tenant isolation is enforced by application code alone.

That gap is not theoretical. It is the reason finding NEW-7 shipped — all 13
cross-tenant scheduled tasks queried without org context and silently returned
zero rows in production, while every test passed.

These settings point the test runner at a real PostgreSQL instance so
migrations create the policies and queries are subject to them.

Running
-------
Requires a reachable PostgreSQL (the repo's docker-compose ``db`` service is
fine)::

    docker compose up -d db
    pytest -c pytest_postgres.ini apps/core/test_rls_integration.py

Credentials come from the same DB_* environment variables the dev settings use,
so no new configuration is introduced.

Important: RLS does not apply to a table's owner unless FORCE ROW LEVEL
SECURITY is set, and the test runner necessarily creates tables as the
connecting (owning) role. Tests must therefore switch to a non-owner role to
observe policies — see ``apps.core.rls_testing.as_app_role``. A test that
queries as the owner will see every row and prove nothing.
"""

from decouple import config

from .testing import *  # noqa: F401, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="finventory"),
        "USER": config("DB_USER", default="postgres"),
        "PASSWORD": config("DB_PASSWORD", default="postgres"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        "TEST": {
            # Explicit so the rehearsal database is obvious in psql and can
            # never be confused with the developer's working database.
            "NAME": "test_audity_rls",
        },
    }
}

# The RLS policies compare against app.current_org_id, which RLSMiddleware sets
# per request. Nothing here overrides that — tests set it explicitly so the
# assertions describe the real mechanism rather than a convenience shim.
