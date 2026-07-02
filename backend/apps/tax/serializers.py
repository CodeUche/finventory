from decimal import Decimal

from rest_framework import serializers
from .models import (
    CapitalAllowanceClaim, DeferredTaxItem, ExciseDuty,
    RelatedPartyTransaction, TaxBracket, TaxClass, TaxConfig, TaxObligation, TaxReturn,
    VATTransaction, WHTCertificate, WHTRate, WHTTransaction,
)


class TaxClassSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxClass
        fields = ["id", "name", "rate", "treatment", "description", "is_active"]
        read_only_fields = ["id"]
        validators = []

    def validate(self, attrs):
        request = self.context.get('request')
        if request and hasattr(request, 'organisation') and request.organisation:
            org = request.organisation
            qs = TaxClass.objects.filter(organisation=org, name=attrs.get('name', ''))
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({'name': 'A VAT class with this name already exists.'})
        return attrs


class TaxBracketSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxBracket
        fields = ["id", "lower_bound", "upper_bound", "rate", "cumulative_tax_below"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        lb = attrs.get('lower_bound', Decimal('0'))
        ub = attrs.get('upper_bound')
        rate = attrs.get('rate', Decimal('0'))
        if ub is not None and ub <= lb:
            raise serializers.ValidationError(
                f"upper_bound ({ub}) must be greater than lower_bound ({lb}). "
                "For the top bracket leave upper_bound blank (null)."
            )
        if rate < 0 or rate > 100:
            raise serializers.ValidationError("rate must be between 0 and 100.")
        return attrs


def _validate_bracket_set(brackets_data: list) -> None:
    """
    Cross-bracket validation for the PUT /tax/configs/{id}/brackets/ endpoint.
    Rejects: overlaps, gaps between consecutive brackets, upper_bound=0, unsorted input.
    """
    if not brackets_data:
        return
    sorted_b = sorted(brackets_data, key=lambda b: b.get('lower_bound', Decimal('0')))
    for i, b in enumerate(sorted_b):
        lb = b.get('lower_bound', Decimal('0'))
        ub = b.get('upper_bound')
        is_last = (i == len(sorted_b) - 1)
        if not is_last and ub is None:
            raise serializers.ValidationError(
                f"Bracket starting at {lb}: upper_bound can only be null on the last (top) bracket."
            )
        if ub is not None and ub == 0:
            raise serializers.ValidationError(
                f"Bracket starting at {lb}: upper_bound=0 is invalid. "
                "Use null for an unbounded top bracket."
            )
        if i > 0:
            prev_ub = sorted_b[i - 1].get('upper_bound')
            if prev_ub is not None and lb != prev_ub:
                raise serializers.ValidationError(
                    f"Gap or overlap between brackets: previous upper_bound={prev_ub}, "
                    f"this lower_bound={lb}. Brackets must be contiguous with no gaps or overlaps."
                )


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
    gross_turnover = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, min_value=Decimal("0"),
                                              help_text="CIT only: gross turnover for small-company exemption and 0.5% minimum tax floor")
    fixed_assets = serializers.DecimalField(max_digits=15, decimal_places=2, required=False, min_value=Decimal("0"),
                                            help_text="CIT only: total fixed assets for small-company exemption (≤₦250m threshold)")


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
    has_certificate = serializers.SerializerMethodField()

    class Meta:
        model = WHTTransaction
        fields = [
            'id', 'transaction_type', 'wht_rate', 'wht_rate_name', 'counterparty_name', 'tin',
            'gross_amount', 'wht_rate_percent', 'wht_amount', 'net_amount',
            'transaction_date', 'status', 'notes', 'has_certificate',
        ]
        read_only_fields = ['id', 'wht_amount', 'net_amount', 'has_certificate']

    def validate_wht_rate(self, value):
        if value is None:
            return value
        request = self.context.get('request')
        if request and hasattr(request, 'organisation') and request.organisation:
            if value.organisation_id != request.organisation.id:
                raise serializers.ValidationError("WHT rate does not belong to this organisation.")
        return value

    def get_has_certificate(self, obj):
        return hasattr(obj, 'certificate')


class WHTCertificateSerializer(serializers.ModelSerializer):
    counterparty_name = serializers.CharField(source='wht_transaction.counterparty_name', read_only=True)
    wht_amount = serializers.DecimalField(source='wht_transaction.wht_amount', max_digits=15, decimal_places=2, read_only=True)
    gross_amount = serializers.DecimalField(source='wht_transaction.gross_amount', max_digits=15, decimal_places=2, read_only=True)
    transaction_date = serializers.DateField(source='wht_transaction.transaction_date', read_only=True)

    class Meta:
        model = WHTCertificate
        fields = [
            'id', 'wht_transaction', 'certificate_number', 'issued_date',
            'remittance_reference', 'notes', 'created_at',
            'counterparty_name', 'wht_amount', 'gross_amount', 'transaction_date',
        ]
        read_only_fields = ['id', 'certificate_number', 'created_at', 'counterparty_name', 'wht_amount', 'gross_amount', 'transaction_date']


class VATTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = VATTransaction
        fields = [
            'id', 'direction', 'period_start', 'period_end',
            'counterparty_name', 'counterparty_tin', 'net_amount', 'vat_amount',
            'vat_rate', 'is_claimable', 'source_ref', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class VATReconciliationSerializer(serializers.Serializer):
    period_start = serializers.DateField()
    period_end = serializers.DateField()


class TaxObligationSerializer(serializers.ModelSerializer):
    is_overdue = serializers.SerializerMethodField()
    days_until_due = serializers.SerializerMethodField()

    class Meta:
        model = TaxObligation
        fields = [
            'id', 'obligation_type', 'label', 'period_year', 'period_month',
            'due_date', 'status', 'amount_due', 'filed_date', 'payment_reference',
            'notes', 'is_auto_generated', 'is_overdue', 'days_until_due', 'created_at',
        ]
        read_only_fields = ['id', 'is_auto_generated', 'created_at', 'is_overdue', 'days_until_due']

    def get_is_overdue(self, obj):
        from datetime import date
        return obj.status == 'pending' and obj.due_date < date.today()

    def get_days_until_due(self, obj):
        from datetime import date
        return (obj.due_date - date.today()).days


class CapitalAllowanceClaimSerializer(serializers.ModelSerializer):
    asset_class_display = serializers.CharField(source='get_asset_class_display', read_only=True)

    class Meta:
        model = CapitalAllowanceClaim
        fields = [
            'id', 'asset_name', 'asset_class', 'asset_class_display', 'tax_year',
            'cost', 'opening_tax_written_down_value', 'is_acquisition_year',
            'initial_allowance_rate', 'annual_allowance_rate',
            'initial_allowance', 'annual_allowance', 'total_allowance',
            'closing_tax_written_down_value', 'notes', 'created_at',
        ]
        read_only_fields = [
            'id', 'asset_class_display', 'initial_allowance_rate', 'annual_allowance_rate',
            'initial_allowance', 'annual_allowance', 'total_allowance',
            'closing_tax_written_down_value', 'created_at',
        ]


class DeferredTaxItemSerializer(serializers.ModelSerializer):
    deferred_type_display = serializers.CharField(source='get_deferred_type_display', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = DeferredTaxItem
        fields = [
            'id', 'deferred_type', 'deferred_type_display', 'category', 'category_display',
            'description', 'tax_year', 'timing_difference', 'tax_rate',
            'deferred_tax_amount', 'is_recognised', 'reversal_year', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'deferred_type', 'deferred_type_display', 'category_display', 'deferred_tax_amount', 'created_at']


class RelatedPartyTransactionSerializer(serializers.ModelSerializer):
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    tp_method_display = serializers.CharField(source='get_tp_method_display', read_only=True)
    exceeds_threshold = serializers.BooleanField(read_only=True)

    class Meta:
        model = RelatedPartyTransaction
        fields = [
            'id', 'related_party_name', 'relationship', 'country',
            'transaction_type', 'transaction_type_display', 'tax_year',
            'amount', 'currency', 'tp_method', 'tp_method_display',
            'arm_length_price', 'adjustment_required', 'adjustment_amount',
            'documentation_status', 'exceeds_threshold', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'transaction_type_display', 'tp_method_display', 'exceeds_threshold', 'created_at']
