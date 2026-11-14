"""
Ledger-trust regression tests: the books must be right before profit is read
from them. One class per item; each uses explicit numbers.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.accounting.management.commands.repair_vat_input_account import Command as RepairVatCommand
from apps.accounting.models import (
    Account, AccountMapping, AccountType, FinancialPeriod, JournalEntry, JournalLine,
)
from apps.accounting.services import AccountingService, AccountMappingService
from apps.accounting.tests import _make_org, _make_user, _upgrade_to_business

D = Decimal
ZERO = Decimal("0")


def acct(org, code):
    return Account.objects.get(organisation=org, code=code)


def bal(org, code):
    return AccountingService._ledger_balance(acct(org, code))


def _setup(email, name):
    user = _make_user(email)
    org = _make_org(user, name)
    _upgrade_to_business(org)
    return user, org


class VatInputMappingTests(TestCase):
    """Item 1: ONE Input VAT account for every flow."""

    def setUp(self):
        self.user, self.org = _setup("vi_owner@example.com", "VI Org")

    def test_new_org_auto_maps_input_vat_to_1400_not_prepaid(self):
        mapping = AccountMapping.objects.filter(organisation=self.org).first()
        if mapping:
            mapping.delete()
        self.assertEqual(AccountMappingService.resolve(self.org, "vat_input_account").code, "1400")

    def test_suggest_also_prefers_1400(self):
        self.assertEqual(AccountMappingService.suggest(self.org, "vat_input_account").code, "1400")

    def test_bill_approved_journal_uses_the_mapped_input_vat_account(self):
        from apps.bills.models import Bill, BillItem
        from apps.suppliers.models import Supplier

        mapping = AccountMappingService.get_or_create_mapping(self.org)
        custom = Account.objects.create(
            organisation=self.org, code="1499", name="My Input VAT", account_type=AccountType.ASSET)
        mapping.vat_input_account = custom
        mapping.save()
        supplier = Supplier.objects.create(organisation=self.org, name="Sup")
        bill = Bill.objects.create(
            organisation=self.org, supplier=supplier, bill_number="B-VI-1", status=Bill.APPROVED,
            issue_date=date.today(), due_date=date.today(), subtotal=D("1000"), tax_amount=D("75"),
            total_amount=D("1075"), amount_due=D("1075"), created_by=self.user,
        )
        BillItem.objects.create(organisation=self.org, bill=bill, description="x", quantity=1,
                                unit_cost=D("1000"), line_total=D("1000"))
        AccountingService.post_bill_approved_journal(self.org, bill, self.user)
        self.assertEqual(AccountingService._ledger_balance(custom), D("75"))
        self.assertEqual(bal(self.org, "1400"), ZERO)

    def test_bill_without_vat_needs_no_input_vat_mapping(self):
        from apps.bills.models import Bill
        from apps.suppliers.models import Supplier

        mapping = AccountMappingService.get_or_create_mapping(self.org)
        mapping.vat_input_account = None
        mapping.save()
        supplier = Supplier.objects.create(organisation=self.org, name="Sup2")
        bill = Bill.objects.create(
            organisation=self.org, supplier=supplier, bill_number="B-VI-2", status=Bill.APPROVED,
            issue_date=date.today(), due_date=date.today(), subtotal=D("500"), tax_amount=D("0"),
            total_amount=D("500"), amount_due=D("500"), created_by=self.user,
        )
        entry = AccountingService.post_bill_approved_journal(self.org, bill, self.user)
        self.assertIsNotNone(entry)


class VatInputRepairCommandTests(TestCase):
    """Item 1 repair: org on 1300; bill VAT 75 and return VAT 7.5 end at 1400 = 67.5, 1300 = 0."""

    def setUp(self):
        self.user, self.org = _setup("vr_owner@example.com", "VR Org")
        mapping = AccountMappingService.get_or_create_mapping(self.org)
        mapping.vat_input_account = acct(self.org, "1300")
        mapping.save()
        today = timezone.now().date()
        inv, ap = acct(self.org, "1200"), acct(self.org, "2001")
        p = acct(self.org, "1300")
        # Goods received: net 1000, VAT 75 (booked to the wrong account, 1300)
        AccountingService.post_journal_entry(
            self.org, "Goods received PO-1", today,
            [(inv, D("1000"), ZERO), (p, D("75"), ZERO), (ap, ZERO, D("1075"))],
            self.user, ref="PO-1", source_type="po_receipt", source_ref="po-1")
        # Purchase return: net 100, VAT 7.5
        AccountingService.post_journal_entry(
            self.org, "Purchase return", today,
            [(ap, D("107.5"), ZERO), (inv, ZERO, D("100")), (p, ZERO, D("7.5"))],
            self.user, ref="PR-1", source_type="purchase_return", source_ref="pr-1")
        # An unrelated debit on 1300 (a genuine prepayment) must NOT be moved.
        AccountingService.post_journal_entry(
            self.org, "Insurance prepaid", today,
            [(p, D("500"), ZERO), (acct(self.org, "1002"), ZERO, D("500"))],
            self.user, ref="PP-1", source_type="manual", source_ref="pp-1")

    def _run(self, *args):
        out = StringIO()
        call_command("repair_vat_input_account", "--org", str(self.org.id), *args, stdout=out)
        return out.getvalue()

    def test_dry_run_reports_and_changes_nothing(self):
        before = JournalEntry.objects.filter(organisation=self.org).count()
        out = self._run()
        self.assertIn("DRY RUN", out)
        self.assertIn("67.50", out)
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org).count(), before)
        mapping = AccountMapping.objects.get(organisation=self.org)
        self.assertEqual(mapping.vat_input_account.code, "1300")
        self.assertEqual(bal(self.org, "1400"), ZERO)
        self.assertEqual(bal(self.org, "1300"), D("567.5"))

    def test_apply_moves_vat_and_repoints_mapping(self):
        out = self._run("--apply")
        self.assertIn("REPAIRED", out)
        self.assertEqual(bal(self.org, "1400"), D("67.5"))
        # 1300 keeps only the genuine 500 prepayment
        self.assertEqual(bal(self.org, "1300"), D("500"))
        mapping = AccountMapping.objects.get(organisation=self.org)
        self.assertEqual(mapping.vat_input_account.code, "1400")
        reclass = JournalEntry.objects.get(organisation=self.org, source_type="vat_input_reclass")
        self.assertEqual(sum(l.debit for l in reclass.lines.all()), sum(l.credit for l in reclass.lines.all()))
        self.assertIn("Reclass Input VAT", reclass.description)

    def test_apply_is_idempotent(self):
        self._run("--apply")
        count = JournalEntry.objects.filter(organisation=self.org).count()
        out = self._run("--apply")
        self.assertIn("fine", out)
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org).count(), count)
        self.assertEqual(bal(self.org, "1400"), D("67.5"))

    def test_creates_1400_when_missing(self):
        Account.objects.filter(organisation=self.org, code="1400").delete()
        self._run("--apply")
        self.assertEqual(bal(self.org, "1400"), D("67.5"))

    def test_locked_period_blocks_and_changes_nothing(self):
        today = timezone.now().date()
        FinancialPeriod.objects.create(organisation=self.org, year=today.year, month=today.month, is_locked=True)
        before = JournalEntry.objects.filter(organisation=self.org).count()
        out = self._run("--apply")
        self.assertIn("BLOCKED", out)
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org).count(), before)
        self.assertEqual(AccountMapping.objects.get(organisation=self.org).vat_input_account.code, "1300")

    def test_org_already_on_1400_is_left_alone(self):
        other_user, other = _setup("vr2_owner@example.com", "VR Org 2")
        before = JournalEntry.objects.filter(organisation=other).count()
        out = StringIO()
        call_command("repair_vat_input_account", "--org", str(other.id), "--apply", stdout=out)
        self.assertIn("fine", out.getvalue())
        self.assertEqual(JournalEntry.objects.filter(organisation=other).count(), before)

    def test_other_organisations_are_never_touched(self):
        other_user, other = _setup("vr3_owner@example.com", "VR Org 3")
        m = AccountMappingService.get_or_create_mapping(other)
        m.vat_input_account = acct(other, "1300")
        m.save()
        self._run("--apply")  # --org limits it to self.org
        m.refresh_from_db()
        self.assertEqual(m.vat_input_account.code, "1300")
