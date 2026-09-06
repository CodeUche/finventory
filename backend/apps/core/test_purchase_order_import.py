"""
CSV import of Purchase Orders — S1. One row per PO LINE; rows sharing the
same po_number group into a single multi-line PO, with header fields (order
date, supplier, warehouse) taken from that PO's first row only. Create-only:
an existing po_number is left untouched, since a PO already has its own
edit/receive/convert workflow that this importer must not disturb.
"""

from decimal import Decimal

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.tests import _upgrade_to_business
from apps.authentication.models import User
from apps.inventory.models import Product, Warehouse
from apps.purchases.models import PurchaseOrder
from apps.suppliers.models import Supplier
from apps.tax.models import TaxClass
from apps.tenancy.services import OrganisationService


def _make_user(email="po_import@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="PO", last_name="Importer", is_verified=True,
    )


def _make_org(user, name="PO Import Org"):
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


def _csv(text: str, name="pos.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


class PurchaseOrderImportTests(TestCase):
    URL = "/api/v1/import/purchase_orders/"

    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        self.supplier = Supplier.objects.create(organisation=self.org, name="Import Supplies Ltd")
        self.warehouse = Warehouse.objects.create(organisation=self.org, name="Main Warehouse", is_default=True)
        self.product1 = Product.objects.create(
            organisation=self.org, sku="IMP-1", name="Widget",
            product_type="physical", cost_price=100, selling_price=150,
        )
        self.product2 = Product.objects.create(
            organisation=self.org, sku="IMP-2", name="Gadget",
            product_type="physical", cost_price=200, selling_price=300,
        )

    def _post(self, url, text):
        return self.client.post(url, {"file": _csv(text)}, format="multipart")

    def test_multi_line_rows_group_into_one_po(self):
        csv_text = (
            "po_number,supplier_name,warehouse_name,order_date,product_sku,quantity,unit_cost\n"
            "PO-0001,Import Supplies Ltd,Main Warehouse,2026-01-10,IMP-1,10,100\n"
            "PO-0001,Import Supplies Ltd,Main Warehouse,2026-01-10,IMP-2,5,200\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["purchase_orders_created"], 1)
        self.assertEqual(res.data["lines_created"], 2)

        po = PurchaseOrder.objects.get(organisation=self.org, po_number="PO-0001")
        self.assertEqual(po.items.count(), 2)
        self.assertEqual(Decimal(str(po.subtotal)), Decimal("2000.00"))  # 10*100 + 5*200

    def test_different_po_numbers_create_separate_pos(self):
        csv_text = (
            "po_number,supplier_name,warehouse_name,order_date,product_sku,quantity,unit_cost\n"
            "PO-A,Import Supplies Ltd,Main Warehouse,2026-01-10,IMP-1,1,100\n"
            "PO-B,Import Supplies Ltd,Main Warehouse,2026-01-11,IMP-2,1,200\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["purchase_orders_created"], 2)
        self.assertTrue(PurchaseOrder.objects.filter(organisation=self.org, po_number="PO-A").exists())
        self.assertTrue(PurchaseOrder.objects.filter(organisation=self.org, po_number="PO-B").exists())

    def test_header_fields_come_from_the_first_row_of_the_group(self):
        """A typo'd date on line 2 of a 2-line PO must not change what line 1
        already committed the order_date to."""
        csv_text = (
            "po_number,supplier_name,warehouse_name,order_date,product_sku,quantity,unit_cost\n"
            "PO-0001,Import Supplies Ltd,Main Warehouse,2026-01-10,IMP-1,1,100\n"
            "PO-0001,Import Supplies Ltd,Main Warehouse,2099-12-31,IMP-2,1,100\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        po = PurchaseOrder.objects.get(organisation=self.org, po_number="PO-0001")
        self.assertEqual(str(po.order_date), "2026-01-10")

    def test_tax_comes_from_the_product_not_the_csv(self):
        vat = TaxClass.objects.create(organisation=self.org, name="VAT 7.5%", rate=Decimal("7.5"))
        self.product1.is_taxable = True
        self.product1.tax_class = vat
        self.product1.save(update_fields=["is_taxable", "tax_class"])

        csv_text = (
            "po_number,supplier_name,warehouse_name,order_date,product_sku,quantity,unit_cost\n"
            "PO-TAX,Import Supplies Ltd,Main Warehouse,2026-01-10,IMP-1,1,1000\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        po = PurchaseOrder.objects.get(organisation=self.org, po_number="PO-TAX")
        item = po.items.first()
        self.assertEqual(item.tax_rate, Decimal("7.50"))
        self.assertEqual(Decimal(str(item.tax_amount)), Decimal("75.00"))
        self.assertEqual(Decimal(str(po.total_amount)), Decimal("1075.00"))

    def test_delivery_amount_and_discount_are_applied(self):
        csv_text = (
            "po_number,supplier_name,warehouse_name,order_date,product_sku,quantity,unit_cost,discount_percent,delivery_amount\n"
            "PO-DISC,Import Supplies Ltd,Main Warehouse,2026-01-10,IMP-1,1,1000,10,500\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        po = PurchaseOrder.objects.get(organisation=self.org, po_number="PO-DISC")
        # 1000 - 10% = 900 subtotal, no tax, +500 delivery = 1400 total
        self.assertEqual(Decimal(str(po.subtotal)), Decimal("900.00"))
        self.assertEqual(Decimal(str(po.total_amount)), Decimal("1400.00"))

    def test_existing_po_number_is_left_untouched(self):
        existing = PurchaseOrder.objects.create(
            organisation=self.org, po_number="PO-EXIST", supplier=self.supplier,
            warehouse=self.warehouse, status="sent", order_date="2025-01-01",
            subtotal=Decimal("1"), tax_amount=Decimal("0"), total_amount=Decimal("1"),
            created_by=self.user,
        )
        csv_text = (
            "po_number,supplier_name,warehouse_name,order_date,product_sku,quantity,unit_cost\n"
            "PO-EXIST,Import Supplies Ltd,Main Warehouse,2026-01-10,IMP-1,99,999\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["purchase_orders_created"], 0)
        self.assertTrue(any(e["field"] == "po_number" for e in res.data["errors"]))
        existing.refresh_from_db()
        self.assertEqual(existing.items.count(), 0)  # untouched, not appended to

    def test_unknown_supplier_reports_a_clear_error_and_creates_nothing(self):
        csv_text = (
            "po_number,supplier_name,warehouse_name,order_date,product_sku,quantity,unit_cost\n"
            "PO-BADSUP,Nonexistent Supplier,Main Warehouse,2026-01-10,IMP-1,1,100\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["purchase_orders_created"], 0)
        self.assertTrue(any(e["field"] == "supplier_name" for e in res.data["errors"]))
        self.assertFalse(PurchaseOrder.objects.filter(organisation=self.org, po_number="PO-BADSUP").exists())

    def test_unknown_product_sku_reports_a_clear_error(self):
        csv_text = (
            "po_number,supplier_name,warehouse_name,order_date,product_sku,quantity,unit_cost\n"
            "PO-BADSKU,Import Supplies Ltd,Main Warehouse,2026-01-10,NOPE,1,100\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["purchase_orders_created"], 0)
        self.assertTrue(any(e["field"] == "product_sku" for e in res.data["errors"]))

    def test_zero_or_negative_quantity_is_rejected(self):
        csv_text = (
            "po_number,supplier_name,warehouse_name,order_date,product_sku,quantity,unit_cost\n"
            "PO-ZEROQ,Import Supplies Ltd,Main Warehouse,2026-01-10,IMP-1,0,100\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["purchase_orders_created"], 0)
        self.assertTrue(any(e["field"] == "quantity" for e in res.data["errors"]))

    def test_template_download_offers_the_new_columns(self):
        res = self.client.get("/api/v1/import/template/purchase_orders/")
        self.assertEqual(res.status_code, 200)
        header = res.content.decode("utf-8").splitlines()[0]
        for col in ("po_number", "supplier_name", "warehouse_name", "order_date", "product_sku", "quantity", "unit_cost"):
            self.assertIn(col, header)

    def test_another_organisation_does_not_see_the_imported_po(self):
        csv_text = (
            "po_number,supplier_name,warehouse_name,order_date,product_sku,quantity,unit_cost\n"
            "PO-ISO,Import Supplies Ltd,Main Warehouse,2026-01-10,IMP-1,1,100\n"
        )
        self._post(self.URL, csv_text)

        other_user = _make_user("other_po_import@example.com")
        other_org = _make_org(other_user, "Other PO Import Org")
        self.assertFalse(PurchaseOrder.objects.filter(organisation=other_org, po_number="PO-ISO").exists())
