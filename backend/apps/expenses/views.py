import django_filters
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsAccountant, IsStaff

from .models import Expense, ExpenseCategory
from .serializers import ExpenseCategorySerializer, ExpenseSerializer


class ExpenseFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name="expense_date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="expense_date", lookup_expr="lte")
    is_income = django_filters.BooleanFilter()
    category = django_filters.UUIDFilter()

    class Meta:
        model = Expense
        fields = ["is_income", "category", "payment_method", "is_approved"]


class ExpenseCategoryViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAuthenticated, IsAccountant]


class ExpenseViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    queryset = Expense.objects.select_related("category", "recorded_by")
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    filterset_class = ExpenseFilter
    search_fields = ["description", "reference"]
    ordering_fields = ["expense_date", "amount"]

    def _resolve_category(self, label, is_income, org):
        """Get or create an ExpenseCategory by name for the org."""
        name = (label or '').strip() or 'Uncategorized'
        category, _ = ExpenseCategory.objects.get_or_create(
            organisation=org,
            name=name,
            defaults={'is_income': is_income, 'description': ''},
        )
        return category

    def perform_create(self, serializer):
        org = self.request.organisation
        label = serializer.validated_data.pop('category_label', '')
        is_income = serializer.validated_data.get('is_income', False)
        category = self._resolve_category(label, is_income, org)
        serializer.save(organisation=org, recorded_by=self.request.user, category=category)

    def perform_update(self, serializer):
        org = self.request.organisation
        label = serializer.validated_data.pop('category_label', None)
        if label is not None:
            is_income = serializer.validated_data.get('is_income', serializer.instance.is_income)
            category = self._resolve_category(label, is_income, org)
            serializer.save(category=category)
        else:
            serializer.save()
