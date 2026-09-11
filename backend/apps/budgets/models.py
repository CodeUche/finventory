from django.db import models
from apps.core.models import TenantAwareModel, MoneyField
from apps.expenses.models import ExpenseCategory
from apps.authentication.models import User


class BudgetPeriod(TenantAwareModel):
    """
    A named financial period (e.g. "FY2026", "Q1 2026") that one or more
    Budgets can be pinned to. Additive: existing Budgets keep working with
    period=None and continue to use the bare `fiscal_year` int for their
    date range (see BudgetService.get_allocation_actuals' fallback).
    """
    DRAFT = 'draft'; ACTIVE = 'active'; CLOSED = 'closed'
    STATUS_CHOICES = [(s, s) for s in [DRAFT, ACTIVE, CLOSED]]

    name = models.CharField(max_length=200)
    financial_year = models.PositiveIntegerField()
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='budget_periods_approved',
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-financial_year', 'start_date']

    def __str__(self):
        return f"{self.name} ({self.financial_year})"


class Budget(TenantAwareModel):
    DAILY = 'daily'; WEEKLY = 'weekly'; MONTHLY = 'monthly'; QUARTERLY = 'quarterly'; ANNUAL = 'annual'
    PERIOD_CHOICES = [(p, p) for p in [DAILY, WEEKLY, MONTHLY, QUARTERLY, ANNUAL]]
    DRAFT = 'draft'; ACTIVE = 'active'; CLOSED = 'closed'
    STATUS_CHOICES = [(s, s) for s in [DRAFT, ACTIVE, CLOSED]]
    OPERATIONAL = 'operational'; CAPITAL = 'capital'
    BUDGET_TYPE_CHOICES = [(OPERATIONAL, 'Operational'), (CAPITAL, 'Capital')]

    name = models.CharField(max_length=200)
    fiscal_year = models.PositiveIntegerField()
    period_type = models.CharField(max_length=20, choices=PERIOD_CHOICES, default=MONTHLY)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    notes = models.TextField(blank=True)
    budget_type = models.CharField(max_length=20, choices=BUDGET_TYPE_CHOICES, default=OPERATIONAL)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='budgets_approved'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    # Additive link to a BudgetPeriod (Phase 5). Nullable so every existing
    # Budget row keeps working unchanged with period=None — fiscal_year
    # stays the source of truth for those. When set, BudgetAllocation actuals
    # use the period's start/end date instead of the bare calendar year.
    period = models.ForeignKey(
        BudgetPeriod, null=True, blank=True, on_delete=models.SET_NULL, related_name='budgets',
    )
    # Phase 6 (B7): a plain user-editable percentage for the lightweight
    # Expected Profit / Tax / Budget Amount roll-up panel. Deliberately NOT
    # wired into TaxService.calculate_income_tax / TaxConfig — that engine
    # needs an active TaxConfig plus gross_turnover/fixed_assets a Budget has
    # no concept of, and is overkill for what's meant to be a quick planning
    # figure, not a statutory computation.
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        ordering = ['-fiscal_year', 'name']

    def __str__(self):
        return f"{self.name} ({self.fiscal_year})"


class BudgetLine(TenantAwareModel):
    EXPENSE = 'expense'; REVENUE = 'revenue'
    TYPE_CHOICES = [(EXPENSE, 'Expense'), (REVENUE, 'Revenue')]

    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='lines')
    category = models.ForeignKey(ExpenseCategory, null=True, blank=True, on_delete=models.SET_NULL)
    category_name = models.CharField(max_length=200)  # denormalised in case category deleted
    category_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=EXPENSE)
    # Phase 7 (B6b): free-text refinement WITHIN revenue/expense (e.g.
    # "Online Sales" under Revenue, "Fuel" under Expense) — additive, parallel
    # to how category_name denormalises the category FK.
    sub_category = models.CharField(max_length=200, blank=True, default='')
    period_month = models.PositiveIntegerField(null=True, blank=True)  # null = annual
    budgeted_amount = MoneyField(default=0)
    # Phase 7 (B10): a planner's forward-looking estimate, separate from the
    # committed budgeted_amount — purely informational, never posted to GL.
    forecast_amount = MoneyField(null=True, blank=True)
    unit_price = MoneyField(null=True, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    description = models.CharField(max_length=500, blank=True)
    # Phase 7 (B6c): supporting document for this line (a quote, an invoice,
    # a contract) — same plain FileField pattern as Account.attachment /
    # JournalEntry.attachment.
    attachment = models.FileField(upload_to='budget_line_attachments/', null=True, blank=True)
    # Optional link to the real Chart of Accounts, additive to the free-text
    # category above. Phase 1 only: this is a plain FK for reporting/grouping
    # purposes — it does NOT feed GL posting (see apps/accounting/services.py,
    # deliberately untouched here; that wiring is Phase 2).
    account = models.ForeignKey(
        'accounting.Account', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='budget_lines',
    )

    class Meta:
        ordering = ['category_name', 'period_month']


class BudgetAllocation(TenantAwareModel):
    """
    A GL-account-level allocation of a Budget's total: "this budget sets
    aside ₦X for account 6200 - Utilities". Distinct from BudgetLine (which
    is a category/month planning row, account optional) — an allocation
    always names a real Chart-of-Accounts account and its spent/remaining
    figures are derived straight from posted GL activity (see
    BudgetService.get_allocation_actuals), not from Expense records.

    account uses PROTECT rather than SET_NULL/CASCADE: an allocation with no
    account is meaningless, and an account that's had money allocated
    against it should not be silently deletable out from under that
    allocation — the delete must be blocked and handled explicitly instead.
    """
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='allocations')
    account = models.ForeignKey(
        'accounting.Account', on_delete=models.PROTECT, related_name='budget_allocations',
    )
    allocated_amount = MoneyField(default=0)
    notes = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['account__code']
