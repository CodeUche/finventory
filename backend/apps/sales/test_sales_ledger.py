"""
What every sale, payment, delivery, void and return does to the ledger.

VAT 7.5% exclusive unless a test says otherwise. Every test checks that the
journals balance and that Accounts Receivable / Cash / Customer Deposits agree
with the customer and till sub-ledgers.
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings

from apps.accounting.models import FinancialPeriod, JournalEntry, JournalLine
from apps.accounting.services import AccountingService, AccountMappingService
from apps.customers.models import Customer
from apps.inventory.models import Product, StockMovement
from apps.sales import ledger
from apps.sales.models import Invoice, SalePayment
from apps.sales.test_new_sale_and_invoice import Base, D, URL
from apps.tax.models import TaxClass, WHTTransaction


class LedgerBase(Base):
    def setUp(self):
        super().setUp()
        self.vat = TaxClass.objects.create(organisation=self.org, name="VAT 7.5", rate=D("7.5"))
        self.taxed = Product.objects.create(
            organisation=self.org, sku="T1", name="Taxed goods", product_type="physical",
            cost_price=600, selling_price=1000, is_taxable=True, tax_class=self.vat,
        )
        from apps.inventory.services import InventoryService
        InventoryService.record_movement(
            organisation=self.org, product=self.taxed, warehouse=self.wh, quantity=D("100"),
            movement_type="purchase_in", unit_cost=D("600"), created_by=self.user,
        )
        self.taxed_service = Product.objects.create(
            organisation=self.org, sku="TS1", name="Taxed service", product_type="service",
            cost_price=0, selling_price=10000, is_taxable=True, tax_class=self.vat,
        )

    def line(self, product=None, qty=2, price="1000", **kw):
        return {"product_id": str((product or self.taxed).id), "quantity": qty, "unit_price": price, **kw}

    def sale(self, **over):
        """A 2 x 1,000 taxed sale: net 2,000 + VAT 150 = 2,150, paid in full by default."""
        body = {"items": [self.line()], "amount_paid": "2150.00"}
        body.update(over)
        return self.ok(**body)

    def acct(self, role):
        if role == "ar":
            return AccountingService._resolve_party_account(
                self.org, self.customer, "receivable_account", "accounts_receivable", "1100")
        if role == "deposits":
            return ledger.deposits_account(self.org)
        return AccountMappingService.resolve(self.org, {
            "cash": "cash_account", "bank": "bank_account", "vat": "vat_output_account",
            "revenue": "revenue_account", "cogs": "cogs_account", "inventory": "inventory_account",
        }[role])

    def gl(self, role):
        """Net debit balance of the account across every posted entry."""
        a = self.acct(role)
        rows = JournalLine.objects.filter(account=a, journal_entry__organisation=self.org)
        return sum((r.debit - r.credit for r in rows), D("0"))

    def entries(self, source_type, source_ref=None):
        q = JournalEntry.objects.filter(organisation=self.org, source_type=source_type)
        if source_ref is not None:
            q = q.filter(source_ref=str(source_ref))
        return list(q)

    def entry_lines(self, entry):
        out = {}
        for ln in entry.lines.all():
            for role in ("cash", "bank", "ar", "deposits", "vat", "revenue", "cogs", "inventory"):
                if self.acct(role).id == ln.account_id:
                    d, c = out.get(role, (D("0"), D("0")))
                    out[role] = (d + ln.debit, c + ln.credit)
        return out

    def assert_all_balanced(self):
        for e in JournalEntry.objects.filter(organisation=self.org):
            d = sum(l.debit for l in e.lines.all())
            c = sum(l.credit for l in e.lines.all())
            self.assertEqual(d, c, f"{e.source_type} {e.reference} unbalanced")

    def assert_subledgers(self):
        """AR in the ledger == what the customer record says is owed; Cash ==
        cash payments in the till sub-ledger; Bank == bank-type payments."""
        self.assert_all_balanced()
        self.customer.refresh_from_db()
        self.assertEqual(self.gl("ar"), self.customer.outstanding_balance, "AR vs customer balance")
        pays = SalePayment.objects.filter(organisation=self.org)
        cash = sum((p.amount for p in pays if p.method == "cash"), D("0"))
        bank = sum((p.amount for p in pays if p.method in ("bank_transfer", "pos")), D("0"))
        self.assertEqual(self.gl("cash"), cash, "Cash vs till payments")
        self.assertEqual(self.gl("bank"), bank, "Bank vs bank payments")

    def pay(self, inv, amount, method="cash"):
        res = self.api.post(f"{URL}{inv.id}/pay/", {"amount": str(amount), "method": method}, format="json")
        self.assertEqual(res.status_code, 201, getattr(res, "data", None))
        inv.refresh_from_db()
        return res


# ─────────────────────────────────────────────────────────────────────────────
class PayNowFulfilNowTests(LedgerBase):
    def test_cash_with_vat(self):
        inv = self.sale()
        self.assertEqual((inv.total_amount, inv.tax_amount, inv.status), (D("2150"), D("150"), "paid"))
        e = self.entries("sale", inv.id)[0]
        self.assertEqual(self.entry_lines(e), {
            "cash": (D("2150"), D("0")), "revenue": (D("0"), D("2000")), "vat": (D("0"), D("150")),
            "cogs": (D("1200"), D("0")), "inventory": (D("0"), D("1200")),
        })
        self.assertEqual(e.entry_date, inv.issue_date)
        self.assert_subledgers()

    def test_bank_transfer_with_vat(self):
        inv = self.sale(payment_method="bank_transfer")
        self.assertEqual(self.entry_lines(self.entries("sale", inv.id)[0])["bank"], (D("2150"), D("0")))
        self.assert_subledgers()

    def test_inclusive_1075(self):
        p = Product.objects.create(
            organisation=self.org, sku="INC", name="Inc", product_type="service", cost_price=0,
            selling_price=1075, is_taxable=True, tax_class=self.vat, tax_type="inclusive")
        inv = self.ok(items=[self.line(p, 1, "1075")], amount_paid="1075")
        self.assertEqual((inv.total_amount, inv.tax_amount), (D("1075"), D("75")))
        self.assertEqual(self.entry_lines(self.entries("sale", inv.id)[0]), {
            "cash": (D("1075"), D("0")), "revenue": (D("0"), D("1000")), "vat": (D("0"), D("75"))})


class CreditAndLaterPaymentTests(LedgerBase):
    def test_credit_then_two_later_payments(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        self.assertEqual(self.gl("ar"), D("2150"))
        self.assert_subledgers()
        self.pay(inv, 1000)
        self.assertEqual((inv.status, inv.amount_due), ("partially_paid", D("1150")))
        receipt = self.entries("credit_payment", inv.payments.get().id)[0]
        self.assertEqual(self.entry_lines(receipt), {"cash": (D("1000"), D("0")), "ar": (D("0"), D("1000"))})
        self.assert_subledgers()
        self.pay(inv, 1150, "bank_transfer")
        self.assertEqual((inv.status, inv.amount_due), ("paid", D("0")))
        self.assertEqual(self.gl("ar"), D("0"))
        self.assert_subledgers()

    def test_partial_pay_now_then_second_payment(self):
        inv = self.sale(amount_paid="1000.00")
        self.assertEqual((inv.status, inv.amount_due), ("partially_paid", D("1150")))
        self.assertEqual(self.gl("ar"), D("1150"))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, D("1150"))   # was never tracked before
        self.assert_subledgers()
        self.pay(inv, 1150)
        self.assertEqual((inv.status, inv.amount_paid), ("paid", D("2150")))
        self.assertEqual(self.gl("ar"), D("0"))
        self.assertEqual(self.gl("cash"), D("2150"))
        self.assert_subledgers()

    def test_every_later_payment_gets_its_own_unique_entry(self):
        inv = self.sale(amount_paid="500.00")
        self.pay(inv, 500)
        self.pay(inv, 500)
        ids = {str(p.id) for p in inv.payments.filter(in_sale_journal=False)}
        self.assertEqual(len(ids), 2)
        self.assertEqual(len([e for e in self.entries("sale_receipt") if e.source_ref in ids]), 2)

    def test_walk_in_payment_ledger_has_no_customer_side(self):
        inv = self.ok(customer_id=None, items=[self.line()], amount_paid="2150")
        self.assertEqual(self.gl("cash"), D("2150"))


class FulfilLaterDepositTests(LedgerBase):
    def test_paid_then_delivered_cash_debited_once(self):
        inv = self.sale(defer_fulfillment=True, issue_date="2020-03-01")
        self.assertEqual(inv.status, "paid")
        self.assertEqual(self.on_hand(self.taxed), D("100"))
        self.assertEqual(self.entries("sale", inv.id), [])
        e = self.entries("sale_deferred", inv.id)[0]
        self.assertEqual(self.entry_lines(e), {
            "cash": (D("2150"), D("0")), "deposits": (D("0"), D("2000")), "vat": (D("0"), D("150"))})
        self.assertEqual(e.entry_date, date(2020, 3, 1))
        self.assertEqual(self.gl("revenue"), D("0"))
        self.assertEqual(self.gl("cogs"), D("0"))

        res = self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertEqual(res.status_code, 200, res.data)
        d = self.entries("sale", inv.id)[0]
        self.assertEqual(self.entry_lines(d), {
            "deposits": (D("2000"), D("0")), "revenue": (D("0"), D("2000")),
            "cogs": (D("1200"), D("0")), "inventory": (D("0"), D("1200"))})
        self.assertEqual(d.entry_date, date.today())          # DELIVERY date, not issue date
        self.assertEqual(self.gl("cash"), D("2150"))          # once
        self.assertEqual(self.gl("vat"), D("-150"))           # once
        self.assertEqual(self.gl("deposits"), D("0"))
        self.assertEqual(self.gl("revenue"), D("-2000"))
        self.assert_subledgers()

    def test_an_older_invoice_stamped_delivery_keeps_its_ledger_behaviour(self):
        # The "delivery" setting no longer exists (VAT is due at the earliest of invoice,
        # receipt or delivery); an invoice already stamped "delivery" is left as it was booked.
        with patch("apps.sales.rules.vat_timing", return_value="delivery"):
            inv = self.sale(defer_fulfillment=True)
            e = self.entries("sale_deferred", inv.id)[0]
            self.assertEqual(self.entry_lines(e), {
                "cash": (D("2150"), D("0")), "deposits": (D("0"), D("2150"))})
            self.api.post(f"{URL}{inv.id}/fulfill/")
            self.assertEqual(self.gl("vat"), D("-150"))
            self.assertEqual(self.gl("deposits"), D("0"))
            self.assert_all_balanced()

    def test_credit_fulfil_later_paid_before_delivery_ar_ends_zero(self):
        inv = self.sale(defer_fulfillment=True, payment_method="credit", amount_paid="0")
        self.assertEqual(self.entry_lines(self.entries("sale_deferred", inv.id)[0]), {
            "ar": (D("2150"), D("0")), "deposits": (D("0"), D("2000")), "vat": (D("0"), D("150"))})
        self.assert_subledgers()
        self.pay(inv, 2150)
        self.assertEqual(self.gl("ar"), D("0"))
        self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertEqual(self.gl("ar"), D("0"))               # was -2150 (cash debited twice)
        self.assertEqual(self.gl("cash"), D("2150"))
        self.assertEqual(self.gl("deposits"), D("0"))
        self.assert_subledgers()

    def test_unpaid_fulfil_later_owes_and_is_delivered_later(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        self.assertEqual(self.gl("ar"), D("2150"))
        self.assert_subledgers()
        self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertEqual(self.gl("ar"), D("2150"))
        self.assertEqual(self.gl("revenue"), D("-2000"))
        self.assert_subledgers()

    def test_old_style_deferred_invoice_still_delivers_correctly(self):
        """An invoice raised before these rules (no sale_deferred entry, a payment
        nobody posted) must still post once, with the cash debited once."""
        inv = self.sale(defer_fulfillment=True)
        for e in self.entries("sale_deferred", inv.id):
            JournalLine.objects.filter(journal_entry=e).delete()          # bulk delete: test-only
            JournalEntry.objects.filter(pk=e.pk).delete()
        self.assertEqual(self.api.post(f"{URL}{inv.id}/fulfill/").status_code, 200)
        self.assertEqual(self.gl("cash"), D("2150"))
        self.assertEqual(self.gl("revenue"), D("-2000"))
        self.assert_all_balanced()

    def test_fulfil_after_a_locked_period_fails_loudly_and_loses_no_stock(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        today = date.today()
        FinancialPeriod.objects.create(organisation=self.org, year=today.year, month=today.month, is_locked=True)
        res = self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertEqual(res.status_code, 422)
        self.assertIn("locked", res.data["error"].lower())
        inv.refresh_from_db()
        self.assertIsNone(inv.fulfilled_at)
        self.assertEqual(self.on_hand(self.taxed), D("100"))
        self.assertEqual(self.sale_moves(), 0)
        self.assertEqual(self.entries("sale", inv.id), [])

    def test_fulfilment_is_idempotent_at_the_ledger(self):
        inv = self.sale(defer_fulfillment=True)
        self.api.post(f"{URL}{inv.id}/fulfill/")
        inv.refresh_from_db()
        first = self.entries("sale", inv.id)[0]
        again = ledger.post_sale_entry(self.org, inv, self.user, mode="fulfilment")
        self.assertEqual(again.id, first.id)
        self.assertEqual(len(self.entries("sale", inv.id)), 1)


class ProformaConfirmTests(LedgerBase):
    def test_proforma_then_confirm_posts_everything_once(self):
        inv = self.sale(is_proforma=True, amount_paid="0")
        self.assertEqual(self.entries("sale", inv.id) + self.entries("sale_deferred", inv.id), [])
        res = self.api.post(f"{URL}{inv.id}/confirm_proforma/")
        self.assertEqual(res.status_code, 200, res.data)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "confirmed")
        self.assertEqual(self.on_hand(self.taxed), D("98"))
        self.assertEqual(self.entry_lines(self.entries("sale", inv.id)[0]), {
            "ar": (D("2150"), D("0")), "revenue": (D("0"), D("2000")), "vat": (D("0"), D("150")),
            "cogs": (D("1200"), D("0")), "inventory": (D("0"), D("1200"))})
        self.assert_subledgers()
        # confirming twice is refused and posts nothing more
        self.assertEqual(self.api.post(f"{URL}{inv.id}/confirm_proforma/").status_code, 422)
        self.assertEqual(len(self.entries("sale", inv.id)), 1)

    def test_proforma_credit_method_puts_the_debt_on_the_customer_at_confirm(self):
        inv = self.sale(is_proforma=True, payment_method="credit", amount_paid="0")
        self.api.post(f"{URL}{inv.id}/confirm_proforma/")
        inv.refresh_from_db()
        self.assertEqual(inv.status, "credit")
        self.assert_subledgers()

    def test_deposit_on_a_proforma_carries_vat_on_receipt_then_confirm_settles_it(self):
        inv = self.sale(is_proforma=True, amount_paid="0")
        self.pay(inv, 500)
        self.assertEqual(inv.status, "proforma")                      # a deposit does not make it a sale
        dep = self.entries("sale_deposit", inv.payments.get().id)[0]
        # VAT share of 500 = 500 x 150 / 2150 = 34.88
        self.assertEqual(self.entry_lines(dep), {
            "cash": (D("500"), D("0")), "deposits": (D("0"), D("465.12")), "vat": (D("0"), D("34.88"))})
        self.assertEqual(self.on_hand(self.taxed), D("100"))
        self.api.post(f"{URL}{inv.id}/confirm_proforma/")
        inv.refresh_from_db()
        self.assertEqual((inv.status, inv.amount_paid, inv.amount_due), ("partially_paid", D("500"), D("1650")))
        self.assertEqual(self.gl("cash"), D("500"))
        self.assertEqual(self.gl("ar"), D("1650"))
        self.assertEqual(self.gl("deposits"), D("0"))
        self.assertEqual(self.gl("revenue"), D("-2000"))
        self.assertEqual(self.gl("vat"), D("-150"))                   # once, never twice
        self.assert_subledgers()

    def test_confirm_a_fulfil_later_proforma_does_not_move_stock(self):
        inv = self.sale(is_proforma=True, defer_fulfillment=True, amount_paid="0")
        self.api.post(f"{URL}{inv.id}/confirm_proforma/")
        self.assertEqual(self.on_hand(self.taxed), D("100"))
        self.assertEqual(len(self.entries("sale_deferred", inv.id)), 1)
        self.assertEqual(self.entries("sale", inv.id), [])
        self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertEqual(self.on_hand(self.taxed), D("98"))
        self.assertEqual(self.gl("deposits"), D("0"))
        self.assert_subledgers()


class AdjustmentTests(LedgerBase):
    def two_lines(self):
        a = Product.objects.create(organisation=self.org, sku="A10", name="A", product_type="service",
                                   cost_price=0, selling_price=10000, is_taxable=True, tax_class=self.vat)
        b = Product.objects.create(organisation=self.org, sku="B5", name="B", product_type="service",
                                   cost_price=0, selling_price=5000, is_taxable=True, tax_class=self.vat)
        return [self.line(a, 1, "10000"), self.line(b, 1, "5000")]

    def test_discount_of_1500_before_vat(self):
        inv = self.ok(items=self.two_lines(), adjustment_amount="-1500", amount_paid="14512.50")
        self.assertEqual(inv.adjustment_amount, D("-1500"))
        self.assertEqual(sorted(i.adjustment_amount for i in inv.items.all()), [D("-1000"), D("-500")])
        # net 13,500 ; VAT 1,012.50 ; total 14,512.50
        self.assertEqual((inv.tax_amount, inv.total_amount, inv.status), (D("1012.50"), D("14512.50"), "paid"))
        self.assertEqual(self.entry_lines(self.entries("sale", inv.id)[0]), {
            "cash": (D("14512.50"), D("0")), "revenue": (D("0"), D("13500")), "vat": (D("0"), D("1012.50"))})
        self.assert_subledgers()

    def test_surcharge_of_1000_before_vat(self):
        inv = self.ok(items=self.two_lines(), adjustment_amount="1000", amount_paid="17200")
        self.assertEqual((inv.tax_amount, inv.total_amount), (D("1200"), D("17200")))   # net 16,000
        self.assertEqual(self.entry_lines(self.entries("sale", inv.id)[0])["revenue"], (D("0"), D("16000")))

    def test_no_adjustment_changes_nothing(self):
        inv = self.ok(items=self.two_lines(), amount_paid="16125")
        self.assertEqual((inv.adjustment_amount, inv.total_amount), (D("0"), D("16125")))

    def test_discount_bigger_than_the_invoice_is_refused(self):
        res = self.post(items=self.two_lines(), adjustment_amount="-15001", amount_paid="0")
        self.assertEqual(res.status_code, 422)
        self.assertIn("adjustment", res.data["error"].lower())
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)

    def test_surcharge_refused_when_the_switch_is_off(self):
        with override_settings(SALES_SURCHARGE_TAXED_LIKE_DISCOUNT=False):
            res = self.post(items=self.two_lines(), adjustment_amount="100", amount_paid="0")
            self.assertEqual(res.status_code, 422)

    def test_adjustment_with_item_discount_and_proforma(self):
        inv = self.ok(is_proforma=True, amount_paid="0", adjustment_amount="-1500",
                      items=self.two_lines())
        self.assertEqual(inv.total_amount, D("14512.50"))
        self.assertEqual(self.entries("sale", inv.id), [])

    def test_odd_adjustment_split_adds_up_exactly(self):
        inv = self.ok(items=self.two_lines(), adjustment_amount="-100.01", amount_paid="0")
        self.assertEqual(sum(i.adjustment_amount for i in inv.items.all()), D("-100.01"))
        self.assert_all_balanced()


@override_settings(SALES_DELIVERY_VAT_FOLLOWS_GOODS=True)
class DeliveryChargeTests(LedgerBase):
    def test_delivery_500_carries_vat_of_the_goods(self):
        inv = self.sale(shipping_amount="500", amount_paid="2662.50")
        # goods 2,000 + VAT 150 ; delivery 500 + VAT 37.50
        self.assertEqual((inv.shipping_amount, inv.shipping_tax_amount, inv.tax_amount, inv.total_amount),
                         (D("500"), D("37.50"), D("187.50"), D("2687.50")))
        self.assertEqual(inv.status, "partially_paid")

    def test_delivery_500_paid_in_full(self):
        inv = self.sale(shipping_amount="500", amount_paid="2687.50")
        self.assertEqual(inv.status, "paid")
        self.assertEqual(self.entry_lines(self.entries("sale", inv.id)[0]), {
            "cash": (D("2687.50"), D("0")), "revenue": (D("0"), D("2500")), "vat": (D("0"), D("187.50")),
            "cogs": (D("1200"), D("0")), "inventory": (D("0"), D("1200"))})

    def test_mixed_basket_splits_delivery_vat_by_line_value(self):
        # 1,000 taxed + 1,000 untaxed, delivery 400 -> half the delivery is taxable: 400 x 50% x 7.5% = 15
        plain = Product.objects.create(organisation=self.org, sku="PL", name="Plain", product_type="service",
                                       cost_price=0, selling_price=1000)
        inv = self.ok(items=[self.line(self.taxed_service, 1, "1000"), self.line(plain, 1, "1000")],
                      shipping_amount="400", amount_paid="0")
        self.assertEqual(inv.shipping_tax_amount, D("15"))
        self.assertEqual((inv.tax_amount, inv.total_amount), (D("90"), D("2490")))

    def test_switch_off_means_delivery_carries_no_vat(self):
        """The shipped default: delivery carries no VAT until the switch is on."""
        with override_settings(SALES_DELIVERY_VAT_FOLLOWS_GOODS=False):
            inv = self.sale(shipping_amount="500", amount_paid="0")
            self.assertEqual((inv.shipping_tax_amount, inv.tax_amount, inv.total_amount),
                             (D("0"), D("150"), D("2650")))

    def test_service_level_rejects_negative_shipping(self):
        from apps.sales.services import SaleService
        with self.assertRaises(ValueError):
            SaleService.create_sale(
                organisation=self.org, created_by=self.user, customer=self.customer, warehouse=self.wh,
                items=[{"product_id": self.taxed.id, "quantity": 1}], payment_method="cash",
                amount_paid=D("0"), shipping_amount=D("-5"))
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)


class StoreCreditLedgerTests(LedgerBase):
    def test_store_credit_300_on_1075_paid_775(self):
        p = Product.objects.create(
            organisation=self.org, sku="INC2", name="Inc2", product_type="service", cost_price=0,
            selling_price=1075, is_taxable=True, tax_class=self.vat, tax_type="inclusive")
        self.customer.store_credit = D("300")
        self.customer.save()
        inv = self.ok(items=[self.line(p, 1, "1075")], credit_applied="300", amount_paid="775")
        self.assertEqual((inv.status, inv.amount_due, inv.credit_applied), ("paid", D("0"), D("300")))
        self.assertEqual(self.entry_lines(self.entries("sale", inv.id)[0]), {
            "cash": (D("775"), D("0")),                      # only what was received
            "deposits": (D("300"), D("0")),                  # store credit used: liability falls
            "revenue": (D("0"), D("1000")), "vat": (D("0"), D("75"))})
        self.assertEqual(self.gl("cash"), D("775"))
        self.assert_subledgers()


class VoidTests(LedgerBase):
    def zero_everywhere(self):
        for role in ("cash", "bank", "ar", "deposits", "vat", "revenue", "cogs", "inventory"):
            self.assertEqual(self.gl(role), D("0"), role)

    def test_void_with_item_discount_mirrors_exactly(self):
        inv = self.ok(payment_method="credit", amount_paid="0",
                      items=[self.line(discount_percent="10")])       # net 1,800 VAT 135 total 1,935
        self.assertEqual((inv.discount_amount, inv.tax_amount, inv.total_amount),
                         (D("200"), D("135"), D("1935")))
        res = self.api.post(f"{URL}{inv.id}/void/")
        self.assertEqual(res.status_code, 200, res.data)
        self.zero_everywhere()
        self.assertEqual(self.on_hand(self.taxed), D("100"))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, D("0"))   # void used to leave this owed
        self.assert_all_balanced()

    def test_void_with_shipping_mirrors_exactly(self):
        inv = self.ok(payment_method="credit", amount_paid="0", shipping_amount="300",
                      items=[self.line()])
        self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        self.zero_everywhere()
        self.assert_all_balanced()

    def test_void_partly_paid_invoice_refunds_the_payment(self):
        inv = self.sale(amount_paid="1000.00")
        self.pay(inv, 500)
        self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        self.zero_everywhere()
        self.assertEqual(sum(p.amount for p in inv.payments.all()), D("0"))
        self.assertEqual(inv.payments.filter(amount__lt=0).count(), 2)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, D("0"))

    def test_void_failure_is_not_swallowed(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        with patch("apps.sales.ledger.void_invoice_entry", side_effect=ValueError("boom")):
            res = self.api.post(f"{URL}{inv.id}/void/")
        self.assertEqual(res.status_code, 422)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "credit")                        # not voided
        self.assertEqual(self.on_hand(self.taxed), D("98"))

    def test_void_unfulfilled_unpaid_deferred_invoice(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        self.zero_everywhere()
        self.assertEqual(self.on_hand(self.taxed), D("100"))
        self.assertEqual(StockMovement.objects.filter(organisation=self.org, movement_type="return_in").count(), 0)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, D("0"))

    def test_void_unfulfilled_paid_deferred_invoice_refunds_the_deposit(self):
        inv = self.sale(defer_fulfillment=True)
        self.assertEqual(inv.status, "paid")
        res = self.api.post(f"{URL}{inv.id}/void/")
        self.assertEqual(res.status_code, 200, res.data)
        self.zero_everywhere()
        self.assertEqual(inv.payments.filter(amount__lt=0).get().amount, D("-2150"))

    def test_void_after_delivery_restocks_and_reverses_both_entries(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        self.zero_everywhere()
        self.assertEqual(self.on_hand(self.taxed), D("100"))

    def test_paid_fulfil_now_invoice_still_cannot_be_voided(self):
        inv = self.sale()
        self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 422)

    def test_void_restores_store_credit(self):
        self.customer.store_credit = D("300")
        self.customer.save()
        inv = self.ok(items=[self.line()], credit_applied="300", amount_paid="0", payment_method="credit")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.store_credit, D("0"))
        self.api.post(f"{URL}{inv.id}/void/")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.store_credit, D("300"))
        self.assertEqual(self.customer.outstanding_balance, D("0"))

    def test_void_twice_is_refused(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        self.api.post(f"{URL}{inv.id}/void/")
        self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 422)
        self.zero_everywhere()

    def test_delete_fulfilled_deferred_invoice_leaves_nothing_behind(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertEqual(self.api.post(f"{URL}{inv.id}/delete_invoice/").status_code, 204)
        self.zero_everywhere()
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, D("0"))
        self.assertEqual(self.on_hand(self.taxed), D("100"))

    def test_delete_invoice_with_later_payments_nets_to_zero_cash(self):
        inv = self.sale(amount_paid="1000.00")
        self.pay(inv, 500)
        self.assertEqual(self.api.post(f"{URL}{inv.id}/delete_invoice/").status_code, 204)
        self.zero_everywhere()


class ReturnOfUnfulfilledTests(LedgerBase):
    def test_return_on_undelivered_invoice_is_refused(self):
        inv = self.sale(defer_fulfillment=True)
        item = inv.items.get()
        res = self.api.post(f"{URL}{inv.id}/process_return/", {
            "items": [{"sale_item_id": str(item.id), "quantity_returned": "1"}]}, format="json")
        self.assertEqual(res.status_code, 422)
        self.assertIn("not been delivered", res.data["error"])
        self.assertEqual(self.on_hand(self.taxed), D("100"))
        self.assertEqual(self.entries("sale_return"), [])


class NeverSwallowTests(LedgerBase):
    def test_failed_sale_journal_rolls_the_whole_sale_back(self):
        with patch("apps.sales.ledger.post_sale_entry", side_effect=ValueError("ledger down")):
            res = self.post(items=[self.line()], amount_paid="2150")
        self.assertEqual(res.status_code, 422)
        self.assertIn("ledger down", res.data["error"])
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)
        self.assertEqual(self.on_hand(self.taxed), D("100"))
        self.assertEqual(SalePayment.objects.filter(organisation=self.org).count(), 0)

    def test_missing_cogs_account_is_flagged_not_silently_dropped(self):
        """COGS used to vanish silently (the sale looked 'posted' with no cost of
        sales). Now the WHOLE entry is withheld and the invoice says so:
        gl_post_status='not_configured', with the missing role named, so it shows
        up in the retry list and posts complete once the account is mapped."""
        from apps.accounting.exceptions import GLAccountNotConfigured
        real = AccountMappingService.resolve.__func__

        def resolve(cls, organisation, role):
            if role == "cogs_account":
                raise GLAccountNotConfigured(role)
            return real(cls, organisation, role)

        with patch.object(AccountMappingService, "resolve", classmethod(resolve)):
            res = self.post(items=[self.line()], amount_paid="2150")
        self.assertEqual(res.status_code, 201, res.data)
        inv = Invoice.objects.get(id=res.data["id"])
        self.assertEqual(inv.gl_post_status, "not_configured")
        self.assertIn("cogs_account", inv.gl_post_error)
        self.assertEqual(self.entries("sale", inv.id), [])            # not a half entry without COGS
        # once mapped, the retry posts the complete entry (cash once)
        ok, err = AccountingService.retry_gl_post(self.org, "invoice", str(inv.id), self.user) \
            if hasattr(AccountingService, "retry_gl_post") else (True, None)
        inv.refresh_from_db()
        self.assertEqual(inv.gl_post_status, "posted", inv.gl_post_error)
        self.assertEqual(self.gl("cash"), D("2150"))
        self.assertEqual(self.gl("cogs"), D("1200"))
        self.assert_all_balanced()

    def test_a_locked_period_at_sale_time_refuses_the_sale(self):
        today = date.today()
        FinancialPeriod.objects.create(organisation=self.org, year=today.year, month=today.month, is_locked=True)
        res = self.post(items=[self.line()], amount_paid="2150")
        self.assertEqual(res.status_code, 422)
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)
        self.assertEqual(self.on_hand(self.taxed), D("100"))

    def test_failed_receipt_journal_rolls_the_payment_back(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        with patch("apps.sales.ledger.post_receipt_entry", side_effect=ValueError("ledger down")):
            res = self.api.post(f"{URL}{inv.id}/pay/", {"amount": "100", "method": "cash"}, format="json")
        self.assertEqual(res.status_code, 422)
        inv.refresh_from_db()
        self.assertEqual((inv.amount_paid, inv.status), (D("0"), "credit"))
        self.assertEqual(inv.payments.count(), 0)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, D("2150"))


class WhtPerPaymentTests(LedgerBase):
    def setUp(self):
        super().setUp()
        from apps.tax.models import WHTRate
        self.rate = WHTRate.objects.filter(organisation=self.org).first()

    def wht(self):
        return list(WHTTransaction.objects.filter(organisation=self.org).order_by("created_at"))

    def test_credit_sale_records_no_wht_until_money_arrives(self):
        inv = self.sale(payment_method="credit", amount_paid="0", wht_rate_id=str(self.rate.id))
        self.assertEqual(self.wht(), [])
        self.pay(inv, 1000)
        self.pay(inv, 1150)
        self.assertEqual([t.gross_amount for t in self.wht()], [D("1000"), D("1150")])

    def test_paid_at_the_till_records_wht_on_what_was_paid(self):
        self.sale(amount_paid="1000.00", wht_rate_id=str(self.rate.id))
        self.assertEqual([t.gross_amount for t in self.wht()], [D("1000")])

    def test_no_wht_rate_no_wht(self):
        inv = self.sale(amount_paid="1000.00")
        self.pay(inv, 500)
        self.assertEqual(self.wht(), [])


class LedgerIdempotencyTests(LedgerBase):
    def test_reposting_the_sale_entry_returns_the_same_entry(self):
        inv = self.sale()
        first = self.entries("sale", inv.id)[0]
        again = ledger.post_sale_entry(self.org, inv, self.user, mode="full")
        self.assertEqual(again.id, first.id)
        self.assertEqual(len(self.entries("sale", inv.id)), 1)

    def test_reposting_a_receipt_returns_the_same_entry(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        self.pay(inv, 100)
        pay = inv.payments.get()
        first = self.entries("credit_payment", pay.id)[0]
        again = ledger.post_receipt_entry(self.org, inv, pay, self.user)
        self.assertEqual(again.id, first.id)

    def test_same_idempotency_key_posts_one_entry(self):
        body = self.payload(items=[self.line()], amount_paid="2150")
        r1 = self.api.post(URL, body, format="json", HTTP_IDEMPOTENCY_KEY="led-1")
        r2 = self.api.post(URL, body, format="json", HTTP_IDEMPOTENCY_KEY="led-1")
        self.assertEqual(r1.data["id"], r2.data["id"])
        self.assertEqual(len(self.entries("sale")), 1)


class EditAndGatewayTests(LedgerBase):
    @override_settings(SALES_DELIVERY_VAT_FOLLOWS_GOODS=True)
    def test_editing_an_invoice_keeps_vat_on_its_delivery(self):
        inv = self.sale(shipping_amount="500", amount_paid="0")
        self.assertEqual((inv.shipping_tax_amount, inv.total_amount), (D("37.50"), D("2687.50")))
        res = self.api.patch(f"{URL}{inv.id}/edit_lines/", {
            "items": [{"product_id": str(self.taxed.id), "quantity": 1, "unit_price": "1000"}],
        }, format="json")
        self.assertEqual(res.status_code, 200, getattr(res, "data", None))
        inv.refresh_from_db()
        # 1,000 + VAT 75 + delivery 500 + VAT 37.50
        self.assertEqual((inv.shipping_tax_amount, inv.total_amount), (D("37.50"), D("1612.50")))

    def test_a_gateway_payment_posts_exactly_one_entry(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        from apps.sales.services import SaleService
        SaleService.record_payment_from_gateway(inv, D("1000"), "REF-1", channel="bank_transfer", provider="paystack")
        self.assertEqual(self.gl("bank"), D("1000"))
        self.assertEqual(self.gl("cash"), D("0"))
        self.assertEqual(self.gl("ar"), D("1150"))
        self.assert_subledgers()

    def test_a_gateway_payment_on_a_paid_in_part_cash_sale_posts_once(self):
        inv = self.sale(amount_paid="1000.00")
        from apps.sales.services import SaleService
        SaleService.record_payment_from_gateway(inv, D("1150"), "REF-2", channel="card")
        self.assertEqual(self.gl("bank"), D("1150"))
        self.assertEqual(self.gl("ar"), D("0"))


class RepostAfterFailureTests(LedgerBase):
    def test_reposting_an_old_invoice_whose_entry_never_posted_debits_cash_once(self):
        """GL retry for an invoice whose payment was never flagged as folded in
        (raised before these rules): the cash must still be in the entry, once."""
        inv = self.sale()
        for e in self.entries("sale", inv.id):
            JournalLine.objects.filter(journal_entry=e).delete()          # bulk delete: test-only
            JournalEntry.objects.filter(pk=e.pk).delete()
        SalePayment.objects.filter(invoice=inv).update(in_sale_journal=False)
        AccountingService.post_sale_journal(self.org, Invoice.objects.get(pk=inv.pk), self.user)
        self.assertEqual(self.gl("cash"), D("2150"))
        self.assertEqual(self.gl("ar"), D("0"))
        self.assert_all_balanced()


class NoCustomerCreditTests(LedgerBase):
    def test_credit_sale_with_no_customer_is_rejected_and_posts_nothing(self):
        res = self.post(customer_id=None, payment_method="credit", amount_paid="0", items=[self.line()])
        self.assertEqual(res.status_code, 422)
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org, source_type="sale").count(), 0)
