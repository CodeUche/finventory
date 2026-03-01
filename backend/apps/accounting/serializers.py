from rest_framework import serializers
from .models import Account, JournalEntry, JournalLine, FixedAsset, DepreciationEntry


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


class DepreciationEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = DepreciationEntry
        fields = ['id', 'period_year', 'period_month', 'depreciation_amount', 'accumulated_to_date', 'net_book_value']
        read_only_fields = ['id']


class FixedAssetSerializer(serializers.ModelSerializer):
    annual_depreciation = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    accumulated_depreciation = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    net_book_value = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    depreciation_entries = DepreciationEntrySerializer(many=True, read_only=True)

    class Meta:
        model = FixedAsset
        fields = [
            'id', 'name', 'asset_code', 'category', 'account', 'purchase_date',
            'purchase_cost', 'depreciation_method', 'useful_life_years', 'residual_value',
            'disposal_date', 'disposal_amount', 'is_active', 'annual_depreciation',
            'accumulated_depreciation', 'net_book_value', 'depreciation_entries'
        ]
        read_only_fields = ['id']
