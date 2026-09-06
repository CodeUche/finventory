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
from apps.purchases.services import PurchaseReturnService, PurchaseService


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


class PurchaseOrderOverReceiptTests(TestCase):
    """
    Finding NEW-12.

    Two sibling actions with inconsistent guards. quick_receive refuses a PO
    that is already received/closed/canceled and computes each line as
    `quantity_ordered - quantity_received`, so it cannot over-receive. The
    plain `receive` action had neither check: it accepted any quantity and did
    `item.quantity_received += qty` unbounded, on a PO in any state.

    Each call also runs _upsert_bill_for_po, so an over-receipt inflates stock
    AND accounts payable together.

    Same shape as H-5: the control exists on one route and not on its sibling.
    """

    def setUp(self):
        self.user = _make_user("overrecv_owner@example.com")
        self.org = _make_org(self.user, "Over Receipt Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        self.supplier = Supplier.objects.create(organisation=self.org, name="Supplier Z")
        self.warehouse = Warehouse.objects.create(
            organisation=self.org, name="Main", is_default=True,
        )
        self.product = Product.objects.create(
            organisation=self.org, sku="OR-1", name="Widget", product_type="physical",
            cost_price=Decimal("50"), selling_price=Decimal("80"),
        )
        self.po = PurchaseOrder.objects.create(
            organisation=self.org, supplier=self.supplier, warehouse=self.warehouse,
            po_number="PO-OVER-1", order_date=date.today(),
            status=PurchaseOrder.Status.SENT, created_by=self.user,
        )
        self.item = PurchaseOrderItem.objects.create(
            organisation=self.org, purchase_order=self.po, product=self.product,
            quantity_ordered=10, unit_cost=Decimal("50"),
        )

    def _receive(self, qty):
        return self.client.post(
            f"/api/v1/purchases/orders/{self.po.id}/receive/",
            {"items": [{"item_id": str(self.item.id), "quantity_received": qty}]},
            format="json",
        )

    def _stock(self):
        si = StockItem.objects.filter(product=self.product).first()
        return Decimal(str(si.quantity_on_hand)) if si else Decimal("0")

    # --- the hole --------------------------------------------------------

    def test_cannot_receive_more_than_ordered(self):
        res = self._receive(9999)
        self.assertIn(
            res.status_code, (400, 422),
            "received 9999 units against an order of 10 — stock and AP both "
            "inflate with no upper bound (NEW-12)",
        )
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_received, 0)
        self.assertEqual(self._stock(), Decimal("0"))

    def test_cannot_receive_twice_beyond_the_order(self):
        """Second receipt must be capped by what the first already took."""
        first = self._receive(10)
        self.assertIn(first.status_code, (200, 201), first.content[:300])
        self.assertEqual(self._stock(), Decimal("10"))

        second = self._receive(10)
        self.assertIn(
            second.status_code, (400, 422),
            "a fully received PO accepted another 10 units — stock doubled",
        )
        self.assertEqual(
            self._stock(), Decimal("10"),
            "stock moved on a receipt that should have been refused",
        )

    def test_cannot_receive_against_a_cancelled_po(self):
        self.po.status = PurchaseOrder.Status.CANCELED
        self.po.save(update_fields=["status"])
        res = self._receive(5)
        self.assertIn(
            res.status_code, (400, 422),
            "goods were received against a cancelled purchase order",
        )
        self.assertEqual(self._stock(), Decimal("0"))

    # --- what must keep working -----------------------------------------

    def test_exact_quantity_is_accepted(self):
        res = self._receive(10)
        self.assertIn(res.status_code, (200, 201), res.content[:300])
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.Status.RECEIVED)
        self.assertEqual(self._stock(), Decimal("10"))

    def test_partial_receipt_still_works(self):
        res = self._receive(4)
        self.assertIn(res.status_code, (200, 201), res.content[:300])
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.Status.PARTIALLY_RECEIVED)
        self.assertEqual(self._stock(), Decimal("4"))

    def test_remainder_can_be_received_afterwards(self):
        """Partial then the rest — the normal two-delivery case."""
        self._receive(4)
        res = self._receive(6)
        self.assertIn(res.status_code, (200, 201), res.content[:300])
        self.po.refresh_from_db()
        self.assertEqual(self.po.status, PurchaseOrder.Status.RECEIVED)
        self.assertEqual(self._stock(), Decimal("10"))


class PurchaseTaxInclusiveExclusiveTests(TestCase):
    """Product.tax_type must apply the same on the buying side as the selling
    side — a product's inclusive/exclusive convention doesn't flip depending
    on which direction it's moving."""

    def setUp(self):
        from apps.tax.models import TaxClass
        self.user = _make_user("purch_taxtype@example.com")
        self.org = _make_org(self.user, "Purchase Tax Type Org")
        self.vat = TaxClass.objects.create(organisation=self.org, name="VAT 15%", rate=Decimal("15"))

    def _validate(self, product, unit_cost, quantity="1"):
        from apps.purchases.serializers import PurchaseOrderItemSerializer
        serializer = PurchaseOrderItemSerializer()
        return serializer.validate({
            "product": product,
            "quantity_ordered": Decimal(quantity),
            "unit_cost": Decimal(unit_cost),
            "discount_percent": Decimal("0"),
        })

    def test_exclusive_adds_tax_on_top(self):
        p = Product.objects.create(
            organisation=self.org, sku="PT-EXCL", name="Exclusive Buy",
            product_type="physical", cost_price=1000, selling_price=1500,
            is_taxable=True, tax_class=self.vat,
        )
        attrs = self._validate(p, "1000")
        self.assertAlmostEqual(float(attrs["tax_amount"]), 150.0, places=2)
        self.assertAlmostEqual(float(attrs["line_total"]), 1150.0, places=2)

    def test_inclusive_backs_tax_out(self):
        p = Product.objects.create(
            organisation=self.org, sku="PT-INCL", name="Inclusive Buy",
            product_type="physical", cost_price=1150, selling_price=1500,
            is_taxable=True, tax_class=self.vat, tax_type="inclusive",
        )
        attrs = self._validate(p, "1150")
        self.assertAlmostEqual(float(attrs["tax_amount"]), 150.0, places=2)
        self.assertAlmostEqual(float(attrs["line_total"]), 1150.0, places=2)


class ConvertToBillTests(TestCase):
    """
    S3/S3b: an explicit "bill the supplier before goods arrive" action,
    distinct from the existing receive-triggers-bill flow. Covers correct GL
    posting, the double-billing guard when goods are later physically
    received, and behaviour with and without a configured goods-in-transit
    clearing account.
    """

    def setUp(self):
        self.user = _make_user("convbill_owner@example.com")
        self.org = _make_org(self.user, "Convert Bill Org")
        _upgrade_to_business(self.org)
        self.supplier = Supplier.objects.create(organisation=self.org, name="Early Invoice Supplies")
        self.warehouse = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.product = Product.objects.create(
            organisation=self.org, sku="CB-1", name="Widget", product_type="physical",
            cost_price=Decimal("100"), selling_price=Decimal("150"),
        )
        self.po = PurchaseOrder.objects.create(
            organisation=self.org, po_number=PurchaseOrder.generate_number(self.org),
            supplier=self.supplier, warehouse=self.warehouse, status="sent",
            order_date=date(2026, 6, 1), subtotal=Decimal("1000"),
            tax_amount=Decimal("75"), total_amount=Decimal("1075"), created_by=self.user,
        )
        self.po_item = PurchaseOrderItem.objects.create(
            organisation=self.org, purchase_order=self.po, product=self.product,
            quantity_ordered=Decimal("10"), quantity_received=Decimal("0"),
            unit_cost=Decimal("100"), line_total=Decimal("1000"), tax_rate=Decimal("7.5"),
        )

    def _journal_lines(self, source_type, source_ref):
        return list(JournalEntry.objects.get(
            organisation=self.org, source_type=source_type, source_ref=source_ref,
        ).lines.all())

    def test_convert_creates_a_bill_for_the_full_po_value(self):
        from apps.bills.models import Bill
        po = PurchaseService.convert_to_bill(self.po, self.user)
        self.assertTrue(po.billed_before_receipt)

        bill = Bill.objects.get(organisation=self.org, source_purchase_order=po)
        self.assertEqual(Decimal(str(bill.subtotal)), Decimal("1000"))
        self.assertEqual(Decimal(str(bill.tax_amount)), Decimal("75"))
        self.assertEqual(Decimal(str(bill.total_amount)), Decimal("1075"))
        self.assertEqual(bill.gl_post_status, "posted")

    def test_convert_posts_goods_in_transit_debit_and_ap_credit_when_unmapped(self):
        # No goods_in_transit_account configured — falls back to plain
        # Inventory, exactly like _upsert_bill_for_po's own unmapped fallback.
        po = PurchaseService.convert_to_bill(self.po, self.user)
        lines = self._journal_lines("po_convert_to_bill", str(po.id))
        by_code = {l.account.code: (Decimal(str(l.debit)), Decimal(str(l.credit))) for l in lines}
        inv_acct = AccountMappingService.resolve(self.org, "inventory_account")
        ap_acct = AccountMappingService.resolve(self.org, "accounts_payable")
        vat_acct = AccountMappingService.resolve(self.org, "vat_input_account")
        self.assertEqual(by_code[inv_acct.code][0], Decimal("1000"))
        self.assertEqual(by_code[ap_acct.code][1], Decimal("1075"))
        self.assertEqual(by_code[vat_acct.code][0], Decimal("75"))

    def test_convert_posts_to_dedicated_clearing_account_when_mapped(self):
        from apps.accounting.models import Account
        transit_acct = Account.objects.create(
            organisation=self.org, code="1250", name="Goods In Transit",
            account_type="asset", normal_balance="debit",
        )
        mapping = AccountMappingService.get_or_create_mapping(self.org)
        mapping.goods_in_transit_account = transit_acct
        mapping.save(update_fields=["goods_in_transit_account"])

        po = PurchaseService.convert_to_bill(self.po, self.user)
        lines = self._journal_lines("po_convert_to_bill", str(po.id))
        by_code = {l.account.code: (Decimal(str(l.debit)), Decimal(str(l.credit))) for l in lines}
        inv_acct = AccountMappingService.resolve(self.org, "inventory_account")
        self.assertNotIn(inv_acct.code, by_code)
        self.assertEqual(by_code["1250"][0], Decimal("1000"))

    def test_cannot_convert_twice(self):
        PurchaseService.convert_to_bill(self.po, self.user)
        self.po.refresh_from_db()
        with self.assertRaises(ValueError):
            PurchaseService.convert_to_bill(self.po, self.user)

    def test_cannot_convert_a_received_po(self):
        self.po.status = PurchaseOrder.Status.RECEIVED
        self.po.save(update_fields=["status"])
        with self.assertRaises(ValueError):
            PurchaseService.convert_to_bill(self.po, self.user)

    def test_cannot_convert_a_po_with_no_supplier(self):
        self.po.supplier = None
        self.po.save(update_fields=["supplier"])
        with self.assertRaises(ValueError):
            PurchaseService.convert_to_bill(self.po, self.user)

    def test_later_physical_receipt_does_not_double_bill(self):
        # The core guard: goods arrive AFTER the supplier invoice was already
        # booked in full — the bill's total must not grow, no second bill,
        # but stock must still move for real.
        from apps.bills.models import Bill
        po = PurchaseService.convert_to_bill(self.po, self.user)
        bill_before = Bill.objects.get(organisation=self.org, source_purchase_order=po)
        total_before = Decimal(str(bill_before.total_amount))

        po = PurchaseService.receive_purchase_order(
            po, [{"item_id": str(self.po_item.id), "quantity_received": "10"}], self.user,
        )

        bills = Bill.objects.filter(organisation=self.org, source_purchase_order=po)
        self.assertEqual(bills.count(), 1)
        bill_after = bills.first()
        self.assertEqual(Decimal(str(bill_after.total_amount)), total_before)

        si = StockItem.objects.get(organisation=self.org, product=self.product, warehouse=self.warehouse)
        self.assertEqual(si.quantity_on_hand, Decimal("10.00"))

    def test_later_physical_receipt_moves_value_from_clearing_to_inventory(self):
        from apps.accounting.models import Account
        transit_acct = Account.objects.create(
            organisation=self.org, code="1251", name="Goods In Transit",
            account_type="asset", normal_balance="debit",
        )
        mapping = AccountMappingService.get_or_create_mapping(self.org)
        mapping.goods_in_transit_account = transit_acct
        mapping.save(update_fields=["goods_in_transit_account"])

        po = PurchaseService.convert_to_bill(self.po, self.user)
        po = PurchaseService.receive_purchase_order(
            po, [{"item_id": str(self.po_item.id), "quantity_received": "10"}], self.user,
        )

        lines = self._journal_lines("po_receipt_clearing", str(po.id))
        by_code = {l.account.code: (Decimal(str(l.debit)), Decimal(str(l.credit))) for l in lines}
        inv_acct = AccountMappingService.resolve(self.org, "inventory_account")
        self.assertEqual(by_code[inv_acct.code][0], Decimal("1000"))
        self.assertEqual(by_code["1251"][1], Decimal("1000"))

    def test_later_physical_receipt_posts_no_redundant_entry_when_unmapped(self):
        # Both conversion and receipt fell back to plain Inventory — DR then
        # CR the same account for the same amount would be a real but
        # pointless zero-effect journal entry. Must not be posted at all.
        po = PurchaseService.convert_to_bill(self.po, self.user)
        po = PurchaseService.receive_purchase_order(
            po, [{"item_id": str(self.po_item.id), "quantity_received": "10"}], self.user,
        )
        self.assertFalse(
            JournalEntry.objects.filter(
                organisation=self.org, source_type="po_receipt_clearing", source_ref=str(po.id),
            ).exists()
        )

    def test_purchase_order_serializer_exposes_the_linked_bill(self):
        from apps.purchases.serializers import PurchaseOrderSerializer
        po = PurchaseService.convert_to_bill(self.po, self.user)
        data = PurchaseOrderSerializer(po).data
        self.assertTrue(data["billed_before_receipt"])
        self.assertIsNotNone(data["bill_id"])
        self.assertTrue(data["bill_number"].startswith("BILL"))

    def test_bill_serializer_exposes_the_source_po(self):
        from apps.bills.models import Bill
        from apps.bills.serializers import BillSerializer
        po = PurchaseService.convert_to_bill(self.po, self.user)
        bill = Bill.objects.get(organisation=self.org, source_purchase_order=po)
        data = BillSerializer(bill).data
        self.assertEqual(data["source_po_number"], po.po_number)
