"""Cross-feature end-to-end flow — simulates a real restaurant user session over the
HTTP API, chaining the major new features together and asserting they interoperate."""
from decimal import Decimal

from django.test import TestCase

from apps.accounting.tests import _make_user, _make_org, _upgrade_to_business, _auth_client
from apps.accounting.models import JournalEntry
from apps.inventory.models import Product, Warehouse, StockItem
from apps.inventory.services import InventoryService
from apps.sales.models import Invoice


class RestaurantEndToEndFlowTests(TestCase):
    def setUp(self):
        self.user = _make_user("e2e_owner@example.com")
        self.org = _make_org(self.user, "E2E Bistro")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        self.wh = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.product = Product.objects.create(
            organisation=self.org, sku="M-1", name="Grilled Chicken", product_type="physical",
            cost_price=Decimal("600"), selling_price=Decimal("1500"))
        InventoryService.record_movement(
            organisation=self.org, product=self.product, warehouse=self.wh,
            quantity=Decimal("100"), movement_type="purchase_in", unit_cost=Decimal("600"),
            reference="INIT", created_by=self.user)

    def test_full_restaurant_session(self):
        c = self.client

        # 1) Switch the org into restaurant mode.
        r = c.patch(f"/api/v1/tenancy/organisations/{self.org.id}/", {"business_type": "restaurant"}, format="json")
        self.assertIn(r.status_code, [200, 202], msg=str(r.data))

        # 2) Generate a fiscal year of periods.
        r = c.post("/api/v1/accounting/periods/generate_fiscal_year/",
                   {"year": 2026, "start_date": "2026-01-01"}, format="json")
        self.assertEqual(r.status_code, 201, msg=str(r.data))
        self.assertEqual(len(r.data["periods"]), 12)

        # 3) Create a table.
        r = c.post("/api/v1/pos/tables/", {"name": "T5", "capacity": 4, "section": "Patio"}, format="json")
        self.assertEqual(r.status_code, 201, msg=str(r.data))
        table_id = r.data["id"]

        # 4) Take a dine-in order.
        r = c.post("/api/v1/pos/orders/", {
            "order_type": "dine_in", "table": table_id,
            "items": [{"product_id": str(self.product.id), "quantity": 3, "unit_price": "1500"}],
            "service_charge": "200", "tip_amount": "100",
        }, format="json")
        self.assertEqual(r.status_code, 201, msg=str(r.data))
        order_id = r.data["id"]

        # 5) Send it to the kitchen (KOT).
        r = c.post(f"/api/v1/pos/orders/{order_id}/generate_kot/", {"section": "Grill"}, format="json")
        self.assertEqual(r.status_code, 201, msg=str(r.data))
        kot_id = r.data["id"]

        # 6) Kitchen advances the ticket.
        r = c.post(f"/api/v1/pos/kots/{kot_id}/set_status/", {"status": "ready"}, format="json")
        self.assertEqual(r.status_code, 200, msg=str(r.data))

        # 7) Split the bill (informational) then pay with a split tender.
        r = c.post(f"/api/v1/pos/orders/{order_id}/split_bill/", {"mode": "equal", "n": 2}, format="json")
        self.assertEqual(r.status_code, 200, msg=str(r.data))
        r = c.post(f"/api/v1/pos/orders/{order_id}/finalize/", {
            "tenders": [{"amount": "3000", "method": "cash"}, {"amount": "1500", "method": "card"}],
        }, format="json")
        self.assertEqual(r.status_code, 201, msg=str(r.data))
        invoice_number = r.data["invoice_number"]

        # 8) The sale posted to the GL and reduced stock.
        inv = Invoice.objects.get(organisation=self.org, invoice_number=invoice_number)
        self.assertEqual(inv.status, Invoice.Status.PAID)
        self.assertTrue(JournalEntry.objects.filter(
            organisation=self.org, source_type="sale", source_ref=str(inv.id)).exists())
        si = StockItem.objects.get(organisation=self.org, product=self.product, warehouse=self.wh)
        self.assertEqual(si.quantity_on_hand, Decimal("97.00"))

        # 9) Reports reflect the activity.
        cat = c.get("/api/v1/reports/catalog/")
        self.assertEqual(cat.status_code, 200)
        pack = c.get("/api/v1/reports/r/financial-report-pack/",
                     {"period": "custom", "date_from": "2026-01-01", "date_to": "2026-12-31"})
        self.assertEqual(pack.status_code, 200, msg=str(pack.data))
        self.assertIn("balance_sheet", pack.data["data"])

        # 10) GL Health is queryable and includes reconciliations.
        gh = c.get("/api/v1/accounting/gl-health/")
        self.assertEqual(gh.status_code, 200)
        self.assertIn("reconciliations", gh.data)

        # 11) Raise a support ticket.
        tk = c.post("/api/v1/helpdesk/tickets/", {"subject": "Printer jam", "priority": "high"}, format="json")
        self.assertEqual(tk.status_code, 201, msg=str(tk.data))

        # 12) Month-end: the close checklist is reachable for a period.
        period = c.get("/api/v1/accounting/periods/").data
        plist = period.get("results", period)
        june = next(p for p in plist if p["year"] == 2026 and p["month"] == 6)
        chk = c.get(f"/api/v1/accounting/periods/{june['id']}/close_checklist/")
        self.assertEqual(chk.status_code, 200, msg=str(chk.data))
        self.assertIn("checks", chk.data)
