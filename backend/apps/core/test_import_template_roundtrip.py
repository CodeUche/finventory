"""
Import-template round trip: the move every new user makes, pinned as a
regression suite.

A reviewer learning the CSV format does exactly one thing: download the
template the app offers for an entity, look at the sample rows, and upload the
file back unchanged to see it work. Every template we ship must therefore
import cleanly into a brand-new organisation, and must produce the records its
sample rows claim to describe. Four confirmed bugs are pinned here:

1. Sample rows shorter than their own column list. ImportTemplateView pads a
   short row with blanks, so every value after the gap lands one column to the
   left of where it belongs and imports as the wrong field. The structural
   guard below catches this for every entity at once, with no database, the
   moment a column is added without updating its sample row.
2. Suppliers duplicating on re-import. A blank `code` in a sample row mints a
   fresh random code and then matches on it, so the record is never found again
   and a second import creates a second copy, reported as a clean `created: 1`.
3. The purchase-orders template not standing alone. Its rows name a supplier, a
   warehouse and two SKUs that only exist once the suppliers and products
   templates have been imported. That ordering is part of the contract, so it
   is written out explicitly in ENTITY_IMPORT_ORDER rather than left implicit.
4. Create-only skips reported as errors. Re-importing budgets or purchase
   orders is correct behaviour and must not come back in the `errors` array;
   the skipped rows belong in a separate `skipped` list.

The template bytes are never hand-copied here: every test downloads through
the real endpoint and posts the exact bytes back, so the suite keeps testing
what we actually ship rather than a copy that can drift from it.
"""

import pytest

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.models import Account
from apps.accounting.tests import _upgrade_to_business
from apps.authentication.models import User
from apps.budgets.models import Budget
from apps.core.import_views import SAMPLE_ROWS, TEMPLATES
from apps.customers.models import Customer
from apps.inventory.models import Product, StockItem, Warehouse
from apps.payroll.models import Employee
from apps.purchases.models import PurchaseOrder
from apps.suppliers.models import Supplier
from apps.tenancy.services import OrganisationService


def _make_user(email="template_roundtrip@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Template", last_name="Importer", is_verified=True,
    )


def _make_org(user, name="Template Round Trip Org"):
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


def _csv_file(text: str, name="template.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


# The order a new organisation must import these in, and the reason for it:
# purchase_orders rows reference a supplier by name ("ABC Distributors Ltd",
# from the suppliers template), a warehouse by name ("Main Warehouse", created
# by the products template's opening-stock column) and two SKUs (SKU001 and
# SKU002, from the products template). Suppliers and products therefore have to
# land first. Nothing else in the set depends on anything, so the remaining
# entities keep their natural reading order.
ENTITY_IMPORT_ORDER = [
    "accounts",
    "customers",
    "suppliers",        # must precede purchase_orders (supplier_name lookup)
    "employees",
    "products",         # must precede purchase_orders (product_sku + warehouse)
    "purchase_orders",
    "budgets",
]

# Every entity the template endpoint serves. Guards the import order above
# against a new entity being added to TEMPLATES and silently left untested.
ALL_ENTITIES = sorted(TEMPLATES.keys())


class _TemplateRoundTripMixin:
    """Download-and-re-upload helpers shared by the database-backed tests."""

    def _template_bytes(self, entity):
        res = self.client.get(f"/api/v1/import/template/{entity}/")
        self.assertEqual(
            res.status_code, 200,
            msg=f"template download for '{entity}' returned {res.status_code}",
        )
        return res.content.decode("utf-8")

    def _upload(self, entity, text):
        return self.client.post(
            f"/api/v1/import/{entity}/",
            {"file": _csv_file(text, name=f"{entity}.csv")},
            format="multipart",
        )

    def _round_trip(self, entity):
        """GET the template, POST those exact bytes back, return the response."""
        return self._upload(entity, self._template_bytes(entity))


@pytest.mark.unit
class ImportTemplateStructureTests(SimpleTestCase):
    """
    Pure-logic guard, no database: every sample row must have exactly one value
    per column of its own entity.

    ImportTemplateView pads a short row out with empty strings, which means a
    sample row that is one value short does not fail loudly: it writes a CSV
    whose values are all shifted one column left of their headers, and the
    import then saves perfectly plausible-looking rubbish. This is the cheapest
    test in the suite and the one that catches the whole class of bug: add a
    column to an entity, forget its sample row, and this goes red immediately.
    """

    def test_every_sample_row_matches_its_column_count(self):
        for entity in ALL_ENTITIES:
            columns = TEMPLATES[entity]
            for row_number, row in enumerate(SAMPLE_ROWS.get(entity, []), start=1):
                with self.subTest(entity=entity, sample_row=row_number):
                    self.assertEqual(
                        len(row), len(columns),
                        msg=(
                            f"'{entity}' sample row {row_number} has {len(row)} "
                            f"values but the entity has {len(columns)} columns. "
                            f"columns={columns} row={row}. A short row is padded "
                            f"with blanks on download, so every value after the "
                            f"gap imports into the wrong field."
                        ),
                    )

    def test_every_entity_ships_at_least_one_sample_row(self):
        """A template with no sample row teaches a new user nothing."""
        for entity in ALL_ENTITIES:
            with self.subTest(entity=entity):
                self.assertTrue(
                    SAMPLE_ROWS.get(entity),
                    msg=f"'{entity}' template ships no sample rows",
                )

    def test_import_order_covers_every_template_entity(self):
        """
        Keeps ENTITY_IMPORT_ORDER honest: a new entity added to TEMPLATES has
        to be placed in the documented order, not quietly skipped by the round
        trip test below.
        """
        self.assertEqual(
            sorted(ENTITY_IMPORT_ORDER), ALL_ENTITIES,
            msg=(
                f"ENTITY_IMPORT_ORDER={ENTITY_IMPORT_ORDER} does not cover "
                f"TEMPLATES={ALL_ENTITIES}"
            ),
        )


@pytest.mark.api
class ImportTemplateRoundTripTests(_TemplateRoundTripMixin, TestCase):
    """
    The reviewer's exact action, for all seven entities: download the template,
    upload it straight back, expect no errors.
    """

    def setUp(self):
        self.user = _make_user("roundtrip_owner@example.com")
        self.org = _make_org(self.user, "Round Trip Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_every_template_imports_itself_without_errors(self):
        # Imported into ONE organisation, in ENTITY_IMPORT_ORDER, because that
        # dependency order is itself part of the contract being tested.
        #
        # Every entity is uploaded before anything is asserted, and the failure
        # message below names each broken entity and dumps its whole response.
        # Stopping at the first bad template would hide the rest, and whoever
        # fixes this needs the full picture, not one error at a time.
        problems = []
        for entity in ENTITY_IMPORT_ORDER:
            res = self._round_trip(entity)
            if res.status_code != 200:
                problems.append(
                    f"  '{entity}': upload returned HTTP {res.status_code}, "
                    f"response={dict(res.data)}"
                )
                continue
            if res.data.get("errors"):
                problems.append(
                    f"  '{entity}': errors={res.data['errors']} "
                    f"full response={dict(res.data)}"
                )

        self.assertEqual(
            problems, [],
            msg=(
                "these templates do not import themselves cleanly "
                f"(imported in order {ENTITY_IMPORT_ORDER}):\n"
                + "\n".join(problems)
            ),
        )

    def test_every_template_creates_the_rows_it_describes(self):
        """A clean response is worthless if nothing was written."""
        row_counts = {
            "accounts": lambda: Account.objects.filter(organisation=self.org).count(),
            "customers": lambda: Customer.objects.filter(organisation=self.org).count(),
            "suppliers": lambda: Supplier.objects.filter(organisation=self.org).count(),
            "employees": lambda: Employee.objects.filter(organisation=self.org).count(),
            "products": lambda: Product.objects.filter(organisation=self.org).count(),
            "purchase_orders": lambda: PurchaseOrder.objects.filter(organisation=self.org).count(),
            "budgets": lambda: Budget.objects.filter(organisation=self.org).count(),
        }
        for entity in ENTITY_IMPORT_ORDER:
            with self.subTest(entity=entity):
                before = row_counts[entity]()
                res = self._round_trip(entity)
                after = row_counts[entity]()
                self.assertGreater(
                    after, before,
                    msg=(
                        f"'{entity}' template import wrote no new rows "
                        f"(count stayed at {before}). response={dict(res.data)}"
                    ),
                )


@pytest.mark.integration
class ProductTemplateSemanticsTests(_TemplateRoundTripMixin, TestCase):
    """
    What actually landed, field by field, after round-tripping the products
    template.

    An empty `errors` list is not proof of a correct import. With the sample
    rows one value short, the shifted products still save: `product_type` picks
    up the category name, falls outside PRODUCT_TYPES and is silently defaulted
    to "physical"; `unit_of_measure` picks up the brand and defaults to "unit";
    the warehouse column receives the reorder level, so a warehouse named "24"
    is created; and the 24 units of opening stock fall off the end of the row
    entirely. Every one of those is asserted below against the value the sample
    row visibly promises.
    """

    def setUp(self):
        self.user = _make_user("product_semantics@example.com")
        self.org = _make_org(self.user, "Product Semantics Org")
        self.client = _auth_client(self.user, self.org)

    def test_products_template_saves_the_values_its_sample_row_shows(self):
        res = self._round_trip("products")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(
            res.data.get("errors"), [],
            msg=f"products template import reported errors: {res.data.get('errors')}",
        )

        # Row 1: a physical product, sold by the bottle, with opening stock.
        physical = Product.objects.get(organisation=self.org, sku="SKU001")
        self.assertEqual(physical.product_type, "physical", msg=f"SKU001 product_type={physical.product_type}")
        self.assertEqual(physical.unit_of_measure, "bottle", msg=f"SKU001 unit_of_measure={physical.unit_of_measure}")
        self.assertIsNotNone(physical.category, msg="SKU001 has no category")
        self.assertEqual(physical.category.name, "Cognac", msg=f"SKU001 category={physical.category.name}")
        self.assertEqual(physical.brand, "Hennessy", msg=f"SKU001 brand={physical.brand!r}")
        self.assertGreater(
            physical.wholesale_price, 0,
            msg=f"SKU001 wholesale_price={physical.wholesale_price} (sample row shows a real price)",
        )
        self.assertEqual(
            physical.description, "",
            msg=f"SKU001 description={physical.description!r} (sample row leaves it blank)",
        )

        # Opening stock: 24 units, in "Main Warehouse", from that same row.
        warehouse = Warehouse.objects.get(organisation=self.org, name="Main Warehouse")
        stock = StockItem.objects.get(organisation=self.org, product=physical, warehouse=warehouse)
        self.assertAlmostEqual(
            float(stock.quantity_on_hand), 24.0, places=2,
            msg=f"SKU001 opening stock in Main Warehouse = {stock.quantity_on_hand}, expected 24",
        )

        # Row 2: a service, sold by the hour, with no stock of any kind.
        service = Product.objects.get(organisation=self.org, sku="SKU002")
        self.assertEqual(service.product_type, "service", msg=f"SKU002 product_type={service.product_type}")
        self.assertEqual(service.unit_of_measure, "hour", msg=f"SKU002 unit_of_measure={service.unit_of_measure}")
        self.assertFalse(
            StockItem.objects.filter(organisation=self.org, product=service).exists(),
            msg="SKU002 is a service and must not have a stock row",
        )

    def test_products_template_creates_no_warehouse_named_after_a_number(self):
        """
        The shifted row puts the reorder level ("24") in the warehouse column,
        so the import creates a warehouse literally named "24". all_objects, so
        a soft-deleted one still counts as the bug.
        """
        self._round_trip("products")
        junk = list(
            Warehouse.all_objects.filter(organisation=self.org).values_list("name", flat=True)
        )
        self.assertNotIn(
            "24", junk,
            msg=f"a warehouse named '24' was created from the reorder level. warehouses={junk}",
        )


@pytest.mark.integration
class ImportTemplateReimportTests(_TemplateRoundTripMixin, TestCase):
    """
    Importing the same template twice must not grow the books.

    A new user re-uploads the same file constantly: to fix a typo, because they
    are not sure the first upload worked, or because they simply try again. The
    importers match on a natural key for exactly that reason, and this test
    pins the result: record counts are identical after the second import, and
    opening stock stays at the quantity on the row instead of doubling.
    """

    def setUp(self):
        self.user = _make_user("reimport_owner@example.com")
        self.org = _make_org(self.user, "Reimport Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def _counts(self):
        return {
            "accounts": Account.objects.filter(organisation=self.org).count(),
            "customers": Customer.objects.filter(organisation=self.org).count(),
            "suppliers": Supplier.objects.filter(organisation=self.org).count(),
            "employees": Employee.objects.filter(organisation=self.org).count(),
            "products": Product.objects.filter(organisation=self.org).count(),
            "purchase_orders": PurchaseOrder.objects.filter(organisation=self.org).count(),
            "budgets": Budget.objects.filter(organisation=self.org).count(),
            "warehouses": Warehouse.objects.filter(organisation=self.org).count(),
        }

    def _import_all(self):
        """Import every template once, in the documented dependency order."""
        return {entity: self._round_trip(entity) for entity in ENTITY_IMPORT_ORDER}

    def test_second_import_of_every_template_creates_no_duplicates(self):
        self._import_all()
        after_first = self._counts()
        self._import_all()
        after_second = self._counts()

        for key, first in after_first.items():
            with self.subTest(records=key):
                self.assertEqual(
                    after_second[key], first,
                    msg=(
                        f"{key} grew from {first} to {after_second[key]} on the "
                        f"second import of the same templates"
                    ),
                )

    def test_supplier_with_a_blank_code_is_not_duplicated(self):
        """
        Sample row 2 of the suppliers template leaves `code` blank. A blank code
        is filled with a fresh random code and then used as the match key, so
        the row is never found again and every re-import adds another copy.
        """
        self._round_trip("suppliers")
        self._round_trip("suppliers")

        kobo = Supplier.objects.filter(
            organisation=self.org, name="Kobo Trading & Services Ltd"
        )
        self.assertEqual(
            kobo.count(), 1,
            msg=(
                "the blank-code supplier sample row duplicated on re-import. "
                f"suppliers now = "
                f"{sorted(Supplier.objects.filter(organisation=self.org).values_list('name', 'code'))}"
            ),
        )
        self.assertEqual(
            Supplier.objects.filter(organisation=self.org).count(), 2,
            msg="the suppliers template ships two rows and must stay at two suppliers",
        )

    def test_opening_stock_is_not_double_counted_on_re_import(self):
        """
        Already-correct behaviour, kept correct: opening stock posts as a
        take-on balance scoped to product plus warehouse, so a re-import
        corrects it in place rather than adding the quantity a second time.
        """
        self._round_trip("products")
        self._round_trip("products")

        product = Product.objects.get(organisation=self.org, sku="SKU001")
        stock = StockItem.objects.filter(organisation=self.org, product=product)
        self.assertEqual(
            stock.count(), 1,
            msg=f"SKU001 has {stock.count()} stock rows after two imports, expected 1",
        )
        self.assertAlmostEqual(
            float(stock.first().quantity_on_hand), 24.0, places=2,
            msg=(
                f"SKU001 opening stock = {stock.first().quantity_on_hand} after two "
                f"imports of the same file, expected 24 (48 means it was added twice)"
            ),
        )


@pytest.mark.integration
class CreateOnlySkipReportingTests(_TemplateRoundTripMixin, TestCase):
    """
    Create-only importers must report a skipped row as skipped, not as an
    error.

    Budgets and purchase orders are deliberately create-only: both have their
    own edit screens, and rewriting one from a re-imported file could clobber
    work in progress. Leaving an existing record alone is therefore the correct
    outcome, and the response must say so. Putting "already exists, skipping
    this row" in `errors` paints correct behaviour red in the UI and trains the
    user to distrust the importer.

    `skipped` carries the same item shape as `errors`: row, field, message.
    """

    SKIP_ENTITIES = ["budgets", "purchase_orders"]

    def setUp(self):
        self.user = _make_user("skip_reporting@example.com")
        self.org = _make_org(self.user, "Skip Reporting Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        # purchase_orders needs its suppliers, products and warehouse first.
        for entity in ("suppliers", "products"):
            self._round_trip(entity)

    def test_second_import_reports_skips_in_skipped_not_errors(self):
        for entity in self.SKIP_ENTITIES:
            with self.subTest(entity=entity):
                first = self._round_trip(entity)
                self.assertEqual(
                    first.data.get("errors"), [],
                    msg=f"first '{entity}' import already reported errors: {dict(first.data)}",
                )

                second = self._round_trip(entity)
                self.assertEqual(second.status_code, 200, msg=str(second.data))
                self.assertEqual(
                    second.data.get("errors"), [],
                    msg=(
                        f"re-importing '{entity}' reported create-only skips as "
                        f"errors: {second.data.get('errors')}"
                    ),
                )

                skipped = second.data.get("skipped")
                self.assertIsNotNone(
                    skipped,
                    msg=(
                        f"re-importing '{entity}' returned no 'skipped' list. "
                        f"response={dict(second.data)}"
                    ),
                )
                self.assertTrue(
                    skipped,
                    msg=f"re-importing '{entity}' skipped nothing, so nothing was reported",
                )
                for item in skipped:
                    self.assertEqual(
                        sorted(item.keys()), ["field", "message", "row"],
                        msg=f"'{entity}' skipped item has unexpected shape: {item}",
                    )
                self.assertTrue(
                    all("already exists" in item["message"] for item in skipped),
                    msg=f"'{entity}' skipped messages do not explain the skip: {skipped}",
                )

    def test_rows_skipped_on_re_import_are_not_counted_as_created(self):
        for entity in self.SKIP_ENTITIES:
            with self.subTest(entity=entity):
                self._round_trip(entity)
                second = self._round_trip(entity)
                self.assertEqual(
                    second.data.get("created"), 0,
                    msg=(
                        f"re-importing '{entity}' reported "
                        f"created={second.data.get('created')}, expected 0"
                    ),
                )
