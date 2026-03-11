import json as _json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings as django_settings

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsManager, IsStaff
from .models import Employee, PayrollRun
from .serializers import EmployeeSerializer, PayrollRunSerializer
from .services import PayrollService


class EmployeeViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated, IsStaff]

    def get_queryset(self):
        org = self._get_organisation()
        return Employee.objects.filter(organisation=org)

    @action(detail=False, methods=["post"])
    def resolve_account(self, request):
        """POST /api/v1/payroll/employees/resolve_account/ — Resolve NUBAN account name via Paystack."""
        account_number = request.data.get("account_number", "").strip()
        bank_code = request.data.get("bank_code", "").strip()

        if not account_number or not bank_code:
            return Response(
                {"error": "account_number and bank_code are required"}, status=400
            )

        secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
        if not secret_key:
            return Response(
                {"error": "Account resolution is not configured. Add PAYSTACK_SECRET_KEY to your .env file."},
                status=503,
            )

        try:
            params = urllib.parse.urlencode(
                {"account_number": account_number, "bank_code": bank_code}
            )
            url = f"https://api.paystack.co/bank/resolve?{params}"
            req = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {secret_key}"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.loads(resp.read())
            return Response({"account_name": data["data"]["account_name"]})
        except urllib.error.HTTPError:
            return Response(
                {"error": "Could not resolve account. Verify the account number and bank."},
                status=400,
            )
        except Exception:
            return Response(
                {"error": "Account resolution service is currently unavailable."},
                status=503,
            )


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
            return Response({'error': f'The period {year}-{month:02d} is locked. Unlock it before running payroll.'}, status=403)
        run = PayrollService.run_payroll(run)
        return Response(PayrollRunSerializer(run).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        import logging as _log
        run = self.get_object()
        if run.status != PayrollRun.PROCESSING:
            return Response({'error': 'Only processing payrolls can be approved'}, status=400)
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
        return Response(PayrollRunSerializer(run).data)

    @action(detail=True, methods=['post'])
    def initiate_transfers(self, request, pk=None):
        """
        POST /payroll/runs/{id}/initiate_transfers/
        Creates Paystack transfer recipients for each employee (if not cached),
        then initiates a bulk transfer for all payslips in the run.
        Returns transfer results per employee.
        """
        import logging as _log
        logger = _log.getLogger(__name__)

        run = self.get_object()
        if run.status != PayrollRun.APPROVED:
            return Response({'error': 'Only approved payroll runs can initiate transfers'}, status=400)

        secret_key = getattr(django_settings, 'PAYSTACK_SECRET_KEY', '')
        if not secret_key:
            return Response({'error': 'Paystack is not configured. Add PAYSTACK_SECRET_KEY to your .env file.'}, status=503)

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

        for payslip in run.payslips.select_related('employee').all():
            emp = payslip.employee
            net = float(payslip.net_salary)

            if not emp.account_number or not emp.bank_code:
                results.append({
                    'employee': emp.employee_id,
                    'name': f'{emp.first_name} {emp.last_name}',
                    'status': 'skipped',
                    'reason': 'Missing bank account number or bank code',
                })
                continue

            # Step 1: Create/get recipient code
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
                    # Cache it on the employee record
                    emp.paystack_recipient_code = recipient_code
                    emp.save(update_fields=['paystack_recipient_code'])
                except Exception as e:
                    logger.warning('Paystack create recipient failed for %s: %s', emp.employee_id, e)
                    results.append({
                        'employee': emp.employee_id,
                        'name': f'{emp.first_name} {emp.last_name}',
                        'status': 'failed',
                        'reason': 'Could not create transfer recipient',
                    })
                    continue

            # Paystack amounts are in kobo (multiply by 100)
            transfers.append({
                'amount': int(net * 100),
                'recipient': recipient_code,
                'reason': f'Net pay — {run.run_number}',
                'reference': f'{run.run_number}-{emp.employee_id}',
            })
            results.append({
                'employee': emp.employee_id,
                'name': f'{emp.first_name} {emp.last_name}',
                'account': emp.account_number,
                'bank': emp.bank_name,
                'amount': net,
                'recipient_code': recipient_code,
                'status': 'queued',
            })

        if not transfers:
            return Response({
                'success': False,
                'message': 'No employees with complete bank details found',
                'results': results,
            }, status=400)

        # Step 2: Initiate bulk transfer
        try:
            bulk_resp = paystack_post('/transfer/bulk', {
                'currency': 'NGN',
                'source': 'balance',
                'transfers': transfers,
            })
            batch_code = bulk_resp.get('data', {}).get('batch_code', '') if isinstance(bulk_resp.get('data'), dict) else ''
            if not batch_code and isinstance(bulk_resp.get('data'), list):
                batch_code = ','.join(str(t.get('reference', '')) for t in bulk_resp['data'][:3])

            # Save reference on the run
            run.transfer_reference = batch_code or run.run_number
            run.save(update_fields=['transfer_reference'])

            # Update queued statuses with transfer codes from response
            if isinstance(bulk_resp.get('data'), list):
                for i, transfer_result in enumerate(bulk_resp['data']):
                    if i < len(results) and results[i]['status'] == 'queued':
                        results[i]['transfer_code'] = transfer_result.get('transfer_code', '')
                        results[i]['status'] = 'initiated'

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
            return Response({'success': False, 'error': 'Transfer service temporarily unavailable', 'results': results}, status=503)
