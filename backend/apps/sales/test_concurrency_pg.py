"""
Real two-connection concurrency tests (PostgreSQL only).

The ordinary tests run inside one transaction on one connection, so a row lock can never be
contended and a "lost update" can never happen. These use TransactionTestCase and real
threads, each with its OWN database connection, so the locks are actually fought over.
Skipped on SQLite (no row locks).

  1. Two sales spend the same 300 of store credit at the same moment: exactly one may win.
  2. A payment lands while an edit of the same invoice is in flight: the payment must survive.
        a. the editor holds a stale copy loaded BEFORE the payment committed
        b. the editor holds the row lock and the payment arrives and has to wait
"""

import threading
import time
from decimal import Decimal

from django.db import connection, connections
from django.test import TransactionTestCase
from unittest import skipUnless
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.models import JournalLine
from apps.authentication.models import User
from apps.customers.models import Customer
from apps.inventory.models import Product, Warehouse
from apps.inventory.services import InventoryService
from apps.sales.models import Invoice, SalePayment
from apps.sales.services import SaleService
from apps.tenancy.services import OrganisationService

D = Decimal
URL = "/api/v1/sales/invoices/"
IS_PG = connection.vendor == "postgresql"


def _client(user, org):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}",
                  HTTP_X_ORGANISATION_ID=str(org.id))
    return c


@skipUnless(IS_PG, "needs PostgreSQL row locks")
class TwoConnectionRaces(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="conc@example.com", password="TestPass123!",
                                             first_name="C", last_name="C", is_verified=True)
        self.org = OrganisationService.create_organisation(
            name="Concurrency Org", owner=self.user, extra={"currency": "NGN", "country": "NG"})
        self.wh = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.prod = Product.objects.create(
            organisation=self.org, sku="G1", name="Goods", product_type="physical",
            cost_price=600, selling_price=1000, unit_of_measure="unit")
        InventoryService.record_movement(
            organisation=self.org, product=self.prod, warehouse=self.wh, quantity=D("100"),
            movement_type="purchase_in", unit_cost=D("600"), created_by=self.user)
        self.cust = Customer.objects.create(organisation=self.org, code="C1", name="Named",
                                            store_credit=D("300"))

    def _body(self, **extra):
        b = {"warehouse_id": str(self.wh.id), "customer_id": str(self.cust.id), "payment_method": "cash",
             "items": [{"product_id": str(self.prod.id), "quantity": 1, "unit_price": "1000"}]}
        b.update(extra)
        return b

    # ── 1 ──────────────────────────────────────────────────────────────────
    def test_two_sales_cannot_spend_the_same_store_credit(self):
        barrier = threading.Barrier(2)
        results = []

        def sell():
            try:
                api = _client(self.user, self.org)
                barrier.wait(timeout=10)
                r = api.post(URL, self._body(credit_applied="300.00", amount_paid="700.00"), format="json")
                results.append((r.status_code, getattr(r, "data", None)))
            finally:
                connections.close_all()

        ts = [threading.Thread(target=sell) for _ in range(2)]
        [t.start() for t in ts]
        [t.join(60) for t in ts]
        codes = sorted(c for c, _ in results)
        self.assertEqual(len(codes), 2, results)
        self.assertEqual(codes[0], 201, results)                 # exactly one wins ...
        self.assertGreaterEqual(codes[1], 400, results)          # ... the other is refused
        self.assertLess(codes[1], 500, results)                  # refused, not crashed
        self.cust.refresh_from_db()
        self.assertEqual(self.cust.store_credit, D("0"))         # spent once, never negative
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 1)
        deposits = JournalLine.objects.filter(
            journal_entry__organisation=self.org, account__code="2050")
        self.assertEqual(sum((l.debit - l.credit for l in deposits), D("0")), D("300"))

    # ── 2a ─────────────────────────────────────────────────────────────────
    def _credit_invoice(self):
        r = _client(self.user, self.org).post(URL, self._body(payment_method="credit", amount_paid="0"), format="json")
        self.assertEqual(r.status_code, 201, getattr(r, "data", None))
        return Invoice.objects.get(id=r.data["id"])

    def test_payment_that_lands_after_the_editor_loaded_the_invoice_is_not_overwritten(self):
        inv = self._credit_invoice()                       # total 1000, nothing paid
        stale = Invoice.objects.get(pk=inv.pk)             # what a slow editor is holding
        self.assertEqual(stale.amount_paid, D("0"))
        errors = []

        def pay():
            try:
                SaleService.record_payment(Invoice.objects.get(pk=inv.pk), D("400"), "cash", received_by=self.user)
            except Exception as e:  # pragma: no cover
                errors.append(e)
            finally:
                connections.close_all()

        t = threading.Thread(target=pay)
        t.start(); t.join(60)
        self.assertEqual(errors, [])
        # now the editor saves from its stale copy: price 1000 -> 1500
        SaleService.update_sale(stale, self.user, items=[
            {"product_id": str(self.prod.id), "quantity": 1, "unit_price": D("1500")}])
        inv.refresh_from_db()
        self.assertEqual(inv.total_amount, D("1500"))
        self.assertEqual(inv.amount_paid, D("400"), "the payment was overwritten by the stale edit")
        self.assertEqual(inv.amount_due, D("1100"))
        self.assertEqual(inv.status, "partially_paid")
        self.assertEqual(SalePayment.objects.filter(invoice=inv).count(), 1)
        self.cust.refresh_from_db()
        self.assertEqual(self.cust.outstanding_balance, D("1100"))   # 1500 owed less 400 paid
        ar = JournalLine.objects.filter(journal_entry__organisation=self.org, account__code="1100")
        self.assertEqual(sum((l.debit - l.credit for l in ar), D("0")), D("1100"))

    # ── 2b ─────────────────────────────────────────────────────────────────
    def test_payment_that_arrives_during_an_edit_waits_and_lands_on_top_of_it(self):
        inv = self._credit_invoice()
        edit_has_lock = threading.Event()
        pay_started = threading.Event()
        out = {}

        def edit():
            try:
                from django.db import transaction
                with transaction.atomic():
                    locked = Invoice.objects.select_for_update().get(pk=inv.pk)
                    edit_has_lock.set()
                    pay_started.wait(10)
                    time.sleep(1.5)                          # the payment is now queued behind us
                    SaleService.update_sale(locked, self.user, items=[
                        {"product_id": str(self.prod.id), "quantity": 1, "unit_price": D("1500")}])
            except Exception as e:  # pragma: no cover
                out["edit_error"] = e
            finally:
                connections.close_all()

        def pay():
            try:
                edit_has_lock.wait(10)
                pay_started.set()
                t0 = time.time()
                SaleService.record_payment(Invoice.objects.get(pk=inv.pk), D("400"), "cash", received_by=self.user)
                out["waited"] = time.time() - t0
            except Exception as e:  # pragma: no cover
                out["pay_error"] = e
            finally:
                connections.close_all()

        ts = [threading.Thread(target=edit), threading.Thread(target=pay)]
        [t.start() for t in ts]
        [t.join(60) for t in ts]
        self.assertNotIn("edit_error", out, out)
        self.assertNotIn("pay_error", out, out)
        self.assertGreater(out["waited"], 1.0, "the payment did not wait for the edit's lock")
        inv.refresh_from_db()
        self.assertEqual((inv.total_amount, inv.amount_paid, inv.amount_due), (D("1500"), D("400"), D("1100")))
        self.assertEqual(inv.status, "partially_paid")
        self.cust.refresh_from_db()
        self.assertEqual(self.cust.outstanding_balance, D("1100"))
