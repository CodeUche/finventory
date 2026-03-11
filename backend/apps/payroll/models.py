from django.db import models
from apps.core.models import TenantAwareModel, MoneyField
from apps.authentication.models import User


class Employee(TenantAwareModel):
    FULL_TIME = 'full_time'; PART_TIME = 'part_time'; CONTRACT = 'contract'
    TYPE_CHOICES = [(t, t) for t in [FULL_TIME, PART_TIME, CONTRACT]]

    employee_id = models.CharField(max_length=20, editable=False)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    job_title = models.CharField(max_length=200)
    department = models.CharField(max_length=200, blank=True)
    employment_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=FULL_TIME)
    hire_date = models.DateField()
    termination_date = models.DateField(null=True, blank=True)
    # Banking
    bank_name = models.CharField(max_length=200, blank=True)
    bank_code = models.CharField(max_length=20, blank=True, help_text="Paystack bank code (3-6 digit)")
    account_number = models.CharField(max_length=20, blank=True)
    account_name = models.CharField(max_length=200, blank=True)
    paystack_recipient_code = models.CharField(max_length=100, blank=True,
        help_text="Cached Paystack transfer recipient code (auto-populated on first transfer)")
    # Nigerian statutory
    pfa_name = models.CharField(max_length=200, blank=True)  # Pension Fund Administrator
    pfa_number = models.CharField(max_length=50, blank=True)
    tin = models.CharField(max_length=50, blank=True)  # Tax Identification Number
    # Salary components
    basic_salary = MoneyField(default=0)
    housing_allowance = MoneyField(default=0)
    transport_allowance = MoneyField(default=0)
    leave_allowance = MoneyField(default=0)
    other_allowances = MoneyField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['last_name', 'first_name']
        unique_together = [('organisation', 'employee_id')]

    def __str__(self):
        return f"{self.employee_id} - {self.first_name} {self.last_name}"

    @property
    def gross_salary(self):
        return (self.basic_salary + self.housing_allowance + self.transport_allowance +
                self.leave_allowance + self.other_allowances)

    def save(self, *args, **kwargs):
        if not self.employee_id:
            count = Employee.objects.filter(organisation=self.organisation).count()
            self.employee_id = f"EMP-{count + 1:03d}"
        super().save(*args, **kwargs)


class PayrollRun(TenantAwareModel):
    DRAFT = 'draft'; PROCESSING = 'processing'; APPROVED = 'approved'; PAID = 'paid'
    STATUS_CHOICES = [(s, s) for s in [DRAFT, PROCESSING, APPROVED, PAID]]

    run_number = models.CharField(max_length=20, editable=False)
    period_year = models.PositiveIntegerField()
    period_month = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    total_gross = MoneyField(default=0)
    total_deductions = MoneyField(default=0)
    total_net = MoneyField(default=0)
    total_paye = MoneyField(default=0)
    total_pension_employee = MoneyField(default=0)
    total_pension_employer = MoneyField(default=0)
    total_nhf = MoneyField(default=0)
    total_nsitf = MoneyField(default=0)
    processed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='payroll_runs_processed')
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='payroll_runs_approved')
    payment_date = models.DateField(null=True, blank=True)
    transfer_reference = models.CharField(max_length=200, blank=True,
        help_text="Paystack bulk transfer batch_transfer_code or reference")

    class Meta:
        ordering = ['-period_year', '-period_month']
        unique_together = [('organisation', 'period_year', 'period_month')]

    def __str__(self):
        return self.run_number

    def save(self, *args, **kwargs):
        if not self.run_number:
            self.run_number = f"PAY-{self.period_year}-{self.period_month:02d}"
        super().save(*args, **kwargs)


class PayslipLine(TenantAwareModel):
    CALCULATED = 'calculated'; PAID = 'paid'
    STATUS_CHOICES = [(s, s) for s in [CALCULATED, PAID]]

    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='payslips')
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name='payslips')
    # Earnings
    basic_salary = MoneyField(default=0)
    housing_allowance = MoneyField(default=0)
    transport_allowance = MoneyField(default=0)
    leave_allowance = MoneyField(default=0)
    other_allowances = MoneyField(default=0)
    gross_salary = MoneyField(default=0)
    # Nigerian statutory deductions (employee)
    employee_pension = MoneyField(default=0)   # 8% of (basic + housing + transport)
    nhf = MoneyField(default=0)                # 2.5% of basic (National Housing Fund)
    nsitf = MoneyField(default=0)              # 1% of gross (National Social Insurance Trust Fund)
    # Tax computation
    consolidated_relief_allowance = MoneyField(default=0)  # 20% of gross or 200k, whichever is higher + 200k
    taxable_income = MoneyField(default=0)
    paye_tax = MoneyField(default=0)
    # Employer contributions (not deducted from employee)
    employer_pension = MoneyField(default=0)  # 10% of (basic + housing + transport)
    # Net pay
    total_deductions = MoneyField(default=0)
    net_salary = MoneyField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=CALCULATED)

    class Meta:
        ordering = ['employee__last_name']
        unique_together = [('payroll_run', 'employee')]
