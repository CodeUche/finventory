"""
Card terminal settlement.

A merchant takes a card payment on their own Moniepoint or OPay terminal. We
cannot push an amount to that terminal — that needs a signed partnership and
certified software — but the money still has to be reconciled against the sale.

So Audity matches rather than controls: the merchant uploads (or receives) the
day's payouts, and each one is tied to the sale it belongs to. Anything that
cannot be matched is surfaced for a human, never guessed onto the nearest sale.
"""

from django.db import models

from apps.core.models import MoneyField, TenantAwareModel


class SettlementBatch(TenantAwareModel):
    """One import of terminal payouts — a CSV export or a provider push."""

    class Source(models.TextChoices):
        UPLOAD = "upload", "File upload"
        PROVIDER = "provider", "Provider feed"

    provider = models.CharField(
        max_length=40, blank=True,
        help_text="Whose terminal these came from, e.g. Moniepoint, OPay.",
    )
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.UPLOAD)
    reference = models.CharField(max_length=120, blank=True)
    statement_date = models.DateField(null=True, blank=True)
    line_count = models.PositiveIntegerField(default=0)
    total_amount = MoneyField(default=0)
    note = models.CharField(max_length=300, blank=True)

    class Meta(TenantAwareModel.Meta):
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider or 'Settlement'} — {self.line_count} payouts"


class SettlementLine(TenantAwareModel):
    """A single payout from the terminal provider."""

    class Status(models.TextChoices):
        UNMATCHED = "unmatched", "Needs review"
        MATCHED = "matched", "Matched"
        OTHER_INCOME = "other_income", "Recorded as other income"
        IGNORED = "ignored", "Ignored"

    batch = models.ForeignKey(
        SettlementBatch, on_delete=models.CASCADE, related_name="lines",
    )
    # The provider's own reference. Unique per organisation so importing the
    # same export twice cannot create the money twice.
    provider_reference = models.CharField(max_length=150)
    paid_at = models.DateTimeField(null=True, blank=True)
    amount = MoneyField(default=0)
    fee = MoneyField(default=0, help_text="What the provider deducted.")
    terminal_id = models.CharField(max_length=60, blank=True)
    card_last4 = models.CharField(max_length=4, blank=True)
    narration = models.CharField(max_length=300, blank=True)

    status = models.CharField(
        max_length=14, choices=Status.choices, default=Status.UNMATCHED, db_index=True,
    )
    payment = models.ForeignKey(
        "sales.SalePayment", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="settlement_lines",
    )
    matched_automatically = models.BooleanField(default=False)
    review_note = models.CharField(max_length=300, blank=True)

    class Meta(TenantAwareModel.Meta):
        ordering = ["-paid_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "provider_reference"],
                name="unique_settlement_reference",
            )
        ]
        indexes = [models.Index(fields=["organisation", "status"])]

    def __str__(self):
        return f"{self.provider_reference} — {self.amount}"
