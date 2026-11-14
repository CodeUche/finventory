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


class CogsNotSilentlyDroppedTests(TestCase):
    """Item 3: an unmapped COGS/Inventory account must show up as a GL failure, not a quiet 'posted'."""

    def setUp(self):
        from apps.customers.models import Customer
        from apps.inventory.models import Product, Warehouse
        from apps.inventory.services import InventoryService

        self.user, self.org = _setup("cg_owner@example.com", "CG Org")
        self.customer = Customer.objects.create(organisation=self.org, name="Cust", email="cg@example.com")
        self.wh = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.product = Product.objects.create(
            organisation=self.org, sku="CG-1", name="Gadget", product_type="physical",
            selling_price=D("200"), cost_price=D("60"))
        InventoryService.record_movement(
            organisation=self.org, product=self.product, warehouse=self.wh, quantity=D("5"),
            movement_type="purchase_in", unit_cost=D("60"), reference="INIT", created_by=self.user)
        AccountMappingService.get_or_create_mapping(self.org)

    def _sell(self):
        from apps.sales.services import SaleService
        return SaleService.create_sale(
            organisation=self.org, customer=self.customer, warehouse=self.wh,
            items=[{"product_id": self.product.id, "quantity": 1, "unit_price": D("200")}],
            payment_method="cash", created_by=self.user)

    def _unmap(self, field):
        # Strict GL mode (the default) refuses the sale up front; the silent
        # drop only ever happened for organisations running without it.
        self.org.strict_gl_mode = False
        self.org.save(update_fields=["strict_gl_mode"])
        m = AccountMapping.objects.get(organisation=self.org)
        setattr(m, field, None)
        m.save()

    def test_sale_with_cogs_mapped_posts_revenue_and_cost(self):
        inv = self._sell()
        inv.refresh_from_db()
        self.assertEqual(inv.gl_post_status, "posted")
        self.assertEqual(bal(self.org, "4001"), D("200"))
        self.assertEqual(bal(self.org, "5001"), D("60"))
        self.assertEqual(bal(self.org, "1200"), D("-60"))

    def test_unmapped_cogs_still_completes_the_sale_but_flags_the_ledger(self):
        from apps.sales.models import Invoice
        self._unmap("cogs_account")
        inv = self._sell()
        inv.refresh_from_db()
        self.assertTrue(Invoice.objects.filter(id=inv.id).exists())       # the sale itself went through
        self.assertEqual(inv.gl_post_status, "not_configured")
        self.assertIn("cogs_account", inv.gl_post_error)
        # Nothing half-posted: no revenue without its cost.
        self.assertEqual(bal(self.org, "4001"), ZERO)
        failures = AccountingService.get_gl_health(self.org)["failures"]
        self.assertTrue(any(f["model"] == "invoice" and f["id"] == str(inv.id) for f in failures))

    def test_unmapped_inventory_account_is_flagged_too(self):
        self._unmap("inventory_account")
        inv = self._sell()
        inv.refresh_from_db()
        self.assertEqual(inv.gl_post_status, "not_configured")
        self.assertIn("inventory_account", inv.gl_post_error)

    def test_retry_after_mapping_the_account_posts_revenue_and_cost_together(self):
        self._unmap("cogs_account")
        inv = self._sell()
        m = AccountMapping.objects.get(organisation=self.org)
        m.cogs_account = acct(self.org, "5001")
        m.save()
        ok, err = AccountingService.retry_gl_post(self.org, "invoice", str(inv.id), self.user)
        self.assertTrue(ok, err)
        inv.refresh_from_db()
        self.assertEqual(inv.gl_post_status, "posted")
        self.assertEqual(bal(self.org, "4001"), D("200"))
        self.assertEqual(bal(self.org, "5001"), D("60"))


class ExpenseEditDeleteLedgerTests(TestCase):
    """Item 4: editing or deleting an expense must move the ledger with it."""

    def setUp(self):
        from apps.accounting.tests import _auth_client
        self.user, self.org = _setup("ex_owner@example.com", "EX Org")
        self.client = _auth_client(self.user, self.org)
        self.today = timezone.now().date()
        self.cash = AccountMappingService.resolve(self.org, "cash_account")
        self.bank = AccountMappingService.resolve(self.org, "bank_account")

    def _create(self, amount="5000", **extra):
        payload = {"description": "Generator fuel", "amount": amount, "expense_date": str(self.today),
                   "category_label": "Fuel", "payment_method": "cash"}
        payload.update(extra)
        res = self.client.post("/api/v1/expenses/", payload, format="json")
        self.assertEqual(res.status_code, 201, res.content[:300])
        return res.data["id"]

    def _bal(self, account):
        return AccountingService._ledger_balance(account)

    def test_edit_5000_to_3000_nets_3000_in_the_ledger(self):
        eid = self._create("5000")
        self.assertEqual(bal(self.org, "6700"), D("5000"))
        res = self.client.patch(f"/api/v1/expenses/{eid}/", {"amount": "3000"}, format="json")
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(bal(self.org, "6700"), D("3000"))
        self.assertEqual(self._bal(self.cash), D("-3000"))
        from apps.expenses.models import Expense
        self.assertEqual(Expense.objects.get(id=eid).gl_post_status, "posted")
        # History kept: original, its reversal, and the new entry under a new reference.
        refs = list(JournalEntry.objects.filter(organisation=self.org, source_type="expense")
                    .values_list("source_ref", flat=True))
        self.assertEqual(sorted(refs), sorted([eid, f"{eid}:v2"]))
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org, source_type="reversal").count(), 1)

    def test_second_edit_chains_cleanly(self):
        eid = self._create("5000")
        self.client.patch(f"/api/v1/expenses/{eid}/", {"amount": "3000"}, format="json")
        self.client.patch(f"/api/v1/expenses/{eid}/", {"amount": "4200"}, format="json")
        self.assertEqual(bal(self.org, "6700"), D("4200"))
        self.assertEqual(self._bal(self.cash), D("-4200"))

    def test_payment_method_change_moves_the_credit_side(self):
        eid = self._create("5000")
        self.client.patch(f"/api/v1/expenses/{eid}/", {"payment_method": "bank"}, format="json")
        self.assertEqual(self._bal(self.cash), ZERO)
        self.assertEqual(self._bal(self.bank), D("-5000"))
        self.assertEqual(bal(self.org, "6700"), D("5000"))

    def test_changing_to_income_flips_the_ledger(self):
        eid = self._create("5000")
        self.client.patch(f"/api/v1/expenses/{eid}/", {"is_income": True}, format="json")
        self.assertEqual(bal(self.org, "6700"), ZERO)
        self.assertEqual(bal(self.org, "4001"), D("5000"))
        self.assertEqual(self._bal(self.cash), D("5000"))

    def test_description_only_edit_posts_nothing(self):
        eid = self._create("5000")
        before = JournalEntry.objects.filter(organisation=self.org).count()
        res = self.client.patch(f"/api/v1/expenses/{eid}/", {"description": "Diesel"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org).count(), before)

    def test_delete_nets_the_ledger_to_zero_and_keeps_audit_rows(self):
        from apps.core.models import AuditLog
        from apps.expenses.models import Expense
        eid = self._create("5000")
        res = self.client.delete(f"/api/v1/expenses/{eid}/")
        self.assertEqual(res.status_code, 204)
        self.assertEqual(bal(self.org, "6700"), ZERO)
        self.assertEqual(self._bal(self.cash), ZERO)
        self.assertFalse(Expense.objects.filter(id=eid).exists())
        self.assertTrue(Expense.all_objects.filter(id=eid, is_deleted=True).exists())
        # The original entry and its reversal are both still there.
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org, source_type="expense").count(), 1)
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org, source_type="reversal").count(), 1)
        self.assertTrue(AuditLog.objects.filter(organisation_id=self.org.id, model_name="Expense",
                                                object_id=eid, action="delete").exists())

    def test_edit_in_a_locked_period_is_blocked_and_nothing_changes(self):
        from apps.expenses.models import Expense
        eid = self._create("5000")
        FinancialPeriod.objects.create(organisation=self.org, year=self.today.year,
                                       month=self.today.month, is_locked=True)
        res = self.client.patch(f"/api/v1/expenses/{eid}/", {"amount": "3000"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertIn("locked", str(res.data).lower())
        self.assertEqual(Expense.objects.get(id=eid).amount, D("5000"))
        self.assertEqual(bal(self.org, "6700"), D("5000"))
        self.assertEqual(JournalEntry.objects.filter(organisation=self.org, source_type="reversal").count(), 0)

    def test_delete_in_a_locked_period_is_blocked(self):
        from apps.expenses.models import Expense
        eid = self._create("5000")
        FinancialPeriod.objects.create(organisation=self.org, year=self.today.year,
                                       month=self.today.month, is_locked=True)
        res = self.client.delete(f"/api/v1/expenses/{eid}/")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(Expense.objects.filter(id=eid).exists())
        self.assertEqual(bal(self.org, "6700"), D("5000"))

    def test_moving_the_date_into_a_locked_period_is_blocked(self):
        eid = self._create("5000")
        FinancialPeriod.objects.create(organisation=self.org, year=2020, month=3, is_locked=True)
        res = self.client.patch(f"/api/v1/expenses/{eid}/", {"expense_date": "2020-03-10"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(bal(self.org, "6700"), D("5000"))

    def test_failed_repost_is_flagged_and_retry_restores_the_cost(self):
        from unittest.mock import patch
        from apps.expenses.models import Expense
        eid = self._create("5000")
        with patch.object(AccountingService, "post_journal_entry", side_effect=RuntimeError("down")):
            self.client.patch(f"/api/v1/expenses/{eid}/", {"amount": "3000"}, format="json")
        self.assertEqual(Expense.objects.get(id=eid).gl_post_status, "failed")
        self.assertEqual(bal(self.org, "6700"), ZERO)       # old entry reversed, new not yet posted
        ok, err = AccountingService.retry_gl_post(self.org, "expense", eid, self.user)
        self.assertTrue(ok, err)
        self.assertEqual(bal(self.org, "6700"), D("3000"))
        # A second retry changes nothing.
        AccountingService.retry_gl_post(self.org, "expense", eid, self.user)
        self.assertEqual(bal(self.org, "6700"), D("3000"))

    def test_another_organisation_cannot_edit_the_expense(self):
        from apps.accounting.tests import _auth_client
        other_user, other = _setup("ex2_owner@example.com", "EX Org 2")
        other_client = _auth_client(other_user, other)
        eid = self._create("5000")
        res = other_client.patch(f"/api/v1/expenses/{eid}/", {"amount": "1"}, format="json")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(bal(self.org, "6700"), D("5000"))


class AccountDeactivationTests(TestCase):
    """Item 5: deactivating an account must never unbalance the reports."""

    def setUp(self):
        from apps.accounting.tests import _auth_client
        self.user, self.org = _setup("ad_owner@example.com", "AD Org")
        self.client = _auth_client(self.user, self.org)
        self.today = timezone.now().date()
        self.rent = Account.objects.create(
            organisation=self.org, code="6150", name="Site Rent", account_type=AccountType.EXPENSE)
        AccountingService.post_journal_entry(
            self.org, "Rent paid", self.today,
            [(self.rent, D("1000"), ZERO), (acct(self.org, "1001"), ZERO, D("1000"))],
            self.user, ref="R1", source_type="manual", source_ref="r1")

    def _deactivate(self, account):
        return self.client.patch(f"/api/v1/accounting/accounts/{account.id}/", {"is_active": False}, format="json")

    def test_account_with_a_balance_cannot_be_deactivated(self):
        res = self._deactivate(self.rent)
        self.assertEqual(res.status_code, 400, res.content[:300])
        self.assertIn("This account still has a balance of 1,000.00. Move it first.", str(res.data))
        self.rent.refresh_from_db()
        self.assertTrue(self.rent.is_active)

    def test_zero_balance_unused_account_can_be_deactivated(self):
        spare = Account.objects.create(
            organisation=self.org, code="6160", name="Spare", account_type=AccountType.EXPENSE)
        res = self._deactivate(spare)
        self.assertEqual(res.status_code, 200, res.content[:300])
        spare.refresh_from_db()
        self.assertFalse(spare.is_active)

    def test_zero_balance_with_open_period_postings_is_refused(self):
        AccountingService.post_journal_entry(
            self.org, "Refund", self.today,
            [(acct(self.org, "1001"), D("1000"), ZERO), (self.rent, ZERO, D("1000"))],
            self.user, ref="R2", source_type="manual", source_ref="r2")
        res = self._deactivate(self.rent)
        self.assertEqual(res.status_code, 400)
        self.assertIn("open period", str(res.data))

    def test_zero_balance_with_postings_only_in_a_locked_month_can_be_deactivated(self):
        AccountingService.post_journal_entry(
            self.org, "Refund", self.today,
            [(acct(self.org, "1001"), D("1000"), ZERO), (self.rent, ZERO, D("1000"))],
            self.user, ref="R2", source_type="manual", source_ref="r2")
        FinancialPeriod.objects.create(organisation=self.org, year=self.today.year,
                                       month=self.today.month, is_locked=True)
        self.assertEqual(self._deactivate(self.rent).status_code, 200)

    def test_reports_still_balance_and_show_an_inactive_account_that_has_a_balance(self):
        # Force the bad state directly (older data, or a path that bypasses the API).
        Account.objects.filter(id=self.rent.id).update(is_active=False)
        tb = AccountingService.trial_balance(self.org)
        self.assertIn("6150", [r["code"] for r in tb])
        debits = sum(r["balance"] for r in tb if r["type"] in ("asset", "expense", "cogs"))
        credits = sum(r["balance"] for r in tb if r["type"] not in ("asset", "expense", "cogs"))
        self.assertEqual(debits, credits)
        bs = AccountingService.balance_sheet(self.org)
        # Cash is -1000 (credit), the rent expense is 1000: equity falls by 1000.
        self.assertEqual(bs["current_year_earnings"], D("-1000"))
        self.assertEqual(bs["total_assets"], D("-1000"))
        self.assertEqual(bs["total_liabilities"] + bs["total_equity"], D("-1000"))

    def test_account_with_a_balance_cannot_be_deleted(self):
        res = self.client.delete(f"/api/v1/accounting/accounts/{self.rent.id}/")
        self.assertEqual(res.status_code, 400)
        self.assertTrue(Account.objects.filter(id=self.rent.id).exists())


def _force_unbalanced_entry(org, user, debit_account, credit_account, debit, credit):
    """Write an unbalanced posted entry the way bad legacy data could: bypass
    post_journal_entry (which refuses it) by creating a draft and flipping it."""
    je = JournalEntry.objects.create(
        organisation=org, description="Legacy bad entry", entry_date=timezone.now().date(),
        status="draft", created_by=user)
    JournalLine.objects.create(journal_entry=je, account=debit_account, debit=debit, credit=ZERO)
    JournalLine.objects.create(journal_entry=je, account=credit_account, debit=ZERO, credit=credit)
    JournalEntry.objects.filter(id=je.id).update(status="posted")
    return je


class BalanceSheetPlugPresentationTests(TestCase):
    """Item 6: a balance sheet that only adds up because of a plug must say so."""

    def setUp(self):
        self.user, self.org = _setup("pl_owner@example.com", "PL Org")

    def test_clean_ledger_reports_balanced_with_no_plug(self):
        AccountingService.post_journal_entry(
            self.org, "Sale", timezone.now().date(),
            [(acct(self.org, "1001"), D("500"), ZERO), (acct(self.org, "4001"), ZERO, D("500"))],
            self.user, ref="S1", source_type="manual", source_ref="s1")
        bs = AccountingService.balance_sheet(self.org)
        self.assertTrue(bs["balanced"])
        self.assertFalse(bs["ledger_out_of_balance"])
        self.assertEqual(bs["unreconciled_amount"], ZERO)
        self.assertEqual([r for r in bs["equity"] if r.get("is_unreconciled")], [])

    def test_out_of_balance_ledger_is_shown_openly_not_as_take_on_suspense(self):
        # DR cash 1,000 / CR revenue 900: the books are 100 out.
        _force_unbalanced_entry(self.org, self.user, acct(self.org, "1001"), acct(self.org, "4001"),
                                D("1000"), D("900"))
        bs = AccountingService.balance_sheet(self.org)
        self.assertFalse(bs["balanced"])
        self.assertTrue(bs["ledger_out_of_balance"])
        self.assertEqual(bs["unreconciled_amount"], D("100"))
        plug = [r for r in bs["equity"] if r.get("is_unreconciled")]
        self.assertEqual(len(plug), 1)
        self.assertEqual(plug[0]["code"], "DIFF")
        self.assertEqual(plug[0]["name"], "Unreconciled difference (needs review)")
        self.assertEqual(plug[0]["balance"], D("100"))
        # Never disguised as the real opening-balance account.
        self.assertEqual([r for r in bs["equity"] if r.get("code") == "3900" and r.get("is_computed")], [])
        # The sheet still adds up, so the frontend keeps working.
        self.assertEqual(bs["total_assets"], bs["total_liabilities"] + bs["total_equity"])
        for key in ("assets", "liabilities", "equity", "total_assets", "total_liabilities",
                    "total_equity", "current_year_earnings", "as_of"):
            self.assertIn(key, bs)

    def test_api_exposes_the_new_fields(self):
        from apps.accounting.tests import _auth_client
        _force_unbalanced_entry(self.org, self.user, acct(self.org, "1001"), acct(self.org, "4001"),
                                D("1000"), D("900"))
        client = _auth_client(self.user, self.org)
        res = client.get("/api/v1/accounting/accounts/balance_sheet/")
        self.assertEqual(res.status_code, 200)
        self.assertIs(res.data["ledger_out_of_balance"], True)
        self.assertEqual(Decimal(str(res.data["unreconciled_amount"])), D("100"))
        self.assertIs(res.data["balanced"], False)

    def test_gl_health_alerts_on_a_non_zero_plug(self):
        clean = AccountingService.get_gl_health(self.org)["reconciliations"]
        self.assertFalse(clean["ledger_out_of_balance"])
        self.assertTrue(clean["all_reconciled"])
        _force_unbalanced_entry(self.org, self.user, acct(self.org, "1001"), acct(self.org, "4001"),
                                D("1000"), D("900"))
        rec = AccountingService.get_gl_health(self.org)["reconciliations"]
        self.assertTrue(rec["ledger_out_of_balance"])
        self.assertEqual(rec["unreconciled_difference"], D("100"))
        self.assertFalse(rec["all_reconciled"])
        checklist = AccountingService.period_close_checklist(self.org)
        self.assertFalse(checklist["ready"])
