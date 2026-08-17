"""
R-1 — index the one tenant table whose RLS predicate would seq-scan.

accounting_accountmapping is the only one of the 68 tables in this rollout
without a leading organisation_id index (its indexes are pkey, is_deleted,
created_at and nhf_account_id). Every RLS policy compares
``organisation_id = current_setting('app.current_org_id', TRUE)::uuid``, so
without that index the predicate falls back to a sequential scan.

It holds 10 rows in production today, so this is a no-op in practice — the
point is to land it before the policy exists rather than after the table has
grown. Benchmarking at 10M rows showed the composite-index question dominates
RLS overhead entirely (490ms -> 1.24ms), so an unindexed predicate is the one
way this rollout could actually cost anything.

Additive: creates an index, drops nothing, touches no data. CONCURRENTLY is
deliberately NOT used — it cannot run inside a transaction, and at 10 rows the
lock is measured in microseconds.
"""

from django.db import migrations

INDEX_NAME = "accounting_accountmapping_org_idx"
TABLE = "accounting_accountmapping"


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_alter_auditlog_action"),
    ]

    operations = [
        migrations.RunSQL(
            sql=f'CREATE INDEX IF NOT EXISTS {INDEX_NAME} ON {TABLE} (organisation_id);',
            reverse_sql=f'DROP INDEX IF EXISTS {INDEX_NAME};',
        ),
    ]
