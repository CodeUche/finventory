"""Tests for inventory: products, stock movements, warehouses, low stock."""

import base64
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.inventory.models import ComboComponent, Product, ProductImage, Warehouse
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


class ProductListQueryCountTests(TestCase):
    """
    Regression guard for the products-list N+1 (real users with large catalogs
    saw 6s+ responses that overran the client timeout → "cannot see inventory").

    The list endpoint must run a BOUNDED number of queries regardless of how
    many products exist, and the annotated fast-path values must match the
    per-object slow-path computation exactly.
    """

    def setUp(self):
        self.user = _make_user("nplusone@example.com")
        self.org = _make_org(self.user, name="NPlusOne Org")
        self.client = _auth_client(self.user, self.org)
        self.wh = _make_warehouse(self.org)

        from apps.inventory.models import Category, StockItem
        cat = Category.objects.create(organisation=self.org, name="Spirits")
        for i in range(30):
            p = Product.objects.create(
                organisation=self.org, sku=f"NP1-{i:03d}", name=f"NP1 Product {i}",
                selling_price=Decimal("100.00"), cost_price=Decimal("60.00"),
                category=cat,
            )
            if i % 2 == 0:  # half the products have stock rows
                StockItem.objects.create(
                    organisation=self.org, product=p, warehouse=self.wh,
                    quantity_on_hand=Decimal(str(i + 1)),
                )

    def test_list_query_count_is_bounded_and_values_correct(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            res = self.client.get("/api/v1/inventory/products/?page_size=9999&slim=1")
        self.assertEqual(res.status_code, 200)
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(rows), 30)

        # Before the fix this was 2 queries PER PRODUCT (60+ for 30 products).
        # Annotated, the whole request must stay under a fixed ceiling.
        self.assertLess(
            len(ctx.captured_queries), 20,
            f"products list ran {len(ctx.captured_queries)} queries — N+1 regression",
        )

        # Correctness: annotated total_stock equals the actual stock per product.
        by_sku = {r["sku"]: r for r in rows}
        for i in range(30):
            expected = Decimal(str(i + 1)) if i % 2 == 0 else Decimal("0")
            got = Decimal(str(by_sku[f"NP1-{i:03d}"]["total_stock"]))
            self.assertEqual(got, expected, f"total_stock wrong for NP1-{i:03d}")

    def test_plain_list_stays_full_for_old_clients(self):
        """Without ?slim=1 (old installed clients) the list keeps EVERY field —
        old edit forms prefill from the list, so slimming it would wipe data."""
        res = self.client.get("/api/v1/inventory/products/?page_size=5")
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        for field in ("description", "barcode", "wholesale_price", "max_stock_level",
                      "quantity_in_pack", "quantity_incoming", "created_at", "updated_at"):
            self.assertIn(field, rows[0], f"plain list must keep '{field}' for old clients")

    def test_list_payload_is_slim_but_detail_is_full(self):
        """With ?slim=1 the list drops heavyweight fields; detail keeps them all."""
        res = self.client.get("/api/v1/inventory/products/?page_size=5&slim=1")
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        row = rows[0]
        for field in ("id", "sku", "name", "selling_price", "cost_price",
                      "total_stock", "product_type", "is_active", "tax_class",
                      "category_name", "volume_ml", "alcohol_percentage"):
            self.assertIn(field, row, f"list must keep '{field}'")
        for field in ("description", "barcode", "wholesale_price", "max_stock_level",
                      "reorder_quantity", "quantity_in_pack", "quantity_incoming",
                      "created_at", "updated_at"):
            self.assertNotIn(field, row, f"list should not ship '{field}'")

        detail = self.client.get(f"/api/v1/inventory/products/{row['id']}/").data
        for field in ("description", "barcode", "wholesale_price", "quantity_in_pack",
                      "quantity_incoming", "created_at", "updated_at"):
            self.assertIn(field, detail, f"detail must keep '{field}'")

    def test_stock_list_query_count_is_bounded(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            res = self.client.get("/api/v1/inventory/stock/")
        self.assertEqual(res.status_code, 200)
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertGreaterEqual(len(rows), 15)
        self.assertLess(
            len(ctx.captured_queries), 20,
            f"stock list ran {len(ctx.captured_queries)} queries — N+1 regression",
        )


class CostingMethodTests(TestCase):
    """
    FIFO / LIFO / Average / Specific Unit costing (the reviewer's "Add Inventory
    Costing Methods" request).

    These assert on MONEY, so they check exact consumed cost, not just that a
    sale succeeded. The scenario is deliberately the classic one: two inbound
    layers at different unit costs, then a sale that spans both, where every
    method gives a provably different answer.
    """

    def setUp(self):
        from apps.customers.models import Customer
        self.user = _make_user("costing@example.com")
        self.org = _make_org(self.user, "Costing Org")
        self.client = _auth_client(self.user, self.org)
        self.wh = _make_warehouse(self.org)
        self.customer = Customer.objects.create(
            organisation=self.org, code="C-COST", name="Cost Customer",
        )

    def _product(self, method, sku="COST-1"):
        return Product.objects.create(
            organisation=self.org, sku=sku, name=f"Item {method}",
            product_type="physical", costing_method=method,
            cost_price=Decimal("100"), selling_price=Decimal("500"),
        )

    def _receive(self, product, qty, unit_cost, reference="PO"):
        from apps.inventory.services import InventoryService
        return InventoryService.record_movement(
            organisation=self.org, product=product, warehouse=self.wh,
            quantity=Decimal(str(qty)), movement_type="purchase_in",
            unit_cost=Decimal(str(unit_cost)), reference=reference,
            created_by=self.user,
        )

    def _sell(self, product, qty, batch=None):
        """Sell via the real sale path so COGS wiring is covered too."""
        from apps.sales.services import SaleService
        item = {"product_id": str(product.id), "quantity": str(qty), "unit_price": "500"}
        if batch is not None:
            item["batch_id"] = str(batch.id)
        invoice = SaleService.create_sale(
            organisation=self.org, created_by=self.user, customer=self.customer,
            warehouse=self.wh, items=[item], payment_method="cash",
        )
        return invoice

    def test_fifo_consumes_oldest_layers_first(self):
        p = self._product("fifo")
        self._receive(p, 10, "100")
        self._receive(p, 10, "200")
        invoice = self._sell(p, 15)          # 10 @ 100 + 5 @ 200 = 2000 → 133.3333/unit
        line = invoice.items.first()
        self.assertAlmostEqual(float(line.cost_of_goods), 2000.0, places=2)

    def test_lifo_consumes_newest_layers_first(self):
        p = self._product("lifo")
        self._receive(p, 10, "100")
        self._receive(p, 10, "200")
        invoice = self._sell(p, 15)          # 10 @ 200 + 5 @ 100 = 2500
        line = invoice.items.first()
        self.assertAlmostEqual(float(line.cost_of_goods), 2500.0, places=2)

    def test_average_uses_running_weighted_average(self):
        p = self._product("average")
        self._receive(p, 10, "100")
        self._receive(p, 10, "200")          # weighted avg = 150
        invoice = self._sell(p, 15)          # 15 × 150 = 2250
        line = invoice.items.first()
        self.assertAlmostEqual(float(line.cost_of_goods), 2250.0, places=2)

    def test_specific_unit_uses_chosen_batch_cost(self):
        from apps.inventory.models import Batch
        p = self._product("specific")
        self._receive(p, 10, "100")
        self._receive(p, 10, "200")
        batch = Batch.objects.create(
            organisation=self.org, product=p, warehouse=self.wh,
            batch_number="LOT-A", quantity=Decimal("10"), unit_cost=Decimal("175"),
        )
        invoice = self._sell(p, 5, batch=batch)   # 5 × 175 = 875
        line = invoice.items.first()
        self.assertAlmostEqual(float(line.cost_of_goods), 875.0, places=2)
        # The chosen lot must be recorded on the line, not silently dropped.
        self.assertEqual(line.batch_id, batch.id)

    def test_fifo_layers_are_drawn_down_across_successive_sales(self):
        """Second sale must not re-consume the first sale's layer."""
        p = self._product("fifo")
        self._receive(p, 10, "100")
        self._receive(p, 10, "200")
        first = self._sell(p, 10)            # exhausts the 100-cost layer
        second = self._sell(p, 5)            # must now draw from the 200 layer
        self.assertAlmostEqual(float(first.items.first().cost_of_goods), 1000.0, places=2)
        self.assertAlmostEqual(float(second.items.first().cost_of_goods), 1000.0, places=2)

    def test_default_method_is_average_for_new_products(self):
        p = Product.objects.create(
            organisation=self.org, sku="COST-DEFAULT", name="Default",
            product_type="physical", cost_price=Decimal("100"), selling_price=Decimal("500"),
        )
        self.assertEqual(p.costing_method, Product.CostingMethod.AVERAGE)

    def test_cogs_falls_back_to_cost_price_without_layer_history(self):
        """Stock taken on before any purchase layer must still cost sanely."""
        from apps.inventory.services import InventoryService
        p = self._product("fifo", sku="COST-NOHIST")
        # Opening-balance style movement still builds a layer, so bypass it and
        # seed the balance the way pre-engine stock would have existed.
        from apps.inventory.models import StockItem, StockCostLayer
        InventoryService.record_movement(
            organisation=self.org, product=p, warehouse=self.wh,
            quantity=Decimal("10"), movement_type="opening",
            unit_cost=Decimal("100"), reference="SEED", created_by=self.user,
        )
        StockCostLayer.objects.filter(organisation=self.org, product=p).delete()
        invoice = self._sell(p, 5)           # no layers → falls back to 100/unit
        self.assertAlmostEqual(float(invoice.items.first().cost_of_goods), 500.0, places=2)

    def test_gl_cogs_matches_the_consumed_ledger_cost(self):
        """
        The journal must post the SAME cost the stock ledger consumed. If COGS
        were still taken from the flat product.cost_price, a FIFO sale would
        post 100/unit to the GL while the ledger consumed 200/unit, and the two
        would drift apart permanently.
        """
        from apps.accounting.models import JournalEntry
        p = self._product("lifo", sku="COST-GL")
        self._receive(p, 10, "100")
        self._receive(p, 10, "200")
        invoice = self._sell(p, 5)           # LIFO → 5 × 200 = 1000
        line = invoice.items.first()
        self.assertAlmostEqual(float(line.cost_of_goods), 1000.0, places=2)

        entry = JournalEntry.objects.filter(
            organisation=self.org, source_type="sale", source_ref=str(invoice.id),
        ).first()
        self.assertIsNotNone(entry)
        cogs_debits = [
            float(l.debit) for l in entry.lines.all()
            if l.account.account_type in ("cogs", "expense") and l.debit > 0
        ]
        self.assertIn(1000.0, cogs_debits, msg=f"GL COGS lines: {cogs_debits}")

    def test_valuation_uses_running_average_once_known(self):
        from apps.inventory.services import InventoryService
        p = self._product("average", sku="COST-VAL")
        self._receive(p, 10, "100")
        self._receive(p, 10, "200")
        rows = InventoryService.get_stock_valuation(self.org)
        row = next(r for r in rows if r.product_id == p.id)
        # 20 units at a 150 weighted average = 3000, not 20 × flat cost_price.
        self.assertAlmostEqual(float(row.total_value), 3000.0, places=2)


class BarcodeGenerationTests(TestCase):
    """
    System-generated barcodes (the reviewer's "best practice: system
    generated, not manually entered" request), with manual entry still
    available for products that already have a printed barcode.
    """

    def setUp(self):
        self.user = _make_user("barcode@example.com")
        self.org = _make_org(self.user, "Barcode Org")
        self.client = _auth_client(self.user, self.org)

    def _luhn_style_valid(self, code: str) -> bool:
        """GS1 check-digit validator: recompute the check digit from the base
        and confirm it matches the last digit — proves the code would actually
        scan, not just that it's numeric."""
        base, check = code[:-1], code[-1]
        return Product._gs1_check_digit(base) == check

    def test_ean13_generates_valid_check_digit(self):
        code = Product.generate_barcode(self.org, "ean13")
        self.assertEqual(len(code), 13)
        self.assertTrue(code.isdigit())
        self.assertTrue(self._luhn_style_valid(code), code)

    def test_upc_generates_valid_check_digit(self):
        code = Product.generate_barcode(self.org, "upc")
        self.assertEqual(len(code), 12)
        self.assertTrue(self._luhn_style_valid(code), code)

    def test_ean8_generates_valid_check_digit(self):
        code = Product.generate_barcode(self.org, "ean8")
        self.assertEqual(len(code), 8)
        self.assertTrue(self._luhn_style_valid(code), code)

    def test_code128_generates_alphanumeric_code(self):
        code = Product.generate_barcode(self.org, "code128")
        self.assertTrue(len(code) > 0)

    def test_successive_generated_barcodes_are_unique(self):
        # Sequence only advances once a product with a barcode is actually
        # persisted, so generating in a loop without saving would repeat the
        # same value — this exercises the real API path, which does save.
        res_codes = set()
        for i in range(3):
            res = self.client.post("/api/v1/inventory/products/", {
                "sku": f"BC-API-{i}", "name": f"API Item {i}",
                "cost_price": "10", "selling_price": "20",
            }, format="json")
            self.assertEqual(res.status_code, 201, msg=str(res.data))
            res_codes.add(res.data["barcode"])
        self.assertEqual(len(res_codes), 3, msg=res_codes)

    def test_blank_barcode_auto_generates_on_create(self):
        res = self.client.post("/api/v1/inventory/products/", {
            "sku": "BC-BLANK", "name": "Blank Barcode Item",
            "cost_price": "10", "selling_price": "20",
        }, format="json")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertTrue(res.data["barcode"], "barcode should have been auto-generated")

    def test_manual_barcode_is_not_overwritten(self):
        res = self.client.post("/api/v1/inventory/products/", {
            "sku": "BC-MANUAL", "name": "Manual Barcode Item",
            "cost_price": "10", "selling_price": "20",
            "barcode": "9990001112223",
        }, format="json")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(res.data["barcode"], "9990001112223")

    def test_ean13_requested_symbology_generates_ean13_shape(self):
        res = self.client.post("/api/v1/inventory/products/", {
            "sku": "BC-EAN13", "name": "EAN13 Item",
            "cost_price": "10", "selling_price": "20",
            "barcode_symbology": "ean13",
        }, format="json")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        code = res.data["barcode"]
        self.assertEqual(len(code), 13)
        self.assertTrue(self._luhn_style_valid(code), code)


class ProductImageGalleryTests(TestCase):
    """
    Multi-image product gallery — the reviewer's "Product images gallery /
    Upload one or more images / Click a thumbnail to set the main image /
    Drag to reorder" request. Product.image (the legacy single-image field
    the storefront reads) must stay in sync with whichever image is main.
    """

    # Minimal valid 1×1 transparent PNG — real magic bytes so
    # validate_image_upload's sniffing accepts it, not just a fake string.
    _PNG = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg=="
    )

    def setUp(self):
        self.user = _make_user("gallery@example.com")
        self.org = _make_org(self.user, "Gallery Org")
        self.client = _auth_client(self.user, self.org)
        self.product = Product.objects.create(
            organisation=self.org, sku="GAL-1", name="Gallery Item",
            cost_price=100, selling_price=200,
        )

    def _upload(self, name="photo.png"):
        return SimpleUploadedFile(name, self._PNG, content_type="image/png")

    def _post_image(self, **extra):
        data = {"product": str(self.product.id), "image": self._upload()}
        data.update(extra)
        return self.client.post("/api/v1/inventory/product-images/", data, format="multipart")

    def test_first_uploaded_image_becomes_main_automatically(self):
        res = self._post_image()
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertTrue(res.data["is_main"])
        self.product.refresh_from_db()
        self.assertTrue(bool(self.product.image))

    def test_second_image_is_not_main_by_default(self):
        self._post_image()
        res2 = self._post_image()
        self.assertEqual(res2.status_code, 201, msg=str(res2.data))
        self.assertFalse(res2.data["is_main"])
        self.assertEqual(
            ProductImage.objects.filter(organisation=self.org, product=self.product, is_main=True).count(), 1,
        )

    def test_set_main_switches_cover_and_syncs_product_image(self):
        img1 = self._post_image().data
        img2 = self._post_image().data
        res = self.client.post(f"/api/v1/inventory/product-images/{img2['id']}/set_main/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertTrue(ProductImage.objects.get(id=img2["id"]).is_main)
        self.assertFalse(ProductImage.objects.get(id=img1["id"]).is_main)
        self.product.refresh_from_db()
        self.assertEqual(self.product.image.name, ProductImage.objects.get(id=img2["id"]).image.name)

    def test_reorder_sets_sort_order_from_list_position(self):
        img1 = self._post_image().data
        img2 = self._post_image().data
        img3 = self._post_image().data
        res = self.client.post("/api/v1/inventory/product-images/reorder/", {
            "order": [img3["id"], img1["id"], img2["id"]],
        }, format="json")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(ProductImage.objects.get(id=img3["id"]).sort_order, 0)
        self.assertEqual(ProductImage.objects.get(id=img1["id"]).sort_order, 1)
        self.assertEqual(ProductImage.objects.get(id=img2["id"]).sort_order, 2)

    def test_deleting_main_image_promotes_the_next_one(self):
        img1 = self._post_image().data
        img2 = self._post_image().data
        res = self.client.delete(f"/api/v1/inventory/product-images/{img1['id']}/")
        self.assertIn(res.status_code, (200, 204), msg=str(res.data))
        self.assertTrue(ProductImage.objects.get(id=img2["id"]).is_main)
        self.product.refresh_from_db()
        self.assertEqual(self.product.image.name, ProductImage.objects.get(id=img2["id"]).image.name)

    def test_deleting_the_only_image_clears_product_image(self):
        img1 = self._post_image().data
        self.client.delete(f"/api/v1/inventory/product-images/{img1['id']}/")
        self.product.refresh_from_db()
        self.assertFalse(bool(self.product.image))

    def test_rejects_non_image_upload(self):
        fake = SimpleUploadedFile("not_an_image.png", b"this is not a real png", content_type="image/png")
        res = self.client.post("/api/v1/inventory/product-images/", {
            "product": str(self.product.id), "image": fake,
        }, format="multipart")
        self.assertIn(res.status_code, (400, 422), msg=str(res.data))

    def test_cannot_attach_image_to_another_orgs_product(self):
        other_user = _make_user("gallery_other@example.com")
        other_org = _make_org(other_user, "Other Gallery Org")
        other_product = Product.objects.create(
            organisation=other_org, sku="GAL-OTHER", name="Other Org Item",
            cost_price=100, selling_price=200,
        )
        res = self.client.post("/api/v1/inventory/product-images/", {
            "product": str(other_product.id), "image": self._upload(),
        }, format="multipart")
        self.assertIn(res.status_code, (400, 403, 404), msg=str(res.data))

    def test_product_detail_includes_gallery(self):
        self._post_image()
        self._post_image()
        res = self.client.get(f"/api/v1/inventory/products/{self.product.id}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data["images"]), 2)


class ProductImageRawUploadTests(TestCase):
    """
    POST /inventory/products/<id>/upload-image/ — raw binary body, the same
    Tauri-FormData-workaround pattern as Organisation.upload_logo. This is
    the endpoint the frontend actually calls (works identically on web and
    desktop); the multipart /product-images/ endpoint stays available as a
    generic API path.
    """

    _PNG = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8zwACTGCSAQANHQEDgslx/wAAAABJRU5ErkJggg=="
    )

    def setUp(self):
        self.user = _make_user("rawupload@example.com")
        self.org = _make_org(self.user, "Raw Upload Org")
        self.client = _auth_client(self.user, self.org)
        self.product = Product.objects.create(
            organisation=self.org, sku="RAW-1", name="Raw Upload Item",
            cost_price=100, selling_price=200,
        )

    def test_raw_binary_upload_creates_gallery_image(self):
        res = self.client.post(
            f"/api/v1/inventory/products/{self.product.id}/upload-image/",
            data=self._PNG, content_type="image/png",
        )
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertTrue(res.data["is_main"])
        self.assertEqual(ProductImage.objects.filter(organisation=self.org, product=self.product).count(), 1)
        self.product.refresh_from_db()
        self.assertTrue(bool(self.product.image))

    def test_raw_binary_upload_rejects_non_image(self):
        res = self.client.post(
            f"/api/v1/inventory/products/{self.product.id}/upload-image/",
            data=b"not an image at all", content_type="image/png",
        )
        self.assertEqual(res.status_code, 400, msg=str(res.data))

    def test_second_raw_upload_is_not_main(self):
        self.client.post(
            f"/api/v1/inventory/products/{self.product.id}/upload-image/",
            data=self._PNG, content_type="image/png",
        )
        res2 = self.client.post(
            f"/api/v1/inventory/products/{self.product.id}/upload-image/",
            data=self._PNG, content_type="image/png",
        )
        self.assertEqual(res2.status_code, 201, msg=str(res2.data))
        self.assertFalse(res2.data["is_main"])


class ProductVariantTests(TestCase):
    """
    Variable Products (the reviewer's "Add Variable Product type" request).

    A variant is a normal Product row with parent_product set to a
    product_type=VARIABLE template — this suite checks the template/variant
    relationship, cross-org/self-parent/double-nesting guards, that each
    variant tracks its own independent stock and price, and that the
    template itself can never be sold directly.
    """

    def setUp(self):
        self.user = _make_user("variant@example.com")
        self.org = _make_org(self.user, "Variant Org")
        self.client = _auth_client(self.user, self.org)
        self.wh = _make_warehouse(self.org)
        self.template = Product.objects.create(
            organisation=self.org, sku="TSHIRT", name="T-Shirt",
            product_type=Product.ProductType.VARIABLE,
            cost_price=Decimal("0"), selling_price=Decimal("0"),
        )

    def test_create_variant_links_to_template(self):
        res = self.client.post("/api/v1/inventory/products/", {
            "sku": "TSHIRT-RED-L", "name": "T-Shirt Red/Large",
            "product_type": "physical", "parent_product": str(self.template.id),
            "variant_attributes": {"Size": "Large", "Color": "Red"},
            "cost_price": "1000", "selling_price": "2000",
        }, format="json")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(str(res.data["parent_product"]), str(self.template.id))
        self.assertEqual(res.data["variant_attributes"], {"Size": "Large", "Color": "Red"})

    def test_template_lists_its_variants(self):
        Product.objects.create(
            organisation=self.org, sku="TSHIRT-S", name="T-Shirt Small",
            product_type="physical", parent_product=self.template,
            variant_attributes={"Size": "Small"},
            cost_price=Decimal("1000"), selling_price=Decimal("2000"),
        )
        Product.objects.create(
            organisation=self.org, sku="TSHIRT-L", name="T-Shirt Large",
            product_type="physical", parent_product=self.template,
            variant_attributes={"Size": "Large"},
            cost_price=Decimal("1200"), selling_price=Decimal("2500"),
        )
        res = self.client.get(f"/api/v1/inventory/products/{self.template.id}/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        skus = {v["sku"] for v in res.data["variants"]}
        self.assertEqual(skus, {"TSHIRT-S", "TSHIRT-L"})

    def test_variants_track_independent_stock_and_price(self):
        small = Product.objects.create(
            organisation=self.org, sku="TSHIRT-S2", name="T-Shirt Small",
            product_type="physical", parent_product=self.template,
            cost_price=Decimal("1000"), selling_price=Decimal("2000"),
        )
        large = Product.objects.create(
            organisation=self.org, sku="TSHIRT-L2", name="T-Shirt Large",
            product_type="physical", parent_product=self.template,
            cost_price=Decimal("1200"), selling_price=Decimal("2500"),
        )
        from apps.inventory.services import InventoryService
        InventoryService.record_movement(
            organisation=self.org, product=small, warehouse=self.wh,
            quantity=Decimal("10"), movement_type="purchase_in",
            unit_cost=Decimal("1000"), created_by=self.user,
        )
        InventoryService.record_movement(
            organisation=self.org, product=large, warehouse=self.wh,
            quantity=Decimal("3"), movement_type="purchase_in",
            unit_cost=Decimal("1200"), created_by=self.user,
        )
        self.assertEqual(small.stock_items.get(warehouse=self.wh).quantity_on_hand, Decimal("10"))
        self.assertEqual(large.stock_items.get(warehouse=self.wh).quantity_on_hand, Decimal("3"))
        self.assertNotEqual(small.selling_price, large.selling_price)

    def test_cannot_sell_template_directly(self):
        from apps.customers.models import Customer
        from apps.sales.services import SaleService
        customer = Customer.objects.create(organisation=self.org, code="C1", name="Cust")
        with self.assertRaises(ValueError):
            SaleService.create_sale(
                organisation=self.org, created_by=self.user, customer=customer,
                warehouse=self.wh, payment_method="cash",
                items=[{"product_id": str(self.template.id), "quantity": "1", "unit_price": "100"}],
            )

    def test_variant_cannot_be_its_own_parent(self):
        res = self.client.patch(f"/api/v1/inventory/products/{self.template.id}/", {
            "parent_product": str(self.template.id),
        }, format="json")
        self.assertEqual(res.status_code, 400, msg=str(res.data))

    def test_parent_must_be_variable_type(self):
        physical = Product.objects.create(
            organisation=self.org, sku="PHYS-1", name="Ordinary Product",
            product_type="physical", cost_price=Decimal("10"), selling_price=Decimal("20"),
        )
        res = self.client.post("/api/v1/inventory/products/", {
            "sku": "BAD-VARIANT", "name": "Bad Variant",
            "product_type": "physical", "parent_product": str(physical.id),
            "cost_price": "10", "selling_price": "20",
        }, format="json")
        self.assertEqual(res.status_code, 400, msg=str(res.data))

    def test_variant_of_variant_rejected(self):
        variant = Product.objects.create(
            organisation=self.org, sku="TSHIRT-M", name="T-Shirt Medium",
            product_type="physical", parent_product=self.template,
            cost_price=Decimal("1000"), selling_price=Decimal("2000"),
        )
        res = self.client.post("/api/v1/inventory/products/", {
            "sku": "TSHIRT-M-SUB", "name": "Sub Variant",
            "product_type": "physical", "parent_product": str(variant.id),
            "cost_price": "10", "selling_price": "20",
        }, format="json")
        self.assertEqual(res.status_code, 400, msg=str(res.data))

    def test_cross_org_parent_rejected(self):
        other_user = _make_user("other_variant@example.com")
        other_org = _make_org(other_user, "Other Variant Org")
        other_template = Product.objects.create(
            organisation=other_org, sku="OTHER-TMPL", name="Other Template",
            product_type=Product.ProductType.VARIABLE,
            cost_price=Decimal("0"), selling_price=Decimal("0"),
        )
        res = self.client.post("/api/v1/inventory/products/", {
            "sku": "CROSS-ORG-VAR", "name": "Cross Org Variant",
            "product_type": "physical", "parent_product": str(other_template.id),
            "cost_price": "10", "selling_price": "20",
        }, format="json")
        self.assertEqual(res.status_code, 400, msg=str(res.data))


class ComboProductTests(TestCase):
    """
    Combo/Bundle Products (the reviewer's "Add Combo Product type" request).

    A combo carries no stock of its own; selling one unit deducts each
    bill-of-materials component from ITS OWN stock (quantity x component
    quantity), through the real costing engine, so GL/COGS reuses everything
    built for ordinary sales. These tests assert on actual component stock
    levels and posted cost-of-goods, not just "the sale succeeded".
    """

    def setUp(self):
        from apps.customers.models import Customer
        self.user = _make_user("combo@example.com")
        self.org = _make_org(self.user, "Combo Org")
        self.client = _auth_client(self.user, self.org)
        self.wh = _make_warehouse(self.org)
        self.customer = Customer.objects.create(organisation=self.org, code="C-COMBO", name="Combo Customer")

        self.bun = Product.objects.create(
            organisation=self.org, sku="BUN", name="Bun",
            product_type="physical", cost_price=Decimal("50"), selling_price=Decimal("100"),
        )
        self.patty = Product.objects.create(
            organisation=self.org, sku="PATTY", name="Patty",
            product_type="physical", cost_price=Decimal("200"), selling_price=Decimal("400"),
        )
        self.combo = Product.objects.create(
            organisation=self.org, sku="BURGER-COMBO", name="Burger Combo",
            product_type=Product.ProductType.COMBO,
            cost_price=Decimal("0"), selling_price=Decimal("500"),
        )
        from apps.inventory.services import InventoryService
        InventoryService.record_movement(
            organisation=self.org, product=self.bun, warehouse=self.wh,
            quantity=Decimal("20"), movement_type="purchase_in",
            unit_cost=Decimal("50"), created_by=self.user,
        )
        InventoryService.record_movement(
            organisation=self.org, product=self.patty, warehouse=self.wh,
            quantity=Decimal("20"), movement_type="purchase_in",
            unit_cost=Decimal("200"), created_by=self.user,
        )
        ComboComponent.objects.create(
            organisation=self.org, combo_product=self.combo, component_product=self.bun,
            quantity=Decimal("2"),
        )
        ComboComponent.objects.create(
            organisation=self.org, combo_product=self.combo, component_product=self.patty,
            quantity=Decimal("1"),
        )

    def test_selling_combo_deducts_each_component_stock(self):
        from apps.sales.services import SaleService
        SaleService.create_sale(
            organisation=self.org, created_by=self.user, customer=self.customer,
            warehouse=self.wh, payment_method="cash",
            items=[{"product_id": str(self.combo.id), "quantity": "3", "unit_price": "500"}],
        )
        self.bun.refresh_from_db()
        self.patty.refresh_from_db()
        self.assertEqual(self.bun.stock_items.get(warehouse=self.wh).quantity_on_hand, Decimal("14"))    # 20 - 3*2
        self.assertEqual(self.patty.stock_items.get(warehouse=self.wh).quantity_on_hand, Decimal("17"))  # 20 - 3*1

    def test_combo_cost_of_goods_is_sum_of_component_costs(self):
        from apps.sales.services import SaleService
        invoice = SaleService.create_sale(
            organisation=self.org, created_by=self.user, customer=self.customer,
            warehouse=self.wh, payment_method="cash",
            items=[{"product_id": str(self.combo.id), "quantity": "1", "unit_price": "500"}],
        )
        line = invoice.items.first()
        # 2 buns @ 50 + 1 patty @ 200 = 300 per combo unit
        self.assertEqual(line.cost_of_goods, Decimal("300.0000"))

    def test_combo_has_no_stock_item_of_its_own(self):
        self.assertFalse(self.combo.stock_items.exists())

    def test_insufficient_component_stock_blocks_the_sale(self):
        from apps.sales.services import SaleService
        with self.assertRaises(ValueError):
            SaleService.create_sale(
                organisation=self.org, created_by=self.user, customer=self.customer,
                warehouse=self.wh, payment_method="cash",
                items=[{"product_id": str(self.combo.id), "quantity": "50", "unit_price": "500"}],
            )
        # Nothing should have been deducted — the whole sale is one atomic transaction.
        self.bun.refresh_from_db()
        self.assertEqual(self.bun.stock_items.get(warehouse=self.wh).quantity_on_hand, Decimal("20"))

    def test_combo_cannot_contain_itself(self):
        res = self.client.post("/api/v1/inventory/combo-components/", {
            "combo_product": str(self.combo.id), "component_product": str(self.combo.id),
            "quantity": "1",
        }, format="json")
        self.assertEqual(res.status_code, 400, msg=str(res.data))

    def test_combo_cannot_contain_another_combo(self):
        other_combo = Product.objects.create(
            organisation=self.org, sku="OTHER-COMBO", name="Other Combo",
            product_type=Product.ProductType.COMBO,
            cost_price=Decimal("0"), selling_price=Decimal("100"),
        )
        res = self.client.post("/api/v1/inventory/combo-components/", {
            "combo_product": str(self.combo.id), "component_product": str(other_combo.id),
            "quantity": "1",
        }, format="json")
        self.assertEqual(res.status_code, 400, msg=str(res.data))

    def test_cross_org_component_rejected(self):
        other_user = _make_user("other_combo@example.com")
        other_org = _make_org(other_user, "Other Combo Org")
        other_product = Product.objects.create(
            organisation=other_org, sku="OTHER-ITEM", name="Other Item",
            product_type="physical", cost_price=Decimal("10"), selling_price=Decimal("20"),
        )
        res = self.client.post("/api/v1/inventory/combo-components/", {
            "combo_product": str(self.combo.id), "component_product": str(other_product.id),
            "quantity": "1",
        }, format="json")
        self.assertEqual(res.status_code, 400, msg=str(res.data))

    def test_zero_quantity_component_rejected(self):
        res = self.client.post("/api/v1/inventory/combo-components/", {
            "combo_product": str(self.combo.id), "component_product": str(self.bun.id),
            "quantity": "0",
        }, format="json")
        self.assertEqual(res.status_code, 400, msg=str(res.data))

    def test_get_product_detail_lists_combo_components(self):
        res = self.client.get(f"/api/v1/inventory/products/{self.combo.id}/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        skus = {c["component_product_sku"] for c in res.data["combo_components"]}
        self.assertEqual(skus, {"BUN", "PATTY"})
