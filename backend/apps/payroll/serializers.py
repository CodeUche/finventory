from decimal import Decimal

from rest_framework import serializers

from .models import (
    AdvancePolicy, AdvanceRequest, Attendance, BenefitPlan, Bonus, CompensationRecord,
    Employee, EmployeeBenefit, EmployeeDocument, EmployeeLoan, EmployeePenalty,
    EmployeeTaxProfile, LeaveBalance, LeaveRequest, LeaveType, PayrollAdjustment,
    PayrollRun, PayrollSettings, PayslipDelivery, PayslipLine, StatutoryRemittance,
    TaxAuthority,
)


class TaxAuthoritySerializer(serializers.ModelSerializer):
    state_label = serializers.CharField(source='get_state_code_display', read_only=True)

    class Meta:
        model = TaxAuthority
        fields = ['id', 'state_code', 'state_label', 'name', 'portal_url', 'payer_id', 'is_active']
        read_only_fields = ['id', 'state_label']


class EmployeeSerializer(serializers.ModelSerializer):
    gross_salary = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    full_name = serializers.SerializerMethodField()
    manager_name = serializers.SerializerMethodField()
    state_label = serializers.CharField(source='get_state_of_residence_display', read_only=True)
    has_portal_access = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            'id', 'employee_id', 'first_name', 'last_name', 'full_name', 'email', 'phone',
            'job_title', 'department', 'employment_type', 'hire_date', 'termination_date',
            # HR master data
            'date_of_birth', 'gender', 'marital_status', 'nin', 'address',
            'next_of_kin_name', 'next_of_kin_phone', 'next_of_kin_relationship',
            'emergency_contact_name', 'emergency_contact_phone',
            'manager', 'manager_name', 'grade', 'confirmation_date', 'contract_end_date',
            'has_portal_access',
            # Banking
            'bank_name', 'bank_code', 'account_number', 'account_name', 'paystack_recipient_code',
            # Statutory
            'pfa_name', 'pfa_number', 'pension_pin', 'tin',
            'state_of_residence', 'state_label', 'annual_rent',
            # Pay
            'basic_salary', 'housing_allowance', 'transport_allowance', 'leave_allowance',
            'other_allowances', 'gross_salary', 'is_active', 'created_at',
        ]
        read_only_fields = [
            'id', 'employee_id', 'paystack_recipient_code', 'created_at',
            'full_name', 'manager_name', 'state_label', 'has_portal_access',
        ]

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"

    def get_manager_name(self, obj):
        if obj.manager_id and obj.manager:
            return f"{obj.manager.first_name} {obj.manager.last_name}".strip()
        return None

    def get_has_portal_access(self, obj):
        return obj.user_id is not None

    def validate_manager(self, value):
        """An employee cannot manage themselves, nor create a reporting cycle."""
        if value is None:
            return value
        instance = self.instance
        if instance and value.id == instance.id:
            raise serializers.ValidationError("An employee cannot be their own manager.")
        if instance:
            seen = set()
            cursor = value
            while cursor is not None:
                if cursor.id == instance.id:
                    raise serializers.ValidationError(
                        "That would create a circular reporting line."
                    )
                if cursor.id in seen:
                    break
                seen.add(cursor.id)
                cursor = cursor.manager
        return value


class CompensationRecordSerializer(serializers.ModelSerializer):
    gross_salary = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    employee_name = serializers.SerializerMethodField()

    class Meta:
        model = CompensationRecord
        fields = [
            'id', 'employee', 'employee_name', 'effective_date', 'reason',
            'basic_salary', 'housing_allowance', 'transport_allowance',
            'leave_allowance', 'other_allowances', 'gross_salary', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'employee_name', 'gross_salary', 'created_at']

    def get_employee_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"


class PayrollAdjustmentSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()

    class Meta:
        model = PayrollAdjustment
        fields = [
            'id', 'employee', 'employee_name', 'adjustment_type', 'amount', 'reason',
            'effective_period_year', 'effective_period_month', 'status',
            'applied_in_run', 'created_at',
        ]
        read_only_fields = ['id', 'employee_name', 'status', 'applied_in_run', 'created_at']

    def get_employee_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"


class EmployeeDocumentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    file_size_display = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeDocument
        fields = [
            'id', 'employee', 'name', 'document_type', 'file', 'file_url',
            'file_size', 'file_size_display', 'created_at',
        ]
        read_only_fields = ['id', 'file_url', 'file_size', 'file_size_display', 'created_at']

    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url if obj.file else None

    def get_file_size_display(self, obj):
        size = obj.file_size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"


class EmployeePenaltySerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeePenalty
        fields = [
            'id', 'employee', 'reason', 'amount', 'penalty_date',
            'status', 'applied_in_run', 'created_at',
        ]
        read_only_fields = ['id', 'applied_in_run', 'created_at']


class EmployeeLoanSerializer(serializers.ModelSerializer):
    balance_remaining = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)

    class Meta:
        model = EmployeeLoan
        fields = [
            'id', 'employee', 'principal_amount', 'interest_rate', 'duration_months',
            'start_date', 'total_repayable', 'monthly_installment',
            'amount_repaid', 'balance_remaining', 'status', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'total_repayable', 'monthly_installment', 'amount_repaid', 'created_at']


class BonusSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()

    class Meta:
        model = Bonus
        fields = [
            'id', 'employee', 'employee_name', 'amount', 'bonus_type', 'reason',
            'period_year', 'period_month', 'status', 'applied_in_run', 'created_at',
        ]
        read_only_fields = ['id', 'status', 'applied_in_run', 'created_at']

    def get_employee_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"


class AttendanceSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()

    class Meta:
        model = Attendance
        fields = [
            'id', 'employee', 'employee_name', 'date', 'status',
            'clock_in', 'clock_out', 'overtime_hours', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_employee_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"


# ── Leave ─────────────────────────────────────────────────────────────────────

class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = [
            'id', 'name', 'days_per_year', 'accrual_method', 'is_paid',
            'carry_forward_max', 'gender_restriction', 'requires_approval',
            'requires_document', 'is_active',
        ]
        read_only_fields = ['id']


class LeaveBalanceSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    leave_type_name = serializers.CharField(source='leave_type.name', read_only=True)
    available_days = serializers.DecimalField(max_digits=6, decimal_places=2, read_only=True)

    class Meta:
        model = LeaveBalance
        fields = [
            'id', 'employee', 'employee_name', 'leave_type', 'leave_type_name', 'year',
            'entitled_days', 'accrued_days', 'carried_forward', 'taken_days',
            'pending_days', 'available_days',
        ]
        read_only_fields = ['id', 'employee_name', 'leave_type_name', 'available_days']

    def get_employee_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"


class LeaveRequestSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    leave_type_name = serializers.CharField(source='leave_type.name', read_only=True)
    is_paid = serializers.BooleanField(source='leave_type.is_paid', read_only=True)
    balance_after = serializers.SerializerMethodField()
    decided_by_name = serializers.SerializerMethodField()

    class Meta:
        model = LeaveRequest
        fields = [
            'id', 'employee', 'employee_name', 'leave_type', 'leave_type_name', 'is_paid',
            'start_date', 'end_date', 'days', 'reason', 'status',
            'approver', 'decided_by', 'decided_by_name', 'decided_at', 'decision_note',
            'attachment', 'balance_after', 'created_at',
        ]
        read_only_fields = [
            'id', 'employee_name', 'leave_type_name', 'is_paid', 'days',
            'decided_by', 'decided_by_name', 'decided_at', 'balance_after', 'created_at',
        ]

    def get_employee_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"

    def get_decided_by_name(self, obj):
        if obj.decided_by:
            return f"{obj.decided_by.first_name} {obj.decided_by.last_name}".strip() or obj.decided_by.email
        return None

    def get_balance_after(self, obj):
        balance = LeaveBalance.objects.filter(
            employee=obj.employee, leave_type=obj.leave_type, year=obj.start_date.year,
        ).first()
        if not balance:
            return None
        remaining = balance.available_days
        if obj.status == LeaveRequest.PENDING:
            # pending_days already holds this request
            return str(remaining)
        return str(remaining)

    def validate(self, attrs):
        start = attrs.get('start_date', getattr(self.instance, 'start_date', None))
        end = attrs.get('end_date', getattr(self.instance, 'end_date', None))
        if start and end and end < start:
            raise serializers.ValidationError({'end_date': 'End date cannot be before the start date.'})
        employee = attrs.get('employee', getattr(self.instance, 'employee', None))
        leave_type = attrs.get('leave_type', getattr(self.instance, 'leave_type', None))
        if employee and leave_type and leave_type.gender_restriction:
            if employee.gender != leave_type.gender_restriction:
                raise serializers.ValidationError({
                    'leave_type': f"{leave_type.name} is restricted to "
                                  f"{leave_type.get_gender_restriction_display().lower()} employees.",
                })
        if start and end and employee:
            overlap = LeaveRequest.objects.filter(
                employee=employee,
                status__in=[LeaveRequest.PENDING, LeaveRequest.APPROVED],
                start_date__lte=end, end_date__gte=start,
            )
            if self.instance:
                overlap = overlap.exclude(pk=self.instance.pk)
            if overlap.exists():
                raise serializers.ValidationError(
                    'This employee already has leave booked over these dates.'
                )
        return attrs


# ── Benefits ──────────────────────────────────────────────────────────────────

class BenefitPlanSerializer(serializers.ModelSerializer):
    enrolled_count = serializers.SerializerMethodField()

    class Meta:
        model = BenefitPlan
        fields = [
            'id', 'name', 'benefit_type', 'provider_name', 'basis',
            'employee_contribution', 'employer_contribution', 'remittance_day',
            'is_active', 'notes', 'enrolled_count',
        ]
        read_only_fields = ['id', 'enrolled_count']

    def get_enrolled_count(self, obj):
        return obj.enrolments.filter(is_active=True).count()


class EmployeeBenefitSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    plan_name = serializers.CharField(source='plan.name', read_only=True)
    provider_name = serializers.CharField(source='plan.provider_name', read_only=True)

    class Meta:
        model = EmployeeBenefit
        fields = [
            'id', 'employee', 'employee_name', 'plan', 'plan_name', 'provider_name',
            'start_date', 'end_date', 'tier',
            'employee_contribution_override', 'employer_contribution_override',
            'is_active',
        ]
        read_only_fields = ['id', 'employee_name', 'plan_name', 'provider_name']

    def get_employee_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"


# ── Salary advances ───────────────────────────────────────────────────────────

class AdvancePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = AdvancePolicy
        fields = [
            'id', 'is_enabled', 'max_percent_of_accrued', 'fee_percent',
            'min_amount', 'max_requests_per_period', 'min_months_employed',
            'require_approval', 'min_cash_buffer',
        ]
        read_only_fields = ['id']


class AdvanceRequestSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    balance_outstanding = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)

    class Meta:
        model = AdvanceRequest
        fields = [
            'id', 'employee', 'employee_name', 'amount', 'fee', 'total_recoverable',
            'period_year', 'period_month', 'reason', 'status',
            'accrued_at_request', 'days_worked_at_request',
            'decided_by', 'decided_at', 'decision_note', 'disbursed_at',
            'amount_recovered', 'balance_outstanding', 'recovered_in_run', 'created_at',
        ]
        read_only_fields = [
            'id', 'employee_name', 'fee', 'total_recoverable', 'status',
            'accrued_at_request', 'days_worked_at_request', 'decided_by', 'decided_at',
            'disbursed_at', 'amount_recovered', 'balance_outstanding',
            'recovered_in_run', 'created_at',
        ]

    def get_employee_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"


# ── Payroll ───────────────────────────────────────────────────────────────────

class PayslipLineSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    employee_id_str = serializers.CharField(source='employee.employee_id', read_only=True)
    employee_bank_name = serializers.CharField(source='employee.bank_name', read_only=True)
    employee_bank_code = serializers.CharField(source='employee.bank_code', read_only=True)
    employee_account_number = serializers.CharField(source='employee.account_number', read_only=True)
    employee_account_name = serializers.CharField(source='employee.account_name', read_only=True)
    employee_email = serializers.CharField(source='employee.email', read_only=True)
    tax_authority_name = serializers.SerializerMethodField()
    paye_bracket_breakdown = serializers.SerializerMethodField()

    class Meta:
        model = PayslipLine
        fields = [
            'id', 'employee', 'employee_name', 'employee_id_str', 'employee_email',
            'employee_bank_name', 'employee_bank_code', 'employee_account_number', 'employee_account_name',
            'proration_factor', 'days_worked', 'days_in_period',
            'tax_authority', 'tax_authority_name',
            'basic_salary', 'housing_allowance', 'transport_allowance', 'leave_allowance',
            'other_allowances', 'gross_salary', 'bonus_amount', 'overtime_amount',
            'adjustment_amount',
            'employee_pension', 'nhf', 'nsitf',
            'consolidated_relief_allowance', 'rent_relief', 'taxable_income', 'paye_tax',
            'employer_pension', 'penalty_deductions', 'loan_deductions', 'attendance_deduction',
            'advance_deductions', 'benefit_deductions', 'benefit_employer_cost',
            'total_deductions', 'net_salary', 'status',
            'transfer_status', 'transfer_reference', 'transfer_error',
            'paye_bracket_breakdown',
        ]
        read_only_fields = ['id']

    def get_employee_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"

    def get_tax_authority_name(self, obj):
        return obj.tax_authority.name if obj.tax_authority_id else None

    def get_paye_bracket_breakdown(self, obj):
        """Compute per-bracket PAYE detail from stored taxable_income (monthly → annualised)."""
        from .services import PayrollService
        annual_taxable = Decimal(str(obj.taxable_income or 0)) * 12
        breakdown = []
        for lower, upper, rate in PayrollService.PAYE_BRACKETS:
            if annual_taxable <= lower:
                break
            bracket_upper = upper if upper is not None else annual_taxable
            taxable_in_bracket = min(annual_taxable, bracket_upper) - lower
            if taxable_in_bracket <= 0:
                continue
            annual_tax = (taxable_in_bracket * rate).quantize(Decimal('0.01'))
            monthly_tax = (annual_tax / 12).quantize(Decimal('0.01'))
            upper_label = f"{float(upper):,.0f}" if upper is not None else "∞"
            breakdown.append({
                "bracket": f"₦{float(lower):,.0f} – ₦{upper_label}",
                "rate": f"{float(rate * 100):.0f}%",
                "taxable_in_bracket_annual": float(taxable_in_bracket),
                "tax_annual": float(annual_tax),
                "tax_monthly": float(monthly_tax),
            })
        return breakdown


class PayrollRunSerializer(serializers.ModelSerializer):
    payslips = PayslipLineSerializer(many=True, read_only=True)
    employee_count = serializers.SerializerMethodField()
    prorated_count = serializers.SerializerMethodField()
    target_approver_name = serializers.SerializerMethodField()
    run_type_label = serializers.CharField(source='get_run_type_display', read_only=True)
    employer_cost = serializers.SerializerMethodField()

    class Meta:
        model = PayrollRun
        fields = [
            'id', 'run_number', 'period_year', 'period_month',
            'period_start', 'period_end', 'run_type', 'run_type_label', 'sequence',
            'pay_frequency', 'status',
            'total_gross', 'total_deductions', 'total_net', 'total_paye',
            'total_pension_employee', 'total_pension_employer', 'total_nhf', 'total_nsitf',
            'total_itf', 'total_benefits', 'total_benefits_employer',
            'total_bonus', 'total_overtime', 'employer_cost',
            'submitted_for_approval', 'submitted_by', 'target_approver', 'target_approver_name',
            'payment_date', 'transfer_reference', 'gl_post_status', 'gl_post_error',
            'created_at', 'payslips', 'employee_count', 'prorated_count',
        ]
        read_only_fields = [
            'id', 'run_number', 'created_at',
            'total_gross', 'total_deductions', 'total_net', 'total_paye',
            'total_pension_employee', 'total_pension_employer', 'total_nhf', 'total_nsitf',
            'total_itf', 'total_benefits', 'total_benefits_employer',
            'total_bonus', 'total_overtime', 'employer_cost', 'run_type_label',
            'gl_post_status', 'gl_post_error',
            'transfer_reference', 'submitted_for_approval', 'submitted_by',
            'target_approver_name', 'employee_count', 'prorated_count',
        ]

    def get_employee_count(self, obj):
        return obj.payslips.count()

    def get_prorated_count(self, obj):
        return obj.payslips.exclude(proration_factor=1).count()

    def get_employer_cost(self, obj):
        """
        Total cash the employer must fund for this run.

        Net pay plus every statutory amount withheld or borne. The old bank
        export omitted employee pension from this figure, understating the
        funding requirement by 8% of emoluments.
        """
        def _d(v):
            return Decimal(str(v or 0))
        return str(
            _d(obj.total_net)
            + _d(obj.total_paye)
            + _d(obj.total_pension_employee)
            + _d(obj.total_pension_employer)
            + _d(obj.total_nhf)
            + _d(obj.total_nsitf)
            + _d(obj.total_itf)
            + _d(obj.total_benefits)
            + _d(obj.total_benefits_employer)
        )

    def get_target_approver_name(self, obj):
        if obj.target_approver:
            name = f"{obj.target_approver.first_name} {obj.target_approver.last_name}".strip()
            return name or obj.target_approver.email
        return None


class EmployeeTaxProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeTaxProfile
        fields = [
            'id', 'employee', 'nhf_enrolled', 'voluntary_pension',
            'life_assurance_premium', 'paye_exempt', 'notes',
        ]
        read_only_fields = ['id']


class StatutoryRemittanceSerializer(serializers.ModelSerializer):
    run_number = serializers.CharField(source='payroll_run.run_number', read_only=True)
    type_label = serializers.CharField(source='get_remittance_type_display', read_only=True)
    authority_name = serializers.SerializerMethodField()
    balance_due = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    days_overdue = serializers.IntegerField(read_only=True)

    class Meta:
        model = StatutoryRemittance
        fields = [
            'id', 'payroll_run', 'run_number', 'remittance_type', 'type_label',
            'period_year', 'period_month', 'tax_authority', 'authority_name',
            'recipient_name', 'basis', 'amount_due', 'amount_paid', 'balance_due',
            'status', 'due_date', 'remittance_date', 'reference', 'notes',
            'gl_cleared', 'is_overdue', 'days_overdue', 'created_at',
        ]
        read_only_fields = [
            'id', 'payroll_run', 'run_number', 'type_label', 'authority_name',
            'period_year', 'period_month', 'amount_due', 'balance_due',
            'is_overdue', 'days_overdue', 'gl_cleared', 'created_at',
        ]

    def get_authority_name(self, obj):
        if obj.tax_authority_id and obj.tax_authority:
            return obj.tax_authority.name
        return obj.recipient_name


class PayslipDeliverySerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()

    class Meta:
        model = PayslipDelivery
        fields = [
            'id', 'payslip', 'employee_name', 'channel', 'recipient',
            'status', 'error', 'sent_by', 'created_at',
        ]
        read_only_fields = fields

    def get_employee_name(self, obj):
        return f"{obj.payslip.employee.first_name} {obj.payslip.employee.last_name}"


class PayrollSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollSettings
        fields = [
            'id', 'itf_applicable', 'itf_auto_assert', 'nsitf_applicable',
            'default_pay_frequency', 'leave_seeded', 'tax_authorities_seeded',
        ]
        read_only_fields = ['id', 'leave_seeded', 'tax_authorities_seeded']
