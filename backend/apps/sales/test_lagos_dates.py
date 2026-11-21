"""
"Today for the books" is the business-local date. Production runs
TIME_ZONE=Africa/Lagos (UTC+1), so at 23:30 UTC it is already 00:30 the NEXT day
in Lagos: delivery, void, later-payment and proforma-confirmation entries, and a
sale with no issue date, must carry the Lagos date, not the UTC one.
"""

from datetime import date, datetime, timezone as dt_timezone
from unittest.mock import patch

from django.test import override_settings

from apps.accounting.models import JournalEntry
from apps.sales.models import Invoice
from apps.sales.test_new_sale_and_invoice import D, URL
from apps.sales.test_sales_ledger import LedgerBase

UTC_LATE = datetime(2026, 11, 20, 23, 30, tzinfo=dt_timezone.utc)      # 00:30 on 21 Nov in Lagos
LAGOS_DAY = date(2026, 11, 21)


@override_settings(TIME_ZONE="Africa/Lagos")
class LagosDateTests(LedgerBase):
    def frozen(self):
        return patch("django.utils.timezone.now", return_value=UTC_LATE)

    def test_a_sale_with_no_issue_date_is_dated_the_lagos_day(self):
        with self.frozen():
            inv = self.sale()
        self.assertEqual(inv.issue_date, LAGOS_DAY)
        self.assertEqual(self.entries("sale", inv.id)[0].entry_date, LAGOS_DAY)

    def test_delivery_is_dated_the_lagos_day(self):
        inv = self.sale(defer_fulfillment=True, issue_date="2026-11-01")
        with self.frozen():
            self.assertEqual(self.api.post(f"{URL}{inv.id}/fulfill/").status_code, 200)
        self.assertEqual(self.entries("sale", inv.id)[0].entry_date, LAGOS_DAY)

    def test_a_later_payment_is_dated_the_lagos_day(self):
        inv = self.sale(payment_method="credit", amount_paid="0", issue_date="2026-11-01")
        with self.frozen():
            self.pay(inv, 500)
        e = self.entries("credit_payment", inv.payments.get().id)[0]
        self.assertEqual(e.entry_date, LAGOS_DAY)

    def test_a_proforma_is_confirmed_on_the_lagos_day(self):
        inv = self.sale(is_proforma=True, amount_paid="0", issue_date="2026-11-01")
        with self.frozen():
            self.assertEqual(self.api.post(f"{URL}{inv.id}/confirm_proforma/").status_code, 200)
        self.assertEqual(self.entries("sale", inv.id)[0].entry_date, LAGOS_DAY)

    def test_a_void_is_dated_the_lagos_day(self):
        inv = self.sale(payment_method="credit", amount_paid="0", issue_date="2026-11-01")
        with self.frozen():
            self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        self.assertEqual(self.entries("invoice_void", inv.id)[0].entry_date, LAGOS_DAY)

    def test_a_gateway_payment_is_dated_the_lagos_day(self):
        from apps.accounting.services import AccountingService
        from apps.sales.models import SalePayment
        inv = self.sale(payment_method="credit", amount_paid="0", issue_date="2026-11-01")
        p = SalePayment.objects.create(organisation=self.org, invoice=inv, amount=D("100"), method="bank_transfer")
        with self.frozen():
            AccountingService.post_gateway_payment_journal(self.org, inv, p, provider="paystack")
        e = JournalEntry.objects.get(organisation=self.org, source_type="gateway_payment", source_ref=str(p.id))
        self.assertEqual(e.entry_date, LAGOS_DAY)

    def test_in_utc_the_dates_are_unchanged(self):
        with override_settings(TIME_ZONE="UTC"), self.frozen():
            inv = self.sale()
        self.assertEqual(inv.issue_date, date(2026, 11, 20))
