from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.mixins import TenantFilterMixin
from apps.core.models import AuditLog
from apps.core.permissions import IsManagerOrSuperuser, plan_requires
from apps.core.permissions import requires_module
# The owner's per-person ticks, enforced server-side (H-2). Mirrors
# useModuleAccess.ts: owners and admins bypass; for everyone else no
# record means no access, and only what was granted is granted.
_ModAccess_budgets = requires_module("budget")


_PlanBudget = plan_requires('budget')
from .models import Budget, BudgetLine
from .serializers import BudgetSerializer, BudgetLineSerializer
from .services import BudgetService


class BudgetViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = BudgetSerializer
    permission_classes = [IsAuthenticated, IsManagerOrSuperuser, _PlanBudget, _ModAccess_budgets]

    AUDITED_FIELDS = [
        'name', 'period_type', 'status', 'notes', 'fiscal_year',
        'budget_type', 'start_date', 'end_date', 'approved_by', 'approved_at',
    ]

    def perform_update(self, serializer):
        before = {f: str(getattr(serializer.instance, f)) for f in self.AUDITED_FIELDS}
        instance = serializer.save()
        after = {f: str(getattr(instance, f)) for f in before}
        changes = {k: {'from': before[k], 'to': after[k]} for k in before if before[k] != after[k]}
        if changes:
            try:
                AuditLog.log(
                    action=AuditLog.UPDATE, user=self.request.user,
                    organisation=self._get_organisation(),
                    model_name='Budget', object_id=str(instance.id),
                    object_repr=instance.name, changes=changes, request=self.request,
                )
            except Exception:
                pass

    def get_queryset(self):
        org = self._get_organisation()
        return Budget.objects.filter(organisation=org).prefetch_related('lines__category')

    @action(detail=True, methods=['get'])
    def variance(self, request, pk=None):
        budget = self.get_object()
        data = BudgetService.get_variance_report(budget)
        return Response(data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Marks the budget approved by the current user. Permission-gated
        the same as the rest of this viewset (manager-or-above / superuser) —
        no separate approval role tier exists yet."""
        budget = self.get_object()
        before_approved_by = budget.approved_by_id
        budget.approved_by = request.user
        budget.approved_at = timezone.now()
        budget.save(update_fields=['approved_by', 'approved_at'])
        try:
            AuditLog.log(
                action=AuditLog.UPDATE, user=request.user,
                organisation=self._get_organisation(),
                model_name='Budget', object_id=str(budget.id),
                object_repr=budget.name,
                changes={
                    'approved_by': {'from': str(before_approved_by), 'to': str(request.user.id)},
                    'approved_at': {'from': '', 'to': str(budget.approved_at)},
                },
                request=request,
            )
        except Exception:
            pass
        return Response(BudgetSerializer(budget).data)

    @action(detail=False, methods=['get'])
    def monitoring(self, request):
        """Flat, cross-budget list of every line + its variance data, for the
        Budget Monitoring page. Query params: `budget_type` (operational|
        capital) and `status` (defaults to 'active'; pass 'all' to include
        every status, or a specific status to filter to just that one)."""
        org = self._get_organisation()
        budget_type = request.query_params.get('budget_type') or None
        status_param = request.query_params.get('status') or 'active'
        data = BudgetService.get_monitoring_rows(org, budget_type=budget_type, status=status_param)
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
        try:
            AuditLog.log(
                action=AuditLog.CREATE, user=request.user,
                organisation=org,
                model_name='BudgetLine', object_id=str(line.id),
                object_repr=f"{budget.name} / {line.category_name}",
                changes={'budgeted_amount': str(line.budgeted_amount)},
                request=request,
            )
        except Exception:
            pass
        return Response(BudgetLineSerializer(line).data, status=status.HTTP_201_CREATED)
