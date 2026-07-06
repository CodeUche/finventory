from rest_framework import serializers
from .models import (
    Attendance, Bonus, Employee, EmployeeDocument, EmployeeLoan,
    EmployeePenalty, EmployeeTaxProfile, PAYERemittance, PayrollRun, PayslipLine,
)


class EmployeeSerializer(serializers.ModelSerializer):
    gross_salary = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            'id', 'employee_id', 'first_name', 'last_name', 'full_name', 'email', 'phone',
            'job_title', 'department', 'employment_type', 'hire_date', 'termination_date',
            'bank_name', 'bank_code', 'account_number', 'account_name', 'paystack_recipient_code',
            'pfa_name', 'pfa_number', 'tin',
            'basic_salary', 'housing_allowance', 'transport_allowance', 'leave_allowance',
            'other_allowances', 'gross_salary', 'is_active', 'created_at'
        ]
        read_only_fields = ['id', 'employee_id', 'paystack_recipient_code', 'created_at']

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}"


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


class PayslipLineSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    employee_id_str = serializers.CharField(source='employee.employee_id', read_only=True)
    employee_bank_name = serializers.CharField(source='employee.bank_name', read_only=True)
    employee_bank_code = serializers.CharField(source='employee.bank_code', read_only=True)
    employee_account_number = serializers.CharField(source='employee.account_number', read_only=True)
    employee_account_name = serializers.CharField(source='employee.account_name', read_only=True)
    paye_bracket_breakdown = serializers.SerializerMethodField()

    class Meta:
        model = PayslipLine
        fields = [
            'id', 'employee', 'employee_name', 'employee_id_str',
            'employee_bank_name', 'employee_bank_code', 'employee_account_number', 'employee_account_name',
            'basic_salary', 'housing_allowance', 'transport_allowance', 'leave_allowance',
            'other_allowances', 'gross_salary', 'bonus_amount', 'overtime_amount',
            'employee_pension', 'nhf', 'nsitf',
            'consolidated_relief_allowance', 'rent_relief', 'taxable_income', 'paye_tax',
            'employer_pension', 'penalty_deductions', 'loan_deductions', 'attendance_deduction',
            'total_deductions', 'net_salary', 'status',
            'transfer_status', 'transfer_reference', 'transfer_error',
            'paye_bracket_breakdown',
        ]
        read_only_fields = ['id']

    def get_employee_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"

    def get_paye_bracket_breakdown(self, obj):
        """Compute per-bracket PAYE detail from stored taxable_income (monthly → annualised)."""
        from decimal import Decimal
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
    target_approver_name = serializers.SerializerMethodField()

    class Meta:
        model = PayrollRun
        fields = [
            'id', 'run_number', 'period_year', 'period_month', 'status',
            'total_gross', 'total_deductions', 'total_net', 'total_paye',
            'total_pension_employee', 'total_pension_employer', 'total_nhf', 'total_nsitf',
            'total_bonus', 'total_overtime',
            'submitted_for_approval', 'submitted_by', 'target_approver', 'target_approver_name',
            'payment_date', 'transfer_reference', 'created_at', 'payslips', 'employee_count',
        ]
        read_only_fields = [
            'id', 'run_number', 'created_at',
            'total_gross', 'total_deductions', 'total_net', 'total_paye',
            'total_pension_employee', 'total_pension_employer', 'total_nhf', 'total_nsitf',
            'total_bonus', 'total_overtime',
            'transfer_reference', 'submitted_for_approval', 'submitted_by', 'target_approver_name', 'employee_count',
        ]

    def get_employee_count(self, obj):
        return obj.payslips.count()

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


class PAYERemittanceSerializer(serializers.ModelSerializer):
    run_number = serializers.CharField(source='payroll_run.run_number', read_only=True)
    balance_due = serializers.SerializerMethodField()

    class Meta:
        model = PAYERemittance
        fields = [
            'id', 'payroll_run', 'run_number', 'period_year', 'period_month',
            'amount_due', 'amount_paid', 'balance_due', 'status',
            'due_date', 'remittance_date', 'reference', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'payroll_run', 'run_number', 'period_year', 'period_month', 'amount_due', 'created_at']

    def get_balance_due(self, obj):
        from decimal import Decimal
        return max(Decimal('0'), Decimal(str(obj.amount_due)) - Decimal(str(obj.amount_paid)))
