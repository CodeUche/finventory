from django.db import models
from apps.core.models import TenantAwareModel, MoneyField
from apps.expenses.models import ExpenseCategory


class Budget(TenantAwareModel):
    DAILY = 'daily'; WEEKLY = 'weekly'; MONTHLY = 'monthly'; QUARTERLY = 'quarterly'; ANNUAL = 'annual'
    PERIOD_CHOICES = [(p, p) for p in [DAILY, WEEKLY, MONTHLY, QUARTERLY, ANNUAL]]
    DRAFT = 'draft'; ACTIVE = 'active'; CLOSED = 'closed'
    STATUS_CHOICES = [(s, s) for s in [DRAFT, ACTIVE, CLOSED]]

    name = models.CharField(max_length=200)
    fiscal_year = models.PositiveIntegerField()
    period_type = models.CharField(max_length=20, choices=PERIOD_CHOICES, default=MONTHLY)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    notes = models.TextField(blank=True)

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

    class Meta:
        ordering = ['category_name', 'period_month']
