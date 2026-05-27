"""
Reporting API views.

All report endpoints are GET-only and accept:
  ?period=today|week|month|year|all|custom   (new — shortcut)
  ?date_from=YYYY-MM-DD                       (used when period=custom)
  ?date_to=YYYY-MM-DD                         (used when period=custom)
  ?format=json|excel|pdf                      (new — triggers file download)

The ?format param is handled by each view via _export_or_json().
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAccountant

from .exporters import dispatch_export
from .period_utils import period_label, resolve_period
from .services import ReportService


# ─── Base ─────────────────────────────────────────────────────────────────────


class BaseDateRangeView(APIView):
    """
    Base view that resolves the period / date range from query params and
    provides a helper for optionally returning an export file instead of JSON.
    """

    permission_classes = [IsAuthenticated, IsAccountant]

    def get_date_range(self, request):
        """Return (date_from, date_to) — both None when period='all'."""
        period = request.query_params.get("period", "custom")
        date_from_str = request.query_params.get("date_from")
        date_to_str = request.query_params.get("date_to")
        return resolve_period(period, date_from_str, date_to_str)

    def get_period_label(self, request, date_from=None, date_to=None) -> str:
        period = request.query_params.get("period", "custom")
        return period_label(period, date_from, date_to)

    def _export_or_json(self, request, data, *, headers, row_fn, title, filename_base):
        """
        If ?format=excel|pdf, build an export file and return HttpResponse.
        Otherwise return a DRF Response with *data* as JSON.

        Args:
            data:          The report payload (list or dict).
            headers:       List of column header strings for the export.
            row_fn:        Callable(data) → list[list] converting data to rows.
            title:         Report title for PDF / Excel sheet name.
            filename_base: Filename without extension.
        """
        fmt = request.query_params.get("format", "json").lower()
        if fmt in ("excel", "pdf"):
            date_from, date_to = self.get_date_range(request)
            subtitle = self.get_period_label(request, date_from, date_to)
            rows = row_fn(data)
            response = dispatch_export(
                fmt=fmt,
                headers=headers,
                rows=rows,
                title=title,
                subtitle=subtitle,
                filename_base=filename_base,
            )
            if response is not None:
                return response
        return Response(data)


# ─── Sales Summary ────────────────────────────────────────────────────────────


class SalesSummaryView(BaseDateRangeView):
    """GET /api/v1/reports/sales/ — Sales summary by period."""

    _HEADERS = ["Period", "Revenue", "Tax Collected", "Discount", "Invoice Count"]

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        group_by = request.query_params.get("group_by", "day")
        data = list(ReportService.sales_summary(request.organisation, date_from, date_to, group_by))

        def _rows(d):
            return [
                [
                    str(r.get("period", "")),
                    r.get("total_revenue"),
                    r.get("total_tax"),
                    r.get("total_discount"),
                    r.get("invoice_count"),
                ]
                for r in d
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Sales Summary",
            filename_base="sales_summary",
        )


# ─── Top Products ─────────────────────────────────────────────────────────────


class TopProductsView(BaseDateRangeView):
    """GET /api/v1/reports/top-products/ — Best-selling products."""

    _HEADERS = ["Product", "SKU", "Units Sold", "Revenue", "COGS", "Gross Profit"]

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        limit = int(request.query_params.get("limit", 10))
        data = ReportService.top_products(request.organisation, date_from, date_to, limit)

        def _rows(d):
            return [
                [r["product_name"], r["product_sku"], r["units_sold"],
                 r["revenue"], r["cogs"], r["gross_profit"]]
                for r in d
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Top Products",
            filename_base="top_products",
        )


# ─── Top Customers ────────────────────────────────────────────────────────────


class TopCustomersView(BaseDateRangeView):
    """GET /api/v1/reports/top-customers/ — Top customers by revenue."""

    _HEADERS = ["Customer", "Code", "Invoice Count", "Revenue"]

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        limit = int(request.query_params.get("limit", 10))
        data = ReportService.top_customers(request.organisation, date_from, date_to, limit)

        def _rows(d):
            return [
                [r["customer_name"], r["customer_code"], r["invoice_count"], r["revenue"]]
                for r in d
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Top Customers",
            filename_base="top_customers",
        )


# ─── Profit & Loss ────────────────────────────────────────────────────────────


class ProfitAndLossView(BaseDateRangeView):
    """GET /api/v1/reports/pnl/ — Profit & Loss statement."""

    _HEADERS = ["Line Item", "Amount (₦)"]

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        data = ReportService.profit_and_loss(request.organisation, date_from, date_to)

        def _rows(d):
            rev = d.get("revenue", {})
            return [
                ["Gross Sales", rev.get("gross_sales", 0)],
                ["Tax Collected", rev.get("tax_collected", 0)],
                ["Discounts", rev.get("discounts", 0)],
                ["Cost of Goods Sold", d.get("cost_of_goods_sold", 0)],
                ["Gross Profit", d.get("gross_profit", 0)],
                ["Gross Margin %", d.get("gross_margin_pct", 0)],
                ["Operating Expenses", d.get("operating_expenses", 0)],
                ["Miscellaneous Income", d.get("miscellaneous_income", 0)],
                ["Net Profit", d.get("net_profit", 0)],
                ["Net Margin %", d.get("net_margin_pct", 0)],
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Profit & Loss Statement",
            filename_base="profit_and_loss",
        )


# ─── Expense Breakdown ────────────────────────────────────────────────────────


class ExpenseBreakdownView(BaseDateRangeView):
    """GET /api/v1/reports/expenses/ — Expenses by category."""

    _HEADERS = ["Category", "Total (₦)", "Count"]

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        data = ReportService.expense_breakdown(request.organisation, date_from, date_to)

        def _rows(d):
            return [[r["category_name"], r["total"], r["count"]] for r in d]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Expense Breakdown",
            filename_base="expense_breakdown",
        )


# ─── Inventory Valuation ──────────────────────────────────────────────────────


class InventoryValuationView(BaseDateRangeView):
    """GET /api/v1/reports/inventory/ — Current inventory valuation."""

    _HEADERS = ["Product", "SKU", "Warehouse", "Qty", "Unit Cost (₦)", "Total Value (₦)"]

    def get(self, request):
        data = ReportService.inventory_valuation(request.organisation)

        def _rows(d):
            return [
                [i["product"], i["sku"], i["warehouse"],
                 i["quantity"], i["unit_cost"], i["total_value"]]
                for i in d.get("items", [])
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Inventory Valuation",
            filename_base="inventory_valuation",
        )


# ─── Cash Flow ────────────────────────────────────────────────────────────────


class CashFlowView(BaseDateRangeView):
    """GET /api/v1/reports/cash-flow/ — Cash flow for period."""

    _HEADERS = ["Line Item", "Amount (₦)"]

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        data = ReportService.cash_flow(request.organisation, date_from, date_to)

        def _rows(d):
            return [
                ["Cash Inflows", d.get("cash_inflows", 0)],
                ["Cash Outflows", d.get("cash_outflows", 0)],
                ["Net Cash Flow", d.get("net_cash_flow", 0)],
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Cash Flow Statement",
            filename_base="cash_flow",
        )


# ─── AR Aging ─────────────────────────────────────────────────────────────────


class ARAgingView(BaseDateRangeView):
    """GET /api/v1/reports/ar-aging/ — Accounts receivable aging buckets."""

    _HEADERS = ["Invoice #", "Customer", "Amount Due (₦)", "Due Date", "Days Overdue"]

    def get(self, request):
        from datetime import date, datetime

        as_of_str = request.query_params.get("as_of")
        try:
            as_of = datetime.strptime(as_of_str, "%Y-%m-%d").date() if as_of_str else date.today()
        except ValueError:
            as_of = date.today()

        data = ReportService.ar_aging(request.organisation, as_of)

        def _rows(d):
            return [
                [i["invoice_number"], i["customer_name"],
                 i["amount_due"], i["due_date"], i["days_overdue"]]
                for i in d.get("invoices", [])
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Accounts Receivable Aging",
            filename_base="ar_aging",
        )


# ─── AP Aging ─────────────────────────────────────────────────────────────────


class APAgingView(BaseDateRangeView):
    """GET /api/v1/reports/ap-aging/ — Accounts payable aging buckets."""

    _HEADERS = ["Bill #", "Supplier", "Amount Due (₦)", "Due Date", "Days Overdue"]

    def get(self, request):
        from datetime import date, datetime

        as_of_str = request.query_params.get("as_of")
        try:
            as_of = datetime.strptime(as_of_str, "%Y-%m-%d").date() if as_of_str else date.today()
        except ValueError:
            as_of = date.today()

        data = ReportService.ap_aging(request.organisation, as_of)

        def _rows(d):
            return [
                [i["bill_number"], i["supplier_name"],
                 i["amount_due"], i["due_date"], i["days_overdue"]]
                for i in d.get("bills", [])
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Accounts Payable Aging",
            filename_base="ap_aging",
        )


# ─── VAT Summary ─────────────────────────────────────────────────────────────


class VATSummaryView(BaseDateRangeView):
    """GET /api/v1/reports/vat-summary/ — VAT output vs input summary."""

    _HEADERS = ["Line Item", "Amount (₦)"]

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        data = ReportService.vat_summary(request.organisation, date_from, date_to)

        def _rows(d):
            return [
                ["Output VAT (Collected on Sales)", d.get("output_vat", 0)],
                ["Input VAT (Paid on Bills)", d.get("input_vat", 0)],
                ["Net VAT Payable", d.get("net_vat_payable", 0)],
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="VAT Summary",
            filename_base="vat_summary",
        )
