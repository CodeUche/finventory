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
