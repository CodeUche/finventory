import uuid

from rest_framework import serializers

from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    available_credit = serializers.DecimalField(max_digits=15, decimal_places=4, read_only=True)
    is_credit_blocked = serializers.BooleanField(read_only=True)
    code = serializers.CharField(max_length=50, required=False, default="")

    class Meta:
        model = Customer
        fields = [
            "id", "code", "name", "customer_type", "email", "phone",
            "address", "contact_person", "credit_limit",
            "payment_terms_days", "outstanding_balance",
            "available_credit", "is_credit_blocked",
            "notes", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "outstanding_balance", "created_at", "updated_at"]

    def create(self, validated_data):
        if not validated_data.get("code"):
            name = validated_data.get("name", "")
            prefix = (name[:3].upper().replace(" ", "") or "CUS").ljust(3, "X")[:3]
            suffix = uuid.uuid4().hex[:6].upper()
            validated_data["code"] = f"{prefix}-{suffix}"
        return super().create(validated_data)
