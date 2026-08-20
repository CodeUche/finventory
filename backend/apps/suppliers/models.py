"""Supplier model."""

from django.db import models
from apps.core.models import TenantAwareModel, MoneyField


class Supplier(TenantAwareModel):
    """Represents a product supplier / vendor."""

    code = models.CharField(max_length=50, db_index=True)
    name = models.CharField(max_length=255)
    contact_person = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    tax_id = models.CharField(max_length=100, blank=True)
    payment_terms_days = models.PositiveSmallIntegerField(default=30)
    notes = models.TextField(blank=True)
    # Take-on opening balance at migration into Audity. Signed: positive = we owe
    # them (credit / payable), negative = they owe us (advance paid).
    opening_balance = MoneyField(default=0)
    # Optional per-supplier payable control account. Blank falls back to the org
    # AccountMapping 'accounts_payable' role, then to code 2001.
    payable_account = models.ForeignKey(
        'accounting.Account', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='suppliers', limit_choices_to={'is_active': True},
        help_text="GL control account for this supplier. Leave blank to use the organisation default.",
    )
    is_active = models.BooleanField(default=True)

    class Meta(TenantAwareModel.Meta):
        # Unique among LIVE rows only — deletion is soft, and a plain
        # unique_together meant a removed supplier held its code permanently.
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "code"],
                condition=models.Q(is_deleted=False),
                name="uniq_supplier_org_code",
            ),
        ]

    def __str__(self):
        return f"{self.code} – {self.name}"
