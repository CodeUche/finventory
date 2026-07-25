from decimal import Decimal

from rest_framework import serializers

from apps.core.validators import validate_file_upload

from .models import PurchaseOrder, PurchaseOrderItem


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    is_fully_received = serializers.BooleanField(read_only=True)

    class Meta:
        model = PurchaseOrderItem
        fields = [
            "id", "product", "product_name",
            "quantity_ordered", "quantity_received",
            "unit_cost", "line_total",
            "batch_number", "expiry_date", "is_fully_received",
        ]
        read_only_fields = ["id", "quantity_received", "line_total"]

    def validate(self, attrs):
        attrs["line_total"] = attrs["quantity_ordered"] * attrs["unit_cost"]
        return attrs


class PurchaseOrderSerializer(serializers.ModelSerializer):
    items = PurchaseOrderItemSerializer(many=True, required=False)
    supplier_name = serializers.SerializerMethodField()

    def get_supplier_name(self, obj):
        return obj.supplier.name if obj.supplier_id else "Walk-in / No Supplier"
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id", "po_number", "supplier", "supplier_name",
            "warehouse", "warehouse_name", "status", "order_date", "expected_date",
            "received_date", "subtotal", "tax_amount", "total_amount",
            "delivery_type", "delivery_notes", "notes", "receipt", "items", "created_at",
        ]
        read_only_fields = ["id", "po_number", "subtotal", "tax_amount", "total_amount", "created_at"]
        extra_kwargs = {
            "notes": {"max_length": 2000, "required": False, "allow_blank": True},
            "supplier": {"required": False, "allow_null": True},
            # Allow only PDF/image receipts; file size capped by validate_file_upload
            "receipt": {"validators": [validate_file_upload], "required": False},
        }

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        subtotal = sum(item["line_total"] for item in items_data) if items_data else Decimal("0")
        validated_data["subtotal"] = subtotal
        validated_data["tax_amount"] = validated_data.get("tax_amount", Decimal("0"))
        validated_data["total_amount"] = subtotal + validated_data["tax_amount"]
        po = PurchaseOrder.objects.create(**validated_data)
        for item_data in items_data:
            PurchaseOrderItem.objects.create(
                purchase_order=po,
                organisation=po.organisation,
                **item_data,
            )
        return po


class ReceiveItemSerializer(serializers.Serializer):
    item_id = serializers.UUIDField()
    quantity_received = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    # Batch numbers are short reference codes — cap to prevent oversized strings
    batch_number = serializers.CharField(required=False, default="", max_length=100)
    expiry_date = serializers.DateField(required=False, allow_null=True)


from .models import PurchaseReturn, PurchaseReturnItem  # noqa: E402


class PurchaseReturnItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = PurchaseReturnItem
        fields = ["id", "product", "product_name", "product_sku",
                  "quantity_returned", "unit_cost", "line_total"]
        read_only_fields = fields


class PurchaseReturnSerializer(serializers.ModelSerializer):
    items = PurchaseReturnItemSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)
    po_number = serializers.CharField(source="purchase_order.po_number", read_only=True)

    class Meta:
        model = PurchaseReturn
        fields = ["id", "return_number", "purchase_order", "po_number", "supplier",
                  "supplier_name", "warehouse", "return_date", "reason", "refund_method",
                  "subtotal", "tax_amount", "total_amount", "gl_post_status", "items", "created_at"]
        read_only_fields = fields
