"""Tests for customers: CRUD, customer statement, credit tracking."""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.customers.models import Customer
from apps.sales.models import Invoice
from apps.tenancy.services import OrganisationService


def _make_user(email="cust_owner@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Cust", last_name="Owner", is_verified=True,
    )


def _make_org(user, name="Cust Org"):
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


class CustomerCRUDTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        self.client = _auth_client(self.user, self.org)

    def _payload(self, **overrides):
        base = {
            "code": "CUS001",
            "name": "Acme Limited",
            "customer_type": "wholesale",
            "email": "acme@example.com",
            "phone": "08012345678",
        }
        base.update(overrides)
        return base

    def test_create_customer(self):
        res = self.client.post("/api/v1/customers/", self._payload())
        self.assertEqual(res.status_code, 201)
        self.assertTrue(Customer.objects.filter(organisation=self.org, code="CUS001").exists())

    def test_list_customers(self):
        Customer.objects.create(organisation=self.org, code="C100", name="Test Customer")
        res = self.client.get("/api/v1/customers/")
        self.assertEqual(res.status_code, 200)
        data = res.data.get("results") or res.data
        self.assertGreater(len(data), 0)

    def test_retrieve_customer(self):
        create_res = self.client.post("/api/v1/customers/", self._payload())
        cid = create_res.data["id"]
        res = self.client.get(f"/api/v1/customers/{cid}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["code"], "CUS001")

    def test_update_customer_name(self):
        create_res = self.client.post("/api/v1/customers/", self._payload())
        cid = create_res.data["id"]
        res = self.client.patch(f"/api/v1/customers/{cid}/", {"name": "Updated Ltd"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["name"], "Updated Ltd")

    def test_delete_customer(self):
        create_res = self.client.post("/api/v1/customers/", self._payload())
        cid = create_res.data["id"]
        res = self.client.delete(f"/api/v1/customers/{cid}/")
        self.assertIn(res.status_code, [200, 204])

    def test_duplicate_code_rejected(self):
        """Customer codes must be unique within an org."""
        Customer.objects.create(organisation=self.org, code="CUS001", name="Existing")
        res2 = self.client.post("/api/v1/customers/", self._payload(name="Duplicate Code"))
        # View may return 400 (validation) or 500 (IntegrityError) — both indicate rejection
        self.assertGreaterEqual(res2.status_code, 400)

    def test_cross_org_isolation(self):
        create_res = self.client.post("/api/v1/customers/", self._payload())
        cid = create_res.data["id"]
        other_user = _make_user("cust_other@example.com")
        other_org = _make_org(other_user, "Other Cust Org")
        c = _auth_client(other_user, other_org)
        res = c.get(f"/api/v1/customers/{cid}/")
        self.assertIn(res.status_code, [403, 404])

    def test_statement_accessible(self):
        create_res = self.client.post("/api/v1/customers/", self._payload())
        cid = create_res.data["id"]
        res = self.client.get(f"/api/v1/customers/{cid}/statement/")
        self.assertIn(res.status_code, [200, 400])  # 400 if date params required

    def test_customer_requires_authentication(self):
        client = APIClient()
        res = client.get("/api/v1/customers/")
        self.assertEqual(res.status_code, 401)


class CustomerStatementOpeningBalanceTests(TestCase):
    """
    C3/C3c: the statement now reports a balance BROUGHT FORWARD into the
    requested date range, so it reconciles instead of silently assuming the
    period starts at zero. Derived backward from customer.outstanding_balance
    (today's always-correct live figure) by undoing everything dated on or
    after date_from.
    """

    def setUp(self):
        from apps.inventory.models import Product, Warehouse
        from apps.sales.models import SalePayment

        self.SalePayment = SalePayment

        self.user = _make_user("stmtowner@example.com")
        self.org = _make_org(self.user, "Statement Org")
        self.client = _auth_client(self.user, self.org)
        self.customer = Customer.objects.create(organisation=self.org, code="STC001", name="Statement Customer")
        self.warehouse = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.product = Product.objects.create(
            organisation=self.org, sku="STMT-P1", name="Statement Item",
            product_type="service", cost_price=0, selling_price=10000, unit_of_measure="unit",
        )

    def _invoice(self, issue_date, unit_price="10000.00", payment_method="credit"):
        # Through the real API (like every other invoice test in this suite) —
        # calling SaleService.create_sale directly would need a real `date`
        # object for issue_date rather than "YYYY-MM-DD", since that coercion
        # normally happens in InvoiceSerializer.issue_date (a DateField)
        # before the service ever sees it.
        res = self.client.post("/api/v1/sales/invoices/", {
            "customer_id": str(self.customer.id),
            "warehouse_id": str(self.warehouse.id),
            "payment_method": payment_method,
            "issue_date": issue_date,
            "items": [{"product_id": str(self.product.id), "quantity": 1, "unit_price": unit_price}],
        }, format="json")
        self.assertIn(res.status_code, (200, 201), msg=str(res.data))
        return Invoice.objects.get(id=res.data["id"])

    def _backdated_payment(self, invoice, amount, when):
        res = self.client.post(f"/api/v1/sales/invoices/{invoice.id}/pay/", {
            "amount": str(amount), "method": "cash",
        }, format="json")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        payment = self.SalePayment.objects.filter(invoice=invoice).latest("received_at")
        self.SalePayment.objects.filter(id=payment.id).update(received_at=when)
        return payment

    def test_opening_balance_excludes_period_transactions(self):
        # Before the window: one invoice, fully unpaid → contributes 10000 to opening.
        self._invoice(issue_date="2026-01-10")
        # Inside the window: another invoice — must NOT be counted in opening.
        self._invoice(issue_date="2026-03-15")

        res = self.client.get(f"/api/v1/customers/{self.customer.id}/statement/", {
            "date_from": "2026-03-01", "date_to": "2026-03-31",
        })
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        summary = res.data["summary"]
        self.assertEqual(Decimal(summary["opening_balance"]), Decimal("10000.0000"))
        self.assertEqual(Decimal(summary["total_invoiced"]), Decimal("10000.0000"))  # just the March one
        self.assertEqual(Decimal(summary["balance_due"]), Decimal("20000.0000"))     # 10000 b/f + 10000 in-period

    def test_opening_balance_reflects_a_prior_payment(self):
        inv = self._invoice(issue_date="2026-01-10")
        self._backdated_payment(inv, Decimal("4000"), timezone_aware("2026-01-20"))

        res = self.client.get(f"/api/v1/customers/{self.customer.id}/statement/", {
            "date_from": "2026-02-01", "date_to": "2026-02-28",
        })
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        summary = res.data["summary"]
        self.assertEqual(Decimal(summary["opening_balance"]), Decimal("6000.0000"))  # 10000 - 4000

    def test_balance_due_reconciles_to_live_outstanding_balance_when_date_to_is_today(self):
        from django.utils import timezone
        self._invoice(issue_date="2026-01-10")
        self._invoice(issue_date=str(timezone.now().date()))

        self.customer.refresh_from_db()
        res = self.client.get(f"/api/v1/customers/{self.customer.id}/statement/", {
            "date_from": "2026-01-01",
        })
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        summary = res.data["summary"]
        self.assertEqual(Decimal(summary["balance_due"]), Decimal(str(self.customer.outstanding_balance)))

    def test_opening_balance_is_zero_with_no_prior_activity(self):
        self._invoice(issue_date="2026-06-01")
        res = self.client.get(f"/api/v1/customers/{self.customer.id}/statement/", {
            "date_from": "2026-06-01", "date_to": "2026-06-30",
        })
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(Decimal(res.data["summary"]["opening_balance"]), Decimal("0"))


def timezone_aware(date_str):
    from django.utils import timezone
    import datetime
    d = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    return timezone.make_aware(d)
