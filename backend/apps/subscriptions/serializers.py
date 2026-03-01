from rest_framework import serializers

from .models import PaymentHistory, Plan, Subscription


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            "id", "name", "slug", "description", "price", "interval",
            "trial_days", "features", "is_public", "display_order",
        ]


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    plan_id = serializers.PrimaryKeyRelatedField(
        queryset=Plan.objects.filter(is_active=True), source="plan", write_only=True
    )
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = Subscription
        fields = [
            "id", "plan", "plan_id", "status", "is_active",
            "trial_end", "current_period_start", "current_period_end",
            "canceled_at", "created_at",
        ]
        read_only_fields = ["id", "status", "trial_end", "current_period_start",
                            "current_period_end", "canceled_at", "created_at"]


class PaymentHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentHistory
        fields = ["id", "amount", "currency", "status", "description", "created_at"]
