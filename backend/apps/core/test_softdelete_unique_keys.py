"""Soft delete must not reserve a natural key forever — and must still stop
genuine duplicates.

Every model here soft-deletes, so the row survives deletion. With a plain
unique_together the database kept counting that dead row: deleting a product
reserved its SKU permanently, deleting a customer burned their code, and an
employee number could never be reused after someone left. The API answered
"already exists" about a record the user could no longer see anywhere, with no
way back from the UI.

The constraints are now conditional on is_deleted=False, so both halves have to
hold: a deleted key can be reused, and a LIVE duplicate is still rejected.
"""
import datetime
import decimal
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.authentication.models import User
from apps.customers.models import Customer
from apps.expenses.models import ExpenseCategory
from apps.inventory.models import Category, Product, Warehouse
from apps.payroll.models import Employee
from apps.suppliers.models import Supplier
from apps.tenancy.services import OrganisationService


class SoftDeletedKeysAreReusableTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="reuse@audity.test", password="Passw0rd!123")
        cls.org = OrganisationService.create_organisation("Reuse Co", cls.user)

    def _cycle(self, make, label):
        """create -> soft delete -> create the same key again."""
        first = make()
        first.delete()
        try:
            with transaction.atomic():
                return make()
        except IntegrityError:
            self.fail(f"{label}: the key stayed reserved after deletion — "
                      f"the user can never recreate it")

    def _rejects_live_duplicate(self, make, label):
        """The guarantee that must NOT be lost: two live rows cannot share a key."""
        make()
        with self.assertRaises(IntegrityError, msg=f"{label}: live duplicate was allowed"):
            with transaction.atomic():
                make()

    # ── inventory ───────────────────────────────────────────────────────────
    def test_product_sku_is_reusable_after_deletion(self):
        self._cycle(lambda: Product.objects.create(
            organisation=self.org, name="Widget", sku="SKU-1"), "Product.sku")

    def test_product_sku_still_rejects_a_live_duplicate(self):
        self._rejects_live_duplicate(lambda: Product.objects.create(
            organisation=self.org, name="Widget", sku="SKU-DUP"), "Product.sku")

    def test_category_name_is_reusable_after_deletion(self):
        self._cycle(lambda: Category.objects.create(
            organisation=self.org, name="Drinks"), "Category.name")

    def test_category_name_still_rejects_a_live_duplicate(self):
        self._rejects_live_duplicate(lambda: Category.objects.create(
            organisation=self.org, name="Drinks-Dup"), "Category.name")

    def test_warehouse_name_is_reusable_after_deletion(self):
        self._cycle(lambda: Warehouse.objects.create(
            organisation=self.org, name="Lagos"), "Warehouse.name")

    def test_warehouse_name_still_rejects_a_live_duplicate(self):
        self._rejects_live_duplicate(lambda: Warehouse.objects.create(
            organisation=self.org, name="Lagos-Dup"), "Warehouse.name")

    # ── customers / suppliers ───────────────────────────────────────────────
    def test_customer_code_is_reusable_after_deletion(self):
        self._cycle(lambda: Customer.objects.create(
            organisation=self.org, name="Acme", code="C-1"), "Customer.code")

    def test_customer_code_still_rejects_a_live_duplicate(self):
        self._rejects_live_duplicate(lambda: Customer.objects.create(
            organisation=self.org, name="Acme", code="C-DUP"), "Customer.code")

    def test_supplier_code_is_reusable_after_deletion(self):
        self._cycle(lambda: Supplier.objects.create(
            organisation=self.org, name="Supplier A", code="S-1"), "Supplier.code")

    def test_supplier_code_still_rejects_a_live_duplicate(self):
        self._rejects_live_duplicate(lambda: Supplier.objects.create(
            organisation=self.org, name="Supplier A", code="S-DUP"), "Supplier.code")

    # ── expenses ────────────────────────────────────────────────────────────
    def test_expense_category_name_is_reusable_after_deletion(self):
        self._cycle(lambda: ExpenseCategory.objects.create(
            organisation=self.org, name="Travel"), "ExpenseCategory.name")

    def test_expense_category_name_still_rejects_a_live_duplicate(self):
        self._rejects_live_duplicate(lambda: ExpenseCategory.objects.create(
            organisation=self.org, name="Travel-Dup"), "ExpenseCategory.name")

    # ── payroll ─────────────────────────────────────────────────────────────
    def test_employee_id_is_reusable_after_offboarding(self):
        """Re-hiring someone under their original number has to work."""
        self._cycle(lambda: Employee.objects.create(
            organisation=self.org, employee_id="EMP-1",
            first_name="Ada", last_name="Obi",
            hire_date=datetime.date(2026, 1, 5)), "Employee.employee_id")

    def test_employee_id_still_rejects_a_live_duplicate(self):
        self._rejects_live_duplicate(lambda: Employee.objects.create(
            organisation=self.org, employee_id="EMP-DUP",
            first_name="Ada", last_name="Obi",
            hire_date=datetime.date(2026, 1, 5)), "Employee.employee_id")


class SoftDeletedKeysRoundTwoTests(TestCase):
    """Round two of the same audit: documents, numbers and codes.

    Deliberately NOT covered here, and deliberately left strict:
      * JournalEntry (organisation, source_type, source_ref) is the ledger's
        double-post guard. Relaxing it for deleted rows would let the same
        source event post to the books twice.
      * FinancialPeriod (organisation, year, month) gates posting and locking.
    Both are correctness boundaries rather than naming collisions, so they keep
    counting deleted rows on purpose.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="round2@audity.test", password="Passw0rd!123")
        cls.org = OrganisationService.create_organisation("Round Two Co", cls.user)

    def _cycle(self, make, label):
        first = make()
        first.delete()
        try:
            with transaction.atomic():
                return make()
        except IntegrityError:
            self.fail(f"{label}: the key stayed reserved after deletion")

    def _rejects_live_duplicate(self, make, label):
        make()
        with self.assertRaises(IntegrityError, msg=f"{label}: live duplicate was allowed"):
            with transaction.atomic():
                make()

    def _bill(self, number):
        from apps.bills.models import Bill
        from apps.suppliers.models import Supplier
        supplier, _ = Supplier.objects.get_or_create(
            organisation=self.org, code="SUP-R2", defaults={"name": "Supplier R2"})
        return lambda: Bill.objects.create(
            organisation=self.org, supplier=supplier, bill_number=number,
            issue_date=datetime.date(2026, 7, 1), due_date=datetime.date(2026, 7, 30),
            created_by=self.user)

    def _quote(self, number):
        from apps.quotes.models import Quote
        from apps.customers.models import Customer
        customer, _ = Customer.objects.get_or_create(
            organisation=self.org, code="CUS-R2", defaults={"name": "Customer R2"})
        from apps.inventory.models import Warehouse
        warehouse, _ = Warehouse.objects.get_or_create(
            organisation=self.org, name="WH-R2")
        return lambda: Quote.objects.create(
            organisation=self.org, customer=customer, warehouse=warehouse,
            quote_number=number, issue_date=datetime.date(2026, 7, 1),
            valid_until=datetime.date(2026, 7, 31), created_by=self.user)

    # ── bills / quotes ──────────────────────────────────────────────────────
    def test_bill_number_is_reusable_after_deletion(self):
        self._cycle(self._bill("BILL-1"), "Bill.bill_number")

    def test_bill_number_still_rejects_a_live_duplicate(self):
        self._rejects_live_duplicate(self._bill("BILL-DUP"), "Bill.bill_number")

    def test_quote_number_is_reusable_after_deletion(self):
        self._cycle(self._quote("QUO-1"), "Quote.quote_number")

    def test_quote_number_still_rejects_a_live_duplicate(self):
        self._rejects_live_duplicate(self._quote("QUO-DUP"), "Quote.quote_number")

    # ── accounting ──────────────────────────────────────────────────────────
    def test_account_code_is_reusable_after_deletion(self):
        from apps.accounting.models import Account
        self._cycle(lambda: Account.objects.create(
            organisation=self.org, code="9101", name="Scratch",
            account_type="asset"), "Account.code")

    def test_account_code_still_rejects_a_live_duplicate(self):
        from apps.accounting.models import Account
        self._rejects_live_duplicate(lambda: Account.objects.create(
            organisation=self.org, code="9102", name="Scratch",
            account_type="asset"), "Account.code")

    def test_asset_type_code_is_reusable_after_deletion(self):
        from apps.accounting.models import AssetType
        self._cycle(lambda: AssetType.objects.create(
            organisation=self.org, code="MV1", name="Motor Vehicles",
            category="vehicle", depreciation_method="straight_line",
            useful_life_years=4), "AssetType.code")

    def test_fixed_asset_code_is_reusable_after_deletion(self):
        from apps.accounting.models import FixedAsset
        self._cycle(lambda: FixedAsset.objects.create(
            organisation=self.org, name="Press", asset_code="FA-1",
            category="equipment", purchase_date=datetime.date(2026, 7, 1),
            purchase_cost=decimal.Decimal("100000")), "FixedAsset.asset_code")

    # ── the ledger keeps counting deleted rows, on purpose ──────────────────
    def test_journal_entry_double_post_guard_is_still_strict(self):
        """A deleted journal entry must STILL block the same source event from
        posting again — this is the guard that stops double-posting."""
        from apps.accounting.models import JournalEntry
        def make():
            return JournalEntry.objects.create(
                organisation=self.org, reference="JE-GUARD",
                entry_date=datetime.date(2026, 7, 1),
                source_type="sale", source_ref="INV-GUARD",
                created_by=self.user)
        entry = make()
        entry.delete()
        with self.assertRaises(IntegrityError,
                               msg="the ledger's double-post guard was weakened"):
            with transaction.atomic():
                make()


class DuplicateKeyReturnsFriendly400Tests(TestCase):
    """A duplicate natural key is a typo, not a server fault.

    The organisation half of these unique pairs is set by the view and never
    sent by the client, so it is not a serializer field and DRF cannot build a
    UniqueTogetherValidator for it. The duplicate therefore passed validation,
    reached the database and surfaced as an unhandled IntegrityError — a 500 for
    a routine mistake, which also buries real outages in the error rate.
    """

    def setUp(self):
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken
        self.user = User.objects.create_user(email="dup400@audity.test", password="Passw0rd!123")
        self.org = OrganisationService.create_organisation("Dup Co", self.user)
        # Suppliers are not on the Free plan, so the org needs the Business plan
        # before the endpoint is reachable at all.
        from apps.subscriptions.models import Plan
        from apps.subscriptions.services import SubscriptionService
        plan, _ = Plan.objects.get_or_create(
            slug="business",
            defaults={"name": "Business", "price": 30000, "interval": "monthly",
                      "features": {"modules": ["inventory", "suppliers", "expenses",
                                               "accounting", "sales", "bills"]}})
        SubscriptionService.upgrade_plan(self.org, plan)
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}",
            HTTP_X_ORGANISATION_ID=str(self.org.id),
        )

    def _post_twice(self, url, payload):
        first = self.client.post(url, payload, format="json")
        self.assertIn(first.status_code, (200, 201), msg=str(first.data)[:200])
        return self.client.post(url, payload, format="json")

    def test_duplicate_product_sku_is_a_400(self):
        second = self._post_twice("/api/v1/inventory/products/", {
            "name": "Dup Widget", "sku": "DUP-SKU", "selling_price": "100.00",
            "cost_price": "50.00"})
        self.assertEqual(second.status_code, 400, msg=str(second.data)[:200])

    def test_duplicate_supplier_code_is_a_400(self):
        second = self._post_twice("/api/v1/suppliers/", {
            "name": "Dup Supplier", "code": "DUP-SUP"})
        self.assertEqual(second.status_code, 400, msg=str(second.data)[:200])

    def test_duplicate_expense_category_is_a_400(self):
        second = self._post_twice("/api/v1/expenses/categories/", {"name": "Dup Travel"})
        self.assertEqual(second.status_code, 400, msg=str(second.data)[:200])
