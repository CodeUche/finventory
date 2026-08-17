"""
R-3 — enable RLS on 15 operational tenant tables.

Messaging, POS, storefront and purchase returns. Second batch: a wrong
policy here shows as an empty list on an operational screen, which is
recoverable, but it is closer to the money than R-2 was.

storefront_* is worth naming: those tables back the PUBLIC, unauthenticated
shop endpoints, where the tenant is resolved from the slug rather than from
a header. Those views set org context explicitly before querying, so the
policy binds correctly — but they are the one place in this batch where an
unauthenticated caller reaches an RLS-protected table, so they get their own
verification in the R-3 rehearsal.

Policy shape, the FORCE decision, savepoint handling and the deliberate
exclusions (tenancy_membership / tenancy_organisation / core_auditlog /
accounting_journalline) are all documented in apps/core/rls_policy.py and
migration 0013. This batch reuses those helpers so the policy applied here is
byte-identical to every other batch.
"""

from django.db import migrations

from apps.core.rls_policy import apply_rls, revert_rls

TABLES = [
    "messaging_conversation",
    "messaging_conversationparticipant",
    "messaging_message",
    "messaging_messageattachment",
    "pos_kitchenorderticket",
    "pos_posorder",
    "pos_posorderitem",
    "pos_restauranttable",
    "pos_tillsession",
    "pos_tilltendercount",
    "purchases_purchasereturn",
    "purchases_purchasereturnitem",
    "storefront_storefront",
    "storefront_storefrontorder",
    "storefront_storefrontorderitem",
]

LABEL = "core.0014 (R-3)"


class Migration(migrations.Migration):
    atomic = False


    # Every app whose tables this batch touches must have created them first.
    # Without these, Django is free to run this migration before those apps'
    # initial migrations: ALTER TABLE then fails on a table that does not exist
    # yet, the per-table handler logs a warning and continues, and the migration
    # is recorded as applied having protected nothing. That is exactly how
    # migrations 0006/0007 came to be silently no-ops. Verified: 8/68 tables
    # were enabled before these dependencies were added, 68/68 after.
    dependencies = [
        ("core", "0013_rls_r2_low_risk_tables"),
        ("messaging", "0001_initial"),
        ("pos", "0004_posorderitem_modifiers"),
        ("purchases", "0005_purchasereturn_purchasereturnitem"),
        ("storefront", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(apply_rls(TABLES, LABEL), revert_rls(TABLES, LABEL), atomic=False),
    ]
