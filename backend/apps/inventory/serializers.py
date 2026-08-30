"""Inventory serializers."""

from decimal import Decimal

from rest_framework import serializers

from apps.core.validators import validate_image_upload
from .models import Batch, Category, Product, ProductImage, StockItem, StockMovement, Warehouse

_OWNER_ROLES = {"owner", "admin"}


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "description", "parent", "created_at"]
        read_only_fields = ["id", "created_at"]


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ["id", "name", "address", "is_active", "is_default", "manager", "created_at"]
        read_only_fields = ["id", "created_at"]


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "product", "image", "sort_order", "is_main", "created_at"]
        read_only_fields = ["id", "created_at"]
        # Matches Organisation.logo / User.avatar — upload validation lives at
        # the serializer layer, not on the model field.
        extra_kwargs = {"image": {"validators": [validate_image_upload]}}

    def validate_product(self, value):
        request = self.context.get("request")
        if request and hasattr(request, "organisation") and request.organisation:
            if value.organisation_id != request.organisation.id:
                raise serializers.ValidationError("Product does not belong to this organisation.")
        return value


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    total_stock = serializers.SerializerMethodField()
    quantity_incoming = serializers.SerializerMethodField()
    inventory_account_code = serializers.CharField(
        source="inventory_account.code", read_only=True, default=None
    )
    inventory_account_name = serializers.CharField(
        source="inventory_account.name", read_only=True, default=None
    )
    sales_account_code = serializers.CharField(
        source="sales_account.code", read_only=True, default=None
    )
    sales_account_name = serializers.CharField(
        source="sales_account.name", read_only=True, default=None
    )
    cogs_account_code = serializers.CharField(
        source="cogs_account.code", read_only=True, default=None
    )
    cogs_account_name = serializers.CharField(
        source="cogs_account.name", read_only=True, default=None
    )
    wages_account_code = serializers.CharField(
        source="wages_account.code", read_only=True, default=None
    )
    wages_account_name = serializers.CharField(
        source="wages_account.name", read_only=True, default=None
    )

    class Meta:
        model = Product
        fields = [
            "id", "sku", "name", "description", "category", "category_name",
            "brand", "unit_of_measure", "product_type", "alcohol_percentage", "volume_ml",
            "cost_price", "owner_cost_price", "selling_price", "wholesale_price",
            "reorder_level", "max_stock_level", "reorder_quantity", "quantity_in_pack",
            "barcode", "barcode_symbology",
            "is_active", "is_taxable", "tax_class", "tax_type", "costing_method",
            "inventory_account", "inventory_account_code", "inventory_account_name",
            "sales_account", "sales_account_code", "sales_account_name",
            "cogs_account", "cogs_account_code", "cogs_account_name",
            "wages_account", "wages_account_code", "wages_account_name",
            "image", "images",
            "total_stock", "quantity_incoming", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "total_stock", "quantity_incoming", "created_at", "updated_at", "image"]

    def get_quantity_incoming(self, obj):
        # Fast path: ProductViewSet.get_queryset annotates _quantity_incoming so
        # list views cost zero extra queries. The fallback below keeps other
        # callers (e.g. nested serialization without the annotation) correct.
        annotated = getattr(obj, "_quantity_incoming", None)
        if annotated is not None:
            return float(annotated) if annotated > 0 else 0
        try:
            from apps.purchases.models import PurchaseOrderItem
            from django.db.models import F, Sum
            result = PurchaseOrderItem.objects.filter(
                product=obj,
                organisation=obj.organisation,
                purchase_order__status__in=["draft", "sent", "partially_received"],
            ).aggregate(total=Sum(F("quantity_ordered") - F("quantity_received")))
            incoming = result["total"] or 0
            return float(incoming) if incoming > 0 else 0
        except Exception:
            return 0

    def validate_tax_class(self, value):
        if value is None:
            return value
        request = self.context.get('request')
        if request and hasattr(request, 'organisation') and request.organisation:
            if value.organisation_id != request.organisation.id:
                raise serializers.ValidationError("Tax class does not belong to this organisation.")
        return value

    def validate_inventory_account(self, value):
        from apps.core.validators import validate_same_org_account
        return validate_same_org_account(value, self.context.get('request'))

    def validate_sales_account(self, value):
        from apps.core.validators import validate_same_org_account
        return validate_same_org_account(value, self.context.get('request'))

    def validate_cogs_account(self, value):
        from apps.core.validators import validate_same_org_account
        return validate_same_org_account(value, self.context.get('request'))

    def validate_wages_account(self, value):
        from apps.core.validators import validate_same_org_account
        return validate_same_org_account(value, self.context.get('request'))

    def get_total_stock(self, obj):
        # Fast path: annotated by ProductViewSet.get_queryset (see there).
        annotated = getattr(obj, "_total_stock", None)
        if annotated is not None:
            return annotated
        return sum(
            s.quantity_on_hand for s in obj.stock_items.filter(organisation=obj.organisation)
        )

    def create(self, validated_data):
        # System-generated by default (the reviewer's "best practice" note) —
        # manual entry still works for a product that already has a printed
        # barcode; this only fills the gap when the field was left blank.
        if not validated_data.get("barcode"):
            organisation = validated_data.get("organisation")
            symbology = validated_data.get("barcode_symbology") or Product.BarcodeSymbology.CODE128
            validated_data["barcode"] = Product.generate_barcode(organisation, symbology)
        return super().create(validated_data)

    def _can_view_cost(self, instance) -> bool:
        """
        Same visibility rule as before, but resolved ONCE per request instead of
        once per product (the old per-row Membership.get + lazy organisation
        fetch cost 2 queries per product — the other half of the list N+1).
        Uses organisation_id (already on the row) to avoid fetching the org.
        """
        cached = getattr(self, "_cost_visibility_cache", None)
        if cached is not None and cached[0] == instance.organisation_id:
            return cached[1]

        request = self.context.get("request")
        allowed = False
        if request and request.user and request.user.is_authenticated:
            try:
                from apps.tenancy.models import Membership
                membership = Membership.objects.get(
                    organisation_id=instance.organisation_id,
                    user=request.user,
                    is_active=True,
                )
                allowed = membership.role in _OWNER_ROLES or request.user.is_superuser
            except Membership.DoesNotExist:
                allowed = False
        self._cost_visibility_cache = (instance.organisation_id, allowed)
        return allowed

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._can_view_cost(instance):
            data.pop("owner_cost_price", None)
            data.pop("cost_price", None)
        return data


class ProductListSerializer(ProductSerializer):
    """
    Slim serializer for the products LIST endpoint only.

    Excludes heavyweight / list-unused fields (description is the payload
    whale; timestamps and pack/reorder details are only needed by the edit
    form, which hydrates from the detail endpoint). The detail endpoint keeps
    the full ProductSerializer, so single-product reads are unchanged.
    Cut ~50% off list payloads that were breaching the client timeout for
    large catalogues.
    """

    class Meta(ProductSerializer.Meta):
        fields = [
            "id", "sku", "name", "category", "category_name",
            "brand", "unit_of_measure", "product_type",
            "alcohol_percentage", "volume_ml",
            "cost_price", "owner_cost_price", "selling_price",
            "reorder_level", "is_active", "is_taxable", "tax_class",
            "total_stock",
        ]
        read_only_fields = ["id", "total_stock"]


class BatchSerializer(serializers.ModelSerializer):
    is_expired = serializers.BooleanField(read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    days_to_expiry = serializers.SerializerMethodField()

    def get_days_to_expiry(self, obj):
        if not obj.expiry_date:
            return None
        from django.utils import timezone
        delta = obj.expiry_date - timezone.now().date()
        return delta.days

    class Meta:
        model = Batch
        fields = [
            "id", "product", "product_name", "product_sku",
            "warehouse", "warehouse_name", "batch_number",
            "quantity", "unit_cost", "manufacture_date",
            "expiry_date", "days_to_expiry", "is_expired",
            "min_quantity", "max_quantity", "qty_per_pack",
            "is_active",
        ]
        read_only_fields = ["id"]


class StockItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    quantity_available = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    is_low_stock = serializers.BooleanField(read_only=True)
    stock_level = serializers.SerializerMethodField()
    quantity_incoming = serializers.SerializerMethodField()
    incoming_eta = serializers.SerializerMethodField()

    class Meta:
        model = StockItem
        fields = [
            "id", "product", "product_name", "product_sku",
            "warehouse", "warehouse_name",
            "quantity_on_hand", "quantity_available",
            "quantity_incoming", "incoming_eta",
            "is_low_stock", "stock_level",
        ]
        read_only_fields = ["id", "quantity_on_hand"]

    def get_stock_level(self, obj):
        reorder = obj.product.reorder_level or 0
        qty = obj.quantity_on_hand
        if qty <= reorder:
            return 'low'
        elif qty <= reorder * 1.5:
            return 'medium'
        return 'ok'

    def get_quantity_incoming(self, obj):
        # Fast path: annotated by StockItemViewSet.get_queryset (N+1 fix).
        annotated = getattr(obj, "_quantity_incoming", None)
        if annotated is not None:
            return float(annotated) if annotated > 0 else 0
        from apps.purchases.models import PurchaseOrderItem
        from django.db.models import F, Sum
        result = PurchaseOrderItem.objects.filter(
            product=obj.product,
            organisation=obj.organisation,
            purchase_order__status__in=["draft", "sent", "partially_received"],
        ).aggregate(total=Sum(F("quantity_ordered") - F("quantity_received")))
        incoming = result["total"] or 0
        return float(incoming) if incoming > 0 else 0

    def get_incoming_eta(self, obj):
        # Fast path: annotated by StockItemViewSet.get_queryset (N+1 fix).
        # hasattr (not None-check) because a legitimate annotated value can be
        # None when no dated PO exists.
        if hasattr(obj, "_incoming_eta"):
            eta = obj._incoming_eta
            return eta.isoformat() if eta else None
        from apps.purchases.models import PurchaseOrder
        from django.db.models import Min
        result = PurchaseOrder.objects.filter(
            items__product=obj.product,
            organisation=obj.organisation,
            status__in=["draft", "sent", "partially_received"],
            expected_date__isnull=False,
        ).aggregate(earliest=Min("expected_date"))
        eta = result["earliest"]
        return eta.isoformat() if eta else None


class StockMovementSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id", "product", "product_sku", "warehouse", "warehouse_name",
            "batch", "movement_type", "quantity", "unit_cost",
            "reference", "notes", "balance_after", "created_at",
        ]
        read_only_fields = ["id", "balance_after", "created_at"]


class StockAdjustmentSerializer(serializers.Serializer):
    """Input for manual stock adjustments."""
    product_id = serializers.UUIDField()
    warehouse_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    reason = serializers.CharField(max_length=500)


class StockTransferSerializer(serializers.Serializer):
    """Input for inter-warehouse stock transfers."""
    product_id = serializers.UUIDField()
    from_warehouse_id = serializers.UUIDField()
    to_warehouse_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
