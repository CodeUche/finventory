from rest_framework import serializers
from .models import Employee, PayrollRun, PayslipLine


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


class PayslipLineSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    employee_id_str = serializers.CharField(source='employee.employee_id', read_only=True)
    employee_bank_name = serializers.CharField(source='employee.bank_name', read_only=True)
    employee_bank_code = serializers.CharField(source='employee.bank_code', read_only=True)
    employee_account_number = serializers.CharField(source='employee.account_number', read_only=True)
    employee_account_name = serializers.CharField(source='employee.account_name', read_only=True)

    class Meta:
        model = PayslipLine
        fields = [
            'id', 'employee', 'employee_name', 'employee_id_str',
            'employee_bank_name', 'employee_bank_code', 'employee_account_number', 'employee_account_name',
            'basic_salary', 'housing_allowance', 'transport_allowance', 'leave_allowance',
            'other_allowances', 'gross_salary', 'employee_pension', 'nhf', 'nsitf',
            'consolidated_relief_allowance', 'taxable_income', 'paye_tax',
            'employer_pension', 'total_deductions', 'net_salary', 'status'
        ]
        read_only_fields = ['id']

    def get_employee_name(self, obj):
        return f"{obj.employee.first_name} {obj.employee.last_name}"


class PayrollRunSerializer(serializers.ModelSerializer):
    payslips = PayslipLineSerializer(many=True, read_only=True)

    class Meta:
        model = PayrollRun
        fields = [
            'id', 'run_number', 'period_year', 'period_month', 'status',
            'total_gross', 'total_deductions', 'total_net', 'total_paye',
            'total_pension_employee', 'total_pension_employer', 'total_nhf', 'total_nsitf',
            'payment_date', 'transfer_reference', 'created_at', 'payslips'
        ]
        read_only_fields = ['id', 'run_number', 'created_at', 'total_gross', 'total_deductions',
                           'total_net', 'total_paye', 'total_pension_employee', 'total_pension_employer',
                           'total_nhf', 'total_nsitf', 'transfer_reference']
