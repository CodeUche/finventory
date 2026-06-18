from decimal import Decimal

from rest_framework import serializers
from .models import CreditTransaction


class CreditTransactionSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = CreditTransaction
        fields = [
            "id", "customer", "customer_name", "invoice",
            "transaction_type", "amount", "balance_before", "balance_after",
            "due_date", "description", "created_at",
            "payment_number", "payment_mode", "bank_name", "bank_code",
            "account_number", "account_name",
            "debit_account", "credit_account", "location",
        ]
        read_only_fields = ["id", "balance_before", "balance_after", "payment_number", "created_at"]


class RecordCreditPaymentSerializer(serializers.Serializer):
    customer_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=15, decimal_places=4, min_value=Decimal("0.01"))
    description = serializers.CharField(required=False, default="")
    due_date = serializers.DateField(required=False, allow_null=True)

    # Optional: when provided, also creates a matching SalePayment on the invoice
    invoice = serializers.UUIDField(required=False, allow_null=True)

    # Optional manual override — if blank, the view auto-generates one
    payment_number = serializers.CharField(required=False, default="", allow_blank=True)

    # Payment receipt detail (only meaningful when invoice is provided)
    payment_mode = serializers.ChoiceField(
        choices=CreditTransaction.PaymentMode.choices, required=False, default="", allow_blank=True
    )
    bank_name = serializers.CharField(required=False, default="", allow_blank=True)
    bank_code = serializers.CharField(required=False, default="", allow_blank=True)
    account_number = serializers.CharField(required=False, default="", allow_blank=True)
    account_name = serializers.CharField(required=False, default="", allow_blank=True)
    reference = serializers.CharField(required=False, default="", allow_blank=True)

    # Optional manual GL posting
    debit_account_id = serializers.UUIDField(required=False, allow_null=True)
    credit_account_id = serializers.UUIDField(required=False, allow_null=True)
    location_id = serializers.UUIDField(required=False, allow_null=True)
