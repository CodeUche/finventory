"""
The inventory tick on stock endpoints.

StockItemViewSet listed the inventory tick in permission_classes but its
get_permissions() override returned only the role classes, so the tick was never
checked: any staff member with NO inventory access could list stock (quantities,
SKUs, every active product) and a manager without the tick could DELETE a stock
row (which zeroes the stock). The same drop affected the adjust / transfer /
bulk-delete actions, which replaced the class permissions with role-only lists.
"""

import uuid

from django.test import TestCase

from apps.core.test_module_access import _member
from apps.inventory.models import Product, StockItem, Warehouse
from apps.payroll.test_track_a import _auth_client, _make_org, _make_user


def _product(org, sku="PRM-1"):
    return Product.objects.create(
        organisation=org, sku=sku, name="Perm Item", product_type="physical",
        cost_price="100.00", selling_price="150.00", unit_of_measure="unit",
    )


class StockTickTests(TestCase):
    def setUp(self):
        self.owner = _make_user("stk_owner@example.com")
        self.org = _make_org(self.owner, "Stock Perm Org")
        self.warehouse = Warehouse.objects.create(
            organisation=self.org, name="Main", is_default=True)
        self.product = _product(self.org)

    def _stock_row(self):
        return StockItem.objects.create(
            organisation=self.org, product=self.product, warehouse=self.warehouse,
            quantity_on_hand=5,
        )

    # --- list ------------------------------------------------------------

    def test_staff_without_inventory_tick_cannot_list_stock(self):
        _, client, _ = _member(self.org, "stk_none@example.com", "staff")
        self.assertEqual(client.get("/api/v1/inventory/stock/").status_code, 403)

    def test_staff_ticked_none_cannot_list_stock(self):
        _, client, _ = _member(
            self.org, "stk_zero@example.com", "staff", "inventory", "none"
        )
        self.assertEqual(client.get("/api/v1/inventory/stock/").status_code, 403)

    def test_staff_with_other_module_tick_cannot_list_stock(self):
        _, client, _ = _member(
            self.org, "stk_oth@example.com", "staff", "sales", "edit"
        )
        self.assertEqual(client.get("/api/v1/inventory/stock/").status_code, 403)

    def test_staff_with_inventory_view_tick_can_list_stock(self):
        _, client, _ = _member(
            self.org, "stk_view@example.com", "staff", "inventory", "view"
        )
        res = client.get("/api/v1/inventory/stock/")
        self.assertEqual(res.status_code, 200)

    def test_owner_and_admin_can_list_stock(self):
        _, admin_client, _ = _member(self.org, "stk_admin@example.com", "admin")
        for client in (_auth_client(self.owner, self.org), admin_client):
            self.assertEqual(client.get("/api/v1/inventory/stock/").status_code, 200)

    def test_viewer_role_still_cannot_list_stock(self):
        _, client, _ = _member(
            self.org, "stk_viewer@example.com", "viewer", "inventory", "edit"
        )
        self.assertEqual(client.get("/api/v1/inventory/stock/").status_code, 403)

    def test_other_tenant_member_cannot_list_stock(self):
        other_owner = _make_user("stk_other@example.com")
        other_org = _make_org(other_owner, "Other Stock Org")
        _, client, _ = _member(
            other_org, "stk_o_member@example.com", "staff", "inventory", "edit"
        )
        client.credentials(
            HTTP_AUTHORIZATION=client._credentials["HTTP_AUTHORIZATION"],
            HTTP_X_ORGANISATION_ID=str(self.org.id),
        )
        self.assertEqual(client.get("/api/v1/inventory/stock/").status_code, 403)

    # --- delete ----------------------------------------------------------

    def test_manager_without_tick_cannot_delete_stock_row(self):
        row = self._stock_row()
        _, client, _ = _member(self.org, "stk_mgr@example.com", "manager")
        self.assertEqual(
            client.delete(f"/api/v1/inventory/stock/{row.id}/").status_code, 403
        )
        self.assertTrue(StockItem.objects.filter(pk=row.pk).exists())

    def test_manager_with_view_tick_cannot_delete_stock_row(self):
        row = self._stock_row()
        _, client, _ = _member(
            self.org, "stk_mgrv@example.com", "manager", "inventory", "view"
        )
        self.assertEqual(
            client.delete(f"/api/v1/inventory/stock/{row.id}/").status_code, 403
        )

    def test_manager_with_edit_tick_can_delete_stock_row(self):
        row = self._stock_row()
        _, client, _ = _member(
            self.org, "stk_mgre@example.com", "manager", "inventory", "edit"
        )
        res = client.delete(f"/api/v1/inventory/stock/{row.id}/")
        self.assertIn(res.status_code, (200, 204), res.content[:200])
        self.assertFalse(StockItem.objects.filter(pk=row.pk).exists())

    def test_staff_with_edit_tick_still_cannot_delete(self):
        """Role gate unchanged: destroy is manager-only."""
        row = self._stock_row()
        _, client, _ = _member(
            self.org, "stk_se@example.com", "staff", "inventory", "edit"
        )
        self.assertEqual(
            client.delete(f"/api/v1/inventory/stock/{row.id}/").status_code, 403
        )

    # --- adjust / transfer / bulk-delete ----------------------------------

    def _adjust(self, client):
        return client.post("/api/v1/inventory/movements/adjust/", {
            "product_id": str(self.product.id), "warehouse_id": str(self.warehouse.id),
            "quantity": 5, "reason": "Perm test",
        }, format="json")

    def test_adjust_needs_the_tick(self):
        _, no_tick, _ = _member(self.org, "adj_none@example.com", "manager")
        _, view_tick, _ = _member(
            self.org, "adj_view@example.com", "manager", "inventory", "view"
        )
        _, write_tick, _ = _member(
            self.org, "adj_write@example.com", "manager", "inventory", "write"
        )
        self.assertEqual(self._adjust(no_tick).status_code, 403)
        self.assertEqual(self._adjust(view_tick).status_code, 403)
        res = self._adjust(write_tick)
        self.assertEqual(res.status_code, 201, res.content[:200])

    def test_transfer_needs_the_tick(self):
        wh2 = Warehouse.objects.create(organisation=self.org, name="Second")
        body = {
            "product_id": str(self.product.id),
            "from_warehouse_id": str(self.warehouse.id),
            "to_warehouse_id": str(wh2.id),
            "quantity": 1,
        }
        _, no_tick, _ = _member(self.org, "tr_none@example.com", "manager")
        _, write_tick, _ = _member(
            self.org, "tr_write@example.com", "manager", "inventory", "write"
        )
        self.assertEqual(
            no_tick.post(
                "/api/v1/inventory/movements/transfer/", body, format="json"
            ).status_code,
            403,
        )
        # With the tick it reaches the service (which may refuse for lack of
        # stock, 422) - not 403.
        res = write_tick.post(
            "/api/v1/inventory/movements/transfer/", body, format="json"
        )
        self.assertNotEqual(res.status_code, 403, res.content[:200])

    def test_bulk_delete_needs_the_tick_and_is_tenant_scoped(self):
        url = "/api/v1/inventory/products/bulk-delete/"
        _, no_tick, _ = _member(self.org, "bd_none@example.com", "manager")
        _, write_tick, _ = _member(
            self.org, "bd_write@example.com", "manager", "inventory", "write"
        )
        _, edit_tick, _ = _member(
            self.org, "bd_edit@example.com", "manager", "inventory", "edit"
        )
        self.assertEqual(
            no_tick.delete(
                url, {"ids": [str(self.product.id)]}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(
            write_tick.delete(
                url, {"ids": [str(self.product.id)]}, format="json"
            ).status_code,
            403,
        )
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

        # A different tenant's product is never touched by this tenant's bulk delete.
        other_owner = _make_user("bd_other@example.com")
        other_org = _make_org(other_owner, "Other BD Org")
        theirs = _product(other_org, "THEIRS-1")
        res = edit_tick.delete(url, {"ids": [str(theirs.id)]}, format="json")
        self.assertIn(res.status_code, (200, 204), res.content[:200])
        self.assertTrue(Product.objects.filter(pk=theirs.pk).exists())

        res = edit_tick.delete(url, {"ids": [str(self.product.id)]}, format="json")
        self.assertIn(res.status_code, (200, 204), res.content[:200])
        self.assertFalse(Product.objects.filter(pk=self.product.pk).exists())

    def test_unknown_stock_id_with_tick_is_404_not_403(self):
        _, client, _ = _member(
            self.org, "stk_404@example.com", "manager", "inventory", "edit"
        )
        self.assertEqual(
            client.delete(f"/api/v1/inventory/stock/{uuid.uuid4()}/").status_code, 404
        )
