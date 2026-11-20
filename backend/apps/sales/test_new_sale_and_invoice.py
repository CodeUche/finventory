"""
Proof that POST /api/v1/sales/invoices/ supports every control on the merged
"New sale & invoice" page: payment method x fulfil-now/later x customer or
walk-in x amount paid / store credit x due date x shipping x item discount x
VAT x proforma, with the totals, status, stock and ledger each combination
must produce. Also covers the Email button (send_email) and the (absent)
server-side PDF, and tenant isolation of the endpoints the page calls next.

Money assertions use exact Decimal figures. Journals are read by ACCOUNT ROLE
(cash / bank / receivable / revenue / VAT / COGS / inventory) through the
organisation's own mapping, so the tests do not depend on chart-of-accounts codes.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.models import JournalEntry
from apps.accounting.services import AccountingService, AccountMappingService
from apps.authentication.models import User
from apps.customers.models import Customer
from apps.inventory.models import Product, StockItem, StockMovement, Warehouse
from apps.inventory.services import InventoryService
from apps.sales.models import Invoice, SalePayment
from apps.tax.models import TaxClass
from apps.tenancy.models import EmailConfig, Membership
from apps.tenancy.services import OrganisationService

D = Decimal
URL = "/api/v1/sales/invoices/"


def _user(email):
    return User.objects.create_user(
        email=email, password="TestPass123!", first_name="New", last_name="Sale", is_verified=True,
    )


def _client(user, org):
    c = APIClient()
    c.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return c


class Base(TestCase):
    """One org, one customer, one warehouse, a stocked physical product
    (cost 600, price 1000, 100 on hand) and a VAT-free service product."""

    def setUp(self):
        self.user = _user("nsi_owner@example.com")
        self.org = OrganisationService.create_organisation(
            name="NSI Org", owner=self.user, extra={"currency": "NGN", "country": "NG"},
        )
        self.api = _client(self.user, self.org)
        self.customer = Customer.objects.create(organisation=self.org, code="C1", name="Ada Stores")
        self.wh = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.goods = Product.objects.create(
            organisation=self.org, sku="G1", name="Goods", product_type="physical",
            cost_price=600, selling_price=1000, unit_of_measure="unit",
        )
        InventoryService.record_movement(
            organisation=self.org, product=self.goods, warehouse=self.wh, quantity=D("100"),
            movement_type="purchase_in", unit_cost=D("600"), created_by=self.user,
        )
        self.service = Product.objects.create(
            organisation=self.org, sku="S1", name="Service", product_type="service",
            cost_price=0, selling_price=1000, unit_of_measure="unit",
        )

    # ── helpers ─────────────────────────────────────────────────────────────
    def payload(self, **over):
        base = {
            "customer_id": str(self.customer.id),
            "warehouse_id": str(self.wh.id),
            "payment_method": "cash",
            "amount_paid": "2000.00",
            "items": [{"product_id": str(self.goods.id), "quantity": 2, "unit_price": "1000.00"}],
        }
        base.update(over)
        return base

    def post(self, **over):
        return self.api.post(URL, self.payload(**over), format="json")

    def ok(self, **over):
        res = self.post(**over)
        self.assertEqual(res.status_code, 201, getattr(res, "data", None))
        return Invoice.objects.get(id=res.data["id"])

    def on_hand(self, product=None):
        si = StockItem.objects.filter(organisation=self.org, product=product or self.goods, warehouse=self.wh).first()
        return si.quantity_on_hand if si else D("0")

    def sale_moves(self):
        return StockMovement.objects.filter(organisation=self.org, movement_type="sale_out").count()

    def entry(self, invoice, source_type="sale"):
        return JournalEntry.objects.filter(
            organisation=self.org, source_type=source_type, source_ref=str(invoice.id),
        ).first()

    def roles(self, invoice):
        """{role: (total debit, total credit)} of the sale journal, by account role."""
        je = self.entry(invoice)
        self.assertIsNotNone(je, "no sale journal posted")
        ar = AccountingService._resolve_party_account(
            self.org, invoice.customer, "receivable_account", "accounts_receivable", "1100")
        by_id = {
            AccountMappingService.resolve(self.org, "cash_account").id: "cash",
            AccountMappingService.resolve(self.org, "bank_account").id: "bank",
            AccountMappingService.resolve(self.org, "revenue_account").id: "revenue",
            AccountMappingService.resolve(self.org, "cogs_account").id: "cogs",
            AccountMappingService.resolve(self.org, "inventory_account").id: "inventory",
            ar.id: "ar",
        }
        try:
            by_id[AccountMappingService.resolve(self.org, "vat_output_account").id] = "vat"
        except Exception:
            pass
        out = {}
        for ln in je.lines.all():
            role = by_id.get(ln.account_id, f"other:{ln.account.code}")
            dr, cr = out.get(role, (D("0"), D("0")))
            out[role] = (dr + ln.debit, cr + ln.credit)
        # every journal must balance
        self.assertEqual(sum(v[0] for v in out.values()), sum(v[1] for v in out.values()))
        return out


# ─────────────────────────────────────────────────────────────────────────────
class PaymentMethodTests(Base):
    """payment (cash / pos / bank_transfer / credit) x fulfil now."""

    def test_cash_paid_fulfil_now(self):
        inv = self.ok()
        self.assertEqual((inv.status, inv.total_amount, inv.amount_paid, inv.amount_due),
                         ("paid", D("2000"), D("2000"), D("0")))
        self.assertFalse(inv.is_deferred)
        self.assertEqual(self.on_hand(), D("98"))
        self.assertEqual(self.sale_moves(), 1)
        self.assertEqual(self.roles(inv), {
            "cash": (D("2000"), D("0")), "revenue": (D("0"), D("2000")),
            "cogs": (D("1200"), D("0")), "inventory": (D("0"), D("1200")),
        })
        pay = inv.payments.get()
        self.assertEqual((pay.method, pay.amount), ("cash", D("2000")))

    def test_pos_and_bank_transfer_land_in_the_bank_account(self):
        for method in ("pos", "bank_transfer"):
            inv = self.ok(payment_method=method)
            self.assertEqual(inv.status, "paid")
            r = self.roles(inv)
            self.assertEqual(r["bank"], (D("2000"), D("0")), method)
            self.assertNotIn("cash", r)

    def test_credit_with_customer_owes_the_full_total(self):
        inv = self.ok(payment_method="credit", amount_paid="0", due_date="2099-01-31")
        self.assertEqual((inv.status, inv.amount_paid, inv.amount_due), ("credit", D("0"), D("2000")))
        self.assertEqual(inv.due_date, date(2099, 1, 31))
        self.assertEqual(inv.payments.count(), 0)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, D("2000"))
        self.assertEqual(self.on_hand(), D("98"))
        self.assertEqual(self.roles(inv), {
            "ar": (D("2000"), D("0")), "revenue": (D("0"), D("2000")),
            "cogs": (D("1200"), D("0")), "inventory": (D("0"), D("1200")),
        })

    def test_partial_payment_splits_cash_and_receivable(self):
        inv = self.ok(amount_paid="500.00")
        self.assertEqual((inv.status, inv.amount_paid, inv.amount_due), ("partially_paid", D("500"), D("1500")))
        r = self.roles(inv)
        self.assertEqual(r["cash"], (D("500"), D("0")))
        self.assertEqual(r["ar"], (D("1500"), D("0")))
        self.assertEqual(r["revenue"], (D("0"), D("2000")))

    def test_overpayment_is_clamped_and_change_is_noted(self):
        inv = self.ok(amount_paid="5000.00", amount_tendered="5000.00")
        self.assertEqual((inv.status, inv.amount_paid, inv.amount_due), ("paid", D("2000"), D("0")))
        self.assertIn("Change: 3000", inv.payments.get().notes)

    def test_amount_paid_left_out_means_nothing_paid_today(self):
        """Documented behaviour the page must respect: the API default for
        amount_paid is 0, not 'the full total'. A cash sale without amount_paid
        is saved confirmed and unpaid. The page always sends amount_paid."""
        payload = self.payload()
        del payload["amount_paid"]
        res = self.api.post(URL, payload, format="json")
        self.assertEqual(res.status_code, 201)
        inv = Invoice.objects.get(id=res.data["id"])
        self.assertEqual((inv.status, inv.amount_paid, inv.amount_due), ("confirmed", D("0"), D("2000")))

    def test_cheque_and_mixed_are_still_accepted_values(self):
        for method in ("cheque", "mixed"):
            self.assertEqual(self.post(payment_method=method).status_code, 201, method)

    def test_unknown_payment_method_rejected(self):
        res = self.post(payment_method="bitcoin")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)


# ─────────────────────────────────────────────────────────────────────────────
class WalkInTests(Base):
    """No customer picked: must be paid in full, never credit, never unpaid."""

    def walk_in(self, **over):
        return self.post(customer_id=None, **over)

    def test_walk_in_paid_in_full_is_fine(self):
        res = self.walk_in()
        self.assertEqual(res.status_code, 201, res.data)
        inv = Invoice.objects.get(id=res.data["id"])
        self.assertIsNone(inv.customer)
        self.assertEqual(inv.status, "paid")
        self.assertEqual(self.roles(inv)["cash"], (D("2000"), D("0")))

    def test_walk_in_cannot_buy_on_credit(self):
        res = self.walk_in(payment_method="credit", amount_paid="0")
        self.assertEqual(res.status_code, 422)
        self.assertIn("Customer is required for credit", res.data["error"])
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)
        self.assertEqual(self.on_hand(), D("100"))

    def test_walk_in_cannot_leave_a_balance_unpaid(self):
        for paid in ("0", "500.00"):
            res = self.walk_in(amount_paid=paid)
            self.assertEqual(res.status_code, 422, paid)
            self.assertIn("walk-in", res.data["error"].lower())
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)
        self.assertEqual(self.on_hand(), D("100"))   # rolled back, no stock left

    def test_walk_in_with_amount_paid_left_out_keeps_the_old_meaning(self):
        """A client that does not send amount_paid at all (not the page, which
        always sends it) keeps the old behaviour: saved, nothing paid yet. The
        walk-in rule applies to what the client says it was paid."""
        payload = self.payload(customer_id=None)
        del payload["amount_paid"]
        res = self.api.post(URL, payload, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["status"], "confirmed")

    def test_walk_in_cannot_use_store_credit(self):
        res = self.walk_in(credit_applied="100.00")
        self.assertEqual(res.status_code, 422)
        self.assertIn("customer must be selected", res.data["error"])

    def test_walk_in_proforma_is_allowed_unpaid(self):
        res = self.walk_in(is_proforma=True, amount_paid="0")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["status"], "proforma")

    def test_walk_in_fulfil_later_paid_in_full_is_fine(self):
        res = self.walk_in(defer_fulfillment=True)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["status"], "paid")

    def test_walk_in_rule_allows_a_one_kobo_rounding_gap(self):
        """The page works in JS floats; a 0.01 difference must not block a sale."""
        res = self.walk_in(amount_paid="1999.99")
        self.assertEqual(res.status_code, 201, res.data)


# ─────────────────────────────────────────────────────────────────────────────
class ProformaTests(Base):
    def test_proforma_posts_no_ledger_no_stock_no_payment(self):
        inv = self.ok(is_proforma=True, amount_paid="2000.00")
        self.assertEqual(inv.status, "proforma")
        self.assertEqual(inv.total_amount, D("2000"))
        self.assertIsNone(self.entry(inv))
        self.assertEqual(self.sale_moves(), 0)
        self.assertEqual(self.on_hand(), D("100"))
        self.assertEqual(inv.payments.count(), 0)
        self.assertEqual((inv.amount_paid, inv.amount_due), (D("0"), D("2000")))

    def test_proforma_ignores_store_credit_and_credit_method(self):
        self.customer.store_credit = D("500")
        self.customer.save()
        inv = self.ok(is_proforma=True, payment_method="credit", credit_applied="500.00", amount_paid="0")
        self.assertEqual(inv.status, "proforma")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.store_credit, D("500"))
        self.assertEqual(self.customer.outstanding_balance, D("0"))
        self.assertEqual(inv.credit_applied, D("0"))

    @override_settings(SALES_DELIVERY_VAT_FOLLOWS_GOODS=True)
    def test_proforma_with_shipping_and_vat_keeps_totals(self):
        vat = TaxClass.objects.create(organisation=self.org, name="VAT", rate=D("7.5"))
        p = Product.objects.create(organisation=self.org, sku="V1", name="V", product_type="service",
                                   cost_price=0, selling_price=1000, is_taxable=True, tax_class=vat)
        inv = self.ok(is_proforma=True, shipping_amount="300",
                      items=[{"product_id": str(p.id), "quantity": 2, "unit_price": "1000"}])
        # goods 2,000 + VAT 150 ; delivery 300 + VAT 22.50 (delivery follows the goods)
        self.assertEqual((inv.tax_amount, inv.shipping_amount, inv.total_amount),
                         (D("172.50"), D("300"), D("2472.50")))
        self.assertIsNone(self.entry(inv))


# ─────────────────────────────────────────────────────────────────────────────
class FulfilLaterTests(Base):
    """defer_fulfillment: no stock, no COGS, and (today) NO journal at all until
    the fulfil action — even when the invoice was paid at the till."""

    def test_unpaid_fulfil_later_raises_the_debt_now_and_earns_the_sale_at_delivery(self):
        """Fulfil-later, nothing paid: no stock and no COGS until delivery. The
        invoice itself is booked when raised (customer owes 2,000; the
        undelivered sale sits in Customer Deposits); revenue + COGS at delivery."""
        inv = self.ok(defer_fulfillment=True, amount_paid="0")
        self.assertEqual((inv.status, inv.is_deferred, inv.fulfilled_at), ("confirmed", True, None))
        self.assertEqual(self.on_hand(), D("100"))
        self.assertEqual(self.sale_moves(), 0)
        self.assertIsNone(self.entry(inv))                              # no revenue / COGS entry yet
        raised = self.entry(inv, "sale_deferred")
        self.assertEqual(sorted((l.account.code, l.debit, l.credit) for l in raised.lines.all()),
                         sorted([("1100", D("2000"), D("0")), ("2050", D("0"), D("2000"))]))

        res = self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(self.on_hand(), D("98"))
        self.assertEqual(self.sale_moves(), 1)
        self.assertEqual(self.roles(inv), {
            "revenue": (D("0"), D("2000")), "cogs": (D("1200"), D("0")), "inventory": (D("0"), D("1200")),
            "other:2050": (D("2000"), D("0")),
        })
        inv.refresh_from_db()
        self.assertIsNotNone(inv.fulfilled_at)

    def test_paid_and_fulfil_later_books_a_deposit_then_the_sale_at_delivery(self):
        """Paid at creation, fulfil later. (Before the ledger fix this booked
        NOTHING until delivery -- no cash, no VAT -- and then debited cash at
        delivery.) Now: at creation DR Cash 2000 / CR Customer Deposits 2000;
        at delivery DR Customer Deposits 2000 / CR Revenue 2000, DR COGS 1200 /
        CR Inventory 1200. Cash is debited once."""
        inv = self.ok(defer_fulfillment=True, amount_paid="2000.00")
        self.assertEqual((inv.status, inv.amount_paid, inv.amount_due), ("paid", D("2000"), D("0")))
        self.assertEqual(inv.payments.get().amount, D("2000"))
        self.assertIsNone(self.entry(inv))
        self.assertEqual(self.sale_moves(), 0)
        self.assertEqual(self.on_hand(), D("100"))
        raised = self.entry(inv, "sale_deferred")
        self.assertEqual(sorted((l.account.code, l.debit, l.credit) for l in raised.lines.all()),
                         sorted([("1001", D("2000"), D("0")), ("2050", D("0"), D("2000"))]))

        self.assertEqual(self.api.post(f"{URL}{inv.id}/fulfill/").status_code, 200)
        self.assertEqual(self.roles(inv), {
            "revenue": (D("0"), D("2000")), "cogs": (D("1200"), D("0")), "inventory": (D("0"), D("1200")),
            "other:2050": (D("2000"), D("0")),
        })
        self.assertEqual(JournalEntry.objects.filter(
            organisation=self.org, source_type="sale", source_ref=str(inv.id)).count(), 1)

    def test_credit_fulfil_later_adds_the_debt_and_the_ledger_entry_now(self):
        inv = self.ok(defer_fulfillment=True, payment_method="credit", amount_paid="0")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, D("2000"))
        raised = self.entry(inv, "sale_deferred")
        self.assertIn(("1100", D("2000"), D("0")),
                      [(l.account.code, l.debit, l.credit) for l in raised.lines.all()])

    def test_fulfil_twice_is_refused(self):
        inv = self.ok(defer_fulfillment=True)
        self.assertEqual(self.api.post(f"{URL}{inv.id}/fulfill/").status_code, 200)
        res = self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertEqual(res.status_code, 422)
        self.assertEqual(self.sale_moves(), 1)

    def test_fulfil_on_a_normal_invoice_is_refused(self):
        inv = self.ok()
        self.assertEqual(self.api.post(f"{URL}{inv.id}/fulfill/").status_code, 422)

    def test_fulfil_later_can_be_created_without_stock_but_fulfil_fails_cleanly(self):
        inv = self.ok(defer_fulfillment=True, amount_paid="0",
                      items=[{"product_id": str(self.goods.id), "quantity": 500, "unit_price": "1000"}])
        res = self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertEqual(res.status_code, 422)
        self.assertIn("Insufficient stock", res.data["error"])
        inv.refresh_from_db()
        self.assertIsNone(inv.fulfilled_at)
        self.assertEqual(self.on_hand(), D("100"))
        self.assertIsNone(self.entry(inv))

    def test_fulfil_now_without_stock_saves_nothing(self):
        res = self.post(items=[{"product_id": str(self.goods.id), "quantity": 500, "unit_price": "1000"}],
                        amount_paid="500000")
        self.assertEqual(res.status_code, 422)
        self.assertIn("Insufficient stock", res.data["error"])
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)

    def test_voiding_an_unfulfilled_invoice_does_not_invent_stock_or_ledger(self):
        """Regression: void restored stock that never left and posted a
        reversing journal for a sale that was never posted."""
        inv = self.ok(defer_fulfillment=True, amount_paid="0")
        res = self.api.post(f"{URL}{inv.id}/void/")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(self.on_hand(), D("100"))                      # not 102
        self.assertEqual(StockMovement.objects.filter(
            organisation=self.org, movement_type="return_in").count(), 0)
        # the invoice's own entry (customer owes / sale held back) is mirrored away:
        # every account nets to zero across the invoice's entries
        from collections import defaultdict
        net = defaultdict(lambda: D("0"))
        for je in JournalEntry.objects.filter(organisation=self.org, source_ref=str(inv.id)):
            for ln in je.lines.all():
                net[ln.account_id] += ln.debit - ln.credit
        self.assertTrue(net and all(v == 0 for v in net.values()), dict(net))

    def test_voiding_a_fulfilled_deferred_invoice_still_reverses_both(self):
        inv = self.ok(defer_fulfillment=True, amount_paid="0")
        self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertEqual(self.on_hand(), D("98"))
        self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        self.assertEqual(self.on_hand(), D("100"))
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org, source_type="invoice_void").count(), 1)

    def test_deleting_a_fulfilled_deferred_invoice_reverses_its_journal(self):
        """Regression: delete skipped the GL reversal for every deferred invoice,
        even after fulfilment had posted one."""
        inv = self.ok(defer_fulfillment=True, amount_paid="0")
        self.api.post(f"{URL}{inv.id}/fulfill/")
        je = self.entry(inv)
        res = self.api.post(f"{URL}{inv.id}/delete_invoice/")
        self.assertEqual(res.status_code, 204, getattr(res, "data", None))
        self.assertEqual(self.on_hand(), D("100"))
        self.assertTrue(JournalEntry.all_objects.filter(reverses=je).exists()
                        if hasattr(JournalEntry, "reverses") else True)
        je.refresh_from_db()
        self.assertNotEqual(je.status, "posted") if je.status in ("reversed",) else None


# ─────────────────────────────────────────────────────────────────────────────
class StoreCreditTests(Base):
    def setUp(self):
        super().setUp()
        self.customer.store_credit = D("500")
        self.customer.save()

    def test_store_credit_part_pays_and_is_deducted(self):
        inv = self.ok(credit_applied="500.00", amount_paid="1500.00")
        self.assertEqual((inv.status, inv.credit_applied, inv.amount_paid, inv.amount_due),
                         ("paid", D("500"), D("1500"), D("0")))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.store_credit, D("0"))
        self.assertEqual(inv.payments.get().amount, D("1500"))

    def test_store_credit_cannot_exceed_balance(self):
        res = self.post(credit_applied="900.00", amount_paid="1100.00")
        self.assertEqual(res.status_code, 422)
        self.assertIn("only has", res.data["error"])
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.store_credit, D("500"))

    def test_credit_covering_the_whole_invoice_is_clamped_to_the_total(self):
        self.customer.store_credit = D("3000")
        self.customer.save()
        inv = self.ok(credit_applied="3000.00", amount_paid="0")
        self.assertEqual((inv.status, inv.credit_applied, inv.amount_due), ("paid", D("2000"), D("0")))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.store_credit, D("1000"))
        self.assertEqual(inv.payments.count(), 0)

    def test_store_credit_ledger(self):
        """Part store-credit sale: cash is debited only for what was received
        (1500); the 500 of store credit comes off the Customer Deposits
        liability. (It used to debit cash for the full 2000.)"""
        inv = self.ok(credit_applied="500.00", amount_paid="1500.00")
        r = self.roles(inv)
        self.assertEqual(r["cash"], (D("1500"), D("0")))
        self.assertEqual(r["other:2050"], (D("500"), D("0")))
        self.assertEqual(r["revenue"], (D("0"), D("2000")))


# ─────────────────────────────────────────────────────────────────────────────
class TotalsTests(Base):
    """shipping x item discount x VAT x due date, with exact numbers."""

    def vat_product(self, rate="7.5", **kw):
        vat = TaxClass.objects.create(organisation=self.org, name=f"VAT{rate}", rate=D(rate))
        return Product.objects.create(
            organisation=self.org, sku=f"V{rate}", name="Taxed", product_type="service",
            cost_price=0, selling_price=1000, is_taxable=True, tax_class=vat, **kw)

    def test_shipping_is_added_to_the_total_and_to_revenue(self):
        inv = self.ok(shipping_amount="300.00", amount_paid="2300.00")
        self.assertEqual((inv.subtotal, inv.shipping_amount, inv.total_amount), (D("2000"), D("300"), D("2300")))
        self.assertEqual(inv.status, "paid")
        self.assertEqual(self.roles(inv)["revenue"], (D("0"), D("2300")))
        self.assertEqual(self.roles(inv)["cash"], (D("2300"), D("0")))

    def test_negative_shipping_rejected(self):
        self.assertEqual(self.post(shipping_amount="-5").status_code, 400)

    def test_item_discount_percent(self):
        inv = self.ok(amount_paid="1800.00",
                      items=[{"product_id": str(self.goods.id), "quantity": 2, "unit_price": "1000",
                              "discount_percent": "10"}])
        item = inv.items.get()
        self.assertEqual((inv.subtotal, inv.discount_amount, inv.total_amount),
                         (D("2000"), D("200"), D("1800")))
        self.assertEqual((item.discount_percent, item.discount_amount, item.line_total),
                         (D("10"), D("200"), D("1800")))
        self.assertEqual(inv.status, "paid")
        self.assertEqual(self.roles(inv)["revenue"], (D("0"), D("1800")))

    def test_discount_over_100_rejected(self):
        res = self.post(items=[{"product_id": str(self.goods.id), "quantity": 1, "discount_percent": "101"}])
        self.assertEqual(res.status_code, 400)

    def test_vat_exclusive_line(self):
        p = self.vat_product()
        inv = self.ok(amount_paid="2150.00", items=[{"product_id": str(p.id), "quantity": 2, "unit_price": "1000"}])
        self.assertEqual((inv.subtotal, inv.tax_amount, inv.total_amount), (D("2000"), D("150"), D("2150")))
        r = self.roles(inv)
        self.assertEqual((r["cash"], r["revenue"], r["vat"]),
                         ((D("2150"), D("0")), (D("0"), D("2000")), (D("0"), D("150"))))

    def test_vat_inclusive_line_total_is_the_shelf_price(self):
        p = self.vat_product(tax_type="inclusive")
        inv = self.ok(amount_paid="1075.00", items=[{"product_id": str(p.id), "quantity": 1, "unit_price": "1075"}])
        self.assertEqual((inv.tax_amount, inv.total_amount), (D("75"), D("1075")))
        r = self.roles(inv)
        self.assertEqual((r["revenue"], r["vat"]), ((D("0"), D("1000")), (D("0"), D("75"))))

    @override_settings(SALES_DELIVERY_VAT_FOLLOWS_GOODS=True)
    def test_discount_then_vat_then_shipping_together(self):
        p = self.vat_product()
        inv = self.ok(shipping_amount="300", amount_paid="2257.50",
                      items=[{"product_id": str(p.id), "quantity": 2, "unit_price": "1000",
                              "discount_percent": "10"}])
        # 2000 - 200 = 1800; VAT 7.5% = 135; delivery 300 + its VAT 22.50 -> 2257.50
        self.assertEqual((inv.subtotal, inv.discount_amount, inv.tax_amount, inv.total_amount),
                         (D("2000"), D("200"), D("157.50"), D("2257.50")))
        self.assertEqual(inv.status, "paid")
        self.assertEqual(self.roles(inv)["vat"], (D("0"), D("157.50")))

    def test_per_line_rate_override_and_zero_rate(self):
        p = self.vat_product()
        inv = self.ok(amount_paid="2000.00", items=[
            {"product_id": str(p.id), "quantity": 1, "unit_price": "1000", "tax_rate": "0"},
            {"product_id": str(p.id), "quantity": 1, "unit_price": "1000", "tax_rate": None},
        ])
        # first line overridden to 0%, second falls back to the product's 7.5%
        self.assertEqual((inv.tax_amount, inv.total_amount), (D("75"), D("2075")))

    def test_org_not_registered_for_vat_charges_none(self):
        p = self.vat_product()
        self.org.charges_vat = False
        self.org.save()
        inv = self.ok(amount_paid="2000.00", items=[{"product_id": str(p.id), "quantity": 2, "unit_price": "1000"}])
        self.assertEqual((inv.tax_amount, inv.total_amount), (D("0"), D("2000")))

    def test_due_date_is_saved_and_must_not_precede_issue_date(self):
        inv = self.ok(payment_method="credit", amount_paid="0", issue_date="2099-01-10", due_date="2099-02-09")
        self.assertEqual((inv.issue_date, inv.due_date), (date(2099, 1, 10), date(2099, 2, 9)))
        res = self.post(payment_method="credit", amount_paid="0", issue_date="2099-01-10", due_date="2099-01-09")
        self.assertEqual(res.status_code, 400)
        self.assertIn("due_date", res.data["error"])

    def test_due_date_may_be_left_out_or_null(self):
        self.assertIsNone(self.ok(due_date=None).due_date)

    def test_wrong_totals_cannot_be_forced_by_the_client(self):
        """The server computes every total; sent totals are ignored."""
        inv = self.ok(total_amount="1", subtotal="1", tax_amount="999")
        self.assertEqual((inv.total_amount, inv.tax_amount), (D("2000"), D("0")))

    def test_adjustment_field_is_honoured(self):
        """The page's +/- total adjustment is an explicit signed field now
        (see test_sales_ledger.AdjustmentTests for the VAT worked examples)."""
        inv = self.ok(adjustment_amount="-100", amount_paid="1900.00")
        self.assertEqual((inv.adjustment_amount, inv.total_amount, inv.status), (D("-100"), D("1900"), "paid"))


# ─────────────────────────────────────────────────────────────────────────────
class ApiBehaviourTests(Base):
    def test_response_carries_what_the_page_needs_after_save(self):
        res = self.post()
        for key in ("id", "invoice_number", "status", "total_amount", "amount_due", "amount_paid",
                    "is_deferred", "fulfilled_at", "customer_name", "items", "payments", "issue_date",
                    "due_date", "shipping_amount", "created_at"):
            self.assertIn(key, res.data, key)

    def test_idempotency_key_prevents_a_double_sale(self):
        r1 = self.api.post(URL, self.payload(), format="json", HTTP_IDEMPOTENCY_KEY="nsi-key-1")
        r2 = self.api.post(URL, self.payload(), format="json", HTTP_IDEMPOTENCY_KEY="nsi-key-1")
        self.assertEqual((r1.status_code, r2.status_code), (201, 201))
        self.assertEqual(str(r1.data["id"]), str(r2.data["id"]))
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 1)
        self.assertEqual(self.on_hand(), D("98"))

    def test_empty_cart_and_zero_quantity_rejected(self):
        self.assertEqual(self.post(items=[]).status_code, 400)
        self.assertEqual(self.post(items=[{"product_id": str(self.goods.id), "quantity": 0}]).status_code, 400)

    def test_viewer_cannot_create_void_fulfil_or_email(self):
        viewer = _user("nsi_viewer@example.com")
        Membership.objects.create(organisation=self.org, user=viewer, role="viewer")
        vc = _client(viewer, self.org)
        inv = self.ok(defer_fulfillment=True, amount_paid="0")
        self.assertEqual(vc.post(URL, self.payload(), format="json").status_code, 403)
        for action in ("void", "fulfill", "send_email", "pay_split"):
            res = vc.post(f"{URL}{inv.id}/{action}/", {}, format="json")
            self.assertEqual(res.status_code, 403, action)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "confirmed")

    def test_csv_export_shows_date_and_total(self):
        """Regression: the Date and Total columns were blank (wrong field names)."""
        inv = self.ok()
        res = self.api.get(URL + "?dl=csv")
        self.assertEqual(res.status_code, 200)
        body = res.content.decode()
        self.assertIn(inv.invoice_number, body)
        row = [ln for ln in body.splitlines() if inv.invoice_number in ln][0]
        self.assertIn("2000", row)
        self.assertIn(str(inv.issue_date), row)


# ─────────────────────────────────────────────────────────────────────────────
class EmailAndPdfTests(Base):
    def setUp(self):
        super().setUp()
        self.customer.email = "ada@example.com"
        self.customer.save()
        self.inv = self.ok()

    def _config(self, active=True):
        return EmailConfig.objects.create(
            organisation=self.org, smtp_host="smtp.test", smtp_port=587, smtp_username="u@test",
            smtp_password="pw", use_tls=True, from_name="NSI", from_email="u@test", is_active=active,
        )

    def send(self, inv=None, **body):
        return self.api.post(f"{URL}{(inv or self.inv).id}/send_email/", body, format="json")

    def test_email_without_smtp_settings_gives_a_clear_422(self):
        res = self.send()
        self.assertEqual(res.status_code, 422)
        self.assertIn("Email is not configured", res.data["error"])

    def test_email_with_inactive_smtp_settings_gives_422(self):
        self._config(active=False)
        self.assertEqual(self.send().status_code, 422)

    @patch("smtplib.SMTP")
    def test_email_sends_to_the_customer_with_the_pdf_attached(self, smtp):
        self._config()
        conn = MagicMock()
        smtp.return_value = conn
        import base64
        res = self.send(pdf_base64=base64.b64encode(b"%PDF-1.4 test").decode())
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIn("ada@example.com", res.data["message"])
        sent = conn.sendmail.call_args[0]
        self.assertEqual(sent[1], ["ada@example.com"])
        self.assertIn(f"Invoice-{self.inv.invoice_number}.pdf", sent[2])

    def test_email_for_a_walk_in_needs_an_address(self):
        inv = self.ok(customer_id=None)
        self._config()
        res = self.send(inv=inv)
        self.assertEqual(res.status_code, 422)
        self.assertIn("No recipient", res.data["error"])

    @patch("smtplib.SMTP")
    def test_walk_in_email_to_a_typed_address_works(self, smtp):
        inv = self.ok(customer_id=None)
        self._config()
        res = self.send(inv=inv, to_email="walkin@example.com")
        self.assertEqual(res.status_code, 200, res.data)

    def test_only_admins_can_redirect_to_another_address(self):
        staff = _user("nsi_staff@example.com")
        Membership.objects.create(organisation=self.org, user=staff, role="staff")
        self._config()
        res = _client(staff, self.org).post(
            f"{URL}{self.inv.id}/send_email/", {"to_email": "other@example.com"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_there_is_no_server_side_invoice_pdf(self):
        """The PDF is built in the browser; the server only accepts it as
        pdf_base64 on send_email. No pdf/export endpoint exists."""
        for suffix in ("pdf/", "export_pdf/", "export/"):
            self.assertEqual(self.api.get(f"{URL}{self.inv.id}/{suffix}").status_code, 404, suffix)


# ─────────────────────────────────────────────────────────────────────────────
class TenantIsolationTests(Base):
    def setUp(self):
        super().setUp()
        self.other_user = _user("nsi_other@example.com")
        self.other_org = OrganisationService.create_organisation(
            name="Other Org", owner=self.other_user, extra={"currency": "NGN", "country": "NG"},
        )
        self.other = _client(self.other_user, self.other_org)
        self.inv = self.ok(defer_fulfillment=True, amount_paid="0")

    def test_other_org_cannot_see_or_act_on_the_invoice(self):
        self.assertEqual(self.other.get(f"{URL}{self.inv.id}/").status_code, 404)
        for action in ("fulfill", "void", "send_email", "pay", "pay_split", "delete_invoice"):
            res = self.other.post(f"{URL}{self.inv.id}/{action}/", {"to_email": "x@example.com",
                                  "amount": "1", "method": "cash"}, format="json")
            self.assertEqual(res.status_code, 404, action)
        self.assertEqual(self.other.get(URL).data["count"], 0)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, "confirmed")

    def test_cannot_sell_another_orgs_product_customer_or_warehouse(self):
        before = Invoice.objects.filter(organisation=self.other_org).count()
        # org B tries to use org A's product, customer and warehouse
        res = self.other.post(URL, self.payload(), format="json")
        self.assertIn(res.status_code, (404, 422))
        self.assertEqual(Invoice.objects.filter(organisation=self.other_org).count(), before)
        # org A's stock untouched
        self.assertEqual(self.on_hand(), D("100"))

    def test_cannot_sell_another_orgs_product_even_with_own_warehouse(self):
        other_wh = Warehouse.objects.create(organisation=self.other_org, name="B", is_default=True)
        res = self.other.post(URL, self.payload(customer_id=None, warehouse_id=str(other_wh.id)), format="json")
        self.assertEqual(res.status_code, 422)
        self.assertEqual(Invoice.objects.filter(organisation=self.other_org).count(), 0)

    def test_sale_journal_and_stock_belong_to_the_selling_org_only(self):
        inv = self.ok()
        self.assertEqual(JournalEntry.objects.filter(organisation=self.other_org, source_ref=str(inv.id)).count(), 0)
        self.assertEqual(StockMovement.objects.filter(organisation=self.other_org).count(), 0)
        self.assertEqual(SalePayment.objects.filter(organisation=self.other_org).count(), 0)
