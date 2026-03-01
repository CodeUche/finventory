from decimal import Decimal
from datetime import date
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsAccountant, IsOwnerOrAdmin
from .models import Account, JournalEntry, JournalLine, FixedAsset
from .serializers import (
    AccountSerializer, JournalEntrySerializer, CreateJournalEntrySerializer,
    FixedAssetSerializer
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
        data = AccountingService.balance_sheet(org)
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
