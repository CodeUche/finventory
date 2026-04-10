from rest_framework import serializers
from .models import Account, JournalEntry, JournalLine, FixedAsset, DepreciationEntry, FinancialPeriod, BankReconciliation, BankReconciliationLine, AIReconMatch


class AccountSerializer(serializers.ModelSerializer):
    balance = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)

    class Meta:
        model = Account
        fields = ['id', 'code', 'name', 'account_type', 'parent', 'description', 'is_active', 'is_system', 'balance']
        read_only_fields = ['id', 'is_system', 'balance']


class JournalLineSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source='account.name', read_only=True)
    account_code = serializers.CharField(source='account.code', read_only=True)

    class Meta:
        model = JournalLine
        fields = ['id', 'account', 'account_name', 'account_code', 'debit', 'credit', 'description']
        read_only_fields = ['id']


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalLineSerializer(many=True, read_only=True)

    class Meta:
        model = JournalEntry
        fields = ['id', 'reference', 'description', 'entry_date', 'status', 'created_at', 'lines']
        read_only_fields = ['id', 'reference', 'created_at']


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
            'accumulated_depreciation', 'net_book_value', 'depreciation_entries'
        ]
        read_only_fields = ['id']
