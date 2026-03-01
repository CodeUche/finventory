"""
Credit management models.

Tracks outstanding customer balances, payment history, and aging.

Design:
    - CreditTransaction is the double-entry ledger for credits.
    - Each credit sale debits the customer's account (increases balance).
    - Each payment credits (reduces balance).
    - Aging is calculated dynamically from transaction dates.
"""

from django.conf import settings
from django.db import models
from apps.core.models import MoneyField, TenantAwareModel


class CreditTransaction(TenantAwareModel):
    """
    Immutable record of a credit debit or credit payment.

    type=DEBIT  → customer owes more (sale on credit)
    type=CREDIT → customer paid (reduces outstanding)
    """

    class TransactionType(models.TextChoices):
        DEBIT = "debit", "Debit (Sale on Credit)"
        CREDIT = "credit", "Credit (Payment Received)"
        ADJUSTMENT = "adjustment", "Adjustment"
        WRITE_OFF = "write_off", "Write-Off"

    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, related_name="credit_transactions"
    )
    invoice = models.ForeignKey(
        "sales.Invoice", null=True, blank=True, on_delete=models.SET_NULL, related_name="credit_txns"
    )
    transaction_type = models.CharField(max_length=15, choices=TransactionType.choices, db_index=True)
    amount = MoneyField(help_text="Always positive; sign determined by transaction_type")
    balance_after = MoneyField(help_text="Denormalised running balance for this customer")
    due_date = models.DateField(null=True, blank=True)
    description = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="credit_transactions"
    )

    class Meta(TenantAwareModel.Meta):
        indexes = [
            models.Index(fields=["customer", "created_at"]),
            models.Index(fields=["due_date"]),
        ]

    def __str__(self):
        return f"{self.transaction_type} {self.amount} → {self.customer}"
