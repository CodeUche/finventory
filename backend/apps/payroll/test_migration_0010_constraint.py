"""
Regression test for the payroll.0010 constraint-removal bug.

On a truly from-zero `migrate` (reproduced against a brand-new Aurora Postgres
instance while standing up the AWS stack — see the AWS migration project
notes), applying `payroll.0010_nta2025_annual_rent_nhf_optin` failed with:

    django.db.utils.ProgrammingError: constraint
    "unique_paye_remittance_per_org_period" of relation
    "payroll_payeremittance" does not exist

even though the immediately preceding migration, 0009, unambiguously adds
that exact constraint. A serial from-zero `migrate` against a clean local
Postgres could not reproduce the failure deterministically — but concurrent,
unguarded `migrate` invocations against the same empty database (the shape
ECS produces when api/worker/beat each run migrate.py independently on cold
start) reliably crash with *other* Postgres catalog races, which is strong
evidence the missing constraint arises from the same class of problem: some
process reaches migration 0010 believing 0009 already ran while the
constraint it added is not actually present in that connection's view of the
schema.

Regardless of the exact trigger, migration 0010 must not hard-fail just
because the constraint it means to remove is already absent. This test
exercises the actual 0009 -> 0010 transition via Django's MigrationExecutor,
manually removing the constraint in between (reproducing the wedged state
seen on Aurora) to confirm 0010 now applies cleanly instead of raising
ProgrammingError.

Runs inside a plain TestCase: Postgres DDL is transactional, so the schema
changes made here by rolling the payroll app back and forward are undone by
Django's end-of-test rollback like any other test-time DB write.
"""
import unittest

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase

from apps.core.rls_testing import rls_available

CONSTRAINT_NAME = "unique_paye_remittance_per_org_period"


@unittest.skipUnless(
    rls_available(), "PostgreSQL required — pg_constraint / real DDL semantics"
)
class Payroll0010ConstraintRemovalTests(TestCase):
    """payroll.0010 must tolerate the unique_paye_remittance_per_org_period
    constraint already being absent when it tries to remove it."""

    def _constraint_exists(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_constraint WHERE conname = %s", [CONSTRAINT_NAME]
            )
            return cursor.fetchone() is not None

    def test_0010_applies_cleanly_when_constraint_already_missing(self):
        executor = MigrationExecutor(connection)

        # Roll payroll back to right after 0009 added the constraint.
        executor.migrate([("payroll", "0009_employeetaxprofile_payeremittance")])
        executor.loader.build_graph()
        self.assertTrue(
            self._constraint_exists(),
            "sanity check: 0009 should have created the constraint",
        )

        # Reproduce the wedged state observed on a from-zero Aurora apply:
        # the constraint is gone by the time 0010 runs.
        with connection.cursor() as cursor:
            cursor.execute(
                f"ALTER TABLE payroll_payeremittance DROP CONSTRAINT {CONSTRAINT_NAME};"
            )
        self.assertFalse(self._constraint_exists())

        # This used to raise:
        #   django.db.utils.ProgrammingError: constraint
        #   "unique_paye_remittance_per_org_period" of relation
        #   "payroll_payeremittance" does not exist
        executor.migrate([("payroll", "0010_nta2025_annual_rent_nhf_optin")])
        executor.loader.build_graph()

        # Forward migration succeeded and state still reflects the removal
        # (0010's state_operations still include RemoveConstraint).
        applied = executor.loader.applied_migrations
        self.assertIn(("payroll", "0010_nta2025_annual_rent_nhf_optin"), applied)

        # Restore payroll to its head so any tests that run after this one in
        # the same session see the normal, fully-migrated schema.
        executor.loader.build_graph()
        latest = executor.loader.graph.leaf_nodes("payroll")
        executor.migrate(latest)
        executor.loader.build_graph()
