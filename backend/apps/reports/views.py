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

from apps.core.permissions import IsStaff

from .exporters import dispatch_export
from .period_utils import period_label, resolve_period
from .services import ReportService

# ─── Base ─────────────────────────────────────────────────────────────────────


class BaseDateRangeView(APIView):
    """
    Base view that resolves the period / date range from query params and
    provides a helper for optionally returning an export file instead of JSON.
    """

    permission_classes = [IsAuthenticated, IsStaff]

    def get_organisation(self):
        """
        Resolve and return the current organisation.

        IsStaff short-circuits for superusers without calling resolve_organisation(),
        leaving request.organisation=None. This method always resolves it so that
        report queries have the correct org even for superusers.
        """
        if getattr(self.request, "organisation", None) is not None:
            return self.request.organisation
        from apps.tenancy.middleware import resolve_organisation
        return resolve_organisation(self.request)

    def get_date_range(self, request):
        """Return (date_from, date_to) — both None when period='all'."""
        period = request.query_params.get("period", "custom")
        date_from_str = request.query_params.get("date_from")
        date_to_str = request.query_params.get("date_to")
        return resolve_period(period, date_from_str, date_to_str)

    def get_period_label(self, request, date_from=None, date_to=None) -> str:
        period = request.query_params.get("period", "custom")
        return period_label(period, date_from, date_to)

    def get_limit(self, request, default=10, max_limit=100) -> int:
        """Parse and clamp the ?limit= query param to [1, max_limit]."""
        try:
            limit = int(request.query_params.get("limit", default))
        except (TypeError, ValueError):
            limit = default
        return max(1, min(limit, max_limit))

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
                org=self.get_organisation(),
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
        data = list(ReportService.sales_summary(self.get_organisation(), date_from, date_to, group_by))

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
        limit = self.get_limit(request)
        data = ReportService.top_products(self.get_organisation(), date_from, date_to, limit)

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
        limit = self.get_limit(request)
        data = ReportService.top_customers(self.get_organisation(), date_from, date_to, limit)

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
        data = ReportService.profit_and_loss(self.get_organisation(), date_from, date_to)

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
        data = ReportService.expense_breakdown(self.get_organisation(), date_from, date_to)

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
        data = ReportService.inventory_valuation(self.get_organisation())

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
        data = ReportService.cash_flow(self.get_organisation(), date_from, date_to)

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

        data = ReportService.ar_aging(self.get_organisation(), as_of)

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

        data = ReportService.ap_aging(self.get_organisation(), as_of)

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
        data = ReportService.vat_summary(self.get_organisation(), date_from, date_to)

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


# ─── Sales by Customer ────────────────────────────────────────────────────────


class SalesByCustomerView(BaseDateRangeView):
    """
    GET /api/v1/reports/sales-by-customer/           — all customers with totals
    GET /api/v1/reports/sales-by-customer/?customer_id=<uuid>   — invoices for one customer
    GET /api/v1/reports/sales-by-customer/?customer_id=walk-in  — walk-in invoices
    """

    _SUMMARY_HEADERS = ["Customer", "Code", "Invoices", "Revenue (₦)", "Paid (₦)", "Outstanding (₦)"]
    _DETAIL_HEADERS  = ["Invoice #", "Date", "Status", "Total (₦)", "Paid (₦)", "Due (₦)"]

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        customer_id = request.query_params.get("customer_id")

        if customer_id:
            # Detail mode: invoices for one customer
            cid = None if customer_id == "walk-in" else customer_id
            data = ReportService.customer_invoices(self.get_organisation(), cid, date_from, date_to)

            def _rows(d):
                return [
                    [r["invoice_number"], str(r["issue_date"]), r["status"],
                     r["total_amount"], r["amount_paid"], r["amount_due"]]
                    for r in d
                ]

            return self._export_or_json(
                request, data,
                headers=self._DETAIL_HEADERS,
                row_fn=_rows,
                title="Customer Invoices",
                filename_base="customer_invoices",
            )

        # Summary mode
        data = ReportService.sales_by_customer(self.get_organisation(), date_from, date_to)

        def _rows(d):
            return [
                [r["customer_name"], r["customer_code"] or "",
                 r["invoice_count"], r["revenue"],
                 r["amount_paid"], r["amount_outstanding"]]
                for r in d
            ]

        return self._export_or_json(
            request, data,
            headers=self._SUMMARY_HEADERS,
            row_fn=_rows,
            title="Sales by Customer",
            filename_base="sales_by_customer",
        )


# ─── Sales by Product ─────────────────────────────────────────────────────────


class SalesByProductView(BaseDateRangeView):
    """
    GET /api/v1/reports/sales-by-product/            — all products with totals
    GET /api/v1/reports/sales-by-product/?product_id=<uuid>   — sale lines for one product
    """

    _SUMMARY_HEADERS = ["Product", "SKU", "Units Sold", "Revenue (₦)", "COGS (₦)", "Gross Profit (₦)"]
    _DETAIL_HEADERS  = ["Invoice #", "Date", "Customer", "Qty", "Unit Price (₦)", "Line Total (₦)"]

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        product_id = request.query_params.get("product_id")

        if product_id:
            data = ReportService.product_sale_lines(self.get_organisation(), product_id, date_from, date_to)

            def _rows(d):
                return [
                    [r["invoice_number"], str(r["issue_date"]), r["customer_name"],
                     r["quantity"], r["unit_price"], r["line_total"]]
                    for r in d
                ]

            return self._export_or_json(
                request, data,
                headers=self._DETAIL_HEADERS,
                row_fn=_rows,
                title="Product Sale Lines",
                filename_base="product_sale_lines",
            )

        data = ReportService.sales_by_product(self.get_organisation(), date_from, date_to)

        def _rows(d):
            return [
                [r["product_name"], r["product_sku"] or "",
                 r["units_sold"], r["revenue"], r["cogs"], r["gross_profit"]]
                for r in d
            ]

        return self._export_or_json(
            request, data,
            headers=self._SUMMARY_HEADERS,
            row_fn=_rows,
            title="Sales by Product",
            filename_base="sales_by_product",
        )


# ─── Payment Method Breakdown ─────────────────────────────────────────────────


class PaymentMethodsView(BaseDateRangeView):
    """GET /api/v1/reports/payment-methods/ — Revenue by payment method."""

    _HEADERS = ["Method", "Total (₦)", "Transactions"]

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        data = ReportService.payment_methods(self.get_organisation(), date_from, date_to)

        def _rows(d):
            return [[r["label"], r["total"], r["count"]] for r in d]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Payment Method Breakdown",
            filename_base="payment_methods",
        )


# ─── Customer Balance ──────────────────────────────────────────────────────


class CustomerBalanceView(BaseDateRangeView):
    """GET /api/v1/reports/customer-balance/ — Outstanding balance snapshot per customer."""

    _HEADERS = ["Customer", "Code", "Outstanding (₦)", "Credit Limit (₦)",
                "Available Credit (₦)", "Last Invoice", "Last Payment"]

    def get(self, request):
        data = ReportService.customer_balance(self.get_organisation())

        def _rows(d):
            return [
                [r["customer_name"], r["customer_code"] or "",
                 r["outstanding_balance"], r["credit_limit"], r["available_credit"],
                 str(r["last_invoice_date"]) if r["last_invoice_date"] else "",
                 str(r["last_payment_date"]) if r["last_payment_date"] else ""]
                for r in d
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Customer Balance",
            filename_base="customer_balance",
        )


# ─── Payments by Customer ─────────────────────────────────────────────────


class PaymentsByCustomerView(BaseDateRangeView):
    """GET /api/v1/reports/payments-by-customer/ — SalePayments grouped by customer."""

    _HEADERS = ["Customer", "Total Received (₦)", "Payment Count"]

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        data = ReportService.payments_by_customer(self.get_organisation(), date_from, date_to)

        def _rows(d):
            return [
                [r["customer_name"], r["total_received"], r["payment_count"]]
                for r in d
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Payments by Customer",
            filename_base="payments_by_customer",
        )


# ─── Customer Payments (drill-down) ───────────────────────────────────────


class CustomerPaymentsView(BaseDateRangeView):
    """GET /api/v1/reports/customer-payments/?customer_id=<uuid> — individual payments for one customer."""

    _HEADERS = ["Date", "Amount (₦)", "Method", "Invoice #", "Reference"]

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        customer_id = request.query_params.get("customer_id")
        if not customer_id:
            return Response({"error": "customer_id is required"}, status=400)

        data = ReportService.customer_payments(
            self.get_organisation(), customer_id, date_from, date_to
        )

        def _rows(d):
            return [
                [str(r["date"]), r["amount"], r["method"], r["invoice_number"], r["reference"]]
                for r in d
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Customer Payments",
            filename_base="customer_payments",
        )


# ─── Account Statement (GL) ────────────────────────────────────────────────


class AccountStatementView(BaseDateRangeView):
    """GET /api/v1/reports/account-statement/?account_id=<uuid> — GL statement for one account."""

    _HEADERS = ["Date", "Reference", "Description", "Debit (₦)", "Credit (₦)", "Running Balance (₦)"]

    def get(self, request):
        from apps.accounting.models import Account

        date_from, date_to = self.get_date_range(request)
        account_id = request.query_params.get("account_id")
        if not account_id:
            return Response({"error": "account_id is required"}, status=400)

        try:
            data = ReportService.account_statement(
                self.get_organisation(), account_id, date_from, date_to
            )
        except Account.DoesNotExist:
            return Response({"error": "Account not found"}, status=404)

        def _rows(d):
            return [
                [str(r["date"]), r["journal_entry_reference"], r["description"],
                 r["debit"], r["credit"], r["running_balance"]]
                for r in d.get("lines", [])
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Account Statement",
            filename_base="account_statement",
        )


# ─── Customer Invoices (drill-down) ───────────────────────────────────────


class CustomerInvoicesView(BaseDateRangeView):
    """GET /api/v1/reports/customer-invoices/?customer_id=<uuid> — invoices for one customer."""

    _HEADERS = ["Invoice #", "Date", "Status", "Total (₦)", "Paid (₦)", "Due (₦)"]

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        customer_id = request.query_params.get("customer_id")
        if not customer_id:
            return Response({"error": "customer_id is required"}, status=400)

        cid = None if customer_id == "walk-in" else customer_id
        data = ReportService.customer_invoices(self.get_organisation(), cid, date_from, date_to)

        def _rows(d):
            return [
                [r["invoice_number"], str(r["issue_date"]), r["status"],
                 r["total_amount"], r["amount_paid"], r["amount_due"]]
                for r in d
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Customer Invoices",
            filename_base="customer_invoices",
        )


# ─── Customer Details (master directory) ──────────────────────────────────


class CustomerDetailsView(BaseDateRangeView):
    """GET /api/v1/reports/customer-details/ — Master customer directory."""

    _HEADERS = ["Code", "Name", "Type", "Email", "Phone",
                "Outstanding (₦)", "Credit Limit (₦)", "Total Sales (₦)", "Total Payments (₦)"]

    def get(self, request):
        data = ReportService.customer_details(self.get_organisation())

        def _rows(d):
            return [
                [r["code"], r["name"], r["customer_type"], r["email"], r["phone"],
                 r["outstanding_balance"], r["credit_limit"], r["total_sales"], r["total_payments"]]
                for r in d
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Customer Details",
            filename_base="customer_details",
        )


# ─── Product Details (master directory) ───────────────────────────────────


class ProductDetailsView(BaseDateRangeView):
    """GET /api/v1/reports/product-details/ — Master product directory."""

    _HEADERS = ["SKU", "Name", "Category", "Cost Price (₦)", "Selling Price (₦)",
                "Stock Qty", "Reorder Level", "Margin %"]

    def get(self, request):
        data = ReportService.product_details(self.get_organisation())

        def _rows(d):
            return [
                [r["sku"], r["name"], r["category_name"], r["cost_price"], r["selling_price"],
                 r["stock_quantity"], r["reorder_level"], r["margin_pct"]]
                for r in d
            ]

        return self._export_or_json(
            request, data,
            headers=self._HEADERS,
            row_fn=_rows,
            title="Product Details",
            filename_base="product_details",
        )


# ─── Unified report engine (registry-backed dispatch) ────────────────────────

from . import registry as report_registry  # noqa: E402


class ReportCatalogView(BaseDateRangeView):
    """GET /reports/catalog/ — list registry-backed reports for the reports menu."""

    def get(self, request):
        return Response({"reports": report_registry.catalog()})


class ReportDispatchView(BaseDateRangeView):
    """GET /reports/r/<key>/ — run any registry-backed report by key.

    Accepts the standard period params plus any resolver-specific params
    (e.g. ?account_id= for gl-detail). Returns JSON.
    """

    def get(self, request, key):
        rd = report_registry.get(key)
        if rd is None:
            return Response({"error": f"Unknown report: {key}"}, status=404)
        org = self.get_organisation()
        if org is None:
            return Response({"error": "Organisation not found"}, status=400)
        date_from, date_to = self.get_date_range(request)
        reserved = {"period", "date_from", "date_to", "format"}
        extra = {k: v for k, v in request.query_params.items() if k not in reserved}
        try:
            data = rd.resolver(org, date_from, date_to, **extra)
        except Exception as e:
            return Response({"error": str(e)}, status=422)

        # Generic export: any resolver returning a flat "rows" list can be
        # exported to Excel/PDF without a bespoke row_fn per report.
        fmt = request.query_params.get("format", "json").lower()
        if fmt in ("excel", "pdf"):
            rows_data = data.get("rows") if isinstance(data, dict) else None
            if isinstance(rows_data, list) and rows_data and isinstance(rows_data[0], dict):
                headers = list(rows_data[0].keys())
                pretty = [h.replace("_", " ").title() for h in headers]
                response = dispatch_export(
                    fmt=fmt,
                    headers=pretty,
                    rows=[[r.get(h) for h in headers] for r in rows_data],
                    title=rd.label,
                    subtitle=self.get_period_label(request, date_from, date_to),
                    filename_base=rd.key,
                    org=org,
                )
                if response is not None:
                    return response

        return Response({
            "key": rd.key, "label": rd.label, "category": rd.category,
            "period_label": self.get_period_label(request, date_from, date_to),
            "data": data,
        })
