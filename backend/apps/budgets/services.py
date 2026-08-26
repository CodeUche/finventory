from decimal import Decimal
from django.db.models import Sum, Q
from .models import Budget, BudgetLine
from apps.expenses.models import Expense
from apps.accounting.models import JournalEntry, JournalLine


class BudgetService:
    @staticmethod
    def _actual_for_line(line, budget, org):
        """
        Actual spend/income for a single BudgetLine.

        Phase 2: when the line has a GL account set (line.account), Actual is
        computed directly from the real ledger — the sum of posted JournalLine
        amounts for that account within the line's period, netted by the
        account's normal balance. This is what makes the account link
        (Phase 1) more than cosmetic: a BudgetLine pointing at "6200 -
        Utilities" now shows the true posted GL activity for that account,
        not a category-name guess. This path deliberately ignores
        Expense.budget — a GL account's balance in a period is a ledger
        fact, not something one budget can "claim" over another; two budgets
        both pointing a line at the same account will correctly show the
        same real Actual.

        Without an account, behaviour is UNCHANGED from Phase 1: matches by
        the ExpenseCategory FK when the line has one, otherwise falls back to
        a case-insensitive category-name match (legacy data with no FK).
        Either way, expenses are only counted if they are EITHER explicitly
        linked to THIS budget via Expense.budget, OR not linked to any budget
        at all (today's plain category-match behaviour, preserved for
        expenses nobody has tagged yet).

        This is the fix for the known bug where the old implementation
        matched purely on category name + fiscal year, ignoring
        Expense.budget entirely — an expense explicitly linked to Budget A
        would leak into Budget B's variance report whenever both budgets
        had a line with the same category name. An explicit link to a
        DIFFERENT budget must never be attributed here even if the
        category matches.
        """
        if line.account_id:
            qs = JournalLine.objects.filter(
                journal_entry__organisation=org,
                journal_entry__status=JournalEntry.POSTED,
                account_id=line.account_id,
                journal_entry__entry_date__year=budget.fiscal_year,
            )
            if line.period_month:
                qs = qs.filter(journal_entry__entry_date__month=line.period_month)
            agg = qs.aggregate(d=Sum('debit'), c=Sum('credit'))
            debits = agg['d'] or Decimal('0')
            credits = agg['c'] or Decimal('0')
            if line.account.effective_normal_balance == 'debit':
                return debits - credits
            return credits - debits
        if line.category:
            qs = Expense.objects.filter(
                organisation=org, category=line.category, expense_date__year=budget.fiscal_year,
            )
        else:
            qs = Expense.objects.filter(
                organisation=org, category__name__iexact=line.category_name,
                expense_date__year=budget.fiscal_year,
            )
        if line.period_month:
            qs = qs.filter(expense_date__month=line.period_month)
        qs = qs.filter(Q(budget=budget) | Q(budget__isnull=True))
        agg = qs.aggregate(t=Sum('amount'))
        return agg['t'] or Decimal('0')

    @staticmethod
    def get_variance_report(budget):
        lines = budget.lines.all()
        org = budget.organisation
        result = []
        for line in lines:
            actual = BudgetService._actual_for_line(line, budget, org)
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

    @staticmethod
    def get_monitoring_rows(org, budget_type=None, status='active'):
        """
        Flat, cross-budget list of every BudgetLine + its variance data, for
        the Budget Monitoring page. `status='all'` includes every budget
        regardless of status; any other value filters to that exact status
        (defaults to 'active' so closed/draft budgets don't clutter the
        default view).
        """
        qs = Budget.objects.filter(organisation=org).prefetch_related('lines__category', 'lines__account')
        if status and status != 'all':
            qs = qs.filter(status=status)
        if budget_type:
            qs = qs.filter(budget_type=budget_type)

        result = []
        for budget in qs:
            for line in budget.lines.all():
                actual = BudgetService._actual_for_line(line, budget, org)
                variance = line.budgeted_amount - actual
                account = None
                if line.account_id:
                    account = {
                        'id': str(line.account_id),
                        'code': line.account.code,
                        'name': line.account.name,
                    }
                result.append({
                    'id': str(line.id),
                    'budget_id': str(budget.id),
                    'budget_name': budget.name,
                    'budget_type': budget.budget_type,
                    'budget_status': budget.status,
                    'category_name': line.category_name,
                    'category_type': line.category_type,
                    'period_month': line.period_month,
                    'budgeted_amount': line.budgeted_amount,
                    'actual_amount': actual,
                    'variance': variance,
                    'over_budget': variance < 0,
                    'account': account,
                })
        return result
