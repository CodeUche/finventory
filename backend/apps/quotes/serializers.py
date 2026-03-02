from rest_framework import serializers
from .models import Quote, QuoteItem
from apps.inventory.models import Product


class QuoteItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all(), source='product', write_only=True)

    class Meta:
        model = QuoteItem
        fields = ['id', 'product', 'product_id', 'product_name', 'quantity', 'unit_price', 'discount_percent', 'tax_rate', 'line_total']
        read_only_fields = ['id', 'product', 'line_total']


class QuoteSerializer(serializers.ModelSerializer):
    items = QuoteItemSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source='customer.name', read_only=True, allow_null=True)
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True)

    class Meta:
        model = Quote
        fields = [
            'id', 'quote_number', 'customer', 'customer_name', 'warehouse', 'warehouse_name',
            'status', 'issue_date', 'valid_until', 'subtotal', 'discount_amount',
            'tax_amount', 'total_amount', 'notes', 'terms', 'converted_invoice',
            'created_at', 'items'
        ]
        read_only_fields = ['id', 'quote_number', 'subtotal', 'discount_amount', 'tax_amount', 'total_amount', 'converted_invoice', 'created_at']


class CreateQuoteSerializer(serializers.Serializer):
    customer = serializers.UUIDField(required=False, allow_null=True)
    warehouse = serializers.UUIDField()
    status = serializers.ChoiceField(choices=Quote.STATUS_CHOICES, required=False, default=Quote.DRAFT)
    issue_date = serializers.DateField()
    valid_until = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    terms = serializers.CharField(required=False, allow_blank=True, default='')
    items = serializers.ListField(child=serializers.DictField(), min_length=1)
