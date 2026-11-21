"""
Design phase 2 QA: the numbers behind the merged "New sale & invoice" page.

Every expected value below was worked out by hand (the working is in the
comment above each case), NOT copied from what the code printed. VAT is the
Nigerian standard rate, 7.5%.

What this file covers that sales/tests.py does not:
  * saved totals + journal lines for each payment method (cash, card/pos,
    bank transfer, credit, part-paid) with 7.5% VAT, discount and delivery
  * stock movement for now / proforma / fulfil-later, and the reverse on void
  * rounding edges at the kobo and zero / negative amounts
  * tenant isolation on create (another tenant's product, customer, warehouse)
    and on every invoice action (pay, void, fulfil, delete)

It deliberately does NOT test the "total adjustment" field: that field does
not exist on this branch yet (it arrives with feat/new-sale-and-invoice-backend).
See ``TotalAdjustmentPending`` at the bottom, which is skipped until it does.
"""

from decimal import Decimal
from unittest import skipUnless

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.models import Account, JournalEntry
from apps.accounting.services import AccountMappingService
from apps.authentication.models import User
from apps.customers.models import Customer
from apps.inventory.models import Product, StockItem, Warehouse
from apps.inventory.services import InventoryService
from apps.sales.models import Invoice, SalePayment
from apps.tax.models import TaxClass
from apps.tenancy.services import OrganisationService

D = Decimal
URL = "/api/v1/sales/invoices/"


def _user(email):
    return User.objects.create_user(
        email=email, password="TestPass123!", first_name="Q", last_name="A", is_verified=True,
    )


def _org(user, name):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _client(user, org):
    c = APIClient()
    token = RefreshToken.for_user(user).access_token
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_ORGANISATION_ID=str(org.id))
    return c


class Base(TestCase):
    maxDiff = None
    """One tenant with a 7.5% VAT class, a stocked product (cost 600, price 1000,
    10 on hand) and a service product (no stock)."""

    def setUp(self):
        self.user = _user("p2qa_a@example.com")
        self.org = _org(self.user, "P2 QA Org A")
        self.api = _client(self.user, self.org)
        self.wh = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.cust = Customer.objects.create(organisation=self.org, code="C1", name="Named Customer")
        self.vat = TaxClass.objects.create(organisation=self.org, name="VAT 7.5%", rate=D("7.5"))
        self.stocked = self._product("STK", "Stocked", cost=600, price=1000, ptype="physical",
                                     taxable=True, tax_type="exclusive")
        InventoryService.record_movement(
            self.org, self.stocked, self.wh, D("10"), "opening", unit_cost=D("600"),
            reference="p2qa-seed", created_by=self.user,
        )

    def _product(self, sku, name, cost, price, ptype="service", taxable=False, tax_type="exclusive"):
        kw = dict(organisation=self.org, sku=sku, name=name, product_type=ptype,
                  cost_price=cost, selling_price=price, unit_of_measure="unit")
        if taxable:
            kw.update(is_taxable=True, tax_class=self.vat, tax_type=tax_type)
        return Product.objects.create(**kw)

    def sell(self, items, method="cash", expect=201, **extra):
        body = {"warehouse_id": str(self.wh.id), "payment_method": method, "items": items}
        # The API records a payment only when amount_paid is sent (the screens always
        # send it; omitted means "nothing paid yet" -> status confirmed, DR receivable;
        # see test_cash_sale_without_amount_paid_is_unpaid below). A very large figure
        # is clamped to what is owed, i.e. "paid in full".
        if method != "credit" and not extra.get("is_proforma") and "amount_paid" not in extra:
            body["amount_paid"] = "99999999.00"
        body.update(extra)
        res = self.api.post(URL, body, format="json")
        self.assertEqual(res.status_code, expect, getattr(res, "data", res.content))
        return Invoice.objects.get(id=res.data["id"]) if expect == 201 else res

    def line(self, product=None, qty="1", price=None, disc=None):
        d = {"product_id": str((product or self.stocked).id), "quantity": qty}
        if price is not None:
            d["unit_price"] = price
        if disc is not None:
            d["discount_percent"] = disc
        return d

    def on_hand(self, product=None):
        return StockItem.objects.get(product=product or self.stocked, warehouse=self.wh).quantity_on_hand

    def role(self, name):
        return AccountMappingService.resolve(self.org, name)

    def journal(self, invoice):
        """{account_id: (total debit, total credit)} for the invoice's sale journal."""
        entry = JournalEntry.objects.get(
            organisation=self.org, source_type="sale", source_ref=str(invoice.id))
        out = {}
        for ln in entry.lines.all():
            dr, cr = out.get(ln.account_id, (D(0), D(0)))
            out[ln.account_id] = (dr + D(str(ln.debit)), cr + D(str(ln.credit)))
        self.assertEqual(sum(v[0] for v in out.values()), sum(v[1] for v in out.values()),
                         "journal does not balance")
        return out

    def no_journal(self, invoice):
        self.assertFalse(JournalEntry.objects.filter(
            organisation=self.org, source_type="sale", source_ref=str(invoice.id)).exists())

    def assertJ(self, invoice, expected):
        """expected: {role: (dr, cr)}; any role not listed must not appear."""
        got = self.journal(invoice)
        want = {self.role(r).id: (D(str(dr)), D(str(cr))) for r, (dr, cr) in expected.items()}
        names = {a.id: f'{a.code} {a.name}' for a in Account.objects.filter(organisation=self.org)}
        self.assertEqual({names[k]: v for k, v in got.items()}, {names[k]: v for k, v in want.items()})


class SavedValuesByPaymentMethod(Base):
    # 3 x 1000 less 10% = 3000 - 300 = 2700; VAT 7.5% of 2700 = 202.50; total 2902.50.
    # COGS = 3 x 600 = 1800.
    def test_cash_walkin_vat_exclusive_discount(self):
        inv = self.sell([self.line(qty="3", disc="10")], "cash")
        self.assertEqual((inv.subtotal, inv.discount_amount, inv.tax_amount, inv.total_amount),
                         (D("3000"), D("300"), D("202.50"), D("2902.50")))
        self.assertEqual((inv.amount_paid, inv.amount_due, inv.status), (D("2902.50"), D(0), "paid"))
        self.assertIsNone(inv.customer)
        self.assertEqual(self.on_hand(), D("7"))
        self.assertJ(inv, {
            "cash_account": ("2902.50", 0),
            "revenue_account": (0, "2700"),
            "vat_output_account": (0, "202.50"),
            "cogs_account": ("1800", 0),
            "inventory_account": (0, "1800"),
        })

    def test_card_pos_goes_to_bank_not_cash(self):
        inv = self.sell([self.line(qty="1")], "pos")          # 1000 + 75 = 1075
        self.assertEqual(inv.total_amount, D("1075"))
        self.assertJ(inv, {
            "bank_account": ("1075", 0), "revenue_account": (0, "1000"),
            "vat_output_account": (0, "75"), "cogs_account": ("600", 0),
            "inventory_account": (0, "600"),
        })

    def test_bank_transfer_goes_to_bank(self):
        inv = self.sell([self.line(qty="1")], "bank_transfer")
        self.assertEqual(inv.status, "paid")
        self.assertIn(self.role("bank_account").id, self.journal(inv))
        self.assertNotIn(self.role("cash_account").id, self.journal(inv))

    def test_credit_sale_named_customer_posts_to_receivable(self):
        inv = self.sell([self.line(qty="2")], "credit", customer_id=str(self.cust.id))
        # 2 x 1000 = 2000, VAT 150, total 2150, nothing paid.
        self.assertEqual((inv.total_amount, inv.amount_paid, inv.amount_due, inv.status),
                         (D("2150"), D(0), D("2150"), "credit"))
        self.assertFalse(SalePayment.objects.filter(invoice=inv).exists())
        self.cust.refresh_from_db()
        self.assertEqual(self.cust.outstanding_balance, D("2150"))
        self.assertJ(inv, {
            "accounts_receivable": ("2150", 0), "revenue_account": (0, "2000"),
            "vat_output_account": (0, "150"), "cogs_account": ("1200", 0),
            "inventory_account": (0, "1200"),
        })

    def test_credit_sale_without_customer_is_refused_and_leaves_nothing_behind(self):
        before = (Invoice.objects.count(), self.on_hand())
        res = self.sell([self.line()], "credit", expect=422)
        self.assertEqual((Invoice.objects.count(), self.on_hand()), before)
        self.assertIn("Customer is required", str(res.data))

    def test_part_payment_splits_cash_and_receivable(self):
        inv = self.sell([self.line(qty="3", disc="10")], "cash",
                        customer_id=str(self.cust.id), amount_paid="1000.00")
        self.assertEqual((inv.total_amount, inv.amount_paid, inv.amount_due, inv.status),
                         (D("2902.50"), D("1000"), D("1902.50"), "partially_paid"))
        self.assertJ(inv, {
            "cash_account": ("1000", 0), "accounts_receivable": ("1902.50", 0),
            "revenue_account": (0, "2700"), "vat_output_account": (0, "202.50"),
            "cogs_account": ("1800", 0), "inventory_account": (0, "1800"),
        })

    def test_cash_sale_without_amount_paid_is_unpaid(self):
        """Characterisation, not a bug: the API treats a missing amount_paid as
        'nothing paid'. A screen that forgets to send it saves a cash sale as
        confirmed / owed (DR receivable, not DR cash). The merged page must always send it."""
        body = {"warehouse_id": str(self.wh.id), "payment_method": "cash",
                "items": [self.line(qty="1")],
                "allow_unpaid_walk_in": True}   # a walk-in is otherwise refused (manager+ flag)
        res = self.api.post(URL, body, format="json")
        self.assertEqual(res.status_code, 201)
        inv = Invoice.objects.get(id=res.data["id"])
        self.assertEqual((inv.amount_paid, inv.amount_due, inv.status), (D(0), D("1075"), "confirmed"))
        self.assertIn(self.role("accounts_receivable").id, self.journal(inv))

    def test_overpayment_is_clamped_to_the_total(self):
        inv = self.sell([self.line()], "cash", amount_paid="5000.00", amount_tendered="5000.00")
        self.assertEqual((inv.amount_paid, inv.amount_due, inv.status), (D("1075"), D(0), "paid"))
        self.assertEqual(SalePayment.objects.get(invoice=inv).amount, D("1075"))


class VatShippingDiscountEdges(Base):
    def test_vat_inclusive_price_is_the_total(self):
        p = self._product("INC", "Inclusive", 0, 1075, taxable=True, tax_type="inclusive")
        inv = self.sell([self.line(p, "1")], "cash")
        # 1075 x 7.5/107.5 = 75.00 ; revenue 1000.
        self.assertEqual((inv.total_amount, inv.tax_amount), (D("1075"), D("75")))
        self.assertJ(inv, {"cash_account": ("1075", 0), "revenue_account": (0, "1000"),
                           "vat_output_account": (0, "75")})

    def test_no_vat_product(self):
        p = self._product("NOV", "Untaxed", 0, 500)
        inv = self.sell([self.line(p, "2")], "cash")
        self.assertEqual((inv.tax_amount, inv.total_amount), (D(0), D("1000")))
        self.assertNotIn(self.role("vat_output_account").id, self.journal(inv))

    def test_delivery_is_not_taxed_and_is_revenue(self):
        inv = self.sell([self.line(qty="1")], "cash", shipping_amount="500.00")
        # 1000 + VAT 75 + delivery 500 = 1575. VAT is on goods only.
        self.assertEqual((inv.tax_amount, inv.total_amount, inv.shipping_amount),
                         (D("75"), D("1575"), D("500")))
        self.assertJ(inv, {"cash_account": ("1575", 0), "revenue_account": (0, "1500"),
                           "vat_output_account": (0, "75"), "cogs_account": ("600", 0),
                           "inventory_account": (0, "600")})

    def test_mixed_inclusive_and_exclusive_lines(self):
        inc = self._product("INC2", "Inclusive2", 0, 1075, taxable=True, tax_type="inclusive")
        inv = self.sell([self.line(self.stocked, "1"), self.line(inc, "1")], "cash")
        # exclusive 1000 -> tax 75 total 1075 ; inclusive 1075 -> tax 75 total 1075.
        self.assertEqual((inv.tax_amount, inv.total_amount), (D("150"), D("2150")))

    def test_rounding_half_up_at_the_kobo(self):
        # 3 x 33.33 = 99.99 ; 7.5% = 7.49925 -> 7.50 ; total 107.49
        p = self._product("R1", "R1", 0, 33.33, taxable=True)
        inv = self.sell([self.line(p, "3")], "cash")
        self.assertEqual((inv.subtotal, inv.tax_amount, inv.total_amount),
                         (D("99.99"), D("7.50"), D("107.49")))
        # 0.10 -> VAT 0.0075 -> 0.01 (half-up) ; total 0.11
        p2 = self._product("R2", "R2", 0, "0.10", taxable=True)
        inv2 = self.sell([self.line(p2, "1")], "cash")
        self.assertEqual((inv2.tax_amount, inv2.total_amount), (D("0.01"), D("0.11")))
        # 0.06 -> VAT 0.0045 -> 0.00 (below half) ; total 0.06
        p3 = self._product("R3", "R3", 0, "0.06", taxable=True)
        inv3 = self.sell([self.line(p3, "1")], "cash")
        self.assertEqual((inv3.tax_amount, inv3.total_amount), (D(0), D("0.06")))

    def test_each_line_rounds_on_its_own_before_summing(self):
        # two lines of 0.10: each tax 0.0075 -> 0.01, so tax 0.02 (not 0.015 -> 0.02 by luck)
        # use 0.06 x2: each 0.0045 -> 0.00, so tax is 0.00 (a sum-then-round would give 0.01)
        p = self._product("R4", "R4", 0, "0.06", taxable=True)
        inv = self.sell([self.line(p, "1"), self.line(p, "1")], "cash")
        self.assertEqual((inv.tax_amount, inv.total_amount), (D(0), D("0.12")))

    def test_100_percent_discount_gives_zero_total_and_no_payment_row(self):
        inv = self.sell([self.line(qty="1", disc="100")], "cash")
        self.assertEqual((inv.total_amount, inv.tax_amount, inv.amount_due), (D(0), D(0), D(0)))
        self.assertFalse(SalePayment.objects.filter(invoice=inv).exists())

    def test_zero_quantity_is_refused(self):
        self.sell([self.line(qty="0")], "cash", expect=400)

    def test_negative_quantity_is_refused(self):
        self.sell([self.line(qty="-1")], "cash", expect=400)

    def test_discount_over_100_or_negative_is_refused(self):
        self.sell([self.line(disc="101")], "cash", expect=400)
        self.sell([self.line(disc="-1")], "cash", expect=400)

    def test_vat_override_rate_zero_wins_over_product_class(self):
        d = self.line(qty="1")
        d["tax_rate"] = "0"
        inv = self.sell([d], "cash")
        self.assertEqual((inv.tax_amount, inv.total_amount), (D(0), D("1000")))


class StockAndFulfilment(Base):
    def test_sale_now_deducts_stock_and_posts_journal(self):
        self.sell([self.line(qty="4")], "cash")
        self.assertEqual(self.on_hand(), D("6"))

    def test_insufficient_stock_is_refused_and_nothing_is_saved(self):
        before = Invoice.objects.count()
        res = self.sell([self.line(qty="11")], "cash", expect=422)
        self.assertEqual(Invoice.objects.count(), before)
        self.assertEqual(self.on_hand(), D("10"))

    def test_proforma_touches_neither_stock_nor_ledger(self):
        inv = self.sell([self.line(qty="2")], "cash", is_proforma=True)
        self.assertEqual(inv.status, "proforma")
        self.assertEqual(inv.total_amount, D("2150"))
        self.assertEqual(self.on_hand(), D("10"))
        self.no_journal(inv)
        self.assertFalse(SalePayment.objects.filter(invoice=inv).exists())

    def test_fulfil_later_holds_stock_and_revenue_until_fulfilled(self):
        """Accountant-approved rules: VAT is due on invoice/receipt, so it is booked when the
        invoice is raised (with the cash and the held sale in Customer Deposits); stock, revenue
        and COGS wait for delivery."""
        inv = self.sell([self.line(qty="2")], "cash", defer_fulfillment=True)
        self.assertTrue(inv.is_deferred)
        self.assertIsNone(inv.fulfilled_at)
        self.assertEqual(self.on_hand(), D("10"))
        self.no_journal(inv)                       # no revenue / COGS entry yet
        raised = JournalEntry.objects.get(organisation=self.org, source_type="sale_deferred",
                                          source_ref=str(inv.id))
        self.assertIn(self.role("vat_output_account").id, {l.account_id for l in raised.lines.all()})
        res = self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertEqual(res.status_code, 200, res.data)
        inv.refresh_from_db()
        self.assertIsNotNone(inv.fulfilled_at)
        self.assertEqual(self.on_hand(), D("8"))
        self.assertIn(self.role("revenue_account").id, self.journal(inv))

    def test_fulfil_twice_is_refused_and_does_not_deduct_twice(self):
        inv = self.sell([self.line(qty="2")], "cash", defer_fulfillment=True)
        self.assertEqual(self.api.post(f"{URL}{inv.id}/fulfill/").status_code, 200)
        again = self.api.post(f"{URL}{inv.id}/fulfill/")
        self.assertEqual(again.status_code, 422)
        self.assertEqual(self.on_hand(), D("8"))

    def _net_after_void(self, inv):
        res = self.api.post(f"{URL}{inv.id}/void/", {"reason": "qa"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "voided")
        from apps.accounting.models import JournalLine
        # the org holds only this one sale (plus the opening-stock entry, which touches
        # inventory only), so these accounts must all be back to zero after a void
        net = {}
        for l in JournalLine.objects.filter(journal_entry__organisation=self.org,
                                            journal_entry__status="posted"):
            net[l.account_id] = net.get(l.account_id, D(0)) + D(str(l.debit)) - D(str(l.credit))
        return {role: net.get(self.role(role).id, D(0)) for role in (
            "cash_account", "bank_account", "accounts_receivable", "revenue_account",
            "vat_output_account", "cogs_account")}

    def test_void_of_a_plain_unpaid_sale_puts_stock_back_and_nets_the_ledger_to_zero(self):
        inv = self.sell([self.line(qty="2")], "cash", amount_paid="0",
                        customer_id=str(self.cust.id))      # 2000 + 150 VAT (a walk-in cannot owe)
        self.assertEqual((inv.status, inv.amount_due), ("confirmed", D("2150")))
        self.assertEqual(self.on_hand(), D("8"))
        net = self._net_after_void(inv)
        self.assertEqual(self.on_hand(), D("10"))
        self.assertEqual({k: v for k, v in net.items() if v != 0}, {})

    # BUG FOUND BY QA (design phase 2 baseline). SaleService.void_invoice reverses revenue
    # with invoice.subtotal (BEFORE discount) and ignores delivery, so for a sale with a
    # discount or a delivery charge the reversing journal does not balance, post_journal_entry
    # rejects it, and the surrounding `except Exception` only logs it. Result: invoice shows
    # voided and stock is restored, but the ledger keeps the sale (receivable, revenue, VAT).
    # Worked example below: 3 x 1000 less 10% (2700) + 202.50 VAT = 2902.50. Reversal posts
    # CR AR 2902.50 but DR Revenue 3000 + DR VAT 202.50 = 3202.50 -> off by the 300 discount.
    # FIXED in the sales ledger rebuild: void now mirrors the original entries exactly.
    def test_void_with_a_discount_nets_the_ledger_to_zero(self):
        inv = self.sell([self.line(qty="3", disc="10")], "cash", amount_paid="0",
                        customer_id=str(self.cust.id))
        net = self._net_after_void(inv)
        self.assertEqual({k: v for k, v in net.items() if v != 0}, {})

    def test_void_with_delivery_nets_the_ledger_to_zero(self):
        # total 1575 = 1000 + 75 VAT + 500 delivery
        inv = self.sell([self.line(qty="1")], "cash", amount_paid="0", shipping_amount="500.00",
                        customer_id=str(self.cust.id))
        net = self._net_after_void(inv)
        self.assertEqual({k: v for k, v in net.items() if v != 0}, {})

    def test_a_paid_sale_cannot_be_voided_it_needs_a_return(self):
        inv = self.sell([self.line(qty="1")], "cash")
        res = self.api.post(f"{URL}{inv.id}/void/", {"reason": "qa"}, format="json")
        self.assertEqual(res.status_code, 422)
        self.assertIn("return", str(res.data).lower())
        self.assertEqual(self.on_hand(), D("9"))


class TenantIsolation(Base):
    def setUp(self):
        super().setUp()
        self.inv = self.sell([self.line(qty="1")], "cash", customer_id=str(self.cust.id),
                             defer_fulfillment=True)
        self.status_before = self.inv.status
        self.user_b = _user("p2qa_b@example.com")
        self.org_b = _org(self.user_b, "P2 QA Org B")
        self.api_b = _client(self.user_b, self.org_b)
        self.wh_b = Warehouse.objects.create(organisation=self.org_b, name="B Main", is_default=True)

    def test_b_cannot_see_a_in_list_or_detail(self):
        res = self.api_b.get(URL)
        rows = res.data.get("results", res.data)
        self.assertNotIn(str(self.inv.id), [str(r["id"]) for r in rows])
        self.assertIn(self.api_b.get(f"{URL}{self.inv.id}/").status_code, (403, 404))

    def test_b_cannot_pay_void_fulfil_or_delete_a(self):
        for verb, path, body in (
            ("post", f"{URL}{self.inv.id}/pay/", {"amount": "10", "method": "cash"}),
            ("post", f"{URL}{self.inv.id}/void/", {"reason": "x"}),
            ("post", f"{URL}{self.inv.id}/fulfill/", {}),
            ("delete", f"{URL}{self.inv.id}/", None),
            ("patch", f"{URL}{self.inv.id}/", {"notes": "hacked"}),
        ):
            res = getattr(self.api_b, verb)(path, body, format="json") if body is not None \
                else getattr(self.api_b, verb)(path)
            self.assertIn(res.status_code, (403, 404), f"{verb} {path} -> {res.status_code}")
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.status, self.status_before)
        self.assertNotEqual(self.inv.notes, "hacked")
        self.assertFalse(self.inv.is_deleted if hasattr(self.inv, "is_deleted") else False)

    def test_b_cannot_sell_a_product_or_use_a_customer_from_a(self):
        body = {"warehouse_id": str(self.wh_b.id), "payment_method": "cash",
                "items": [{"product_id": str(self.stocked.id), "quantity": "1"}]}
        res = self.api_b.post(URL, body, format="json")
        self.assertIn(res.status_code, (400, 403, 404, 422), res.data)
        self.assertEqual(self.on_hand(), D("10"))
        free = Product.objects.create(organisation=self.org_b, sku="BFREE", name="B item",
                                      product_type="service", cost_price=0, selling_price=100)
        body = {"warehouse_id": str(self.wh_b.id), "payment_method": "cash",
                "customer_id": str(self.cust.id),
                "items": [{"product_id": str(free.id), "quantity": "1"}]}
        res = self.api_b.post(URL, body, format="json")
        self.assertIn(res.status_code, (400, 403, 404, 422), res.data)
        body["customer_id"] = None
        body["warehouse_id"] = str(self.wh.id)           # A's warehouse
        res = self.api_b.post(URL, body, format="json")
        self.assertIn(res.status_code, (400, 403, 404, 422), res.data)
        self.assertEqual(Invoice.objects.filter(organisation=self.org_b).count(), 0)

    def test_invoice_numbers_do_not_leak_between_tenants(self):
        free = Product.objects.create(organisation=self.org_b, sku="BF2", name="B item",
                                      product_type="service", cost_price=0, selling_price=100)
        res = self.api_b.post(URL, {"warehouse_id": str(self.wh_b.id), "payment_method": "cash",
                                    "amount_paid": "100",
                                    "items": [{"product_id": str(free.id), "quantity": "1"}]},
                              format="json")
        self.assertEqual(res.status_code, 201, res.data)
        b = Invoice.objects.get(id=res.data["id"])
        self.assertEqual(b.organisation_id, self.org_b.id)
        self.assertEqual(JournalEntry.objects.filter(
            organisation=self.org_b, source_ref=str(self.inv.id)).count(), 0)


try:
    from apps.sales.models import Invoice as _I
    _HAS_ADJ = any(f.name in ("total_adjustment", "adjustment_amount") for f in _I._meta.get_fields())
except Exception:  # pragma: no cover
    _HAS_ADJ = False


@skipUnless(_HAS_ADJ, "total adjustment field not on this branch yet")
class TotalAdjustmentPending(Base):
    """Switches on by itself once the backend branch adds the field.
    Settled rule (tax expert, Nigeria Tax Act 2025): the adjustment is spread over the
    lines BEFORE VAT, so VAT moves with it. Hand-computed on one 1,000 line at 7.5%:
      +  adjustment +100 -> net 1100, VAT 82.50, total 1182.50
      -  adjustment  -75 -> net  925, VAT 69.38 (69.375 rounded), total 994.38
    and the journal must still balance."""

    def test_positive_and_negative(self):
        pos = self.sell([self.line(qty="1")], "cash", adjustment_amount="100.00")
        self.assertEqual((pos.total_amount, pos.tax_amount), (D("1182.50"), D("82.50")))
        neg = self.sell([self.line(qty="1")], "cash", adjustment_amount="-75.00")
        self.assertEqual((neg.total_amount, neg.tax_amount), (D("994.38"), D("69.38")))
        self.journal(pos)
        self.journal(neg)
