from decimal import Decimal

from rest_framework import serializers

from apps.core.validators import validate_file_upload

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
        extra_kwargs = {
            'attachment': {'validators': [validate_file_upload], 'required': False},
            'notes': {'max_length': 2000, 'required': False, 'allow_blank': True},
            'reference': {'max_length': 100, 'required': False, 'allow_blank': True},
        }


class BillItemInputSerializer(serializers.Serializer):
    """
    Schema-validated bill line item.

    Replaces the previous DictField(child=any) which accepted arbitrary
    unvalidated keys and values. Each line is now strictly typed with
    explicit bounds on every numeric and text field.
    """

    description = serializers.CharField(max_length=500)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.001"))
    unit_cost = serializers.DecimalField(max_digits=15, decimal_places=4, min_value=Decimal("0.01"))
    # Optional FK references — resolved in the view/service
    expense_category_id = serializers.UUIDField(required=False, allow_null=True)
    account_id = serializers.UUIDField(required=False, allow_null=True)


class CreateBillSerializer(serializers.Serializer):
    # supplier is optional when vendor_name (custom/walk-in) is supplied instead
    supplier = serializers.UUIDField(required=False, allow_null=True)
    vendor_name = serializers.CharField(required=False, allow_blank=True, default='', max_length=255)
    folder = serializers.UUIDField(required=False, allow_null=True)
    issue_date = serializers.DateField()
    due_date = serializers.DateField()
    # max_length prevents oversized free-text fields from being stored
    reference = serializers.CharField(required=False, allow_blank=True, default='', max_length=100)
    tax_amount = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, default=Decimal("0"), min_value=Decimal("0"))
    notes = serializers.CharField(required=False, allow_blank=True, default='', max_length=2000)
    status = serializers.ChoiceField(
        choices=['draft', 'received', 'approved'],
        required=False,
        default='draft',
    )
    # Use the typed nested serializer — replaces unsafe DictField
    items = BillItemInputSerializer(many=True, min_length=1, max_length=200)

    def validate(self, attrs):
        if not attrs.get('supplier') and not attrs.get('vendor_name', '').strip():
            raise serializers.ValidationError(
                {'supplier': 'Either a supplier or a custom vendor name is required.'}
            )
        return attrs


class RecordBillPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=15, decimal_places=2, min_value=Decimal("0.01"))
    payment_date = serializers.DateField()
    method = serializers.ChoiceField(choices=['cash', 'bank_transfer', 'cheque', 'pos'], default='cash')
    reference = serializers.CharField(required=False, allow_blank=True, default='', max_length=200)
    notes = serializers.CharField(required=False, allow_blank=True, default='', max_length=1000)
    wht_rate_id = serializers.UUIDField(required=False, allow_null=True)
