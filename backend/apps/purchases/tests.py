"""Purchase Return tests — inventory reduction + reversing GL posting."""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounting.tests import _make_user, _make_org, _upgrade_to_business, _auth_client
from apps.accounting.models import JournalEntry
from apps.accounting.services import AccountMappingService
from apps.inventory.models import Product, Warehouse, StockItem
from apps.inventory.services import InventoryService
from apps.suppliers.models import Supplier
from apps.purchases.models import PurchaseOrder, PurchaseOrderItem, PurchaseReturn
from apps.purchases.services import PurchaseReturnService


class PurchaseReturnTests(TestCase):
    def setUp(self):
        self.user = _make_user("pret_owner@example.com")
        self.org = _make_org(self.user, "PRet Org")
        _upgrade_to_business(self.org)
        self.supplier = Supplier.objects.create(organisation=self.org, name="Acme Supplies")
        self.warehouse = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.product = Product.objects.create(
            organisation=self.org, sku="P-1", name="Widget", product_type="physical",
            cost_price=Decimal("100"), selling_price=Decimal("150"),
        )
        # Receive 10 units into stock.
        InventoryService.record_movement(
            organisation=self.org, product=self.product, warehouse=self.warehouse,
            quantity=Decimal("10"), movement_type="purchase_in", unit_cost=Decimal("100"),
            reference="INIT", created_by=self.user,
        )
        self.po = PurchaseOrder.objects.create(
            organisation=self.org, po_number=PurchaseOrder.generate_number(self.org),
            supplier=self.supplier, warehouse=self.warehouse, status="received",
            order_date=date(2026, 6, 1), subtotal=Decimal("1000"),
            tax_amount=Decimal("75"), total_amount=Decimal("1075"), created_by=self.user,
        )
        PurchaseOrderItem.objects.create(
            organisation=self.org, purchase_order=self.po, product=self.product,
            quantity_ordered=Decimal("10"), quantity_received=Decimal("10"),
            unit_cost=Decimal("100"), line_total=Decimal("1000"),
        )

    def test_return_reduces_stock_and_posts_reversing_journal(self):
        pret = PurchaseReturnService.process_return(
            self.org, self.po,
            items=[{"product_id": str(self.product.id), "quantity": "4"}],
            return_date=date(2026, 6, 20), refund_method="ap", created_by=self.user,
        )
        # Totals: net 400, VAT 7.5% of proportional = 30, total 430.
        self.assertEqual(pret.subtotal, Decimal("400.00"))
        self.assertEqual(pret.tax_amount, Decimal("30.00"))
        self.assertEqual(pret.total_amount, Decimal("430.00"))
        self.assertEqual(pret.gl_post_status, "posted")
        # Stock reduced 10 → 6.
        si = StockItem.objects.get(organisation=self.org, product=self.product, warehouse=self.warehouse)
        self.assertEqual(si.quantity_on_hand, Decimal("6.00"))
        # PO received qty rolled back 10 → 6.
        self.po.items.first().refresh_from_db()
        self.assertEqual(self.po.items.first().quantity_received, Decimal("6.00"))
        # Reversing journal: DR Accounts Payable 430.
        je = JournalEntry.objects.filter(
            organisation=self.org, source_type="purchase_return", source_ref=str(pret.id)).first()
        self.assertIsNotNone(je)
        ap = AccountMappingService.resolve(self.org, "accounts_payable")
        inv = AccountMappingService.resolve(self.org, "inventory_account")
        self.assertTrue(je.lines.filter(account=ap, debit=Decimal("430.00")).exists())
        self.assertTrue(je.lines.filter(account=inv, credit=Decimal("400.00")).exists())

    def test_cannot_return_more_than_on_hand(self):
        with self.assertRaises(Exception):
            PurchaseReturnService.process_return(
                self.org, self.po,
                items=[{"product_id": str(self.product.id), "quantity": "99"}],
                created_by=self.user,
            )

    def test_api_create_return(self):
        client = _auth_client(self.user, self.org)
        res = client.post("/api/v1/purchases/returns/", {
            "purchase_order_id": str(self.po.id),
            "items": [{"product_id": str(self.product.id), "quantity": 2}],
        }, format="json")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(PurchaseReturn.objects.filter(organisation=self.org).count(), 1)

    def test_report_lists_return(self):
        PurchaseReturnService.process_return(
            self.org, self.po,
            items=[{"product_id": str(self.product.id), "quantity": "3"}],
            return_date=date(2026, 6, 20), created_by=self.user,
        )
        from apps.reports.registry import get as get_report
        rd = get_report("purchase-returns")
        data = rd.resolver(self.org, date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["total"], Decimal("322.50"))  # 300 + 22.50 VAT


class PurchaseOrderStatusBypassTests(TestCase):
    """
    Finding H-5.

    ``receive_purchase_order()`` is the only path that moves stock and creates
    the supplier Bill. ``status`` was writable on PurchaseOrderSerializer with
    no override of the default ModelViewSet update, so a plain PATCH could mark
    a PO "received" with no stock movement, no Bill and no GL posting — books
    reconciled against goods that never arrived.

    The UI's edit dialog legitimately PATCHes status (PurchasesPage.tsx), so the
    fix blocks only the two states that carry side effects and leaves the
    administrative ones working.
    """

    def setUp(self):
        self.user = _make_user("postatus_owner@example.com")
        self.org = _make_org(self.user, "PO Status Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        self.supplier = Supplier.objects.create(organisation=self.org, name="Supplier X")
        self.warehouse = Warehouse.objects.create(
            organisation=self.org, name="Main", is_default=True,
        )
        self.product = Product.objects.create(
            organisation=self.org, sku="PS-1", name="Thing", product_type="physical",
            cost_price=Decimal("50"), selling_price=Decimal("80"),
        )
        self.po = PurchaseOrder.objects.create(
            organisation=self.org, supplier=self.supplier, warehouse=self.warehouse,
            po_number="PO-STATUS-1", order_date=date.today(),
            status=PurchaseOrder.Status.SENT, created_by=self.user,
        )
        PurchaseOrderItem.objects.create(
            organisation=self.org, purchase_order=self.po, product=self.product,
            quantity_ordered=10, unit_cost=Decimal("50"),
        )

    def _patch(self, payload):
        return self.client.patch(
            f"/api/v1/purchases/orders/{self.po.id}/", payload, format="json",
        )

    def test_cannot_mark_received_via_patch(self):
        res = self._patch({"status": PurchaseOrder.Status.RECEIVED})
        self.assertIn(
            res.status_code, (400, 422),
            "PATCH set PO status to 'received' — stock never moved and no Bill "
            "was created, but the books show the goods as arrived (H-5)",
        )
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.Status.SENT)

    def test_cannot_mark_partially_received_via_patch(self):
        res = self._patch({"status": PurchaseOrder.Status.PARTIALLY_RECEIVED})
        self.assertIn(res.status_code, (400, 422))
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.Status.SENT)

    def test_no_stock_is_created_by_the_bypass_attempt(self):
        """The reason this matters: the bypass would desync stock from purchasing."""
        self._patch({"status": PurchaseOrder.Status.RECEIVED})
        self.assertFalse(
            StockItem.objects.filter(product=self.product).exists(),
            "stock existed after a status-only PATCH",
        )

    # --- the administrative transitions the UI relies on must keep working ---

    def test_can_still_set_administrative_statuses(self):
        for status in (
            PurchaseOrder.Status.DRAFT,
            PurchaseOrder.Status.SENT,
            PurchaseOrder.Status.CLOSED,
            PurchaseOrder.Status.CANCELED,
        ):
            with self.subTest(status=status):
                res = self._patch({"status": status})
                self.assertEqual(
                    res.status_code, 200,
                    f"blocking '{status}' breaks the PO edit dialog in PurchasesPage.tsx",
                )
                self.po.refresh_from_db()
                self.assertEqual(self.po.status, status)

    def test_can_still_edit_non_status_fields(self):
        res = self._patch({"notes": "Chasing the supplier"})
        self.assertEqual(res.status_code, 200)
        self.po.refresh_from_db()
        self.assertEqual(self.po.notes, "Chasing the supplier")

    def test_receive_action_still_sets_received(self):
        """The legitimate path must remain the way to reach 'received'."""
        res = self.client.post(
            f"/api/v1/purchases/orders/{self.po.id}/receive/",
            {"items": [{"item_id": str(self.po.items.first().id), "quantity_received": 10}]},
            format="json",
        )
        self.assertIn(res.status_code, (200, 201), res.content[:300])
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.Status.RECEIVED)
        self.assertTrue(
            StockItem.objects.filter(product=self.product).exists(),
            "receive action did not move stock",
        )
