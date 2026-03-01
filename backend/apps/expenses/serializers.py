from rest_framework import serializers
from .models import Expense, ExpenseCategory


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "name", "description", "is_income", "created_at"]
        read_only_fields = ["id", "created_at"]


class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    # Write-only: accept a category name string; view auto-creates the FK record
    category_label = serializers.CharField(write_only=True, required=False, allow_blank=True)
    # Allow blank description — model requires non-blank but we default to empty string
    description = serializers.CharField(required=False, allow_blank=True, default='')
    recorded_by_name = serializers.CharField(source="recorded_by.get_full_name", read_only=True)

    class Meta:
        model = Expense
        fields = [
            "id", "category", "category_label", "category_name", "amount", "is_income",
            "description", "expense_date", "payment_method",
            "reference", "attachment", "is_approved",
            "recorded_by_name", "created_at",
        ]
        read_only_fields = ["id", "is_approved", "created_at"]
        extra_kwargs = {
            # category FK is resolved from category_label in the view
            'category': {'required': False},
        }
