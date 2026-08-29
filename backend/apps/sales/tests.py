"""Tests for sales: invoice CRUD, payment, proforma, sale returns."""

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.customers.models import Customer
from apps.inventory.models import Product, Warehouse
from apps.sales.models import Invoice
from apps.tenancy.services import OrganisationService


def _make_user(email="sales_owner@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Sales", last_name="Owner", is_verified=True,
    )


def _make_org(user, name="Sales Org"):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _auth_client(user, org):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return client


def _make_customer(org):
    return Customer.objects.create(
        organisation=org, code="C001", name="Walk-in Customer",
    )


def _make_product(org):
    return Product.objects.create(
        organisation=org, sku="P001", name="Test Product",
        product_type="service",   # service skips inventory movements
        cost_price=500, selling_price=1000, unit_of_measure="unit",
    )


def _make_warehouse(org):
    return Warehouse.objects.create(organisation=org, name="Main", is_default=True)


class InvoiceCreateTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        self.client = _auth_client(self.user, self.org)
        self.customer = _make_customer(self.org)
        self.product = _make_product(self.org)
        self.warehouse = _make_warehouse(self.org)

    def _payload(self, **overrides):
        base = {
            "customer_id": str(self.customer.id),
            "warehouse_id": str(self.warehouse.id),
            "payment_method": "cash",
            "items": [
                {
                    "product_id": str(self.product.id),
                    "quantity": 2,
                    "unit_price": "1000.00",
                }
            ],
        }
        base.update(overrides)
        return base

    def test_create_invoice_success(self):
        res = self.client.post("/api/v1/sales/invoices/", self._payload(), format="json")
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))
        self.assertTrue(Invoice.objects.filter(organisation=self.org).exists())

    def test_create_invoice_generates_number(self):
        res = self.client.post("/api/v1/sales/invoices/", self._payload(), format="json")
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))
        invoice = Invoice.objects.filter(organisation=self.org).first()
        self.assertIsNotNone(invoice.invoice_number)

    def test_invoice_number_unique_per_org(self):
        """Two invoices in the same org must get different numbers."""
        res1 = self.client.post("/api/v1/sales/invoices/", self._payload(), format="json")
        res2 = self.client.post("/api/v1/sales/invoices/", self._payload(), format="json")
        self.assertIn(res1.status_code, [200, 201], msg=str(res1.data))
        self.assertIn(res2.status_code, [200, 201], msg=str(res2.data))
        nums = list(Invoice.objects.filter(organisation=self.org).values_list("invoice_number", flat=True))
        self.assertEqual(len(nums), len(set(nums)))

    def test_create_invoice_missing_items_rejected(self):
        payload = self._payload()
        payload["items"] = []
        res = self.client.post("/api/v1/sales/invoices/", payload, format="json")
        self.assertIn(res.status_code, [400, 422])

    def test_create_proforma_invoice(self):
        payload = self._payload()
        payload["is_proforma"] = True
        res = self.client.post("/api/v1/sales/invoices/", payload, format="json")
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))
        invoice = Invoice.objects.filter(organisation=self.org).first()
        self.assertEqual(invoice.status, Invoice.Status.PROFORMA)

    def test_split_payment_records_multiple_tenders(self):
        """POS split payment: a credit invoice paid part cash + part transfer is
        recorded as two tenders and fully settled."""
        payload = self._payload(payment_method="credit")
        res = self.client.post("/api/v1/sales/invoices/", payload, format="json")
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))
        inv = Invoice.objects.filter(organisation=self.org).latest("created_at")
        total = float(inv.total_amount)
        half = round(total / 2, 2)
        rest = round(total - half, 2)
        pay = self.client.post(f"/api/v1/sales/invoices/{inv.id}/pay_split/", {
            "tenders": [
                {"amount": half, "method": "cash"},
                {"amount": rest, "method": "bank_transfer"},
            ],
        }, format="json")
        self.assertEqual(pay.status_code, 201, msg=str(pay.data))
        self.assertEqual(len(pay.data["payments"]), 2)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.PAID)
        self.assertEqual(float(inv.amount_due), 0.0)

    def test_create_invoice_in_locked_period_returns_clear_message(self):
        """POS/sale into a LOCKED period must return a clear 'locked' message, not the
        opaque 'An unexpected error occurred' toast (the reported POS bug)."""
        from apps.accounting.models import FinancialPeriod
        from django.utils import timezone
        now = timezone.now()
        FinancialPeriod.objects.create(
            organisation=self.org, year=now.year, month=now.month, is_locked=True,
        )
        res = self.client.post("/api/v1/sales/invoices/", self._payload(), format="json")
        self.assertEqual(res.status_code, 422, msg=str(res.data))
        body = str(res.data).lower()
        self.assertIn("locked", body)
        self.assertNotIn("unexpected error", body)


class InvoiceRetrieveTests(TestCase):
    def setUp(self):
        self.user = _make_user("sales_get@example.com")
        self.org = _make_org(self.user, "Sales Get Org")
        self.client = _auth_client(self.user, self.org)
        self.customer = _make_customer(self.org)
        self.product = _make_product(self.org)
        self.warehouse = _make_warehouse(self.org)

    def _create_invoice(self):
        payload = {
            "customer_id": str(self.customer.id),
            "warehouse_id": str(self.warehouse.id),
            "payment_method": "cash",
            "items": [{"product_id": str(self.product.id), "quantity": 1, "unit_price": "500.00"}],
        }
        res = self.client.post("/api/v1/sales/invoices/", payload, format="json")
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))
        return res.data["id"]

    def test_list_invoices(self):
        self._create_invoice()
        res = self.client.get("/api/v1/sales/invoices/")
        self.assertEqual(res.status_code, 200)
        data = res.data.get("results") or res.data
        self.assertGreater(len(data), 0)

    def test_retrieve_invoice_detail(self):
        inv_id = self._create_invoice()
        res = self.client.get(f"/api/v1/sales/invoices/{inv_id}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["id"], inv_id)

    def test_other_org_cannot_access_invoice(self):
        inv_id = self._create_invoice()
        other_user = _make_user("other_sales@example.com")
        other_org = _make_org(other_user, "Other Sales Org")
        c = _auth_client(other_user, other_org)
        res = c.get(f"/api/v1/sales/invoices/{inv_id}/")
        self.assertIn(res.status_code, [403, 404])


class InvoicePaymentTests(TestCase):
    def setUp(self):
        self.user = _make_user("pay_owner@example.com")
        self.org = _make_org(self.user, "Pay Org")
        self.client = _auth_client(self.user, self.org)
        self.customer = _make_customer(self.org)
        self.product = _make_product(self.org)
        self.warehouse = _make_warehouse(self.org)

    def _create_unpaid_invoice(self):
        payload = {
            "customer_id": str(self.customer.id),
            "warehouse_id": str(self.warehouse.id),
            "payment_method": "cash",
            "amount_paid": "0.00",
            "items": [{"product_id": str(self.product.id), "quantity": 1, "unit_price": "1000.00"}],
        }
        res = self.client.post("/api/v1/sales/invoices/", payload, format="json")
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))
        return res.data["id"]

    def test_pay_invoice(self):
        inv_id = self._create_unpaid_invoice()
        res = self.client.post(
            f"/api/v1/sales/invoices/{inv_id}/pay/",
            {"amount": "1000.00", "method": "cash"},
            format="json",
        )
        self.assertIn(res.status_code, [200, 201])

    def test_void_invoice(self):
        inv_id = self._create_unpaid_invoice()
        res = self.client.post(f"/api/v1/sales/invoices/{inv_id}/void/")
        self.assertIn(res.status_code, [200, 204])


class ProformaConfirmTests(TestCase):
    def setUp(self):
        self.user = _make_user("proforma_owner@example.com")
        self.org = _make_org(self.user, "Proforma Org")
        self.client = _auth_client(self.user, self.org)
        self.customer = _make_customer(self.org)
        self.product = _make_product(self.org)
        self.warehouse = _make_warehouse(self.org)

    def test_confirm_proforma_becomes_invoice(self):
        payload = {
            "customer_id": str(self.customer.id),
            "warehouse_id": str(self.warehouse.id),
            "payment_method": "cash",
            "is_proforma": True,
            "items": [{"product_id": str(self.product.id), "quantity": 1, "unit_price": "800.00"}],
        }
        create_res = self.client.post("/api/v1/sales/invoices/", payload, format="json")
        self.assertIn(create_res.status_code, [200, 201])
        inv_id = create_res.data["id"]

        confirm_res = self.client.post(f"/api/v1/sales/invoices/{inv_id}/confirm_proforma/")
        self.assertIn(confirm_res.status_code, [200, 201])
        invoice = Invoice.objects.get(id=inv_id)
        self.assertNotEqual(invoice.status, Invoice.Status.PROFORMA)


class InvoiceStatusBypassTests(TestCase):
    """
    Finding M-1.

    InvoiceViewSet.update allows `status` in ALLOWED_FIELDS and blocked only
    PAID and VOIDED. CONFIRMED was not blocked, so a proforma could be promoted
    to a confirmed sale by PATCH — skipping confirm_proforma entirely, which is
    the only path that deducts stock via InventoryService.record_movement.

    Result: a confirmed sale with inventory never reduced. The stock ledger and
    the sales ledger disagree, and nothing surfaces the discrepancy.
    """

    def setUp(self):
        from datetime import date
        from decimal import Decimal

        self.user = _make_user("invstatus_owner@example.com")
        self.org = _make_org(self.user, "Inv Status Org")
        self.client = _auth_client(self.user, self.org)
        self.customer = _make_customer(self.org)
        self.warehouse = _make_warehouse(self.org)
        self.product = _make_product(self.org)
        self.invoice = Invoice.objects.create(
            organisation=self.org, customer=self.customer, warehouse=self.warehouse,
            invoice_number="INV-STATUS-1", status=Invoice.Status.PROFORMA,
            issue_date=date.today(), due_date=date.today(),
            subtotal=Decimal("100"), total_amount=Decimal("100"), created_by=self.user,
        )

    def _patch(self, payload):
        return self.client.patch(
            f"/api/v1/sales/invoices/{self.invoice.id}/", payload, format="json",
        )

    def test_cannot_confirm_via_patch(self):
        res = self._patch({"status": Invoice.Status.CONFIRMED})
        self.assertIn(
            res.status_code, (400, 422),
            "PATCH promoted a proforma to confirmed, skipping the stock "
            "deduction in confirm_proforma (M-1)",
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PROFORMA)

    def test_cannot_set_partially_paid_via_patch(self):
        res = self._patch({"status": Invoice.Status.PARTIALLY_PAID})
        self.assertIn(res.status_code, (400, 422))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PROFORMA)

    def test_existing_paid_and_voided_guards_still_hold(self):
        """Regression cover for the guard that was already there."""
        for bad in (Invoice.Status.PAID, Invoice.Status.VOIDED):
            with self.subTest(status=bad):
                res = self._patch({"status": bad})
                self.assertIn(res.status_code, (400, 422))
                self.invoice.refresh_from_db()
                self.assertEqual(self.invoice.status, Invoice.Status.PROFORMA)

    def test_can_still_edit_metadata(self):
        res = self._patch({"notes": "Customer asked to hold"})
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.notes, "Customer asked to hold")


class ProductHistoryOpeningBalanceTests(TestCase):
    """
    /sales/invoices/product_history/ must show a product's opening balance,
    not just its sales — otherwise there is no way to see where a stock count
    started. The opening row must be dated from the take-on's JournalEntry
    (the date the user specified), not from StockMovement.created_at (the date
    it happened to be recorded, which can be weeks later for a backdated
    take-on).
    """

    def setUp(self):
        from decimal import Decimal
        self.user = _make_user("history_owner@example.com")
        self.org = _make_org(self.user, "History Org")
        self.client = _auth_client(self.user, self.org)
        self.customer = _make_customer(self.org)
        self.warehouse = _make_warehouse(self.org)
        self.product = Product.objects.create(
            organisation=self.org, sku="HIST-1", name="History Item",
            product_type="physical", cost_price=Decimal("500"),
            selling_price=Decimal("1000"), unit_of_measure="unit",
        )

    def test_opening_balance_row_uses_journal_entry_date_not_created_at(self):
        from apps.accounting.services import AccountingService
        AccountingService.set_item_opening_balance(
            self.org, self.product, self.warehouse, quantity="20",
            unit_cost="500", as_of_date="2026-01-01", created_by=self.user,
        )
        res = self.client.get(
            "/api/v1/sales/invoices/product_history/", {"product_id": str(self.product.id)},
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        results = res.data["results"]
        opening = [r for r in results if r["status"] == "opening"]
        self.assertEqual(len(opening), 1, msg=results)
        row = opening[0]
        # Backdated to 2026-01-01 — must NOT show today's date (created_at).
        self.assertEqual(row["issue_date"], "2026-01-01")
        self.assertEqual(row["quantity"], "20.00")
        self.assertEqual(row["unit_price"], "500.0000")
        self.assertEqual(row["warehouse"], "Main")
        self.assertEqual(row["invoice_number"], "Opening Balance")

    def test_opening_balance_and_sale_both_appear(self):
        from apps.accounting.services import AccountingService
        AccountingService.set_item_opening_balance(
            self.org, self.product, self.warehouse, quantity="20",
            unit_cost="500", as_of_date="2026-01-01", created_by=self.user,
        )
        res = self.client.post(
            "/api/v1/sales/invoices/",
            {
                "customer_id": str(self.customer.id),
                "warehouse_id": str(self.warehouse.id),
                "payment_method": "cash",
                "items": [{"product_id": str(self.product.id), "quantity": 3, "unit_price": "1000.00"}],
            },
            format="json",
        )
        self.assertIn(res.status_code, (200, 201), msg=str(res.data))

        res = self.client.get(
            "/api/v1/sales/invoices/product_history/", {"product_id": str(self.product.id)},
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        results = res.data["results"]
        statuses = [r["status"] for r in results]
        self.assertIn("opening", statuses)
        self.assertTrue(any(s != "opening" for s in statuses), msg=results)

    def test_reposted_opening_balance_updates_row_not_duplicates(self):
        """Correcting the opening qty must show ONE current row, not a growing history."""
        from apps.accounting.services import AccountingService
        AccountingService.set_item_opening_balance(
            self.org, self.product, self.warehouse, quantity="20",
            unit_cost="500", as_of_date="2026-01-01", created_by=self.user,
        )
        AccountingService.set_item_opening_balance(
            self.org, self.product, self.warehouse, quantity="35",
            unit_cost="500", as_of_date="2026-01-05", created_by=self.user,
        )
        res = self.client.get(
            "/api/v1/sales/invoices/product_history/", {"product_id": str(self.product.id)},
        )
        opening = [r for r in res.data["results"] if r["status"] == "opening"]
        self.assertEqual(len(opening), 1, msg=opening)
        self.assertEqual(opening[0]["quantity"], "35.00")
        self.assertEqual(opening[0]["issue_date"], "2026-01-05")

    def test_no_opening_balance_means_no_synthetic_row(self):
        res = self.client.get(
            "/api/v1/sales/invoices/product_history/", {"product_id": str(self.product.id)},
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["results"], [])

    def test_date_filter_applies_to_opening_row(self):
        from apps.accounting.services import AccountingService
        AccountingService.set_item_opening_balance(
            self.org, self.product, self.warehouse, quantity="20",
            unit_cost="500", as_of_date="2026-01-01", created_by=self.user,
        )
        res = self.client.get(
            "/api/v1/sales/invoices/product_history/",
            {"product_id": str(self.product.id), "date_from": "2026-02-01"},
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["results"], [])
