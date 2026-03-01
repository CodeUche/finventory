"""
Reporting service: aggregation-heavy queries for analytics.

All queries use .values() + .annotate() for database-side aggregation.
Never pull rows into Python for counting/summing — that defeats indexing.

Scaling notes:
    - For very large datasets, consider materialised views or summary tables
      updated by Celery beat tasks.
    - All report queries are read-only and should be pointed at a DB replica.
"""

import logging
from decimal import Decimal

from django.db.models import Count, F, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncYear

logger = logging.getLogger(__name__)


class ReportService:

    # ─── Sales Reports ────────────────────────────────────────────────────────

    @staticmethod
    def sales_summary(organisation, date_from, date_to, group_by="day") -> list[dict]:
        """
        Aggregate sales by day/month/year.

        group_by: "day" | "month" | "year"
        """
        from apps.sales.models import Invoice

        trunc_fn = {"day": TruncDay, "month": TruncMonth, "year": TruncYear}.get(group_by, TruncDay)

        return (
            Invoice.objects.filter(
                organisation=organisation,
                issue_date__gte=date_from,
                issue_date__lte=date_to,
                status__in=["paid", "confirmed", "partially_paid", "credit"],
            )
            .annotate(period=trunc_fn("issue_date"))
            .values("period")
            .annotate(
                total_revenue=Sum("total_amount"),
                total_tax=Sum("tax_amount"),
                total_discount=Sum("discount_amount"),
                invoice_count=Count("id"),
            )
            .order_by("period")
        )

    @staticmethod
    def top_products(organisation, date_from, date_to, limit=10) -> list[dict]:
        """Top N products by revenue in the period."""
        from apps.sales.models import SaleItem

        return (
            SaleItem.objects.filter(
                organisation=organisation,
                invoice__issue_date__gte=date_from,
                invoice__issue_date__lte=date_to,
                invoice__status__in=["paid", "confirmed", "partially_paid"],
            )
            .values("product__id", "product__name", "product__sku")
            .annotate(
                total_quantity=Sum("quantity"),
                total_revenue=Sum("line_total"),
                total_cogs=Sum("cost_of_goods"),
                gross_profit=Sum("line_total") - Sum("cost_of_goods"),
            )
            .order_by("-total_revenue")[:limit]
        )

    @staticmethod
    def top_customers(organisation, date_from, date_to, limit=10) -> list[dict]:
        """Top N customers by revenue."""
        from apps.sales.models import Invoice

        return (
            Invoice.objects.filter(
                organisation=organisation,
                issue_date__gte=date_from,
                issue_date__lte=date_to,
                status__in=["paid", "confirmed", "partially_paid"],
                customer__isnull=False,
            )
            .values("customer__id", "customer__name", "customer__code")
            .annotate(
                total_revenue=Sum("total_amount"),
                invoice_count=Count("id"),
            )
            .order_by("-total_revenue")[:limit]
        )

    # ─── P&L Report ──────────────────────────────────────────────────────────

    @staticmethod
    def profit_and_loss(organisation, date_from, date_to) -> dict:
        """
        Profit & Loss statement for the period.

        Revenue − COGS = Gross Profit
        Gross Profit − Operating Expenses = Net Profit
        """
        from apps.expenses.models import Expense
        from apps.sales.models import Invoice, SaleItem

        # Revenue
        revenue_data = Invoice.objects.filter(
            organisation=organisation,
            issue_date__gte=date_from,
            issue_date__lte=date_to,
            status__in=["paid", "confirmed", "partially_paid", "credit"],
        ).aggregate(
            total_revenue=Sum("total_amount"),
            total_tax_collected=Sum("tax_amount"),
            total_discounts=Sum("discount_amount"),
        )

        # COGS (from sale items)
        cogs_data = SaleItem.objects.filter(
            organisation=organisation,
            invoice__issue_date__gte=date_from,
            invoice__issue_date__lte=date_to,
            invoice__status__in=["paid", "confirmed", "partially_paid"],
        ).aggregate(total_cogs=Sum("cost_of_goods"))

        # Operating expenses
        expense_data = Expense.objects.filter(
            organisation=organisation,
            expense_date__gte=date_from,
            expense_date__lte=date_to,
            is_income=False,
        ).aggregate(total_expenses=Sum("amount"))

        # Miscellaneous income
        income_data = Expense.objects.filter(
            organisation=organisation,
            expense_date__gte=date_from,
            expense_date__lte=date_to,
            is_income=True,
        ).aggregate(total_misc_income=Sum("amount"))

        total_revenue = revenue_data["total_revenue"] or Decimal("0")
        total_cogs = cogs_data["total_cogs"] or Decimal("0")
        total_expenses = expense_data["total_expenses"] or Decimal("0")
        misc_income = income_data["total_misc_income"] or Decimal("0")
        tax_collected = revenue_data["total_tax_collected"] or Decimal("0")

        gross_profit = total_revenue - total_cogs
        operating_profit = gross_profit - total_expenses + misc_income
        # Net profit (before income tax)
        net_profit = operating_profit

        return {
            "period_start": date_from,
            "period_end": date_to,
            "revenue": {
                "gross_sales": total_revenue,
                "tax_collected": tax_collected,
                "discounts": revenue_data["total_discounts"] or Decimal("0"),
            },
            "cost_of_goods_sold": total_cogs,
            "gross_profit": gross_profit,
            "gross_margin_pct": (
                (gross_profit / total_revenue * 100).quantize(Decimal("0.01"))
                if total_revenue > 0 else Decimal("0")
            ),
            "operating_expenses": total_expenses,
            "miscellaneous_income": misc_income,
            "operating_profit": operating_profit,
            "net_profit": net_profit,
            "net_margin_pct": (
                (net_profit / total_revenue * 100).quantize(Decimal("0.01"))
                if total_revenue > 0 else Decimal("0")
            ),
        }

    # ─── Expense Breakdown ────────────────────────────────────────────────────

    @staticmethod
    def expense_breakdown(organisation, date_from, date_to) -> list[dict]:
        """Expenses grouped by category."""
        from apps.expenses.models import Expense

        return (
            Expense.objects.filter(
                organisation=organisation,
                expense_date__gte=date_from,
                expense_date__lte=date_to,
                is_income=False,
            )
            .values("category__name")
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("-total")
        )

    # ─── Stock Reports ────────────────────────────────────────────────────────

    @staticmethod
    def inventory_valuation(organisation) -> dict:
        """Current inventory value."""
        from apps.inventory.models import StockItem

        items = (
            StockItem.objects.filter(organisation=organisation, quantity_on_hand__gt=0)
            .select_related("product", "warehouse")
            .annotate(total_value=F("quantity_on_hand") * F("product__cost_price"))
        )

        total_value = sum(i.total_value for i in items)

        return {
            "total_inventory_value": total_value,
            "items": [
                {
                    "product": i.product.name,
                    "sku": i.product.sku,
                    "warehouse": i.warehouse.name,
                    "quantity": i.quantity_on_hand,
                    "unit_cost": i.product.cost_price,
                    "total_value": i.total_value,
                }
                for i in items
            ],
        }

    # ─── Cash Flow ────────────────────────────────────────────────────────────

    @staticmethod
    def cash_flow(organisation, date_from, date_to) -> dict:
        """Simple cash flow: inflows − outflows."""
        from apps.expenses.models import Expense
        from apps.sales.models import SalePayment

        cash_in = (
            SalePayment.objects.filter(
                organisation=organisation,
                received_at__date__gte=date_from,
                received_at__date__lte=date_to,
                method__in=["cash", "bank_transfer", "pos"],
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0")
        )

        cash_out = (
            Expense.objects.filter(
                organisation=organisation,
                expense_date__gte=date_from,
                expense_date__lte=date_to,
                is_income=False,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0")
        )

        misc_in = (
            Expense.objects.filter(
                organisation=organisation,
                expense_date__gte=date_from,
                expense_date__lte=date_to,
                is_income=True,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0")
        )

        return {
            "period_start": date_from,
            "period_end": date_to,
            "cash_inflows": cash_in + misc_in,
            "cash_outflows": cash_out,
            "net_cash_flow": (cash_in + misc_in) - cash_out,
        }
