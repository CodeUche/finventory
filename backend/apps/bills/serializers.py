from rest_framework import serializers
from .models import Bill, BillItem, BillPayment


class BillItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillItem
        fields = ['id', 'description', 'quantity', 'unit_cost', 'line_total']
        read_only_fields = ['id', 'line_total']


class BillPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillPayment
        fields = ['id', 'amount', 'payment_date', 'method', 'reference', 'notes', 'recorded_by', 'created_at']
        read_only_fields = ['id', 'recorded_by', 'created_at']


class BillSerializer(serializers.ModelSerializer):
    items = BillItemSerializer(many=True, read_only=True)
    payments = BillPaymentSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)

    class Meta:
        model = Bill
        fields = [
            'id', 'bill_number', 'supplier', 'supplier_name', 'status',
            'issue_date', 'due_date', 'reference', 'subtotal', 'tax_amount',
            'total_amount', 'amount_paid', 'amount_due', 'notes', 'attachment',
            'created_at', 'items', 'payments'
        ]
        read_only_fields = ['id', 'bill_number', 'subtotal', 'total_amount', 'amount_paid', 'amount_due', 'created_at']


class CreateBillSerializer(serializers.Serializer):
    supplier = serializers.UUIDField()
    issue_date = serializers.DateField()
    due_date = serializers.DateField()
    reference = serializers.CharField(required=False, allow_blank=True, default='')
    tax_amount = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, default=0)
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    items = serializers.ListField(child=serializers.DictField(), min_length=1)


class RecordBillPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    payment_date = serializers.DateField()
    method = serializers.ChoiceField(choices=['cash', 'bank_transfer', 'cheque', 'pos'], default='cash')
    reference = serializers.CharField(required=False, allow_blank=True, default='')
    notes = serializers.CharField(required=False, allow_blank=True, default='')
