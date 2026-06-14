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
    def calculate_income_tax(
        organisation, income: Decimal, tax_year: int = None,
        allowances: Decimal = None, tax_type: str = None,
        gross_turnover: Decimal = None,
    ) -> dict:
        """
        Calculate income tax for the organisation using the active tax config.

        For CIT: pass gross_turnover to enforce the 0.5% minimum tax floor.
        For PIT: the 1% of gross income minimum tax floor is always applied.

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
        tax_payable = result.tax_payable
        minimum_tax_applied = False
        minimum_tax_amount = Decimal('0')

        # PIT minimum tax: 1% of gross income (PITA s.37; Finance Act 2020)
        if config.tax_type == TaxConfig.TaxType.INCOME:
            pit_minimum = income * Decimal('0.01')
            if tax_payable < pit_minimum:
                tax_payable = pit_minimum
                minimum_tax_applied = True
                minimum_tax_amount = pit_minimum

        # CIT minimum tax: 0.5% of gross turnover (CITA s.33; Finance Act 2020)
        elif config.tax_type == TaxConfig.TaxType.CORPORATE and gross_turnover:
            cit_minimum = Decimal(str(gross_turnover)) * Decimal('0.005')
            if tax_payable < cit_minimum:
                tax_payable = cit_minimum
                minimum_tax_applied = True
                minimum_tax_amount = cit_minimum

        effective_rate = (tax_payable / income * 100) if income > 0 else Decimal('0')

        return {
            "gross_income": result.gross_income,
            "total_allowances": result.total_allowances,
            "net_taxable_income": result.net_taxable_income,
            "tax_payable": tax_payable,
            "effective_rate": effective_rate,
            "minimum_tax_applied": minimum_tax_applied,
            "minimum_tax_amount": minimum_tax_amount if minimum_tax_applied else None,
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
