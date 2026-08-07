"""
Employee self-service endpoints, mounted under /api/v1/me/.

Every queryset here is filtered to ``request.employee`` — the single Employee
record linked to the calling user — and never to the organisation header. That
is deliberate: the header is client-supplied, the OneToOne is not.
"""

from datetime import date

from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    AdvanceRequest, Attendance, EmployeeBenefit, EmployeeDocument, EmployeeLoan,
    LeaveBalance, LeaveRequest, LeaveType, PayslipLine,
)
from .permissions import IsEmployeeSelf
from .serializers import (
    AdvanceRequestSerializer, AttendanceSerializer, EmployeeBenefitSerializer,
    EmployeeDocumentSerializer, EmployeeLoanSerializer, EmployeeSerializer,
    LeaveBalanceSerializer, LeaveRequestSerializer, LeaveTypeSerializer,
    PayslipLineSerializer,
)
from .services import EWAService, LeaveService


class MeProfileView(APIView):
    """GET/PATCH /me/profile/ — the employee's own record."""

    permission_classes = [IsAuthenticated, IsEmployeeSelf]

    # Fields an employee may change about themselves. Pay, job title, manager
    # and statutory identifiers are deliberately absent.
    EDITABLE = {
        'phone', 'address', 'next_of_kin_name', 'next_of_kin_phone',
        'next_of_kin_relationship', 'emergency_contact_name',
        'emergency_contact_phone', 'marital_status', 'annual_rent',
    }

    def get(self, request):
        return Response(EmployeeSerializer(request.employee).data)

    def patch(self, request):
        employee = request.employee
        payload = {k: v for k, v in request.data.items() if k in self.EDITABLE}
        rejected = sorted(set(request.data) - self.EDITABLE)
        if not payload:
            return Response(
                {'error': 'None of the supplied fields can be changed from the portal.',
                 'rejected': rejected},
                status=400,
            )
        for field, value in payload.items():
            setattr(employee, field, value)
        employee.save(update_fields=list(payload.keys()))
        data = EmployeeSerializer(employee).data
        if rejected:
            data['ignored_fields'] = rejected
        return Response(data)


class MePayslipViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /me/payslips/ — the employee's own payslips."""

    serializer_class = PayslipLineSerializer
    permission_classes = [IsAuthenticated, IsEmployeeSelf]

    def get_queryset(self):
        employee = self.request.employee
        return (
            PayslipLine.objects
            .filter(employee=employee)
            .select_related('employee', 'payroll_run', 'tax_authority')
            .order_by('-payroll_run__period_year', '-payroll_run__period_month')
        )

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        data = []
        for slip in qs:
            row = PayslipLineSerializer(slip).data
            run = slip.payroll_run
            row['period_year'] = run.period_year
            row['period_month'] = run.period_month
            row['run_number'] = run.run_number
            row['run_status'] = run.status
            row['payment_date'] = run.payment_date
            data.append(row)
        return Response(data)

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        """GET /me/payslips/{id}/pdf/ — server-rendered payslip download."""
        from .pdf import build_payslip_pdf

        payslip = self.get_object()
        pdf_bytes = build_payslip_pdf(payslip)
        run = payslip.payroll_run
        filename = f"Payslip-{payslip.employee.employee_id}-{run.period_year}{run.period_month:02d}.pdf"
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class MeLeaveRequestViewSet(viewsets.ModelViewSet):
    """GET/POST /me/leave-requests/ — raise and track own leave."""

    serializer_class = LeaveRequestSerializer
    permission_classes = [IsAuthenticated, IsEmployeeSelf]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return (
            LeaveRequest.objects
            .filter(employee=self.request.employee)
            .select_related('leave_type', 'decided_by')
        )

    def create(self, request, *args, **kwargs):
        from decimal import Decimal

        employee = request.employee
        # request.data may be a QueryDict (form-encoded) — dict() on one wraps
        # every value in a list, which the serializer then rejects. Copy through
        # the mapping API so both JSON and form bodies behave the same.
        data = {key: request.data.get(key) for key in request.data}
        # The employee is taken from the session, never from the request body,
        # so a crafted payload cannot book leave for a colleague.
        data['employee'] = str(employee.id)
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

        leave_type = serializer.validated_data['leave_type']
        if leave_type.organisation_id != employee.organisation_id:
            return Response({'error': 'Unknown leave type.'}, status=400)

        days = LeaveRequest.working_days_between(
            serializer.validated_data['start_date'], serializer.validated_data['end_date']
        )
        if days <= 0:
            return Response(
                {'error': 'That range contains no working days.'}, status=400,
            )

        balance = LeaveService.get_or_create_balance(
            employee, leave_type, serializer.validated_data['start_date'].year
        )
        if leave_type.is_paid and days > balance.available_days:
            return Response(
                {'error': f'You have {balance.available_days} days available '
                          f'but requested {days}.'},
                status=400,
            )

        approver = (
            employee.manager.user
            if (employee.manager and employee.manager.user_id) else None
        )
        instance = serializer.save(
            organisation=employee.organisation,
            employee=employee,
            days=days,
            approver=approver,
            status=LeaveRequest.PENDING,
        )
        balance.pending_days = Decimal(str(balance.pending_days)) + days
        balance.save(update_fields=['pending_days'])
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        leave_request = self.get_object()
        if leave_request.status not in [LeaveRequest.PENDING, LeaveRequest.APPROVED]:
            return Response({'error': 'This request can no longer be cancelled.'}, status=400)
        LeaveService.cancel(leave_request, user=request.user)
        leave_request.refresh_from_db()
        return Response(LeaveRequestSerializer(leave_request).data)


class MeLeaveBalanceView(APIView):
    """GET /me/leave-balances/ — own balances for a year."""

    permission_classes = [IsAuthenticated, IsEmployeeSelf]

    def get(self, request):
        employee = request.employee
        year = int(request.query_params.get('year') or date.today().year)
        # Make sure a balance row exists for every active type, so a new
        # employee sees their entitlement rather than an empty list.
        for leave_type in LeaveType.objects.filter(
            organisation=employee.organisation, is_active=True
        ):
            if leave_type.gender_restriction and employee.gender != leave_type.gender_restriction:
                continue
            LeaveService.get_or_create_balance(employee, leave_type, year)
        balances = (
            LeaveBalance.objects
            .filter(employee=employee, year=year)
            .select_related('leave_type', 'employee')
        )
        return Response(LeaveBalanceSerializer(balances, many=True).data)


class MeLeaveTypeView(APIView):
    """GET /me/leave-types/ — types this employee may request."""

    permission_classes = [IsAuthenticated, IsEmployeeSelf]

    def get(self, request):
        employee = request.employee
        qs = LeaveType.objects.filter(organisation=employee.organisation, is_active=True)
        allowed = [
            t for t in qs
            if not t.gender_restriction or t.gender_restriction == employee.gender
        ]
        return Response(LeaveTypeSerializer(allowed, many=True).data)


class MeDocumentViewSet(viewsets.ModelViewSet):
    """
    GET /me/documents/ — own HR documents.
    POST /me/documents/ — employee-initiated upload, restricted to a subset of
    document types (never 'contract' — that stays an HR-authored record type).
    Self-uploads are flagged uploaded_by_employee=True and start unreviewed, so
    HR can tell an official record from something an employee submitted.
    """

    serializer_class = EmployeeDocumentSerializer
    permission_classes = [IsAuthenticated, IsEmployeeSelf]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return EmployeeDocument.objects.filter(employee=self.request.employee)

    def create(self, request, *args, **kwargs):
        employee = request.employee
        document_type = request.data.get('document_type', EmployeeDocument.OTHER)
        if document_type not in EmployeeDocument.EMPLOYEE_UPLOADABLE_TYPES:
            return Response(
                {'error': (
                    f"You may only upload these document types from the portal: "
                    f"{', '.join(EmployeeDocument.EMPLOYEE_UPLOADABLE_TYPES)}"
                )},
                status=400,
            )
        file = request.FILES.get('file')
        if not file:
            return Response({'error': 'A file is required.'}, status=400)

        doc = EmployeeDocument.objects.create(
            organisation=employee.organisation,
            employee=employee,
            name=request.data.get('name') or file.name,
            document_type=document_type,
            file=file,
            file_size=file.size,
            expiry_date=request.data.get('expiry_date') or None,
            uploaded_by_employee=True,
        )
        return Response(
            EmployeeDocumentSerializer(doc, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class MeLoanView(APIView):
    """GET /me/loans/ — own loans and outstanding balances."""

    permission_classes = [IsAuthenticated, IsEmployeeSelf]

    def get(self, request):
        loans = EmployeeLoan.objects.filter(employee=request.employee)
        return Response(EmployeeLoanSerializer(loans, many=True).data)


class MeBenefitView(APIView):
    """GET /me/benefits/ — own benefit enrolments."""

    permission_classes = [IsAuthenticated, IsEmployeeSelf]

    def get(self, request):
        enrolments = (
            EmployeeBenefit.objects
            .filter(employee=request.employee, is_active=True)
            .select_related('plan')
        )
        return Response(EmployeeBenefitSerializer(enrolments, many=True).data)


class MeAttendanceView(APIView):
    """GET /me/attendance/?year=&month= — own attendance for a month."""

    permission_classes = [IsAuthenticated, IsEmployeeSelf]

    def get(self, request):
        today = date.today()
        year = int(request.query_params.get('year') or today.year)
        month = int(request.query_params.get('month') or today.month)
        rows = Attendance.objects.filter(
            employee=request.employee, date__year=year, date__month=month,
        )
        return Response(AttendanceSerializer(rows, many=True).data)


class MeAdvanceViewSet(viewsets.ModelViewSet):
    """GET/POST /me/advances/ — request an advance on wages already earned."""

    serializer_class = AdvanceRequestSerializer
    permission_classes = [IsAuthenticated, IsEmployeeSelf]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return AdvanceRequest.objects.filter(employee=self.request.employee)

    def create(self, request, *args, **kwargs):
        try:
            advance = EWAService.request(
                request.employee,
                request.data.get('amount'),
                request.data.get('reason', ''),
            )
        except ValueError as exc:
            return Response({'error': str(exc)}, status=400)
        return Response(
            AdvanceRequestSerializer(advance).data, status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=['get'])
    def eligibility(self, request):
        info = EWAService.eligibility(request.employee)
        return Response({
            k: (str(v) if hasattr(v, 'quantize') else v) for k, v in info.items()
        })


class MeSummaryView(APIView):
    """GET /me/summary/ — everything the portal landing page needs, in one call."""

    permission_classes = [IsAuthenticated, IsEmployeeSelf]

    def get(self, request):
        employee = request.employee
        today = date.today()

        latest_slip = (
            PayslipLine.objects
            .filter(employee=employee)
            .select_related('payroll_run', 'tax_authority')
            .order_by('-payroll_run__period_year', '-payroll_run__period_month')
            .first()
        )
        payslip_data = None
        if latest_slip:
            payslip_data = PayslipLineSerializer(latest_slip).data
            payslip_data['period_year'] = latest_slip.payroll_run.period_year
            payslip_data['period_month'] = latest_slip.payroll_run.period_month
            payslip_data['run_status'] = latest_slip.payroll_run.status
            payslip_data['payment_date'] = latest_slip.payroll_run.payment_date

        for leave_type in LeaveType.objects.filter(
            organisation=employee.organisation, is_active=True, is_paid=True
        ):
            if leave_type.gender_restriction and employee.gender != leave_type.gender_restriction:
                continue
            LeaveService.get_or_create_balance(employee, leave_type, today.year)
        balances = (
            LeaveBalance.objects
            .filter(employee=employee, year=today.year)
            .select_related('leave_type', 'employee')
        )

        try:
            advance_info = EWAService.eligibility(employee)
            advance_info = {
                k: (str(v) if hasattr(v, 'quantize') else v)
                for k, v in advance_info.items()
            }
        except Exception:
            advance_info = None

        return Response({
            'employee': EmployeeSerializer(employee).data,
            'organisation': {
                'id': str(employee.organisation_id),
                'name': employee.organisation.name,
                'currency': getattr(employee.organisation, 'currency', 'NGN'),
            },
            'latest_payslip': payslip_data,
            'leave_balances': LeaveBalanceSerializer(balances, many=True).data,
            'open_leave_requests': LeaveRequest.objects.filter(
                employee=employee, status=LeaveRequest.PENDING
            ).count(),
            'advance': advance_info,
            'outstanding_loans': EmployeeLoanSerializer(
                EmployeeLoan.objects.filter(employee=employee, status=EmployeeLoan.ACTIVE),
                many=True,
            ).data,
        })
