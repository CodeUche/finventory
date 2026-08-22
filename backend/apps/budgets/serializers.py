from rest_framework import serializers
from .models import Budget, BudgetLine


class BudgetLineSerializer(serializers.ModelSerializer):
    actual_amount = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True, required=False)
    variance = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True, required=False)
    category_name = serializers.CharField(required=False, allow_blank=True, default='')
    account_code = serializers.CharField(source='account.code', read_only=True, default=None)
    account_name = serializers.CharField(source='account.name', read_only=True, default=None)

    class Meta:
        model = BudgetLine
        fields = [
            'id', 'category', 'category_name', 'category_type', 'period_month',
            'budgeted_amount', 'unit_price', 'quantity', 'description',
            'actual_amount', 'variance', 'account', 'account_code', 'account_name',
        ]
        read_only_fields = ['id']

    def validate(self, attrs):
        # Auto-populate category_name from FK if not explicitly provided
        category = attrs.get('category')
        category_name = attrs.get('category_name', '').strip()
        if category and not category_name:
            attrs['category_name'] = category.name
        elif not category_name:
            attrs['category_name'] = 'Uncategorized'
        return attrs


class BudgetSerializer(serializers.ModelSerializer):
    lines = BudgetLineSerializer(many=True, read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True, default=None)

    class Meta:
        model = Budget
        fields = [
            'id', 'name', 'fiscal_year', 'period_type', 'status', 'notes', 'created_at', 'lines',
            'budget_type', 'start_date', 'end_date',
            'approved_by', 'approved_by_name', 'approved_at',
        ]
        read_only_fields = ['id', 'created_at', 'approved_by', 'approved_by_name', 'approved_at']
