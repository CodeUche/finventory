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

    po_number = models.CharField(max_length=50, unique=True, db_index=True)
    supplier = models.ForeignKey(
        "suppliers.Supplier", on_delete=models.PROTECT, related_name="purchase_orders"
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
        # po_number is GLOBALLY unique, so we must use a global count
        # to avoid conflicts across multiple organisations.
        count = cls.objects.count() + 1
        return f"PO-{count:06d}"


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
