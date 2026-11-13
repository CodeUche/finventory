"""
The cashier at the register can SEE what they sell, and nothing more.

A team member with the Sales module at "write" (the register's access) must be
able to load the product list and the warehouse list without the owner also
ticking Inventory. That access is read-only: no creating, changing or deleting,
no stock screens, no cost prices, and never another company's rows.
"""

from decimal import Decimal

from django.test import TestCase

from apps.core.test_module_access import _member
from apps.inventory.models import Product, Warehouse
from apps.payroll.test_track_a import _auth_client, _make_org, _make_user


class RegisterReadAccessTests(TestCase):
    def setUp(self):
        self.owner = _make_user("rr_owner@example.com")
        self.org = _make_org(self.owner, "Register Org")
        self.owner_client = _auth_client(self.owner, self.org)
        self.wh = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.product = Product.objects.create(
            organisation=self.org, sku="RR-1", name="Zobo",
            cost_price=Decimal("300"), selling_price=Decimal("700"),
        )
        # A second company with its own product and warehouse.
        other_owner = _make_user("rr_other@example.com")
        self.other_org = _make_org(other_owner, "Other Org")
        Warehouse.objects.create(organisation=self.other_org, name="Their Store")
        self.other_product = Product.objects.create(
            organisation=self.other_org, sku="OT-1", name="Their Item",
            cost_price=Decimal("1"), selling_price=Decimal("2"),
        )

    def _cashier(self, level="write", module="sales", email="rr_cashier@example.com"):
        return _member(self.org, email, "staff", module, level)[1]

    def test_cashier_with_sales_write_can_list_products(self):
        res = self._cashier().get("/api/v1/inventory/products/?slim=1&is_active=true")
        self.assertEqual(res.status_code, 200)
        rows = res.json().get("results", res.json())
        self.assertEqual([r["sku"] for r in rows], ["RR-1"])

    def test_cashier_can_open_one_product(self):
        res = self._cashier().get(f"/api/v1/inventory/products/{self.product.id}/")
        self.assertEqual(res.status_code, 200)

    def test_cashier_can_list_warehouses(self):
        res = self._cashier().get("/api/v1/inventory/warehouses/")
        self.assertEqual(res.status_code, 200)
        rows = res.json().get("results", res.json())
        self.assertEqual([r["name"] for r in rows], ["Main"])

    def test_cashier_never_sees_cost_price(self):
        client = self._cashier()
        for url in ("/api/v1/inventory/products/", "/api/v1/inventory/products/?slim=1",
                    f"/api/v1/inventory/products/{self.product.id}/"):
            body = client.get(url).json()
            rows = body.get("results", body) if isinstance(body, dict) and "results" in body else [body] if isinstance(body, dict) else body
            for r in rows:
                self.assertNotIn("cost_price", r)
                self.assertNotIn("owner_cost_price", r)

    def test_cashier_cannot_create_change_or_delete_products(self):
        client = self._cashier(level="edit")  # even full sales access
        res = client.post("/api/v1/inventory/products/", {
            "sku": "X", "name": "X", "selling_price": "1", "cost_price": "1"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(client.patch(f"/api/v1/inventory/products/{self.product.id}/",
                                      {"name": "Hacked"}, format="json").status_code, 403)
        self.assertEqual(client.delete(f"/api/v1/inventory/products/{self.product.id}/").status_code, 403)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Zobo")

    def test_cashier_cannot_create_change_or_delete_warehouses(self):
        client = self._cashier(level="edit")
        self.assertEqual(client.post("/api/v1/inventory/warehouses/", {"name": "New"}, format="json").status_code, 403)
        self.assertEqual(client.patch(f"/api/v1/inventory/warehouses/{self.wh.id}/",
                                      {"name": "Hacked"}, format="json").status_code, 403)
        self.assertEqual(client.delete(f"/api/v1/inventory/warehouses/{self.wh.id}/").status_code, 403)

    # NOTE: /inventory/stock/ is not listed: StockItemViewSet.get_permissions already
    # lets any staff member read it (it skips the inventory tick). Pre-existing.
    def test_cashier_cannot_reach_other_inventory_screens(self):
        client = self._cashier()
        for url in ("/api/v1/inventory/products/low-stock/",
                    "/api/v1/inventory/movements/", "/api/v1/inventory/categories/",
                    "/api/v1/inventory/batches/"):
            self.assertEqual(client.get(url).status_code, 403, url)

    def test_cashier_cannot_adjust_stock(self):
        res = self._cashier(level="edit").post("/api/v1/inventory/movements/adjust/", {
            "product": str(self.product.id), "warehouse": str(self.wh.id),
            "quantity": "5", "reason": "x"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_cashier_cannot_read_another_companys_rows(self):
        client = self._cashier()
        res = client.get(f"/api/v1/inventory/products/{self.other_product.id}/")
        self.assertEqual(res.status_code, 404)
        skus = [r["sku"] for r in client.get("/api/v1/inventory/products/").json().get("results", [])]
        self.assertNotIn("OT-1", skus)
        names = [r["name"] for r in client.get("/api/v1/inventory/warehouses/").json().get("results", [])]
        self.assertNotIn("Their Store", names)

    def test_sales_view_only_or_no_tick_still_blocked(self):
        # Viewing sales is not ringing sales: the register door stays shut.
        self.assertEqual(self._cashier(level="view", email="rr_v@example.com")
                         .get("/api/v1/inventory/products/").status_code, 403)
        self.assertEqual(self._cashier(level="write", module="purchases", email="rr_p@example.com")
                         .get("/api/v1/inventory/warehouses/").status_code, 403)

    def test_unauthenticated_is_refused(self):
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get("/api/v1/inventory/products/").status_code, (401, 403))

    def test_owner_and_inventory_ticked_staff_unchanged(self):
        self.assertEqual(self.owner_client.get("/api/v1/inventory/warehouses/").status_code, 200)
        inv = _member(self.org, "rr_inv@example.com", "staff", "inventory", "view")[1]
        self.assertEqual(inv.get("/api/v1/inventory/products/").status_code, 200)
        # Staff role + inventory tick still cannot list warehouses (manager rule).
        self.assertEqual(inv.get("/api/v1/inventory/warehouses/").status_code, 403)
