"""Sales serializers."""

from decimal import Decimal

from rest_framework import serializers

from .models import Invoice, SaleItem, SalePayment, RecurringInvoice


class SaleItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = SaleItem
        fields = [
            "id", "product", "product_name", "product_sku",
            "batch", "quantity", "unit_price",
            "discount_percent", "discount_amount",
            "tax_rate", "tax_amount", "line_total", "cost_of_goods",
        ]
        read_only_fields = ["id", "discount_amount", "tax_amount", "line_total", "cost_of_goods"]


class SalePaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalePayment
        fields = ["id", "amount", "method", "reference", "received_at", "notes"]
        read_only_fields = ["id", "received_at"]


class InvoiceSerializer(serializers.ModelSerializer):
    items = SaleItemSerializer(many=True, read_only=True)
    payments = SalePaymentSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True, allow_null=True)

    class Meta:
        model = Invoice
        fields = [
            "id", "invoice_number", "customer", "customer_name",
            "status", "payment_method", "issue_date", "due_date", "warehouse",
            "subtotal", "discount_amount", "tax_amount", "total_amount",
            "amount_paid", "amount_due", "notes",
            "items", "payments", "created_at",
        ]
        read_only_fields = [
            "id", "invoice_number", "subtotal", "discount_amount",
            "tax_amount", "total_amount", "amount_paid", "amount_due", "created_at",
        ]


class CreateSaleSerializer(serializers.Serializer):
    """Input serializer for creating a new sale."""

    class ItemInputSerializer(serializers.Serializer):
        product_id = serializers.UUIDField()
        quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
        unit_price = serializers.DecimalField(max_digits=15, decimal_places=4, required=False)
        discount_percent = serializers.DecimalField(
            max_digits=5, decimal_places=2, default=0, min_value=Decimal("0"), max_value=Decimal("100")
        )
        batch_id = serializers.UUIDField(required=False, allow_null=True)

    customer_id = serializers.UUIDField(required=False, allow_null=True)
    warehouse_id = serializers.UUIDField()
    payment_method = serializers.ChoiceField(choices=Invoice.PaymentMethod.choices)
    items = ItemInputSerializer(many=True, min_length=1)
    notes = serializers.CharField(required=False, default="", allow_blank=True)
    issue_date = serializers.DateField(required=False)
    due_date = serializers.DateField(required=False, allow_null=True)


class RecordPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=15, decimal_places=4, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=SalePayment.Method.choices)
    reference = serializers.CharField(required=False, default="")
    notes = serializers.CharField(required=False, default="")


class RecurringInvoiceSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True, allow_null=True)
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True)

    class Meta:
        model = RecurringInvoice
        fields = [
            'id', 'template_name', 'customer', 'customer_name', 'warehouse', 'warehouse_name',
            'frequency', 'interval', 'next_run_date', 'end_date', 'max_occurrences',
            'occurrences_count', 'is_active', 'items', 'notes', 'payment_method', 'created_at',
        ]
        read_only_fields = ['id', 'occurrences_count', 'created_at']
