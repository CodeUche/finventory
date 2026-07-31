from rest_framework import serializers

from .models import TillSession, TillTenderCount


class TillTenderCountSerializer(serializers.ModelSerializer):
    class Meta:
        model = TillTenderCount
        fields = ["id", "method", "expected", "counted", "variance", "transaction_count"]
        read_only_fields = fields


class TillSessionSerializer(serializers.ModelSerializer):
    opened_by_name = serializers.SerializerMethodField()
    closed_by_name = serializers.SerializerMethodField()
    location_name = serializers.CharField(source="location.name", read_only=True, default="")
    tender_counts = TillTenderCountSerializer(many=True, read_only=True)

    class Meta:
        model = TillSession
        fields = [
            "id", "location", "location_name", "opened_by", "opened_by_name",
            "opened_at", "opening_float", "closed_by", "closed_by_name", "closed_at",
            "status", "cash_variance", "variance_reason", "notes", "tender_counts",
        ]
        read_only_fields = [
            "id", "opened_by", "opened_by_name", "opened_at", "closed_by",
            "closed_by_name", "closed_at", "status", "cash_variance", "tender_counts",
        ]

    def _name(self, user):
        if user is None:
            return ""
        return user.get_full_name() or user.email

    def get_opened_by_name(self, obj) -> str:
        return self._name(obj.opened_by)

    def get_closed_by_name(self, obj) -> str:
        return self._name(obj.closed_by)
