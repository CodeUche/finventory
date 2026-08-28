"""
CSV product-import tests — covers the reviewer's "import with or without
balances" request and the opening-stock take-on it triggers.

The `opening_stock` + `warehouse` columns are optional (see PRODUCT_ALIASES in
import_views.py), so a single import flow already supports both cases; these
tests pin that down and guard the GL-correctness fix: opening stock from a CSV
import must post through AccountingService.set_item_opening_balance (Debit
Inventory / Credit Take-On Suspense) and must be idempotent on re-import,
rather than the old InventoryService.adjust_stock call, which added the
imported quantity again on every re-run of the same file.
"""

import io

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.authentication.models import User
from apps.tenancy.services import OrganisationService
from apps.accounting.models import Account
from apps.inventory.models import Product, StockItem, Warehouse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken


def _make_user(email="import_owner@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Import", last_name="Owner", is_verified=True,
    )


def _make_org(user, name="Import Test Org"):
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


def _csv_file(text: str, name="products.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


class ProductImportWithBalancesTests(TestCase):

    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        self.client = _auth_client(self.user, self.org)

    def test_import_without_opening_stock_column_creates_product_only(self):
        csv_text = "sku,name,selling_price,cost_price\nSKU1,Widget,1000,600\n"
        res = self.client.post(
            "/api/v1/import/products/",
            {"file": _csv_file(csv_text)},
            format="multipart",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["created"], 1)
        product = Product.objects.get(organisation=self.org, sku="SKU1")
        self.assertFalse(StockItem.objects.filter(organisation=self.org, product=product).exists())

    def test_import_with_opening_stock_posts_gl_correct_take_on(self):
        csv_text = (
            "sku,name,selling_price,cost_price,warehouse,opening_stock\n"
            "SKU2,Gadget,2000,1200,Main Store,15\n"
        )
        res = self.client.post(
            "/api/v1/import/products/",
            {"file": _csv_file(csv_text)},
            format="multipart",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["stock_assigned"], 1)

        product = Product.objects.get(organisation=self.org, sku="SKU2")
        wh = Warehouse.objects.get(organisation=self.org, name="Main Store")
        stock = StockItem.objects.get(organisation=self.org, product=product, warehouse=wh)
        self.assertAlmostEqual(float(stock.quantity_on_hand), 15.0, places=2)

        inv = Account.objects.get(organisation=self.org, code="1200")
        self.assertAlmostEqual(float(inv.balance), 15 * 1200.0, places=2)

    def test_reimporting_same_file_does_not_double_stock_or_gl(self):
        """Regression: adjust_stock used to add the qty again on every re-run."""
        csv_text = (
            "sku,name,selling_price,cost_price,warehouse,opening_stock\n"
            "SKU3,Crate,3000,1800,Main Store,20\n"
        )
        for _ in range(2):
            res = self.client.post(
                "/api/v1/import/products/",
                {"file": _csv_file(csv_text)},
                format="multipart",
            )
            self.assertEqual(res.status_code, 200, msg=str(res.data))

        product = Product.objects.get(organisation=self.org, sku="SKU3")
        wh = Warehouse.objects.get(organisation=self.org, name="Main Store")
        stock = StockItem.objects.get(organisation=self.org, product=product, warehouse=wh)
        self.assertAlmostEqual(float(stock.quantity_on_hand), 20.0, places=2)

        inv = Account.objects.get(organisation=self.org, code="1200")
        self.assertAlmostEqual(float(inv.balance), 20 * 1800.0, places=2)

    def test_reimporting_with_increased_quantity_posts_only_the_delta(self):
        wh = Warehouse.objects.create(organisation=self.org, name="Depot", is_default=True)
        csv_text_1 = (
            "sku,name,selling_price,cost_price,warehouse,opening_stock\n"
            "SKU4,Box,500,300,Depot,5\n"
        )
        csv_text_2 = (
            "sku,name,selling_price,cost_price,warehouse,opening_stock\n"
            "SKU4,Box,500,300,Depot,12\n"
        )
        self.client.post("/api/v1/import/products/", {"file": _csv_file(csv_text_1)}, format="multipart")
        self.client.post("/api/v1/import/products/", {"file": _csv_file(csv_text_2)}, format="multipart")

        product = Product.objects.get(organisation=self.org, sku="SKU4")
        stock = StockItem.objects.get(organisation=self.org, product=product, warehouse=wh)
        self.assertAlmostEqual(float(stock.quantity_on_hand), 12.0, places=2)

        inv = Account.objects.get(organisation=self.org, code="1200")
        self.assertAlmostEqual(float(inv.balance), 12 * 300.0, places=2)
