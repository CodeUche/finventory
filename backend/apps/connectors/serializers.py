from rest_framework import serializers

from .models import ConnectorAddonSubscription, ConnectorConnection


class ConnectorConnectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConnectorConnection
        fields = [
            "id", "connector_key", "status", "external_account_label",
            "config", "billing_mode", "connected_at", "created_at", "updated_at",
        ]
        read_only_fields = fields


class ConnectorAddonSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConnectorAddonSubscription
        fields = [
            "id", "connector_key", "status", "interval", "amount",
            "current_period_start", "current_period_end", "canceled_at",
        ]
        read_only_fields = fields
