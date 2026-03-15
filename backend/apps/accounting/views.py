from decimal import Decimal
from datetime import date
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsAccountant, IsOwnerOrAdmin
from .models import Account, JournalEntry, JournalLine, FixedAsset, FinancialPeriod, BankReconciliation, BankReconciliationLine
from .serializers import (
    AccountSerializer, JournalEntrySerializer, CreateJournalEntrySerializer,
    FixedAssetSerializer, FinancialPeriodSerializer, BankReconciliationSerializer, BankReconciliationLineSerializer,
)
from .services import AccountingService


class AccountViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated, IsAccountant]

    def get_queryset(self):
        org = self._get_organisation()
        return Account.objects.filter(organisation=org)

    def perform_destroy(self, instance):
        if instance.is_system:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("System accounts cannot be deleted")
        instance.delete()

    @action(detail=False, methods=['get'])
    def trial_balance(self, request):
        org = self._get_organisation()
        data = AccountingService.trial_balance(org)
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


class JournalEntryViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = JournalEntrySerializer
    permission_classes = [IsAuthenticated, IsAccountant]

    def get_queryset(self):
        org = self._get_organisation()
        return JournalEntry.objects.filter(organisation=org).prefetch_related('lines__account')

    def create(self, request, *args, **kwargs):
        org = self._get_organisation()
        ser = CreateJournalEntrySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        lines_data = d['lines']
        total_debit = sum(Decimal(str(l.get('debit', '0'))) for l in lines_data)
        total_credit = sum(Decimal(str(l.get('credit', '0'))) for l in lines_data)
        if abs(total_debit - total_credit) > Decimal('0.01'):
            return Response({'error': f'Journal entry not balanced: debits={total_debit}, credits={total_credit}'}, status=400)

        entry = JournalEntry.objects.create(
            organisation=org,
            description=d['description'],
            entry_date=d['entry_date'],
            created_by=request.user,
        )
        for line in lines_data:
            acct = Account.objects.get(id=line['account'], organisation=org)
            JournalLine.objects.create(
                journal_entry=entry,
                account=acct,
                debit=Decimal(str(line.get('debit', '0'))),
                credit=Decimal(str(line.get('credit', '0'))),
                description=line.get('description', ''),
            )
        return Response(JournalEntrySerializer(entry).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def post_entry(self, request, pk=None):
        entry = self.get_object()
        if entry.status == JournalEntry.POSTED:
            return Response({'error': 'Already posted'}, status=400)
        entry.status = JournalEntry.POSTED
        entry.posted_by = request.user
        entry.save()
        return Response(JournalEntrySerializer(entry).data)


class FixedAssetViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = FixedAssetSerializer
    permission_classes = [IsAuthenticated, IsAccountant]

    def get_queryset(self):
        org = self._get_organisation()
        return FixedAsset.objects.filter(organisation=org).prefetch_related('depreciation_entries')

    @action(detail=False, methods=['post'])
    def run_depreciation(self, request):
        org = self._get_organisation()
        today = date.today()
        year = int(request.data.get('year', today.year))
        month = int(request.data.get('month', today.month))
        entries = AccountingService.run_depreciation(org, year, month)
        return Response({'message': f'Ran depreciation for {year}-{month:02d}', 'entries_created': len(entries)})


class FinancialPeriodViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = FinancialPeriodSerializer
    permission_classes = [IsAuthenticated, IsAccountant]

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

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsOwnerOrAdmin])
    def lock(self, request, pk=None):
        from django.utils import timezone as tz
        period = self.get_object()
        if period.is_locked:
            return Response({'error': 'Period is already locked'}, status=400)
        period.is_locked = True
        period.locked_by = request.user
        period.locked_at = tz.now()
        period.save()
        return Response(FinancialPeriodSerializer(period).data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsOwnerOrAdmin])
    def unlock(self, request, pk=None):
        period = self.get_object()
        period.is_locked = False
        period.locked_by = None
        period.locked_at = None
        period.save()
        return Response(FinancialPeriodSerializer(period).data)


class BankReconciliationViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = BankReconciliationSerializer
    permission_classes = [IsAuthenticated, IsAccountant]

    def get_queryset(self):
        org = self._get_organisation()
        return BankReconciliation.objects.filter(organisation=org).prefetch_related('lines')

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

                if amount_str and not debit_str and not credit_str:
                    amt = Decimal(amount_str.replace(',', ''))
                    debit = -amt if amt < 0 else Decimal('0')
                    credit = amt if amt >= 0 else Decimal('0')
                else:
                    debit = Decimal(debit_str.replace(',', '') or '0')
                    credit = Decimal(credit_str.replace(',', '') or '0')

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
