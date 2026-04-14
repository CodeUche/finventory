import csv
import io
import json as _json
from openpyxl import Workbook
from openpyxl.styles import (
    PatternFill, Font, Alignment, Border, Side, numbers as xl_numbers,
)
from openpyxl.utils import get_column_letter
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
from apps.core.permissions import IsManager, IsStaff, IsOwnerOrAdmin, plan_requires

_PlanPayroll = plan_requires('payroll')
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
    permission_classes = [IsAuthenticated, IsStaff, _PlanPayroll]
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
    permission_classes = [IsAuthenticated, IsStaff, _PlanPayroll]

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
    permission_classes = [IsAuthenticated, IsStaff, _PlanPayroll]

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
    permission_classes = [IsAuthenticated, IsStaff, _PlanPayroll]

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
    permission_classes = [IsAuthenticated, IsStaff, _PlanPayroll]

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
    permission_classes = [IsAuthenticated, IsStaff, _PlanPayroll]

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
    permission_classes = [IsAuthenticated, IsManager, _PlanPayroll]

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

    @action(detail=False, methods=['get'])
    def eligible_approvers(self, request):
        """Return org members with admin or owner role — valid approvers for payroll."""
        from apps.tenancy.models import Membership
        org = self._get_organisation()
        members = (
            Membership.objects
            .filter(organisation=org, is_active=True, role__in=['owner', 'admin'])
            .select_related('user')
            .exclude(user=request.user)
        )
        data = [
            {'id': str(m.user.id), 'name': f"{m.user.first_name} {m.user.last_name}".strip() or m.user.email, 'email': m.user.email, 'role': m.role}
            for m in members
        ]
        return Response(data)

    @action(detail=True, methods=['post'])
    def submit_for_approval(self, request, pk=None):
        """Manager/HR submits a processed payroll for admin/owner approval."""
        run = self.get_object()
        if run.status != PayrollRun.PROCESSING:
            return Response({'error': 'Only processing payrolls can be submitted for approval'}, status=400)
        run.submitted_for_approval = True
        run.submitted_by = request.user

        # Optional: target a specific approver
        approver_id = request.data.get('approver_id')
        if approver_id:
            from django.contrib.auth import get_user_model
            try:
                approver = get_user_model().objects.get(id=approver_id)
                run.target_approver = approver
            except Exception:
                pass

        run.save(update_fields=['submitted_for_approval', 'submitted_by', 'target_approver'])

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

        Returns a professionally formatted Excel workbook (.xlsx) for bank
        submission — NIBSS EFT / NIP compatible.

        Workbook structure
        ------------------
        Sheet 1 — Payment Schedule   (ready-to-transfer employees, full breakdown)
        Sheet 2 — Statutory Summary  (employer remittance obligations)
        Sheet 3 — Exceptions         (employees with missing bank details)
        """
        from datetime import date as _date

        run  = self.get_object()
        org  = run.organisation
        curr = org.currency or 'NGN'
        payslips = run.payslips.select_related('employee').order_by(
            'employee__department', 'employee__last_name'
        )

        MONTHS = ['', 'January', 'February', 'March', 'April', 'May', 'June',
                  'July', 'August', 'September', 'October', 'November', 'December']

        period_label  = f"{MONTHS[run.period_month]} {run.period_year}"
        generated_on  = _date.today().strftime('%d %B %Y')
        payment_date  = (run.payment_date.strftime('%d %B %Y')
                         if run.payment_date else 'Pending')
        processed_by  = (
            f"{run.processed_by.first_name} {run.processed_by.last_name}".strip()
            or run.processed_by.email
        )
        approved_by = (
            (f"{run.approved_by.first_name} {run.approved_by.last_name}".strip()
             or run.approved_by.email)
            if run.approved_by else 'Pending Approval'
        )

        def _d(v):
            try:
                return float(v or 0)
            except Exception:
                return 0.0

        ready, exceptions = [], []
        for p in payslips:
            e = p.employee
            if (e.account_number or '').strip() and (e.bank_code or '').strip():
                ready.append(p)
            else:
                exceptions.append(p)

        # Aggregate totals (ready employees only)
        tot_basic     = sum(_d(p.basic_salary)          for p in ready)
        tot_housing   = sum(_d(p.housing_allowance)     for p in ready)
        tot_transport = sum(_d(p.transport_allowance)   for p in ready)
        tot_leave     = sum(_d(p.leave_allowance)       for p in ready)
        tot_other     = sum(_d(p.other_allowances)      for p in ready)
        tot_gross     = sum(_d(p.gross_salary)          for p in ready)
        tot_bonus     = sum(_d(p.bonus_amount)          for p in ready)
        tot_overtime  = sum(_d(p.overtime_amount)       for p in ready)
        tot_earnings  = tot_gross + tot_bonus + tot_overtime
        tot_pen_emp   = sum(_d(p.employee_pension)      for p in ready)
        tot_nhf       = sum(_d(p.nhf)                   for p in ready)
        tot_nsitf     = sum(_d(p.nsitf)                 for p in ready)
        tot_paye      = sum(_d(p.paye_tax)              for p in ready)
        tot_att       = sum(_d(p.attendance_deduction)  for p in ready)
        tot_loan      = sum(_d(p.loan_deductions)       for p in ready)
        tot_penalty   = sum(_d(p.penalty_deductions)    for p in ready)
        tot_deduct    = sum(_d(p.total_deductions)      for p in ready)
        tot_net       = sum(_d(p.net_salary)            for p in ready)
        tot_pen_er    = _d(run.total_pension_employer)

        # ── Shared style helpers ─────────────────────────────────────────────────

        # Palette (navy + gold — investment-grade standard)
        NAVY   = '0D1F3C'   # header background
        GOLD   = 'C9A84C'   # accent / totals row
        WHITE  = 'FFFFFF'
        LIGHT  = 'F4F6FA'   # alternate row tint
        MID    = 'DDE3ED'   # section header tint
        RED_BG = 'FFF0F0'   # exception rows
        RED_TX = 'C0392B'

        def _fill(hex_color):
            return PatternFill('solid', fgColor=hex_color)

        def _font(bold=False, color=WHITE, size=10, italic=False):
            return Font(name='Calibri', bold=bold, color=color, size=size,
                        italic=italic)

        def _border(style='thin'):
            s = Side(style=style, color='B0BAC9')
            return Border(left=s, right=s, top=s, bottom=s)

        def _align(h='left', v='center', wrap=False):
            return Alignment(horizontal=h, vertical=v, wrap_text=wrap)

        MONEY_FMT  = f'"{curr}" #,##0.00'
        NUMBER_FMT = '#,##0'

        def _set_col_widths(ws, widths):
            for col_idx, w in enumerate(widths, start=1):
                ws.column_dimensions[get_column_letter(col_idx)].width = w

        def _freeze(ws, cell='A1'):
            ws.freeze_panes = cell

        # ── Workbook ─────────────────────────────────────────────────────────────
        wb = Workbook()

        # ═══════════════════════════════════════════════════════════════════════
        # SHEET 1 — Payment Schedule
        # ═══════════════════════════════════════════════════════════════════════
        ws1 = wb.active
        ws1.title = 'Payment Schedule'
        ws1.sheet_view.showGridLines = False

        # ── Cover block (rows 1-12) ───────────────────────────────────────────
        TOTAL_COLS = 30   # widest data section width in columns

        def _cover_row(ws, row, label, value, label_col=1, val_col=3,
                       label_font=None, val_font=None):
            lc = ws.cell(row=row, column=label_col, value=label)
            lc.font      = label_font or _font(bold=True, color='0D1F3C', size=10)
            lc.alignment = _align('left')
            vc = ws.cell(row=row, column=val_col, value=value)
            vc.font      = val_font or _font(bold=False, color='1A1A2E', size=10)
            vc.alignment = _align('left')

        # Title banner — merged across all columns
        ws1.merge_cells(start_row=1, start_column=1,
                         end_row=2,   end_column=TOTAL_COLS)
        title_cell = ws1.cell(row=1, column=1,
                               value='PAYROLL BULK PAYMENT FILE')
        title_cell.fill      = _fill(NAVY)
        title_cell.font      = Font(name='Calibri', bold=True, color=WHITE,
                                    size=18)
        title_cell.alignment = _align('center', 'center')
        ws1.row_dimensions[1].height = 36
        ws1.row_dimensions[2].height = 6   # spacer within merge

        # Sub-header: company name + document class
        ws1.merge_cells(start_row=3, start_column=1,
                         end_row=3,   end_column=TOTAL_COLS)
        sub = ws1.cell(row=3, column=1, value=org.name.upper())
        sub.fill      = _fill(GOLD)
        sub.font      = Font(name='Calibri', bold=True, color=NAVY, size=12)
        sub.alignment = _align('center', 'center')
        ws1.row_dimensions[3].height = 22

        # Blank gap row
        ws1.row_dimensions[4].height = 6

        # Meta fields (two-column pairs side by side)
        meta_pairs = [
            ('Pay Period',              period_label,
             'Run Reference',           run.run_number),
            ('Run Status',              run.status.upper(),
             'Payment Date',            payment_date),
            ('Currency',                curr,
             'Total Employees (Ready)', len(ready)),
            ('Total Employees (Exceptions)', len(exceptions),
             'Total Net Transfer',      tot_net),
            ('Processed By',            processed_by,
             'Approved By',             approved_by),
            ('Company Address',         org.address or '—',
             'Tax ID (TIN/VAT)',         org.tax_id or '—'),
            ('Generated On',            generated_on,
             'CONFIDENTIAL',
             'For authorised recipients only'),
        ]
        for i, (l1, v1, l2, v2) in enumerate(meta_pairs, start=5):
            row = i
            ws1.row_dimensions[row].height = 17
            # Left pair
            lc = ws1.cell(row=row, column=1, value=l1)
            lc.font = _font(bold=True, color=NAVY, size=9)
            lc.fill = _fill(MID)
            lc.alignment = _align('left')
            lc.border = _border()
            vc = ws1.cell(row=row, column=3, value=v1)
            vc.font = _font(bold=False, color='1A1A2E', size=9)
            vc.alignment = _align('left')
            vc.border = _border()
            ws1.merge_cells(start_row=row, start_column=3,
                             end_row=row,   end_column=9)
            if l1 == 'Total Net Transfer':
                vc.number_format = MONEY_FMT
                vc.value = tot_net
            # Right pair
            lc2 = ws1.cell(row=row, column=11, value=l2)
            lc2.font = _font(bold=True, color=NAVY, size=9)
            lc2.fill = _fill(MID)
            lc2.alignment = _align('left')
            lc2.border = _border()
            vc2 = ws1.cell(row=row, column=13, value=v2)
            vc2.font = _font(bold=False, color='1A1A2E', size=9)
            vc2.alignment = _align('left')
            vc2.border = _border()
            ws1.merge_cells(start_row=row, start_column=13,
                             end_row=row,   end_column=20)

        # Divider row before table
        div_row = len(meta_pairs) + 5 + 1
        ws1.row_dimensions[div_row].height = 6

        # ── Column headers (row after divider) ───────────────────────────────
        hdr_row = div_row + 1
        ws1.row_dimensions[hdr_row].height = 42

        HEADERS = [
            # identity
            'S/N', 'Employee ID', 'Full Name', 'Job Title', 'Department',
            # bank
            'Bank Name', 'Account Number\n(NUBAN)', 'Account Name', 'Bank\nCode (CBN)',
            # earnings
            'Basic\nSalary', 'Housing\nAllowance', 'Transport\nAllowance',
            'Leave\nAllowance', 'Other\nAllowances', 'Gross\nSalary',
            'Bonus', 'Overtime', 'Total\nEarnings',
            # deductions
            'Employee\nPension (8%)', 'NHF\n(2.5%)', 'NSITF\n(1%)', 'PAYE\nTax',
            'Attendance\nDeduction', 'Loan\nRepayment', 'Penalty\nDeduction',
            'Total\nDeductions',
            # net
            f'NET PAY\n({curr})',
            # statutory IDs
            "Employee's\nPFA", 'RSA PIN\n(PFA No.)', 'TIN',
            # narration
            'Bank Narration',
        ]
        MONEY_COLS = set(range(10, 28))  # 1-indexed columns that hold currency

        for col, hdr in enumerate(HEADERS, start=1):
            c = ws1.cell(row=hdr_row, column=col, value=hdr)
            c.fill      = _fill(NAVY)
            c.font      = _font(bold=True, color=WHITE, size=9)
            c.alignment = _align('center', 'center', wrap=True)
            c.border    = _border()

        # ── Data rows ────────────────────────────────────────────────────────
        first_data = hdr_row + 1
        for sn, p in enumerate(ready, start=1):
            emp   = p.employee
            drow  = first_data + sn - 1
            ws1.row_dimensions[drow].height = 16
            bg = LIGHT if sn % 2 == 0 else WHITE
            full_name   = f"{emp.first_name} {emp.last_name}".strip()
            narration   = (f"SALARY/{MONTHS[run.period_month][:3].upper()}"
                           f"-{run.period_year}/{emp.employee_id}")
            gross_total = _d(p.gross_salary) + _d(p.bonus_amount) + _d(p.overtime_amount)

            row_data = [
                sn,
                emp.employee_id,
                full_name,
                emp.job_title,
                emp.department or '',
                emp.bank_name or '',
                emp.account_number or '',
                emp.account_name or full_name,
                emp.bank_code or '',
                _d(p.basic_salary),
                _d(p.housing_allowance),
                _d(p.transport_allowance),
                _d(p.leave_allowance),
                _d(p.other_allowances),
                _d(p.gross_salary),
                _d(p.bonus_amount),
                _d(p.overtime_amount),
                gross_total,
                _d(p.employee_pension),
                _d(p.nhf),
                _d(p.nsitf),
                _d(p.paye_tax),
                _d(p.attendance_deduction),
                _d(p.loan_deductions),
                _d(p.penalty_deductions),
                _d(p.total_deductions),
                _d(p.net_salary),
                emp.pfa_name or '',
                emp.pfa_number or '',
                emp.tin or '',
                narration,
            ]
            for col, val in enumerate(row_data, start=1):
                c = ws1.cell(row=drow, column=col, value=val)
                c.fill      = _fill(bg)
                c.border    = _border()
                c.font      = Font(name='Calibri', size=9, color='1A1A2E')
                if col in MONEY_COLS:
                    c.number_format = MONEY_FMT
                    c.alignment     = _align('right')
                elif col == 1:
                    c.alignment = _align('center')
                else:
                    c.alignment = _align('left')

        # ── Totals row ───────────────────────────────────────────────────────
        tot_row = first_data + len(ready)
        ws1.row_dimensions[tot_row].height = 18
        totals_map = {
            1:  'TOTALS',
            10: tot_basic,   11: tot_housing,  12: tot_transport,
            13: tot_leave,   14: tot_other,    15: tot_gross,
            16: tot_bonus,   17: tot_overtime, 18: tot_earnings,
            19: tot_pen_emp, 20: tot_nhf,      21: tot_nsitf,
            22: tot_paye,    23: tot_att,      24: tot_loan,
            25: tot_penalty, 26: tot_deduct,   27: tot_net,
        }
        for col in range(1, len(HEADERS) + 1):
            c = ws1.cell(row=tot_row, column=col,
                          value=totals_map.get(col, ''))
            c.fill      = _fill(GOLD)
            c.font      = Font(name='Calibri', bold=True, color=NAVY, size=9)
            c.border    = _border('medium')
            if col in MONEY_COLS:
                c.number_format = MONEY_FMT
                c.alignment     = _align('right')
            elif col == 1:
                c.alignment = _align('center')
            else:
                c.alignment = _align('left')

        # Confidentiality footer
        footer_row = tot_row + 2
        ws1.merge_cells(start_row=footer_row, start_column=1,
                         end_row=footer_row,   end_column=TOTAL_COLS)
        fc = ws1.cell(row=footer_row, column=1,
                       value=(
                           'CONFIDENTIAL — This document contains sensitive payroll '
                           'and banking information. Authorised recipients only. '
                           f'Generated by {org.name} on {generated_on}.'
                       ))
        fc.font      = _font(italic=True, color='6B7280', size=8)
        fc.alignment = _align('center')

        # Column widths (Sheet 1)
        _set_col_widths(ws1, [
            5,   # S/N
            12,  # Employee ID
            24,  # Full Name
            20,  # Job Title
            18,  # Department
            22,  # Bank Name
            18,  # Account Number
            24,  # Account Name
            10,  # Bank Code
            14,  # Basic
            14,  # Housing
            14,  # Transport
            14,  # Leave
            14,  # Other
            14,  # Gross
            12,  # Bonus
            12,  # Overtime
            14,  # Total Earnings
            14,  # Pension emp
            12,  # NHF
            12,  # NSITF
            13,  # PAYE
            14,  # Attendance
            13,  # Loan
            13,  # Penalty
            15,  # Total Deductions
            16,  # NET PAY
            22,  # PFA
            18,  # RSA PIN
            16,  # TIN
            38,  # Narration
        ])
        _freeze(ws1, f'A{hdr_row + 1}')

        # ═══════════════════════════════════════════════════════════════════════
        # SHEET 2 — Statutory Remittance Summary
        # ═══════════════════════════════════════════════════════════════════════
        ws2 = wb.create_sheet('Statutory Summary')
        ws2.sheet_view.showGridLines = False

        ws2.merge_cells('A1:E1')
        t2 = ws2.cell(row=1, column=1, value='STATUTORY REMITTANCE SUMMARY')
        t2.fill      = _fill(NAVY)
        t2.font      = Font(name='Calibri', bold=True, color=WHITE, size=14)
        t2.alignment = _align('center', 'center')
        ws2.row_dimensions[1].height = 32

        ws2.merge_cells('A2:E2')
        s2 = ws2.cell(row=2, column=1,
                       value=f"{org.name}  ·  {period_label}  ·  Ref: {run.run_number}")
        s2.fill      = _fill(GOLD)
        s2.font      = Font(name='Calibri', bold=True, color=NAVY, size=10)
        s2.alignment = _align('center', 'center')
        ws2.row_dimensions[2].height = 18

        # Table header
        for col, hdr in enumerate(
            ['Statutory Obligation', 'Rate / Basis', f'Amount ({curr})',
             'Remittance Deadline', 'Remit To'],
            start=1,
        ):
            c = ws2.cell(row=4, column=col, value=hdr)
            c.fill      = _fill(NAVY)
            c.font      = _font(bold=True, color=WHITE, size=10)
            c.alignment = _align('center', 'center', wrap=True)
            c.border    = _border()
        ws2.row_dimensions[4].height = 28

        stat_data = [
            # Employee deductions (already in net pay calc)
            ('Employee Pension Contribution',
             '8% of (Basic + Housing + Transport)',
             tot_pen_emp,
             '7th of following month',
             'Pension Fund Administrator (PFA)'),
            ('National Housing Fund (NHF)',
             '2.5% of Basic Salary',
             tot_nhf,
             '1st week of following month',
             'Federal Mortgage Bank of Nigeria (FMBN)'),
            ('NSITF Contribution (Employee)',
             '1% of Gross Salary',
             tot_nsitf,
             '1st week of following month',
             'NSITF Board'),
            ('PAYE Tax (Employee)',
             'Progressive brackets per Finance Act',
             tot_paye,
             '10th of following month',
             'State Internal Revenue Service (LIRS/SIRS)'),
            # Employer obligations (additional cost to company)
            ('Employer Pension Contribution',
             '10% of (Basic + Housing + Transport)',
             tot_pen_er,
             '7th of following month',
             'Pension Fund Administrator (PFA)'),
            ('Net Salary Bank Transfer',
             'Total net pay for all employees',
             tot_net,
             payment_date,
             'Employees\' bank accounts via NIBSS NIP'),
        ]

        for i, (obligation, rate, amount, deadline, remit_to) in \
                enumerate(stat_data, start=5):
            bg = LIGHT if i % 2 == 0 else WHITE
            ws2.row_dimensions[i].height = 18
            is_employer = 'Employer' in obligation or 'Transfer' in obligation
            row_vals = [obligation, rate, amount, deadline, remit_to]
            for col, val in enumerate(row_vals, start=1):
                c = ws2.cell(row=i, column=col, value=val)
                c.fill      = _fill(bg)
                c.font      = Font(
                    name='Calibri', size=9, color='1A1A2E',
                    bold=(col == 3 and is_employer),
                )
                c.border    = _border()
                c.alignment = _align('left' if col != 3 else 'right',
                                     wrap=(col == 1))
                if col == 3:
                    c.number_format = MONEY_FMT

        # Grand total
        grand_row = len(stat_data) + 5
        ws2.row_dimensions[grand_row].height = 20
        labels = ['TOTAL EMPLOYER OBLIGATION', '(Pension + NHF + NSITF + PAYE + Net Pay)',
                  tot_pen_er + tot_nhf + tot_nsitf + tot_paye + tot_net, '', '']
        for col, val in enumerate(labels, start=1):
            c = ws2.cell(row=grand_row, column=col, value=val)
            c.fill      = _fill(GOLD)
            c.font      = Font(name='Calibri', bold=True, color=NAVY, size=10)
            c.border    = _border('medium')
            c.alignment = _align('right' if col == 3 else 'left')
            if col == 3:
                c.number_format = MONEY_FMT

        _set_col_widths(ws2, [38, 38, 18, 28, 42])

        # ═══════════════════════════════════════════════════════════════════════
        # SHEET 3 — Exceptions
        # ═══════════════════════════════════════════════════════════════════════
        ws3 = wb.create_sheet('Exceptions')
        ws3.sheet_view.showGridLines = False

        ws3.merge_cells('A1:L1')
        t3 = ws3.cell(row=1, column=1,
                       value='EXCEPTIONS — INCOMPLETE BANK DETAILS')
        t3.fill      = PatternFill('solid', fgColor='8B0000')
        t3.font      = Font(name='Calibri', bold=True, color=WHITE, size=14)
        t3.alignment = _align('center', 'center')
        ws3.row_dimensions[1].height = 30

        ws3.merge_cells('A2:L2')
        s3 = ws3.cell(row=2, column=1,
                       value=(f"{len(exceptions)} employee(s) excluded from bank transfer — "
                              "update their bank details and re-run."))
        s3.fill      = PatternFill('solid', fgColor='FFE4E4')
        s3.font      = Font(name='Calibri', italic=True, color=RED_TX, size=10)
        s3.alignment = _align('center')
        ws3.row_dimensions[2].height = 18

        exc_headers = [
            'S/N', 'Employee ID', 'Full Name', 'Job Title', 'Department',
            'Bank Name', 'Account Number', 'Account Name', 'Bank Code',
            f'Net Pay Due ({curr})', 'Missing Fields', 'Action Required',
        ]
        for col, hdr in enumerate(exc_headers, start=1):
            c = ws3.cell(row=4, column=col, value=hdr)
            c.fill      = PatternFill('solid', fgColor='8B0000')
            c.font      = _font(bold=True, color=WHITE, size=9)
            c.alignment = _align('center', 'center', wrap=True)
            c.border    = _border()
        ws3.row_dimensions[4].height = 28

        if exceptions:
            for sn, p in enumerate(exceptions, start=1):
                emp  = p.employee
                drow = sn + 4
                ws3.row_dimensions[drow].height = 16
                missing = []
                if not (emp.account_number or '').strip():
                    missing.append('Account Number')
                if not (emp.bank_code or '').strip():
                    missing.append('Bank Code')
                if not (emp.account_name or '').strip():
                    missing.append('Account Name')
                exc_row = [
                    sn,
                    emp.employee_id,
                    f"{emp.first_name} {emp.last_name}".strip(),
                    emp.job_title,
                    emp.department or '',
                    emp.bank_name or 'NOT SET',
                    emp.account_number or 'NOT SET',
                    emp.account_name or 'NOT SET',
                    emp.bank_code or 'NOT SET',
                    _d(p.net_salary),
                    ', '.join(missing),
                    'Update bank details in Payroll → Employees',
                ]
                for col, val in enumerate(exc_row, start=1):
                    c = ws3.cell(row=drow, column=col, value=val)
                    c.fill      = _fill(RED_BG)
                    c.font      = Font(name='Calibri', size=9, color=RED_TX)
                    c.border    = _border()
                    c.alignment = _align(
                        'right' if col == 10 else 'center' if col == 1 else 'left'
                    )
                    if col == 10:
                        c.number_format = MONEY_FMT
        else:
            ws3.merge_cells('A5:L5')
            ok = ws3.cell(row=5, column=1,
                           value='✓  No exceptions — all employees have complete bank details.')
            ok.fill      = PatternFill('solid', fgColor='E6F9EC')
            ok.font      = Font(name='Calibri', color='166534', bold=True, size=10)
            ok.alignment = _align('center')

        _set_col_widths(ws3, [5, 12, 24, 20, 18, 22, 18, 24, 10, 16, 30, 36])

        # ── Serialize and respond ────────────────────────────────────────────────
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        filename = (f'{run.run_number}-payroll-bank-file-'
                    f'{run.period_year}{run.period_month:02d}.xlsx')
        response = HttpResponse(
            buf.read(),
            content_type=(
                'application/vnd.openxmlformats-officedocument'
                '.spreadsheetml.sheet'
            ),
        )
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
