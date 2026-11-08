"""
The sample rows that ship inside each CSV import template must themselves
import cleanly.

An app reviewer downloaded every template, uploaded each one straight back
unchanged, and got errors. That round trip is exactly what a new user does to
learn the format, so it is the contract these tests hold:

  1. Every sample row carries one value per template column. The products
     template was short by one value, so every value after cost_price landed in
     the wrong column: a warehouse literally named "24" was created and the 24
     units of opening stock never landed.
  2. Re-importing the suppliers template does not duplicate anything. A blank
     `code` used to mint a fresh random code and match on it, so every re-run
     created another copy of the same supplier with no warning at all.
  3. The purchase-order template works on a brand new organisation once
     suppliers and products are in: a missing warehouse is created by name
     instead of failing every row.
  4. Create-only importers (purchase orders, budgets) report an
     already-present record under "skipped", not "errors".
"""

from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.tests import _upgrade_to_business
from apps.authentication.models import User
from apps.core.import_views import TEMPLATES, _validate_sample_rows
from apps.inventory.models import StockItem, Warehouse
from apps.purchases.models import PurchaseOrder
from apps.suppliers.models import Supplier
from apps.tenancy.services import OrganisationService

ENTITIES = [
    "products", "customers", "suppliers", "accounts",
    "employees", "purchase_orders", "budgets",
]

# The dependency order the Import page now spells out: suppliers and products
# before purchase orders. Within that order every template stands on its own.
IMPORT_ORDER = [
    "accounts", "customers", "suppliers", "products",
    "employees", "purchase_orders", "budgets",
]


class SampleRowShapeTests(TestCase):
    """No DB needed: pure checks on the shipped sample data."""

    def test_every_sample_row_has_one_value_per_column(self):
        self.assertEqual(_validate_sample_rows(), [])

    def test_products_sample_includes_wholesale_price(self):
        """Regression guard for the exact off-by-one-column bug."""
        from apps.core.import_views import SAMPLE_ROWS

        columns = TEMPLATES["products"]
        idx = columns.index("wholesale_price")
        row = SAMPLE_ROWS["products"][0]
        self.assertEqual(len(row), len(columns))
        self.assertEqual(row[idx], "5000.00")
        self.assertEqual(row[columns.index("product_type")], "physical")
        self.assertEqual(row[columns.index("warehouse")], "Main Warehouse")
        self.assertEqual(row[columns.index("opening_stock")], "24")


class TemplateRoundTripTests(TestCase):
    """Download each template, upload it straight back, expect no errors."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="template_roundtrip@example.com", password="TestPass123!",
            first_name="Round", last_name="Trip", is_verified=True,
        )
        self.org = OrganisationService.create_organisation(
            name="Round Trip Org", owner=self.user,
            extra={"currency": "NGN", "country": "NG"},
        )
        _upgrade_to_business(self.org)
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {str(RefreshToken.for_user(self.user).access_token)}",
            HTTP_X_ORGANISATION_ID=str(self.org.id),
        )

    def _template(self, entity):
        res = self.client.get(f"/api/v1/import/template/{entity}/")
        self.assertEqual(res.status_code, 200, msg=f"{entity}: {res.content[:200]}")
        return res.content.decode("utf-8")

    def _upload(self, entity, body):
        upload = SimpleUploadedFile(
            f"{entity}.csv", body.encode("utf-8"), content_type="text/csv",
        )
        res = self.client.post(
            f"/api/v1/import/{entity}/", {"file": upload}, format="multipart",
        )
        self.assertEqual(res.status_code, 200, msg=f"{entity}: {res.data}")
        return res.data

    def test_a_short_sample_row_is_loud_instead_of_silently_padded(self):
        """
        Silent padding is what hid the products bug for months: the endpoint
        quietly filled the gap at the END of the row, so the download looked
        fine and only the re-upload failed. Under DEBUG or in tests this is now
        a hard error, so a developer who adds a column cannot miss it.
        """
        from unittest import mock

        from apps.core import import_views

        short = dict(import_views.SAMPLE_ROWS)
        short["accounts"] = [["6000", "Office Supplies", "expense"]]  # 3 of 4
        with mock.patch.object(import_views, "SAMPLE_ROWS", short):
            self.assertTrue(
                any("accounts" in p for p in import_views._validate_sample_rows()),
                msg="_validate_sample_rows did not spot a short row",
            )
            # The endpoint refuses rather than serving a column-shifted file.
            # It raises ImproperlyConfigured, which the test client reports as
            # a 500: impossible to ignore, which is exactly the point.
            self.assertEqual(
                self.client.get("/api/v1/import/template/accounts/").status_code, 500,
            )

    def test_every_template_round_trips_without_errors(self):
        for entity in IMPORT_ORDER:
            with self.subTest(entity=entity):
                data = self._upload(entity, self._template(entity))
                self.assertEqual(
                    data["errors"], [],
                    msg=f"{entity} template cannot be re-imported: {data['errors']}",
                )

    def test_products_template_creates_main_warehouse_and_lands_its_stock(self):
        data = self._upload("products", self._template("products"))
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["created"], 2)
        self.assertEqual(data["warehouses_created"], 1)
        self.assertEqual(data["stock_assigned"], 1)

        warehouse = Warehouse.objects.get(organisation=self.org)
        self.assertEqual(warehouse.name, "Main Warehouse")

        stock = StockItem.objects.get(product__organisation=self.org, product__sku="SKU001")
        self.assertEqual(Decimal(str(stock.quantity_on_hand)), Decimal("24"))
        self.assertEqual(stock.warehouse_id, warehouse.id)

        # And the fields that used to be shifted one column left:
        from apps.inventory.models import Product
        product = Product.objects.get(organisation=self.org, sku="SKU001")
        self.assertEqual(product.product_type, "physical")
        self.assertEqual(product.unit_of_measure, "bottle")
        self.assertEqual(Decimal(str(product.wholesale_price)), Decimal("5000.00"))
        self.assertEqual(product.category.name, "Cognac")
        self.assertEqual(product.brand, "Hennessy")
        self.assertEqual(product.description, "")

    def test_one_new_warehouse_across_many_rows_is_counted_once(self):
        """The reported count must be warehouses created, not rows that named one."""
        data = self._upload("products", (
            "sku,name,cost_price,product_type,warehouse,opening_stock\n"
            "W-1,Widget,100,physical,Ikeja Depot,5\n"
            "W-2,Gadget,200,physical,Ikeja Depot,7\n"
        ))
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["warehouses_created"], 1)
        self.assertEqual(Warehouse.objects.filter(organisation=self.org).count(), 1)

    def test_re_importing_every_template_creates_no_duplicates(self):
        first = {e: self._upload(e, self._template(e)) for e in IMPORT_ORDER}
        counts = self._record_counts()

        second = {e: self._upload(e, self._template(e)) for e in IMPORT_ORDER}
        self.assertEqual(counts, self._record_counts())

        for entity in IMPORT_ORDER:
            with self.subTest(entity=entity):
                self.assertEqual(second[entity]["errors"], [])
                # Nothing new on the second pass, by whichever route the
                # importer takes (update in place, or an intended skip).
                self.assertEqual(
                    second[entity]["created"], 0,
                    msg=f"{entity} created records on a second identical import",
                )
        # Opening stock must not double on re-import.
        stock = StockItem.objects.get(product__organisation=self.org, product__sku="SKU001")
        self.assertEqual(Decimal(str(stock.quantity_on_hand)), Decimal("24"))
        self.assertEqual(first["suppliers"]["created"], 2)

    def _record_counts(self):
        from apps.accounting.models import Account
        from apps.budgets.models import Budget
        from apps.customers.models import Customer
        from apps.inventory.models import Product
        from apps.payroll.models import Employee

        org = self.org
        return {
            "products": Product.objects.filter(organisation=org).count(),
            "customers": Customer.objects.filter(organisation=org).count(),
            "suppliers": Supplier.objects.filter(organisation=org).count(),
            "accounts": Account.objects.filter(organisation=org).count(),
            "employees": Employee.objects.filter(organisation=org).count(),
            "purchase_orders": PurchaseOrder.objects.filter(organisation=org).count(),
            "budgets": Budget.objects.filter(organisation=org).count(),
            "warehouses": Warehouse.objects.filter(organisation=org).count(),
        }

    # ----------------------------------------------------------- bug 2 ----

    def test_blank_code_matches_an_existing_supplier_by_name(self):
        body = (
            "name,code,contact_person\n"
            "Kobo Trading & Services Ltd,,Chinedu Okoro\n"
        )
        first = self._upload("suppliers", body)
        self.assertEqual(first["created"], 1)

        for _ in range(2):
            again = self._upload("suppliers", body)
            self.assertEqual(again["created"], 0)
            self.assertEqual(again["updated"], 1)
            self.assertEqual(again["errors"], [])

        matches = Supplier.objects.filter(
            organisation=self.org, name="Kobo Trading & Services Ltd",
        )
        self.assertEqual(matches.count(), 1)
        # A genuinely new supplier still gets the SupplierSerializer code scheme.
        self.assertRegex(matches.first().code, r"^KOB-[0-9A-F]{6}$")

    def test_blank_code_revives_a_soft_deleted_supplier_instead_of_duplicating(self):
        # Two filled cells minimum: _parse_csv treats a row with fewer than
        # two non-empty cells as a blank/section line and drops it.
        body = "name,code,phone\nKobo Trading & Services Ltd,,08087654321\n"
        self._upload("suppliers", body)
        supplier = Supplier.objects.get(organisation=self.org)
        supplier.delete()  # soft delete
        self.assertFalse(Supplier.objects.filter(organisation=self.org).exists())

        self._upload("suppliers", body)
        self.assertEqual(Supplier.objects.filter(organisation=self.org).count(), 1)
        self.assertEqual(Supplier.all_objects.filter(organisation=self.org).count(), 1)

    def test_customers_import_does_not_have_the_blank_code_hole(self):
        """`code` is required for customers, so a blank one is a clear error."""
        body = "code,name,phone\n,Adaeze Okafor,08012345678\n"
        data = self._upload("customers", body)
        self.assertEqual(data["created"], 0)
        self.assertTrue(any(e["field"] == "code" for e in data["errors"]))

        from apps.customers.models import Customer
        self.assertFalse(Customer.objects.filter(organisation=self.org).exists())

    def test_customers_re_import_matches_on_code_and_does_not_duplicate(self):
        body = self._template("customers")
        self._upload("customers", body)
        second = self._upload("customers", body)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["updated"], 2)

        from apps.customers.models import Customer
        self.assertEqual(Customer.objects.filter(organisation=self.org).count(), 2)

    # ----------------------------------------------------------- bug 3 ----

    def test_purchase_order_import_creates_a_missing_warehouse(self):
        self._upload("suppliers", self._template("suppliers"))
        # Products with no warehouse column, so the organisation still has no
        # warehouse at all when the purchase orders arrive. That is the state a
        # brand new organisation is in, and it used to fail every PO row.
        self._upload("products", (
            "sku,name,selling_price,cost_price,product_type\n"
            "SKU001,Hennessy VS 750ml,5500.00,3200.00,physical\n"
            "SKU002,Delivery Service,2000.00,0.00,service\n"
        ))
        self.assertFalse(Warehouse.objects.filter(organisation=self.org).exists())

        data = self._upload("purchase_orders", self._template("purchase_orders"))
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["purchase_orders_created"], 2)
        self.assertEqual(data["lines_created"], 3)
        self.assertEqual(data["warehouses_created"], 1)
        self.assertEqual(
            Warehouse.objects.get(organisation=self.org).name, "Main Warehouse",
        )

    def test_purchase_order_import_still_rejects_unknown_suppliers_and_skus(self):
        """A warehouse can be invented. A supplier or a product cannot."""
        body = (
            "po_number,supplier_name,warehouse_name,order_date,product_sku,quantity,unit_cost\n"
            "PO-X,Nobody Ltd,Brand New Warehouse,2026-01-10,NOPE,1,100\n"
        )
        data = self._upload("purchase_orders", body)
        self.assertEqual(data["purchase_orders_created"], 0)
        self.assertTrue(any(e["field"] == "supplier_name" for e in data["errors"]))
        # Nothing written at all, including the warehouse the row asked for.
        self.assertFalse(
            Warehouse.objects.filter(organisation=self.org, name="Brand New Warehouse").exists()
        )

    # ----------------------------------------------------------- bug 4 ----

    def test_re_importing_purchase_orders_reports_skipped_not_errors(self):
        self._upload("suppliers", self._template("suppliers"))
        self._upload("products", self._template("products"))
        body = self._template("purchase_orders")
        self._upload("purchase_orders", body)

        again = self._upload("purchase_orders", body)
        self.assertEqual(again["errors"], [])
        self.assertEqual(len(again["skipped"]), 3)
        self.assertEqual(again["purchase_orders_created"], 0)
        for item in again["skipped"]:
            self.assertEqual(item["field"], "po_number")
            self.assertIn("row", item)
            self.assertIn("message", item)
        self.assertEqual(PurchaseOrder.objects.filter(organisation=self.org).count(), 2)

    def test_re_importing_budgets_reports_skipped_not_errors(self):
        body = self._template("budgets")
        self._upload("budgets", body)

        again = self._upload("budgets", body)
        self.assertEqual(again["errors"], [])
        self.assertEqual(len(again["skipped"]), 3)
        self.assertEqual(again["budgets_created"], 0)
        for item in again["skipped"]:
            self.assertEqual(item["field"], "budget_name")

        from apps.budgets.models import Budget
        self.assertEqual(Budget.objects.filter(organisation=self.org).count(), 2)

    def test_every_importer_returns_a_skipped_list(self):
        """One response shape, so the UI never has to guess."""
        for entity in IMPORT_ORDER:
            with self.subTest(entity=entity):
                data = self._upload(entity, self._template(entity))
                self.assertIn("skipped", data)
                self.assertIsInstance(data["skipped"], list)


class TemplateTenantIsolationTests(TestCase):
    """A template import must never reach into another organisation."""

    def test_a_second_org_sees_none_of_the_first_orgs_imported_rows(self):
        user_a = User.objects.create_user(
            email="tpl_org_a@example.com", password="TestPass123!",
            first_name="A", last_name="Org", is_verified=True,
        )
        org_a = OrganisationService.create_organisation(
            name="Template Org A", owner=user_a,
            extra={"currency": "NGN", "country": "NG"},
        )
        _upgrade_to_business(org_a)
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {str(RefreshToken.for_user(user_a).access_token)}",
            HTTP_X_ORGANISATION_ID=str(org_a.id),
        )
        for entity in IMPORT_ORDER:
            body = client.get(f"/api/v1/import/template/{entity}/").content
            client.post(
                f"/api/v1/import/{entity}/",
                {"file": SimpleUploadedFile(f"{entity}.csv", body, content_type="text/csv")},
                format="multipart",
            )

        user_b = User.objects.create_user(
            email="tpl_org_b@example.com", password="TestPass123!",
            first_name="B", last_name="Org", is_verified=True,
        )
        org_b = OrganisationService.create_organisation(
            name="Template Org B", owner=user_b,
            extra={"currency": "NGN", "country": "NG"},
        )
        self.assertFalse(Supplier.objects.filter(organisation=org_b).exists())
        self.assertFalse(PurchaseOrder.objects.filter(organisation=org_b).exists())
        self.assertFalse(
            Warehouse.objects.filter(organisation=org_b, name="Main Warehouse").exists()
        )
