from decimal import Decimal

from rest_framework import serializers
from .models import CreditTransaction


class CreditTransactionSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = CreditTransaction
        fields = [
            "id", "customer", "customer_name", "invoice",
            "transaction_type", "amount", "balance_after",
            "due_date", "description", "created_at",
        ]
        read_only_fields = ["id", "balance_after", "created_at"]


class RecordCreditPaymentSerializer(serializers.Serializer):
    customer_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=15, decimal_places=4, min_value=Decimal("0.01"))
    description = serializers.CharField(required=False, default="")
    due_date = serializers.DateField(required=False, allow_null=True)
