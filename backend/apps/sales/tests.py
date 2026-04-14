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
