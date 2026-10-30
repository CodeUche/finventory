"""
repair_ledger_damage posts only what the owner approved, only when the
approver really is the owner, once, with a rehearsal that changes nothing.
"""

import io
import json
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from apps.accounting.models import FinancialPeriod, JournalEntry
from apps.accounting.tests import _make_org, _make_user, _upgrade_to_business


class RepairLedgerDamageTests(TestCase):
    def setUp(self):
        from apps.credits.models import CreditTransaction
        from apps.customers.models import Customer

        self.user = _make_user("owner-repair@example.com")
        self.org = _make_org(self.user, "Repair Org")
        _upgrade_to_business(self.org)
        self.customer = Customer.objects.create(organisation=self.org, name="Ada", customer_type="retail")
        CreditTransaction.objects.create(              # the debt the payment settles
            organisation=self.org, customer=self.customer, amount=Decimal("300"), balance_after=300,
            recorded_by=self.user, transaction_type=CreditTransaction.TransactionType.DEBIT,
            description="Credit sale – INV-B",
        )
        self.txn = CreditTransaction.objects.create(   # a payment the old code never posted
            organisation=self.org, customer=self.customer, amount=Decimal("300"), balance_after=0,
            recorded_by=self.user, transaction_type=CreditTransaction.TransactionType.CREDIT,
            description="Credit payment – INV-B",
        )
        self.plan_path = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name

    def _plan(self, approve=True):
        call_command("repair_ledger_damage", "plan", "--org", str(self.org.id), "--out", self.plan_path,
                     stdout=io.StringIO())
        with open(self.plan_path, encoding="utf-8") as fh:
            plan = json.load(fh)
        for c in plan["corrections"]:
            c["approved"] = approve
        with open(self.plan_path, "w", encoding="utf-8") as fh:
            json.dump(plan, fh)
        return plan

    def _apply(self, email=None, commit=True):
        args = ["repair_ledger_damage", "apply", "--plan", self.plan_path,
                "--approved-by", email or self.user.email] + (["--commit"] if commit else [])
        out = io.StringIO()
        call_command(*args, stdout=out)
        return out.getvalue()

    def _repairs(self):
        return JournalEntry.objects.filter(organisation=self.org, source_type="data_repair")

    def test_plan_proposes_the_payment_and_changes_nothing(self):
        plan = self._plan(approve=False)
        self.assertEqual([c["id"] for c in plan["corrections"]], [f"BUG-001:{self.txn.id}"])
        self.assertFalse(plan["corrections"][0]["approved"])
        self.assertEqual(self._repairs().count(), 0)

    def test_nothing_unapproved_is_posted(self):
        self._plan(approve=False)
        self._apply()
        self.assertEqual(self._repairs().count(), 0)

    def test_rehearsal_rolls_back(self):
        self._plan()
        out = self._apply(commit=False)
        self.assertIn("REHEARSAL", out)
        self.assertEqual(self._repairs().count(), 0)

    def test_commit_posts_dr_cash_cr_receivable_once(self):
        self._plan()
        self._apply()
        entry = self._repairs().get()
        self.assertEqual(entry.source_ref, f"BUG-001:{self.txn.id}")
        self.assertEqual(entry.created_by.email, "data-repair@system.audity.africa")
        debit = [l for l in entry.lines.all() if l.debit > 0][0]
        credit = [l for l in entry.lines.all() if l.credit > 0][0]
        self.assertEqual((debit.debit, credit.credit), (Decimal("300"), Decimal("300")))
        self.assertTrue(credit.account.code.startswith("1100"))
        self._apply()                                      # a second run posts nothing new
        self.assertEqual(self._repairs().count(), 1)
        # and the damage report no longer needs to be told about it by hand
        from apps.core.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(organisation_id=self.org.id, model_name="DataRepairBatch").exists())

    def test_only_the_owner_can_approve(self):
        other = _make_user("not-owner@example.com")
        self._plan()
        with self.assertRaises(CommandError):
            self._apply(email=other.email)
        self.assertEqual(self._repairs().count(), 0)

    def test_a_locked_month_is_not_unlocked_the_entry_posts_today(self):
        old = timezone.now().date() - timedelta(days=90)
        from apps.credits.models import CreditTransaction
        CreditTransaction.objects.filter(organisation=self.org).update(created_at=timezone.now() - timedelta(days=91))
        CreditTransaction.objects.filter(pk=self.txn.pk).update(created_at=timezone.now() - timedelta(days=90))
        FinancialPeriod.objects.update_or_create(
            organisation=self.org, year=old.year, month=old.month, defaults={"is_locked": True})
        self._plan()
        self._apply()
        entry = self._repairs().get()
        self.assertEqual(entry.entry_date, timezone.now().date())
        self.assertIn(old.isoformat(), entry.description)
        self.assertTrue(FinancialPeriod.objects.get(
            organisation=self.org, year=old.year, month=old.month).is_locked)

    def test_a_payment_bigger_than_the_debt_only_repairs_the_part_that_was_owed(self):
        """A 400 payment against 100 owed was stored as if 100 had been paid. Only the
        100 is evident from the books; the other 300 goes to a person, never the ledger."""
        from apps.credits.models import CreditTransaction
        from apps.customers.models import Customer
        c = Customer.objects.create(organisation=self.org, name="Bola", code="C-BOLA", customer_type="retail")
        CreditTransaction.objects.create(
            organisation=self.org, customer=c, amount=Decimal("100"), balance_after=100,
            recorded_by=self.user, transaction_type=CreditTransaction.TransactionType.DEBIT,
            description="Credit sale – INV-C")
        big = CreditTransaction.objects.create(
            organisation=self.org, customer=c, amount=Decimal("400"), balance_after=0,
            recorded_by=self.user, transaction_type=CreditTransaction.TransactionType.CREDIT,
            description="Payment received – Bola")
        plan = self._plan()
        mine = [x for x in plan["corrections"] if x["record"] == str(big.id)]
        self.assertEqual([Decimal(x["amount"]) for x in mine], [Decimal("100")])
        held = plan["manual"]["overpaid_payments"]
        self.assertEqual([(h["payment"], Decimal(h["not_owed"])) for h in held], [(str(big.id), Decimal("300"))])
        self._apply()
        entry = self._repairs().get(source_ref=f"BUG-001:{big.id}")
        self.assertEqual(sum(l.debit for l in entry.lines.all()), Decimal("100"))


class BillAlreadyPostedTests(TestCase):
    def test_a_bill_whose_approval_already_booked_the_payable_is_not_flagged(self):
        from datetime import date
        from apps.accounting.services import AccountingService
        from apps.bills.models import Bill
        from apps.core.management.commands.find_ledger_damage import Command as Finder
        from apps.purchases.models import PurchaseOrder
        from apps.suppliers.models import Supplier

        user = _make_user("bill-posted@example.com")
        org = _make_org(user, "Bill Posted Org")
        _upgrade_to_business(org)
        from apps.inventory.models import Warehouse
        supplier = Supplier.objects.create(organisation=org, name="Kobo")
        warehouse = Warehouse.objects.create(organisation=org, name="Main", is_default=True)
        po = PurchaseOrder.objects.create(
            organisation=org, po_number="PO-X", supplier=supplier, warehouse=warehouse, status="received",
            order_date=date(2026, 6, 1), subtotal=Decimal("500"), tax_amount=Decimal("0"),
            total_amount=Decimal("500"), created_by=user)
        bill = Bill.objects.create(
            organisation=org, supplier=supplier, status=Bill.APPROVED, issue_date=date(2026, 6, 1),
            due_date=date(2026, 7, 1), subtotal=Decimal("500"), tax_amount=Decimal("0"),
            total_amount=Decimal("500"), created_by=user, source_purchase_order=po)

        flagged = Finder()._missed_po_receipts(org)["items"]
        self.assertEqual([i["bill"] for i in flagged], [bill.bill_number])   # nothing posted yet: missing

        expense = AccountingService._get_or_create_account(org, "6700", "Other Expenses", "expense")
        payable = AccountingService._get_or_create_account(org, "2001", "Accounts Payable", "liability")
        AccountingService.post_journal_entry(
            org, f"Bill approved {bill.bill_number}", date(2026, 6, 1),
            [(expense, Decimal("500"), Decimal("0")), (payable, Decimal("0"), Decimal("500"))],
            user, source_type="bill_approved", source_ref=str(bill.id))
        self.assertEqual(Finder()._missed_po_receipts(org)["items"], [])
