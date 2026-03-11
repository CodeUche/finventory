from rest_framework import serializers
from .models import Bill, BillFolder, BillItem, BillPayment


class BillFolderSerializer(serializers.ModelSerializer):
    children_count = serializers.SerializerMethodField()
    bills_count = serializers.SerializerMethodField()
    ancestors = serializers.SerializerMethodField()

    class Meta:
        model = BillFolder
        fields = ['id', 'name', 'description', 'folder_date', 'parent',
                  'children_count', 'bills_count', 'ancestors', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_children_count(self, obj):
        return obj.children.filter(is_deleted=False).count() if hasattr(obj, 'children') else 0

    def get_bills_count(self, obj):
        return obj.bills.filter(is_deleted=False).count() if hasattr(obj, 'bills') else 0

    def get_ancestors(self, obj):
        return obj.get_ancestors()


class BillItemSerializer(serializers.ModelSerializer):
    expense_category_name = serializers.CharField(source='expense_category.name', read_only=True)
    expense_category_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    account_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = BillItem
        fields = ['id', 'description', 'quantity', 'unit_cost', 'line_total',
                  'expense_category', 'expense_category_name', 'expense_category_id',
                  'account', 'account_id']
        read_only_fields = ['id', 'line_total', 'expense_category']


class BillPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillPayment
        fields = ['id', 'amount', 'payment_date', 'method', 'reference', 'notes', 'recorded_by', 'created_at']
        read_only_fields = ['id', 'recorded_by', 'created_at']


class BillSerializer(serializers.ModelSerializer):
    items = BillItemSerializer(many=True, read_only=True)
    payments = BillPaymentSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    folder_name = serializers.CharField(source='folder.name', read_only=True, allow_null=True)

    class Meta:
        model = Bill
        fields = [
            'id', 'bill_number', 'folder', 'folder_name', 'supplier', 'supplier_name', 'status',
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
    status = serializers.ChoiceField(
        choices=['draft', 'received', 'approved'],
        required=False,
        default='draft',
    )
    items = serializers.ListField(child=serializers.DictField(), min_length=1)


class RecordBillPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    payment_date = serializers.DateField()
    method = serializers.ChoiceField(choices=['cash', 'bank_transfer', 'cheque', 'pos'], default='cash')
    reference = serializers.CharField(required=False, allow_blank=True, default='')
    notes = serializers.CharField(required=False, allow_blank=True, default='')
