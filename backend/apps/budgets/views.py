from django.db import transaction
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

    @staticmethod
    def _resolve_category(org, category_name):
        """Link an existing ExpenseCategory FK by case-insensitive name match
        so variance/GL-account inheritance works, without forcing the caller
        to know the category's id. Shared identity logic between add_line
        (single-line entry) and bulk_lines (monthly grid entry) so the two
        never drift apart."""
        if not category_name:
            return None
        from apps.expenses.models import ExpenseCategory
        return ExpenseCategory.objects.filter(
            organisation=org, name__iexact=category_name
        ).first()

    @action(detail=True, methods=['post'])
    def add_line(self, request, pk=None):
        budget = self.get_object()
        org = self._get_organisation()
        ser = BudgetLineSerializer(data=request.data, context={'request': request})
        ser.is_valid(raise_exception=True)
        validated = dict(ser.validated_data)
        category_name = validated.get('category_name', '')
        category = self._resolve_category(org, category_name)
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

    @action(detail=True, methods=['post'])
    def bulk_lines(self, request, pk=None):
        """Bulk upsert BudgetLine rows for the monthly grid editor (Phase 3).

        Accepts a JSON list of line payloads — same shape as add_line's body
        (category_type, category_name, account, period_month, budgeted_amount,
        etc) — either as the raw top-level list or wrapped as {"lines": [...]}.

        Identity for update-vs-create is (budget, category_name, period_month)
        — an existing line matching all three is updated in place; anything
        else is created. This mirrors add_line's category resolution
        (_resolve_category, above) rather than duplicating it.

        Every payload is validated with BudgetLineSerializer BEFORE any
        database write happens — so a validation failure anywhere in the
        batch (e.g. a foreign-org account, same guard as add_line) aborts the
        whole request with zero writes. The write loop itself is wrapped in
        one atomic transaction so an unexpected failure partway through
        (e.g. a DB-level error) rolls back every write made so far in this
        call, not just the failing one. add_line is untouched and keeps
        working exactly as before this endpoint's addition.
        """
        budget = self.get_object()
        org = self._get_organisation()
        payload = request.data
        lines_data = payload.get('lines') if isinstance(payload, dict) else payload
        if not isinstance(lines_data, list) or not lines_data:
            return Response(
                {'error': 'Expected a non-empty list of budget lines.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate every line up front — nothing is written until the whole
        # batch passes. raise_exception propagates a DRF ValidationError,
        # which DRF turns into a 400 before the write loop below ever runs.
        validated_items = []
        for item in lines_data:
            ser = BudgetLineSerializer(data=item, context={'request': request})
            ser.is_valid(raise_exception=True)
            validated = dict(ser.validated_data)
            validated.pop('category', None)  # resolved fresh below, like add_line
            validated_items.append(validated)

        created_count = 0
        updated_count = 0
        result_lines = []
        with transaction.atomic():
            for validated in validated_items:
                category_name = validated.get('category_name', '')
                period_month = validated.get('period_month')
                category = self._resolve_category(org, category_name)
                existing = BudgetLine.objects.filter(
                    organisation=org, budget=budget,
                    category_name=category_name, period_month=period_month,
                ).first()
                if existing:
                    for field, value in validated.items():
                        setattr(existing, field, value)
                    existing.category = category
                    existing.save()
                    result_lines.append(existing)
                    updated_count += 1
                else:
                    line = BudgetLine.objects.create(
                        organisation=org, budget=budget, category=category, **validated,
                    )
                    result_lines.append(line)
                    created_count += 1
            try:
                AuditLog.log(
                    action=AuditLog.UPDATE, user=request.user,
                    organisation=org,
                    model_name='Budget', object_id=str(budget.id),
                    object_repr=budget.name,
                    changes={
                        'bulk_lines': f"{created_count} line(s) created, "
                                      f"{updated_count} line(s) updated via monthly grid",
                    },
                    request=request,
                )
            except Exception:
                pass

        return Response({
            'created': created_count,
            'updated': updated_count,
            'lines': BudgetLineSerializer(result_lines, many=True).data,
        }, status=status.HTTP_200_OK)
