from decimal import Decimal
from django.db.models import Sum, Q
from .models import Budget, BudgetLine
from apps.expenses.models import Expense


class BudgetService:
    @staticmethod
    def get_variance_report(budget):
        lines = budget.lines.all()
        org = budget.organisation
        result = []
        for line in lines:
            actual = Decimal('0')
            # Match by FK when available, otherwise fall back to category name
            if line.category:
                qs = Expense.objects.filter(
                    organisation=org,
                    category=line.category,
                    expense_date__year=budget.fiscal_year,
                )
            else:
                qs = Expense.objects.filter(
                    organisation=org,
                    category__name__iexact=line.category_name,
                    expense_date__year=budget.fiscal_year,
                )
            if line.period_month:
                qs = qs.filter(expense_date__month=line.period_month)
            agg = qs.aggregate(t=Sum('amount'))
            actual = agg['t'] or Decimal('0')
            variance = line.budgeted_amount - actual
            result.append({
                'id': str(line.id),
                'category_name': line.category_name,
                'category_type': line.category_type,
                'period_month': line.period_month,
                'budgeted_amount': line.budgeted_amount,
                'actual_amount': actual,
                'variance': variance,
                'over_budget': variance < 0,
            })
        return result
