from decimal import Decimal

from rest_framework import serializers
from .models import TaxBracket, TaxClass, TaxConfig, TaxReturn, ExciseDuty, WHTRate, WHTTransaction


class TaxClassSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxClass
        fields = ["id", "name", "rate", "description", "is_active"]
        read_only_fields = ["id"]


class TaxBracketSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxBracket
        fields = ["id", "lower_bound", "upper_bound", "rate", "cumulative_tax_below"]
        read_only_fields = ["id"]


class TaxConfigSerializer(serializers.ModelSerializer):
    brackets = TaxBracketSerializer(many=True, read_only=True)

    class Meta:
        model = TaxConfig
        fields = [
            "id", "name", "tax_type", "country", "tax_year",
            "is_progressive", "flat_rate", "personal_allowance",
            "is_active", "notes", "brackets",
        ]
        read_only_fields = ["id"]


class TaxReturnSerializer(serializers.ModelSerializer):
    config_name = serializers.CharField(source="config.name", read_only=True)

    class Meta:
        model = TaxReturn
        fields = [
            "id", "config", "config_name", "period_type",
            "period_start", "period_end", "status",
            "total_taxable_income", "total_allowances",
            "net_taxable_income", "tax_payable",
            "tax_paid", "tax_due", "filed_at", "notes",
        ]
        read_only_fields = ["id", "filed_at"]


class IncomeTaxCalculateSerializer(serializers.Serializer):
    income = serializers.DecimalField(max_digits=15, decimal_places=2, min_value=Decimal("0"))
    tax_year = serializers.IntegerField(required=False)
    allowances = serializers.DecimalField(max_digits=15, decimal_places=2, required=False)
    tax_type = serializers.ChoiceField(choices=['income', 'corporate'], required=False, default='income')


class VATReportSerializer(serializers.Serializer):
    period_start = serializers.DateField()
    period_end = serializers.DateField()


class ExciseDutySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExciseDuty
        fields = ['id', 'name', 'product_category', 'duty_type', 'rate', 'effective_date', 'is_active', 'notes']
        read_only_fields = ['id']


class WHTRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = WHTRate
        fields = ['id', 'transaction_type', 'company_rate', 'individual_rate', 'is_active']
        read_only_fields = ['id']


class WHTTransactionSerializer(serializers.ModelSerializer):
    wht_rate_name = serializers.CharField(source='wht_rate.transaction_type', read_only=True)

    class Meta:
        model = WHTTransaction
        fields = [
            'id', 'transaction_type', 'wht_rate', 'wht_rate_name', 'counterparty_name', 'tin',
            'gross_amount', 'wht_rate_percent', 'wht_amount', 'net_amount',
            'transaction_date', 'status', 'notes',
        ]
        # wht_amount and net_amount are auto-calculated in the view from gross × rate
        read_only_fields = ['id', 'wht_amount', 'net_amount']
