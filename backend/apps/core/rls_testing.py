"""
Test helpers for exercising PostgreSQL row-level security.

The trap this exists to avoid
-----------------------------
RLS policies do not apply to a table's owner unless FORCE ROW LEVEL SECURITY is
set. Django's test runner creates the schema as the connecting role, so that
role owns every table — meaning a test that simply sets ``app.current_org_id``
and queries will see **all** rows and happily pass while proving nothing.

Production does not have this problem: the app connects as ``audity_app``,
which owns almost nothing (verified: 7 of 163 tables, none RLS-enabled), so
policies apply to it. ``as_app_role`` reproduces that arrangement in tests by
switching to a deliberately unprivileged role for the duration of a block.

Usage::

    with as_app_role(), organisation_context(org.id):
        assert Invoice.objects.count() == 1   # only this tenant's row

Order matters: enter ``as_app_role`` first so the SET ROLE and the queries share
one connection state, and note that both are connection-scoped, not
transaction-scoped.
"""

from contextlib import contextmanager

from django.db import connection

APP_ROLE = "audity_app_test"


def rls_available() -> bool:
    """True when the connection can actually enforce RLS (i.e. PostgreSQL)."""
    return connection.vendor == "postgresql"


def ensure_app_role():
    """
    Create the unprivileged test role if absent and grant it read/write on the
    public schema.

    Deliberately NOT granted BYPASSRLS and never made an owner — either would
    silently defeat every isolation assertion in the suite.
    """
    if not rls_available():
        return
    with connection.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", [APP_ROLE]
        )
        if not cur.fetchone():
            # NOINHERIT so the role cannot pick up privileges (including
            # BYPASSRLS) from any role it may later be granted membership in.
            cur.execute(f'CREATE ROLE "{APP_ROLE}" NOLOGIN NOINHERIT')
        cur.execute(f'GRANT USAGE ON SCHEMA public TO "{APP_ROLE}"')
        cur.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "
            f'public TO "{APP_ROLE}"'
        )
        cur.execute(
            f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{APP_ROLE}"'
        )


@contextmanager
def as_app_role():
    """
    Run the block as the unprivileged role so RLS policies actually apply.

    Resets on exit even if the body raises, so a failing assertion cannot leave
    the connection switched for whatever test runs next.
    """
    if not rls_available():
        # SQLite has no roles and no RLS; yielding unchanged keeps these
        # helpers importable from the default suite without pretending the
        # isolation was verified.
        yield
        return

    ensure_app_role()
    with connection.cursor() as cur:
        cur.execute(f'SET ROLE "{APP_ROLE}"')
    try:
        yield
    finally:
        with connection.cursor() as cur:
            cur.execute("RESET ROLE")


def assert_rls_is_really_on(test_case, table: str):
    """
    Guard against the false-confidence failure mode: a suite that reports green
    because RLS was never enforced in the first place.

    Asserts the named table has RLS enabled and that the current role is
    genuinely subject to it.
    """
    with connection.cursor() as cur:
        cur.execute(
            "SELECT relrowsecurity FROM pg_class WHERE relname = %s", [table]
        )
        row = cur.fetchone()
        test_case.assertIsNotNone(row, f"table {table} not found")
        test_case.assertTrue(
            row[0], f"RLS is not enabled on {table} — isolation tests would pass vacuously"
        )
        cur.execute(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        is_super, bypass = cur.fetchone()
        test_case.assertFalse(
            is_super, "connected as a superuser — RLS is bypassed, test proves nothing"
        )
        test_case.assertFalse(
            bypass, "current role has BYPASSRLS — test proves nothing"
        )
