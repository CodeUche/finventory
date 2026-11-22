"""
The one VAT function (apps.tax.vat.compute_vat) must move with the 0.4.0 sales
ledger: whatever the ledger books to Output VAT on a day, the VAT figure shows
for that same day. Each test states the numbers (VAT 7.5%, 2 x 1,000 sale:
net 2,000, VAT 150, total 2,150).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import override_settings
from django.utils import timezone

from apps.accounting.models import JournalEntry
from apps.accounting.services import AccountingService
from apps.sales.models import Invoice
from apps.sales.test_new_sale_and_invoice import URL
from apps.sales.test_sales_ledger import LedgerBase
from apps.tax.vat import compute_vat

D = Decimal


class VatFollowsLedgerTests(LedgerBase):
    def vat_result(self):
        today = timezone.localdate()
        return compute_vat(self.org, today - timedelta(days=40), today + timedelta(days=40),
                           with_previous_methods=False)

    def assert_agrees_with_ledger(self, expected):
        v = self.vat_result()
        self.assertEqual(v["output_vat"], D(expected), "VAT function")
        self.assertEqual(-self.gl("vat"), D(expected), "Output VAT account in the ledger")
        self.assertEqual(v["reconciliation"]["output_difference"], D("0"), "function vs ledger")

    def test_normal_sale_counts_150_and_agrees(self):
        self.sale()
        self.assert_agrees_with_ledger("150")

    def test_deposit_on_a_proforma_counts_its_vat_on_the_receipt_date(self):
        inv = self.sale(is_proforma=True, amount_paid="0")
        self.assert_agrees_with_ledger("0")                # a proforma owes nothing yet
        self.pay(inv, 500)
        # 500 x 150 / 2150 = 34.88 booked the day the money arrives
        v = self.vat_result()
        self.assertEqual(v["output_vat"], D("34.88"))
        dep = [l for l in v["lines"] if "deposit" in l["reason"]]
        self.assertEqual([(l["vat_amount"], l["date"]) for l in dep],
                         [(D("34.88"), str(timezone.localdate()))])
        self.assert_agrees_with_ledger("34.88")

    def test_confirming_the_proforma_counts_the_vat_once_not_twice(self):
        inv = self.sale(is_proforma=True, amount_paid="0")
        self.pay(inv, 500)
        self.api.post(f"{URL}{inv.id}/confirm_proforma/")
        v = self.vat_result()
        # 34.88 on the deposit + 115.12 on the invoice = 150.00
        self.assertEqual(sorted(l["vat_amount"] for l in v["lines"] if l["kind"] == "sale"),
                         [D("34.88"), D("115.12")])
        self.assert_agrees_with_ledger("150")

    def test_voiding_a_paid_fulfil_later_sale_takes_its_vat_out_of_both(self):
        inv = self.sale(defer_fulfillment=True)            # raised on "invoice" timing: VAT booked now
        self.assert_agrees_with_ledger("150")
        self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        self.assert_agrees_with_ledger("0")

    def test_voiding_a_proforma_with_a_deposit_takes_the_deposit_vat_out(self):
        inv = self.sale(is_proforma=True, amount_paid="0")
        self.pay(inv, 500)
        self.assertEqual(self.vat_result()["output_vat"], D("34.88"))
        inv.refresh_from_db()
        res = self.api.post(f"{URL}{inv.id}/void/")
        self.assertEqual(res.status_code, 200, getattr(res, "data", None))
        self.assert_agrees_with_ledger("0")

    @override_settings(SALES_VAT_TIMING="delivery")
    def test_delivery_timing_books_vat_only_when_delivered(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        inv.refresh_from_db()
        self.assertEqual(inv.vat_timing, "delivery")        # the stamp put on it when it was raised
        self.assert_agrees_with_ledger("0")                 # not delivered: no VAT in either
        self.assertEqual(self.api.post(f"{URL}{inv.id}/fulfill/").status_code, 200)
        self.assert_agrees_with_ledger("150")

    @override_settings(SALES_VAT_TIMING="delivery")
    def test_the_stamp_beats_a_later_change_of_the_setting(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")      # stamped "delivery"
        with override_settings(SALES_VAT_TIMING="invoice"):
            self.assert_agrees_with_ledger("0")                       # still follows the stamp
            self.api.post(f"{URL}{inv.id}/fulfill/")
            self.assert_agrees_with_ledger("150")

    def test_invoice_timing_books_a_fulfil_later_sale_when_raised_and_delivery_adds_nothing(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        inv.refresh_from_db()
        self.assertEqual(inv.vat_timing, "invoice")
        self.assert_agrees_with_ledger("150")
        self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assert_agrees_with_ledger("150")

    def test_delivery_is_counted_on_the_lagos_date_not_the_utc_date(self):
        # 23:30 UTC on 31 Dec is 00:30 on 1 Jan in Lagos (UTC+1).
        from datetime import datetime, timezone as dt_tz
        from apps.tax.vat import _effective_vat_date
        inv = Invoice(is_deferred=True, issue_date=date(2026, 12, 20), vat_timing="delivery",
                      fulfilled_at=datetime(2026, 12, 31, 23, 30, tzinfo=dt_tz.utc))
        with override_settings(TIME_ZONE="Africa/Lagos"):
            timezone.activate("Africa/Lagos")
            try:
                with self.settings(USE_TZ=True):
                    from unittest.mock import patch
                    with patch("apps.sales.ledger.is_new_style_deferred", return_value=True):
                        self.assertEqual(_effective_vat_date(inv), date(2027, 1, 1))
            finally:
                timezone.deactivate()

    def test_a_reversal_defaults_to_the_lagos_date(self):
        from datetime import datetime, timezone as dt_tz
        from unittest.mock import patch
        inv = self.sale()
        entry = JournalEntry.objects.get(organisation=self.org, source_type="sale", source_ref=str(inv.id))
        late_utc = datetime(2026, 12, 31, 23, 30, tzinfo=dt_tz.utc)
        timezone.activate("Africa/Lagos")
        try:
            with patch("django.utils.timezone.now", return_value=late_utc):
                rev = AccountingService.reverse_journal_entry(entry, self.user)
        finally:
            timezone.deactivate()
        self.assertEqual(rev.entry_date, date(2027, 1, 1))
