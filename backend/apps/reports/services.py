"""
Reporting service: aggregation-heavy queries for analytics.

All queries use .values() + .annotate() for database-side aggregation.
Never pull rows into Python for counting/summing — that defeats indexing.

date_from / date_to are Optional throughout.  When both are None the query
runs against ALL records for the organisation (period='all').  When only
one is provided the half-open filter is applied correctly.

Scaling notes:
    - For very large datasets, consider materialised views or summary tables
      updated by Celery beat tasks.
    - All report queries are read-only and should be pointed at a DB replica.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from django.db.models import Count, F, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncYear

logger = logging.getLogger(__name__)


def _date_filter(qs, field: str, date_from: Optional[date], date_to: Optional[date]):
    """Apply optional gte/lte date range filters to a queryset."""
    if date_from:
        qs = qs.filter(**{f"{field}__gte": date_from})
    if date_to:
        qs = qs.filter(**{f"{field}__lte": date_to})
    return qs


class ReportService:

    # ─── Sales Reports ────────────────────────────────────────────────────────

    @staticmethod
    def sales_summary(
        organisation,
        date_from: Optional[date],
        date_to: Optional[date],
        group_by: str = "day",
    ) -> list[dict]:
        """
        Aggregate sales by day/month/year.

        group_by: "day" | "month" | "year"
        When date_from is None (period='all') group_by defaults to "month".
        """
        from apps.sales.models import Invoice

        if date_from is None and group_by == "day":
            group_by = "month"

        trunc_fn = {"day": TruncDay, "month": TruncMonth, "year": TruncYear}.get(
            group_by, TruncDay
        )

        qs = Invoice.objects.filter(
            organisation=organisation,
            status__in=["paid", "confirmed", "partially_paid", "credit", "overdue"],
        )
        qs = _date_filter(qs, "issue_date", date_from, date_to)

        return (
            qs.annotate(period=trunc_fn("issue_date"))
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
    def top_products(
        organisation,
        date_from: Optional[date],
        date_to: Optional[date],
        limit: int = 10,
    ) -> list[dict]:
        """Top N products by revenue in the period."""
        from apps.sales.models import SaleItem

        qs = SaleItem.objects.filter(
            organisation=organisation,
            invoice__status__in=["paid", "confirmed", "partially_paid", "credit", "overdue"],
        )
        qs = _date_filter(qs, "invoice__issue_date", date_from, date_to)

        qs = (
            qs.values("product__id", "product__name", "product__sku")
            .annotate(
                total_quantity=Sum("quantity"),
                total_revenue=Sum("line_total"),
                total_cogs=Sum("cost_of_goods"),
                gross_profit=Sum("line_total") - Sum("cost_of_goods"),
            )
            .order_by("-total_revenue")[:limit]
        )
        return [
            {
                "product_id": r["product__id"],
                "product_name": r["product__name"],
                "product_sku": r["product__sku"],
                "units_sold": r["total_quantity"],
                "revenue": r["total_revenue"],
                "cogs": r["total_cogs"],
                "gross_profit": r["gross_profit"],
            }
            for r in qs
        ]

    @staticmethod
    def top_customers(
        organisation,
        date_from: Optional[date],
        date_to: Optional[date],
        limit: int = 10,
    ) -> list[dict]:
        """Top N customers by revenue."""
        from apps.sales.models import Invoice

        qs = Invoice.objects.filter(
            organisation=organisation,
            status__in=["paid", "confirmed", "partially_paid", "credit", "overdue"],
            customer__isnull=False,
        )
        qs = _date_filter(qs, "issue_date", date_from, date_to)

        qs = (
            qs.values("customer__id", "customer__name", "customer__code")
            .annotate(
                total_revenue=Sum("total_amount"),
                invoice_count=Count("id"),
            )
            .order_by("-total_revenue")[:limit]
        )
        return [
            {
                "customer_id": r["customer__id"],
                "customer_name": r["customer__name"],
                "customer_code": r["customer__code"],
                "revenue": r["total_revenue"],
                "invoice_count": r["invoice_count"],
            }
            for r in qs
        ]

    # ─── P&L Report ──────────────────────────────────────────────────────────

    @staticmethod
    def profit_and_loss(
        organisation,
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> dict:
        """
        Profit & Loss statement for the period.

        Revenue − COGS = Gross Profit
        Gross Profit − Operating Expenses = Net Profit
        """
        from apps.expenses.models import Expense
        from apps.sales.models import Invoice, SaleItem

        rev_qs = Invoice.objects.filter(
            organisation=organisation,
            status__in=["paid", "confirmed", "partially_paid", "credit", "overdue"],
        )
        rev_qs = _date_filter(rev_qs, "issue_date", date_from, date_to)
        revenue_data = rev_qs.aggregate(
            total_revenue=Sum("total_amount"),
            total_tax_collected=Sum("tax_amount"),
            total_discounts=Sum("discount_amount"),
        )

        cogs_qs = SaleItem.objects.filter(
            organisation=organisation,
            invoice__status__in=["paid", "confirmed", "partially_paid", "credit", "overdue"],
        )
        cogs_qs = _date_filter(cogs_qs, "invoice__issue_date", date_from, date_to)
        cogs_data = cogs_qs.aggregate(total_cogs=Sum("cost_of_goods"))

        exp_qs = Expense.objects.filter(organisation=organisation, is_income=False)
        exp_qs = _date_filter(exp_qs, "expense_date", date_from, date_to)
        expense_data = exp_qs.aggregate(total_expenses=Sum("amount"))

        inc_qs = Expense.objects.filter(organisation=organisation, is_income=True)
        inc_qs = _date_filter(inc_qs, "expense_date", date_from, date_to)
        income_data = inc_qs.aggregate(total_misc_income=Sum("amount"))

        total_revenue = revenue_data["total_revenue"] or Decimal("0")
        total_cogs = cogs_data["total_cogs"] or Decimal("0")
        total_expenses = expense_data["total_expenses"] or Decimal("0")
        misc_income = income_data["total_misc_income"] or Decimal("0")
        tax_collected = revenue_data["total_tax_collected"] or Decimal("0")

        total_income = total_revenue + misc_income
        gross_profit = total_income - total_cogs
        net_profit = gross_profit - total_expenses

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
                (gross_profit / total_income * 100).quantize(Decimal("0.01"))
                if total_income > 0
                else Decimal("0")
            ),
            "operating_expenses": total_expenses,
            "miscellaneous_income": misc_income,
            "net_profit": net_profit,
            "net_margin_pct": (
                (net_profit / total_income * 100).quantize(Decimal("0.01"))
                if total_income > 0
                else Decimal("0")
            ),
        }

    # ─── Sales by Customer ───────────────────────────────────────────────────

    @staticmethod
    def sales_by_customer(
        organisation,
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> list[dict]:
        """All customers with revenue totals for the period (NULL customer = walk-in)."""
        from apps.sales.models import Invoice

        qs = Invoice.objects.filter(
            organisation=organisation,
            status__in=["paid", "confirmed", "partially_paid", "credit", "overdue"],
        )
        qs = _date_filter(qs, "issue_date", date_from, date_to)
        qs = (
            qs.values(
                "customer__id", "customer__name",
                "customer__code", "customer__email",
            )
            .annotate(
                total_revenue=Sum("total_amount"),
                invoice_count=Count("id"),
                total_paid=Sum("amount_paid"),
                total_outstanding=Sum("amount_due"),
            )
            .order_by("-total_revenue")
        )
        return [
            {
                "customer_id": str(r["customer__id"]) if r["customer__id"] else None,
                "customer_name": r["customer__name"] or "Walk-in",
                "customer_code": r["customer__code"],
                "customer_email": r["customer__email"],
                "invoice_count": r["invoice_count"],
                "revenue": r["total_revenue"],
                "amount_paid": r["total_paid"],
                "amount_outstanding": r["total_outstanding"],
            }
            for r in qs
        ]

    @staticmethod
    def customer_invoices(
        organisation,
        customer_id,           # str UUID or None (= walk-in)
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> list[dict]:
        """Individual invoices for one customer (or all walk-in invoices) in the period."""
        from apps.sales.models import Invoice

        qs = Invoice.objects.filter(
            organisation=organisation,
            status__in=["paid", "confirmed", "partially_paid", "credit", "overdue"],
        )
        if customer_id is None:
            qs = qs.filter(customer__isnull=True)
        else:
            qs = qs.filter(customer__id=customer_id)
        qs = _date_filter(qs, "issue_date", date_from, date_to)
        return list(
            qs.values(
                "id", "invoice_number", "issue_date",
                "status", "total_amount", "amount_paid", "amount_due",
            ).order_by("-issue_date")
        )

    # ─── Sales by Product ────────────────────────────────────────────────────

    @staticmethod
    def sales_by_product(
        organisation,
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> list[dict]:
        """All products with revenue / quantity totals for the period."""
        from apps.sales.models import SaleItem

        qs = SaleItem.objects.filter(
            organisation=organisation,
            invoice__status__in=["paid", "confirmed", "partially_paid", "credit", "overdue"],
        )
        qs = _date_filter(qs, "invoice__issue_date", date_from, date_to)
        qs = (
            qs.values("product__id", "product__name", "product__sku")
            .annotate(
                total_quantity=Sum("quantity"),
                total_revenue=Sum("line_total"),
                total_cogs=Sum("cost_of_goods"),
                gross_profit=Sum("line_total") - Sum("cost_of_goods"),
            )
            .order_by("-total_revenue")
        )
        return [
            {
                "product_id": str(r["product__id"]) if r["product__id"] else None,
                "product_name": r["product__name"] or "Unknown",
                "product_sku": r["product__sku"],
                "units_sold": r["total_quantity"],
                "revenue": r["total_revenue"],
                "cogs": r["total_cogs"],
                "gross_profit": r["gross_profit"],
            }
            for r in qs
        ]

    @staticmethod
    def product_sale_lines(
        organisation,
        product_id: str,
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> list[dict]:
        """Individual sale-item lines for one product across all invoices in the period."""
        from apps.sales.models import SaleItem

        qs = SaleItem.objects.filter(
            organisation=organisation,
            product__id=product_id,
            invoice__status__in=["paid", "confirmed", "partially_paid", "credit", "overdue"],
        )
        qs = _date_filter(qs, "invoice__issue_date", date_from, date_to)
        qs = qs.select_related("invoice", "invoice__customer").order_by(
            "-invoice__issue_date"
        )
        return [
            {
                "invoice_id": str(item.invoice.id),
                "invoice_number": item.invoice.invoice_number,
                "issue_date": item.invoice.issue_date,
                "customer_name": (
                    item.invoice.customer.name if item.invoice.customer else "Walk-in"
                ),
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": item.line_total,
            }
            for item in qs
        ]

    # ─── Expense Breakdown ────────────────────────────────────────────────────

    @staticmethod
    def expense_breakdown(
        organisation,
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> list[dict]:
        """Expenses grouped by category."""
        from apps.expenses.models import Expense

        qs = Expense.objects.filter(organisation=organisation, is_income=False)
        qs = _date_filter(qs, "expense_date", date_from, date_to)

        qs = (
            qs.values("category__name")
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("-total")
        )
        return [
            {
                "category_name": r["category__name"] or "Uncategorised",
                "total": r["total"],
                "count": r["count"],
            }
            for r in qs
        ]

    # ─── Stock Reports ────────────────────────────────────────────────────────

    @staticmethod
    def inventory_valuation(organisation) -> dict:
        """Current inventory value — point-in-time snapshot, no date range."""
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

    # ─── AR Aging ─────────────────────────────────────────────────────────────

    @staticmethod
    def ar_aging(organisation, as_of: Optional[date] = None) -> dict:
        """Bucket outstanding invoices by days overdue."""
        from datetime import date as _date
        from apps.sales.models import Invoice

        as_of = as_of or _date.today()
        invoices = Invoice.objects.filter(
            organisation=organisation,
            status__in=["confirmed", "credit", "partially_paid", "overdue"],
            amount_due__gt=0,
        ).select_related("customer")

        buckets = {
            "current": Decimal("0"),
            "1_30": Decimal("0"),
            "31_60": Decimal("0"),
            "61_90": Decimal("0"),
            "over_90": Decimal("0"),
        }
        invoice_list = []

        for inv in invoices:
            due_date = inv.due_date or inv.issue_date
            days = (as_of - due_date).days if due_date else 0
            amount_due = Decimal(str(inv.amount_due or 0))

            if days <= 0:
                buckets["current"] += amount_due
            elif days <= 30:
                buckets["1_30"] += amount_due
            elif days <= 60:
                buckets["31_60"] += amount_due
            elif days <= 90:
                buckets["61_90"] += amount_due
            else:
                buckets["over_90"] += amount_due

            invoice_list.append(
                {
                    "id": str(inv.id),
                    "invoice_number": inv.invoice_number,
                    "customer_name": inv.customer.name if inv.customer else "Walk-in",
                    "amount_due": amount_due,
                    "due_date": due_date,
                    "days_overdue": max(0, days),
                }
            )

        return {
            "as_of": as_of,
            "buckets": buckets,
            "total_outstanding": sum(buckets.values()),
            "invoices": sorted(invoice_list, key=lambda x: x["days_overdue"], reverse=True),
        }

    # ─── AP Aging ─────────────────────────────────────────────────────────────

    @staticmethod
    def ap_aging(organisation, as_of: Optional[date] = None) -> dict:
        """Bucket outstanding bills by days overdue."""
        from datetime import date as _date
        from apps.bills.models import Bill

        as_of = as_of or _date.today()
        bills = Bill.objects.filter(
            organisation=organisation,
            status__in=["approved", "received", "partially_paid", "overdue"],
            amount_due__gt=0,
        ).select_related("supplier")

        buckets = {
            "current": Decimal("0"),
            "1_30": Decimal("0"),
            "31_60": Decimal("0"),
            "61_90": Decimal("0"),
            "over_90": Decimal("0"),
        }
        bill_list = []

        for bill in bills:
            due_date = bill.due_date or bill.issue_date
            days = (as_of - due_date).days if due_date else 0
            amount_due = Decimal(str(bill.amount_due or 0))

            if days <= 0:
                buckets["current"] += amount_due
            elif days <= 30:
                buckets["1_30"] += amount_due
            elif days <= 60:
                buckets["31_60"] += amount_due
            elif days <= 90:
                buckets["61_90"] += amount_due
            else:
                buckets["over_90"] += amount_due

            bill_list.append(
                {
                    "id": str(bill.id),
                    "bill_number": bill.bill_number,
                    "supplier_name": bill.supplier.name if bill.supplier else "Walk-in",
                    "amount_due": amount_due,
                    "due_date": due_date,
                    "days_overdue": max(0, days),
                }
            )

        sorted_bills = sorted(bill_list, key=lambda x: x["days_overdue"], reverse=True)
        return {
            "as_of": as_of,
            "buckets": buckets,
            "total_outstanding": sum(buckets.values()),
            "bills": sorted_bills,
            "invoices": sorted_bills,  # alias so frontend type works for both AR and AP
        }

    # ─── VAT Summary ──────────────────────────────────────────────────────────

    @staticmethod
    def vat_summary(
        organisation,
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> dict:
        """Output VAT (collected on sales) minus Input VAT (paid on bills)."""
        from apps.bills.models import Bill
        from apps.sales.models import Invoice

        out_qs = Invoice.objects.filter(
            organisation=organisation,
            status__in=["paid", "confirmed", "partially_paid", "credit", "overdue"],
        )
        out_qs = _date_filter(out_qs, "issue_date", date_from, date_to)
        output_vat = out_qs.aggregate(t=Sum("tax_amount"))["t"] or Decimal("0")

        in_qs = Bill.objects.filter(
            organisation=organisation,
            status__in=["approved", "paid", "partially_paid"],
        )
        in_qs = _date_filter(in_qs, "issue_date", date_from, date_to)
        input_vat = in_qs.aggregate(t=Sum("tax_amount"))["t"] or Decimal("0")

        return {
            "period_start": date_from,
            "period_end": date_to,
            "output_vat": output_vat,
            "input_vat": input_vat,
            "net_vat_payable": output_vat - input_vat,
        }

    # ─── Cash Flow ────────────────────────────────────────────────────────────

    @staticmethod
    def cash_flow(
        organisation,
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> dict:
        """Simple cash flow: inflows − outflows."""
        from apps.expenses.models import Expense
        from apps.sales.models import SalePayment

        cash_qs = SalePayment.objects.filter(
            organisation=organisation,
            method__in=["cash", "bank_transfer", "pos"],
        )
        if date_from:
            cash_qs = cash_qs.filter(received_at__date__gte=date_from)
        if date_to:
            cash_qs = cash_qs.filter(received_at__date__lte=date_to)
        cash_in = cash_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")

        exp_qs = Expense.objects.filter(organisation=organisation, is_income=False)
        exp_qs = _date_filter(exp_qs, "expense_date", date_from, date_to)
        cash_out = exp_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")

        misc_qs = Expense.objects.filter(organisation=organisation, is_income=True)
        misc_qs = _date_filter(misc_qs, "expense_date", date_from, date_to)
        misc_in = misc_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")

        return {
            "period_start": date_from,
            "period_end": date_to,
            "cash_inflows": cash_in + misc_in,
            "cash_outflows": cash_out,
            "net_cash_flow": (cash_in + misc_in) - cash_out,
        }

    # ─── Payment Method Breakdown ─────────────────────────────────────────────

    @staticmethod
    def payment_methods(
        organisation,
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> list[dict]:
        """Revenue collected grouped by payment method."""
        from apps.sales.models import SalePayment

        qs = SalePayment.objects.filter(organisation=organisation)
        if date_from:
            qs = qs.filter(received_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(received_at__date__lte=date_to)

        qs = (
            qs.values("method")
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("-total")
        )

        METHOD_LABELS = {
            "cash": "Cash",
            "bank_transfer": "Bank Transfer",
            "pos": "POS",
            "cheque": "Cheque",
            "credit_applied": "Credit Applied",
        }
        return [
            {
                "method": r["method"],
                "label": METHOD_LABELS.get(r["method"], r["method"].replace("_", " ").title()),
                "total": r["total"],
                "count": r["count"],
            }
            for r in qs
        ]
