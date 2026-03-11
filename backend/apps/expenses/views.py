import django_filters
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsAccountant, IsStaff

from .models import Expense, ExpenseCategory, ExpenseGroup
from .serializers import ExpenseCategorySerializer, ExpenseSerializer, ExpenseGroupSerializer


class ExpenseFilter(django_filters.FilterSet):
    date_from = django_filters.DateFilter(field_name="expense_date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="expense_date", lookup_expr="lte")
    is_income = django_filters.BooleanFilter()
    category = django_filters.UUIDFilter()

    class Meta:
        model = Expense
        fields = ["is_income", "category", "payment_method", "is_approved"]


class ExpenseGroupViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """
    CRUD for expense/income folders.
    GET /expenses/groups/?parent=null  → root-level folders
    GET /expenses/groups/?parent=<id>  → children of a folder
    GET /expenses/groups/<id>/contents/ → folder + its children + its expenses
    """
    serializer_class = ExpenseGroupSerializer
    permission_classes = [IsAuthenticated, IsStaff]

    def get_queryset(self):
        org = self._get_organisation()
        qs = ExpenseGroup.objects.filter(organisation=org)
        parent_param = self.request.query_params.get('parent')
        if parent_param is not None:
            if parent_param in ('null', ''):
                qs = qs.filter(parent__isnull=True)
            else:
                qs = qs.filter(parent_id=parent_param)
        return qs

    def perform_create(self, serializer):
        serializer.save(organisation=self._get_organisation())

    @action(detail=True, methods=['get'])
    def contents(self, request, pk=None):
        group = self.get_object()
        children = group.children.all()
        expenses = group.expenses.select_related('category', 'recorded_by').all()
        return Response({
            'group': ExpenseGroupSerializer(group).data,
            'children': ExpenseGroupSerializer(children, many=True).data,
            'expenses': ExpenseSerializer(expenses, many=True).data,
        })


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
        import logging as _log
        org = self.request.organisation

        # Period lock check
        from apps.accounting.services import AccountingService
        expense_date = serializer.validated_data.get('expense_date')
        if expense_date and AccountingService.is_period_locked(org, expense_date):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied(f"The period {expense_date.year}-{expense_date.month:02d} is locked.")

        label = serializer.validated_data.pop('category_label', '')
        is_income = serializer.validated_data.get('is_income', False)
        category = self._resolve_category(label, is_income, org)
        expense = serializer.save(organisation=org, recorded_by=self.request.user, category=category)

        # Auto-post journal entry (non-blocking)
        try:
            AccountingService.post_expense_journal(org, expense, self.request.user)
        except Exception as exc:
            _log.getLogger(__name__).warning("post_expense_journal failed: %s", exc)

    def perform_update(self, serializer):
        org = self.request.organisation
        label = serializer.validated_data.pop('category_label', None)
        if label is not None:
            is_income = serializer.validated_data.get('is_income', serializer.instance.is_income)
            category = self._resolve_category(label, is_income, org)
            serializer.save(category=category)
        else:
            serializer.save()
