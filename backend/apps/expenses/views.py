import django_filters
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import ExportMixin, TenantFilterMixin
from apps.core.permissions import IsAccountant, IsStaff
from apps.core.permissions import requires_module
# The owner's per-person ticks, enforced server-side (H-2). Mirrors
# useModuleAccess.ts: owners and admins bypass; for everyone else no
# record means no access, and only what was granted is granted.
_ModAccess_expenses = requires_module("expenses")

from apps.core.throttles import ExemptibleUserRateThrottle, FinancialWriteThrottle

from .models import Expense, ExpenseCategory, ExpenseGroup
from .serializers import ExpenseCategorySerializer, ExpenseSerializer, ExpenseGroupSerializer
from apps.core.unique_errors import FriendlyUniqueErrorMixin


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
    permission_classes = [IsAuthenticated, IsStaff, _ModAccess_expenses]

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


class ExpenseCategoryViewSet(FriendlyUniqueErrorMixin, TenantFilterMixin, viewsets.ModelViewSet):
    unique_error_message = "An expense category with that name already exists in your organisation."
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAuthenticated, IsAccountant, _ModAccess_expenses]

    def get_queryset(self):
        # Per-row count/total as subqueries — avoids 2 queries per category (N+1).
        from django.db.models import Count, DecimalField, IntegerField, OuterRef, Subquery, Sum, Value
        from django.db.models.functions import Coalesce
        from .models import Expense

        dec = DecimalField(max_digits=15, decimal_places=2)
        count_sq = (Expense.objects.filter(category=OuterRef('pk'))
                    .values('category').annotate(c=Count('id')).values('c')[:1])
        total_sq = (Expense.objects.filter(category=OuterRef('pk'))
                    .values('category').annotate(t=Sum('amount')).values('t')[:1])
        return super().get_queryset().annotate(
            _expenses_count=Coalesce(Subquery(count_sq, output_field=IntegerField()), Value(0, output_field=IntegerField())),
            _total_amount=Coalesce(Subquery(total_sq, output_field=dec), Value(0, output_field=dec)),
        )


class ExpenseViewSet(ExportMixin, TenantFilterMixin, viewsets.ModelViewSet):
    export_filename = 'expenses'
    export_fields = [
        ('Date', 'expense_date'),
        ('Description', 'description'),
        ('Category', lambda o: o.category.name if o.category else ''),
        ('Amount', 'amount'),
        ('Previous Price', 'previous_price'),
        ('Payment Method', 'payment_method'),
        ('Type', lambda o: 'Income' if o.is_income else 'Expense'),
        ('Approved', lambda o: 'Yes' if o.is_approved else 'No'),
    ]
    queryset = Expense.objects.select_related("category", "recorded_by")
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated, IsStaff, _ModAccess_expenses]
    # Writes: 60/min. Reads: the ordinary per-user hourly allowance — listing
    # both because throttle_classes REPLACES the defaults, so naming only the
    # write throttle left reads charged against the write budget.
    throttle_classes = [FinancialWriteThrottle, ExemptibleUserRateThrottle]
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
        logger = _log.getLogger(__name__)
        # Use _get_organisation() (not self.request.organisation) so that
        # resolve_organisation() re-sets the PostgreSQL RLS GUC
        # (app.current_org_id) within the current DB transaction before any
        # INSERT.  The GUC set during the permission check is transaction-local
        # and may have expired by the time perform_create runs.
        org = self._get_organisation()

        # Strict GL mode + period lock check
        from apps.accounting.services import AccountingService, check_strict_gl_mode
        try:
            check_strict_gl_mode(org)
        except ValueError as e:
            raise serializers.ValidationError(str(e))
        expense_date = serializer.validated_data.get('expense_date')
        if expense_date and AccountingService.is_period_locked(org, expense_date, user=self.request.user):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied(f"The period {expense_date.year}-{expense_date.month:02d} is locked.")

        label = serializer.validated_data.pop('category_label', '')
        is_income = serializer.validated_data.get('is_income', False)
        try:
            category = self._resolve_category(label, is_income, org)
            expense = serializer.save(organisation=org, recorded_by=self.request.user, category=category)
        except Exception as exc:
            logger.exception("Expense create failed: %s", exc)
            raise serializers.ValidationError(f"Could not save: [{type(exc).__name__}] {exc}")
        self._write_audit('create', expense, {k: {'old': None, 'new': str(v)} for k, v in serializer.validated_data.items()})

        # Auto-post journal entry (non-blocking)
        from apps.accounting.services import safe_post_gl
        safe_post_gl(
            AccountingService.post_expense_journal, org, expense, self.request.user,
            model_instance=expense,
        )

    # What the ledger entry is built from. Anything else (description,
    # reference, attachment, group...) can change without touching the books.
    _LEDGER_FIELDS = ('amount', 'expense_date', 'category_id', 'payment_method', 'is_income')

    @staticmethod
    def _locked_message(date):
        return (f"The period {date.year}-{date.month:02d} is locked, so this expense cannot be "
                f"changed or deleted. Ask an administrator to unlock it first.")

    def perform_update(self, serializer):
        from django.core.exceptions import PermissionDenied
        from django.db import transaction
        from apps.accounting.exceptions import PeriodLockedError
        from apps.accounting.exceptions import GLAccountNotConfigured
        from apps.accounting.services import AccountingService

        org = self._get_organisation()
        label = serializer.validated_data.pop('category_label', None)
        instance = serializer.instance
        before = {f: getattr(instance, f, None) for f in serializer.validated_data}
        ledger_before = {f: getattr(instance, f) for f in self._LEDGER_FIELDS}
        old_date = instance.expense_date

        with transaction.atomic():
            if label is not None:
                is_income = serializer.validated_data.get('is_income', serializer.instance.is_income)
                category = self._resolve_category(label, is_income, org)
                serializer.save(category=category)
            else:
                serializer.save()
            expense = serializer.instance
            ledger_changed = any(getattr(expense, f) != ledger_before[f] for f in self._LEDGER_FIELDS)
            if ledger_changed:
                # The old entry is reversed (kept, never edited) and the corrected
                # expense is posted fresh, so the ledger shows the new figures and
                # nothing of the old ones. A locked month on either date blocks it,
                # and the save above rolls back with it.
                user = self.request.user
                for d in {old_date, expense.expense_date}:
                    if AccountingService.is_period_locked(org, d, user=user):
                        raise PermissionDenied(self._locked_message(d))
                # Reverse the old entry and post the corrected one as ONE unit with
                # the save above. If the new entry cannot be posted, the whole edit
                # rolls back: the old entry and the old figures stay exactly as they
                # were, rather than leaving the cost missing from the books.
                try:
                    AccountingService.reverse_expense_journal(org, expense, user)
                    AccountingService.post_expense_journal(org, expense, user)
                except PeriodLockedError:
                    raise PermissionDenied(self._locked_message(old_date))
                except GLAccountNotConfigured as exc:
                    raise serializers.ValidationError(
                        f"This change could not be recorded in your books because the "
                        f"{exc.role.replace('_', ' ')} is not set up (Settings, GL Mapping). "
                        f"Nothing was changed.")
                except Exception:
                    raise serializers.ValidationError(
                        "This change could not be recorded in your books, so nothing was changed. "
                        "Please try again or contact support.")
                expense.gl_post_status = 'posted'
                expense.gl_post_error = ''
                expense.save(update_fields=['gl_post_status', 'gl_post_error'])
        after = {f: getattr(serializer.instance, f, None) for f in before}
        changes = {f: {'old': str(before[f]), 'new': str(after[f])} for f in before if str(before[f]) != str(after[f])}
        if ledger_changed:
            changes['ledger'] = {'old': 'reversed previous entry', 'new': 'posted corrected entry'}
        self._write_audit('update', serializer.instance, changes)

    def perform_destroy(self, instance):
        """Delete = reverse the ledger entry too. A deleted expense must not keep showing as a cost."""
        from django.core.exceptions import PermissionDenied
        from django.db import transaction
        from apps.accounting.exceptions import PeriodLockedError
        from apps.accounting.services import AccountingService

        org = self._get_organisation()
        user = self.request.user
        if AccountingService.is_period_locked(org, instance.expense_date, user=user):
            raise PermissionDenied(self._locked_message(instance.expense_date))
        with transaction.atomic():
            try:
                AccountingService.reverse_expense_journal(org, instance, user)
            except PeriodLockedError:
                raise PermissionDenied(self._locked_message(instance.expense_date))
            except Exception:
                raise serializers.ValidationError(
                    "This expense could not be taken out of your books, so it was not deleted. "
                    "Please try again or contact support.")
            self._write_audit('delete', instance, {
                'amount': str(instance.amount), 'expense_date': str(instance.expense_date),
                'ledger': 'entry reversed',
            })
            instance.delete()
