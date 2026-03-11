from rest_framework import serializers
from .models import Budget, BudgetLine


class BudgetLineSerializer(serializers.ModelSerializer):
    actual_amount = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True, required=False)
    variance = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True, required=False)
    category_name = serializers.CharField(required=False, allow_blank=True, default='')

    class Meta:
        model = BudgetLine
        fields = ['id', 'category', 'category_name', 'category_type', 'period_month', 'budgeted_amount', 'unit_price', 'quantity', 'description', 'actual_amount', 'variance']
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

    class Meta:
        model = Budget
        fields = ['id', 'name', 'fiscal_year', 'period_type', 'status', 'notes', 'created_at', 'lines']
        read_only_fields = ['id', 'created_at']
