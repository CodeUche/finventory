"""
Reporting API views.

All report endpoints are GET-only and accept date_from/date_to filters.
Reports use DB aggregation — no Python-level loops over large datasets.
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.pagination import LargeResultsSetPagination
from apps.core.permissions import IsAccountant

from .services import ReportService


class BaseDateRangeView(APIView):
    """Base view that parses date_from and date_to from query params."""

    permission_classes = [IsAuthenticated, IsAccountant]

    def get_date_range(self, request):
        from datetime import date

        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")

        today = date.today()
        first_of_month = today.replace(day=1)

        try:
            from datetime import datetime

            date_from = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else first_of_month
            date_to = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else today
        except ValueError:
            date_from = first_of_month
            date_to = today

        return date_from, date_to


class SalesSummaryView(BaseDateRangeView):
    """GET /api/v1/reports/sales/ — Sales summary by period."""

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        group_by = request.query_params.get("group_by", "day")
        data = ReportService.sales_summary(request.organisation, date_from, date_to, group_by)
        return Response(list(data))


class TopProductsView(BaseDateRangeView):
    """GET /api/v1/reports/top-products/ — Best-selling products."""

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        limit = int(request.query_params.get("limit", 10))
        data = ReportService.top_products(request.organisation, date_from, date_to, limit)
        return Response(list(data))


class TopCustomersView(BaseDateRangeView):
    """GET /api/v1/reports/top-customers/ — Top customers by revenue."""

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        limit = int(request.query_params.get("limit", 10))
        data = ReportService.top_customers(request.organisation, date_from, date_to, limit)
        return Response(list(data))


class ProfitAndLossView(BaseDateRangeView):
    """GET /api/v1/reports/pnl/ — Profit & Loss statement."""

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        data = ReportService.profit_and_loss(request.organisation, date_from, date_to)
        return Response(data)


class ExpenseBreakdownView(BaseDateRangeView):
    """GET /api/v1/reports/expenses/ — Expenses by category."""

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        data = ReportService.expense_breakdown(request.organisation, date_from, date_to)
        return Response(list(data))


class InventoryValuationView(BaseDateRangeView):
    """GET /api/v1/reports/inventory/ — Current inventory valuation."""

    def get(self, request):
        data = ReportService.inventory_valuation(request.organisation)
        return Response(data)


class CashFlowView(BaseDateRangeView):
    """GET /api/v1/reports/cash-flow/ — Cash flow for period."""

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        data = ReportService.cash_flow(request.organisation, date_from, date_to)
        return Response(data)


class ARAgingView(BaseDateRangeView):
    """GET /api/v1/reports/ar-aging/ — Accounts receivable aging buckets."""

    def get(self, request):
        from datetime import date, datetime
        as_of_str = request.query_params.get('as_of')
        try:
            as_of = datetime.strptime(as_of_str, '%Y-%m-%d').date() if as_of_str else date.today()
        except ValueError:
            as_of = date.today()
        data = ReportService.ar_aging(request.organisation, as_of)
        return Response(data)


class VATSummaryView(BaseDateRangeView):
    """GET /api/v1/reports/vat-summary/ — VAT output vs input summary."""

    def get(self, request):
        date_from, date_to = self.get_date_range(request)
        data = ReportService.vat_summary(request.organisation, date_from, date_to)
        return Response(data)
