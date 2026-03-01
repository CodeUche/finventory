import uuid

from rest_framework import serializers

from .models import Supplier


class SupplierSerializer(serializers.ModelSerializer):
    code = serializers.CharField(max_length=50, required=False, default="")

    class Meta:
        model = Supplier
        fields = [
            "id", "code", "name", "contact_person", "email", "phone",
            "address", "tax_id", "payment_terms_days", "notes",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data):
        if not validated_data.get("code"):
            name = validated_data.get("name", "")
            prefix = (name[:3].upper().replace(" ", "") or "SUP").ljust(3, "X")[:3]
            suffix = uuid.uuid4().hex[:6].upper()
            validated_data["code"] = f"{prefix}-{suffix}"
        return super().create(validated_data)
