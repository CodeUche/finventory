"""
Inventory models for a liquor distribution business.

Key design decisions:
    - Products (SKUs) are separate from Stock records to support
      multi-warehouse with different stock levels per location.
    - StockMovement is the immutable ledger of all stock changes.
      Never update stock directly; always go through StockMovement.
    - Batch tracking enables FIFO/FEFO costing and expiry management.
    - Cost price is tracked per batch for accurate COGS calculations.

Scaling:
    - Stock level is denormalised on StockItem for O(1) reads.
    - The ledger (StockMovement) can be archived to a cold table annually.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import MoneyField, TenantAwareModel


class Category(TenantAwareModel):
    """Product category (e.g. Spirits, Beer, Wine, RTD)."""

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )

    class Meta(TenantAwareModel.Meta):
        verbose_name_plural = "categories"
        unique_together = [["organisation", "name"]]

    def __str__(self):
        return self.name


class Warehouse(TenantAwareModel):
    """Physical storage location. Multi-warehouse architecture."""

    name = models.CharField(max_length=200)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_warehouses",
    )

    class Meta(TenantAwareModel.Meta):
        unique_together = [["organisation", "name"]]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Ensure only one default warehouse per organisation
        if self.is_default:
            Warehouse.objects.filter(
                organisation=self.organisation, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class Product(TenantAwareModel):
    """
    A product SKU.

    Supports physical goods, services, and digital products via product_type.
    Physical/digital items track inventory; service items do not.
    """

    class UnitOfMeasure(models.TextChoices):
        BOTTLE = "bottle", "Bottle"
        CARTON = "carton", "Carton"
        CASE = "case", "Case"
        LITRE = "litre", "Litre"
        UNIT = "unit", "Unit"
        HOUR = "hour", "Hour"
        DAY = "day", "Day"
        KG = "kg", "Kilogram"
        PIECE = "piece", "Piece"

    class ProductType(models.TextChoices):
        PHYSICAL = "physical", "Physical (tracked inventory)"
        SERVICE = "service", "Service (no inventory)"
        DIGITAL = "digital", "Digital (no inventory)"

    sku = models.CharField(max_length=100, db_index=True)
    product_type = models.CharField(
        max_length=20,
        choices=ProductType.choices,
        default=ProductType.PHYSICAL,
        db_index=True,
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="products"
    )
    brand = models.CharField(max_length=100, blank=True)
    unit_of_measure = models.CharField(
        max_length=20, choices=UnitOfMeasure.choices, default=UnitOfMeasure.BOTTLE
    )
    # Liquor-specific
    alcohol_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    volume_ml = models.PositiveIntegerField(null=True, blank=True, help_text="Volume in millilitres")

    # Pricing
    cost_price = MoneyField(help_text="Default cost price (overridden per batch)")
    owner_cost_price = MoneyField(
        default=Decimal("0"),
        help_text="Owner's actual purchase cost — visible to owners only for margin analytics",
    )
    selling_price = MoneyField(help_text="Default retail selling price")
    wholesale_price = MoneyField(default=Decimal("0"))

    # Stock control
    reorder_level = models.PositiveIntegerField(
        default=10, help_text="Minimum safety level — alert when stock drops below this"
    )
    max_stock_level = models.PositiveIntegerField(
        null=True, blank=True, help_text="Maximum safety level — do not order above this"
    )
    quantity_in_pack = models.DecimalField(
        max_digits=10, decimal_places=2, default=1,
        help_text="Number of units in one pack / carton"
    )
    reorder_quantity = models.PositiveIntegerField(default=50)

    barcode = models.CharField(max_length=100, blank=True)
    image = models.ImageField(upload_to="products/", null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    is_taxable = models.BooleanField(default=True)
    tax_class = models.ForeignKey(
        "tax.TaxClass", null=True, blank=True, on_delete=models.SET_NULL, related_name="products"
    )

    class Meta(TenantAwareModel.Meta):
        unique_together = [["organisation", "sku"]]
        indexes = [
            models.Index(fields=["organisation", "is_active"]),
            models.Index(fields=["organisation", "category"]),
        ]

    def __str__(self):
        return f"{self.sku} – {self.name}"


class Batch(TenantAwareModel):
    """
    A specific lot/batch of a product with its own cost and expiry.

    Enables:
        - FEFO (First Expired First Out) picking
        - Batch-level cost tracking
        - Recall tracing
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="batches")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="batches")
    batch_number = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_cost = MoneyField(help_text="Cost per unit for this specific batch")
    manufacture_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True, db_index=True)
    min_quantity = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Minimum quantity threshold")
    max_quantity = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Maximum quantity cap")
    qty_per_pack = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Units per pack/carton in this batch")
    is_active = models.BooleanField(default=True)

    class Meta(TenantAwareModel.Meta):
        unique_together = [["organisation", "product", "batch_number"]]
        indexes = [
            models.Index(fields=["expiry_date"]),
            models.Index(fields=["product", "warehouse"]),
        ]

    def __str__(self):
        return f"{self.product.sku} batch {self.batch_number}"

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone
        return self.expiry_date is not None and self.expiry_date < timezone.now().date()


class StockItem(TenantAwareModel):
    """
    Current stock level for a product in a warehouse.

    Denormalised for O(1) stock-level reads.
    Updated atomically whenever a StockMovement is created.

    Use select_for_update() before modifying to prevent race conditions.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_items")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="stock_items")
    quantity_on_hand = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    quantity_reserved = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Reserved for pending sales orders"
    )

    class Meta(TenantAwareModel.Meta):
        unique_together = [["organisation", "product", "warehouse"]]

    def __str__(self):
        return f"{self.product.sku} @ {self.warehouse.name}: {self.quantity_on_hand}"

    @property
    def quantity_available(self) -> Decimal:
        return self.quantity_on_hand - self.quantity_reserved

    @property
    def is_low_stock(self) -> bool:
        return self.quantity_on_hand <= self.product.reorder_level


class StockMovement(TenantAwareModel):
    """
    Immutable ledger entry recording every stock change.

    Append-only: never update or delete. This is the source of truth.
    Recalculate StockItem.quantity_on_hand by summing movements.

    Movement types map to business operations:
        PURCHASE_IN     → purchase order received
        SALE_OUT        → sale recorded
        ADJUSTMENT_IN   → manual positive adjustment
        ADJUSTMENT_OUT  → manual negative adjustment / write-off
        RETURN_IN       → customer return
        TRANSFER_IN/OUT → inter-warehouse transfer
    """

    class MovementType(models.TextChoices):
        PURCHASE_IN = "purchase_in", "Purchase In"
        SALE_OUT = "sale_out", "Sale Out"
        ADJUSTMENT_IN = "adjustment_in", "Adjustment In"
        ADJUSTMENT_OUT = "adjustment_out", "Adjustment Out"
        RETURN_IN = "return_in", "Customer Return In"
        TRANSFER_IN = "transfer_in", "Transfer In"
        TRANSFER_OUT = "transfer_out", "Transfer Out"
        OPENING = "opening", "Opening Stock"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="movements")
    batch = models.ForeignKey(
        Batch, null=True, blank=True, on_delete=models.SET_NULL, related_name="movements"
    )
    movement_type = models.CharField(max_length=20, choices=MovementType.choices, db_index=True)
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="Positive for in, negative for out"
    )
    unit_cost = MoneyField(help_text="Cost at time of movement for COGS calculation")
    reference = models.CharField(max_length=100, blank=True, db_index=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stock_movements"
    )

    # Denormalised running balance for fast reporting
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta(TenantAwareModel.Meta):
        indexes = [
            models.Index(fields=["product", "warehouse", "created_at"]),
            models.Index(fields=["movement_type", "created_at"]),
            models.Index(fields=["reference"]),
        ]

    def __str__(self):
        return f"{self.movement_type} {self.quantity} × {self.product.sku}"
