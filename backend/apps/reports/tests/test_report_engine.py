"""Tests for the unified report engine (registry-backed dispatch)."""
from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.accounting.models import Account, AccountType
from apps.accounting.services import AccountingService

from .test_views import BaseReportTestCase


class ReportEngineTests(BaseReportTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.bank = Account.objects.create(
            organisation=cls.org, code="1002", name="Bank", account_type=AccountType.ASSET)
        cls.revenue = Account.objects.create(
            organisation=cls.org, code="4001", name="Sales Revenue", account_type=AccountType.REVENUE)
        cls.equity = Account.objects.create(
            organisation=cls.org, code="3001", name="Owner Equity", account_type=AccountType.EQUITY)
        # One balanced posted journal in-period.
        AccountingService.post_journal_entry(
            cls.org, "Sale", date(2026, 6, 15),
            [(cls.bank, Decimal("1000"), Decimal("0")),
             (cls.revenue, Decimal("0"), Decimal("1000"))],
            cls.user, ref="JE-T1",
        )

    def _dispatch(self, key, **query):
        self._auth()
        url = reverse("report-dispatch", kwargs={"key": key})
        return self.client.get(url, query)

    def test_catalog_lists_registered_reports(self):
        self._auth()
        res = self.client.get(reverse("report-catalog"))
        self.assertEqual(res.status_code, 200)
        keys = [r["key"] for r in res.data["reports"]]
        for expected in ("gl-detail", "journal-register", "changes-in-equity", "notes"):
            self.assertIn(expected, keys)

    def test_unknown_report_returns_404(self):
        res = self._dispatch("does-not-exist")
        self.assertEqual(res.status_code, 404)

    def test_journal_register_lists_entry(self):
        res = self._dispatch("journal-register", period="custom",
                             date_from="2026-01-01", date_to="2026-12-31")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        data = res.data["data"]
        self.assertEqual(len(data["entries"]), 1)
        self.assertEqual(Decimal(str(data["total_debit"])), Decimal("1000"))
        self.assertEqual(Decimal(str(data["total_credit"])), Decimal("1000"))

    def test_gl_detail_running_balance(self):
        res = self._dispatch("gl-detail", period="custom",
                             date_from="2026-01-01", date_to="2026-12-31",
                             account_id=str(self.bank.id))
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        accounts = res.data["data"]["accounts"]
        self.assertEqual(len(accounts), 1)
        sec = accounts[0]
        self.assertEqual(sec["account_code"], "1002")
        self.assertEqual(len(sec["lines"]), 1)
        # Bank is debit-normal: running balance after a 1000 debit is 1000.
        self.assertEqual(Decimal(str(sec["lines"][0]["balance"])), Decimal("1000"))
        self.assertEqual(Decimal(str(sec["closing_balance"])), Decimal("1000"))

    def test_changes_in_equity_includes_unclosed_profit(self):
        res = self._dispatch("changes-in-equity", period="custom",
                             date_from="2026-01-01", date_to="2026-12-31")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["data"]["rows"]
        # The 1000 revenue (unclosed) shows as a profit-for-the-period movement.
        names = [r["account_name"] for r in rows]
        self.assertIn("Profit for the period (unclosed)", names)
        profit_row = next(r for r in rows if r["account_name"].startswith("Profit"))
        self.assertEqual(Decimal(str(profit_row["movement"])), Decimal("1000"))
