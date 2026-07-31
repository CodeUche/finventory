from rest_framework import serializers

from .models import (
    BankTransferClaim, MerchantBankAccount, PaymentGatewayConfig, PaymentLink,
    VirtualAccount,
)


class PaymentGatewayConfigSerializer(serializers.ModelSerializer):
    provider_label = serializers.CharField(source='get_provider_display', read_only=True)
    # Lets the settings screen say "key saved" without ever sending it back.
    has_secret_key = serializers.SerializerMethodField()
    has_webhook_secret = serializers.SerializerMethodField()

    class Meta:
        model = PaymentGatewayConfig
        fields = [
            'id', 'provider', 'provider_label', 'public_key', 'secret_key', 'webhook_secret',
            'has_secret_key', 'has_webhook_secret', 'is_active',
            'contract_code', 'preferred_bank', 'use_sandbox',
            'allow_card', 'allow_transfer', 'virtual_account_minutes',
        ]
        read_only_fields = ['id', 'provider_label', 'has_secret_key', 'has_webhook_secret']
        extra_kwargs = {
            # Never return API secrets in GET responses — write-only.
            'secret_key': {'write_only': True, 'required': False},
            'webhook_secret': {'write_only': True, 'required': False},
        }

    def get_has_secret_key(self, obj) -> bool:
        return bool(obj.secret_key)

    def get_has_webhook_secret(self, obj) -> bool:
        return bool(obj.webhook_secret)

    def update(self, instance, validated_data):
        # A blank secret on update means "leave it alone", not "erase it" — the
        # form can't show the value, so it can't send it back either.
        for field in ('secret_key', 'webhook_secret'):
            if field in validated_data and not validated_data[field]:
                validated_data.pop(field)
        return super().update(instance, validated_data)


class MerchantBankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = MerchantBankAccount
        fields = [
            'id', 'bank_name', 'account_number', 'account_name', 'is_default',
            'is_active', 'show_on_invoice', 'show_on_storefront', 'instructions',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class PaymentLinkSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)

    class Meta:
        model = PaymentLink
        fields = [
            'id', 'invoice', 'invoice_number', 'provider', 'payment_reference',
            'amount', 'currency', 'link_url', 'status', 'paid_at', 'created_at',
        ]
        read_only_fields = [
            'id', 'payment_reference', 'link_url', 'status', 'paid_at', 'created_at',
        ]


class VirtualAccountSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = VirtualAccount
        fields = [
            'id', 'invoice', 'invoice_number', 'provider', 'reference',
            'account_number', 'bank_name', 'account_name', 'amount', 'currency',
            'status', 'is_expired', 'expires_at', 'paid_at', 'created_at',
        ]
        read_only_fields = fields


class BankTransferClaimSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True)
    bank_name = serializers.CharField(source='bank_account.bank_name', read_only=True, default='')
    account_number = serializers.CharField(
        source='bank_account.account_number', read_only=True, default='',
    )
    reviewed_by_name = serializers.CharField(
        source='reviewed_by.get_full_name', read_only=True, default='',
    )

    class Meta:
        model = BankTransferClaim
        fields = [
            'id', 'invoice', 'invoice_number', 'bank_account', 'bank_name',
            'account_number', 'amount', 'payer_name', 'narration', 'proof',
            'status', 'reviewed_by_name', 'reviewed_at', 'review_note', 'created_at',
        ]
        read_only_fields = [
            'id', 'status', 'reviewed_by_name', 'reviewed_at', 'review_note', 'created_at',
        ]
