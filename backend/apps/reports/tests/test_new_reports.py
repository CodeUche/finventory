"""Tests for the nav-reorg report resolvers (spec: Audity – Nav. Bar Rearrangement).

Every new registry-backed report is dispatched through /reports/r/<key>/ with
real fixture data, asserting correct totals, date filtering and shape. A final
test asserts the full catalog matches the reviewer's category tree.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.urls import reverse

from apps.accounting.models import Account, AccountType, DepreciationEntry, FixedAsset
from apps.accounting.services import AccountingService
from apps.bills.models import Bill, BillPayment
from apps.customers.models import Customer
from apps.expenses.models import Expense, ExpenseCategory
from apps.inventory.models import Product, StockItem, Warehouse
from apps.payroll.models import Attendance, Employee, PayrollRun
from apps.purchases.models import PurchaseOrder, PurchaseOrderItem
from apps.sales.models import Invoice, SalePayment
from apps.suppliers.models import Supplier

from .test_views import BaseReportTestCase

PERIOD = {"period": "custom", "date_from": "2026-01-01", "date_to": "2026-12-31"}


class NewReportsBase(BaseReportTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        org, user = cls.org, cls.user

        # ── Accounting fixtures ──
        cls.cash = Account.objects.create(
            organisation=org, code="1000", name="Cash on Hand", account_type=AccountType.ASSET)
        cls.revenue = Account.objects.create(
            organisation=org, code="4000", name="Sales Revenue", account_type=AccountType.REVENUE)
        AccountingService.post_journal_entry(
            org, "Cash sale", date(2026, 3, 10),
            [(cls.cash, Decimal("500"), Decimal("0")),
             (cls.revenue, Decimal("0"), Decimal("500"))],
            user, ref="JE-NR1",
        )

        # ── Supplier / bills ──
        cls.supplier = Supplier.objects.create(organisation=org, name="Acme Supplies")
        cls.bill = Bill.objects.create(
            organisation=org, supplier=cls.supplier, status=Bill.APPROVED,
            issue_date=date(2026, 4, 1), due_date=date(2026, 5, 1),
            subtotal=Decimal("200"), tax_amount=Decimal("15"),
            total_amount=Decimal("215"), amount_due=Decimal("115"),
            amount_paid=Decimal("100"), created_by=user,
        )
        BillPayment.objects.create(
            organisation=org, bill=cls.bill, amount=Decimal("100"),
            payment_date=date(2026, 4, 15), method="cash", recorded_by=user,
        )

        # ── Expenses (out + misc income) ──
        cat = ExpenseCategory.objects.create(organisation=org, name="Utilities")
        Expense.objects.create(
            organisation=org, category=cat, amount=Decimal("50"),
            description="Electricity", expense_date=date(2026, 4, 20),
            recorded_by=user,
        )
        Expense.objects.create(
            organisation=org, category=cat, amount=Decimal("75"),
            description="Sundry income", expense_date=date(2026, 4, 22),
            is_income=True, recorded_by=user,
        )

        # ── Inventory ──
        cls.warehouse = Warehouse.objects.create(organisation=org, name="Main WH")
        cls.product = Product.objects.create(
            organisation=org, sku="SKU-1", name="Widget",
            cost_price=Decimal("10"), selling_price=Decimal("20"),
        )
        StockItem.objects.create(
            organisation=org, product=cls.product, warehouse=cls.warehouse,
            quantity_on_hand=Decimal("40"),
        )

        # ── Customer / invoice / receipt ──
        cls.customer = Customer.objects.create(organisation=org, name="Jane Buyer")
        cls.invoice = Invoice.objects.create(
            organisation=org, customer=cls.customer, status="paid",
            warehouse=cls.warehouse,
            issue_date=date(2026, 5, 2), due_date=date(2026, 5, 2),
            subtotal=Decimal("300"), total_amount=Decimal("300"),
            amount_paid=Decimal("300"), created_by=user,
        )
        SalePayment.objects.create(
            organisation=org, invoice=cls.invoice, amount=Decimal("300"),
            method="cash", received_by=user,
        )

        # ── Purchase order (for product purchases) ──
        po = PurchaseOrder.objects.create(
            organisation=org, supplier=cls.supplier, status="received",
            warehouse=cls.warehouse,
            order_date=date(2026, 4, 5), created_by=user,
        )
        PurchaseOrderItem.objects.create(
            organisation=org, purchase_order=po, product=cls.product,
            quantity_ordered=Decimal("10"), quantity_received=Decimal("10"),
            unit_cost=Decimal("10"),
        )

        # ── Fixed asset + depreciation ──
        cls.asset = FixedAsset.objects.create(
            organisation=org, name="Delivery Van", asset_code="FA-001",
            category="vehicle", purchase_date=date(2026, 1, 15),
            purchase_cost=Decimal("1200"), depreciation_method="straight_line",
            useful_life_years=5,
        )
        DepreciationEntry.objects.create(
            organisation=org, asset=cls.asset, period_year=2026, period_month=2,
            depreciation_amount=Decimal("20"), accumulated_to_date=Decimal("20"),
            net_book_value=Decimal("1180"),
        )

        # ── Payroll ──
        cls.employee = Employee.objects.create(
            organisation=org, first_name="Tunde", last_name="Ade",
            job_title="Clerk", hire_date=date(2025, 6, 1),
            basic_salary=Decimal("100000"),
        )
        PayrollRun.objects.create(
            organisation=org, period_year=2026, period_month=3, status="paid",
            total_gross=Decimal("100000"), total_deductions=Decimal("20000"),
            total_net=Decimal("80000"), total_paye=Decimal("7000"),
            processed_by=user,
        )
        Attendance.objects.create(
            organisation=org, employee=cls.employee,
            date=date(2026, 3, 3), status="present",
            overtime_hours=Decimal("2.5"),
        )
        Attendance.objects.create(
            organisation=org, employee=cls.employee,
            date=date(2026, 3, 4), status="absent",
        )

    def _dispatch(self, key, **extra):
        self._auth()
        url = reverse("report-dispatch", kwargs={"key": key})
        return self.client.get(url, {**PERIOD, **extra})


class FinancialStatementReports(NewReportsBase):
    def test_profit_loss(self):
        res = self._dispatch("profit-loss")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertIn("data", res.data)

    def test_cash_flow(self):
        res = self._dispatch("cash-flow")
        self.assertEqual(res.status_code, 200, msg=str(res.data))

    def test_balance_sheet(self):
        res = self._dispatch("balance-sheet")
        self.assertEqual(res.status_code, 200, msg=str(res.data))

    def test_trial_balance(self):
        res = self._dispatch("trial-balance")
        self.assertEqual(res.status_code, 200, msg=str(res.data))

    def test_tax_summary(self):
        res = self._dispatch("tax-summary")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        d = res.data["data"]
        self.assertIn("vat", d)
        self.assertEqual(Decimal(str(d["paye_payable"])), Decimal("7000"))


class GeneralLedgerReports(NewReportsBase):
    def test_account_list_has_balances(self):
        res = self._dispatch("account-list")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["data"]["rows"]
        cash = next(r for r in rows if r["code"] == "1000")
        self.assertEqual(Decimal(str(cash["balance"])), Decimal("500"))

    def test_cash_register_covers_cash_accounts(self):
        res = self._dispatch("cash-register")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        accounts = res.data["data"]["accounts"]
        self.assertTrue(any(a["account_code"] == "1000" for a in accounts))
        cash_sec = next(a for a in accounts if a["account_code"] == "1000")
        self.assertEqual(Decimal(str(cash_sec["closing_balance"])), Decimal("500"))

    def test_pay_bills_report_totals(self):
        res = self._dispatch("pay-bills")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        d = res.data["data"]
        self.assertEqual(len(d["rows"]), 1)
        self.assertEqual(Decimal(str(d["total"])), Decimal("100"))
        self.assertEqual(d["rows"][0]["supplier"], "Acme Supplies")

    def test_deposit_report_combines_receipts_and_income(self):
        res = self._dispatch("deposits")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        d = res.data["data"]
        # 300 customer receipt + 75 misc income
        self.assertEqual(Decimal(str(d["total"])), Decimal("375"))
        sources = {r["source"] for r in d["rows"]}
        self.assertEqual(sources, {"Customer receipt", "Other income"})

    def test_payments_out_combines_bills_and_expenses(self):
        res = self._dispatch("payments")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        d = res.data["data"]
        # 100 bill payment + 50 expense (misc income excluded)
        self.assertEqual(Decimal(str(d["total"])), Decimal("150"))

    def test_payments_respects_date_filter(self):
        res = self._dispatch("payments", date_from="2026-06-01", date_to="2026-12-31")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(Decimal(str(res.data["data"]["total"])), Decimal("0"))


class ReceivablePayableReports(NewReportsBase):
    def test_sales_by_customer(self):
        res = self._dispatch("sales-by-customer")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["data"]["rows"]
        self.assertTrue(any(r["customer_name"] == "Jane Buyer" for r in rows))

    def test_customers_report(self):
        res = self._dispatch("customers-report")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertTrue(len(res.data["data"]["rows"]) >= 1)

    def test_customer_receipts_org_wide(self):
        """Regression: this used to 422 — it called a per-customer service org-wide."""
        res = self._dispatch("customer-receipts")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        d = res.data["data"]
        self.assertEqual(Decimal(str(d["total"])), Decimal("300"))
        self.assertEqual(d["rows"][0]["customer"], "Jane Buyer")

    def test_purchases_report_totals(self):
        res = self._dispatch("purchases-report")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        d = res.data["data"]
        self.assertEqual(len(d["rows"]), 1)
        self.assertEqual(Decimal(str(d["total"])), Decimal("215"))
        self.assertEqual(Decimal(str(d["tax"])), Decimal("15"))

    def test_product_purchases_grouped(self):
        res = self._dispatch("product-purchases")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        d = res.data["data"]
        self.assertEqual(len(d["rows"]), 1)
        row = d["rows"][0]
        self.assertEqual(row["product_sku"], "SKU-1")
        self.assertEqual(Decimal(str(row["total_cost"])), Decimal("100"))

    def test_suppliers_report_outstanding(self):
        res = self._dispatch("suppliers-report")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["data"]["rows"]
        acme = next(r for r in rows if r["name"] == "Acme Supplies")
        self.assertEqual(Decimal(str(acme["outstanding"])), Decimal("115"))


class InventoryReports(NewReportsBase):
    def test_stock_report(self):
        res = self._dispatch("stock-report")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["data"]["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(Decimal(str(rows[0]["quantity"])), Decimal("40"))

    def test_stock_valuation(self):
        res = self._dispatch("stock-valuation")
        self.assertEqual(res.status_code, 200, msg=str(res.data))


class FixedAssetReports(NewReportsBase):
    def test_asset_register(self):
        res = self._dispatch("asset-register")
        self.assertEqual(res.status_code, 200, msg=str(res.data))

    def test_assets_by_category(self):
        res = self._dispatch("assets-by-category")
        self.assertEqual(res.status_code, 200, msg=str(res.data))

    def test_assets_by_location(self):
        res = self._dispatch("assets-by-location")
        self.assertEqual(res.status_code, 200, msg=str(res.data))

    def test_depreciation_report_rows(self):
        res = self._dispatch("depreciation-report")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        d = res.data["data"]
        self.assertEqual(len(d["rows"]), 1)
        self.assertEqual(Decimal(str(d["total"])), Decimal("20"))
        self.assertEqual(d["rows"][0]["period"], "2026-02")

    def test_depreciation_method_grouping(self):
        res = self._dispatch("depreciation-method")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["data"]["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["assets"], 1)
        self.assertEqual(Decimal(str(rows[0]["total_cost"])), Decimal("1200"))


class PayrollReports(NewReportsBase):
    def test_employee_list(self):
        res = self._dispatch("employee-list")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["data"]["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Tunde Ade")

    def test_payroll_report_totals(self):
        res = self._dispatch("payroll-report")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        d = res.data["data"]
        self.assertEqual(len(d["rows"]), 1)
        self.assertEqual(Decimal(str(d["totals"]["net"])), Decimal("80000"))
        self.assertEqual(Decimal(str(d["totals"]["paye"])), Decimal("7000"))

    def test_attendance_summary_counts(self):
        res = self._dispatch("attendance-summary")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data["data"]["rows"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["present"], 1)
        # A.7: the 'absent' bucket was split into paid_leave / unpaid_leave_absent
        # to distinguish approved paid leave (Attendance.status='leave') from
        # true unpaid absence (Attendance.status='absent').
        self.assertEqual(row["unpaid_leave_absent"], 1)
        self.assertEqual(Decimal(str(row["overtime_hours"])), Decimal("2.5"))


class CatalogTreeMatchesSpec(NewReportsBase):
    """The catalog must expose exactly the reviewer's category tree."""

    EXPECTED = {
        "Financial Statements": {
            "profit-loss", "cash-flow", "balance-sheet", "trial-balance",
            "vat-return", "tax-summary",
        },
        "General Ledger": {
            "account-list", "cash-register", "pay-bills", "deposits",
            "gl-tax-summary", "gl-detail", "payments", "journal-register",
        },
        "Accounts Receivable": {
            "sales-by-customer", "customers-report", "customer-receipts",
        },
        "Accounts Payable": {
            "purchases-report", "purchase-returns", "product-purchases",
            "suppliers-report",
        },
        "Inventory": {"stock-report", "stock-valuation"},
        "Fixed Assets": {
            "asset-register", "assets-by-category", "assets-by-location",
            "depreciation-report", "depreciation-method",
        },
        "Payroll & HR": {"employee-list", "payroll-report", "attendance-summary"},
        "Accountant Reports": {"financial-report-pack", "changes-in-equity", "notes"},
    }

    def test_catalog_matches_spec_tree(self):
        self._auth()
        res = self.client.get(reverse("report-catalog"))
        self.assertEqual(res.status_code, 200)
        actual: dict = {}
        for r in res.data["reports"]:
            actual.setdefault(r["category"], set()).add(r["key"])
        self.assertEqual(actual, self.EXPECTED)

    def test_every_report_dispatches_without_error(self):
        """Smoke: every catalog key returns 200 with fixture data present."""
        self._auth()
        res = self.client.get(reverse("report-catalog"))
        for r in res.data["reports"]:
            with self.subTest(key=r["key"]):
                out = self._dispatch(r["key"])
                self.assertEqual(out.status_code, 200, msg=str(out.data))

    def test_row_based_report_exports_to_excel(self):
        self._auth()
        url = reverse("report-dispatch", kwargs={"key": "pay-bills"})
        res = self.client.get(url, {**PERIOD, "format": "excel"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("spreadsheetml", res["Content-Type"])

    def test_row_based_report_exports_to_pdf(self):
        self._auth()
        url = reverse("report-dispatch", kwargs={"key": "pay-bills"})
        res = self.client.get(url, {**PERIOD, "format": "pdf"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/pdf")

    def test_non_row_report_json_shape_unaffected(self):
        """Nested reports (no flat top-level `rows`) still return their normal
        nested JSON shape when format=json — only the export path changed."""
        self._auth()
        url = reverse("report-dispatch", kwargs={"key": "gl-detail"})
        res = self.client.get(url, PERIOD)
        self.assertEqual(res.status_code, 200)
        self.assertIn("data", res.data)
        self.assertIn("accounts", res.data["data"])

    def test_nested_report_now_exports_to_excel(self):
        """flatten_for_export() (apps/reports/exporters.py) knows how to turn
        gl-detail's nested {accounts: [{..., lines: [...]}]} shape into a flat
        table, so this — previously JSON-only — now exports a real workbook
        instead of silently falling back to JSON."""
        self._auth()
        url = reverse("report-dispatch", kwargs={"key": "gl-detail"})
        res = self.client.get(url, {**PERIOD, "format": "excel"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("spreadsheetml", res["Content-Type"])

        import io
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        ws = wb.active
        cell_values = [c.value for row in ws.iter_rows() for c in row if c.value is not None]
        # The Cash on Hand account (code 1000) from setUpTestData should
        # appear somewhere in the flattened sheet.
        self.assertTrue(any(v == "1000" for v in cell_values))

    def test_nested_report_now_exports_to_pdf(self):
        """Same normalisation also unblocks the PDF export path."""
        self._auth()
        url = reverse("report-dispatch", kwargs={"key": "gl-detail"})
        res = self.client.get(url, {**PERIOD, "format": "pdf"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/pdf")

    def test_tenant_isolation(self):
        """Another org's user must see empty data, not ours."""
        from apps.reports.tests.test_views import _make_superuser, _make_org
        other = _make_superuser(suffix="_iso_nr")
        other_org = _make_org(owner=other)
        self.client.force_authenticate(user=other)
        self.client.credentials(HTTP_X_ORGANISATION_ID=str(other_org.id))
        url = reverse("report-dispatch", kwargs={"key": "pay-bills"})
        res = self.client.get(url, PERIOD)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(len(res.data["data"]["rows"]), 0)
