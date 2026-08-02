from rest_framework import serializers

from .models import RestaurantTable, POSOrder, POSOrderItem, KitchenOrderTicket


class RestaurantTableSerializer(serializers.ModelSerializer):
    class Meta:
        model = RestaurantTable
        fields = ["id", "name", "capacity", "section", "status", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]


class POSOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    line_total = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)

    class Meta:
        model = POSOrderItem
        fields = ["id", "product", "product_name", "quantity", "unit_price",
                  "notes", "modifiers", "kitchen_status", "line_total"]
        read_only_fields = ["id", "product_name", "line_total"]


class KitchenOrderTicketSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    table_name = serializers.CharField(source="order.table.name", read_only=True, default=None)
    order_type = serializers.CharField(source="order.order_type", read_only=True)
    items = POSOrderItemSerializer(source="order.items", many=True, read_only=True)

    class Meta:
        model = KitchenOrderTicket
        fields = ["id", "kot_number", "order", "order_number", "table_name", "order_type",
                  "section", "status", "printed_at", "items", "created_at"]
        read_only_fields = fields


class POSOrderSerializer(serializers.ModelSerializer):
    items = POSOrderItemSerializer(many=True, read_only=True)
    waiter_name = serializers.CharField(source="waiter.get_full_name", read_only=True, default=None)
    table_name = serializers.CharField(source="table.name", read_only=True, default=None)
    customer_name = serializers.CharField(source="customer.name", read_only=True, default=None)
    items_subtotal = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True, default=None)

    class Meta:
        model = POSOrder
        fields = ["id", "order_number", "order_type", "table", "table_name", "room_number",
                  "waiter", "waiter_name", "customer", "customer_name", "status",
                  "service_charge", "tip_amount", "notes", "warehouse", "invoice",
                  "invoice_number", "items", "items_subtotal", "created_at", "updated_at"]
        read_only_fields = ["id", "order_number", "table_name", "waiter_name", "customer_name",
                            "invoice", "invoice_number", "items", "items_subtotal",
                            "created_at", "updated_at"]
