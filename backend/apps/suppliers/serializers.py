import uuid

from rest_framework import serializers

from apps.core.validators import validate_same_org_account

from .models import Supplier


class SupplierSerializer(serializers.ModelSerializer):
    code = serializers.CharField(max_length=50, required=False, default="")
    payable_account_code = serializers.CharField(
        source="payable_account.code", read_only=True, default=None
    )
    payable_account_name = serializers.CharField(
        source="payable_account.name", read_only=True, default=None
    )

    class Meta:
        model = Supplier
        fields = [
            "id", "code", "name", "contact_person", "email", "phone",
            "address", "tax_id", "payment_terms_days", "notes",
            "opening_balance", "opening_balance_date",
            "payable_account", "payable_account_code", "payable_account_name",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "opening_balance", "opening_balance_date", "created_at", "updated_at"]

    def validate_payable_account(self, value):
        return validate_same_org_account(value, self.context.get("request"))

    def create(self, validated_data):
        if not validated_data.get("code"):
            name = validated_data.get("name", "")
            prefix = (name[:3].upper().replace(" ", "") or "SUP").ljust(3, "X")[:3]
            suffix = uuid.uuid4().hex[:6].upper()
            validated_data["code"] = f"{prefix}-{suffix}"
        return super().create(validated_data)
