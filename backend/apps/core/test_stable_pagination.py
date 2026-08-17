"""
NEW-16 — paged lists must come back in an order the database cannot change.

The bug: paging with LIMIT/OFFSET over an unordered (or ambiguously ordered)
query. Page 2 is not guaranteed to continue where page 1 stopped, so a row can
appear on two pages and another on none.

Testing it by actually catching a reordering is not possible on demand — the
database is *allowed* to be consistent, it is simply not obliged to be, and on
a small table it usually is. Passing such a test would mean nothing. So these
tests assert the property that makes reordering impossible instead: every
paged query ends on a column no two rows share.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from apps.core.pagination import ensure_stable_ordering
from apps.sales.models import Invoice
from apps.customers.models import Customer
from apps.inventory.models import Product


class EnsureStableOrdering(TestCase):
    """The rule itself."""

    def test_an_unordered_queryset_gains_an_unambiguous_order(self):
        qs = ensure_stable_ordering(Invoice.objects.all())
        self.assertEqual(list(qs.query.order_by)[-1], "pk")

    def test_an_ambiguous_order_keeps_its_sort_and_gains_a_tiebreak(self):
        qs = ensure_stable_ordering(Customer.objects.order_by("name"))
        self.assertEqual(list(qs.query.order_by), ["name", "pk"])

    def test_a_descending_sort_gets_a_descending_tiebreak(self):
        qs = ensure_stable_ordering(Invoice.objects.order_by("-issue_date"))
        self.assertEqual(list(qs.query.order_by), ["-issue_date", "-pk"])

    def test_an_order_that_is_already_unambiguous_is_left_alone(self):
        qs = ensure_stable_ordering(Invoice.objects.order_by("-issue_date", "id"))
        self.assertEqual(list(qs.query.order_by), ["-issue_date", "id"])

    def test_the_default_sort_for_no_ordering_is_oldest_first(self):
        """
        Deliberate. An unordered scan tends to come back in insertion order, so
        this keeps what these screens already show and only makes it reliable.
        Flipping them to newest-first is a product decision, not this fix.
        """
        qs = ensure_stable_ordering(Invoice.objects.all())
        self.assertEqual(list(qs.query.order_by), ["created_at", "pk"])

    # --- the guards -------------------------------------------------------

    def test_an_aggregate_is_untouched(self):
        """Adding pk here would join the GROUP BY and split the totals."""
        from django.db.models import Count

        qs = Invoice.objects.values("status").annotate(n=Count("id"))
        self.assertEqual(ensure_stable_ordering(qs).query.order_by, qs.query.order_by)

    def test_distinct_on_is_untouched(self):
        """Postgres requires ORDER BY to lead with the DISTINCT ON columns."""
        qs = Invoice.objects.order_by("customer_id").distinct("customer_id")
        self.assertEqual(ensure_stable_ordering(qs).query.order_by, qs.query.order_by)

    def test_a_plain_list_is_returned_unchanged(self):
        """Some views paginate lists, not querysets."""
        rows = [1, 2, 3]
        self.assertIs(ensure_stable_ordering(rows), rows)

    def test_ordering_by_a_related_field_is_left_alone(self):
        qs = Product.objects.order_by("category__name")
        self.assertEqual(ensure_stable_ordering(qs).query.order_by, qs.query.order_by)


class PagedEndpointsAreOrdered(TestCase):
    """The property, end to end, on the endpoint the finding was written about."""

    def setUp(self):
        from apps.payroll.test_track_a import _make_user, _make_org, _auth_client

        self.owner = _make_user("np_owner@example.com")
        self.org = _make_org(self.owner, "Ordering Org")
        self.client_ = _auth_client(self.owner, self.org)

        from apps.inventory.models import Warehouse

        warehouse = Warehouse.objects.create(
            organisation=self.org, name="Main", is_default=True,
        )
        customer = Customer.objects.create(
            organisation=self.org, name="Acme", email="acme@example.com",
        )
        # Same issue_date on every invoice — the tie that makes the order
        # ambiguous in the first place.
        for i in range(5):
            Invoice.objects.create(
                organisation=self.org, customer=customer, warehouse=warehouse,
                invoice_number=f"ORD-{i:03d}", issue_date=date.today(),
                due_date=date.today(), subtotal=Decimal("100"),
                total_amount=Decimal("100"), created_by=self.owner,
            )

    def _list_sql(self):
        with CaptureQueriesContext(connection) as captured:
            res = self.client_.get("/api/v1/sales/invoices/?page_size=2")
            self.assertEqual(res.status_code, 200, res.content[:300])
        return [q["sql"] for q in captured.captured_queries if "sales_invoice" in q["sql"]]

    def test_the_invoice_list_query_is_ordered(self):
        ordered = [s for s in self._list_sql() if "ORDER BY" in s]
        self.assertTrue(
            ordered,
            "the paginated invoice query has no ORDER BY, so the database may "
            "return these rows in a different order on the next request",
        )

    def test_the_invoice_list_order_ends_on_the_primary_key(self):
        paged = [
            s for s in self._list_sql()
            if "ORDER BY" in s and "LIMIT" in s
        ]
        # Asserted, not assumed. Without this the loop below has nothing to
        # iterate when the ORDER BY is missing entirely, and the test passes
        # while proving nothing — which is the exact failure it exists to catch.
        self.assertTrue(
            paged,
            "no ordered, paged query was issued for the invoice list at all",
        )
        for sql in paged:
            tail = sql.split("ORDER BY")[-1]
            self.assertIn(
                '"id"', tail,
                "the paged invoice query does not end on a unique column, so "
                "rows sharing a sort key can move between pages",
            )

    def test_the_ui_sort_control_still_gets_a_tiebreak(self):
        """
        The real path. Sales, Bills, Products, Customers and Stock all send
        ?ordering= from their sort dropdown, so the server-side default never
        applies there — but "-issue_date" is not unique either. Invoices raised
        on the same day can still swap between pages unless the primary key is
        appended after the chosen column.

        This is what stops the sort control and this fix from being mistaken
        for the same thing: the control picks which column, it does not make
        the order unambiguous.
        """
        with CaptureQueriesContext(connection) as captured:
            res = self.client_.get(
                "/api/v1/sales/invoices/?ordering=-issue_date&page_size=2"
            )
            self.assertEqual(res.status_code, 200, res.content[:300])

        paged = [
            q["sql"] for q in captured.captured_queries
            if "sales_invoice" in q["sql"] and "ORDER BY" in q["sql"] and "LIMIT" in q["sql"]
        ]
        self.assertTrue(paged, "no ordered, paged query was issued")
        for sql in paged:
            tail = sql.split("ORDER BY")[-1]
            self.assertIn("issue_date", tail, "the chosen sort column was dropped")
            self.assertIn(
                '"id"', tail,
                "the sort column chosen in the UI was not given a tiebreak, so "
                "invoices sharing an issue date can still move between pages",
            )

    def test_paging_right_through_returns_every_row_exactly_once(self):
        seen = []
        for page in (1, 2, 3):
            res = self.client_.get(f"/api/v1/sales/invoices/?page_size=2&page={page}")
            self.assertEqual(res.status_code, 200)
            seen += [row["id"] for row in res.json()["results"]]
        self.assertEqual(len(seen), 5)
        self.assertEqual(len(set(seen)), 5, "a row appeared on two pages")
