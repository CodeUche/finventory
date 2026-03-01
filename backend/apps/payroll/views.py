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
        run = PayrollService.run_payroll(run)
        return Response(PayrollRunSerializer(run).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        run = self.get_object()
        if run.status != PayrollRun.PROCESSING:
            return Response({'error': 'Only processing payrolls can be approved'}, status=400)
        run.status = PayrollRun.APPROVED
        run.approved_by = request.user
        run.save()
        return Response(PayrollRunSerializer(run).data)

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        run = self.get_object()
        from django.utils import timezone
        run.status = PayrollRun.PAID
        run.payment_date = request.data.get('payment_date', timezone.now().date())
        run.save()
        return Response(PayrollRunSerializer(run).data)
