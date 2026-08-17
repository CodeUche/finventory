"""
NEW-6 — the composite index that "the newest N for this company" queries want.

Every list screen in this application runs the same query::

    WHERE organisation_id = <company> ORDER BY created_at DESC LIMIT <page>

With only a single-column ``organisation_id`` index, Postgres finds the
company's rows and then sorts all of them to return one page. That sort is
the whole cost. Benchmarked during the R-1 work:

    (organisation_id) only .............. 490.73 ms
    (organisation_id, created_at DESC) ... 1.24 ms      397x

This buys nothing today and is not claimed to. The largest table here holds
2,547 rows in production and the whole database is 34 MB; at that size
Postgres does not care. The point is that the cliff is a function of rows per
company, not of anything we control, and it is far cheaper to land the index
while the tables are small than to diagnose it later from a support ticket.

Which tables, and why not all of them
-------------------------------------
134 tenant tables have a ``created_at`` column. Only 16 are indexed here.
A table qualifies on two counts:

  1. Something actually sorts it by ``created_at`` — either the model's
     default ordering or an explicit ``.order_by("-created_at")`` in a view.
     62 tables sort by a business date instead (``entry_date``,
     ``purchase_date``, ``start_date``); a ``created_at`` index does nothing
     for those. They want their own composite — logged separately as NEW-6b,
     not bundled in here.

  2. It is listed by its own company-filtered endpoint. This is what excludes
     line-item tables. ``bill.items.all()`` emits
     ``WHERE bill_id = X ORDER BY created_at`` — ``organisation_id`` is not in
     that query at all, so an index leading with it can never be used. The
     foreign-key index already serves them.

Indexing all 134 would have added write cost to every insert across the
application in exchange for nothing on 118 of them.

Additive and reversible: creates indexes, drops nothing, touches no data and
no schema. CONCURRENTLY is deliberately not used, matching migration 0012 —
it cannot run inside a transaction, and at these row counts the lock is
measured in microseconds. If this ever needs re-running against a large
table, switch it to CONCURRENTLY with ``atomic = False`` first.
"""

from django.db import migrations

# Sorted by created_at AND listed by their own company-filtered endpoint.
TABLES = [
    "bills_bill",
    "core_auditlog",
    "helpdesk_supportticket",
    "integrations_webhooksubscription",
    "inventory_stockmovement",
    "notifications_notification",
    "payments_banktransferclaim",
    "payments_paymentlink",
    "payments_settlementbatch",
    "payments_virtualaccount",
    "payroll_advancerequest",
    "payroll_payrolladjustment",
    "pos_kitchenorderticket",
    "pos_posorder",
    "quotes_quote",
    "storefront_storefrontorder",
]


def _index_name(table):
    return f"{table}_org_created_idx"


class Migration(migrations.Migration):

    # Every app owning a table below is named, so this can never run before
    # the table exists. The RLS rollout hit exactly that: missing dependencies
    # meant the migration ran first and its error handler swallowed the
    # failure, leaving 60 of 68 tables unprotected while the suite stayed
    # green. There is no error handler here — a missing table fails loudly —
    # but the dependencies mean it should never come up.
    dependencies = [
        ("core", "0016_rls_r5_connectors_tables"),
        ("bills", "0005_billitem_asset_category_billitem_capitalise_and_more"),
        ("helpdesk", "0001_initial"),
        ("integrations", "0003_alter_webhooksubscription_options"),
        ("inventory", "0011_modifiergroup_modifieroption"),
        ("notifications", "0001_initial"),
        ("payments", "0003_settlementbatch_settlementline"),
        ("payroll", "0017_employeeloan_approved_at_employeeloan_approved_by_and_more"),
        ("pos", "0004_posorderitem_modifiers"),
        ("quotes", "0001_initial"),
        ("storefront", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                f"CREATE INDEX IF NOT EXISTS {_index_name(t)} "
                f"ON {t} (organisation_id, created_at DESC);"
            ),
            reverse_sql=f"DROP INDEX IF EXISTS {_index_name(t)};",
        )
        for t in TABLES
    ]
