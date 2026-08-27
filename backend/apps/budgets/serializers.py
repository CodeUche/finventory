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

    def validate_account(self, value):
        """Tenant isolation: reject an Account PK belonging to another org.
        _actual_for_line queries real JournalLine data by this FK (Phase 2),
        so a cross-org account here is a genuine data leak, not cosmetic —
        must be blocked at write time. Requires context={'request': request}
        to be passed by the caller (see views.py add_line)."""
        if value is None:
            return value
        request = self.context.get('request')
        org = getattr(request, 'organisation', None) if request else None
        if org is None or value.organisation_id != org.id:
            raise serializers.ValidationError("This account does not belong to your organisation.")
        return value


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
