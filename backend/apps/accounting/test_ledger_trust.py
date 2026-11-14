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


class PoBillRetryTests(TestCase):
    """Item 2: GL Health Retry on a PO-raised bill must not post a second, expense-side entry."""

    def setUp(self):
        from unittest.mock import patch
        from apps.inventory.models import Product, Warehouse
        from apps.purchases.models import PurchaseOrder, PurchaseOrderItem
        from apps.suppliers.models import Supplier

        self.patch = patch
        self.user, self.org = _setup("pr_owner@example.com", "PR Org")
        self.supplier = Supplier.objects.create(organisation=self.org, name="Acme")
        self.wh = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.product = Product.objects.create(
            organisation=self.org, sku="R-1", name="Widget", product_type="physical",
            cost_price=D("100"), selling_price=D("150"))
        self.po = PurchaseOrder.objects.create(
            organisation=self.org, supplier=self.supplier, warehouse=self.wh, po_number="PO-RETRY-1",
            order_date=date.today(), status=PurchaseOrder.Status.SENT,
            subtotal=D("1000"), tax_amount=D("75"), total_amount=D("1075"), created_by=self.user)
        self.item = PurchaseOrderItem.objects.create(
            organisation=self.org, purchase_order=self.po, product=self.product,
            quantity_ordered=D("10"), unit_cost=D("100"), tax_rate=D("7.5"), line_total=D("1000"))

    def _receive(self, qty, fail=False):
        from apps.purchases.services import PurchaseService
        self.po.refresh_from_db()
        args = [{"item_id": str(self.item.id), "quantity_received": qty}]
        if fail:
            with self.patch.object(AccountingService, "post_journal_entry", side_effect=RuntimeError("ledger down")):
                PurchaseService.receive_purchase_order(self.po, args, self.user)
        else:
            PurchaseService.receive_purchase_order(self.po, args, self.user)

    def _bill(self):
        from apps.bills.models import Bill
        return Bill.objects.get(organisation=self.org, source_purchase_order=self.po)

    def _assert_books(self, inventory, vat, ap_credit, expense=D("0")):
        self.assertEqual(bal(self.org, "1200"), inventory)
        self.assertEqual(bal(self.org, "1400"), vat)
        self.assertEqual(bal(self.org, "2001"), ap_credit)
        self.assertEqual(bal(self.org, "6700"), expense)

    def test_retry_after_failed_receipt_posts_the_receipt_not_a_bill_journal(self):
        self._receive(10, fail=True)
        bill = self._bill()
        self.assertEqual(bill.gl_post_status, "failed")
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org).exclude(source_type="").count(), 0)

        ok, err = AccountingService.retry_gl_post(self.org, "bill", str(bill.id), self.user)
        self.assertTrue(ok, err)
        bill.refresh_from_db()
        self.assertEqual(bill.gl_post_status, "posted")
        self.assertFalse(JournalEntry.objects.filter(organisation=self.org, source_type="bill_approved").exists())
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org, source_type="po_receipt").count(), 1)
        # Inventory 1,000, Input VAT 75, AP 1,075 (credit balance), General Expense untouched.
        self._assert_books(D("1000"), D("75"), D("1075"))

    def test_second_retry_changes_nothing(self):
        self._receive(10, fail=True)
        bill = self._bill()
        AccountingService.retry_gl_post(self.org, "bill", str(bill.id), self.user)
        AccountingService.retry_gl_post(self.org, "bill", str(bill.id), self.user)
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org, source_type="po_receipt").count(), 1)
        self._assert_books(D("1000"), D("75"), D("1075"))

    def test_retry_after_failed_second_partial_receipt_posts_only_that_batch(self):
        self._receive(4)                      # net 400, VAT 30: posts fine
        self._receive(6, fail=True)           # net 600, VAT 45: ledger down
        bill = self._bill()
        self.assertEqual(bill.gl_post_status, "failed")
        self._assert_books(D("400"), D("30"), D("430"))
        ok, err = AccountingService.retry_gl_post(self.org, "bill", str(bill.id), self.user)
        self.assertTrue(ok, err)
        self._assert_books(D("1000"), D("75"), D("1075"))
        self.assertFalse(JournalEntry.objects.filter(organisation=self.org, source_type="bill_approved").exists())

    def test_retry_after_failed_convert_to_bill_reposts_the_conversion_journal(self):
        from apps.purchases.services import PurchaseService
        with self.patch.object(AccountingService, "post_journal_entry", side_effect=RuntimeError("down")):
            PurchaseService.convert_to_bill(self.po, self.user)
        bill = self._bill()
        self.assertEqual(bill.gl_post_status, "failed")
        ok, err = AccountingService.retry_gl_post(self.org, "bill", str(bill.id), self.user)
        self.assertTrue(ok, err)
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org, source_type="po_convert_to_bill").count(), 1)
        self.assertFalse(JournalEntry.objects.filter(organisation=self.org, source_type="bill_approved").exists())
        self._assert_books(D("1000"), D("75"), D("1075"))

    def test_retry_of_a_normal_bill_still_posts_the_bill_journal(self):
        from apps.bills.models import Bill
        bill = Bill.objects.create(
            organisation=self.org, supplier=self.supplier, bill_number="B-NORMAL", status=Bill.APPROVED,
            issue_date=date.today(), due_date=date.today(), subtotal=D("1000"), tax_amount=D("75"),
            total_amount=D("1075"), amount_due=D("1075"), created_by=self.user)
        ok, err = AccountingService.retry_gl_post(self.org, "bill", str(bill.id), self.user)
        self.assertTrue(ok, err)
        self.assertTrue(JournalEntry.objects.filter(organisation=self.org, source_type="bill_approved").exists())
        self.assertEqual(bal(self.org, "6700"), D("1000"))
        self.assertEqual(bal(self.org, "1400"), D("75"))
