"""
Accountant review round: old-style data on void/delete/delivery, retry after
void, confirmation dating, cheque, store credit with no ledger source, the VAT
timing stamp, and edits that re-post the ledger.
"""

from datetime import date
from decimal import Decimal

from unittest.mock import patch
from django.test import override_settings

from apps.accounting.models import FinancialPeriod, JournalEntry, JournalLine
from apps.accounting.services import AccountingService
from apps.credits.services import CreditService
from apps.customers.models import Customer
from apps.sales import ledger
from apps.sales.models import Invoice, SalePayment
from apps.sales.test_new_sale_and_invoice import D, URL
from apps.sales.test_sales_ledger import LedgerBase


class Zero(LedgerBase):
    def zero_everywhere(self, roles=("cash", "bank", "ar", "deposits", "vat", "revenue", "cogs", "inventory")):
        for role in roles:
            self.assertEqual(self.gl(role), D("0"), role)


# ── A1: old-style receipts ──────────────────────────────────────────────────
class OldStyleReceiptTests(Zero):
    def old_credit_payment(self, inv, amount, method="cash"):
        """A credit-invoice payment exactly as the OLD code recorded it: the credit
        service posts the journal (source_ref CRPAY-<credit txn id>), the payment
        row is not flagged, no sale_receipt entry exists."""
        CreditService.record_payment(
            organisation=self.org, customer=self.customer, amount=D(amount), recorded_by=self.user,
            description=f"Credit payment – {inv.invoice_number}", method=method,
        )
        SalePayment.objects.create(organisation=self.org, invoice=inv, amount=D(amount), method=method,
                                   received_by=self.user)
        Invoice.objects.filter(pk=inv.pk).update(
            amount_paid=inv.amount_paid + D(amount), amount_due=inv.amount_due - D(amount),
            status="partially_paid")
        inv.refresh_from_db()

    def old_gateway_payment(self, inv, amount, method="bank_transfer"):
        p = SalePayment.objects.create(organisation=self.org, invoice=inv, amount=D(amount), method=method,
                                       received_by=None)
        AccountingService.post_gateway_payment_journal(self.org, inv, p, provider="paystack")
        Invoice.objects.filter(pk=inv.pk).update(
            amount_paid=inv.amount_paid + D(amount), amount_due=inv.amount_due - D(amount),
            status="partially_paid")
        inv.refresh_from_db()
        return p

    def test_void_of_an_old_part_paid_credit_invoice_reverses_the_receipt(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        self.old_credit_payment(inv, "1000")
        self.assertEqual(self.gl("cash"), D("1000"))
        self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        self.zero_everywhere()

    def test_delete_of_an_old_part_paid_credit_invoice_reverses_the_receipt(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        self.old_credit_payment(inv, "1000")
        self.assertEqual(self.api.post(f"{URL}{inv.id}/delete_invoice/").status_code, 204)
        self.zero_everywhere()

    def test_void_of_an_invoice_with_an_old_gateway_payment_reverses_it(self):
        inv = self.sale(amount_paid="1000.00")                 # part paid, rest owed
        self.old_gateway_payment(inv, "500")
        self.assertEqual(self.gl("bank"), D("500"))
        self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        self.zero_everywhere()

    def test_old_style_deferred_delivery_does_not_debit_cash_twice_for_a_gateway_payment(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        for e in self.entries("sale_deferred", inv.id):         # make it an old-style invoice
            JournalLine.objects.filter(journal_entry=e).delete()
            JournalEntry.objects.filter(pk=e.pk).delete()
        self.old_gateway_payment(inv, "2150")
        self.assertEqual(self.api.post(f"{URL}{inv.id}/fulfill/").status_code, 200)
        self.assertEqual(self.gl("bank"), D("2150"))            # once
        self.assertEqual(self.gl("cash"), D("0"))
        self.assertEqual(self.gl("ar"), D("0"))
        self.assert_all_balanced()


# ── A2: retry after void ────────────────────────────────────────────────────
class RetryAfterVoidTests(Zero):
    def test_a_voided_invoice_is_never_reposted(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        self.api.post(f"{URL}{inv.id}/void/")
        before = JournalEntry.objects.filter(organisation=self.org).count()
        ok, msg = AccountingService.retry_gl_post(self.org, "invoice", str(inv.id), self.user)
        self.assertFalse(ok)
        self.assertIn("voided", msg.lower())
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org).count(), before)
        self.zero_everywhere()

    def test_post_sale_journal_itself_refuses_a_voided_invoice(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        self.api.post(f"{URL}{inv.id}/void/")
        inv.refresh_from_db()
        with self.assertRaises(ValueError):
            AccountingService.post_sale_journal(self.org, inv, self.user)


# ── A3: confirmation date ───────────────────────────────────────────────────
class ConfirmDateTests(Zero):
    def test_a_proforma_is_dated_at_confirmation_not_at_the_proforma_date(self):
        inv = self.sale(is_proforma=True, amount_paid="0", issue_date="2020-03-01")
        self.assertEqual(self.api.post(f"{URL}{inv.id}/confirm_proforma/").status_code, 200)
        e = self.entries("sale", inv.id)[0]
        self.assertEqual(e.entry_date, date.today())

    def test_a_locked_confirmation_period_fails_loudly_and_moves_no_stock(self):
        inv = self.sale(is_proforma=True, amount_paid="0", issue_date="2020-03-01")
        today = date.today()
        FinancialPeriod.objects.create(organisation=self.org, year=today.year, month=today.month, is_locked=True)
        res = self.api.post(f"{URL}{inv.id}/confirm_proforma/")
        self.assertEqual(res.status_code, 422)
        self.assertIn("locked", res.data["error"].lower())
        inv.refresh_from_db()
        self.assertEqual(inv.status, "proforma")
        self.assertEqual(self.on_hand(self.taxed), D("100"))
        self.assertEqual(self.entries("sale", inv.id), [])

    def test_a_deferred_proforma_confirms_dated_today_too(self):
        inv = self.sale(is_proforma=True, defer_fulfillment=True, amount_paid="0", issue_date="2020-03-01")
        self.api.post(f"{URL}{inv.id}/confirm_proforma/")
        self.assertEqual(self.entries("sale_deferred", inv.id)[0].entry_date, date.today())


# ── A4: cheque / mixed ──────────────────────────────────────────────────────
class ChequeTests(Zero):
    def test_a_cheque_payment_lands_in_the_bank_not_the_cash_drawer(self):
        inv = self.sale(payment_method="cheque")
        self.assertEqual(self.gl("bank"), D("2150"))
        self.assertEqual(self.gl("cash"), D("0"))

    def test_a_later_cheque_receipt_lands_in_the_bank(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        self.pay(inv, 1000, "cheque")
        self.assertEqual(self.gl("bank"), D("1000"))
        self.assertEqual(self.gl("cash"), D("0"))

    def test_mixed_is_refused_as_a_single_tender(self):
        res = self.post(payment_method="mixed")
        self.assertEqual(res.status_code, 422)
        self.assertIn("separate", res.data["error"].lower())
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)


# ── A5: store credit has no back door ───────────────────────────────────────
class StoreCreditReadOnlyTests(Zero):
    def test_store_credit_cannot_be_typed_in_through_the_customer_api(self):
        res = self.api.post("/api/v1/customers/", {"name": "New Cust", "code": "NC1", "store_credit": "5000"},
                            format="json")
        self.assertIn(res.status_code, (200, 201), getattr(res, "data", None))
        c = Customer.objects.get(id=res.data["id"])
        self.assertEqual(c.store_credit, D("0"))
        res = self.api.patch(f"/api/v1/customers/{self.customer.id}/", {"store_credit": "9999"}, format="json")
        self.assertIn(res.status_code, (200, 400))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.store_credit, D("0"))

    def test_store_credit_is_still_shown_by_the_api(self):
        res = self.api.get(f"/api/v1/customers/{self.customer.id}/")
        self.assertIn("store_credit", res.data)


# ── A6: VAT timing is stamped per invoice ───────────────────────────────────
class VatTimingStampTests(Zero):
    def test_the_rule_in_force_is_stamped_on_the_invoice(self):
        inv = self.sale()
        self.assertEqual(inv.vat_timing, "invoice")
        # NTA 2025 s.146(1): VAT is due at the earliest of invoice, receipt or delivery, so the
        # old "delivery" setting is no longer a choice: it is ignored and every new invoice is
        # stamped "invoice". (This used to assert the stamp became "delivery".)
        with override_settings(SALES_VAT_TIMING="delivery"):
            self.assertEqual(self.sale().vat_timing, "invoice")

    def test_flip_invoice_to_delivery_between_raising_and_delivery(self):
        inv = self.sale(defer_fulfillment=True)                  # raised under "invoice": VAT booked now
        self.assertEqual(self.gl("vat"), D("-150"))
        with override_settings(SALES_VAT_TIMING="delivery"):
            self.assertEqual(self.api.post(f"{URL}{inv.id}/fulfill/").status_code, 200)
        self.assertEqual(self.gl("vat"), D("-150"))              # once, not 300, not 0
        self.assertEqual(self.gl("deposits"), D("0"))
        self.assert_all_balanced()

    def test_flip_delivery_to_invoice_between_raising_and_delivery(self):
        # An OLDER invoice stamped "delivery" (raised before the rule changed) keeps its ledger
        # behaviour. The stamp can no longer be created by the setting, so make one the way the old
        # code did. (Was: override_settings(SALES_VAT_TIMING="delivery").)
        with patch("apps.sales.rules.vat_timing", return_value="delivery"):
            inv = self.sale(defer_fulfillment=True)              # VAT not booked yet
            self.assertEqual(self.gl("vat"), D("0"))
        self.assertEqual(self.api.post(f"{URL}{inv.id}/fulfill/").status_code, 200)
        self.assertEqual(self.gl("vat"), D("-150"))              # booked at delivery, not skipped
        self.assertEqual(self.gl("deposits"), D("0"))
        self.assert_all_balanced()

    def test_a_proforma_deposit_and_its_confirmation_agree_after_a_flip(self):
        inv = self.sale(is_proforma=True, amount_paid="0")
        self.pay(inv, 500)
        with override_settings(SALES_VAT_TIMING="delivery"):
            self.api.post(f"{URL}{inv.id}/confirm_proforma/")
        self.assertEqual(self.gl("vat"), D("-150"))
        self.assertEqual(self.gl("deposits"), D("0"))

    def test_an_old_invoice_with_no_stamp_follows_the_current_setting(self):
        inv = self.sale(defer_fulfillment=True)
        Invoice.objects.filter(pk=inv.pk).update(vat_timing=None)
        inv.refresh_from_db()
        self.assertIsNone(inv.vat_timing)
        self.assertEqual(ledger.vat_now(inv), True)
        with override_settings(SALES_VAT_TIMING="delivery"):
            self.assertEqual(ledger.vat_now(inv), True)       # the setting is ignored now (was False)


# ── A7: editing amounts re-posts the ledger ─────────────────────────────────
class EditRepostTests(Zero):
    def edit(self, inv, **body):
        body.setdefault("items", [{"product_id": str(self.taxed.id), "quantity": 1, "unit_price": "1000"}])
        return self.api.patch(f"{URL}{inv.id}/edit_lines/", body, format="json")

    def test_edit_a_credit_invoice_reposts_ar_revenue_vat_cogs_and_the_customer_balance(self):
        inv = self.sale(payment_method="credit", amount_paid="0")        # 2 x 1000 + 150
        res = self.edit(inv)                                             # now 1 x 1000
        self.assertEqual(res.status_code, 200, getattr(res, "data", None))
        inv.refresh_from_db()
        self.assertEqual((inv.total_amount, inv.tax_amount, inv.amount_due), (D("1075"), D("75"), D("1075")))
        self.assertEqual(self.gl("ar"), D("1075"))
        self.assertEqual(self.gl("revenue"), D("-1000"))
        self.assertEqual(self.gl("vat"), D("-75"))
        self.assertEqual(self.gl("cogs"), D("600"))
        self.assertEqual(self.on_hand(self.taxed), D("99"))
        self.assert_subledgers()

    def test_void_after_an_edit_nets_everything_to_zero(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        self.edit(inv)
        self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        for role in ("cash", "bank", "ar", "deposits", "vat", "revenue", "cogs", "inventory"):
            self.assertEqual(self.gl(role), D("0"), role)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, D("0"))
        self.assertEqual(self.on_hand(self.taxed), D("100"))

    def test_edit_a_part_paid_invoice_keeps_the_payment_and_moves_the_balance(self):
        inv = self.sale(amount_paid="1000.00")                           # owes 1150
        res = self.edit(inv)                                             # total now 1075, owes 75
        self.assertEqual(res.status_code, 200, getattr(res, "data", None))
        inv.refresh_from_db()
        self.assertEqual((inv.amount_paid, inv.amount_due), (D("1000"), D("75")))
        self.assertEqual(self.gl("cash"), D("1000"))
        self.assertEqual(self.gl("ar"), D("75"))
        self.assert_subledgers()

    def test_an_edit_that_takes_the_total_below_what_was_paid_is_refused(self):
        inv = self.sale(amount_paid="1500.00")
        res = self.edit(inv)
        self.assertEqual(res.status_code, 422)
        self.assertIn("paid", res.data["error"].lower())
        inv.refresh_from_db()
        self.assertEqual(inv.total_amount, D("2150"))
        self.assertEqual(self.on_hand(self.taxed), D("98"))
        self.assertEqual(self.gl("ar"), D("650"))

    def test_edit_a_fulfil_later_invoice_that_is_not_yet_delivered(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        res = self.edit(inv)
        self.assertEqual(res.status_code, 200, getattr(res, "data", None))
        self.assertEqual(self.on_hand(self.taxed), D("100"))             # nothing moved
        self.assertEqual(self.gl("ar"), D("1075"))
        self.assertEqual(self.gl("deposits"), D("-1000"))
        self.assertEqual(self.gl("vat"), D("-75"))
        self.assertEqual(self.api.post(f"{URL}{inv.id}/fulfill/").status_code, 200)
        self.assertEqual(self.gl("deposits"), D("0"))
        self.assertEqual(self.gl("revenue"), D("-1000"))                 # delivered on the NEW totals
        self.assertEqual(self.on_hand(self.taxed), D("99"))
        self.assert_subledgers()

    def test_an_edit_of_a_delivered_fulfil_later_invoice_is_refused(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        self.api.post(f"{URL}{inv.id}/fulfill/")
        res = self.edit(inv)
        self.assertEqual(res.status_code, 422)
        self.assertIn("void", res.data["error"].lower())

    def test_an_edit_in_a_locked_period_is_refused_and_changes_nothing(self):
        inv = self.sale(payment_method="credit", amount_paid="0", issue_date="2020-03-01")
        FinancialPeriod.objects.create(organisation=self.org, year=2020, month=3, is_locked=True)
        res = self.edit(inv)
        self.assertEqual(res.status_code, 422)
        self.assertIn("locked", res.data["error"].lower())
        inv.refresh_from_db()
        self.assertEqual(inv.total_amount, D("2150"))
        self.assertEqual(self.on_hand(self.taxed), D("98"))
        self.assertEqual(self.gl("ar"), D("2150"))

    def test_a_notes_only_edit_posts_nothing_new(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        n = JournalEntry.objects.filter(organisation=self.org).count()
        res = self.edit(inv, items=[{"product_id": str(self.taxed.id), "quantity": 2, "unit_price": "1000"}],
                        notes="call before delivery")
        self.assertEqual(res.status_code, 200, getattr(res, "data", None))
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org).count(), n)
        inv.refresh_from_db()
        self.assertEqual(inv.notes, "call before delivery")

    def test_changing_the_customer_of_a_posted_invoice_is_refused(self):
        other = Customer.objects.create(organisation=self.org, code="C2", name="Other Co")
        inv = self.sale(payment_method="credit", amount_paid="0")
        res = self.edit(inv, items=[{"product_id": str(self.taxed.id), "quantity": 2, "unit_price": "1000"}],
                        customer_id=str(other.id))
        self.assertEqual(res.status_code, 422)

    def test_a_failed_repost_rolls_the_whole_edit_back(self):
        from unittest.mock import patch
        inv = self.sale(payment_method="credit", amount_paid="0")
        with patch("apps.sales.ledger.post_sale_entry", side_effect=ValueError("ledger down")):
            res = self.edit(inv)
        self.assertEqual(res.status_code, 422)
        inv.refresh_from_db()
        self.assertEqual(inv.total_amount, D("2150"))
        self.assertEqual(self.on_hand(self.taxed), D("98"))
        self.assertEqual(self.gl("ar"), D("2150"))

    def test_edit_with_shipping_change_reposts_too(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        res = self.edit(inv, items=[{"product_id": str(self.taxed.id), "quantity": 2, "unit_price": "1000"}],
                        shipping_amount="300")
        self.assertEqual(res.status_code, 200, getattr(res, "data", None))
        self.assertEqual(self.gl("ar"), D("2450"))
        self.assertEqual(self.gl("revenue"), D("-2300"))
        self.assert_subledgers()
