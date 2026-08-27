"""
Storefront serializers.

These are the only serializers in Audity that answer to the open internet, so
they are written as allowlists: every field is named deliberately. A
ModelSerializer with `exclude` would happily start publishing cost prices the
day someone adds a field, which is exactly the mistake that must be impossible
here.
"""

from decimal import Decimal

from rest_framework import serializers

from .models import Storefront, StorefrontOrder, StorefrontOrderItem


class PublicProductSerializer(serializers.Serializer):
    """What a customer may see. Cost, margin and supplier data are absent by
    construction, not by exclusion."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True, default="")
    unit_of_measure = serializers.CharField(read_only=True)
    selling_price = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    image = serializers.SerializerMethodField()
    in_stock = serializers.SerializerMethodField()

    def get_image(self, obj) -> str:
        try:
            return obj.image.url if obj.image else ""
        except Exception:
            return ""

    def get_in_stock(self, obj) -> bool:
        """A boolean, never the actual quantity — stock levels are commercially
        sensitive and a competitor should not be able to read them off a page."""
        return bool(getattr(obj, "_available", 0) > 0)


class PublicStorefrontSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="organisation.name", read_only=True)
    logo = serializers.SerializerMethodField()
    currency = serializers.CharField(source="organisation.currency", read_only=True)

    class Meta:
        model = Storefront
        fields = [
            "slug", "name", "logo", "currency", "headline", "about", "whatsapp",
            "delivery_note", "accent_colour", "accepts_orders", "minimum_order",
            "free_delivery_threshold", "fixed_delivery_charge",
        ]
        read_only_fields = fields

    def get_logo(self, obj) -> str:
        try:
            return obj.organisation.logo.url if obj.organisation.logo else ""
        except Exception:
            return ""


class PublicOrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = StorefrontOrderItem
        fields = ["product_name", "quantity", "unit_price", "line_total"]
        read_only_fields = fields


class PublicOrderSerializer(serializers.ModelSerializer):
    items = PublicOrderItemSerializer(many=True, read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = StorefrontOrder
        fields = [
            "reference", "status", "status_label", "fulfilment", "customer_name",
            "delivery_address", "note", "subtotal", "total", "items", "created_at",
        ]
        read_only_fields = fields


class PlaceOrderSerializer(serializers.Serializer):
    """Validates an order from an untrusted caller.

    Prices are NEVER taken from the request — only product ids and quantities
    are. Everything monetary is recomputed server-side from the catalogue.
    """

    customer_name = serializers.CharField(max_length=120)
    customer_phone = serializers.CharField(max_length=30)
    customer_email = serializers.EmailField(required=False, allow_blank=True)
    fulfilment = serializers.ChoiceField(
        choices=StorefrontOrder.Fulfilment.choices,
        default=StorefrontOrder.Fulfilment.PICKUP,
    )
    delivery_address = serializers.CharField(max_length=500, required=False, allow_blank=True)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True)
    table_code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    items = serializers.ListField(child=serializers.DictField(), min_length=1, max_length=100)

    def validate_items(self, value):
        cleaned = []
        for raw in value:
            product_id = raw.get("product") or raw.get("product_id")
            if not product_id:
                raise serializers.ValidationError("Every line needs a product.")
            try:
                quantity = Decimal(str(raw.get("quantity", 1)))
            except Exception:
                raise serializers.ValidationError("Quantity must be a number.")
            if quantity <= 0:
                raise serializers.ValidationError("Quantity must be more than zero.")
            if quantity > Decimal("10000"):
                raise serializers.ValidationError("That quantity is not possible.")
            cleaned.append({"product_id": str(product_id), "quantity": quantity})
        return cleaned

    def validate(self, attrs):
        if (attrs.get("fulfilment") == StorefrontOrder.Fulfilment.DELIVERY
                and not (attrs.get("delivery_address") or "").strip()):
            raise serializers.ValidationError(
                {"delivery_address": "Add the address we should deliver to."}
            )
        return attrs


# ── Merchant-side (authenticated) ────────────────────────────────────────────
class StorefrontSerializer(serializers.ModelSerializer):
    public_url = serializers.SerializerMethodField()

    class Meta:
        model = Storefront
        fields = [
            "id", "slug", "is_published", "headline", "about", "whatsapp",
            "delivery_note", "accent_colour", "accepts_orders", "minimum_order",
            "free_delivery_threshold", "fixed_delivery_charge",
            "hide_out_of_stock", "public_url", "created_at",
        ]
        read_only_fields = ["id", "public_url", "created_at"]

    def get_public_url(self, obj) -> str:
        return f"/s/{obj.slug}"

    def validate_slug(self, value):
        from .models import RESERVED_SLUGS
        value = (value or "").strip().lower()
        if value in RESERVED_SLUGS:
            raise serializers.ValidationError("That address is reserved. Pick another.")
        return value


class MerchantOrderSerializer(serializers.ModelSerializer):
    items = PublicOrderItemSerializer(many=True, read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    invoice_number = serializers.CharField(
        source="invoice.invoice_number", read_only=True, default="",
    )
    table_name = serializers.CharField(source="table.name", read_only=True, default="")

    class Meta:
        model = StorefrontOrder
        fields = [
            "id", "reference", "status", "status_label", "fulfilment",
            "customer_name", "customer_phone", "customer_email",
            "delivery_address", "note", "table_name", "subtotal", "total",
            "items", "invoice", "invoice_number", "created_at",
        ]
        read_only_fields = fields
