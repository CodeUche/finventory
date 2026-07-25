from rest_framework import serializers
from .models import (
    Account, AccountSubType, JournalEntry, JournalLine, FixedAsset, DepreciationEntry,
    FinancialPeriod, BankReconciliation, BankReconciliationLine, AIReconMatch, AccountMapping,
    AssetType, normal_balance_for_type,
)


class AccountSubTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountSubType
        fields = ['id', 'name', 'account_group', 'base_account_type', 'is_active', 'is_system']
        read_only_fields = ['id', 'is_system']


class AccountSerializer(serializers.ModelSerializer):
    balance = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)
    sub_type_name = serializers.CharField(source='sub_type.name', read_only=True)
    parent_code = serializers.CharField(source='parent.code', read_only=True)
    parent_name = serializers.CharField(source='parent.name', read_only=True)

    class Meta:
        model = Account
        fields = [
            'id', 'code', 'name', 'account_type', 'account_group', 'sub_type', 'sub_type_name',
            'parent', 'parent_code', 'parent_name', 'description', 'normal_balance',
            'is_active', 'allow_posting', 'is_control_account',
            'opening_balance', 'opening_balance_date', 'attachment', 'is_system', 'balance',
        ]
        read_only_fields = ['id', 'is_system', 'balance', 'sub_type_name', 'parent_code', 'parent_name']

    def validate(self, attrs):
        # Sub-type must belong to the selected group (server-side enforcement so
        # imports can't create inconsistent (group, sub_type) pairs).
        sub_type = attrs.get('sub_type') or getattr(self.instance, 'sub_type', None)
        group = attrs.get('account_group') or getattr(self.instance, 'account_group', '')
        if sub_type and group and sub_type.account_group != group:
            raise serializers.ValidationError(
                {'sub_type': f"Sub-type '{sub_type.name}' does not belong to group '{group}'."}
            )
        # Prevent self-parenting cycles.
        parent = attrs.get('parent')
        if parent and self.instance and parent.pk == self.instance.pk:
            raise serializers.ValidationError({'parent': 'An account cannot be its own parent.'})
        return attrs

    def create(self, validated_data):
        # Default normal_balance from account_type when the client omits it.
        if not validated_data.get('normal_balance'):
            validated_data['normal_balance'] = normal_balance_for_type(validated_data.get('account_type'))
        return super().create(validated_data)


class JournalLineSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source='account.name', read_only=True)
    account_code = serializers.CharField(source='account.code', read_only=True)

    class Meta:
        model = JournalLine
        fields = ['id', 'account', 'account_name', 'account_code', 'debit', 'credit', 'description']
        read_only_fields = ['id']


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalLineSerializer(many=True, read_only=True)
    total_debit = serializers.SerializerMethodField()
    total_credit = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True)
    signed_by_name = serializers.CharField(source='signed_by.get_full_name', read_only=True)

    class Meta:
        model = JournalEntry
        fields = [
            'id', 'reference', 'description', 'entry_date', 'status', 'created_at', 'lines',
            'total_debit', 'total_credit', 'created_by_name',
            'approval_status', 'approved_by_name', 'approved_at', 'approval_note',
            'attachment', 'signature', 'signed_by_name', 'signed_at',
        ]
        read_only_fields = ['id', 'reference', 'created_at']

    def get_total_debit(self, obj):
        return sum((l.debit for l in obj.lines.all()), 0)

    def get_total_credit(self, obj):
        return sum((l.credit for l in obj.lines.all()), 0)

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else ''


class CreateJournalEntrySerializer(serializers.Serializer):
    description = serializers.CharField()
    entry_date = serializers.DateField()
    lines = serializers.ListField(child=serializers.DictField(), min_length=2)


class UpdateJournalEntrySerializer(serializers.Serializer):
    description = serializers.CharField(required=False)
    entry_date = serializers.DateField(required=False)
    lines = serializers.ListField(child=serializers.DictField(), min_length=2, required=False)


class DepreciationEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = DepreciationEntry
        fields = ['id', 'period_year', 'period_month', 'depreciation_amount', 'accumulated_to_date', 'net_book_value']
        read_only_fields = ['id']


class FinancialPeriodSerializer(serializers.ModelSerializer):
    locked_by_name = serializers.CharField(source='locked_by.get_full_name', read_only=True, default=None)

    class Meta:
        model = FinancialPeriod
        fields = ['id', 'year', 'month', 'is_locked', 'locked_by', 'locked_by_name', 'locked_at', 'created_at']
        read_only_fields = ['id', 'is_locked', 'locked_by', 'locked_at', 'created_at']


class BankReconciliationLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankReconciliationLine
        fields = ['id', 'description', 'transaction_date', 'amount', 'is_cleared', 'reference', 'journal_line']
        read_only_fields = ['id']


class AIReconMatchSerializer(serializers.ModelSerializer):
    bank_line_description = serializers.CharField(source='bank_line.description', read_only=True)
    bank_line_date = serializers.DateField(source='bank_line.transaction_date', read_only=True)
    bank_line_amount = serializers.DecimalField(source='bank_line.amount', max_digits=15, decimal_places=4, read_only=True)
    book_line_description = serializers.CharField(source='book_line.description', read_only=True, allow_null=True)
    book_line_date = serializers.DateField(source='book_line.journal_entry.entry_date', read_only=True, allow_null=True)
    book_line_debit = serializers.DecimalField(source='book_line.debit', max_digits=15, decimal_places=4, read_only=True, allow_null=True)
    book_line_credit = serializers.DecimalField(source='book_line.credit', max_digits=15, decimal_places=4, read_only=True, allow_null=True)
    book_line_reference = serializers.CharField(source='book_line.journal_entry.reference', read_only=True, allow_null=True)

    class Meta:
        model = AIReconMatch
        fields = [
            'id', 'bank_line', 'book_line', 'confidence', 'match_type', 'status',
            'ai_reasoning', 'ai_advice',
            'bank_line_description', 'bank_line_date', 'bank_line_amount',
            'book_line_description', 'book_line_date', 'book_line_debit', 'book_line_credit', 'book_line_reference',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class BankReconciliationSerializer(serializers.ModelSerializer):
    lines = BankReconciliationLineSerializer(many=True, read_only=True)
    ai_matches = AIReconMatchSerializer(many=True, read_only=True)
    account_name = serializers.CharField(source='account.name', read_only=True)
    account_code = serializers.CharField(source='account.code', read_only=True)

    class Meta:
        model = BankReconciliation
        fields = [
            'id', 'account', 'account_name', 'account_code',
            'period_start', 'period_end', 'statement_closing_balance',
            'book_balance', 'is_reconciled', 'reconciled_by', 'reconciled_at',
            'notes', 'lines', 'ai_matches', 'created_at',
        ]
        read_only_fields = ['id', 'book_balance', 'is_reconciled', 'reconciled_by', 'reconciled_at', 'created_at']


class FixedAssetSerializer(serializers.ModelSerializer):
    # Optional — auto-generated (FA-XXXX) by the view when left blank, matching the
    # "auto if blank" hint on the form.
    asset_code = serializers.CharField(required=False, allow_blank=True)
    annual_depreciation = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    accumulated_depreciation = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    net_book_value = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    depreciation_entries = DepreciationEntrySerializer(many=True, read_only=True, source='ordered_entries')

    class Meta:
        model = FixedAsset
        fields = [
            'id', 'name', 'asset_code', 'category', 'account', 'purchase_date',
            'purchase_cost', 'depreciation_method', 'useful_life_years', 'residual_value',
            'disposal_date', 'disposal_amount', 'is_active', 'annual_depreciation',
            'accumulated_depreciation', 'net_book_value', 'depreciation_entries',
            'funding_source', 'capitalisation_source', 'source_document_ref',
            'acquisition_posted', 'acquisition_error',
            'qualifying_cost', 'input_tax_paid', 'input_tax_amount',
            'reducing_balance_rate', 'depreciation_convention', 'total_units',
            'location', 'cost_centre', 'asset_type',
        ]
        read_only_fields = ['id', 'acquisition_posted', 'acquisition_error', 'source_document_ref']


class AssetTypeSerializer(serializers.ModelSerializer):
    asset_count = serializers.SerializerMethodField()

    class Meta:
        model = AssetType
        fields = [
            'id', 'code', 'name', 'category', 'depreciation_method', 'useful_life_years',
            'reducing_balance_rate', 'fixed_asset_account', 'depreciation_expense_account',
            'accumulated_depreciation_account', 'is_active', 'asset_count',
        ]
        read_only_fields = ['id', 'asset_count']

    def get_asset_count(self, obj):
        return obj.assets.count()


# Helper to build account summary dict
def _account_summary(account):
    if account is None:
        return None
    return {'id': str(account.id), 'code': account.code, 'name': account.name}


MAPPING_ROLES = [
    'revenue_account', 'cogs_account', 'inventory_account', 'accounts_receivable',
    'cash_account', 'bank_account', 'accounts_payable', 'vat_output_account',
    'vat_input_account', 'paye_account', 'pension_account', 'wht_account',
    'salary_expense_account', 'general_expense_account', 'bank_charges_account',
]


class AccountMappingSerializer(serializers.ModelSerializer):
    """
    Serializer for AccountMapping. Exposes for each role:
    - {role}_id   — UUID of mapped account
    - {role}_code — account code (read-only)
    - {role}_name — account name (read-only)
    - {role}_suggestion — best-guess account if null (read-only, computed)
    """

    class Meta:
        model = AccountMapping
        fields = ['id'] + [r + '_id' for r in MAPPING_ROLES]
        read_only_fields = ['id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _get_role_account(self, obj, role):
        return getattr(obj, role, None)

    def _get_suggestion(self, obj, role):
        from .services import AccountMappingService
        acct = getattr(obj, role, None)
        if acct is not None:
            return None  # Already mapped
        suggestion = AccountMappingService.suggest(obj.organisation, role)
        return _account_summary(suggestion)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for role in MAPPING_ROLES:
            acct = getattr(instance, role, None)
            data[f'{role}_code'] = acct.code if acct else None
            data[f'{role}_name'] = acct.name if acct else None
            # Suggestion
            if acct is None:
                from .services import AccountMappingService
                suggestion = AccountMappingService.suggest(instance.organisation, role)
                data[f'{role}_suggestion'] = _account_summary(suggestion)
            else:
                data[f'{role}_suggestion'] = None
        return data

    def update(self, instance, validated_data):
        for role in MAPPING_ROLES:
            field_name = f'{role}_id'
            if field_name in validated_data:
                setattr(instance, role + '_id', validated_data[field_name])
        instance.save()
        return instance
