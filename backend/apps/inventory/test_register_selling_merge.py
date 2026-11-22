"""
Merge-time contract between the stock-tick fix and the register cashier fix.

The cashier fix (branch feat/global-ds-polish, commit aa1a106) adds
RegisterSellingRead to apps/core/permissions.py: staff holding the sales tick
get READ-ONLY product and warehouse lists, so the register can sell. It must not
open stock levels or any stock-changing endpoint.

These tests are skipped until that class exists, and light up automatically when
the two branches are merged.
"""

import unittest

from django.test import TestCase

from apps.core import permissions
from apps.core.test_module_access import _member
from apps.inventory.models import Product, Warehouse
from apps.payroll.test_track_a import _make_org, _make_user


@unittest.skipUnless(
    hasattr(permissions, "RegisterSellingRead"),
    "RegisterSellingRead (cashier fix, feat/global-ds-polish aa1a106) "
    "is not merged yet",
)
class RegisterCashierAfterMergeTests(TestCase):
    def setUp(self):
        self.owner = _make_user("rsm_owner@example.com")
        self.org = _make_org(self.owner, "Register Merge Org")
        self.warehouse = Warehouse.objects.create(
            organisation=self.org, name="Main", is_default=True)
        self.product = Product.objects.create(
            organisation=self.org,
            sku="RSM-1",
            name="Till Item",
            product_type="physical",
            cost_price="100.00",
            selling_price="150.00",
            unit_of_measure="unit",
        )
        # A cashier: staff, sales write, nothing else.
        _, self.cashier, _ = _member(
            self.org, "rsm_cashier@example.com", "staff", "sales", "write"
        )

    def test_cashier_can_read_products_and_warehouses(self):
        self.assertEqual(
            self.cashier.get("/api/v1/inventory/products/").status_code, 200
        )
        self.assertEqual(
            self.cashier.get("/api/v1/inventory/warehouses/").status_code, 200
        )

    def test_cashier_cannot_read_stock_levels(self):
        self.assertEqual(self.cashier.get("/api/v1/inventory/stock/").status_code, 403)

    def test_cashier_cannot_adjust_stock(self):
        res = self.cashier.post("/api/v1/inventory/movements/adjust/", {
            "product_id": str(self.product.id), "warehouse_id": str(self.warehouse.id),
            "quantity": 5, "reason": "cashier",
        }, format="json")
        self.assertEqual(res.status_code, 403)

    def test_cashier_cannot_bulk_delete_products(self):
        res = self.cashier.delete(
            "/api/v1/inventory/products/bulk-delete/",
            {"ids": [str(self.product.id)]}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())
