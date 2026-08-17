"""
NEW-6 — the composite index that company list screens depend on.

Two separate jobs here, and the second matters more than the first.

`TheIndexExists` checks the 16 indexes are actually in the database. It fails
with migration 0017 reverted and passes with it applied.

`NothingSlipsThrough` is the one that keeps working after today. It derives
the candidate set from the models, so a table added next year that sorts by
created_at fails this test until somebody classifies it — indexed, or
excluded with a stated reason. Without that, this file would only ever
describe the day it was written.

Deliberately NOT read from migration 0017. A coverage test that reads its
expectations out of the migration it is checking proves only that the
migration equals itself. That mistake was made once already on the RLS
coverage test and is not repeated here.
"""

from django.apps import apps
from django.db import connection
from django.test import TestCase

# Sorted by created_at AND listed by their own company-filtered endpoint.
INDEXED = {
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
}

# Sorted by created_at, but the query that does it never filters on
# organisation_id, so an index leading with organisation_id cannot serve it.
# Each of these is reached through a parent row; the foreign-key index is
# what the sort rides on.
EXCLUDED = {
    "bills_billitem": "read as bill.items — filtered by bill_id",
    "bills_billpayment": "read as bill.payments — filtered by bill_id",
    "pos_posorderitem": "read as order.items — filtered by posorder_id",
    "quotes_quoteitem": "read as quote.items — filtered by quote_id",
    "storefront_storefrontorderitem": "read as order.items — filtered by order_id",
    "helpdesk_ticketcomment": "read as ticket.comments — filtered by ticket_id",
    "payroll_payslipdelivery": "filtered by payroll run, not by company alone",
    "accounting_periodpostinggrant": "filtered by period_id",
    "einvoicing_firsconfig": "one row per company — nothing to sort",
    "einvoicing_firssubmission": "reached through the invoice it belongs to",
    "einvoicing_sandboxtestrun": "developer tooling, not a customer screen",
    "subscriptions_paymenthistory": "looked up by reference, never listed by date",
    "tenancy_partneraccessrequest": "looked up by partner and company equality",
    "tenancy_partnerclientlink": "looked up by partner and company equality",
}


def _tenant_models_sorted_by_created_at():
    """Models whose default ordering makes every list query sort on created_at."""
    found = {}
    for model in apps.get_models():
        if model._meta.abstract or model._meta.proxy:
            continue
        cols = {f.column for f in model._meta.fields}
        if not {"organisation_id", "created_at"} <= cols:
            continue
        ordering = list(getattr(model._meta, "ordering", None) or [])
        if ordering and ordering[0].lstrip("-") == "created_at":
            found[model._meta.db_table] = model
    return found


class TheIndexExists(TestCase):
    """Each of the 16 tables carries an index led by (organisation_id, created_at)."""

    def _leading_columns(self, table):
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, table)
        return [
            c["columns"][:2]
            for c in constraints.values()
            if c.get("index") and len(c.get("columns") or []) >= 2
        ]

    def test_every_listed_table_has_the_composite_index(self):
        missing = []
        for table in sorted(INDEXED):
            if ["organisation_id", "created_at"] not in self._leading_columns(table):
                missing.append(table)
        self.assertEqual(
            missing, [],
            "these tables have no index starting (organisation_id, created_at), so "
            "'the newest N for this company' sorts every matching row on every "
            "page load",
        )

    def test_the_index_leads_with_organisation_id(self):
        """
        Order matters. (created_at, organisation_id) would look similar and be
        useless — the company filter is an equality test and has to come first
        for the sort to come out of the index already ordered.
        """
        for table in sorted(INDEXED):
            pairs = self._leading_columns(table)
            self.assertNotIn(
                ["created_at", "organisation_id"], pairs,
                f"{table} has the two columns the wrong way round",
            )


class NothingSlipsThrough(TestCase):
    """The guard that keeps this honest as tables are added."""

    def test_every_created_at_sorted_table_is_classified(self):
        unclassified = sorted(
            set(_tenant_models_sorted_by_created_at()) - INDEXED - set(EXCLUDED)
        )
        self.assertEqual(
            unclassified, [],
            "these tables sort by created_at under a company filter but appear in "
            "neither list. Add the index (INDEXED, plus a line in migration 0017) "
            "or record why it is not needed (EXCLUDED). See NEW-6.",
        )

    def test_the_two_lists_do_not_overlap(self):
        both = INDEXED & set(EXCLUDED)
        self.assertEqual(both, set(), "a table cannot be both indexed and excluded")

    def test_excluded_tables_still_exist(self):
        """An exclusion for a table that no longer exists is a stale excuse."""
        live = {
            m._meta.db_table
            for m in apps.get_models()
            if not (m._meta.abstract or m._meta.proxy)
        }
        gone = sorted(set(EXCLUDED) - live)
        self.assertEqual(gone, [], "these exclusions name tables that no longer exist")
