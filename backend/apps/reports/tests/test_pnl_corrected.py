"""
The corrected Profit and Loss: it includes payroll, depreciation and approved supplier
bills (all booked in the ledger, none of them an Expense row), and for the same dates
it must equal the ledger profit (income accounts minus expense accounts).

Numbers (VAT 7.5%): one cash sale of 2 x 1,000 (net 2,000, VAT 150, cost 1,200).
"""
from datetime import date, datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone

from apps.accounting.models import Account, AccountType, JournalEntry, JournalLine
from apps.accounting.services import AccountingService
from apps.expenses.models import Expense, ExpenseCategory
from apps.reports.services import ReportService
from apps.sales.test_new_sale_and_invoice import URL
from apps.sales.test_sales_ledger import LedgerBase

D = Decimal


def ledger_net_profit(org, d_from, d_to):
    """Income accounts minus expense and cost-of-sales accounts, posted entries dated in the period."""
    rows = JournalLine.objects.filter(
        journal_entry__organisation=org, journal_entry__status="posted",
        journal_entry__entry_date__gte=d_from, journal_entry__entry_date__lte=d_to,
    ).exclude(journal_entry__source_type="year_end_close")
    net = D("0")
    for r in rows.select_related("account"):
        t = r.account.account_type
        if t == AccountType.REVENUE:
            net += r.credit - r.debit
        elif t in (AccountType.EXPENSE, AccountType.COST_OF_GOODS):
            net -= r.debit - r.credit
    return net


class PnlBase(LedgerBase):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.span = (self.today - timedelta(days=30), self.today + timedelta(days=30))

    def pnl(self, span=None):
        return ReportService.profit_and_loss(self.org, *(span or self.span))

    def acc(self, code):
        return Account.objects.get(organisation=self.org, code=code)

    def journal(self, source_type, lines, when=None, ref="T"):
        when = when or self.today
        return AccountingService.post_journal_entry(
            self.org, f"{source_type} test", when,
            [(self.acc(c), d, cr) for c, d, cr in lines], self.user,
            ref=f"{ref}-{source_type}", source_type=source_type,
            source_ref=f"{ref}-{source_type}-{when}")

    def payroll(self, when=None):
        # gross 200,000 + employer pension 16,000 + NSITF 2,000 = 218,000 salary cost
        return self.journal("payroll", [("6001", D("218000"), D("0")), ("2200", D("0"), D("20000")),
                                     ("2300", D("0"), D("32000")), ("2001", D("0"), D("166000"))], when)

    def depreciation(self, when=None):
        return self.journal("depreciation", [("6400", D("10000"), D("0")), ("1510", D("0"), D("10000"))], when)

    def bill(self, when=None):
        # rent 300,000 + claimable input VAT 22,500 = 322,500 owed
        return self.journal("bill_approved", [("6700", D("300000"), D("0")), ("1400", D("22500"), D("0")),
                                           ("2001", D("0"), D("322500"))], when)

    def expense(self, amount="100000"):
        cat = ExpenseCategory.objects.create(organisation=self.org, name="Fuel")
        e = Expense.objects.create(organisation=self.org, category=cat, amount=D(amount), description="Fuel",
                                   expense_date=self.today, recorded_by=self.user)
        AccountingService.post_expense_journal(self.org, e, self.user)
        return e


class CorrectedProfitTests(PnlBase):
    def test_payroll_depreciation_and_bills_are_in_the_profit_and_it_equals_the_ledger(self):
        self.sale()                      # revenue 2,000, cost 1,200
        self.expense()                   # 100,000
        self.payroll()
        self.depreciation()
        self.bill()
        p = self.pnl()
        self.assertEqual(p["revenue"]["gross_sales"], D("2000"))
        self.assertEqual(p["cost_of_goods_sold"], D("1200"))
        self.assertEqual(p["operating_expenses_breakdown"], {
            "logged_expenses": D("100000"), "supplier_bills": D("300000"),
            "payroll": D("218000"), "depreciation": D("10000"), "stock_adjustments": D("0"),
            "other_postings": D("0")})
        self.assertEqual(p["operating_expenses"], D("628000"))
        # 2,000 - 1,200 - 628,000
        self.assertEqual(p["net_profit"], D("-627200"))
        self.assertEqual(p["net_profit"], ledger_net_profit(self.org, *self.span))
        self.assertEqual(p["ledger_reconciliation"]["difference"], D("0"))

    def test_the_old_method_would_have_shown_a_smaller_loss(self):
        self.sale()
        self.expense()
        self.payroll()
        p = self.pnl()
        old = p["revenue"]["gross_sales"] - p["cost_of_goods_sold"] - D("100000")
        self.assertEqual(old, D("-99200"))
        self.assertEqual(p["net_profit"], D("-317200"))      # 2,000 - 1,200 - 100,000 - 218,000

    def test_claimable_input_vat_is_not_a_cost(self):
        self.bill()
        p = self.pnl()
        self.assertEqual(p["operating_expenses_breakdown"]["supplier_bills"], D("300000"))   # not 322,500

    def test_a_reversed_bill_leaves_the_profit(self):
        e = self.bill()
        AccountingService.reverse_journal_entry(e, self.user)
        p = self.pnl()
        self.assertEqual(p["operating_expenses_breakdown"]["supplier_bills"], D("0"))
        self.assertEqual(p["ledger_reconciliation"]["difference"], D("0"))

    def test_bill_dated_outside_the_period_is_left_out(self):
        self.bill(when=self.today - timedelta(days=90))
        self.assertEqual(self.pnl()["operating_expenses"], D("0"))

    def test_payments_do_not_change_profit(self):
        self.bill()
        before = self.pnl()["net_profit"]
        self.journal("bill_payment", [("2001", D("322500"), D("0")), ("1002", D("0"), D("322500"))])
        self.assertEqual(self.pnl()["net_profit"], before)

    def test_a_manual_journal_is_counted_as_other_postings_and_still_reconciles(self):
        self.journal("manual", [("6700", D("5000"), D("0")), ("1001", D("0"), D("5000"))])
        p = self.pnl()
        self.assertEqual(p["operating_expenses_breakdown"]["other_postings"], D("5000"))
        self.assertEqual(p["net_profit"], D("-5000"))
        self.assertEqual(p["ledger_reconciliation"]["difference"], D("0"))

    def test_a_sale_the_ledger_never_got_is_not_in_the_profit_and_is_counted_in_a_banner(self):
        from apps.sales.models import Invoice
        inv = self.sale()
        # pretend the sale was held back (account not mapped): no entry, flagged
        JournalEntry.objects.filter(organisation=self.org, source_type="sale").delete()
        Invoice.objects.filter(id=inv.id).update(gl_post_status="not_configured", gl_post_error="cogs_account")
        p = self.pnl()
        self.assertEqual(p["revenue"]["gross_sales"], D("0"))
        self.assertEqual(p["sales_not_in_books"]["count"], 1)
        self.assertEqual(p["sales_not_in_books"]["cost_missing_count"], 1)
        self.assertIn("not in your books", p["sales_not_in_books"]["message"])

    def test_a_return_comes_off_sales_and_cost_comes_back(self):
        inv = self.sale()
        item = inv.items.get()
        res = self.api.post(f"{URL}{inv.id}/process_return/", {
            "items": [{"sale_item_id": str(item.id), "quantity_returned": "1"}]}, format="json")
        self.assertIn(res.status_code, (200, 201), getattr(res, "data", None))
        p = self.pnl()
        self.assertEqual(p["revenue"]["returns"], D("1000"))
        self.assertEqual(p["revenue"]["gross_sales"], D("1000"))     # 2,000 - 1,000
        self.assertEqual(p["cost_of_goods_sold"], D("600"))          # 1,200 - 600 restocked
        self.assertEqual(p["ledger_reconciliation"]["difference"], D("0"))


class FulfilLaterTests(PnlBase):
    def test_undelivered_fulfil_later_sale_is_not_revenue_yet(self):
        inv = self.sale(defer_fulfillment=True)
        p = self.pnl()
        self.assertEqual(p["revenue"]["gross_sales"], D("0"))       # held in Customer Deposits 2050
        self.assertEqual(p["cost_of_goods_sold"], D("0"))
        self.assertEqual(p["net_profit"], ledger_net_profit(self.org, *self.span))
        self.assertEqual(self.api.post(f"{URL}{inv.id}/fulfill/").status_code, 200)
        p = self.pnl()
        self.assertEqual(p["revenue"]["gross_sales"], D("2000"))
        self.assertEqual(p["cost_of_goods_sold"], D("1200"))
        self.assertEqual(p["net_profit"], ledger_net_profit(self.org, *self.span))
        self.assertEqual(p["ledger_reconciliation"]["difference"], D("0"))

    def test_the_basis_is_the_ledger_and_says_so(self):
        p = self.pnl()
        self.assertEqual((p["basis"], p["fulfil_later_revenue_at"]), ("ledger", "delivery"))
        self.assertIn("not counted as sales until the goods are delivered", p["note"])

    def test_voided_sale_is_out(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        self.api.post(f"{URL}{inv.id}/void/")
        p = self.pnl()
        self.assertEqual((p["revenue"]["gross_sales"], p["net_profit"]), (D("0"), D("0")))
        self.assertEqual(p["ledger_reconciliation"]["difference"], D("0"))


class LagosEdgeTests(PnlBase):
    def test_a_delivery_just_after_midnight_lagos_is_in_the_next_day(self):
        inv = self.sale(defer_fulfillment=True, amount_paid="0")
        # 23:30 UTC on 31 Dec is 00:30 on 1 Jan in Lagos
        late = datetime(2026, 12, 31, 23, 30, tzinfo=dt_tz.utc)
        timezone.activate("Africa/Lagos")
        try:
            with patch("django.utils.timezone.now", return_value=late):
                self.assertEqual(self.api.post(f"{URL}{inv.id}/fulfill/").status_code, 200)
            dec = ReportService.profit_and_loss(self.org, date(2026, 12, 1), date(2026, 12, 31))
            jan = ReportService.profit_and_loss(self.org, date(2027, 1, 1), date(2027, 1, 31))
        finally:
            timezone.deactivate()
        self.assertEqual(dec["revenue"]["gross_sales"], D("0"))
        self.assertEqual(jan["revenue"]["gross_sales"], D("2000"))
        self.assertEqual(jan["ledger_reconciliation"]["difference"], D("0"))


class BalanceSheetAgreementTests(PnlBase):
    def test_current_year_earnings_equals_the_profit_for_the_same_year(self):
        self.sale()
        self.expense()
        self.payroll()
        self.depreciation()
        self.bill()
        year = (date(self.today.year, 1, 1), date(self.today.year, 12, 31))
        p = ReportService.profit_and_loss(self.org, *year)
        bs = AccountingService.balance_sheet(self.org, as_of=year[1])
        self.assertEqual(p["net_profit"], bs["current_year_earnings"])
        self.assertEqual(p["net_profit"], D("-627200"))


class ApiAndExportTests(PnlBase):
    def test_the_endpoint_returns_the_note_and_breakdown_and_the_export_lists_them(self):
        self.sale()
        self.payroll()
        self.depreciation()
        qs = {"period": "custom", "date_from": str(self.span[0]), "date_to": str(self.span[1])}
        res = self.api.get("/api/v1/reports/pnl/", qs)
        self.assertEqual(res.status_code, 200, getattr(res, "data", None))
        data = res.data
        self.assertIn("follows your books", data["note"])
        self.assertEqual(D(str(data["operating_expenses_breakdown"]["payroll"])), D("218000"))
        self.assertEqual(D(str(data["operating_expenses_breakdown"]["depreciation"])), D("10000"))
        self.assertEqual(D(str(data["ledger_reconciliation"]["difference"])), D("0"))
        xl = self.api.get("/api/v1/reports/pnl/", {**qs, "format": "excel"})
        self.assertEqual(xl.status_code, 200)
        import io
        from openpyxl import load_workbook
        ws = load_workbook(io.BytesIO(xl.content)).active
        cells = " | ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
        self.assertIn("Payroll", cells)
        self.assertIn("Depreciation", cells)
        self.assertIn("follows your books", cells)
        pdf = self.api.get("/api/v1/reports/pnl/", {**qs, "format": "pdf"})
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF"))


class StockAdjustmentLineTests(PnlBase):
    def adjust(self, qty):
        from apps.inventory.services import InventoryService
        return InventoryService.adjust_stock(self.org, self.taxed, self.wh, D(qty), "Damaged", self.user)

    def test_shrinkage_is_its_own_line_and_profit_still_equals_the_ledger(self):
        self.sale()                      # sales 2,000, cost of what was sold 1,200
        self.adjust("-3")                # 3 x 600 stock loss = 1,800 (account 5100, a cost-of-goods account)
        p = self.pnl()
        self.assertEqual(p["cost_of_goods_sold"], D("1200"))                          # sale cost only
        self.assertEqual(p["operating_expenses_breakdown"]["stock_adjustments"], D("1800"))
        self.assertEqual(p["operating_expenses"], D("1800"))
        self.assertEqual(p["net_profit"], D("-1000"))                                 # 2,000 - 1,200 - 1,800
        self.assertEqual(p["net_profit"], ledger_net_profit(self.org, *self.span))
        self.assertEqual(p["ledger_reconciliation"]["difference"], D("0"))

    def test_found_stock_is_a_gain_on_the_same_line(self):
        self.adjust("2")                 # 2 x 600 found: a gain of 1,200
        p = self.pnl()
        self.assertEqual(p["operating_expenses_breakdown"]["stock_adjustments"], D("-1200"))
        self.assertEqual(p["net_profit"], D("1200"))
        self.assertEqual(p["net_profit"], ledger_net_profit(self.org, *self.span))

    def test_a_stock_loss_at_23_30_utc_is_dated_on_the_lagos_day(self):
        late = datetime(2026, 12, 31, 23, 30, tzinfo=dt_tz.utc)         # 00:30 on 1 Jan in Lagos
        timezone.activate("Africa/Lagos")
        try:
            with patch("django.utils.timezone.now", return_value=late):
                self.adjust("-1")
        finally:
            timezone.deactivate()
        entry = JournalEntry.objects.get(organisation=self.org, source_type="stock_adjustment")
        self.assertEqual(entry.entry_date, date(2027, 1, 1))
