"""
Tax service: orchestrates tax return creation and VAT reporting.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.sales.models import SaleItem

from .engine import TaxEngine
from .models import TaxConfig, TaxReturn

logger = logging.getLogger(__name__)


class TaxService:

    @staticmethod
    def calculate_income_tax(organisation, income: Decimal, tax_year: int = None, allowances: Decimal = None, tax_type: str = None) -> dict:
        """
        Calculate income tax for the organisation using the active tax config.

        Returns a full breakdown suitable for tax return generation.
        """
        year = tax_year or timezone.now().year
        allowed_types = [tax_type] if tax_type in ['income', 'corporate'] else [TaxConfig.TaxType.INCOME, TaxConfig.TaxType.CORPORATE]
        config = TaxConfig.objects.filter(
            organisation=organisation,
            tax_type__in=allowed_types,
            tax_year=year,
            is_active=True,
        ).first()

        if not config:
            raise ValueError(f"No active income tax configuration found for {year}.")

        result = TaxEngine.calculate(income=income, config=config, allowances=allowances)

        return {
            "gross_income": result.gross_income,
            "total_allowances": result.total_allowances,
            "net_taxable_income": result.net_taxable_income,
            "tax_payable": result.tax_payable,
            "effective_rate": result.effective_rate,
            "brackets": [
                {
                    "bracket": f"{b.lower:,.0f} – {'∞' if b.upper is None else f'{b.upper:,.0f}'}",
                    "rate": b.rate,
                    "taxable_amount": b.taxable_in_bracket,
                    "tax": b.tax_in_bracket,
                }
                for b in result.brackets
            ],
            "config": config.name,
            "tax_year": year,
        }

    @staticmethod
    def calculate_vat_report(organisation, period_start, period_end) -> dict:
        """
        Aggregate VAT collected on sales for a given period.

        Returns VAT output (collected on sales) and VAT input (paid on purchases — future).
        """
        # VAT output (collected from customers)
        sales_vat = SaleItem.objects.filter(
            organisation=organisation,
            invoice__issue_date__gte=period_start,
            invoice__issue_date__lte=period_end,
            invoice__status__in=["paid", "confirmed", "partially_paid", "credit"],
        ).aggregate(
            total_vat=Sum("tax_amount"),
            total_net=Sum("line_total"),
        )

        output_vat = sales_vat["total_vat"] or Decimal("0")
        net_sales = sales_vat["total_net"] or Decimal("0")

        # VAT input (from supplier bills approved/paid in the period)
        from apps.bills.models import Bill
        bills_vat = Bill.objects.filter(
            organisation=organisation,
            issue_date__gte=period_start,
            issue_date__lte=period_end,
            status__in=[Bill.APPROVED, Bill.PAID, Bill.PARTIALLY_PAID],
        ).aggregate(total_vat=Sum("tax_amount"))
        input_vat = bills_vat["total_vat"] or Decimal("0")
        net_vat_payable = output_vat - input_vat

        return {
            "period_start": period_start,
            "period_end": period_end,
            "vat_output": output_vat,
            "vat_input": input_vat,
            "net_vat_payable": net_vat_payable,
            "total_net_sales": net_sales,
        }

    @staticmethod
    @transaction.atomic
    def create_tax_return(organisation, config: TaxConfig, period_start, period_end) -> TaxReturn:
        """Create or update a draft tax return for the given period."""
        # Calculate totals from the financial data
        from apps.expenses.models import Expense
        from apps.sales.models import Invoice
        from django.db.models import Sum

        # Total sales revenue
        revenue = Invoice.objects.filter(
            organisation=organisation,
            issue_date__gte=period_start,
            issue_date__lte=period_end,
            status__in=["paid", "confirmed", "partially_paid"],
        ).aggregate(total=Sum("total_amount"))["total"] or Decimal("0")

        # Total expenses (COGS + operating)
        expenses = Expense.objects.filter(
            organisation=organisation,
            expense_date__gte=period_start,
            expense_date__lte=period_end,
            is_income=False,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        taxable_income = max(revenue - expenses, Decimal("0"))
        result = TaxEngine.calculate(income=taxable_income, config=config)

        tax_return, _ = TaxReturn.objects.update_or_create(
            organisation=organisation,
            config=config,
            period_start=period_start,
            period_end=period_end,
            defaults={
                "period_type": TaxReturn.PeriodType.ANNUAL,
                "status": TaxReturn.Status.DRAFT,
                "total_taxable_income": revenue,
                "total_allowances": result.total_allowances,
                "net_taxable_income": result.net_taxable_income,
                "tax_payable": result.tax_payable,
                "tax_paid": Decimal("0"),
                "tax_due": result.tax_payable,
            },
        )
        return tax_return
