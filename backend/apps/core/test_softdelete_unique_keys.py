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
