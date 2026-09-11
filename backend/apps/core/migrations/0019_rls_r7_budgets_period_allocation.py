"""
R-7 — enable row-level security on the two Budgets tables added in Phase 5
(BudgetPeriod, BudgetAllocation).

Same cause as R-6: these tables were built after batches R-2 to R-5 were
generated, so they carried no database-level tenant isolation until
RlsCoverageTests (which derives its expectation from the Django models, not
from what any prior batch happened to cover) caught the gap.

BudgetAllocation names a real Chart-of-Accounts account and an allocated
amount — exactly the kind of figure that must never leak across tenants at
the database layer, not just via application-level org filtering.
BudgetPeriod is lower-stakes (just a named date range) but is included for
the same reason every other tenant table is: consistency, and because it FKs
into Budget the same way Budget's own table already has RLS.

Policy shape, the FORCE decision, savepoint handling and the deliberate
exclusions are documented in apps/core/rls_policy.py and migration 0013.
"""

from django.db import migrations

from apps.core.rls_policy import apply_rls, revert_rls

TABLES = [
    "budgets_budgetperiod",
    "budgets_budgetallocation",
]

LABEL = "core.0019 (R-7)"


class Migration(migrations.Migration):
    atomic = False

    # budgets must have created these tables first — see the note in 0016/0018.
    dependencies = [
        ("core", "0018_rls_r6_notifications_tables"),
        ("budgets", "0006_budgetline_attachment_budgetline_forecast_amount_and_more"),
    ]

    operations = [
        migrations.RunPython(apply_rls(TABLES, LABEL), revert_rls(TABLES, LABEL), atomic=False),
    ]
