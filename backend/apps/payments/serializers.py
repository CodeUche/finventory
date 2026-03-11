from rest_framework import serializers
from .models import PaymentGatewayConfig, PaymentLink


class PaymentGatewayConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentGatewayConfig
        fields = ['id', 'provider', 'public_key', 'secret_key', 'is_active', 'webhook_secret']
        read_only_fields = ['id']
        extra_kwargs = {
            # Never return API secrets in GET responses — write-only
            'secret_key': {'write_only': True},
            'webhook_secret': {'write_only': True},
        }


class PaymentLinkSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)

    class Meta:
        model = PaymentLink
        fields = ['id', 'invoice', 'invoice_number', 'provider', 'payment_reference', 'amount', 'currency', 'link_url', 'status', 'paid_at', 'created_at']
        read_only_fields = ['id', 'payment_reference', 'link_url', 'status', 'paid_at', 'created_at']
