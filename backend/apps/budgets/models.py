from django.db import models
from apps.core.models import TenantAwareModel, MoneyField
from apps.expenses.models import ExpenseCategory
from apps.authentication.models import User


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
    period_month = models.PositiveIntegerField(null=True, blank=True)  # null = annual
    budgeted_amount = MoneyField(default=0)
    unit_price = MoneyField(null=True, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    description = models.CharField(max_length=500, blank=True)
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
