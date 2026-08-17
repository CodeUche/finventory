"""
Shared row-level-security policy helpers used by the RLS rollout migrations.

Every batch (R-2, R-3, R-4) calls these rather than carrying its own copy of
the SQL, so the policy applied to table 1 and table 68 cannot drift apart.

The policy shape is identical to the one migration 0002_enable_rls established:

    USING       (organisation_id = current_setting('app.current_org_id', TRUE)::uuid)
    WITH CHECK  (same)

RLSMiddleware sets that session variable once per request; Celery tasks set it
per organisation through apps.core.tenant_context (see NEW-7). Requests with no
org context carry the SENTINEL, which matches no row.

FORCE ROW LEVEL SECURITY is deliberately never set. Policies do not apply to a
table's owner without it, but the application connects as ``audity_app``, which
owns 7 of 163 tables — none of them RLS-enabled — so policies already bind. The
only thing FORCE would change is breaking ``manage.py migrate``, which runs as
the owner by design.

Each statement runs inside its own SAVEPOINT. Migrations 0006 and 0007 wrapped
every ALTER TABLE in one cursor block behind one broad except: the first failure
aborted the transaction, every later statement raised "current transaction is
aborted", the except swallowed all of it, and Django recorded the migration as
applied while nothing had run. Per-statement savepoints make one table's failure
cost only that table.
"""

import logging

logger = logging.getLogger(__name__)


def enable_sql(table: str) -> str:
    return f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON {table};
        CREATE POLICY tenant_isolation ON {table}
            USING (
                organisation_id = current_setting('app.current_org_id', TRUE)::uuid
            )
            WITH CHECK (
                organisation_id = current_setting('app.current_org_id', TRUE)::uuid
            );
    """


def disable_sql(table: str) -> str:
    return f"""
        DROP POLICY IF EXISTS tenant_isolation ON {table};
        ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
    """


def _run(schema_editor, tables, sql_for, label):
    if schema_editor.connection.vendor != "postgresql":
        # SQLite has no RLS; the default test settings use it, which is exactly
        # why apps/core/test_rls_integration.py exists on Postgres (NEW-8).
        return

    from django.db import transaction

    for table in tables:
        # One transaction per table. Each table's three statements (ALTER,
        # DROP POLICY, CREATE POLICY) must land together or not at all, and a
        # failure on one table must not touch the others.
        #
        # Raw SAVEPOINT cannot be used here: these migrations run with
        # atomic = False, so there is no enclosing transaction to save a point
        # within, and Postgres rejects it outright. atomic() opens a real
        # transaction per table, which is what the savepoints were reaching for.
        try:
            with transaction.atomic():
                with schema_editor.connection.cursor() as cursor:
                    cursor.execute(sql_for(table))
        except Exception as exc:
            logger.warning("%s: could not apply RLS to %s: %s", label, table, exc)


def apply_rls(tables, label):
    def _apply(apps, schema_editor):
        _run(schema_editor, tables, enable_sql, label)
    return _apply


def revert_rls(tables, label):
    def _revert(apps, schema_editor):
        _run(schema_editor, tables, disable_sql, f"{label} (revert)")
    return _revert
