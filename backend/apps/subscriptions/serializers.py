from rest_framework import serializers

from .models import PaymentHistory, Plan, Subscription


class PlanSerializer(serializers.ModelSerializer):
    is_free = serializers.SerializerMethodField()

    def get_is_free(self, obj):
        return float(obj.price) == 0

    class Meta:
        model = Plan
        fields = [
            "id", "name", "slug", "description", "price", "interval",
            "trial_days", "features", "is_public", "display_order", "is_free",
        ]


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    plan_id = serializers.PrimaryKeyRelatedField(
        queryset=Plan.objects.filter(is_active=True), source="plan", write_only=True
    )
    is_active = serializers.BooleanField(read_only=True)
    is_expired = serializers.SerializerMethodField()
    is_trial = serializers.SerializerMethodField()
    days_remaining = serializers.SerializerMethodField()

    def get_is_expired(self, obj):
        return not obj.is_active

    def get_is_trial(self, obj):
        return obj.status == obj.__class__.Status.TRIALING

    def get_days_remaining(self, obj):
        from django.utils import timezone
        now = timezone.now()
        if obj.status == obj.__class__.Status.TRIALING and obj.trial_end:
            return max(0, (obj.trial_end - now).days)
        if obj.status == obj.__class__.Status.ACTIVE and obj.current_period_end:
            return max(0, (obj.current_period_end - now).days)
        return None

    class Meta:
        model = Subscription
        fields = [
            "id", "plan", "plan_id", "status", "is_active",
            "is_expired", "is_trial", "days_remaining",
            "trial_end", "current_period_start", "current_period_end",
            "canceled_at", "created_at",
        ]
        read_only_fields = ["id", "status", "trial_end", "current_period_start",
                            "current_period_end", "canceled_at", "created_at"]


class PaymentHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentHistory
        fields = ["id", "amount", "currency", "status", "description", "created_at"]
