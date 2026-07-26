from decimal import Decimal

from django.test import TestCase

from apps.accounting.tests import _make_user, _make_org, _upgrade_to_business, _auth_client
from apps.accounting.models import Account, JournalEntry
from apps.inventory.models import Product, Warehouse, StockItem
from apps.inventory.services import InventoryService
from apps.sales.models import Invoice
from apps.pos.models import RestaurantTable, POSOrder, KitchenOrderTicket


class POSModuleTests(TestCase):
    def setUp(self):
        self.user = _make_user("pos_owner@example.com")
        self.org = _make_org(self.user, "POS Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        self.warehouse = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.product = Product.objects.create(
            organisation=self.org, sku="F-1", name="Jollof Rice", product_type="physical",
            cost_price=Decimal("400"), selling_price=Decimal("1000"))
        InventoryService.record_movement(
            organisation=self.org, product=self.product, warehouse=self.warehouse,
            quantity=Decimal("50"), movement_type="purchase_in", unit_cost=Decimal("400"),
            reference="INIT", created_by=self.user)
        self.table = RestaurantTable.objects.create(organisation=self.org, name="T1", capacity=4)

    def _create_order(self, qty=2):
        return self.client.post("/api/v1/pos/orders/", {
            "order_type": "dine_in", "table": str(self.table.id),
            "items": [{"product_id": str(self.product.id), "quantity": qty, "unit_price": "1000"}],
        }, format="json")

    def test_create_order_occupies_table(self):
        res = self._create_order()
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertTrue(res.data["order_number"].startswith("ORD-"))
        self.assertEqual(len(res.data["items"]), 1)
        self.table.refresh_from_db()
        self.assertEqual(self.table.status, "occupied")

    def test_generate_kot_and_status(self):
        oid = self._create_order().data["id"]
        kot = self.client.post(f"/api/v1/pos/orders/{oid}/generate_kot/", {"section": "Kitchen"}, format="json")
        self.assertEqual(kot.status_code, 201, msg=str(kot.data))
        self.assertTrue(kot.data["kot_number"].startswith("KOT-"))
        self.assertEqual(len(kot.data["items"]), 1)
        POSOrder.objects.get(id=oid)
        st = self.client.post(f"/api/v1/pos/orders/{oid}/set_status/", {"status": "ready"}, format="json")
        self.assertEqual(st.status_code, 200, msg=str(st.data))
        self.assertEqual(st.data["status"], "ready")

    def test_split_bill_equal(self):
        oid = self._create_order().data["id"]
        res = self.client.post(f"/api/v1/pos/orders/{oid}/split_bill/", {"mode": "equal", "n": 2}, format="json")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(len(res.data["splits"]), 2)
        total = sum(Decimal(str(s["amount"])) for s in res.data["splits"])
        self.assertEqual(total, Decimal(str(res.data["total"])))

    def test_finalize_creates_invoice_reduces_stock_frees_table(self):
        oid = self._create_order(qty=2).data["id"]
        res = self.client.post(f"/api/v1/pos/orders/{oid}/finalize/", {
            "tenders": [{"amount": "2000", "method": "cash"}],
        }, format="json")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        order = POSOrder.objects.get(id=oid)
        self.assertEqual(order.status, "completed")
        self.assertIsNotNone(order.invoice_id)
        inv = Invoice.objects.get(id=order.invoice_id)
        self.assertEqual(inv.status, Invoice.Status.PAID)
        # Stock reduced 50 → 48.
        si = StockItem.objects.get(organisation=self.org, product=self.product, warehouse=self.warehouse)
        self.assertEqual(si.quantity_on_hand, Decimal("48.00"))
        # Sale journal posted.
        self.assertTrue(JournalEntry.objects.filter(
            organisation=self.org, source_type="sale", source_ref=str(inv.id)).exists())
        # Table freed.
        self.table.refresh_from_db()
        self.assertEqual(self.table.status, "available")

    def test_finalize_posts_service_charge_and_tip(self):
        order = POSOrder.objects.get(id=self._create_order().data["id"])
        order.service_charge = Decimal("150"); order.tip_amount = Decimal("100")
        order.save(update_fields=["service_charge", "tip_amount"])
        res = self.client.post(f"/api/v1/pos/orders/{order.id}/finalize/", {
            "tenders": [{"amount": "2000", "method": "cash"}]}, format="json")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        # Tips Payable (2900) created + service/tip journal posted.
        self.assertTrue(Account.objects.filter(organisation=self.org, code="2900").exists())
        self.assertTrue(JournalEntry.objects.filter(
            organisation=self.org, source_type="pos_service_tip").exists())

    def test_tenant_isolation(self):
        oid = self._create_order().data["id"]
        other = _make_user("pos_other@example.com")
        other_org = _make_org(other, "Other POS Org")
        _upgrade_to_business(other_org)
        oc = _auth_client(other, other_org)
        got = oc.get(f"/api/v1/pos/orders/{oid}/")
        self.assertIn(got.status_code, [403, 404])
