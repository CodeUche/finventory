"""Sales serializers."""

from decimal import Decimal

from rest_framework import serializers

from .models import Invoice, InvoiceFolder, Location, SaleItem, SalePayment, RecurringInvoice, SaleReturn, SaleReturnItem


class LocationSerializer(serializers.ModelSerializer):
    manager_name = serializers.SerializerMethodField()

    class Meta:
        model = Location
        fields = ["id", "name", "address", "phone", "manager", "manager_name", "is_active", "created_at"]
        read_only_fields = ["id", "created_at"]

    def get_manager_name(self, obj):
        if obj.manager:
            return f"{obj.manager.first_name} {obj.manager.last_name}".strip() or obj.manager.email
        return None


class InvoiceFolderSerializer(serializers.ModelSerializer):
    children_count = serializers.SerializerMethodField()
    invoices_count = serializers.SerializerMethodField()
    ancestors = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceFolder
        fields = ['id', 'name', 'description', 'folder_date', 'parent',
                  'children_count', 'invoices_count', 'ancestors', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_children_count(self, obj):
        annotated = getattr(obj, '_children_count', None)
        if annotated is not None:
            return annotated
        return obj.children.filter(is_deleted=False).count() if hasattr(obj, 'children') else 0

    def get_invoices_count(self, obj):
        annotated = getattr(obj, '_invoices_count', None)
        if annotated is not None:
            return annotated
        return obj.invoices.filter(is_deleted=False).count() if hasattr(obj, 'invoices') else 0

    def get_ancestors(self, obj):
        return obj.get_ancestors()


class SaleItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = SaleItem
        fields = [
            "id", "product", "product_name", "product_sku",
            "batch", "quantity", "quantity_returned", "unit_price",
            "discount_percent", "discount_amount",
            "tax_rate", "tax_amount", "line_total", "cost_of_goods", "modifiers",
        ]
        read_only_fields = ["id", "quantity_returned", "discount_amount", "tax_amount", "line_total", "cost_of_goods"]


class SalePaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalePayment
        fields = ["id", "amount", "method", "reference", "received_at", "notes"]
        read_only_fields = ["id", "received_at"]


class InvoiceSerializer(serializers.ModelSerializer):
    items = SaleItemSerializer(many=True, read_only=True)
    payments = SalePaymentSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True, allow_null=True)
    folder_name = serializers.CharField(source="folder.name", read_only=True, allow_null=True)
    location_name = serializers.CharField(source="location.name", read_only=True, allow_null=True)

    class Meta:
        model = Invoice
        fields = [
            "id", "invoice_number", "folder", "folder_name", "customer", "customer_name",
            "status", "payment_method", "issue_date", "due_date", "warehouse",
            "location", "location_name",
            "subtotal", "discount_amount", "tax_amount", "shipping_amount", "total_amount",
            "credit_applied", "amount_paid", "amount_due", "notes", "sold_by",
            "is_deferred", "fulfilled_at",
            "items", "payments", "created_at",
            # ── FIRS e-invoicing fields ───────────────────────────────────────────
            # All fields are read-only from the API consumer's perspective;
            # they are written only by EInvoicingService / webhook callbacks.
            "firs_status", "firs_irn", "firs_invoice_number", "firs_csid", "firs_qr_code",
        ]
        read_only_fields = [
            "id", "invoice_number", "subtotal", "discount_amount",
            "tax_amount", "shipping_amount", "total_amount", "credit_applied", "amount_paid", "amount_due", "created_at",
            "is_deferred", "fulfilled_at",
            "firs_status", "firs_irn", "firs_invoice_number", "firs_csid", "firs_qr_code",
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
        # Per-line VAT override: pick a configured TaxClass, or set an explicit
        # rate directly. Omit both to keep using the product's own default tax
        # class — see SaleService._process_line_item for the resolution order.
        tax_class_id = serializers.UUIDField(required=False, allow_null=True)
        tax_rate = serializers.DecimalField(
            max_digits=5, decimal_places=2, required=False, allow_null=True,
            min_value=Decimal("0"), max_value=Decimal("100"),
        )

    customer_id = serializers.UUIDField(required=False, allow_null=True)
    warehouse_id = serializers.UUIDField()
    location_id = serializers.UUIDField(required=False, allow_null=True)
    payment_method = serializers.ChoiceField(choices=Invoice.PaymentMethod.choices)
    # Cap line items to 200 — prevents absurdly large payloads
    items = ItemInputSerializer(many=True, min_length=1, max_length=200)
    # max_length guards against oversized text being stored in the DB
    notes = serializers.CharField(required=False, default="", allow_blank=True, max_length=2000)
    sold_by = serializers.CharField(required=False, allow_blank=True, max_length=200)
    issue_date = serializers.DateField(required=False)
    due_date = serializers.DateField(required=False, allow_null=True)
    is_proforma = serializers.BooleanField(required=False, default=False)
    defer_fulfillment = serializers.BooleanField(required=False, default=False, write_only=True)
    shipping_amount = serializers.DecimalField(
        max_digits=15, decimal_places=4, required=False, default=Decimal("0"), min_value=Decimal("0")
    )

    def validate(self, attrs):
        issue_date = attrs.get('issue_date')
        due_date = attrs.get('due_date')
        if issue_date and due_date and due_date < issue_date:
            raise serializers.ValidationError(
                {"due_date": "Due date cannot be before the issue date."}
            )
        return attrs
    amount_paid = serializers.DecimalField(max_digits=15, decimal_places=4, required=False, default=Decimal("0"), min_value=Decimal("0"))
    amount_tendered = serializers.DecimalField(max_digits=15, decimal_places=4, required=False, allow_null=True)
    credit_applied = serializers.DecimalField(max_digits=15, decimal_places=4, required=False, default=Decimal("0"), min_value=Decimal("0"))
    wht_rate_id = serializers.UUIDField(required=False, allow_null=True)


class RecordPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=15, decimal_places=4, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=SalePayment.Method.choices)
    reference = serializers.CharField(required=False, default="", max_length=200)
    notes = serializers.CharField(required=False, default="", max_length=1000)


class SaleReturnItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = SaleReturnItem
        fields = ["id", "original_item", "product", "product_name", "product_sku",
                  "quantity_returned", "unit_price", "refund_amount"]
        read_only_fields = ["id"]


class SaleReturnSerializer(serializers.ModelSerializer):
    items = SaleReturnItemSerializer(many=True, read_only=True)
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)

    class Meta:
        model = SaleReturn
        fields = [
            "id", "return_number", "invoice", "invoice_number", "reason",
            "notes", "return_date", "total_refund", "restocked",
            "processed_by", "items", "created_at",
        ]
        read_only_fields = ["id", "return_number", "total_refund", "created_at"]


class ProcessReturnSerializer(serializers.Serializer):
    """Input for processing a sales return."""

    class ReturnItemSerializer(serializers.Serializer):
        sale_item_id = serializers.UUIDField()
        quantity_returned = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))

    invoice_id = serializers.UUIDField(required=False, allow_null=True)  # ignored — taken from URL
    items = ReturnItemSerializer(many=True, min_length=1, max_length=200)
    reason = serializers.ChoiceField(choices=SaleReturn.Reason.choices, default=SaleReturn.Reason.OTHER)
    notes = serializers.CharField(required=False, default="", allow_blank=True, max_length=2000)
    restocked = serializers.BooleanField(default=True)
    return_date = serializers.DateField(required=False)


class RecurringInvoiceSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True, allow_null=True)
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True)

    class Meta:
        model = RecurringInvoice
        fields = [
            'id', 'template_name', 'customer', 'customer_name', 'custom_customer_name',
            'warehouse', 'warehouse_name',
            'frequency', 'interval', 'next_run_date', 'end_date', 'max_occurrences',
            'occurrences_count', 'is_active', 'items', 'notes', 'payment_method', 'created_at',
        ]
        read_only_fields = ['id', 'occurrences_count', 'created_at']
