"""
Purchase Order models.

Workflow: DRAFT → SENT → RECEIVED (partial or full) → CLOSED

Receiving a PO triggers stock inward movements via InventoryService.
"""

from django.conf import settings
from django.db import models
from apps.core.models import MoneyField, TenantAwareModel


class PurchaseOrder(TenantAwareModel):
    """Header for a purchase order sent to a supplier."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent to Supplier"
        PARTIALLY_RECEIVED = "partially_received", "Partially Received"
        RECEIVED = "received", "Fully Received"
        CLOSED = "closed", "Closed"
        CANCELED = "canceled", "Canceled"

    class DeliveryType(models.TextChoices):
        SELF_COLLECTION = "self_collection", "Self Collection"
        HAULAGE = "haulage", "Haulage / Courier"
        OTHER = "other", "Other"

    po_number = models.CharField(max_length=50, unique=True, db_index=True)
    supplier = models.ForeignKey(
        "suppliers.Supplier", null=True, blank=True,
        on_delete=models.PROTECT, related_name="purchase_orders"
    )
    warehouse = models.ForeignKey(
        "inventory.Warehouse", on_delete=models.PROTECT, related_name="purchase_orders"
    )
    status = models.CharField(max_length=25, choices=Status.choices, default=Status.DRAFT)
    order_date = models.DateField()
    expected_date = models.DateField(null=True, blank=True)
    received_date = models.DateField(null=True, blank=True)
    subtotal = MoneyField()
    tax_amount = MoneyField()
    total_amount = MoneyField()
    delivery_type = models.CharField(
        max_length=20, choices=DeliveryType.choices,
        default=DeliveryType.SELF_COLLECTION, blank=True
    )
    delivery_notes = models.CharField(max_length=255, blank=True, help_text="Custom delivery instructions")
    notes = models.TextField(blank=True)
    receipt = models.FileField(upload_to="purchase_receipts/", null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="purchase_orders"
    )

    class Meta(TenantAwareModel.Meta):
        indexes = [models.Index(fields=["organisation", "status", "order_date"])]

    def __str__(self):
        return self.po_number

    @classmethod
    def generate_number(cls, organisation):
        """
        Generate a collision-safe PO number using org-specific prefix + MAX().

        Format: PO-XXXX-000001  (XXXX = first 4 hex chars of org UUID)
        Uses MAX() on existing numbers (not count) so deletions/voids never
        cause duplicate key errors.
        """
        from django.db.models import Max
        import re

        prefix = str(organisation.id).replace("-", "")[:4].upper()
        pattern = f"PO-{prefix}-"

        last = (
            cls.objects.filter(po_number__startswith=pattern)
            .aggregate(m=Max("po_number"))["m"]
        )
        if last:
            m = re.search(r"-(\d+)$", last)
            next_seq = (int(m.group(1)) + 1) if m else 1
        else:
            next_seq = 1

        candidate = f"{pattern}{next_seq:06d}"
        # Safety: if somehow a collision still exists, keep incrementing
        while cls.objects.filter(po_number=candidate).exists():
            next_seq += 1
            candidate = f"{pattern}{next_seq:06d}"
        return candidate


class PurchaseOrderItem(TenantAwareModel):
    """A single line item on a purchase order."""

    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(
        "inventory.Product", on_delete=models.PROTECT, related_name="po_items"
    )
    quantity_ordered = models.DecimalField(max_digits=12, decimal_places=2)
    quantity_received = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_cost = MoneyField()
    line_total = MoneyField()
    batch_number = models.CharField(max_length=100, blank=True)
    expiry_date = models.DateField(null=True, blank=True)

    class Meta(TenantAwareModel.Meta):
        pass

    def __str__(self):
        return f"{self.product.sku} × {self.quantity_ordered}"

    @property
    def is_fully_received(self) -> bool:
        return self.quantity_received >= self.quantity_ordered
