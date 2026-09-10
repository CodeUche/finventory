"""
Regression test for the core.0003 ALTER DATABASE connection-poisoning bug.

On a truly from-zero `migrate` against a brand-new AWS Aurora Postgres
instance (see the AWS migration project notes), `core.0003_rls_db_default`
crashed the whole migrate run with:

    django.db.utils.InternalError: current transaction is aborted, commands
    ignored until end of transaction block

raised not from the migration's own ALTER DATABASE statement, but from the
*next* statement Django ran on that connection — its own INSERT INTO
django_migrations recording 0003 as applied.

Root cause: `apply()` ran `ALTER DATABASE ... SET app.current_org_id = ...`
inside a bare `try/except Exception: pass`. Railway's connecting role can run
that ALTER DATABASE outright, so the except branch never fired there. AWS
RDS/Aurora's master user is `rds_superuser`, not a true Postgres superuser,
and is refused this instance-level ALTER — reproduced locally below by
forcing the same statement to fail for an unrelated reason (a nonexistent
database name), which fails identically whether the cause is a missing
privilege or a missing database. Either way, once a statement inside a
transaction errors, PostgreSQL refuses every subsequent statement on that
connection until an explicit ROLLBACK — which the bare `except` never issued.
The fix wraps the statement in `transaction.atomic()`, which creates a real
savepoint and rolls back to it on failure, leaving the connection usable.

This mirrors the exact failure class already documented (and fixed, via
per-statement SAVEPOINTs) in core.0008_bulletproof_disable_rls.py's own
docstring for migrations 0006/0007 — the same shape has now bitten this repo
three times.
"""
import importlib
import unittest
from types import SimpleNamespace

from django.db import connection
from django.test import TestCase

from apps.core.rls_testing import rls_available

# core.0003's filename is not a valid Python identifier (leading digit), so
# it's loaded the same way Django's migration loader loads it: by dotted
# module path via importlib, not a literal `import` statement.
_migration_0003 = importlib.import_module(
    "apps.core.migrations.0003_rls_db_default"
)


class _BadNameConnection:
    """Delegates to the real connection for everything except the database
    name, which is swapped for one that doesn't exist — forcing the
    migration's `ALTER DATABASE "<name>" SET ...` to fail with a genuine
    PostgreSQL error while still executing against the real connection (and
    therefore the real transaction/session state) underneath.
    """

    def __init__(self, real_connection):
        self._real = real_connection
        self.settings_dict = {
            **real_connection.settings_dict,
            "NAME": "definitely_not_a_real_database_xyz",
        }
        self.vendor = real_connection.vendor
        self.alias = real_connection.alias

    def cursor(self):
        return self._real.cursor()


@unittest.skipUnless(
    rls_available(), "PostgreSQL required — real transaction-abort semantics"
)
class Core0003AlterDatabaseFailureTests(TestCase):
    """core.0003's apply()/revert() must not leave the connection's
    transaction poisoned when the ALTER DATABASE statement fails."""

    def test_apply_survives_alter_database_failure_and_leaves_connection_usable(self):
        fake_schema_editor = SimpleNamespace(connection=_BadNameConnection(connection))

        # This used to propagate all the way out as
        # django.db.utils.InternalError once the *next* query ran — never
        # from this call itself, which is exactly what made the bug hard to
        # spot from the traceback alone.
        _migration_0003.apply(apps=None, schema_editor=fake_schema_editor)

        # The real regression: the connection must still be usable
        # afterwards. Before the fix, this next query is where the failure
        # actually surfaced — "current transaction is aborted, commands
        # ignored until end of transaction block".
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            self.assertEqual(cursor.fetchone(), (1,))

    def test_revert_survives_alter_database_failure_and_leaves_connection_usable(self):
        fake_schema_editor = SimpleNamespace(connection=_BadNameConnection(connection))

        _migration_0003.revert(apps=None, schema_editor=fake_schema_editor)

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            self.assertEqual(cursor.fetchone(), (1,))
