"""
Expenses and miscellaneous income models.

Expense categories are user-configurable per organisation.
Both expenses and income are tracked here for P&L calculation.
"""

from django.conf import settings
from django.db import models
from apps.core.models import MoneyField, TenantAwareModel


class ExpenseCategory(TenantAwareModel):
    """User-defined expense categories (e.g., Rent, Transport, Salaries)."""

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_income = models.BooleanField(
        default=False, help_text="True for income categories (e.g., miscellaneous income)"
    )

    class Meta(TenantAwareModel.Meta):
        unique_together = [["organisation", "name"]]
        verbose_name_plural = "Expense Categories"

    def __str__(self):
        return self.name


class ExpenseGroup(TenantAwareModel):
    """
    A named folder for grouping expenses and income records.
    Supports unlimited nesting (parent → children) for hierarchical organisation.
    Example: "January 2026 Market Run" → "Beverages", "Snacks", "Transport"
    """

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    group_date = models.DateField(null=True, blank=True, help_text="Date of the event/run (optional)")
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='children'
    )

    class Meta(TenantAwareModel.Meta):
        ordering = ['-group_date', 'name']

    def __str__(self):
        return self.name

    def get_ancestors(self):
        ancestors = []
        current = self.parent
        while current:
            ancestors.insert(0, {'id': str(current.id), 'name': current.name})
            current = current.parent
        return ancestors


class Expense(TenantAwareModel):
    """
    A single expense or miscellaneous income record.

    is_income=True → miscellaneous income (not a sale)
    is_income=False → expense/cost
    """

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        BANK = "bank", "Bank Transfer"
        CHEQUE = "cheque", "Cheque"
        CARD = "card", "Card"

    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.PROTECT, related_name="expenses"
    )
    amount = MoneyField()
    is_income = models.BooleanField(default=False, db_index=True)
    description = models.TextField()
    expense_date = models.DateField(db_index=True)
    payment_method = models.CharField(
        max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )
    reference = models.CharField(max_length=100, blank=True)
    attachment = models.FileField(upload_to="expense_docs/", null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_expenses",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="approved_expenses",
    )
    is_approved = models.BooleanField(default=False)
    previous_price = MoneyField(null=True, blank=True, help_text="Previous/old price for comparison")
    group = models.ForeignKey(
        ExpenseGroup, null=True, blank=True, on_delete=models.SET_NULL, related_name='expenses'
    )
    budget = models.ForeignKey(
        'budgets.Budget', null=True, blank=True, on_delete=models.SET_NULL, related_name='expenses'
    )

    # GL auto-post tracking
    GL_STATUS = [
        ('pending', 'Pending'), ('posted', 'Posted'),
        ('failed', 'Failed'), ('not_configured', 'Not Configured'),
    ]
    gl_post_status = models.CharField(max_length=20, choices=GL_STATUS, default='pending')
    gl_post_error  = models.TextField(blank=True, default='')

    class Meta(TenantAwareModel.Meta):
        indexes = [
            models.Index(fields=["organisation", "expense_date"]),
            models.Index(fields=["organisation", "is_income"]),
            models.Index(fields=["category", "expense_date"]),
        ]

    def __str__(self):
        sign = "+" if self.is_income else "-"
        return f"{sign}{self.amount} | {self.category} | {self.expense_date}"
