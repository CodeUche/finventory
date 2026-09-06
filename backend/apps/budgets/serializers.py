from rest_framework import serializers
from .models import Budget, BudgetLine, BudgetPeriod, BudgetAllocation
from .services import BudgetService


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
    period_name = serializers.SerializerMethodField()

    class Meta:
        model = Budget
        fields = [
            'id', 'name', 'fiscal_year', 'period_type', 'status', 'notes', 'created_at', 'lines',
            'budget_type', 'start_date', 'end_date',
            'approved_by', 'approved_by_name', 'approved_at',
            'period', 'period_name', 'tax_rate',
        ]
        read_only_fields = ['id', 'created_at', 'approved_by', 'approved_by_name', 'approved_at']

    def get_period_name(self, obj):
        return obj.period.name if obj.period else None


class BudgetPeriodSerializer(serializers.ModelSerializer):
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True, default=None)

    class Meta:
        model = BudgetPeriod
        fields = [
            'id', 'name', 'financial_year', 'start_date', 'end_date', 'status',
            'approved_by', 'approved_by_name', 'approved_at',
        ]
        read_only_fields = ['id', 'approved_by', 'approved_by_name', 'approved_at']


class BudgetAllocationSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source='account.code', read_only=True, default=None)
    account_name = serializers.CharField(source='account.name', read_only=True, default=None)
    budget_name = serializers.CharField(source='budget.name', read_only=True, default=None)
    spent_amount = serializers.SerializerMethodField()
    remaining_amount = serializers.SerializerMethodField()

    class Meta:
        model = BudgetAllocation
        fields = [
            'id', 'budget', 'budget_name', 'account', 'account_code', 'account_name',
            'allocated_amount', 'notes', 'spent_amount', 'remaining_amount',
        ]
        read_only_fields = ['id']

    def get_spent_amount(self, obj):
        return BudgetService.get_allocation_actuals(obj)['spent_amount']

    def get_remaining_amount(self, obj):
        return BudgetService.get_allocation_actuals(obj)['remaining_amount']

    def validate_account(self, value):
        """Tenant isolation: reject an Account PK belonging to another org.
        Same guard as BudgetLineSerializer.validate_account — this FK feeds
        real JournalLine queries (get_allocation_actuals), so a cross-org
        account here would leak that org's GL activity into this org's
        allocation view."""
        if value is None:
            return value
        request = self.context.get('request')
        org = getattr(request, 'organisation', None) if request else None
        if org is None or value.organisation_id != org.id:
            raise serializers.ValidationError("This account does not belong to your organisation.")
        return value

    def validate_budget(self, value):
        """Tenant isolation: the Budget this allocation attaches to must also
        belong to the requesting org — otherwise a caller could attach an
        allocation (and its GL-account link) to another org's budget."""
        if value is None:
            return value
        request = self.context.get('request')
        org = getattr(request, 'organisation', None) if request else None
        if org is None or value.organisation_id != org.id:
            raise serializers.ValidationError("This budget does not belong to your organisation.")
        return value
