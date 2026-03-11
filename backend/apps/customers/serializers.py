import uuid

from rest_framework import serializers

from .models import Customer


class CustomerSerializer(serializers.ModelSerializer):
    available_credit = serializers.DecimalField(max_digits=15, decimal_places=4, read_only=True)
    is_credit_blocked = serializers.BooleanField(read_only=True)
    code = serializers.CharField(max_length=50, required=False, default="")
    credit_score = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            "id", "code", "name", "customer_type", "email", "phone",
            "address", "contact_person", "credit_limit",
            "payment_terms_days", "outstanding_balance",
            "available_credit", "is_credit_blocked", "credit_score",
            "notes", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "outstanding_balance", "created_at", "updated_at"]

    def get_credit_score(self, obj) -> int:
        """Compute a 1–100 credit score based on invoice payment history."""
        try:
            from apps.sales.models import Invoice
            invoices = Invoice.objects.filter(
                organisation=obj.organisation,
                customer=obj.id,
                status__in=["paid", "partially_paid", "overdue", "credit"],
            )
            if not invoices.exists():
                return 50  # No history — neutral

            score = 70  # Baseline for any customer with history
            paid_count = invoices.filter(status="paid").count()
            overdue_count = invoices.filter(status="overdue").count()
            partial_count = invoices.filter(status="partially_paid").count()

            score += min(paid_count * 3, 25)       # Reward consistent payment (+up to 25)
            score -= min(overdue_count * 12, 50)   # Penalise overdue (-up to 50)
            score -= min(partial_count * 3, 15)    # Minor partial-pay penalty (-up to 15)
            if obj.is_credit_blocked:
                score -= 20                         # Hard penalty for blocked account

            return max(1, min(100, score))
        except Exception:
            return 50

    def create(self, validated_data):
        if not validated_data.get("code"):
            name = validated_data.get("name", "")
            prefix = (name[:3].upper().replace(" ", "") or "CUS").ljust(3, "X")[:3]
            suffix = uuid.uuid4().hex[:6].upper()
            validated_data["code"] = f"{prefix}-{suffix}"
        return super().create(validated_data)
