"""Tests for inventory: products, stock movements, warehouses, low stock."""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.inventory.models import Product, Warehouse
from apps.tenancy.services import OrganisationService


def _make_user(email="inv_owner@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Inv", last_name="Owner", is_verified=True,
    )


def _make_org(user, name="Inv Org"):
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


def _make_warehouse(org, name="Main Warehouse"):
    return Warehouse.objects.create(organisation=org, name=name, is_default=True)


class ProductCRUDTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        self.client = _auth_client(self.user, self.org)

    def _payload(self, **overrides):
        base = {
            "sku": "SKU001",
            "name": "Palm Oil 5L",
            "product_type": "physical",
            "cost_price": "1500.00",
            "selling_price": "2000.00",
            "unit_of_measure": "bottle",
            "reorder_level": 5,
        }
        base.update(overrides)
        return base

    def test_create_product_success(self):
        res = self.client.post("/api/v1/inventory/products/", self._payload())
        self.assertEqual(res.status_code, 201)
        self.assertTrue(Product.objects.filter(organisation=self.org, sku="SKU001").exists())

    def test_list_products(self):
        self.client.post("/api/v1/inventory/products/", self._payload())
        res = self.client.get("/api/v1/inventory/products/")
        self.assertEqual(res.status_code, 200)
        data = res.data.get("results") or res.data
        self.assertGreater(len(data), 0)

    def test_retrieve_product(self):
        create_res = self.client.post("/api/v1/inventory/products/", self._payload())
        pid = create_res.data["id"]
        res = self.client.get(f"/api/v1/inventory/products/{pid}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["sku"], "SKU001")

    def test_update_product_price(self):
        create_res = self.client.post("/api/v1/inventory/products/", self._payload())
        pid = create_res.data["id"]
        res = self.client.patch(
            f"/api/v1/inventory/products/{pid}/",
            {"selling_price": "2500.00"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(str(res.data["selling_price"]).startswith("2500"))

    def test_create_service_product(self):
        payload = self._payload(sku="SVC001", name="Consulting Fee", product_type="service")
        res = self.client.post("/api/v1/inventory/products/", payload)
        self.assertEqual(res.status_code, 201)
        product = Product.objects.get(organisation=self.org, sku="SVC001")
        self.assertEqual(product.product_type, "service")

    def test_delete_product(self):
        create_res = self.client.post("/api/v1/inventory/products/", self._payload())
        pid = create_res.data["id"]
        res = self.client.delete(f"/api/v1/inventory/products/{pid}/")
        self.assertIn(res.status_code, [200, 204])

    def test_other_org_cannot_see_product(self):
        create_res = self.client.post("/api/v1/inventory/products/", self._payload())
        pid = create_res.data["id"]
        other_user = _make_user("inv_other@example.com")
        other_org = _make_org(other_user, "Other Inv Org")
        c = _auth_client(other_user, other_org)
        res = c.get(f"/api/v1/inventory/products/{pid}/")
        self.assertIn(res.status_code, [403, 404])


class StockMovementTests(TestCase):
    def setUp(self):
        self.user = _make_user("stock_owner@example.com")
        self.org = _make_org(self.user, "Stock Org")
        self.client = _auth_client(self.user, self.org)
        self.warehouse = _make_warehouse(self.org)
        # Create a physical product
        create_res = self.client.post("/api/v1/inventory/products/", {
            "sku": "STOCK001",
            "name": "Stocked Item",
            "product_type": "physical",
            "cost_price": "200.00",
            "selling_price": "350.00",
            "unit_of_measure": "unit",
            "reorder_level": 10,
        })
        self.product_id = create_res.data["id"]

    def test_adjust_stock_in(self):
        res = self.client.post("/api/v1/inventory/movements/adjust/", {
            "product_id": self.product_id,
            "warehouse_id": str(self.warehouse.id),
            "quantity": 50,
            "reason": "Initial stock",
        }, format="json")
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))

    def test_adjust_stock_increases_quantity(self):
        self.client.post("/api/v1/inventory/movements/adjust/", {
            "product_id": self.product_id,
            "warehouse_id": str(self.warehouse.id),
            "quantity": 30,
            "reason": "Goods received",
        }, format="json")
        from apps.inventory.models import StockItem
        stock = StockItem.objects.filter(
            product_id=self.product_id, warehouse=self.warehouse
        ).first()
        self.assertIsNotNone(stock)
        self.assertEqual(stock.quantity_on_hand, 30)

    def test_list_stock_movements(self):
        self.client.post("/api/v1/inventory/stock/adjust/", {
            "product": self.product_id,
            "warehouse": str(self.warehouse.id),
            "quantity": 20,
            "movement_type": "in",
            "reference": "Test",
        }, format="json")
        res = self.client.get("/api/v1/inventory/movements/")
        self.assertEqual(res.status_code, 200)


class LowStockTests(TestCase):
    def setUp(self):
        self.user = _make_user("lowstock@example.com")
        self.org = _make_org(self.user, "Low Stock Org")
        self.client = _auth_client(self.user, self.org)
        self.warehouse = _make_warehouse(self.org)

    def test_low_stock_endpoint_accessible(self):
        res = self.client.get("/api/v1/inventory/products/low-stock/")
        self.assertEqual(res.status_code, 200)

    def test_product_with_no_stock_appears_in_low_stock(self):
        # Create product directly via ORM to ensure reorder_level is set
        product = Product.objects.create(
            organisation=self.org,
            sku="NOSTOCK001",
            name="Never Stocked",
            product_type="physical",
            cost_price=100,
            selling_price=150,
            unit_of_measure="unit",
            reorder_level=5,
        )
        res = self.client.get("/api/v1/inventory/products/low-stock/")
        self.assertEqual(res.status_code, 200)
        data = res.data if isinstance(res.data, list) else (res.data.get("results") or res.data)
        # low_stock response has "product" field = product UUID for no-movement items
        product_ids = [str(p.get("product") or p.get("id")) for p in data]
        self.assertIn(str(product.id), product_ids)


class WarehouseTests(TestCase):
    def setUp(self):
        self.user = _make_user("wh_owner@example.com")
        self.org = _make_org(self.user, "WH Org")
        self.client = _auth_client(self.user, self.org)

    def test_create_warehouse(self):
        res = self.client.post("/api/v1/inventory/warehouses/", {
            "name": "Lagos Warehouse",
            "address": "12 Lagos St",
        })
        self.assertEqual(res.status_code, 201)
        self.assertTrue(Warehouse.objects.filter(organisation=self.org, name="Lagos Warehouse").exists())

    def test_list_warehouses(self):
        _make_warehouse(self.org)
        res = self.client.get("/api/v1/inventory/warehouses/")
        self.assertEqual(res.status_code, 200)
