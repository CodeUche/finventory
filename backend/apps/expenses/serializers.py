from decimal import Decimal

from django.db.models import Sum
from rest_framework import serializers

from apps.core.validators import validate_file_upload

from .models import Expense, ExpenseCategory, ExpenseGroup


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "name", "description", "is_income", "created_at"]
        read_only_fields = ["id", "created_at"]


class ExpenseGroupSerializer(serializers.ModelSerializer):
    parent_name = serializers.CharField(source='parent.name', read_only=True)
    children_count = serializers.SerializerMethodField()
    expense_count = serializers.SerializerMethodField()
    total_amount = serializers.SerializerMethodField()
    ancestors = serializers.SerializerMethodField()

    class Meta:
        model = ExpenseGroup
        fields = [
            'id', 'name', 'description', 'group_date',
            'parent', 'parent_name', 'ancestors',
            'children_count', 'expense_count', 'total_amount',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_children_count(self, obj):
        return obj.children.count()

    def get_expense_count(self, obj):
        return obj.expenses.count()

    def get_total_amount(self, obj):
        result = obj.expenses.aggregate(total=Sum('amount'))
        return str(result['total'] or 0)

    def get_ancestors(self, obj):
        return obj.get_ancestors()


class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    # Write-only: accept a category name string; view auto-creates the FK record
    # max_length on write-only fields prevents large strings from hitting the DB
    category_label = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=200)
    # Allow blank description — model requires non-blank but we default to empty string
    description = serializers.CharField(required=False, allow_blank=True, default='', max_length=1000)
    recorded_by_name = serializers.CharField(source="recorded_by.get_full_name", read_only=True)
    group_name = serializers.CharField(source="group.name", read_only=True)
    budget_name = serializers.CharField(source="budget.name", read_only=True, allow_null=True)

    class Meta:
        model = Expense
        fields = [
            "id", "category", "category_label", "category_name", "amount", "is_income",
            "description", "expense_date", "payment_method",
            "reference", "attachment", "is_approved",
            "previous_price", "recorded_by_name",
            "group", "group_name",
            "budget", "budget_name",
            "created_at",
        ]
        read_only_fields = ["id", "is_approved", "created_at"]
        extra_kwargs = {
            # category FK is resolved from category_label in the view
            'category': {'required': False},
            'group': {'required': False},
            'budget': {'required': False},
            # Field-level caps and upload validation
            'amount': {'min_value': Decimal('0.01')},
            'previous_price': {'min_value': Decimal('0.01'), 'required': False, 'allow_null': True},
            'reference': {'max_length': 200, 'required': False, 'allow_blank': True},
            'attachment': {'validators': [validate_file_upload], 'required': False},
        }
