"""
Purchase Returns list/filter tests — the reviewer's ask for a page to browse
and reprint debit notes. The backend (PurchaseReturnViewSet, full
ModelViewSet with create()) already existed and was already complete; this
phase only adds date_from/date_to filtering and widens search to include the
supplier name and PO number, to match the new frontend list page. Covers
exactly that, plus a regression check that supplier_name/po_number — already
shipped — still come through.
"""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.tests import _upgrade_to_business
from apps.authentication.models import User
from apps.inventory.models import Product, Warehouse
from apps.purchases.models import PurchaseOrder, PurchaseReturn, PurchaseReturnItem
from apps.suppliers.models import Supplier
from apps.tenancy.services import OrganisationService


def _make_user(email="po_returns_owner@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="POReturns", last_name="Owner", is_verified=True,
    )


def _make_org(user, name="PO Returns Test Org"):
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


class PurchaseReturnListingTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        self.warehouse = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.supplier = Supplier.objects.create(organisation=self.org, code="SUP001", name="Test Supplier Ltd")
        self.product = Product.objects.create(
            organisation=self.org, sku="PORET-P1", name="Returnable Stock Item",
            product_type="stock", cost_price=1000, selling_price=2000, unit_of_measure="unit",
        )

    def _make_po(self, po_number):
        return PurchaseOrder.objects.create(
            organisation=self.org, po_number=po_number, supplier=self.supplier,
            warehouse=self.warehouse, order_date="2026-01-01",
            subtotal=Decimal("10000"), tax_amount=Decimal("1500"),
            created_by=self.user,
        )

    def _make_return(self, po, return_date, total=Decimal("5000")):
        ret = PurchaseReturn.objects.create(
            organisation=self.org, purchase_order=po, supplier=self.supplier,
            warehouse=self.warehouse, return_number=f"PRTN-{po.po_number}-{return_date}",
            return_date=return_date, subtotal=total, tax_amount=Decimal("0"),
            total_amount=total, created_by=self.user,
        )
        PurchaseReturnItem.objects.create(
            organisation=self.org, purchase_return=ret, product=self.product,
            quantity_returned=1, unit_cost=total, line_total=total,
        )
        return ret

    def test_return_lists_with_supplier_name_and_po_number(self):
        po = self._make_po("PO-0001")
        self._make_return(po, "2026-03-10")

        res = self.client.get("/api/v1/purchases/returns/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["supplier_name"], "Test Supplier Ltd")
        self.assertEqual(rows[0]["po_number"], "PO-0001")

    def test_date_range_filters_returns(self):
        po1 = self._make_po("PO-0002")
        self._make_return(po1, "2026-01-05")
        po2 = self._make_po("PO-0003")
        self._make_return(po2, "2026-06-15")

        res = self.client.get("/api/v1/purchases/returns/", {"date_from": "2026-05-01", "date_to": "2026-07-01"})
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["return_date"], "2026-06-15")

    def test_search_by_supplier_name(self):
        po = self._make_po("PO-0004")
        self._make_return(po, "2026-03-10")

        res = self.client.get("/api/v1/purchases/returns/", {"search": "Test Supplier"})
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(len(rows), 1)

    def test_search_by_po_number(self):
        po = self._make_po("PO-UNIQUE-0005")
        self._make_return(po, "2026-03-10")

        res = self.client.get("/api/v1/purchases/returns/", {"search": "PO-UNIQUE-0005"})
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(len(rows), 1)

    def test_another_organisation_cannot_see_these_returns(self):
        po = self._make_po("PO-0006")
        self._make_return(po, "2026-03-10")

        other_user = _make_user("other_po_org_owner@example.com")
        other_org = _make_org(other_user, "Other PO Org")
        _upgrade_to_business(other_org)
        other_client = _auth_client(other_user, other_org)

        res = other_client.get("/api/v1/purchases/returns/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(len(rows), 0)
