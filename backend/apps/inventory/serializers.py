"""Inventory serializers."""

from decimal import Decimal

from rest_framework import serializers

from .models import Batch, Category, Product, StockItem, StockMovement, Warehouse

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


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    total_stock = serializers.SerializerMethodField()
    quantity_incoming = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "sku", "name", "description", "category", "category_name",
            "brand", "unit_of_measure", "product_type", "alcohol_percentage", "volume_ml",
            "cost_price", "owner_cost_price", "selling_price", "wholesale_price",
            "reorder_level", "max_stock_level", "reorder_quantity", "quantity_in_pack", "barcode",
            "is_active", "is_taxable", "tax_class",
            "total_stock", "quantity_incoming", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "total_stock", "quantity_incoming", "created_at", "updated_at"]

    def get_quantity_incoming(self, obj):
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

    def get_total_stock(self, obj):
        return sum(
            s.quantity_on_hand for s in obj.stock_items.filter(organisation=obj.organisation)
        )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request and request.user and request.user.is_authenticated:
            try:
                from apps.tenancy.models import Membership
                membership = Membership.objects.get(
                    organisation=instance.organisation,
                    user=request.user,
                    is_active=True,
                )
                if membership.role not in _OWNER_ROLES and not request.user.is_superuser:
                    data.pop("owner_cost_price", None)
                    data.pop("cost_price", None)
            except Membership.DoesNotExist:
                data.pop("owner_cost_price", None)
                data.pop("cost_price", None)
        else:
            data.pop("owner_cost_price", None)
            data.pop("cost_price", None)
        return data


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

    class Meta:
        model = StockItem
        fields = [
            "id", "product", "product_name", "product_sku",
            "warehouse", "warehouse_name",
            "quantity_on_hand", "quantity_reserved",
            "quantity_available", "is_low_stock", "stock_level",
        ]
        read_only_fields = ["id", "quantity_on_hand", "quantity_reserved"]

    def get_stock_level(self, obj):
        reorder = obj.product.reorder_level or 0
        qty = obj.quantity_on_hand
        if qty <= reorder:
            return 'low'
        elif qty <= reorder * 1.5:
            return 'medium'
        return 'ok'


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
