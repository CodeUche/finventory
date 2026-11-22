"""
The one VAT function (apps.tax.vat.compute_vat) must move with the sales ledger: whatever the
ledger books to Output VAT on a day, the VAT figure shows for that same day.

VAT 7.5%, a 2 x 1,000 sale: net 2,000, VAT 150, total 2,150.

Rule since the tax review: VAT is due at the EARLIEST of invoice, receipt or delivery
(NTA 2025 s.146(1)); the old "delivery" setting is gone. An invoice stamped "delivery" before
that is "older": its ledger entries are left alone and the worksheet flags it.
"""
import unittest
from datetime import date, datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.accounting.models import JournalEntry, JournalLine
from apps.accounting.services import AccountingService
from apps.sales.models import Invoice
from apps.sales.test_new_sale_and_invoice import URL
from apps.sales.test_sales_ledger import LedgerBase
from apps.tax.vat import compute_vat

D = Decimal


def legacy_delivery():
    """Make an invoice the way the old code stamped one under the removed 'delivery' setting."""
    return patch("apps.sales.rules.vat_timing", return_value="delivery")


class VatBase(LedgerBase):
    def vat_result(self, d_from=None, d_to=None):
        today = timezone.localdate()
        return compute_vat(self.org, d_from or today - timedelta(days=40), d_to or today + timedelta(days=40),
                           with_previous_methods=False)

    def ledger_vat(self, d_from, d_to):
        """Credits less debits on the Output VAT account for entries dated in the range."""
        rows = JournalLine.objects.filter(
            account=self.acct("vat"), journal_entry__organisation=self.org, journal_entry__status="posted",
            journal_entry__entry_date__gte=d_from, journal_entry__entry_date__lte=d_to)
        return sum((r.credit - r.debit for r in rows), D("0"))

    def assert_agrees(self, d_from, d_to, expected):
        v = self.vat_result(d_from, d_to)
        self.assertEqual(v["output_vat"], D(expected), "VAT function")
        self.assertEqual(self.ledger_vat(d_from, d_to), D(expected), "Output VAT account in the ledger")

    def at(self, when):
        """Run the next call as if it were `when` (a date) in Lagos."""
        moment = datetime(when.year, when.month, when.day, 12, 0, tzinfo=dt_tz.utc)
        return patch("django.utils.timezone.now", return_value=moment)


class VatFollowsLedgerTests(VatBase):
    def test_normal_sale_counts_150_and_agrees(self):
        self.sale()
        v = self.vat_result()
        self.assertEqual(v["output_vat"], D("150"))
        self.assertEqual(-self.gl("vat"), D("150"))
        self.assertEqual(v["reconciliation"]["output_difference"], D("0"))

    def test_deposit_on_a_proforma_counts_its_vat_on_the_receipt_date(self):
        inv = self.sale(is_proforma=True, amount_paid="0")
        self.assertEqual(self.vat_result()["output_vat"], D("0"))          # a proforma owes nothing yet
        self.pay(inv, 500)
        v = self.vat_result()
        self.assertEqual(v["output_vat"], D("34.88"))                       # 500 x 150 / 2150
        dep = [l for l in v["lines"] if "deposit" in l["reason"]]
        self.assertEqual([(l["vat_amount"], l["date"]) for l in dep], [(D("34.88"), str(timezone.localdate()))])
        self.assertEqual(v["reconciliation"]["output_difference"], D("0"))

    def test_confirming_the_proforma_counts_the_vat_once_not_twice(self):
        inv = self.sale(is_proforma=True, amount_paid="0")
        self.pay(inv, 500)
        self.api.post(f"{URL}{inv.id}/confirm_proforma/")
        v = self.vat_result()
        self.assertEqual(sorted(l["vat_amount"] for l in v["lines"] if l["kind"] == "sale"),
                         [D("34.88"), D("115.12")])
        self.assertEqual(v["output_vat"], D("150"))
        self.assertEqual(v["reconciliation"]["output_difference"], D("0"))

    def test_a_proforma_confirmed_in_a_later_month_is_counted_in_that_month(self):
        # Her probe S5: the ledger dates the sale on the confirmation day; the invoice must too.
        today = timezone.localdate()
        inv = self.sale(is_proforma=True, amount_paid="0")
        Invoice.objects.filter(id=inv.id).update(issue_date=today - timedelta(days=45))   # raised long ago
        later = today + timedelta(days=3)
        with self.at(later):
            self.assertEqual(self.api.post(f"{URL}{inv.id}/confirm_proforma/").status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.issue_date, later)          # the tax invoice is issued on confirmation
        self.assert_agrees(later, later, "150")
        self.assert_agrees(today - timedelta(days=60), later - timedelta(days=1), "0")

    def test_a_fulfil_later_sale_books_its_vat_when_raised_and_delivery_adds_nothing(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        inv.refresh_from_db()
        self.assertEqual(inv.vat_timing, "invoice")
        self.assertEqual(self.vat_result()["output_vat"], D("150"))
        self.assertEqual(-self.gl("vat"), D("150"))
        self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertEqual(self.vat_result()["output_vat"], D("150"))
        self.assertEqual(-self.gl("vat"), D("150"))

    @override_settings(SALES_VAT_TIMING="delivery")
    def test_the_old_delivery_setting_is_ignored(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        inv.refresh_from_db()
        self.assertEqual(inv.vat_timing, "invoice")
        self.assertEqual(-self.gl("vat"), D("150"))                          # booked when raised

    def test_a_deposit_on_a_fulfil_later_invoice_stamped_delivery_still_carries_vat_on_receipt(self):
        with legacy_delivery():
            inv = self.sale(is_proforma=True, amount_paid="0")
        self.pay(inv, 500)
        self.assertEqual(-self.gl("vat"), D("34.88"))                        # was 0 under the old gate


class OlderInvoiceTests(VatBase):
    def make_older(self, **kw):
        with legacy_delivery():
            return self.sale(defer_fulfillment=True, **kw)

    def test_an_older_invoice_is_counted_at_the_earliest_date_and_flagged(self):
        inv = self.make_older(amount_paid="0")
        self.assertEqual(-self.gl("vat"), D("0"))                            # its ledger entries are left alone
        v = self.vat_result()
        self.assertEqual(v["output_vat"], D("150"))                          # but the worksheet counts it at issue
        line = [l for l in v["lines"] if l["source_ref"] == inv.invoice_number][0]
        self.assertTrue(line["older_invoice"])
        self.assertIn("Older invoice", line["reason"])
        self.assertTrue(any("Older invoice" in w for w in v["warnings"]))

    def test_an_older_invoice_paid_before_it_was_issued_counts_at_first_receipt(self):
        inv = self.make_older(amount_paid="0")
        today = timezone.localdate()
        Invoice.objects.filter(id=inv.id).update(issue_date=today + timedelta(days=5))
        from apps.sales.models import SalePayment
        SalePayment.objects.create(organisation=self.org, invoice=inv, amount=D("100"), method="cash")
        v = self.vat_result(today, today)                                    # the receipt is today
        self.assertEqual(v["output_vat"], D("150"))


class VoidTests(VatBase):
    def test_void_in_the_same_month_nets_to_zero_there(self):
        inv = self.sale(defer_fulfillment=True)
        today = timezone.localdate()
        self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        v = self.vat_result(today, today)
        self.assertEqual(v["output_vat"], D("0"))
        self.assertEqual(sorted(l["vat_amount"] for l in v["lines"] if l["kind"] in ("sale", "sale_void")),
                         [D("-150"), D("150")])
        self.assert_agrees(today, today, "0")

    def test_void_in_a_later_month_keeps_the_original_month_and_goes_negative_in_the_void_month(self):
        inv = self.sale(defer_fulfillment=True)
        today = timezone.localdate()
        later = today + timedelta(days=40)
        with self.at(later):
            self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        # the month already filed does not change
        self.assert_agrees(today, today + timedelta(days=30), "150")
        # the void month carries the reversal
        self.assert_agrees(later, later, "-150")
        v = self.vat_result(later, later)
        self.assertEqual([l["kind"] for l in v["lines"]], ["sale_void"])

    def test_refunding_a_deposit_by_voiding_the_proforma_reduces_vat_in_the_refund_month(self):
        inv = self.sale(is_proforma=True, amount_paid="0")
        self.pay(inv, 500)
        today = timezone.localdate()
        later = today + timedelta(days=40)
        with self.at(later):
            res = self.api.post(f"{URL}{inv.id}/void/")
            self.assertEqual(res.status_code, 200, getattr(res, "data", None))
        self.assert_agrees(today, today + timedelta(days=30), "34.88")      # filed month unchanged
        self.assert_agrees(later, later, "-34.88")                          # refund month reduced

    def test_a_voided_invoice_that_never_reached_the_ledger_is_not_counted_at_all(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        JournalEntry.objects.filter(organisation=self.org).delete()
        Invoice.objects.filter(id=inv.id).update(status="voided")
        self.assertEqual(self.vat_result()["output_vat"], D("0"))


class DeliveryChargeTests(VatBase):
    @override_settings(SALES_DELIVERY_VAT_FOLLOWS_GOODS=True)
    def test_delivery_charge_vat_is_in_the_vat_figure(self):
        inv = self.ok(items=[self.line()], shipping_amount="500", amount_paid="0", payment_method="credit")
        # goods VAT 150 + delivery VAT 37.50 = 187.50 on the invoice header
        self.assertEqual(inv.tax_amount, D("187.50"))
        v = self.vat_result()
        self.assertEqual(v["output_vat"], D("187.50"))
        self.assertEqual(v["invoice_vat_mismatches"], [])
        self.assertEqual(-self.gl("vat"), D("187.50"))

    def test_with_the_switch_off_delivery_carries_no_vat(self):
        inv = self.ok(items=[self.line()], shipping_amount="500", amount_paid="0", payment_method="credit")
        self.assertEqual(inv.tax_amount, D("150"))
        self.assertEqual(self.vat_result()["output_vat"], D("150"))


class ReturnAndRetryTests(VatBase):
    def test_a_return_on_a_sale_that_never_reached_the_ledger_is_refused(self):
        inv = self.sale()
        Invoice.objects.filter(id=inv.id).update(gl_post_status="not_configured")
        item = inv.items.get()
        res = self.api.post(f"{URL}{inv.id}/process_return/", {
            "items": [{"sale_item_id": str(item.id), "quantity_returned": "1"}]}, format="json")
        self.assertEqual(res.status_code, 422, getattr(res, "data", None))
        self.assertIn("Post this sale first", res.data["error"])
        self.assertEqual(self.entries("sale_return"), [])

    def test_the_retry_dates_a_delivery_on_the_lagos_day_not_the_utc_day(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        late = datetime(2026, 12, 31, 23, 30, tzinfo=dt_tz.utc)               # 00:30 on 1 Jan in Lagos
        Invoice.objects.filter(id=inv.id).update(fulfilled_at=late)
        inv.refresh_from_db()
        JournalEntry.objects.filter(organisation=self.org, source_type="sale").delete()
        with override_settings(TIME_ZONE="Africa/Lagos"):
            timezone.activate("Africa/Lagos")
            try:
                entry = AccountingService.post_sale_journal(self.org, inv, self.user)
            finally:
                timezone.deactivate()
        self.assertEqual(entry.entry_date, date(2027, 1, 1))

    def test_a_reversal_defaults_to_the_lagos_date(self):
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


class BackfillCommandTests(VatBase):
    def test_it_stamps_only_unstamped_proformas_that_already_took_a_deposit(self):
        from django.core.management import call_command
        with_deposit = self.sale(is_proforma=True, amount_paid="0")
        self.pay(with_deposit, 500)
        no_deposit = self.sale(is_proforma=True, amount_paid="0")
        Invoice.objects.filter(id__in=[with_deposit.id, no_deposit.id]).update(vat_timing=None)
        call_command("backfill_vat_timing", stdout=__import__("io").StringIO())            # report only
        self.assertIsNone(Invoice.objects.get(id=with_deposit.id).vat_timing)
        call_command("backfill_vat_timing", "--apply", stdout=__import__("io").StringIO())
        self.assertEqual(Invoice.objects.get(id=with_deposit.id).vat_timing, "invoice")
        self.assertIsNone(Invoice.objects.get(id=no_deposit.id).vat_timing)


class TurnoverAndRefundEdgeTests(VatBase):
    def test_a_deposit_only_proforma_voided_later_leaves_turnover_unchanged_and_vat_goes_negative(self):
        inv = self.sale(is_proforma=True, amount_paid="0")
        self.pay(inv, 500)
        today = timezone.localdate()
        later = today + timedelta(days=40)
        with self.at(later):
            self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        first = self.vat_result(today, today + timedelta(days=30))
        second = self.vat_result(later, later)
        zero_turnover = {k: D("0") for k in first["turnover"]}
        self.assertEqual(first["turnover"], zero_turnover)      # a proforma never added turnover
        self.assertEqual(second["turnover"], zero_turnover)     # so its void takes none back
        self.assertEqual(second["output_vat"], D("-34.88"))

    def test_a_real_sale_voided_later_takes_its_turnover_back_in_the_void_month_only(self):
        inv = self.sale(defer_fulfillment=True)
        today = timezone.localdate()
        later = today + timedelta(days=40)
        with self.at(later):
            self.api.post(f"{URL}{inv.id}/void/")
        self.assertEqual(self.vat_result(today, today + timedelta(days=30))["turnover"]["taxable_standard"], D("2000"))
        self.assertEqual(self.vat_result(later, later)["turnover"]["taxable_standard"], D("-2000"))

    def test_a_partial_deposit_refund_that_is_not_a_void(self):
        # No code path posts a "sale_refund" entry. The only ways a deposit comes back are the void
        # (one mirror entry, tested above) and a negative payment recorded through /pay/.
        inv = self.sale(is_proforma=True, amount_paid="0")
        self.pay(inv, 500)
        res = self.api.post(f"{URL}{inv.id}/pay/", {"amount": "-200", "method": "cash"}, format="json")
        self.assertIn(res.status_code, (400, 422), getattr(res, "data", None))     # refused, not silently half-booked
        self.assertEqual(self.entries("sale_refund"), [])
        self.assertEqual(self.vat_result()["output_vat"], D("34.88"))
        self.assertEqual(-self.gl("vat"), D("34.88"))


class DeliveryChargeReturnTests(VatBase):
    """BLOCKER for ever switching SALES_DELIVERY_VAT_FOLLOWS_GOODS on (it stays OFF): a return only hands
    back the VAT of the goods lines (SaleReturnItem.tax_refund), never the VAT on the delivery charge, and
    the delivery charge itself is in no turnover line. Fixing it means changing how returns refund and post
    (the return model, its journal and the e-invoice credit note), which is not a small change."""

    def full_return(self):
        inv = self.ok(items=[self.line()], shipping_amount="500", amount_paid="2687.50")   # 2,000 + 500 + 187.50
        self.assertEqual(inv.tax_amount, D("187.50"))
        item = inv.items.get()
        res = self.api.post(f"{URL}{inv.id}/process_return/", {
            "items": [{"sale_item_id": str(item.id), "quantity_returned": "2"}]}, format="json")
        self.assertIn(res.status_code, (200, 201), getattr(res, "data", None))

    @override_settings(SALES_DELIVERY_VAT_FOLLOWS_GOODS=True)
    def test_after_a_full_return_the_vat_figure_and_the_ledger_agree_even_though_delivery_vat_stays(self):
        self.full_return()
        v = self.vat_result()
        self.assertEqual(-self.gl("vat"), v["output_vat"])
        self.assertEqual(v["output_vat"], D("37.50"))          # goods VAT 150 came back, delivery VAT 37.50 did not

    @unittest.expectedFailure
    @override_settings(SALES_DELIVERY_VAT_FOLLOWS_GOODS=True)
    def test_a_full_return_should_hand_back_the_delivery_vat_too(self):
        self.full_return()
        self.assertEqual(self.vat_result()["output_vat"], D("0"))
