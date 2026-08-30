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
        # Unique among LIVE rows only. Deletion here is a soft delete, so a plain
        # unique_together kept counting the deleted row: delete a category and
        # its name was reserved forever, with the API answering "already exists"
        # about something the user could no longer see anywhere.
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "name"],
                condition=models.Q(is_deleted=False),
                name="uniq_inventory_category_org_name",
            ),
        ]

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
        # Live rows only — see Category above. Deleting "Lagos" used to reserve
        # that warehouse name permanently.
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "name"],
                condition=models.Q(is_deleted=False),
                name="uniq_inventory_warehouse_org_name",
            ),
        ]

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
        VARIABLE = "variable", "Variable (has variants)"
        COMBO = "combo", "Combo / Bundle"

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

    class BarcodeSymbology(models.TextChoices):
        CODE128 = "code128", "Code 128"
        CODE39 = "code39", "Code 39"
        EAN8 = "ean8", "EAN-8"
        EAN13 = "ean13", "EAN-13"
        UPC = "upc", "UPC"

    barcode = models.CharField(max_length=100, blank=True)
    barcode_symbology = models.CharField(
        max_length=10, choices=BarcodeSymbology.choices, default=BarcodeSymbology.CODE128,
        help_text="Format the barcode is encoded/printed as. Only affects generation and scanning, not the stored value.",
    )
    image = models.ImageField(upload_to="products/", null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    # Off by default: publishing a merchant's whole catalogue to the internet
    # the moment they enable a storefront would be a nasty surprise.
    is_published = models.BooleanField(
        default=False, db_index=True,
        help_text="Show this item on the public storefront.",
    )

    # ── FIRS e-invoicing fields ───────────────────────────────────────────────
    hsn_code = models.CharField(
        max_length=20, blank=True,
        help_text="Harmonized System Nomenclature code — required for FIRS e-invoicing line items.",
    )
    digitax_item_id = models.CharField(
        max_length=100, blank=True,
        help_text="DigiTax-assigned item ID after POST /items. Cached to avoid re-registration.",
    )
    is_taxable = models.BooleanField(default=True)
    tax_class = models.ForeignKey(
        "tax.TaxClass", null=True, blank=True, on_delete=models.SET_NULL, related_name="products"
    )

    class TaxType(models.TextChoices):
        EXCLUSIVE = "exclusive", "Exclusive (tax added on top)"
        INCLUSIVE = "inclusive", "Inclusive (tax already in the price)"

    # Default 'exclusive' preserves every existing product's current behaviour
    # (VAT has always been calculated as added on top of unit_price).
    tax_type = models.CharField(
        max_length=10, choices=TaxType.choices, default=TaxType.EXCLUSIVE,
        help_text="Whether this item's price already includes tax, or tax is added on top at sale.",
    )

    # Optional per-product inventory control account. Blank falls back to the org
    # AccountMapping 'inventory_account' role, then to code 1200.
    inventory_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="products", limit_choices_to={"is_active": True},
        help_text="GL control account for this item's stock. Leave blank to use the organisation default.",
    )
    # Per-product Sales/COGS overrides — same "blank falls back to org
    # AccountMapping" pattern as inventory_account above. Shared by both
    # physical and service products (the reviewer's "Inventory GL Mapped" and
    # "Service GL Mapped" blocks both have a Sales Acct and a Cost of Sales
    # Acct; only the debit side for services differs — see wages_account).
    sales_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="products_as_sales_account", limit_choices_to={"is_active": True},
        help_text="GL revenue account for this item's sales. Leave blank to use the organisation default.",
    )
    cogs_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="products_as_cogs_account", limit_choices_to={"is_active": True},
        help_text="GL cost-of-sales account for this item. Leave blank to use the organisation default.",
    )
    # Service products only: when set, a sale debits this account instead of
    # cogs_account (e.g. "Wages Expense" instead of generic "Cost of Sales").
    wages_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="products_as_wages_account", limit_choices_to={"is_active": True},
        help_text="Service products only — GL wages/direct-labor account debited on a sale instead of cogs_account.",
    )

    class CostingMethod(models.TextChoices):
        FIFO = "fifo", "FIFO"
        LIFO = "lifo", "LIFO"
        AVERAGE = "average", "Average"
        SPECIFIC = "specific", "Specific Unit"

    costing_method = models.CharField(
        max_length=10, choices=CostingMethod.choices, default=CostingMethod.AVERAGE,
        help_text="How cost of goods sold is determined for this item on a sale.",
    )

    # ── Variants ──────────────────────────────────────────────────────────────
    # A variant IS a full Product row (own SKU, price, stock, costing) that
    # points back at a "template" product (product_type=VARIABLE) which is
    # never itself sold or stocked — it exists only to group its variants in
    # the catalogue UI. This mirrors how Shopify/WooCommerce model variants
    # under the hood, and reuses every bit of pricing/stock/costing/GL
    # machinery already built for ordinary products instead of inventing a
    # parallel system.
    parent_product = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE,
        related_name="variants",
        help_text="Set on a variant row to link it to its Variable Product template.",
    )
    variant_attributes = models.JSONField(
        default=dict, blank=True,
        help_text='Display attributes for this variant, e.g. {"Size": "Large", "Color": "Red"}.',
    )

    @staticmethod
    def _gs1_check_digit(digits: str) -> str:
        """
        Standard GS1 check digit: weight the digits 3,1,3,1... starting from
        the RIGHTMOST digit, sum, subtract from the next multiple of 10. The
        same algorithm produces a valid check digit for EAN-8, UPC-A (treated
        as an 11-digit base), and EAN-13 (a 12-digit base) alike.
        """
        total = sum(
            int(d) * (3 if i % 2 == 0 else 1)
            for i, d in enumerate(reversed(digits))
        )
        return str((10 - total % 10) % 10)

    @classmethod
    def generate_barcode(cls, organisation, symbology=None) -> str:
        """
        A system-generated barcode for a product that doesn't have a real one
        already — the reviewer's "best practice: system generated, not
        manually entered" request. Manual entry stays available for products
        that already have a printed barcode; this only fills the gap when the
        field is left blank.

        EAN-8/EAN-13/UPC need a numeric value with a valid check digit to
        actually scan; Code 128/39 have no such constraint, so those get a
        simple sequential alphanumeric code instead. Sequenced per
        organisation via a count of existing barcodes — not a globally
        registered GS1 prefix, since these are internal shop codes, not resold
        retail products that need a real manufacturer prefix.
        """
        symbology = symbology or cls.BarcodeSymbology.CODE128
        seq = cls.all_objects.filter(organisation=organisation).exclude(barcode="").count() + 1
        if symbology == cls.BarcodeSymbology.EAN13:
            base = str(seq).zfill(12)[-12:]
            return base + cls._gs1_check_digit(base)
        if symbology == cls.BarcodeSymbology.UPC:
            base = str(seq).zfill(11)[-11:]
            return base + cls._gs1_check_digit(base)
        if symbology == cls.BarcodeSymbology.EAN8:
            base = str(seq).zfill(7)[-7:]
            return base + cls._gs1_check_digit(base)
        # Code 128 / Code 39 — alphanumeric, no checksum requirement.
        org_prefix = str(organisation.id).replace("-", "")[:4].upper()
        return f"{org_prefix}{seq:08d}"

    class Meta(TenantAwareModel.Meta):
        # Live rows only — see Category above. A deleted product used to hold its
        # SKU forever, so re-adding an item you had removed was impossible.
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "sku"],
                condition=models.Q(is_deleted=False),
                name="uniq_inventory_product_org_sku",
            ),
        ]
        indexes = [
            models.Index(fields=["organisation", "is_active"]),
            models.Index(fields=["organisation", "category"]),
        ]

    def __str__(self):
        return f"{self.sku} – {self.name}"


class ComboComponent(TenantAwareModel):
    """
    One line of a Combo/Bundle Product's bill-of-materials: "this combo is
    made of `quantity` units of `component_product`".

    A combo has no stock of its own — it isn't a physical thing sitting on a
    shelf, it's an assembly instruction. Selling one combo unit deducts
    `quantity` units of each component from that component's own stock (see
    SalesService), so existing per-component costing/GL/reorder-alert
    machinery keeps working untouched; the combo itself never needs a
    StockItem.
    """

    combo_product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="combo_components",
        help_text="The Combo Product this line belongs to.",
    )
    component_product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="used_in_combos",
        help_text="The underlying product consumed when the combo is sold.",
    )
    quantity = models.DecimalField(
        max_digits=12, decimal_places=2, default=1,
        help_text="How many units of the component one combo unit consumes.",
    )

    class Meta(TenantAwareModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["combo_product", "component_product"],
                condition=models.Q(is_deleted=False),
                name="uniq_combo_component_per_combo",
            ),
        ]

    def __str__(self):
        return f"{self.combo_product.sku}: {self.quantity} x {self.component_product.sku}"


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
    # Running weighted-average unit cost, recomputed on every inbound movement
    # regardless of the product's costing_method (so switching a product TO
    # 'average' later has real history instead of starting from zero). Read at
    # sale time only when costing_method == 'average'.
    average_cost = MoneyField(default=Decimal("0"))

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

    product = models.ForeignKey(
        Product, null=True, blank=True, on_delete=models.SET_NULL, related_name="movements"
    )
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
        sku = self.product.sku if self.product_id else "[deleted product]"
        return f"{self.movement_type} {self.quantity} × {sku}"


class StockCostLayer(TenantAwareModel):
    """
    Internal FIFO/LIFO cost layer — one row per inbound movement's remaining
    quantity at its own unit cost. Invisible to users (unlike Batch, which is
    opt-in lot/expiry tracking); this is purely the accounting cost ledger a
    FIFO/LIFO costing_method consumes from oldest/newest first on a sale.

    Created for every inbound movement regardless of the product's
    costing_method, so switching a product to fifo/lifo later has real history
    to consume instead of starting empty.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="cost_layers")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="cost_layers")
    quantity_remaining = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = MoneyField()
    reference = models.CharField(max_length=100, blank=True)

    class Meta(TenantAwareModel.Meta):
        indexes = [
            models.Index(fields=["product", "warehouse", "created_at"]),
        ]

    def __str__(self):
        return f"{self.product.sku} @ {self.warehouse.name}: {self.quantity_remaining} left @ {self.unit_cost}"


class ProductImage(TenantAwareModel):
    """
    One photo in a product's gallery — the reviewer's "Product images gallery
    / Upload one or more images / Click a thumbnail to set the main image /
    Drag to reorder" request. Product.image (a single legacy field) stays in
    sync with whichever image is marked main, so the storefront and anything
    else already reading it directly keeps working unchanged.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    # Validated in ProductImageSerializer (validate_image_upload), matching
    # Organisation.logo / User.avatar — this codebase keeps upload validation
    # at the serializer layer rather than on the model field.
    image = models.ImageField(upload_to="products/gallery/")
    sort_order = models.PositiveIntegerField(default=0)
    is_main = models.BooleanField(default=False)

    class Meta(TenantAwareModel.Meta):
        ordering = ["sort_order", "created_at"]

    def __str__(self):
        return f"{self.product.sku} image {self.sort_order}{' (main)' if self.is_main else ''}"

    def save(self, *args, **kwargs):
        if self.is_main:
            ProductImage.objects.filter(
                organisation=self.organisation, product=self.product, is_main=True,
            ).exclude(pk=self.pk).update(is_main=False)
        super().save(*args, **kwargs)
        if self.is_main:
            Product.objects.filter(pk=self.product_id).update(image=self.image)

    def delete(self, *args, **kwargs):
        was_main = self.is_main
        product = self.product
        super().delete(*args, **kwargs)
        if was_main:
            # Promote the next image (if any) so the storefront isn't left
            # pointing at a file that no longer exists.
            next_image = ProductImage.objects.filter(
                organisation=self.organisation, product=product,
            ).order_by("sort_order", "created_at").first()
            if next_image:
                next_image.is_main = True
                next_image.save(update_fields=["is_main"])
            else:
                Product.objects.filter(pk=product.pk).update(image=None)


# Product modifiers live in their own module for clarity; re-exported so Django
# discovers them and existing imports keep working.
from .modifier_models import ModifierGroup, ModifierOption  # noqa: E402,F401
