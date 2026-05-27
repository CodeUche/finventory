import re
from decimal import Decimal
from datetime import date
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsAccountant, IsOwnerOrAdmin, plan_requires

_PlanAccounting = plan_requires('accounting')
from .models import Account, JournalEntry, JournalLine, FixedAsset, FinancialPeriod, BankReconciliation, BankReconciliationLine, AIReconMatch
from django.db import transaction
from .serializers import (
    AccountSerializer, JournalEntrySerializer, CreateJournalEntrySerializer, UpdateJournalEntrySerializer,
    FixedAssetSerializer, FinancialPeriodSerializer, BankReconciliationSerializer, BankReconciliationLineSerializer,
    AIReconMatchSerializer,
)
from .services import AccountingService


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


class JournalEntryViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = JournalEntrySerializer
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

    def get_queryset(self):
        org = self._get_organisation()
        return JournalEntry.objects.filter(organisation=org).prefetch_related('lines__account').order_by('-entry_date', '-created_at')

    def _build_lines(self, org, lines_data):
        """Validate balance and return JournalLine instances (unsaved)."""
        total_debit = sum(Decimal(str(l.get('debit', '0'))) for l in lines_data)
        total_credit = sum(Decimal(str(l.get('credit', '0'))) for l in lines_data)
        if abs(total_debit - total_credit) > Decimal('0.01'):
            raise ValueError(f'Journal entry not balanced: debits={total_debit}, credits={total_credit}')
        instances = []
        for line in lines_data:
            acct = Account.objects.get(id=line['account'], organisation=org)
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


class FixedAssetViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = FixedAssetSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

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
        return Response(FinancialPeriodSerializer(period).data)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsOwnerOrAdmin, _PlanAccounting])
    def unlock(self, request, pk=None):
        period = self.get_object()
        period.is_locked = False
        period.locked_by = None
        period.locked_at = None
        period.save()
        return Response(FinancialPeriodSerializer(period).data)


class BankReconciliationViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = BankReconciliationSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _PlanAccounting]

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

    @action(detail=True, methods=['post'], url_path='ai_reconcile')
    def ai_reconcile(self, request, pk=None):
        """
        POST /accounting/reconciliations/{id}/ai_reconcile/
        Uses Groq (free tier, llama-3.3-70b-versatile) to match bank statement
        lines to book journal lines. Requires GROQ_API_KEY in .env.
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

        # Fetch bank statement lines for this reconciliation
        bank_lines = list(recon.lines.all())
        if not bank_lines:
            return Response({'error': 'No bank statement lines found. Import a CSV statement first.'}, status=400)

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
            client = Groq(api_key=api_key)
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
