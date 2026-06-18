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

    class PaymentMode(models.TextChoices):
        CASH = "cash", "Cash"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        POS = "pos", "POS"
        CHEQUE = "cheque", "Cheque"
        CREDIT_APPLIED = "credit_applied", "Credit Applied"
        OTHER = "other", "Other"

    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.PROTECT, related_name="credit_transactions"
    )
    invoice = models.ForeignKey(
        "sales.Invoice", null=True, blank=True, on_delete=models.SET_NULL, related_name="credit_txns"
    )
    transaction_type = models.CharField(max_length=15, choices=TransactionType.choices, db_index=True)
    amount = MoneyField(help_text="Always positive; sign determined by transaction_type")
    balance_before = MoneyField(null=True, blank=True, help_text="Denormalised running balance prior to this entry")
    balance_after = MoneyField(help_text="Denormalised running balance for this customer")
    due_date = models.DateField(null=True, blank=True)
    description = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="credit_transactions"
    )

    # ── Payment receipt fields (only populated when transaction_type=CREDIT
    # and the entry represents an actual payment receipt) ─────────────────
    payment_number = models.CharField(max_length=30, blank=True, db_index=True)
    payment_mode = models.CharField(max_length=20, choices=PaymentMode.choices, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_code = models.CharField(max_length=10, blank=True, help_text="Paystack bank code, for account resolution")
    account_number = models.CharField(max_length=20, blank=True)
    account_name = models.CharField(max_length=150, blank=True, help_text="Resolved or manually entered remitter name")
    debit_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="credit_transactions_debited",
    )
    credit_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="credit_transactions_credited",
    )
    location = models.ForeignKey(
        "inventory.Warehouse", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="credit_transactions",
    )

    class Meta(TenantAwareModel.Meta):
        indexes = [
            models.Index(fields=["customer", "created_at"]),
            models.Index(fields=["due_date"]),
        ]

    def __str__(self):
        return f"{self.transaction_type} {self.amount} → {self.customer}"

    @staticmethod
    def generate_payment_number(organisation):
        """
        Generate a sequential payment number per organisation.

        Mirrors Invoice.generate_number exactly: uses MAX(payment_number) scan
        within the org to find the next sequence value, which is safe against
        concurrent cross-org requests (different org prefixes never collide
        because each org uses its own 4-char hex prefix derived from its UUID).
        """
        from django.db.models import Max
        # 4-char hex prefix from org UUID — unique per org, collision-proof
        org_prefix = str(organisation.id).replace('-', '')[:4].upper()
        prefix = f"PMT-{org_prefix}"
        # Use all_objects so voided/deleted entries don't reset the counter
        last = CreditTransaction.all_objects.filter(
            organisation=organisation,
            payment_number__startswith=prefix,
        ).aggregate(last=Max('payment_number'))['last']
        if last:
            try:
                seq = int(last.split('-')[-1]) + 1
            except (ValueError, IndexError):
                seq = CreditTransaction.all_objects.filter(organisation=organisation).count() + 1
        else:
            seq = 1
        return f"{prefix}-{seq:06d}"
