"""
find_ledger_damage must find records the old code got wrong, ignore records
the fixed code posted correctly, and change nothing.
"""

import io
import json
import tempfile
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from apps.accounting.models import JournalEntry
from apps.accounting.tests import _make_org, _make_user, _upgrade_to_business


class FindLedgerDamageTests(TestCase):
    def setUp(self):
        from apps.customers.models import Customer
        from apps.inventory.models import Product, Warehouse
        from apps.inventory.services import InventoryService

        self.user = _make_user("damage@example.com")
        self.org = _make_org(self.user, "Damage Org")
        _upgrade_to_business(self.org)
        self.customer = Customer.objects.create(organisation=self.org, name="Repeat Buyer", customer_type="retail")
        self.wh = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.product = Product.objects.create(
            organisation=self.org, sku="DMG", name="Item", cost_price=Decimal("100"), selling_price=Decimal("200"),
        )
        InventoryService.record_movement(
            organisation=self.org, product=self.product, warehouse=self.wh, quantity=Decimal("10"),
            movement_type="purchase_in", unit_cost=Decimal("100"), reference="SEED", created_by=self.user,
        )

    def _run(self):
        with tempfile.NamedTemporaryFile("r", suffix=".json", delete=False) as fh:
            path = fh.name
        call_command("find_ledger_damage", "--org", str(self.org.id), "--json", path, stdout=io.StringIO())
        with open(path, encoding="utf-8") as fh:
            report = json.load(fh)
        return report[0]["findings"] if report else {}

    def test_finds_an_unposted_payment_and_ignores_a_posted_one(self):
        from apps.credits.models import CreditTransaction
        from apps.credits.services import CreditService

        CreditTransaction.objects.create(                                     # the debt both payments settle
            organisation=self.org, customer=self.customer, amount=Decimal("800"), balance_after=800, recorded_by=self.user,
            transaction_type=CreditTransaction.TransactionType.DEBIT, description="Credit sale – INV-A",
        )
        self.customer.outstanding_balance = Decimal("800")
        self.customer.save(update_fields=["outstanding_balance"])
        CreditService.record_payment(self.org, self.customer, Decimal("500"), recorded_by=self.user,
                                     description="Credit payment – INV-A")   # fixed code: posted
        CreditTransaction.objects.create(                                     # old code: never posted
            organisation=self.org, customer=self.customer, amount=Decimal("300"), balance_after=0, recorded_by=self.user,
            transaction_type=CreditTransaction.TransactionType.CREDIT, description="Credit payment – INV-B",
        )
        found = self._run()["missed_credit_payments"]
        self.assertEqual([i["description"] for i in found["items"]], ["Credit payment – INV-B"])
        self.assertEqual(found["total"], "300.00")

    def test_finds_an_invoice_charged_vat_twice(self):
        from apps.sales.models import Invoice
        from apps.sales.services import SaleService

        inv = SaleService.create_sale(
            organisation=self.org, created_by=self.user, customer=self.customer, warehouse=self.wh,
            items=[{"product_id": str(self.product.id), "quantity": 1}], payment_method="credit",
        )
        Invoice.objects.filter(pk=inv.pk).update(total_amount=Decimal("215"))  # what the old code stored
        found = self._run()["vat_charged_twice"]
        self.assertEqual(found["items"][0]["overcharge"], "15.00")

    def test_changes_nothing(self):
        from apps.credits.models import CreditTransaction
        CreditTransaction.objects.create(
            organisation=self.org, customer=self.customer, amount=Decimal("300"), balance_after=0, recorded_by=self.user,
            transaction_type=CreditTransaction.TransactionType.CREDIT, description="Credit payment – INV-C",
        )
        before = JournalEntry.objects.filter(organisation=self.org).count()
        self._run()
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org).count(), before)
