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

from django.db.models import Count, F, Max, Sum
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
        """
        Current inventory value — point-in-time snapshot, no date range.

        Includes:
          • Products with StockItem records (any quantity ≥ 0)
          • Physical products with NO StockItem records yet (imported / never received)
            — these appear with quantity 0 and value 0 for visibility.
        """
        from apps.inventory.models import StockItem, Product

        stock_items = (
            StockItem.objects.filter(organisation=organisation, quantity_on_hand__gte=0)
            .select_related("product", "warehouse")
            .annotate(total_value=F("quantity_on_hand") * F("product__cost_price"))
        )

        total_value = sum((i.total_value or Decimal("0")) for i in stock_items)

        product_ids_with_stock = set(
            StockItem.objects.filter(organisation=organisation)
            .values_list("product_id", flat=True)
        )
        phantom_products = Product.objects.filter(
            organisation=organisation,
            is_active=True,
            product_type="physical",
        ).exclude(id__in=product_ids_with_stock)

        items = [
            {
                "product": i.product.name,
                "sku": i.product.sku or "",
                "warehouse": i.warehouse.name,
                "quantity": i.quantity_on_hand,
                "unit_cost": i.product.cost_price,
                "total_value": i.total_value or Decimal("0"),
            }
            for i in stock_items
        ] + [
            {
                "product": p.name,
                "sku": p.sku or "",
                "warehouse": "—",
                "quantity": 0,
                "unit_cost": p.cost_price,
                "total_value": Decimal("0"),
            }
            for p in phantom_products
        ]

        return {
            "total_inventory_value": total_value,
            "items": items,
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

    # ─── Customer Balance (AR snapshot) ──────────────────────────────────────

    @staticmethod
    def customer_balance(organisation) -> list[dict]:
        """
        Point-in-time snapshot of every active customer's outstanding balance,
        credit position, and last activity dates. Sorted by outstanding_balance
        descending by default.
        """
        from apps.customers.models import Customer
        from apps.sales.models import Invoice, SalePayment

        customers = Customer.objects.filter(organisation=organisation, is_active=True)

        last_invoice_map = dict(
            Invoice.objects.filter(organisation=organisation, customer__in=customers)
            .values("customer_id")
            .annotate(last_date=Max("issue_date"))
            .values_list("customer_id", "last_date")
        )
        last_payment_map = dict(
            SalePayment.objects.filter(
                organisation=organisation, invoice__customer__in=customers
            )
            .values("invoice__customer_id")
            .annotate(last_date=Max("received_at"))
            .values_list("invoice__customer_id", "last_date")
        )

        rows = [
            {
                "customer_id": str(c.id),
                "customer_name": c.name,
                "customer_code": c.code,
                "outstanding_balance": c.outstanding_balance,
                "credit_limit": c.credit_limit,
                "available_credit": c.available_credit,
                "last_invoice_date": last_invoice_map.get(c.id),
                "last_payment_date": last_payment_map.get(c.id),
            }
            for c in customers
        ]
        return sorted(rows, key=lambda r: r["outstanding_balance"], reverse=True)

    # ─── Payments by Customer ─────────────────────────────────────────────────

    @staticmethod
    def payments_by_customer(
        organisation,
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> list[dict]:
        """Group SalePayment (via Invoice.customer) by customer for the period."""
        from apps.sales.models import SalePayment

        qs = SalePayment.objects.filter(
            organisation=organisation, invoice__customer__isnull=False
        )
        if date_from:
            qs = qs.filter(received_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(received_at__date__lte=date_to)

        totals = (
            qs.values(
                "invoice__customer__id",
                "invoice__customer__name",
            )
            .annotate(total_received=Sum("amount"), payment_count=Count("id"))
            .order_by("-total_received")
        )

        method_rows = (
            qs.values("invoice__customer__id", "method")
            .annotate(total=Sum("amount"))
        )
        method_map: dict = {}
        for r in method_rows:
            cid = r["invoice__customer__id"]
            method_map.setdefault(cid, {}).setdefault(r["method"], Decimal("0"))
            method_map[cid][r["method"]] = r["total"] or Decimal("0")

        methods = ["cash", "bank_transfer", "pos", "cheque", "credit_applied"]
        result = []
        for r in totals:
            cid = r["invoice__customer__id"]
            breakdown = {m: method_map.get(cid, {}).get(m, Decimal("0")) for m in methods}
            result.append(
                {
                    "customer_id": str(cid),
                    "customer_name": r["invoice__customer__name"],
                    "total_received": r["total_received"],
                    "payment_count": r["payment_count"],
                    "breakdown": breakdown,
                }
            )
        return result

    @staticmethod
    def customer_payments(
        organisation,
        customer_id: str,
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> list[dict]:
        """Individual SalePayment rows for one customer in the period."""
        from apps.sales.models import SalePayment

        qs = SalePayment.objects.filter(
            organisation=organisation, invoice__customer__id=customer_id
        )
        if date_from:
            qs = qs.filter(received_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(received_at__date__lte=date_to)
        qs = qs.select_related("invoice").order_by("-received_at")

        return [
            {
                "date": p.received_at,
                "amount": p.amount,
                "method": p.method,
                "invoice_number": p.invoice.invoice_number,
                "reference": p.reference,
            }
            for p in qs
        ]

    # ─── Account Statement (GL) ──────────────────────────────────────────────

    @staticmethod
    def account_statement(
        organisation,
        account_id: str,
        date_from: Optional[date],
        date_to: Optional[date],
    ) -> dict:
        """
        Standard GL statement for one Account: opening balance, chronological
        lines with running balance, and closing balance.

        Normal balance side follows Account.balance: asset/expense/cogs types
        are debit-normal (debits − credits); liability/equity/revenue types
        are credit-normal (credits − debits).
        """
        from apps.accounting.models import Account, AccountType, JournalLine

        account = Account.objects.get(organisation=organisation, id=account_id)
        is_debit_normal = account.account_type in [
            AccountType.ASSET, AccountType.EXPENSE, AccountType.COST_OF_GOODS,
        ]

        base_qs = JournalLine.objects.filter(
            account=account,
            journal_entry__organisation=organisation,
            journal_entry__status="posted",
        )

        opening_qs = base_qs
        if date_from:
            opening_qs = opening_qs.filter(journal_entry__entry_date__lt=date_from)
        else:
            opening_qs = opening_qs.none()
        opening_agg = opening_qs.aggregate(d=Sum("debit"), c=Sum("credit"))
        opening_debit = opening_agg["d"] or Decimal("0")
        opening_credit = opening_agg["c"] or Decimal("0")
        opening_balance = (
            opening_debit - opening_credit
            if is_debit_normal
            else opening_credit - opening_debit
        )

        period_qs = base_qs
        period_qs = _date_filter(period_qs, "journal_entry__entry_date", date_from, date_to)
        period_qs = period_qs.select_related("journal_entry").order_by(
            "journal_entry__entry_date", "created_at"
        )

        running = opening_balance
        lines = []
        for line in period_qs:
            delta = (
                line.debit - line.credit
                if is_debit_normal
                else line.credit - line.debit
            )
            running += delta
            lines.append(
                {
                    "date": line.journal_entry.entry_date,
                    "journal_entry_reference": line.journal_entry.reference,
                    "description": line.description or line.journal_entry.description,
                    "debit": line.debit,
                    "credit": line.credit,
                    "running_balance": running,
                }
            )

        return {
            "account": {
                "id": str(account.id),
                "code": account.code,
                "name": account.name,
                "account_type": account.account_type,
            },
            "opening_balance": opening_balance,
            "lines": lines,
            "closing_balance": running,
        }

    # ─── Customer Details (master directory) ─────────────────────────────────

    @staticmethod
    def customer_details(organisation) -> list[dict]:
        """Master customer directory with lifetime sales/payment totals."""
        from apps.customers.models import Customer
        from apps.sales.models import Invoice, SalePayment

        customers = Customer.objects.filter(organisation=organisation)

        sales_map = dict(
            Invoice.objects.filter(organisation=organisation, customer__in=customers)
            .values("customer_id")
            .annotate(total=Sum("total_amount"))
            .values_list("customer_id", "total")
        )
        payments_map = dict(
            SalePayment.objects.filter(
                organisation=organisation, invoice__customer__in=customers
            )
            .values("invoice__customer_id")
            .annotate(total=Sum("amount"))
            .values_list("invoice__customer_id", "total")
        )

        return [
            {
                "customer_id": str(c.id),
                "code": c.code,
                "name": c.name,
                "customer_type": c.customer_type,
                "email": c.email,
                "phone": c.phone,
                "outstanding_balance": c.outstanding_balance,
                "credit_limit": c.credit_limit,
                "total_sales": sales_map.get(c.id) or Decimal("0"),
                "total_payments": payments_map.get(c.id) or Decimal("0"),
            }
            for c in customers
        ]

    # ─── Product Details (master directory) ──────────────────────────────────

    @staticmethod
    def product_details(organisation) -> list[dict]:
        """Master product directory with current stock and margin %."""
        from apps.inventory.models import Product, StockItem

        products = Product.objects.filter(organisation=organisation).select_related("category")

        stock_map = dict(
            StockItem.objects.filter(organisation=organisation)
            .values("product_id")
            .annotate(total_qty=Sum("quantity_on_hand"))
            .values_list("product_id", "total_qty")
        )

        rows = []
        for p in products:
            stock_qty = stock_map.get(p.id) or Decimal("0")
            if p.selling_price and p.selling_price > 0:
                margin_pct = (
                    (p.selling_price - p.cost_price) / p.selling_price * 100
                ).quantize(Decimal("0.01"))
            else:
                margin_pct = Decimal("0")
            rows.append(
                {
                    "product_id": str(p.id),
                    "sku": p.sku,
                    "name": p.name,
                    "category_name": p.category.name if p.category else "Uncategorised",
                    "cost_price": p.cost_price,
                    "selling_price": p.selling_price,
                    "stock_quantity": stock_qty,
                    "reorder_level": p.reorder_level,
                    "margin_pct": margin_pct,
                }
            )
        return rows
