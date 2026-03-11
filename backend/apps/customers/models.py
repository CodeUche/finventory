"""Customer model for retail and wholesale buyers."""

from django.db import models

from apps.core.models import MoneyField, TenantAwareModel


class Customer(TenantAwareModel):
    """
    Represents a buyer (retail customer or wholesale client).

    credit_limit = 0 means no credit allowed (cash only).
    """

    class CustomerType(models.TextChoices):
        RETAIL = "retail", "Retail"
        WHOLESALE = "wholesale", "Wholesale"
        DISTRIBUTOR = "distributor", "Distributor"
        CORPORATE = "corporate", "Corporate"
        CLIENT = "client", "Client"
        PASSENGER = "passenger", "Passenger"
        VIP = "vip", "VIP"
        GOVERNMENT = "government", "Government"
        NGO = "ngo", "NGO"

    code = models.CharField(max_length=50, db_index=True)
    name = models.CharField(max_length=255)
    customer_type = models.CharField(
        max_length=20, choices=CustomerType.choices, default=CustomerType.RETAIL
    )
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    contact_person = models.CharField(max_length=200, blank=True)

    # Credit settings
    credit_limit = MoneyField(default=0, help_text="Maximum outstanding balance allowed")
    payment_terms_days = models.PositiveSmallIntegerField(
        default=0, help_text="Net payment terms in days (0 = cash on delivery)"
    )

    # Denormalised outstanding balance (updated by credit service)
    outstanding_balance = MoneyField(default=0)

    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta(TenantAwareModel.Meta):
        unique_together = [["organisation", "code"]]
        indexes = [models.Index(fields=["organisation", "name"])]

    def __str__(self):
        return f"{self.code} – {self.name}"

    @property
    def available_credit(self):
        return max(self.credit_limit - self.outstanding_balance, 0)

    @property
    def is_credit_blocked(self) -> bool:
        return self.outstanding_balance >= self.credit_limit and self.credit_limit > 0
