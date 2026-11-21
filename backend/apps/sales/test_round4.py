"""Round 4: a walk-in quote never turns into a paid sale; void locks the customer first."""

from collections import Counter
from datetime import date, timedelta
from unittest.mock import patch

from django.db.models.query import QuerySet

from apps.accounting.models import JournalEntry
from apps.quotes.models import Quote
from apps.sales.models import Invoice, SalePayment
from apps.sales.test_new_sale_and_invoice import D, URL
from apps.sales.test_sales_ledger import LedgerBase


class QuoteConversionTests(LedgerBase):
    def setUp(self):
        super().setUp()
        from apps.accounting.tests import _upgrade_to_business
        _upgrade_to_business(self.org)

    def quote(self, with_customer):
        body = {"warehouse": str(self.wh.id), "issue_date": str(date.today()),
                "valid_until": str(date.today() + timedelta(days=30)),
                "items": [{"product": str(self.taxed.id), "quantity": 2}]}
        if with_customer:
            body["customer"] = str(self.customer.id)
        res = self.api.post("/api/v1/quotes/", body, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return res.data["id"]

    def test_a_walk_in_quote_cannot_be_converted_and_nothing_is_invented(self):
        qid = self.quote(False)
        res = self.api.post(f"/api/v1/quotes/{qid}/convert/")
        self.assertEqual(res.status_code, 422)
        self.assertIn("customer", res.data["error"].lower())
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)
        self.assertEqual(SalePayment.objects.filter(organisation=self.org).count(), 0)
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org, source_type="sale").count(), 0)
        self.assertEqual(self.on_hand(self.taxed), D("100"))
        self.assertNotEqual(Quote.objects.get(id=qid).status, Quote.CONVERTED)

    def test_the_service_refuses_it_too(self):
        from apps.quotes.services import QuoteService
        q = Quote.objects.get(id=self.quote(False))
        with self.assertRaises(ValueError):
            QuoteService.convert_to_invoice(q, self.user)

    def test_a_walk_in_quote_converts_once_a_customer_is_added(self):
        qid = self.quote(False)
        self.api.patch(f"/api/v1/quotes/{qid}/", {"customer": str(self.customer.id)}, format="json")
        res = self.api.post(f"/api/v1/quotes/{qid}/convert/")
        self.assertEqual(res.status_code, 200, getattr(res, "data", None))

    def test_a_named_customer_quote_converts_as_a_credit_sale_with_no_payment(self):
        """Unchanged behaviour: the customer owes the whole quote; no payment is invented."""
        res = self.api.post(f"/api/v1/quotes/{self.quote(True)}/convert/")
        self.assertEqual(res.status_code, 200, res.data)
        inv = Invoice.objects.get(id=res.data["invoice_id"])
        self.assertEqual((inv.status, inv.amount_paid, inv.amount_due), ("credit", D("0"), inv.total_amount))
        self.assertEqual(SalePayment.objects.filter(invoice=inv).count(), 0)
        self.assertEqual(self.gl("ar"), inv.total_amount)
        self.assertEqual(self.gl("cash") + self.gl("bank"), D("0"))


class VoidLockOrderTests(LedgerBase):
    def test_void_locks_the_customer_before_it_moves_stock(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        order = []
        real = QuerySet.select_for_update

        def spy(qs, *a, **k):
            order.append(qs.model.__name__)
            return real(qs, *a, **k)

        with patch.object(QuerySet, "select_for_update", spy):
            self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        self.assertIn("Customer", order)
        self.assertIn("StockItem", order)
        self.assertLess(order.index("Customer"), order.index("StockItem"), order)


class PlainLineErrorTests(LedgerBase):
    def create(self, **line):
        return self.post(items=[self.line(**line)], amount_paid="0")

    def edit(self, inv, **line):
        item = {"product_id": str(self.taxed.id), "quantity": 1, "unit_price": "1000", **line}
        return self.api.patch(f"{URL}{inv.id}/edit_lines/", {"items": [item]}, format="json")

    def assert_plain(self, res, status, *words):
        self.assertEqual(res.status_code, status, res.data)
        msg = res.data["error"]
        self.assertIsInstance(msg, str)
        for bad in ("ErrorDetail", "min_value", "max_value", "{", "'"):
            self.assertNotIn(bad, msg)
        for w in words:
            self.assertIn(w, msg.lower())

    def test_negative_price_on_create(self):
        self.assert_plain(self.create(price="-500"), 400, "unit price", "negative")

    def test_zero_quantity_on_create(self):
        self.assert_plain(self.create(qty=0), 400, "quantity", "greater than zero")

    def test_discount_out_of_range_on_create(self):
        self.assert_plain(self.create(discount_percent="150"), 400, "discount", "between 0 and 100")

    def test_negative_tax_rate_on_create(self):
        self.assert_plain(self.create(tax_rate="-7.5"), 400, "tax rate", "between 0 and 100")

    def test_edit_lines_says_it_in_plain_words_too(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        self.assert_plain(self.edit(inv, unit_price="-5"), 422, "unit price", "negative")
        self.assert_plain(self.edit(inv, quantity=-1), 422, "quantity")
        self.assert_plain(self.edit(inv, discount_percent=101), 422, "discount")

    def test_other_errors_keep_the_old_shape(self):
        res = self.post(items=[])
        self.assertEqual(res.status_code, 400)
        self.assertIn("error", res.data)
