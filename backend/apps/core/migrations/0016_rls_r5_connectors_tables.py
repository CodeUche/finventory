"""
R-5 — enable RLS on the three Connectors tenant tables.

Why this batch exists at all is the useful part.

Batches R-2 to R-4 were generated from the models as they stood, and covered
every tenant-bearing table at that moment. The Connectors feature merged from
main shortly afterwards, bringing three new TenantAwareModel subclasses --
ConnectorConnection, ConnectorAddonSubscription, ConnectorEventDelivery -- none
of which appeared in any batch. They would have deployed with no database-level
isolation at all, days after that gap was closed everywhere else.

ConnectorConnection is the one that matters: it holds the per-organisation
state for third-party OAuth connections (Nango), so a missing policy there is
a missing policy on integration credentials.

Nothing caught this automatically. RlsCoverageTests only asserted that the
tables *named in the batch migrations* had RLS on, which is true and useless
when the problem is a table nobody listed. That test now derives the expected
set from the Django models instead, so the next app to arrive fails the suite
rather than shipping quietly.

Policy shape, the FORCE decision, savepoint handling and the deliberate
exclusions are documented in apps/core/rls_policy.py and migration 0013.
"""

from django.db import migrations

from apps.core.rls_policy import apply_rls, revert_rls

TABLES = [
    "connectors_connectoraddonsubscription",
    "connectors_connectorconnection",
    "connectors_connectoreventdelivery",
]

LABEL = "core.0016 (R-5)"


class Migration(migrations.Migration):
    atomic = False

    # connectors must have created its tables first. Without this the ALTER
    # TABLE fails on a table that does not exist, the per-table handler logs a
    # warning and continues, and the migration is recorded as applied having
    # protected nothing — the failure that hit 8/68 tables in the R-2..R-4
    # rehearsal before app dependencies were added.
    dependencies = [
        ("core", "0015_rls_r4_high_value_tables"),
        ("connectors", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(apply_rls(TABLES, LABEL), revert_rls(TABLES, LABEL), atomic=False),
    ]
