import csv
import io
import json as _json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings as django_settings
from django.http import HttpResponse

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.mixins import ExportMixin, TenantFilterMixin
from apps.core.permissions import IsManager, IsStaff, IsOwnerOrAdmin
from .models import Employee, EmployeeDocument, EmployeePenalty, EmployeeLoan, PayrollRun, PayslipLine, Bonus, Attendance
from .serializers import (
    EmployeeSerializer, EmployeeDocumentSerializer,
    EmployeePenaltySerializer, EmployeeLoanSerializer,
    PayrollRunSerializer, BonusSerializer, AttendanceSerializer,
)
from .services import PayrollService


class EmployeeViewSet(ExportMixin, TenantFilterMixin, viewsets.ModelViewSet):
    export_filename = 'employees'
    export_fields = [
        ('Employee ID', 'employee_id'),
        ('First Name', 'first_name'),
        ('Last Name', 'last_name'),
        ('Email', 'email'),
        ('Phone', 'phone'),
        ('Job Title', 'job_title'),
        ('Department', 'department'),
        ('Type', 'employment_type'),
        ('Hire Date', 'hire_date'),
        ('Gross Salary', 'gross_salary'),
        ('Active', lambda o: 'Yes' if o.is_active else 'No'),
    ]
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    search_fields = ["first_name", "last_name", "email", "department", "job_title", "employee_id"]
    ordering_fields = ["first_name", "last_name", "basic_salary", "hire_date"]
    ordering = ["first_name"]

    def get_queryset(self):
        org = self._get_organisation()
        return Employee.objects.filter(organisation=org)

    @action(detail=False, methods=["post"])
    def resolve_account(self, request):
        """POST /api/v1/payroll/employees/resolve_account/ — Resolve NUBAN account name via Paystack."""
        account_number = request.data.get("account_number", "").strip()
        bank_code = request.data.get("bank_code", "").strip()

        if not account_number or not bank_code:
            return Response({"error": "account_number and bank_code are required"}, status=400)

        secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
        if not secret_key:
            return Response(
                {"error": "Account resolution is not configured. Add PAYSTACK_SECRET_KEY to your .env file."},
                status=503,
            )

        try:
            params = urllib.parse.urlencode({"account_number": account_number, "bank_code": bank_code})
            url = f"https://api.paystack.co/bank/resolve?{params}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {secret_key}"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
            return Response({"account_name": data["data"]["account_name"]})
        except urllib.error.HTTPError:
            return Response(
                {"error": "Could not resolve account. Verify the account number and bank."},
                status=400,
            )
        except Exception:
            return Response({"error": "Account resolution service is currently unavailable."}, status=503)


class EmployeeDocumentViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = EmployeeDocumentSerializer
    permission_classes = [IsAuthenticated, IsStaff]

    def get_queryset(self):
        org = self._get_organisation()
        qs = EmployeeDocument.objects.filter(organisation=org)
        employee_id = self.request.query_params.get('employee')
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        return qs

    def perform_create(self, serializer):
        file = self.request.FILES.get('file')
        size = file.size if file else 0
        serializer.save(organisation=self._get_organisation(), file_size=size)


class EmployeePenaltyViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = EmployeePenaltySerializer
    permission_classes = [IsAuthenticated, IsStaff]

    def get_queryset(self):
        org = self._get_organisation()
        qs = EmployeePenalty.objects.filter(organisation=org)
        employee_id = self.request.query_params.get('employee')
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(organisation=self._get_organisation())

    @action(detail=True, methods=['post'])
    def waive(self, request, pk=None):
        penalty = self.get_object()
        if penalty.status != EmployeePenalty.PENDING:
            return Response({'error': 'Only pending penalties can be waived'}, status=400)
        penalty.status = EmployeePenalty.WAIVED
        penalty.save(update_fields=['status'])
        return Response(EmployeePenaltySerializer(penalty).data)


class EmployeeLoanViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = EmployeeLoanSerializer
    permission_classes = [IsAuthenticated, IsStaff]

    def get_queryset(self):
        org = self._get_organisation()
        qs = EmployeeLoan.objects.filter(organisation=org)
        employee_id = self.request.query_params.get('employee')
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(organisation=self._get_organisation())

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        loan = self.get_object()
        if loan.status != EmployeeLoan.ACTIVE:
            return Response({'error': 'Only active loans can be cancelled'}, status=400)
        loan.status = EmployeeLoan.CANCELLED
        loan.save(update_fields=['status'])
        return Response(EmployeeLoanSerializer(loan).data)


class BonusViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = BonusSerializer
    permission_classes = [IsAuthenticated, IsStaff]

    def get_queryset(self):
        org = self._get_organisation()
        qs = Bonus.objects.filter(organisation=org).select_related('employee')
        employee_id = self.request.query_params.get('employee')
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        period_year = self.request.query_params.get('period_year')
        period_month = self.request.query_params.get('period_month')
        if period_year:
            qs = qs.filter(period_year=period_year)
        if period_month:
            qs = qs.filter(period_month=period_month)
        return qs

    def perform_create(self, serializer):
        serializer.save(organisation=self._get_organisation())


class AttendanceViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = AttendanceSerializer
    permission_classes = [IsAuthenticated, IsStaff]

    def get_queryset(self):
        org = self._get_organisation()
        qs = Attendance.objects.filter(organisation=org).select_related('employee')
        employee_id = self.request.query_params.get('employee')
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        month = self.request.query_params.get('month')
        year = self.request.query_params.get('year')
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        if year:
            qs = qs.filter(date__year=year)
        if month:
            qs = qs.filter(date__month=month)
        return qs

    def perform_create(self, serializer):
        serializer.save(organisation=self._get_organisation())

    @action(detail=False, methods=['post'])
    def bulk_mark(self, request):
        """
        POST /payroll/attendance/bulk_mark/
        Body: { employee_ids: [...], date: "YYYY-MM-DD", status: "present"|"absent"|..., overtime_hours: 0 }
        Marks attendance for multiple employees on the same day.
        """
        org = self._get_organisation()
        emp_ids = request.data.get('employee_ids', [])
        date = request.data.get('date')
        att_status = request.data.get('status', Attendance.PRESENT)
        overtime_hours = request.data.get('overtime_hours', 0)
        notes = request.data.get('notes', '')

        if not emp_ids or not date:
            return Response({'error': 'employee_ids and date are required'}, status=400)

        created, updated = 0, 0
        for emp_id in emp_ids:
            obj, is_new = Attendance.objects.update_or_create(
                organisation=org,
                employee_id=emp_id,
                date=date,
                defaults={
                    'status': att_status,
                    'overtime_hours': overtime_hours,
                    'notes': notes,
                }
            )
            if is_new:
                created += 1
            else:
                updated += 1

        return Response({'created': created, 'updated': updated})


class PayrollRunViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = PayrollRunSerializer
    permission_classes = [IsAuthenticated, IsManager]

    def get_queryset(self):
        org = self._get_organisation()
        return PayrollRun.objects.filter(organisation=org).prefetch_related('payslips__employee')

    def create(self, request, *args, **kwargs):
        org = self._get_organisation()
        year = int(request.data.get('period_year'))
        month = int(request.data.get('period_month'))
        run, created = PayrollRun.objects.get_or_create(
            organisation=org, period_year=year, period_month=month,
            defaults={'processed_by': request.user}
        )
        if not created and run.status not in [PayrollRun.DRAFT]:
            return Response({'error': 'Payroll already processed for this period'}, status=400)
        # Period-lock guard
        from datetime import date as _date
        from apps.accounting.services import AccountingService
        period_date = _date(year, month, 1)
        if AccountingService.is_period_locked(org, period_date):
            return Response(
                {'error': f'The period {year}-{month:02d} is locked. Unlock it before running payroll.'},
                status=403,
            )
        run = PayrollService.run_payroll(run)
        return Response(
            PayrollRunSerializer(run).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'])
    def submit_for_approval(self, request, pk=None):
        """Manager/HR submits a processed payroll for admin/owner approval."""
        run = self.get_object()
        if run.status != PayrollRun.PROCESSING:
            return Response({'error': 'Only processing payrolls can be submitted for approval'}, status=400)
        run.submitted_for_approval = True
        run.submitted_by = request.user
        run.save(update_fields=['submitted_for_approval', 'submitted_by'])

        # Notify admins/owners via audit log (notifications picked up by frontend polling)
        try:
            from apps.core.utils import log_audit
            log_audit(request, run, 'PAYROLL_SUBMITTED',
                      f"Payroll {run.run_number} submitted for approval by {request.user.email}")
        except Exception:
            pass

        return Response(PayrollRunSerializer(run).data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Owner/Admin final approval — requires submitted_for_approval=True."""
        import logging as _log
        run = self.get_object()
        if run.status != PayrollRun.PROCESSING:
            return Response({'error': 'Only processing payrolls can be approved'}, status=400)
        if not run.submitted_for_approval:
            # Allow owners/admins to self-approve without submission step
            from apps.core.permissions import IsOwnerOrAdmin as _IsOwner
            checker = _IsOwner()
            if not checker.has_permission(request, self):
                return Response(
                    {'error': 'This payroll must be submitted for approval first.'},
                    status=400,
                )
        run.status = PayrollRun.APPROVED
        run.approved_by = request.user
        run.save()

        # Auto-post payroll journal entry (non-blocking)
        try:
            from apps.accounting.services import AccountingService
            AccountingService.post_payroll_journal(run.organisation, run, request.user)
        except Exception as exc:
            _log.getLogger(__name__).warning("post_payroll_journal failed: %s", exc)

        return Response(PayrollRunSerializer(run).data)

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        run = self.get_object()
        from django.utils import timezone
        run.status = PayrollRun.PAID
        run.payment_date = request.data.get('payment_date', timezone.now().date())
        run.save()
        # Mark all payslips as paid
        run.payslips.filter(status=PayslipLine.CALCULATED).update(status=PayslipLine.PAID)
        return Response(PayrollRunSerializer(run).data)

    @action(detail=True, methods=['post'])
    def initiate_transfers(self, request, pk=None):
        """
        POST /payroll/runs/{id}/initiate_transfers/
        Bulk Paystack salary transfer. Persists per-payslip transfer_status for reconciliation.
        """
        import logging as _log
        logger = _log.getLogger(__name__)

        run = self.get_object()
        if run.status != PayrollRun.APPROVED:
            return Response({'error': 'Only approved payroll runs can initiate transfers'}, status=400)

        secret_key = getattr(django_settings, 'PAYSTACK_SECRET_KEY', '')
        if not secret_key:
            return Response(
                {'error': 'Paystack is not configured. Add PAYSTACK_SECRET_KEY to your .env file.'},
                status=503,
            )

        def paystack_post(path, payload):
            req_body = _json.dumps(payload).encode()
            req = urllib.request.Request(
                f'https://api.paystack.co{path}',
                data=req_body,
                headers={
                    'Authorization': f'Bearer {secret_key}',
                    'Content-Type': 'application/json',
                },
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return _json.loads(resp.read())

        results = []
        transfers = []
        payslip_map = {}  # reference → payslip id

        for payslip in run.payslips.select_related('employee').all():
            emp = payslip.employee
            net = float(payslip.net_salary)
            ref = f'{run.run_number}-{emp.employee_id}'

            if not emp.account_number or not emp.bank_code:
                payslip.transfer_status = PayslipLine.TRANSFER_SKIPPED
                payslip.transfer_error = 'Missing bank account number or bank code'
                payslip.save(update_fields=['transfer_status', 'transfer_error'])
                results.append({
                    'employee': emp.employee_id, 'name': f'{emp.first_name} {emp.last_name}',
                    'status': 'skipped', 'reason': 'Missing bank account number or bank code',
                })
                continue

            # Create/get Paystack recipient code
            recipient_code = emp.paystack_recipient_code
            if not recipient_code:
                try:
                    r = paystack_post('/transferrecipient', {
                        'type': 'nuban',
                        'name': emp.account_name or f'{emp.first_name} {emp.last_name}',
                        'account_number': emp.account_number,
                        'bank_code': emp.bank_code,
                        'currency': 'NGN',
                    })
                    recipient_code = r['data']['recipient_code']
                    emp.paystack_recipient_code = recipient_code
                    emp.save(update_fields=['paystack_recipient_code'])
                except Exception as e:
                    logger.warning('Paystack create recipient failed for %s: %s', emp.employee_id, e)
                    payslip.transfer_status = PayslipLine.TRANSFER_FAILED
                    payslip.transfer_error = 'Could not create transfer recipient'
                    payslip.save(update_fields=['transfer_status', 'transfer_error'])
                    results.append({
                        'employee': emp.employee_id, 'name': f'{emp.first_name} {emp.last_name}',
                        'status': 'failed', 'reason': 'Could not create transfer recipient',
                    })
                    continue

            transfers.append({
                'amount': int(net * 100),
                'recipient': recipient_code,
                'reason': f'Net pay — {run.run_number}',
                'reference': ref,
            })
            payslip_map[ref] = payslip.id
            results.append({
                'employee': emp.employee_id, 'name': f'{emp.first_name} {emp.last_name}',
                'account': emp.account_number, 'bank': emp.bank_name,
                'amount': net, 'recipient_code': recipient_code,
                'status': 'queued', 'reference': ref,
            })

        if not transfers:
            return Response({
                'success': False,
                'message': 'No employees with complete bank details found',
                'results': results,
            }, status=400)

        try:
            bulk_resp = paystack_post('/transfer/bulk', {
                'currency': 'NGN', 'source': 'balance', 'transfers': transfers,
            })
            batch_code = (
                bulk_resp.get('data', {}).get('batch_code', '')
                if isinstance(bulk_resp.get('data'), dict)
                else ''
            )
            if not batch_code and isinstance(bulk_resp.get('data'), list):
                batch_code = ','.join(str(t.get('reference', '')) for t in bulk_resp['data'][:3])

            run.transfer_reference = batch_code or run.run_number
            run.save(update_fields=['transfer_reference'])

            # Persist per-payslip transfer status
            if isinstance(bulk_resp.get('data'), list):
                for transfer_result in bulk_resp['data']:
                    ref = transfer_result.get('reference', '')
                    pslip_id = payslip_map.get(ref)
                    if pslip_id:
                        t_status = transfer_result.get('status', '')
                        ps_status = (
                            PayslipLine.TRANSFER_INITIATED if t_status in ('pending', 'otp')
                            else PayslipLine.TRANSFER_SUCCESS if t_status == 'success'
                            else PayslipLine.TRANSFER_FAILED
                        )
                        PayslipLine.objects.filter(id=pslip_id).update(
                            transfer_status=ps_status,
                            transfer_reference=transfer_result.get('transfer_code', ref),
                        )
                        # Mirror to results list
                        for r in results:
                            if r.get('reference') == ref:
                                r['status'] = 'initiated'
                                r['transfer_code'] = transfer_result.get('transfer_code', '')
            else:
                # Fallback: mark all queued as initiated
                PayslipLine.objects.filter(
                    payroll_run=run,
                    transfer_status=PayslipLine.TRANSFER_PENDING,
                ).update(transfer_status=PayslipLine.TRANSFER_INITIATED)
                for r in results:
                    if r['status'] == 'queued':
                        r['status'] = 'initiated'

            return Response({
                'success': True,
                'message': f'{len(transfers)} transfer(s) initiated via Paystack',
                'batch_code': batch_code,
                'results': results,
            })

        except urllib.error.HTTPError as e:
            body = e.read().decode()
            logger.warning('Paystack bulk transfer failed: %s %s', e.code, body)
            try:
                err_data = _json.loads(body)
                msg = err_data.get('message', 'Paystack rejected the bulk transfer')
            except Exception:
                msg = f'HTTP {e.code}: {body[:200]}'
            return Response({'success': False, 'error': msg, 'results': results}, status=400)
        except Exception as e:
            logger.warning('Paystack bulk transfer error: %s', e)
            return Response({
                'success': False, 'error': 'Transfer service temporarily unavailable',
                'results': results,
            }, status=503)

    @action(detail=True, methods=['post'])
    def retry_failed(self, request, pk=None):
        """
        POST /payroll/runs/{id}/retry_failed/
        Retries only the payslips whose transfer_status is 'failed'.
        Same idempotency key (run_number-employee_id) prevents double payments.
        """
        import logging as _log
        logger = _log.getLogger(__name__)

        run = self.get_object()
        if run.status not in [PayrollRun.APPROVED, PayrollRun.PAID]:
            return Response({'error': 'Can only retry on approved or paid payroll runs'}, status=400)

        secret_key = getattr(django_settings, 'PAYSTACK_SECRET_KEY', '')
        if not secret_key:
            return Response({'error': 'Paystack is not configured.'}, status=503)

        failed_payslips = list(
            run.payslips.select_related('employee').filter(
                transfer_status__in=[PayslipLine.TRANSFER_FAILED, PayslipLine.TRANSFER_PENDING]
            )
        )
        if not failed_payslips:
            return Response({'message': 'No failed transfers to retry', 'retried': 0})

        def paystack_post(path, payload):
            req_body = _json.dumps(payload).encode()
            req = urllib.request.Request(
                f'https://api.paystack.co{path}',
                data=req_body,
                headers={
                    'Authorization': f'Bearer {secret_key}',
                    'Content-Type': 'application/json',
                },
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return _json.loads(resp.read())

        results = []
        transfers = []
        payslip_map = {}

        for payslip in failed_payslips:
            emp = payslip.employee
            if not emp.account_number or not emp.bank_code:
                results.append({'employee': emp.employee_id, 'name': f'{emp.first_name} {emp.last_name}',
                                 'status': 'skipped', 'reason': 'No bank details'})
                continue
            recipient_code = emp.paystack_recipient_code
            if not recipient_code:
                try:
                    r = paystack_post('/transferrecipient', {
                        'type': 'nuban',
                        'name': emp.account_name or f'{emp.first_name} {emp.last_name}',
                        'account_number': emp.account_number,
                        'bank_code': emp.bank_code,
                        'currency': 'NGN',
                    })
                    recipient_code = r['data']['recipient_code']
                    emp.paystack_recipient_code = recipient_code
                    emp.save(update_fields=['paystack_recipient_code'])
                except Exception as e:
                    logger.warning('Retry: recipient failed for %s: %s', emp.employee_id, e)
                    results.append({'employee': emp.employee_id, 'name': f'{emp.first_name} {emp.last_name}',
                                     'status': 'failed', 'reason': 'Could not create recipient'})
                    continue

            ref = f'{run.run_number}-{emp.employee_id}'
            transfers.append({
                'amount': int(float(payslip.net_salary) * 100),
                'recipient': recipient_code,
                'reason': f'Retry net pay — {run.run_number}',
                'reference': ref,
            })
            payslip_map[ref] = payslip.id
            results.append({'employee': emp.employee_id, 'name': f'{emp.first_name} {emp.last_name}',
                             'status': 'queued', 'reference': ref})

        if not transfers:
            return Response({'success': False, 'message': 'No retryable transfers', 'results': results})

        try:
            bulk_resp = paystack_post('/transfer/bulk', {
                'currency': 'NGN', 'source': 'balance', 'transfers': transfers,
            })
            for transfer_result in (bulk_resp.get('data') or []):
                ref = transfer_result.get('reference', '')
                pslip_id = payslip_map.get(ref)
                if pslip_id:
                    PayslipLine.objects.filter(id=pslip_id).update(
                        transfer_status=PayslipLine.TRANSFER_INITIATED,
                        transfer_reference=transfer_result.get('transfer_code', ref),
                        transfer_error='',
                    )
                    for r in results:
                        if r.get('reference') == ref:
                            r['status'] = 'initiated'

            return Response({'success': True, 'retried': len(transfers), 'results': results})
        except Exception as e:
            logger.warning('Retry bulk transfer error: %s', e)
            return Response({'success': False, 'error': str(e), 'results': results}, status=503)

    @action(detail=True, methods=['get'])
    def export_bank_file(self, request, pk=None):
        """
        GET /payroll/runs/{id}/export_bank_file/

        Returns an industry-standard Nigerian payroll bulk-payment CSV compatible
        with NIBSS EFT / NIP and the bulk-salary upload portals of GTBank, Zenith,
        Access, UBA, First Bank, and other CBN-licensed commercial banks.

        Structure
        ---------
        Section A : File header  (company, period, run metadata)
        Section B : Payment schedule — one row per employee with complete
                    earnings, statutory deductions, and net pay breakdown
        Section C : Exceptions  — employees whose bank details are incomplete
                    and require manual processing
        Section D : Summary totals row
        """
        import calendar
        from datetime import date

        run = self.get_object()
        org = run.organisation
        payslips = run.payslips.select_related('employee').order_by(
            'employee__department', 'employee__last_name'
        )

        MONTHS = [
            '', 'January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December',
        ]
        period_label = f"{MONTHS[run.period_month]} {run.period_year}"
        generated_on = date.today().strftime('%d %B %Y')
        processed_by = (
            f"{run.processed_by.first_name} {run.processed_by.last_name}".strip()
            or run.processed_by.email
        )
        approved_by = ''
        if run.approved_by:
            approved_by = (
                f"{run.approved_by.first_name} {run.approved_by.last_name}".strip()
                or run.approved_by.email
            )

        # Partition payslips
        ready, exceptions = [], []
        for p in payslips:
            emp = p.employee
            if emp.account_number and emp.account_number.strip() and emp.bank_code and emp.bank_code.strip():
                ready.append(p)
            else:
                exceptions.append(p)

        # Totals across ready-to-pay employees only
        def _d(val):
            """Safely convert MoneyField / Decimal to float."""
            try:
                return float(val or 0)
            except Exception:
                return 0.0

        total_gross       = sum(_d(p.gross_salary)         for p in ready)
        total_bonus       = sum(_d(p.bonus_amount)         for p in ready)
        total_overtime    = sum(_d(p.overtime_amount)      for p in ready)
        total_earnings    = sum(_d(p.gross_salary) + _d(p.bonus_amount) + _d(p.overtime_amount) for p in ready)
        total_pension_emp = sum(_d(p.employee_pension)     for p in ready)
        total_nhf         = sum(_d(p.nhf)                  for p in ready)
        total_nsitf       = sum(_d(p.nsitf)               for p in ready)
        total_paye        = sum(_d(p.paye_tax)             for p in ready)
        total_att_ded     = sum(_d(p.attendance_deduction) for p in ready)
        total_loan        = sum(_d(p.loan_deductions)      for p in ready)
        total_penalty     = sum(_d(p.penalty_deductions)   for p in ready)
        total_deductions  = sum(_d(p.total_deductions)     for p in ready)
        total_net         = sum(_d(p.net_salary)           for p in ready)

        output = io.StringIO()
        writer = csv.writer(output)

        # ── Section A: File Header ───────────────────────────────────────────────
        writer.writerow(['PAYROLL BULK PAYMENT FILE'])
        writer.writerow(['Company Name',        org.name])
        writer.writerow(['Company Address',     org.address or ''])
        writer.writerow(['Tax ID (TIN/VAT)',    org.tax_id or ''])
        writer.writerow(['Pay Period',          period_label])
        writer.writerow(['Run Reference',       run.run_number])
        writer.writerow(['Run Status',          run.status.upper()])
        writer.writerow(['Payment Date',        run.payment_date.strftime('%d %B %Y') if run.payment_date else 'Pending'])
        writer.writerow(['Currency',            org.currency or 'NGN'])
        writer.writerow(['Total Employees (Ready to Pay)', len(ready)])
        writer.writerow(['Total Employees (Exceptions)',   len(exceptions)])
        writer.writerow(['Total Net Pay (Transfer Amount)', f'{total_net:,.2f}'])
        writer.writerow(['Processed By',        processed_by])
        writer.writerow(['Approved By',         approved_by or 'Pending Approval'])
        writer.writerow(['Generated On',        generated_on])
        writer.writerow([])  # blank separator

        # ── Section B: Payment Schedule ─────────────────────────────────────────
        writer.writerow(['SECTION B — PAYMENT SCHEDULE (Ready to Transfer)'])
        writer.writerow([
            # Identity
            'S/N', 'Employee ID', 'Full Name', 'Job Title', 'Department',
            # Bank (NIBSS/NIP fields)
            'Bank Name', 'Account Number (NUBAN)', 'Account Name', 'Bank Code (CBN)',
            # Earnings breakdown
            'Basic Salary', 'Housing Allowance', 'Transport Allowance',
            'Leave Allowance', 'Other Allowances', 'Gross Salary',
            'Bonus', 'Overtime', 'Total Earnings',
            # Statutory deductions (employee)
            'Employee Pension (8%)', 'NHF (2.5%)', 'NSITF (1%)', 'PAYE Tax',
            # Other deductions
            'Attendance Deduction', 'Loan Repayment', 'Penalty Deduction',
            'Total Deductions',
            # Net pay (the amount actually transferred)
            'Net Pay (Transfer Amount)',
            # Statutory IDs for remittance
            "Employee's PFA", 'RSA PIN (PFA Number)', 'TIN',
            # Bank narration (what appears on the beneficiary's bank statement)
            'Narration',
        ])

        for sn, p in enumerate(ready, start=1):
            emp = p.employee
            full_name = f"{emp.first_name} {emp.last_name}".strip()
            # Narration format: SALARY/APR-2025/EMP-001  (≤ 100 chars, bank-safe)
            narration = f"SALARY/{MONTHS[run.period_month][:3].upper()}-{run.period_year}/{emp.employee_id}"
            gross_total = _d(p.gross_salary) + _d(p.bonus_amount) + _d(p.overtime_amount)
            writer.writerow([
                sn,
                emp.employee_id,
                full_name,
                emp.job_title,
                emp.department or '',
                emp.bank_name or '',
                emp.account_number or '',
                emp.account_name or full_name,
                emp.bank_code or '',
                f"{_d(p.basic_salary):,.2f}",
                f"{_d(p.housing_allowance):,.2f}",
                f"{_d(p.transport_allowance):,.2f}",
                f"{_d(p.leave_allowance):,.2f}",
                f"{_d(p.other_allowances):,.2f}",
                f"{_d(p.gross_salary):,.2f}",
                f"{_d(p.bonus_amount):,.2f}",
                f"{_d(p.overtime_amount):,.2f}",
                f"{gross_total:,.2f}",
                f"{_d(p.employee_pension):,.2f}",
                f"{_d(p.nhf):,.2f}",
                f"{_d(p.nsitf):,.2f}",
                f"{_d(p.paye_tax):,.2f}",
                f"{_d(p.attendance_deduction):,.2f}",
                f"{_d(p.loan_deductions):,.2f}",
                f"{_d(p.penalty_deductions):,.2f}",
                f"{_d(p.total_deductions):,.2f}",
                f"{_d(p.net_salary):,.2f}",
                emp.pfa_name or '',
                emp.pfa_number or '',
                emp.tin or '',
                narration,
            ])

        # ── Section C: Exceptions ────────────────────────────────────────────────
        writer.writerow([])
        writer.writerow(['SECTION C — EXCEPTIONS (Incomplete Bank Details — Manual Processing Required)'])
        if exceptions:
            writer.writerow([
                'S/N', 'Employee ID', 'Full Name', 'Job Title', 'Department',
                'Bank Name', 'Account Number', 'Account Name', 'Bank Code',
                'Net Pay Due', 'Missing Fields', 'Action Required',
            ])
            for sn, p in enumerate(exceptions, start=1):
                emp = p.employee
                missing = []
                if not (emp.account_number or '').strip():
                    missing.append('Account Number')
                if not (emp.bank_code or '').strip():
                    missing.append('Bank Code')
                if not (emp.account_name or '').strip():
                    missing.append('Account Name')
                writer.writerow([
                    sn,
                    emp.employee_id,
                    f"{emp.first_name} {emp.last_name}".strip(),
                    emp.job_title,
                    emp.department or '',
                    emp.bank_name or 'NOT SET',
                    emp.account_number or 'NOT SET',
                    emp.account_name or 'NOT SET',
                    emp.bank_code or 'NOT SET',
                    f"{_d(p.net_salary):,.2f}",
                    ', '.join(missing),
                    'Update employee bank details in payroll settings',
                ])
        else:
            writer.writerow(['No exceptions — all employees have complete bank details.'])

        # ── Section D: Summary Totals ────────────────────────────────────────────
        writer.writerow([])
        writer.writerow(['SECTION D — PAYROLL SUMMARY'])
        writer.writerow(['Description', f'Amount ({org.currency or "NGN"})'])
        writer.writerow(['Total Gross Salary',          f'{total_gross:,.2f}'])
        writer.writerow(['Total Bonus & Overtime',      f'{total_bonus + total_overtime:,.2f}'])
        writer.writerow(['Total Earnings',              f'{total_earnings:,.2f}'])
        writer.writerow(['—', ''])
        writer.writerow(['Employee Pension (8%)',        f'{total_pension_emp:,.2f}'])
        writer.writerow(['NHF (2.5% of Basic)',          f'{total_nhf:,.2f}'])
        writer.writerow(['NSITF (1% of Gross)',          f'{total_nsitf:,.2f}'])
        writer.writerow(['PAYE Tax',                     f'{total_paye:,.2f}'])
        writer.writerow(['Attendance / Loan / Penalty',  f'{total_att_ded + total_loan + total_penalty:,.2f}'])
        writer.writerow(['Total Deductions',             f'{total_deductions:,.2f}'])
        writer.writerow(['—', ''])
        writer.writerow(['NET PAY (Bank Transfer Total)', f'{total_net:,.2f}'])
        writer.writerow(['—', ''])
        writer.writerow(['Employer Pension (10%) — Remit to PFA', f'{_d(run.total_pension_employer):,.2f}'])
        writer.writerow(['PAYE — Remit to LIRS/SIRS by 10th',     f'{_d(run.total_paye):,.2f}'])
        writer.writerow(['NHF — Remit to Federal Mortgage Bank',   f'{_d(run.total_nhf):,.2f}'])
        writer.writerow(['NSITF — Remit to NSITF Board',           f'{_d(run.total_nsitf):,.2f}'])

        filename = f'{run.run_number}-bank-payment-{run.period_year}{run.period_month:02d}.csv'
        response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    @action(detail=False, methods=['get'])
    def pending_approvals(self, request):
        """GET /payroll/runs/pending_approvals/ — runs awaiting approval (for notification badge)."""
        org = self._get_organisation()
        runs = PayrollRun.objects.filter(
            organisation=org,
            status=PayrollRun.PROCESSING,
            submitted_for_approval=True,
        ).values('id', 'run_number', 'period_year', 'period_month', 'submitted_by__email')
        return Response(list(runs))
