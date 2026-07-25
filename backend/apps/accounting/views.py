import re
from decimal import Decimal
from datetime import date
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsAccountant, IsOwnerOrAdmin, plan_requires

_PlanAccounting = plan_requires('accounting')
from .models import (
    Account, AccountSubType, JournalEntry, JournalLine, FixedAsset, FinancialPeriod,
    BankReconciliation, BankReconciliationLine, AIReconMatch, AccountMapping, AssetType, ACCOUNT_GROUP_SPEC,
)
from django.db import transaction
from .serializers import (
    AccountSerializer, AccountSubTypeSerializer, JournalEntrySerializer, CreateJournalEntrySerializer,
    UpdateJournalEntrySerializer, FixedAssetSerializer, FinancialPeriodSerializer,
    BankReconciliationSerializer, BankReconciliationLineSerializer,
    AIReconMatchSerializer, AccountMappingSerializer, AssetTypeSerializer, MAPPING_ROLES,
    MAPPING_ROLE_MODULES, MAPPING_ROLE_LABELS,
)
from .services import AccountingService, AccountMappingService, safe_post_gl


class AccountViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

    def get_queryset(self):
        org = self._get_organisation()
        return Account.objects.filter(organisation=org)

    def perform_destroy(self, instance):
        if instance.is_system:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("System accounts cannot be deleted")
        instance.delete()

    @action(detail=False, methods=['get'])
    def general_ledger(self, request):
        """
        GET /accounting/accounts/general_ledger/?date_from=&date_to=
        Consolidated GL: every account with a non-zero opening balance or activity in
        the range, each with its posted lines and a running balance. Powers the
        'General Ledger' report.
        """
        from django.db.models import Sum
        org = self._get_organisation()
        df = request.query_params.get('date_from')
        dt = request.query_params.get('date_to')
        date_from = date.fromisoformat(df) if df else None
        date_to = date.fromisoformat(dt) if dt else None

        accounts = Account.objects.filter(organisation=org).order_by('code')
        result = []
        for account in accounts:
            is_debit_normal = account.account_type in ['asset', 'expense', 'cogs']
            opening = Decimal('0')
            if date_from:
                pre = JournalLine.objects.filter(
                    journal_entry__organisation=org, journal_entry__status='posted',
                    account=account, journal_entry__entry_date__lt=date_from,
                ).aggregate(d=Sum('debit'), c=Sum('credit'))
                pd, pc = pre['d'] or Decimal('0'), pre['c'] or Decimal('0')
                opening = (pd - pc) if is_debit_normal else (pc - pd)

            qs = JournalLine.objects.filter(
                journal_entry__organisation=org, journal_entry__status='posted', account=account,
            ).select_related('journal_entry').order_by('journal_entry__entry_date', 'journal_entry__created_at')
            if date_from:
                qs = qs.filter(journal_entry__entry_date__gte=date_from)
            if date_to:
                qs = qs.filter(journal_entry__entry_date__lte=date_to)

            running = opening
            lines = []
            for line in qs:
                delta = (line.debit - line.credit) if is_debit_normal else (line.credit - line.debit)
                running += delta
                lines.append({
                    'date': line.journal_entry.entry_date,
                    'reference': line.journal_entry.reference,
                    'description': line.description or line.journal_entry.description,
                    'debit': line.debit, 'credit': line.credit, 'balance': running,
                })
            if opening == 0 and not lines:
                continue  # skip dormant accounts
            result.append({
                'code': account.code, 'name': account.name, 'account_type': account.account_type,
                'opening_balance': opening, 'closing_balance': running, 'lines': lines,
            })
        return Response({'accounts': result, 'date_from': df, 'date_to': dt})

    @action(detail=False, methods=['post'])
    def opening_balances(self, request):
        """
        POST /accounting/accounts/opening_balances/
        Body: { "as_of_date": "YYYY-MM-DD",
                "entries": [ { "account": "<uuid>", "amount": "10000", "side": "debit" }, ... ] }

        Posts one balanced take-on journal, plugging the difference to Take-On
        Suspense (3900). Re-posting for the same date reverses the prior take-on.
        """
        org = self._get_organisation()
        as_of_str = request.data.get('as_of_date')
        if not as_of_str:
            return Response({'error': 'as_of_date is required'}, status=400)
        try:
            as_of = date.fromisoformat(as_of_str)
        except (ValueError, TypeError):
            return Response({'error': 'as_of_date must be YYYY-MM-DD'}, status=400)

        raw_entries = request.data.get('entries') or []
        entries = []
        for item in raw_entries:
            acct_id = item.get('account')
            if not acct_id:
                continue
            try:
                acct = Account.objects.get(id=acct_id, organisation=org)
            except Account.DoesNotExist:
                return Response({'error': f'Account {acct_id} not found'}, status=400)
            entries.append({
                'account': acct,
                'amount': item.get('amount', 0),
                'side': item.get('side'),
            })
        if not entries:
            return Response({'error': 'At least one opening balance entry is required'}, status=400)

        try:
            entry = AccountingService.set_opening_balances(org, as_of, entries, created_by=request.user)
        except Exception as e:
            return Response({'error': f'[{type(e).__name__}] {e}'}, status=422)
        if entry is None:
            return Response({'error': 'No non-zero opening balances provided'}, status=400)
        return Response(JournalEntrySerializer(entry).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def set_opening_balance(self, request, pk=None):
        """Post/replace a single account's opening balance (account-form Option 1)."""
        account = self.get_object()
        org = self._get_organisation()
        as_of_str = request.data.get('as_of_date')
        try:
            as_of = date.fromisoformat(as_of_str) if as_of_str else date.today()
        except (ValueError, TypeError):
            return Response({'error': 'as_of_date must be YYYY-MM-DD'}, status=400)
        try:
            AccountingService.set_account_opening_balance(
                org, account, request.data.get('amount', 0),
                request.data.get('side'), as_of, created_by=request.user,
            )
        except Exception as e:
            return Response({'error': f'[{type(e).__name__}] {e}'}, status=422)
        return Response(AccountSerializer(account).data)

    @action(detail=False, methods=['post'])
    def subledger_opening_balances(self, request):
        """
        POST /accounting/accounts/subledger_opening_balances/
        Body: { as_of_date, customers:[{id,amount}], suppliers:[{id,amount}],
                items:[{product_id, warehouse_id?, quantity, unit_cost?}] }
        """
        org = self._get_organisation()
        as_of_str = request.data.get('as_of_date')
        try:
            as_of = date.fromisoformat(as_of_str) if as_of_str else date.today()
        except (ValueError, TypeError):
            return Response({'error': 'as_of_date must be YYYY-MM-DD'}, status=400)
        try:
            entry = AccountingService.set_subledger_opening_balances(
                org, as_of,
                customers=request.data.get('customers'),
                suppliers=request.data.get('suppliers'),
                items=request.data.get('items'),
                created_by=request.user,
            )
        except Exception as e:
            return Response({'error': f'[{type(e).__name__}] {e}'}, status=422)
        if entry is None:
            return Response({'error': 'No non-zero sub-ledger opening balances provided'}, status=400)
        return Response(JournalEntrySerializer(entry).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def taxonomy(self, request):
        """Return the account-type headers, their statement + base type and the
        org's active sub-types, so the COA form can drive dependent dropdowns."""
        org = self._get_organisation()
        subs = AccountSubType.objects.filter(organisation=org, is_active=True)
        by_group = {}
        for s in subs:
            by_group.setdefault(s.account_group, []).append(
                {'id': str(s.id), 'name': s.name, 'base_account_type': s.base_account_type}
            )
        groups = []
        for group, (base_type, statement, _names) in ACCOUNT_GROUP_SPEC.items():
            groups.append({
                'group': group,
                'statement': statement,   # 'pl' or 'bs'
                'base_account_type': base_type,
                'sub_types': by_group.get(group, []),
            })
        return Response({'groups': groups})

    @action(detail=False, methods=['get'])
    def trial_balance(self, request):
        org = self._get_organisation()
        as_of = None
        as_of_str = request.query_params.get('as_of')
        if as_of_str:
            try:
                from datetime import date
                as_of = date.fromisoformat(as_of_str)
            except ValueError:
                pass
        data = AccountingService.trial_balance(org, as_of=as_of)
        return Response(data)

    @action(detail=False, methods=['get'])
    def balance_sheet(self, request):
        org = self._get_organisation()
        as_of = None
        as_of_str = request.query_params.get('as_of')
        if as_of_str:
            try:
                from datetime import date
                as_of = date.fromisoformat(as_of_str)
            except ValueError:
                pass
        data = AccountingService.balance_sheet(org, as_of=as_of)
        return Response(data)

    @action(detail=False, methods=['post'])
    def seed(self, request):
        org = self._get_organisation()
        AccountingService.seed_chart_of_accounts(org)
        return Response({'message': 'Chart of accounts seeded successfully'})

    @action(detail=True, methods=['get'])
    def ledger(self, request, pk=None):
        """
        GET /accounting/accounts/{id}/ledger/?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD

        Returns posted journal lines for this account with a running balance.
        If date_from is provided, also computes an opening balance for lines before that date.
        For the inventory account (code 1200), includes the actual stock valuation.
        """
        from django.db.models import Sum
        from datetime import datetime

        account = self.get_object()
        org = self._get_organisation()
        is_debit_normal = account.account_type in ['asset', 'expense', 'cogs']

        date_from_str = request.query_params.get('date_from')
        date_to_str   = request.query_params.get('date_to')
        date_from = None
        date_to   = None
        if date_from_str:
            try:
                date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        if date_to_str:
            try:
                date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        # Opening balance: all posted lines before date_from
        if date_from:
            pre_qs = JournalLine.objects.filter(
                journal_entry__organisation=org,
                journal_entry__status='posted',
                account=account,
                journal_entry__entry_date__lt=date_from,
            )
            pre_d = pre_qs.aggregate(t=Sum('debit'))['t']  or Decimal('0')
            pre_c = pre_qs.aggregate(t=Sum('credit'))['t'] or Decimal('0')
            opening = (pre_d - pre_c) if is_debit_normal else (pre_c - pre_d)
        else:
            opening = Decimal('0')

        # Lines in range
        qs = JournalLine.objects.filter(
            journal_entry__organisation=org,
            journal_entry__status='posted',
            account=account,
        ).select_related('journal_entry', 'journal_entry__created_by').order_by(
            'journal_entry__entry_date', 'journal_entry__created_at'
        )
        if date_from:
            qs = qs.filter(journal_entry__entry_date__gte=date_from)
        if date_to:
            qs = qs.filter(journal_entry__entry_date__lte=date_to)

        running = opening
        lines = []
        for line in qs:
            delta = (line.debit - line.credit) if is_debit_normal else (line.credit - line.debit)
            running += delta
            lines.append({
                'id': str(line.id),
                'date': line.journal_entry.entry_date,
                'reference': line.journal_entry.reference,
                'description': line.description or line.journal_entry.description,
                'debit': line.debit,
                'credit': line.credit,
                'balance': running,
            })

        # Inventory account: include actual stock valuation as comparison
        inventory_value = None
        if account.code == '1200':
            from apps.reports.services import ReportService
            inv = ReportService.inventory_valuation(org)
            inventory_value = inv['total_inventory_value']

        return Response({
            'account': {
                'id': str(account.id),
                'code': account.code,
                'name': account.name,
                'account_type': account.account_type,
            },
            'opening_balance': opening,
            'closing_balance': running,
            'inventory_value': inventory_value,
            'lines': lines,
        })


class AccountSubTypeViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """CRUD for the 'Add Sub Account Type' management screen."""
    serializer_class = AccountSubTypeSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

    def get_queryset(self):
        org = self._get_organisation()
        qs = AccountSubType.objects.filter(organisation=org)
        group = self.request.query_params.get('account_group')
        if group:
            qs = qs.filter(account_group=group)
        return qs

    def perform_create(self, serializer):
        serializer.save(organisation=self._get_organisation())

    def perform_destroy(self, instance):
        if instance.is_system:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("System sub-types cannot be deleted; deactivate instead.")
        if instance.accounts.exists():
            from rest_framework.exceptions import ValidationError as DRFValidationError
            raise DRFValidationError("Sub-type is in use by accounts; deactivate instead of deleting.")
        instance.delete()


class JournalEntryViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = JournalEntrySerializer
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

    def get_queryset(self):
        org = self._get_organisation()
        qs = JournalEntry.objects.filter(organisation=org).prefetch_related('lines__account')
        params = self.request.query_params
        df, dt = params.get('date_from'), params.get('date_to')
        if df:
            try:
                qs = qs.filter(entry_date__gte=date.fromisoformat(df))
            except ValueError:
                pass
        if dt:
            try:
                qs = qs.filter(entry_date__lte=date.fromisoformat(dt))
            except ValueError:
                pass
        st = params.get('status')
        if st:
            qs = qs.filter(status=st)
        appr = params.get('approval_status')
        if appr:
            qs = qs.filter(approval_status=appr)
        return qs.order_by('-entry_date', '-created_at')

    def _build_lines(self, org, lines_data):
        """Validate balance and return JournalLine instances (unsaved)."""
        total_debit = sum(Decimal(str(l.get('debit', '0'))) for l in lines_data)
        total_credit = sum(Decimal(str(l.get('credit', '0'))) for l in lines_data)
        if abs(total_debit - total_credit) > Decimal('0.01'):
            raise ValueError(f'Journal entry not balanced: debits={total_debit}, credits={total_credit}')
        instances = []
        for line in lines_data:
            acct = Account.objects.get(id=line['account'], organisation=org)
            # Control-account lock: block DIRECT manual/import posting to accounts
            # flagged allow_posting=False (AR/AP/Inventory control). System
            # auto-posting goes through AccountingService.post_journal_entry and is
            # NOT affected by this path, so sales/bills keep posting normally.
            if not acct.allow_posting:
                raise ValueError(
                    f"Account {acct.code} — {acct.name} is a control account and does not "
                    f"accept direct journal entries. Post to its sub-ledger instead."
                )
            instances.append(JournalLine(
                account=acct,
                debit=Decimal(str(line.get('debit', '0'))),
                credit=Decimal(str(line.get('credit', '0'))),
                description=line.get('description', ''),
            ))
        return instances

    def create(self, request, *args, **kwargs):
        org = self._get_organisation()
        ser = CreateJournalEntrySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            line_instances = self._build_lines(org, d['lines'])
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Account.DoesNotExist:
            return Response({'error': 'One or more accounts not found'}, status=400)

        with transaction.atomic():
            entry = JournalEntry.objects.create(
                organisation=org,
                description=d['description'],
                entry_date=d['entry_date'],
                created_by=request.user,
            )
            for li in line_instances:
                li.journal_entry = entry
                li.save()
        return Response(JournalEntrySerializer(entry).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        entry = self.get_object()
        if entry.status == JournalEntry.POSTED:
            return Response({'error': 'Posted entries cannot be edited. Create a reversing entry instead.'}, status=400)

        ser = UpdateJournalEntrySerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        org = self._get_organisation()

        with transaction.atomic():
            if 'description' in d:
                entry.description = d['description']
            if 'entry_date' in d:
                entry.entry_date = d['entry_date']
            if 'lines' in d:
                try:
                    line_instances = self._build_lines(org, d['lines'])
                except ValueError as e:
                    return Response({'error': str(e)}, status=400)
                except Account.DoesNotExist:
                    return Response({'error': 'One or more accounts not found'}, status=400)
                entry.lines.all().delete()
                for li in line_instances:
                    li.journal_entry = entry
                    li.save()
            entry.save()

        entry.refresh_from_db()
        return Response(JournalEntrySerializer(entry).data)

    def destroy(self, request, *args, **kwargs):
        entry = self.get_object()
        if entry.status == JournalEntry.POSTED:
            return Response({'error': 'Posted entries cannot be deleted. Use the Reverse action instead.'}, status=400)
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def post_entry(self, request, pk=None):
        entry = self.get_object()
        if entry.status == JournalEntry.POSTED:
            return Response({'error': 'Already posted'}, status=400)
        entry.status = JournalEntry.POSTED
        entry.posted_by = request.user
        entry.save()
        return Response(JournalEntrySerializer(entry).data)

    @action(detail=True, methods=['post'])
    def reverse(self, request, pk=None):
        """
        Create a reversing journal entry (all DR/CR flipped) as a draft.
        The accountant reviews and posts it to cancel the original posting.
        Standard accounting practice — never deletes a posted entry.
        """
        original = self.get_object()
        if original.status != JournalEntry.POSTED:
            return Response({'error': 'Only posted entries can be reversed.'}, status=400)

        org = self._get_organisation()
        reversal_date = request.data.get('reversal_date', original.entry_date)

        def _safe_desc(text, max_len=200):
            """Strip CSV-injection lead chars and cap length."""
            cleaned = re.sub(r'^[=+\-@\t\r]+', '', (text or '').strip())
            return cleaned[:max_len]

        with transaction.atomic():
            reversal = JournalEntry.objects.create(
                organisation=org,
                description=f'Reversal of {original.reference}: {_safe_desc(original.description)}',
                entry_date=reversal_date,
                created_by=request.user,
                status=JournalEntry.DRAFT,
            )
            for line in original.lines.all():
                JournalLine.objects.create(
                    journal_entry=reversal,
                    account=line.account,
                    debit=line.credit,   # flip
                    credit=line.debit,   # flip
                    description=f'Reversal: {_safe_desc(line.description)}' if line.description else 'Reversal',
                )

        return Response(JournalEntrySerializer(reversal).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def import_entries(self, request):
        """
        Bulk-import draft journal entries.
        Body: { "entries": [ { "description", "entry_date",
                               "lines": [ {"account", "debit", "credit", "description"} ] } ] }
        Each entry is validated (balanced, no control accounts) and created as a
        DRAFT for review — never auto-posted. Returns per-row results.
        """
        org = self._get_organisation()
        rows = request.data.get('entries') or []
        if not rows:
            return Response({'error': 'No entries provided'}, status=400)
        created, errors = [], []
        for idx, row in enumerate(rows):
            lines = row.get('lines') or []
            if len(lines) < 2:
                errors.append({'row': idx, 'error': 'At least two lines required'})
                continue
            try:
                line_instances = self._build_lines(org, lines)
            except ValueError as e:
                errors.append({'row': idx, 'error': str(e)})
                continue
            except Account.DoesNotExist:
                errors.append({'row': idx, 'error': 'One or more accounts not found'})
                continue
            try:
                with transaction.atomic():
                    entry = JournalEntry.objects.create(
                        organisation=org,
                        description=row.get('description', 'Imported entry'),
                        entry_date=row.get('entry_date') or date.today(),
                        created_by=request.user,
                    )
                    for li in line_instances:
                        li.journal_entry = entry
                        li.save()
                created.append(str(entry.id))
            except Exception as e:
                errors.append({'row': idx, 'error': f'[{type(e).__name__}] {e}'})
        return Response(
            {'created': len(created), 'created_ids': created, 'errors': errors},
            status=status.HTTP_201_CREATED if created else 400,
        )

    @action(detail=True, methods=['post'])
    def submit_for_approval(self, request, pk=None):
        entry = self.get_object()
        if entry.status == JournalEntry.POSTED:
            return Response({'error': 'Posted entries need no approval.'}, status=400)
        entry.approval_status = JournalEntry.PENDING
        entry.save(update_fields=['approval_status'])
        return Response(JournalEntrySerializer(entry).data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve a pending journal and (optionally) post it in one step."""
        entry = self.get_object()
        entry.approval_status = JournalEntry.APPROVED
        entry.approved_by = request.user
        entry.approved_at = timezone.now()
        entry.approval_note = request.data.get('note', '')
        entry.save(update_fields=['approval_status', 'approved_by', 'approved_at', 'approval_note'])
        if request.data.get('post') and entry.status != JournalEntry.POSTED:
            entry.status = JournalEntry.POSTED
            entry.posted_by = request.user
            entry.save(update_fields=['status', 'posted_by'])
        return Response(JournalEntrySerializer(entry).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        entry = self.get_object()
        if entry.status == JournalEntry.POSTED:
            return Response({'error': 'Posted entries cannot be rejected. Reverse instead.'}, status=400)
        entry.approval_status = JournalEntry.REJECTED
        entry.approved_by = request.user
        entry.approved_at = timezone.now()
        entry.approval_note = request.data.get('note', '')
        entry.save(update_fields=['approval_status', 'approved_by', 'approved_at', 'approval_note'])
        return Response(JournalEntrySerializer(entry).data)

    @action(detail=True, methods=['post'])
    def sign(self, request, pk=None):
        """Attach an e-signature (typed name or data-URI) and/or a document upload."""
        entry = self.get_object()
        signature = request.data.get('signature', '')
        if signature:
            entry.signature = signature
            entry.signed_by = request.user
            entry.signed_at = timezone.now()
        if 'attachment' in request.FILES:
            entry.attachment = request.FILES['attachment']
        entry.save(update_fields=['signature', 'signed_by', 'signed_at', 'attachment'])
        return Response(JournalEntrySerializer(entry).data)


class AssetTypeViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """CRUD for asset types (default depreciation settings + GL account mapping)."""
    serializer_class = AssetTypeSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

    def get_queryset(self):
        return AssetType.objects.filter(organisation=self._get_organisation())


class FixedAssetViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = FixedAssetSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

    def get_queryset(self):
        org = self._get_organisation()
        return FixedAsset.objects.filter(organisation=org).select_related('asset_type').prefetch_related('depreciation_entries')

    def perform_create(self, serializer):
        """Create the asset (organisation injected by the mixin) AND post its GL entry.

        - Purchase (default): DR 1500 Fixed Assets / CR funding (Bank/Cash/AP/Equity).
        - Take-on (capitalisation_source='opening_balance' or funding_source='none'):
          DR 1500 / CR 1510 accumulated dep / CR 3900 NBV, seeding depreciation
          history. Pass `opening_accumulated_depreciation` for dep-to-date.

        Posting failure is non-fatal and recorded on the asset (acquisition_error)."""
        org = getattr(self.request, 'organisation', None) or self._get_organisation()
        from .services import CapitalisationService
        # Auto-generate the asset code when the user leaves it blank ("auto if blank").
        if not (serializer.validated_data.get('asset_code') or '').strip():
            serializer.validated_data['asset_code'] = CapitalisationService._next_asset_code(org)
        super().perform_create(serializer)  # injects organisation + writes audit
        asset = serializer.instance
        is_takeon = (
            asset.capitalisation_source == FixedAsset.CAP_OPENING
            or asset.funding_source == FixedAsset.FUND_NONE
        )
        try:
            if is_takeon:
                CapitalisationService.set_asset_opening_balance(
                    org, asset,
                    accumulated_depreciation=self.request.data.get('opening_accumulated_depreciation', 0),
                    created_by=self.request.user,
                )
            else:
                CapitalisationService.post_acquisition(
                    org, asset, funding_source=asset.funding_source, created_by=self.request.user,
                )
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Asset GL posting failed for %s", asset.asset_code, exc_info=True
            )

    @action(detail=False, methods=['get'])
    def reconciliation(self, request):
        """GET /accounting/assets/reconciliation/?as_of=YYYY-MM-DD
        Prove the register ties to the GL (cost/accum-dep/NBV vs 1500/1510), with the
        Take-On Suspense decomposition and any assets whose acquisition never posted."""
        org = self._get_organisation()
        as_of = None
        as_of_str = request.query_params.get('as_of')
        if as_of_str:
            try:
                as_of = date.fromisoformat(as_of_str)
            except ValueError:
                pass
        from .services import CapitalisationService
        return Response(CapitalisationService.gl_reconciliation(org, as_of=as_of))

    @action(detail=True, methods=['post'])
    def dispose(self, request, pk=None):
        """POST /accounting/assets/{id}/dispose/  Body: {proceeds, disposal_date, proceeds_funding}
        Derecognise the asset and post the gain/loss on disposal."""
        asset = self.get_object()
        org = self._get_organisation()
        from .services import CapitalisationService
        try:
            result = CapitalisationService.dispose_asset(
                org, asset,
                proceeds=request.data.get('proceeds', 0),
                disposal_date=request.data.get('disposal_date'),
                proceeds_funding=request.data.get('proceeds_funding', 'bank'),
                created_by=request.user,
            )
        except Exception as e:
            return Response({'error': f'[{type(e).__name__}] {e}'}, status=422)
        if result is None:
            return Response({'error': 'Asset is already disposed.'}, status=400)
        return Response({
            'message': 'Asset disposed.',
            'gain_loss': result['gain_loss'],
            'net_book_value': result['net_book_value'],
            'proceeds': result['proceeds'],
            'asset': FixedAssetSerializer(asset).data,
        })

    @action(detail=False, methods=['get'])
    def disposal_report(self, request):
        """GET /accounting/assets/disposal_report/?date_from=&date_to="""
        org = self._get_organisation()
        df = request.query_params.get('date_from')
        dt = request.query_params.get('date_to')
        date_from = date.fromisoformat(df) if df else None
        date_to = date.fromisoformat(dt) if dt else None
        from .services import CapitalisationService
        return Response(CapitalisationService.disposal_report(org, date_from=date_from, date_to=date_to))

    @action(detail=True, methods=['post'])
    def transfer(self, request, pk=None):
        """POST /accounting/assets/{id}/transfer/  Body: {to_location, to_cost_centre, to_asset_type, transfer_date, reference, notes}"""
        asset = self.get_object()
        org = self._get_organisation()
        to_location = None
        loc_id = request.data.get('to_location')
        if loc_id:
            from apps.inventory.models import Warehouse
            to_location = Warehouse.objects.filter(organisation=org, id=loc_id).first()
            if not to_location:
                return Response({'error': 'Destination location not found'}, status=400)
        to_asset_type = None
        at_id = request.data.get('to_asset_type')
        if at_id:
            from .models import AssetType
            to_asset_type = AssetType.objects.filter(organisation=org, id=at_id).first()
            if not to_asset_type:
                return Response({'error': 'Destination asset type not found'}, status=400)
        from .services import CapitalisationService
        CapitalisationService.transfer_asset(
            org, asset, to_location=to_location,
            to_cost_centre=request.data.get('to_cost_centre'),
            to_asset_type=to_asset_type,
            transfer_date=request.data.get('transfer_date'),
            reference=request.data.get('reference', ''), notes=request.data.get('notes', ''),
            created_by=request.user,
        )
        return Response(FixedAssetSerializer(asset).data)

    @action(detail=True, methods=['post'])
    def record_usage(self, request, pk=None):
        """POST /accounting/assets/{id}/record_usage/  Body: {year, month, units}
        Units-of-Production depreciation for a period from recorded usage."""
        asset = self.get_object()
        org = self._get_organisation()
        today = date.today()
        try:
            year = int(request.data.get('year', today.year))
            month = int(request.data.get('month', today.month))
            units = request.data.get('units')
        except (TypeError, ValueError):
            return Response({'error': 'year, month and units are required'}, status=400)
        from .services import AccountingService
        try:
            entry = AccountingService.record_usage_depreciation(
                org, asset, year, month, units, created_by=request.user
            )
        except Exception as e:
            return Response({'error': f'{e}'}, status=422)
        return Response({
            'message': f'Recorded {units} units for {year}-{month:02d}.',
            'depreciation_amount': entry.depreciation_amount,
            'asset': FixedAssetSerializer(asset).data,
        })

    @action(detail=True, methods=['post'])
    def revalue(self, request, pk=None):
        """POST /accounting/assets/{id}/revalue/  Body: {new_value, revaluation_date, reference, notes}
        Gated behind the org's fixed_asset_revaluation_enabled flag."""
        asset = self.get_object()
        org = self._get_organisation()
        from .services import CapitalisationService
        try:
            result = CapitalisationService.revalue_asset(
                org, asset, new_value=request.data.get('new_value'),
                revaluation_date=request.data.get('revaluation_date'),
                reference=request.data.get('reference', ''), notes=request.data.get('notes', ''),
                created_by=request.user,
            )
        except Exception as e:
            return Response({'error': f'[{type(e).__name__}] {e}'}, status=422)
        return Response({
            'message': 'Asset revalued.', 'surplus': result['surplus'],
            'new_carrying_amount': result['new_carrying_amount'],
            'asset': FixedAssetSerializer(asset).data,
        })

    @action(detail=False, methods=['get'])
    def register_report(self, request):
        from .services import CapitalisationService
        return Response(CapitalisationService.asset_register_report(self._get_organisation()))

    @action(detail=False, methods=['get'])
    def by_category(self, request):
        from .services import CapitalisationService
        return Response(CapitalisationService.assets_by_category(self._get_organisation()))

    @action(detail=False, methods=['get'])
    def by_location(self, request):
        from .services import CapitalisationService
        return Response(CapitalisationService.assets_by_location(self._get_organisation()))

    @action(detail=False, methods=['get'])
    def transfer_report(self, request):
        org = self._get_organisation()
        df = request.query_params.get('date_from')
        dt = request.query_params.get('date_to')
        from .services import CapitalisationService
        return Response(CapitalisationService.transfer_report(
            org,
            date_from=date.fromisoformat(df) if df else None,
            date_to=date.fromisoformat(dt) if dt else None,
        ))

    @action(detail=True, methods=['get'])
    def depreciation_schedule(self, request, pk=None):
        """GET /accounting/assets/{id}/depreciation_schedule/?forecast=true"""
        asset = self.get_object()
        forecast = request.query_params.get('forecast', '').lower() in ('1', 'true', 'yes')
        from .services import CapitalisationService
        return Response(CapitalisationService.depreciation_schedule(
            self._get_organisation(), asset, forecast=forecast))

    @action(detail=False, methods=['post'])
    def run_depreciation(self, request):
        org = self._get_organisation()
        today = date.today()
        year = int(request.data.get('year', today.year))
        month = int(request.data.get('month', today.month))
        catch_up = bool(request.data.get('catch_up'))
        draft = bool(request.data.get('draft'))
        if catch_up:
            entries = AccountingService.run_depreciation_catch_up(org, year, month, created_by=request.user, draft=draft)
        else:
            entries = AccountingService.run_depreciation(org, year, month, created_by=request.user, draft=draft)
        already_run = len(entries) == 0 and not catch_up
        mode = 'draft batch' if draft else 'posted'
        if already_run:
            message = f'Depreciation for {year}-{month:02d} has already been run (or no assets are due).'
        elif catch_up:
            message = f'Ran catch-up depreciation up to {year}-{month:02d} ({mode}): {len(entries)} entries.'
        else:
            message = f'Ran depreciation for {year}-{month:02d} ({mode}): {len(entries)} entries.'
        return Response({
            'message': message,
            'entries_created': len(entries),
            'already_run': already_run,
            'draft': draft,
        })

    @action(detail=False, methods=['post'])
    def post_depreciation_batch(self, request):
        """POST /accounting/assets/post_depreciation_batch/  Body: {year, month}
        Post (approve) all draft depreciation journals for the period."""
        org = self._get_organisation()
        today = date.today()
        year = int(request.data.get('year', today.year))
        month = int(request.data.get('month', today.month))
        count = AccountingService.post_depreciation_drafts(org, year, month, request.user)
        return Response({
            'posted': count,
            'message': f'Posted {count} draft depreciation entr{"y" if count == 1 else "ies"} for {year}-{month:02d}.',
        })


class FinancialPeriodViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = FinancialPeriodSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

    def get_queryset(self):
        org = self._get_organisation()
        return FinancialPeriod.objects.filter(organisation=org)

    def create(self, request, *args, **kwargs):
        from django.db import IntegrityError
        org = self._get_organisation()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            period = serializer.save(organisation=org)
        except IntegrityError:
            # Period for this month already exists — return it instead of erroring
            year = serializer.validated_data.get('year')
            month = serializer.validated_data.get('month')
            period = FinancialPeriod.objects.get(organisation=org, year=year, month=month)
        return Response(FinancialPeriodSerializer(period).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsOwnerOrAdmin, _PlanAccounting])
    def lock(self, request, pk=None):
        from django.utils import timezone as tz
        period = self.get_object()
        if period.is_locked:
            return Response({'error': 'Period is already locked'}, status=400)
        period.is_locked = True
        period.locked_by = request.user
        period.locked_at = tz.now()
        period.save()
        self._audit(request, period, 'LOCK', f"Locked period {period.year}-{period.month:02d}")
        return Response(FinancialPeriodSerializer(period).data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsOwnerOrAdmin, _PlanAccounting])
    def unlock(self, request, pk=None):
        from django.utils import timezone as tz
        period = self.get_object()
        # Unlocking a closed period is an audit-sensitive action — require a reason,
        # keep the original lock evidence, and record who unlocked + why. Only an
        # already-locked period can be unlocked.
        if not period.is_locked:
            return Response({'error': 'Period is not locked'}, status=400)
        reason = (request.data.get('reason') or '').strip()
        if not reason:
            return Response({'error': 'A reason is required to unlock a closed period.'}, status=400)
        period.is_locked = False
        period.unlocked_by = request.user
        period.unlocked_at = tz.now()
        period.unlock_reason = reason
        # Deliberately keep locked_by / locked_at so the lock history survives.
        period.save()
        self._audit(request, period, 'UNLOCK',
                    f"Unlocked period {period.year}-{period.month:02d} — reason: {reason}")
        return Response(FinancialPeriodSerializer(period).data)

    def _audit(self, request, period, event, message):
        """Write an immutable audit-log entry for a lock/unlock event."""
        try:
            from apps.core.models import AuditLog
            AuditLog.log(
                action=AuditLog.UPDATE,
                user=request.user,
                organisation=period.organisation,
                model_name='FinancialPeriod',
                object_id=str(period.id),
                object_repr=str(period),
                changes={'event': f'period_{event.lower()}', 'note': message},
                request=request,
                is_owner_action=True,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to write period %s audit log", event, exc_info=True)


class BankReconciliationViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = BankReconciliationSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

    def get_queryset(self):
        org = self._get_organisation()
        return BankReconciliation.objects.filter(organisation=org).prefetch_related('lines')

    def create(self, request, *args, **kwargs):
        """Start a reconciliation. If one already exists for this account + period,
        resume it (return it) instead of erroring with a unique-constraint 500."""
        from django.db import IntegrityError, transaction as _txn
        org = self._get_organisation()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with _txn.atomic():
                recon = serializer.save(organisation=org)
        except IntegrityError:
            v = serializer.validated_data
            acct = v.get('account')
            existing = BankReconciliation.objects.filter(
                organisation=org, account=acct,
                period_start=v.get('period_start'), period_end=v.get('period_end'),
            ).first()
            if existing:
                return Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)
            return Response(
                {'error': 'A reconciliation for this account and period already exists.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(self.get_serializer(recon).data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        org = self._get_organisation()
        serializer.save(organisation=org)

    @action(detail=True, methods=['post'])
    def mark_reconciled(self, request, pk=None):
        from django.utils import timezone as tz
        recon = self.get_object()
        if recon.is_reconciled:
            return Response({'error': 'Already reconciled'}, status=400)
        recon.is_reconciled = True
        recon.reconciled_by = request.user
        recon.reconciled_at = tz.now()
        recon.save()
        return Response(BankReconciliationSerializer(recon).data)

    @action(detail=True, methods=['post'])
    def add_line(self, request, pk=None):
        recon = self.get_object()
        ser = BankReconciliationLineSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        line = ser.save(organisation=recon.organisation, reconciliation=recon)
        return Response(BankReconciliationLineSerializer(line).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch'])
    def update_line(self, request, pk=None):
        recon = self.get_object()
        line_id = request.data.get('line_id')
        try:
            line = recon.lines.get(id=line_id)
        except BankReconciliationLine.DoesNotExist:
            return Response({'error': 'Line not found'}, status=404)
        line.is_cleared = request.data.get('is_cleared', line.is_cleared)
        line.save(update_fields=['is_cleared'])
        return Response(BankReconciliationLineSerializer(line).data)

    @action(detail=True, methods=['post'], url_path='import_statement')
    def import_statement(self, request, pk=None):
        """
        POST /accounting/reconciliations/{id}/import_statement/
        Accepts a CSV file with columns: date, description, debit, credit
        (or a single 'amount' column — positive = credit, negative = debit).
        Creates one BankReconciliationLine per row.
        """
        import csv, io
        recon = self.get_object()
        csv_file = request.FILES.get('file')
        if not csv_file:
            return Response({'error': 'No file provided. Upload a CSV file.'}, status=400)

        # Enforce file size limit (max 5 MB) to prevent DoS via large uploads
        MAX_CSV_BYTES = 5 * 1024 * 1024
        if csv_file.size > MAX_CSV_BYTES:
            return Response({'error': 'File too large. Maximum size is 5 MB.'}, status=400)

        # Enforce .csv extension (basic MIME guard)
        if not csv_file.name.lower().endswith('.csv'):
            return Response({'error': 'Only .csv files are accepted.'}, status=400)

        try:
            text = csv_file.read().decode('utf-8-sig')  # utf-8-sig strips BOM
        except UnicodeDecodeError:
            return Response({'error': 'File encoding not supported. Please save as UTF-8.'}, status=400)

        reader = csv.DictReader(io.StringIO(text))
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]

        # Normalise header names (accept variations)
        def _col(row, *keys):
            for k in keys:
                for h in headers:
                    if h == k:
                        return row.get(h, '').strip()
            return ''

        lines_created = []
        errors = []
        for i, row in enumerate(reader, start=2):  # row 1 is header
            row_lower = {k.strip().lower(): v.strip() for k, v in row.items()}
            try:
                from decimal import Decimal
                date_str = _col(row_lower, 'date', 'transaction date', 'txn date', 'value date')
                description = _col(row_lower, 'description', 'narration', 'details', 'remarks', 'memo')

                debit_str = _col(row_lower, 'debit', 'dr', 'withdrawal', 'charge')
                credit_str = _col(row_lower, 'credit', 'cr', 'deposit', 'payment')
                amount_str = _col(row_lower, 'amount', 'value')

                if not date_str:
                    continue  # skip blank rows

                _MAX_AMOUNT = Decimal('999999999.99')

                if amount_str and not debit_str and not credit_str:
                    amt = Decimal(amount_str.replace(',', '')).quantize(Decimal('0.01'))
                    if abs(amt) > _MAX_AMOUNT:
                        errors.append(f"Row {i}: amount exceeds maximum allowed value")
                        continue
                    debit = -amt if amt < 0 else Decimal('0')
                    credit = amt if amt >= 0 else Decimal('0')
                else:
                    debit = Decimal(debit_str.replace(',', '') or '0').quantize(Decimal('0.01'))
                    credit = Decimal(credit_str.replace(',', '') or '0').quantize(Decimal('0.01'))
                    if debit > _MAX_AMOUNT or credit > _MAX_AMOUNT:
                        errors.append(f"Row {i}: amount exceeds maximum allowed value")
                        continue

                from datetime import datetime
                for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%d %b %Y'):
                    try:
                        txn_date = datetime.strptime(date_str, fmt).date()
                        break
                    except ValueError:
                        continue
                else:
                    errors.append(f"Row {i}: unrecognised date format '{date_str}'")
                    continue

                # Signed amount: credit (inflow) = positive, debit (outflow) = negative
                signed_amount = credit - debit
                line = BankReconciliationLine.objects.create(
                    organisation=recon.organisation,
                    reconciliation=recon,
                    transaction_date=txn_date,
                    description=description or 'Imported transaction',
                    amount=signed_amount,
                    is_cleared=False,
                )
                lines_created.append(line)
            except Exception as e:
                errors.append(f"Row {i}: {e}")

        return Response({
            'lines_created': len(lines_created),
            'errors': errors,
            'lines': BankReconciliationLineSerializer(lines_created, many=True).data,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='auto_match')
    def auto_match(self, request, pk=None):
        """
        POST /accounting/reconciliations/{id}/auto_match/
        Deterministic exact-match pass — instant, offline, auditable. Matches bank
        lines to book entries on exact amount + date tolerance (+ reference), auto-
        confirming unambiguous matches. Run this FIRST; the AI pass then only handles
        whatever is left. Body (optional): {"date_tolerance_days": 4}.
        """
        recon = self.get_object()
        from apps.accounting.services import ReconciliationMatchingService
        tol = request.data.get('date_tolerance_days')
        try:
            tol = int(tol) if tol is not None else None
        except (TypeError, ValueError):
            tol = None
        summary = ReconciliationMatchingService.deterministic_match(recon, date_tolerance_days=tol)
        all_matches = AIReconMatch.objects.filter(reconciliation=recon).select_related(
            'bank_line', 'book_line', 'book_line__journal_entry'
        )
        return Response({
            'matches': AIReconMatchSerializer(all_matches, many=True).data,
            'summary': summary,
        })

    @action(detail=True, methods=['post'], url_path='ai_reconcile')
    def ai_reconcile(self, request, pk=None):
        """
        POST /accounting/reconciliations/{id}/ai_reconcile/
        AI-assist pass (Groq llama-3.3-70b) for the lines the deterministic auto-match
        could NOT resolve. Requires GROQ_API_KEY. A hard timeout keeps it from hanging.
        Get a free key at: https://console.groq.com/keys
        """
        import json
        from django.conf import settings

        recon = self.get_object()

        api_key = getattr(settings, 'GROQ_API_KEY', '') or ''
        if not api_key:
            return Response(
                {'error': 'AI reconciliation requires a GROQ_API_KEY. Get a free key at https://console.groq.com/keys and add it to your .env file.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Only the lines the deterministic pass left uncleared — never re-match cleared ones.
        bank_lines = list(recon.lines.filter(is_cleared=False))
        if not bank_lines:
            return Response({'error': 'No unmatched bank statement lines. Import a statement, or everything is already matched.'}, status=400)

        # Fetch book journal lines for the account + period
        journal_lines = list(
            JournalLine.objects.filter(
                account=recon.account,
                journal_entry__organisation=recon.organisation,
                journal_entry__entry_date__gte=recon.period_start,
                journal_entry__entry_date__lte=recon.period_end,
                journal_entry__status='posted',
            ).select_related('journal_entry')
        )

        bank_items = [
            {
                'id': str(line.id),
                'date': str(line.transaction_date),
                'description': line.description,
                'amount': float(line.amount),
                'reference': line.reference,
            }
            for line in bank_lines
        ]

        book_items = [
            {
                'id': str(jl.id),
                'date': str(jl.journal_entry.entry_date),
                'description': jl.description or jl.journal_entry.description,
                'debit': float(jl.debit),
                'credit': float(jl.credit),
                'reference': jl.journal_entry.reference,
            }
            for jl in journal_lines
        ]

        prompt = f"""You are an expert accountant performing bank reconciliation for a Nigerian business.

TASK: Match each bank statement transaction to the corresponding book entry (journal line), if one exists.

BANK STATEMENT TRANSACTIONS (from the bank):
{json.dumps(bank_items, indent=2)}

BOOK ENTRIES (journal lines from the accounting system):
{json.dumps(book_items, indent=2)}

MATCHING RULES:
- Exact match: same amount AND same/similar date AND description matches
- Fuzzy match: amount matches but date differs by ≤5 days, OR description partially matches
- Uncertain: possible match but significant discrepancy
- No match: cannot find a reasonable corresponding book entry

For Nigerian context: bank descriptions often use coded references (e.g. "NIP/TRANSFER/ACCTNO", "POS/MERCHANT", "USSD/TRF"). Match these to book entries by amount and approximate date.

RESPONSE FORMAT — Return ONLY valid JSON, nothing else:
{{
  "matches": [
    {{
      "bank_line_id": "uuid",
      "book_line_id": "uuid",
      "confidence": 0.95,
      "match_type": "exact|fuzzy|uncertain",
      "reasoning": "Brief explanation of why these match"
    }}
  ],
  "unmatched_bank": [
    {{
      "bank_line_id": "uuid",
      "advice": "This looks like a bank charge — create an expense entry: DR Bank Charges, CR Bank Account"
    }}
  ],
  "unmatched_book": [
    {{
      "book_line_id": "uuid",
      "advice": "This entry has no corresponding bank transaction — it may be a timing difference or an error"
    }}
  ]
}}"""

        try:
            from groq import Groq
            # Hard timeout + no retries so a slow/unreachable Groq can never hang the
            # request (the "stuck in progress" bug). It fails fast into the except below.
            client = Groq(api_key=api_key, timeout=20.0, max_retries=0)
            chat_completion = client.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=4096,
                temperature=0.1,  # Low temp for deterministic matching
                response_format={'type': 'json_object'},
            )
            response_text = chat_completion.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if response_text.startswith('```'):
                response_text = response_text.split('```', 2)[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]
            result = json.loads(response_text.strip())
        except Exception as e:
            return Response(
                {'error': f'AI reconciliation failed: {type(e).__name__}: {e}'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Build lookup maps
        bank_line_map = {str(bl.id): bl for bl in bank_lines}
        journal_line_map = {str(jl.id): jl for jl in journal_lines}

        # Delete old AI matches for this reconciliation
        AIReconMatch.objects.filter(reconciliation=recon).delete()

        created_matches = []

        # Create matched records
        for m in result.get('matches', []):
            bank_line = bank_line_map.get(m.get('bank_line_id'))
            book_line = journal_line_map.get(m.get('book_line_id'))
            if bank_line:
                match = AIReconMatch.objects.create(
                    organisation=recon.organisation,
                    reconciliation=recon,
                    bank_line=bank_line,
                    book_line=book_line,
                    confidence=float(m.get('confidence', 0.5)),
                    match_type=m.get('match_type', 'uncertain'),
                    status='proposed',
                    ai_reasoning=m.get('reasoning', ''),
                )
                created_matches.append(match)

        # Create unmatched bank records
        for u in result.get('unmatched_bank', []):
            bank_line = bank_line_map.get(u.get('bank_line_id'))
            if bank_line:
                match = AIReconMatch.objects.create(
                    organisation=recon.organisation,
                    reconciliation=recon,
                    bank_line=bank_line,
                    book_line=None,
                    confidence=0.0,
                    match_type='uncertain',
                    status='proposed',
                    ai_advice=u.get('advice', ''),
                )
                created_matches.append(match)

        # Create unmatched book records — attach to a placeholder bank_line if possible
        # We can't create an AIReconMatch without a bank_line (FK is required).
        # Instead we return unmatched_book as extra data in the response.
        unmatched_book_data = result.get('unmatched_book', [])

        all_matches = AIReconMatch.objects.filter(reconciliation=recon).select_related(
            'bank_line', 'book_line', 'book_line__journal_entry'
        )
        return Response({
            'matches': AIReconMatchSerializer(all_matches, many=True).data,
            'unmatched_book': unmatched_book_data,
            'summary': {
                'bank_lines_total': len(bank_lines),
                'book_lines_total': len(journal_lines),
                'matches_proposed': len(created_matches),
                'unmatched_book_count': len(unmatched_book_data),
            }
        })

    @action(detail=True, methods=['post'], url_path='confirm_match')
    def confirm_match(self, request, pk=None):
        """
        POST /accounting/reconciliations/{id}/confirm_match/
        Body: { match_id: uuid, action: "confirm" | "reject" }
        """
        recon = self.get_object()
        match_id = request.data.get('match_id')
        action_val = request.data.get('action')

        if action_val not in ('confirm', 'reject'):
            return Response({'error': 'action must be "confirm" or "reject"'}, status=400)

        try:
            match = AIReconMatch.objects.get(id=match_id, reconciliation=recon)
        except AIReconMatch.DoesNotExist:
            return Response({'error': 'Match not found'}, status=404)

        if action_val == 'confirm':
            match.status = 'confirmed'
            match.bank_line.is_cleared = True
            match.bank_line.save(update_fields=['is_cleared'])
        else:
            match.status = 'rejected'
            match.bank_line.is_cleared = False
            match.bank_line.save(update_fields=['is_cleared'])

        match.save(update_fields=['status'])

        return Response(AIReconMatchSerializer(
            AIReconMatch.objects.select_related('bank_line', 'book_line', 'book_line__journal_entry').get(id=match.id)
        ).data)

    @action(detail=True, methods=['post'], url_path='post_confirmed_gl')
    def post_confirmed_gl(self, request, pk=None):
        """
        POST /accounting/reconciliations/{id}/post_confirmed_gl/
        Creates journal entries for all confirmed AI matches that don't yet have
        a corresponding GL entry. Marks each bank_line.is_cleared = True.

        Entry pattern: DR Bank Account → CR Accounts Receivable (for inflows)
                       DR Accounts Payable → CR Bank Account (for outflows)
        """
        recon = self.get_object()
        org = self._get_organisation()

        confirmed = AIReconMatch.objects.filter(
            reconciliation=recon,
            status='confirmed',
            book_line__isnull=True,  # no existing GL entry linked
        ).select_related('bank_line')

        if not confirmed.exists():
            confirmed_with_book = AIReconMatch.objects.filter(
                reconciliation=recon, status='confirmed'
            ).count()
            return Response({
                'posted': 0,
                'message': f'No unmatched confirmed entries to post. ({confirmed_with_book} already linked to GL entries)',
            })

        posted, errors = [], []
        for match in confirmed:
            bank_line = match.bank_line
            amount_val = abs(bank_line.amount)
            if amount_val == 0:
                continue
            try:
                from apps.accounting.services import AccountingService, AccountMappingService
                from decimal import Decimal
                from django.utils import timezone as tz
                amt = Decimal(str(amount_val))
                zero = Decimal('0')
                is_inflow = bank_line.amount >= 0
                if is_inflow:
                    dr_acct = AccountMappingService.resolve(org, 'bank_account')
                    cr_acct = AccountMappingService.resolve(org, 'accounts_receivable')
                else:
                    dr_acct = AccountMappingService.resolve(org, 'accounts_payable')
                    cr_acct = AccountMappingService.resolve(org, 'bank_account')
                je = AccountingService.post_journal_entry(
                    organisation=org,
                    description=f"Bank recon: {bank_line.description[:80]}",
                    entry_date=bank_line.transaction_date,
                    lines=[
                        (dr_acct, amt, zero),
                        (cr_acct, zero, amt),
                    ],
                    created_by=request.user,
                    source_type='bank_recon',
                    source_ref=str(bank_line.id),
                )
                bank_line.is_cleared = True
                bank_line.save(update_fields=['is_cleared'])
                posted.append(str(je.id))
            except Exception as e:
                errors.append({'bank_line_id': str(bank_line.id), 'error': str(e)})

        return Response({
            'posted': len(posted),
            'errors': errors,
            'journal_entry_ids': posted,
        }, status=status.HTTP_201_CREATED if posted else status.HTTP_422_UNPROCESSABLE_ENTITY)


class AccountMappingView(APIView):
    """
    GET  /accounting/account-mapping/   — get org's mapping (with suggestions for nulls)
    PUT  /accounting/account-mapping/   — update mapping
    """
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

    def _get_org(self, request):
        from apps.core.mixins import TenantFilterMixin
        org_id = request.META.get('HTTP_X_ORGANISATION_ID')
        if not org_id:
            return None
        from apps.tenancy.models import Organisation
        try:
            return Organisation.objects.get(id=org_id)
        except Exception:
            return None

    def get(self, request):
        org = self._get_org(request)
        if not org:
            return Response({'error': 'Organisation not found'}, status=400)
        mapping = AccountMappingService.get_or_create_mapping(org)
        data = AccountMappingSerializer(mapping).data
        # Expose the module grouping + labels so the UI can render mapping BY MODULE
        # (GL / Customer / Supplier / Inventory / Payroll) per the client spec.
        data['modules'] = MAPPING_ROLE_MODULES
        data['role_labels'] = MAPPING_ROLE_LABELS
        return Response(data)

    def put(self, request):
        org = self._get_org(request)
        if not org:
            return Response({'error': 'Organisation not found'}, status=400)
        mapping = AccountMappingService.get_or_create_mapping(org)

        # Validate that all provided account IDs belong to this org
        for role in MAPPING_ROLES:
            acct_id = request.data.get(f'{role}_id') or request.data.get(role)
            if acct_id:
                try:
                    acct = Account.objects.get(id=acct_id)
                    if str(acct.organisation_id) != str(org.id):
                        return Response(
                            {'error': f'Account for {role} does not belong to this organisation'},
                            status=400
                        )
                    setattr(mapping, role, acct)
                except Account.DoesNotExist:
                    return Response({'error': f'Account not found for role: {role}'}, status=400)
            elif f'{role}_id' in request.data and request.data[f'{role}_id'] is None:
                setattr(mapping, role, None)

        # Enforce model-level rules (active, non-header) before saving.
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            mapping.full_clean(exclude=['organisation'])
        except DjangoValidationError as e:
            return Response({'error': '; '.join(e.messages)}, status=400)

        mapping.save()
        data = AccountMappingSerializer(mapping).data
        data['modules'] = MAPPING_ROLE_MODULES
        data['role_labels'] = MAPPING_ROLE_LABELS
        return Response(data)


class AccountMappingSuggestionsView(APIView):
    """GET /accounting/account-mapping/suggestions/ — get best-guess suggestions for all roles."""
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

    def get(self, request):
        org_id = request.META.get('HTTP_X_ORGANISATION_ID')
        if not org_id:
            return Response({'error': 'Organisation not found'}, status=400)
        from apps.tenancy.models import Organisation
        try:
            org = Organisation.objects.get(id=org_id)
        except Exception:
            return Response({'error': 'Organisation not found'}, status=400)

        suggestions = {}
        for role in MAPPING_ROLES:
            suggestion = AccountMappingService.suggest(org, role)
            suggestions[role] = {
                'id': str(suggestion.id) if suggestion else None,
                'code': suggestion.code if suggestion else None,
                'name': suggestion.name if suggestion else None,
            }
        return Response(suggestions)


class BeginningBalancesSummaryView(APIView):
    """GET /accounting/beginning-balances/summary/ — consolidated take-on status
    (suspense plug, GL opening balances, subledger control balances)."""
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

    def _get_org(self, request):
        org_id = request.META.get('HTTP_X_ORGANISATION_ID')
        if not org_id:
            return None
        from apps.tenancy.models import Organisation
        try:
            return Organisation.objects.get(id=org_id)
        except Exception:
            return None

    def get(self, request):
        org = self._get_org(request)
        if not org:
            return Response({'error': 'Organisation not found'}, status=400)
        from .services import CapitalisationService
        return Response(CapitalisationService.beginning_balances_summary(org))


class GLHealthView(APIView):
    """GET /accounting/gl-health/ — list recent GL failures with retry info."""
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

    def _get_org(self, request):
        org_id = request.META.get('HTTP_X_ORGANISATION_ID')
        if not org_id:
            return None
        from apps.tenancy.models import Organisation
        try:
            return Organisation.objects.get(id=org_id)
        except Exception:
            return None

    def get(self, request):
        org = self._get_org(request)
        if not org:
            return Response({'error': 'Organisation not found'}, status=400)
        data = AccountingService.get_gl_health(org)
        return Response(data)


class GLHealthBulkRetryView(APIView):
    """POST /accounting/gl-health/retry-all/ — retry ALL failed/not_configured GL posts."""
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

    def _get_org(self, request):
        org_id = request.META.get('HTTP_X_ORGANISATION_ID')
        if not org_id:
            return None
        from apps.tenancy.models import Organisation
        try:
            return Organisation.objects.get(id=org_id)
        except Exception:
            return None

    def post(self, request):
        org = self._get_org(request)
        if not org:
            return Response({'error': 'Organisation not found'}, status=400)

        from apps.sales.models import Invoice
        from apps.bills.models import Bill
        from apps.expenses.models import Expense
        from apps.payroll.models import PayrollRun

        results = {'attempted': 0, 'succeeded': 0, 'failed': 0, 'errors': []}
        retry_statuses = ['failed', 'not_configured']

        for model_name, qs in [
            ('invoice', Invoice.objects.filter(organisation=org, gl_post_status__in=retry_statuses)),
            ('bill',    Bill.objects.filter(organisation=org, gl_post_status__in=retry_statuses)),
            ('expense', Expense.objects.filter(organisation=org, gl_post_status__in=retry_statuses)),
            ('payroll', PayrollRun.objects.filter(organisation=org, gl_post_status__in=retry_statuses)),
        ]:
            for obj in qs[:50]:  # cap per model to avoid timeout
                results['attempted'] += 1
                try:
                    success, err = AccountingService.retry_gl_post(org, model_name, str(obj.id), request.user)
                    if success:
                        results['succeeded'] += 1
                    else:
                        results['failed'] += 1
                        results['errors'].append({'model': model_name, 'id': str(obj.id), 'error': err})
                except Exception as e:
                    results['failed'] += 1
                    results['errors'].append({'model': model_name, 'id': str(obj.id), 'error': str(e)})

        return Response(results)


class GLHealthRetryView(APIView):
    """POST /accounting/gl-health/{type}/{id}/retry/ — retry a failed GL post."""
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

    def post(self, request, model_type, object_id):
        org_id = request.META.get('HTTP_X_ORGANISATION_ID')
        if not org_id:
            return Response({'error': 'Organisation not found'}, status=400)
        from apps.tenancy.models import Organisation
        try:
            org = Organisation.objects.get(id=org_id)
        except Exception:
            return Response({'error': 'Organisation not found'}, status=400)

        try:
            success, err = AccountingService.retry_gl_post(org, model_type, object_id, request.user)
        except Exception as e:
            return Response({'error': str(e)}, status=404)
        if success:
            return Response({'status': 'posted', 'message': 'GL entry posted successfully'})
        return Response({'status': 'failed', 'error': err}, status=422)
