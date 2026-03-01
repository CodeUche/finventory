"""Supplier model."""

from django.db import models
from apps.core.models import TenantAwareModel


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
    is_active = models.BooleanField(default=True)

    class Meta(TenantAwareModel.Meta):
        unique_together = [["organisation", "code"]]

    def __str__(self):
        return f"{self.code} – {self.name}"
