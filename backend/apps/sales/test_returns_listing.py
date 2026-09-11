"""
Sales Returns list/filter/serializer tests — the reviewer's ask for a page to
browse and reprint credit notes, which previously had no UI even though the
list endpoint (salesApi.listReturns) already existed unused.

Covers what this phase actually changed: date_from/date_to filtering on
SaleReturnViewSet, and the new customer_name / processed_by_name fields on
SaleReturnSerializer (including the walk-in / no-customer case, which must
default to None rather than 500 on invoice.customer being null).
"""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.customers.models import Customer
from apps.inventory.models import Product, Warehouse
from apps.sales.models import Invoice, SaleReturn, SaleReturnItem
from apps.tenancy.services import OrganisationService


def _make_user(email="returns_owner@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Returns", last_name="Owner", is_verified=True,
    )


def _make_org(user, name="Returns Test Org"):
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


class SaleReturnListingTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        self.client = _auth_client(self.user, self.org)
        self.warehouse = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.customer = Customer.objects.create(organisation=self.org, code="C001", name="Regular Customer")
        self.product = Product.objects.create(
            organisation=self.org, sku="RET-P1", name="Returnable Item",
            product_type="service", cost_price=0, selling_price=5000, unit_of_measure="unit",
        )

    def _create_invoice(self, customer=None):
        res = self.client.post("/api/v1/sales/invoices/", {
            "customer_id": str(customer.id) if customer else None,
            "warehouse_id": str(self.warehouse.id),
            "payment_method": "cash",
            "items": [{"product_id": str(self.product.id), "quantity": 1, "unit_price": "5000.00"}],
        }, format="json")
        self.assertIn(res.status_code, (200, 201), msg=str(res.data))
        return Invoice.objects.get(id=res.data["id"])

    def _make_return(self, invoice, return_date, amount=Decimal("5000")):
        item = invoice.items.first()
        ret = SaleReturn.objects.create(
            organisation=self.org, return_number=f"RTN-TEST-{invoice.id.hex[:8]}-{return_date}",
            invoice=invoice, reason=SaleReturn.Reason.DEFECTIVE,
            return_date=return_date, total_refund=amount,
            processed_by=self.user,
        )
        SaleReturnItem.objects.create(
            organisation=self.org, sale_return=ret, original_item=item,
            product=self.product, quantity_returned=1,
            unit_price=amount, refund_amount=amount,
        )
        return ret

    def test_return_lists_with_customer_name(self):
        invoice = self._create_invoice(customer=self.customer)
        self._make_return(invoice, "2026-03-10")

        res = self.client.get("/api/v1/sales/returns/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["customer_name"], "Regular Customer")
        self.assertIsNotNone(rows[0]["processed_by_name"])

    def test_walk_in_invoice_return_has_null_customer_name_not_500(self):
        """A cash/walk-in sale has invoice.customer = None — must not crash the list."""
        invoice = self._create_invoice(customer=None)
        self._make_return(invoice, "2026-03-11")

        res = self.client.get("/api/v1/sales/returns/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(rows[0]["customer_name"], None)

    def test_date_from_filters_out_earlier_returns(self):
        invoice = self._create_invoice(customer=self.customer)
        self._make_return(invoice, "2026-01-05")
        invoice2 = self._create_invoice(customer=self.customer)
        self._make_return(invoice2, "2026-06-15")

        res = self.client.get("/api/v1/sales/returns/", {"date_from": "2026-06-01"})
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["return_date"], "2026-06-15")

    def test_date_to_filters_out_later_returns(self):
        invoice = self._create_invoice(customer=self.customer)
        self._make_return(invoice, "2026-01-05")
        invoice2 = self._create_invoice(customer=self.customer)
        self._make_return(invoice2, "2026-06-15")

        res = self.client.get("/api/v1/sales/returns/", {"date_to": "2026-02-01"})
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["return_date"], "2026-01-05")

    def test_date_range_narrows_to_returns_inside_it(self):
        invoice = self._create_invoice(customer=self.customer)
        self._make_return(invoice, "2026-01-05")
        invoice2 = self._create_invoice(customer=self.customer)
        self._make_return(invoice2, "2026-03-15")
        invoice3 = self._create_invoice(customer=self.customer)
        self._make_return(invoice3, "2026-09-01")

        res = self.client.get("/api/v1/sales/returns/", {"date_from": "2026-02-01", "date_to": "2026-06-01"})
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["return_date"], "2026-03-15")

    def test_search_by_invoice_number_finds_the_return(self):
        invoice = self._create_invoice(customer=self.customer)
        self._make_return(invoice, "2026-03-10")

        res = self.client.get("/api/v1/sales/returns/", {"search": invoice.invoice_number})
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(len(rows), 1)

    def test_search_by_customer_name_finds_the_return(self):
        invoice = self._create_invoice(customer=self.customer)
        self._make_return(invoice, "2026-03-10")

        res = self.client.get("/api/v1/sales/returns/", {"search": "Regular Customer"})
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(len(rows), 1)

    def test_another_organisation_cannot_see_these_returns(self):
        invoice = self._create_invoice(customer=self.customer)
        self._make_return(invoice, "2026-03-10")

        other_user = _make_user("other_org_owner@example.com")
        other_org = _make_org(other_user, "Other Org")
        other_client = _auth_client(other_user, other_org)

        res = other_client.get("/api/v1/sales/returns/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(len(rows), 0)
