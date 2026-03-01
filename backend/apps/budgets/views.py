from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsManagerOrSuperuser
from .models import Budget, BudgetLine
from .serializers import BudgetSerializer, BudgetLineSerializer
from .services import BudgetService


class BudgetViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = BudgetSerializer
    permission_classes = [IsAuthenticated, IsManagerOrSuperuser]

    def get_queryset(self):
        org = self._get_organisation()
        return Budget.objects.filter(organisation=org).prefetch_related('lines__category')

    @action(detail=True, methods=['get'])
    def variance(self, request, pk=None):
        budget = self.get_object()
        data = BudgetService.get_variance_report(budget)
        return Response(data)

    @action(detail=True, methods=['post'])
    def add_line(self, request, pk=None):
        budget = self.get_object()
        org = self._get_organisation()
        ser = BudgetLineSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        validated = dict(ser.validated_data)
        # Try to link an existing ExpenseCategory FK by name so variance works
        from apps.expenses.models import ExpenseCategory
        category_name = validated.get('category_name', '')
        category = None
        if category_name:
            category = ExpenseCategory.objects.filter(
                organisation=org, name__iexact=category_name
            ).first()
        validated.pop('category', None)  # don't double-assign
        line = BudgetLine.objects.create(
            organisation=org,
            budget=budget,
            category=category,
            **validated,
        )
        return Response(BudgetLineSerializer(line).data, status=status.HTTP_201_CREATED)
