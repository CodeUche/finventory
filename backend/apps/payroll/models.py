from decimal import Decimal

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
    total_bonus = MoneyField(default=0)
    total_overtime = MoneyField(default=0)
    processed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='payroll_runs_processed')
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='payroll_runs_approved')
    # Multi-level approval: HR/Manager submits → Owner/Admin approves
    submitted_for_approval = models.BooleanField(default=False)
    submitted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='payroll_runs_submitted')
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

    # Per-employee Paystack transfer status
    TRANSFER_PENDING = 'pending'
    TRANSFER_INITIATED = 'initiated'
    TRANSFER_SUCCESS = 'success'
    TRANSFER_FAILED = 'failed'
    TRANSFER_SKIPPED = 'skipped'
    TRANSFER_STATUS_CHOICES = [
        (TRANSFER_PENDING, 'Pending'),
        (TRANSFER_INITIATED, 'Initiated'),
        (TRANSFER_SUCCESS, 'Success'),
        (TRANSFER_FAILED, 'Failed'),
        (TRANSFER_SKIPPED, 'Skipped'),
    ]

    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='payslips')
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name='payslips')
    # Earnings
    basic_salary = MoneyField(default=0)
    housing_allowance = MoneyField(default=0)
    transport_allowance = MoneyField(default=0)
    leave_allowance = MoneyField(default=0)
    other_allowances = MoneyField(default=0)
    gross_salary = MoneyField(default=0)
    # Extras
    bonus_amount = MoneyField(default=0)
    overtime_amount = MoneyField(default=0)
    attendance_deduction = MoneyField(default=0)
    # Nigerian statutory deductions (employee)
    employee_pension = MoneyField(default=0)   # 8% of (basic + housing + transport)
    nhf = MoneyField(default=0)                # 2.5% of basic (National Housing Fund)
    nsitf = MoneyField(default=0)              # 1% of gross (National Social Insurance Trust Fund)
    # Tax computation
    consolidated_relief_allowance = MoneyField(default=0)
    taxable_income = MoneyField(default=0)
    paye_tax = MoneyField(default=0)
    # Employer contributions (not deducted from employee)
    employer_pension = MoneyField(default=0)  # 10% of (basic + housing + transport)
    # Net pay
    total_deductions = MoneyField(default=0)
    net_salary = MoneyField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=CALCULATED)

    penalty_deductions = MoneyField(default=0)
    loan_deductions = MoneyField(default=0)

    # Paystack transfer tracking (persisted for reconciliation & retry)
    transfer_status = models.CharField(
        max_length=20, choices=TRANSFER_STATUS_CHOICES, default=TRANSFER_PENDING
    )
    transfer_reference = models.CharField(max_length=200, blank=True)
    transfer_error = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['employee__last_name']
        unique_together = [('payroll_run', 'employee')]


class EmployeePenalty(TenantAwareModel):
    """One-off or recurring salary deduction for disciplinary or operational reasons."""
    PENDING = 'pending'
    APPLIED = 'applied'
    WAIVED = 'waived'
    STATUS_CHOICES = [(s, s) for s in [PENDING, APPLIED, WAIVED]]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='penalties')
    reason = models.CharField(max_length=500)
    amount = MoneyField()
    penalty_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    applied_in_run = models.ForeignKey(
        'PayrollRun', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='applied_penalties'
    )

    class Meta:
        ordering = ['-penalty_date']

    def __str__(self):
        return f"{self.employee} — {self.reason} ({self.amount})"


class EmployeeLoan(TenantAwareModel):
    """Company loan issued to an employee, repaid via monthly payroll deductions."""
    ACTIVE = 'active'
    SETTLED = 'settled'
    CANCELLED = 'cancelled'
    STATUS_CHOICES = [(s, s) for s in [ACTIVE, SETTLED, CANCELLED]]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='loans')
    principal_amount = MoneyField()
    # Flat interest rate applied to the principal (e.g. 5 = 5%). Zero = interest-free.
    interest_rate = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    duration_months = models.PositiveIntegerField()
    start_date = models.DateField()
    # Auto-computed on save
    total_repayable = MoneyField(default=0)
    monthly_installment = MoneyField(default=0)
    # Tracks repayment progress
    amount_repaid = MoneyField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ACTIVE)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.employee} — loan {self.principal_amount}"

    @property
    def balance_remaining(self):
        return max(Decimal('0'), self.total_repayable - self.amount_repaid)

    def save(self, *args, **kwargs):
        principal = Decimal(str(self.principal_amount))
        rate = Decimal(str(self.interest_rate))
        if rate > 0:
            self.total_repayable = (principal * (1 + rate / 100)).quantize(Decimal('0.01'))
        else:
            self.total_repayable = principal
        months = max(1, self.duration_months)
        self.monthly_installment = (Decimal(str(self.total_repayable)) / months).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)


class Bonus(TenantAwareModel):
    """Ad-hoc or recurring bonus payment for an employee, applied during payroll."""
    PERFORMANCE = 'performance'
    SIGNING = 'signing'
    ANNUAL = 'annual'
    REFERRAL = 'referral'
    OTHER = 'other'
    TYPE_CHOICES = [
        (PERFORMANCE, 'Performance Bonus'),
        (SIGNING, 'Signing Bonus'),
        (ANNUAL, 'Annual Bonus'),
        (REFERRAL, 'Referral Bonus'),
        (OTHER, 'Other'),
    ]

    PENDING = 'pending'
    APPLIED = 'applied'
    STATUS_CHOICES = [(s, s) for s in [PENDING, APPLIED]]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='bonuses')
    amount = MoneyField()
    bonus_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=OTHER)
    reason = models.CharField(max_length=500)
    period_year = models.PositiveIntegerField()
    period_month = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    applied_in_run = models.ForeignKey(
        'PayrollRun', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='applied_bonuses'
    )

    class Meta:
        ordering = ['-period_year', '-period_month']

    def __str__(self):
        return f"{self.employee} — {self.bonus_type} ₦{self.amount}"


class Attendance(TenantAwareModel):
    """Daily attendance record for an employee."""
    PRESENT = 'present'
    ABSENT = 'absent'
    HALF_DAY = 'half_day'
    LEAVE = 'leave'
    HOLIDAY = 'holiday'
    STATUS_CHOICES = [
        (PRESENT, 'Present'),
        (ABSENT, 'Absent'),
        (HALF_DAY, 'Half Day'),
        (LEAVE, 'Leave / Holiday'),
        (HOLIDAY, 'Public Holiday'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendance')
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PRESENT)
    clock_in = models.TimeField(null=True, blank=True)
    clock_out = models.TimeField(null=True, blank=True)
    # Overtime hours logged for this day (e.g. 2.5 = 2h 30m)
    overtime_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['-date']
        unique_together = [('employee', 'date')]

    def __str__(self):
        return f"{self.employee} — {self.date} ({self.status})"


def _employee_doc_path(instance, filename):
    import os
    ext = os.path.splitext(filename)[1].lower()
    safe = filename.replace(' ', '_')
    return f"employee_documents/{instance.employee.organisation_id}/{instance.employee_id}/{safe}"


class EmployeeDocument(TenantAwareModel):
    """File attachment for an employee (CV, ID card, certificates, contracts, etc.)."""
    CV = 'cv'
    ID = 'id'
    CERTIFICATE = 'certificate'
    CONTRACT = 'contract'
    OTHER = 'other'
    TYPE_CHOICES = [
        (CV, 'CV / Resume'),
        (ID, 'ID Card / Passport'),
        (CERTIFICATE, 'Certificate / Qualification'),
        (CONTRACT, 'Employment Contract'),
        (OTHER, 'Other'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='documents')
    name = models.CharField(max_length=300)
    document_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=OTHER)
    file = models.FileField(upload_to=_employee_doc_path)
    file_size = models.PositiveIntegerField(default=0, help_text="File size in bytes")

    class Meta:
        ordering = ['document_type', 'name']

    def __str__(self):
        return f"{self.employee} — {self.name}"

    @property
    def file_url(self):
        if self.file:
            return self.file.url
        return None
