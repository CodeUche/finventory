from decimal import Decimal

from django.db import models
from apps.core.models import TenantAwareModel, MoneyField
from apps.authentication.models import User

from .constants import STATE_CHOICES


class TaxAuthority(TenantAwareModel):
    """
    A State Internal Revenue Service (or FCT-IRS) that PAYE is remitted to.

    PAYE follows the employee's state of *residence*, not the employer's
    registered address, so a single payroll run can owe several authorities.
    Seeded per organisation on first use from ``constants.NIGERIAN_STATES``.
    """

    state_code = models.CharField(max_length=2, choices=STATE_CHOICES)
    name = models.CharField(max_length=200)
    portal_url = models.URLField(blank=True)
    payer_id = models.CharField(
        max_length=100, blank=True,
        help_text="The employer's registration / payer ID with this authority",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        unique_together = [('organisation', 'state_code')]
        verbose_name_plural = 'Tax authorities'

    def __str__(self):
        return self.name


class PayrollSettings(TenantAwareModel):
    """Org-level payroll configuration. One row per organisation, auto-created."""

    # ITF Act s.6(1): employers with 5+ employees, or turnover of ₦50m+, pay a
    # 1% training levy on annual payroll. Auto-asserted from headcount on each
    # run; an admin can force it on for the turnover limb, which the ledger
    # knows about but which shouldn't silently switch a levy on.
    itf_applicable = models.BooleanField(default=False)
    itf_auto_assert = models.BooleanField(
        default=True, help_text="Turn ITF on automatically once headcount reaches 5",
    )
    nsitf_applicable = models.BooleanField(default=True)
    default_pay_frequency = models.CharField(
        max_length=10, default='monthly',
        choices=[('monthly', 'Monthly'), ('biweekly', 'Bi-weekly'), ('weekly', 'Weekly')],
    )
    leave_seeded = models.BooleanField(default=False)
    tax_authorities_seeded = models.BooleanField(default=False)
    public_holidays_seeded_years = models.JSONField(
        default=list, blank=True,
        help_text="Years for which fixed-date public holidays have been seeded",
    )
    # 13th-month pro-rata basis (A.4): months_served/12 × this figure.
    THIRTEENTH_BASIC = 'basic'; THIRTEENTH_GROSS = 'gross'
    THIRTEENTH_BASIS_CHOICES = [(THIRTEENTH_BASIC, 'Basic salary'), (THIRTEENTH_GROSS, 'Gross salary')]
    thirteenth_month_basis = models.CharField(
        max_length=10, choices=THIRTEENTH_BASIS_CHOICES, default=THIRTEENTH_BASIC,
    )
    # Gratuity (A.3 offboarding) — no universal Nigerian statutory formula, so
    # this is an explicit per-org policy. 0 = gratuity is off. Rate is applied
    # per completed year of service against final basic salary. Routed as
    # fully taxable ordinary income pending practitioner sign-off on any
    # tax-exemption treatment — do NOT add exemption logic without that
    # confirmation (see OffboardingService.compute_gratuity).
    gratuity_rate_per_year = MoneyField(default=0)
    # Leave-accrual GL true-up idempotency marker (A.6)
    leave_accrual_last_posted_amount = MoneyField(default=0)
    leave_accrual_last_posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = 'Payroll settings'

    def __str__(self):
        return f"Payroll settings — {self.organisation}"


class Employee(TenantAwareModel):
    FULL_TIME = 'full_time'; PART_TIME = 'part_time'; CONTRACT = 'contract'
    TYPE_CHOICES = [(t, t) for t in [FULL_TIME, PART_TIME, CONTRACT]]

    MALE = 'male'; FEMALE = 'female'; UNSPECIFIED = ''
    GENDER_CHOICES = [(MALE, 'Male'), (FEMALE, 'Female'), (UNSPECIFIED, 'Not specified')]

    MARITAL_CHOICES = [
        ('single', 'Single'), ('married', 'Married'),
        ('divorced', 'Divorced'), ('widowed', 'Widowed'), ('', 'Not specified'),
    ]

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
    # ── Personal / HR master data ────────────────────────────────────────────
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, default='')
    marital_status = models.CharField(max_length=10, choices=MARITAL_CHOICES, blank=True, default='')
    nin = models.CharField(max_length=20, blank=True, help_text="National Identification Number")
    address = models.TextField(blank=True)
    next_of_kin_name = models.CharField(max_length=200, blank=True)
    next_of_kin_phone = models.CharField(max_length=20, blank=True)
    next_of_kin_relationship = models.CharField(max_length=100, blank=True)
    emergency_contact_name = models.CharField(max_length=200, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    # Reporting line — drives the org chart and the leave approval route
    manager = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='direct_reports',
    )
    grade = models.CharField(max_length=50, blank=True, help_text="Job grade / level")
    confirmation_date = models.DateField(null=True, blank=True, help_text="End of probation")
    contract_end_date = models.DateField(null=True, blank=True)
    # Self-service portal account (a sub-account User); null until invited
    user = models.OneToOneField(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='employee_profile',
    )
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
    pension_pin = models.CharField(max_length=50, blank=True, help_text="RSA PIN issued by the PFA")
    tin = models.CharField(max_length=50, blank=True)  # Tax Identification Number
    # PAYE is remitted to the SIRS of the employee's state of residence
    state_of_residence = models.CharField(
        max_length=2, choices=STATE_CHOICES, blank=True, default='',
        help_text="Determines which State IRS this employee's PAYE is remitted to",
    )
    # Salary components
    basic_salary = MoneyField(default=0)
    housing_allowance = MoneyField(default=0)
    transport_allowance = MoneyField(default=0)
    leave_allowance = MoneyField(default=0)
    other_allowances = MoneyField(default=0)
    # NTA 2025: Rent Relief — employee's declared annual rent paid (used to compute pre-tax relief)
    annual_rent = MoneyField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['last_name', 'first_name']
        unique_together = [('organisation', 'employee_id')]

    def __str__(self):
        return f"{self.employee_id} - {self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def gross_salary(self):
        return (self.basic_salary + self.housing_allowance + self.transport_allowance +
                self.leave_allowance + self.other_allowances)

    def save(self, *args, **kwargs):
        if not self.employee_id:
            # all_objects: soft-deleted employees still hold their number, so
            # counting only live rows would re-issue an ID and trip the
            # (organisation, employee_id) unique constraint.
            count = Employee.all_objects.filter(organisation=self.organisation).count()
            candidate = f"EMP-{count + 1:03d}"
            while Employee.all_objects.filter(
                organisation=self.organisation, employee_id=candidate
            ).exists():
                count += 1
                candidate = f"EMP-{count + 1:03d}"
            self.employee_id = candidate
        super().save(*args, **kwargs)


class CompensationRecord(TenantAwareModel):
    """
    Effective-dated salary for an employee.

    Without this, ``Employee.basic_salary`` is a mutable field with no history:
    a backdated raise is unauditable and arrears cannot be computed. The payroll
    engine resolves the record in force on the run's period_end; the Employee
    columns are kept in sync with the latest record so existing reads still work.
    """

    HIRE = 'hire'; REVIEW = 'review'; PROMOTION = 'promotion'
    ADJUSTMENT = 'adjustment'; DEMOTION = 'demotion'
    REASON_CHOICES = [
        (HIRE, 'Hire'), (REVIEW, 'Annual review'), (PROMOTION, 'Promotion'),
        (ADJUSTMENT, 'Adjustment'), (DEMOTION, 'Demotion'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='compensation_history')
    effective_date = models.DateField()
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default=ADJUSTMENT)
    basic_salary = MoneyField(default=0)
    housing_allowance = MoneyField(default=0)
    transport_allowance = MoneyField(default=0)
    leave_allowance = MoneyField(default=0)
    other_allowances = MoneyField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-effective_date', '-created_at']
        unique_together = [('employee', 'effective_date')]

    def __str__(self):
        return f"{self.employee} — {self.effective_date} ({self.reason})"

    @property
    def gross_salary(self):
        return (self.basic_salary + self.housing_allowance + self.transport_allowance +
                self.leave_allowance + self.other_allowances)


class PayrollRun(TenantAwareModel):
    DRAFT = 'draft'; PROCESSING = 'processing'; APPROVED = 'approved'; PAID = 'paid'
    STATUS_CHOICES = [(s, s) for s in [DRAFT, PROCESSING, APPROVED, PAID]]

    # A month can hold more than one run: the regular payroll plus any
    # off-cycle, supplementary, 13th-month or final-settlement runs.
    REGULAR = 'regular'; OFF_CYCLE = 'off_cycle'; SUPPLEMENTARY = 'supplementary'
    THIRTEENTH = 'thirteenth_month'; FINAL_SETTLEMENT = 'final_settlement'
    RUN_TYPE_CHOICES = [
        (REGULAR, 'Regular'),
        (OFF_CYCLE, 'Off-cycle'),
        (SUPPLEMENTARY, 'Supplementary'),
        (THIRTEENTH, '13th Month'),
        (FINAL_SETTLEMENT, 'Final Settlement'),
    ]

    MONTHLY = 'monthly'; BIWEEKLY = 'biweekly'; WEEKLY = 'weekly'
    FREQUENCY_CHOICES = [(MONTHLY, 'Monthly'), (BIWEEKLY, 'Bi-weekly'), (WEEKLY, 'Weekly')]

    run_number = models.CharField(max_length=32, editable=False)
    period_year = models.PositiveIntegerField()
    period_month = models.PositiveIntegerField()
    # Explicit period boundaries drive proration. Defaulted to the calendar
    # month on save when not supplied, so existing callers keep working.
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    run_type = models.CharField(max_length=20, choices=RUN_TYPE_CHOICES, default=REGULAR)
    sequence = models.PositiveIntegerField(default=1)
    pay_frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, default=MONTHLY)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    total_gross = MoneyField(default=0)
    total_deductions = MoneyField(default=0)
    total_net = MoneyField(default=0)
    total_paye = MoneyField(default=0)
    total_pension_employee = MoneyField(default=0)
    total_pension_employer = MoneyField(default=0)
    total_nhf = MoneyField(default=0)
    total_nsitf = MoneyField(default=0)
    total_itf = MoneyField(default=0)
    total_benefits = MoneyField(default=0)
    total_benefits_employer = MoneyField(default=0)
    total_bonus = MoneyField(default=0)
    total_overtime = MoneyField(default=0)
    # Leave-encashment portion of PayrollAdjustment(ENCASHMENT) applied in this
    # run. Tracked separately from total_gross/total_bonus so post_payroll_journal
    # can carve it out of the Salaries & Wages Expense debit and route it
    # instead through AccountingService.post_leave_encashment_settlement as a
    # DR Accrued Leave / CR Bank liability settlement — encashing accrued leave
    # is paying out a liability already recognised by the accrual true-up, not
    # a fresh expense.
    total_encashment = MoneyField(default=0)
    processed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='payroll_runs_processed')
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='payroll_runs_approved')
    # Multi-level approval: HR/Manager submits → Owner/Admin approves
    submitted_for_approval = models.BooleanField(default=False)
    submitted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='payroll_runs_submitted')
    target_approver = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='payroll_runs_to_approve',
        help_text="The specific admin/owner the submitter directed this approval to")
    payment_date = models.DateField(null=True, blank=True)
    transfer_reference = models.CharField(max_length=200, blank=True,
        help_text="Paystack bulk transfer batch_transfer_code or reference")

    # GL auto-post tracking
    GL_STATUS = [
        ('pending', 'Pending'), ('posted', 'Posted'),
        ('failed', 'Failed'), ('not_configured', 'Not Configured'),
    ]
    gl_post_status = models.CharField(max_length=20, choices=GL_STATUS, default='pending')
    gl_post_error  = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-period_year', '-period_month', 'run_type', 'sequence']
        # Replaces the old (org, year, month) lock. A second *regular* run for
        # the same month still collides — which is the behaviour that lock was
        # actually protecting — while off-cycle and supplementary runs are free
        # to coexist, each with its own sequence number.
        unique_together = [
            ('organisation', 'period_year', 'period_month', 'run_type', 'sequence'),
        ]

    def __str__(self):
        return self.run_number

    @property
    def is_regular(self):
        return self.run_type == self.REGULAR

    def save(self, *args, **kwargs):
        import calendar as _cal
        from datetime import date as _date

        if not self.period_start or not self.period_end:
            _, last_day = _cal.monthrange(self.period_year, self.period_month)
            if not self.period_start:
                self.period_start = _date(self.period_year, self.period_month, 1)
            if not self.period_end:
                self.period_end = _date(self.period_year, self.period_month, last_day)

        if not self.run_number:
            base = f"PAY-{self.period_year}-{self.period_month:02d}"
            suffix_map = {
                self.REGULAR: 'R', self.OFF_CYCLE: 'OC', self.SUPPLEMENTARY: 'S',
                self.THIRTEENTH: 'M13', self.FINAL_SETTLEMENT: 'FS',
            }
            self.run_number = f"{base}-{suffix_map.get(self.run_type, 'R')}{self.sequence}"
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
    # ── Proration ────────────────────────────────────────────────────────────
    # Stored rather than recomputed so a historical payslip stays reproducible
    # even after the employee's hire/termination dates are corrected.
    proration_factor = models.DecimalField(max_digits=6, decimal_places=4, default=1)
    days_worked = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    days_in_period = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    # Which State IRS this line's PAYE is owed to (snapshot at run time)
    tax_authority = models.ForeignKey(
        TaxAuthority, null=True, blank=True, on_delete=models.SET_NULL, related_name='payslips',
    )
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
    adjustment_amount = MoneyField(default=0, help_text="Arrears / back-pay applied in this run")
    attendance_deduction = MoneyField(default=0)
    # Nigerian statutory deductions (employee)
    employee_pension = MoneyField(default=0)   # 8% of (basic + housing + transport)
    nhf = MoneyField(default=0)                # 2.5% of basic (National Housing Fund)
    nsitf = MoneyField(default=0)              # 1% of gross (National Social Insurance Trust Fund)
    # Tax computation
    consolidated_relief_allowance = MoneyField(default=0)  # pre-NTA-2025 CRA (kept for historical payslips)
    rent_relief = MoneyField(default=0)  # NTA 2025: monthly share of 20% annual rent, capped ₦500k/yr
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
    advance_deductions = MoneyField(default=0, help_text="Salary advance (EWA) recovered this period")
    benefit_deductions = MoneyField(default=0, help_text="Employee share of benefit premiums")
    benefit_employer_cost = MoneyField(default=0, help_text="Employer share (not deducted from net)")

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
    """
    Company loan issued to an employee, repaid via monthly payroll deductions.

    Loans start PENDING and only begin deducting once a manager approves them.
    Before this existed any staff-level user could create a loan for themselves
    that went straight to ACTIVE — self-issued credit with no second pair of
    eyes (NEW-10). PayrollService already filters on ACTIVE, so a pending loan
    is inert until approved.
    """
    PENDING = 'pending'
    ACTIVE = 'active'
    SETTLED = 'settled'
    CANCELLED = 'cancelled'
    REJECTED = 'rejected'
    STATUS_CHOICES = [(s, s) for s in [PENDING, ACTIVE, SETTLED, CANCELLED, REJECTED]]

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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    notes = models.TextField(blank=True)
    # Who released the money, and when. Nullable because every loan created
    # before this workflow existed was implicitly already active.
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='loans_approved',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=500, blank=True)

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


class EmployeeTaxProfile(TenantAwareModel):
    """
    Individual-level tax relief overrides for an employee (NTA 2025 rules).
    """
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name='tax_profile')
    # NHF is voluntary for private-sector employees — must explicitly opt in (NHF Act)
    nhf_enrolled = models.BooleanField(default=False, help_text="Employee has opted into NHF (2.5% of basic, voluntary)")
    voluntary_pension = MoneyField(default=0, help_text="Additional voluntary pension contributions per month")
    life_assurance_premium = MoneyField(default=0, help_text="Monthly life assurance premium (pre-tax deductible)")
    paye_exempt = models.BooleanField(default=False, help_text="If True, no PAYE is deducted (e.g., expatriate relief, diplomatic exemption)")
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Employee Tax Profile"

    def __str__(self):
        return f"Tax profile — {self.employee}"


class StatutoryRemittance(TenantAwareModel):
    """
    A single statutory or benefit obligation arising from a payroll run.

    Replaces the old PAYERemittance, which modelled one PAYE obligation per run
    and named FIRS as the recipient. Both were wrong: PAYE is owed to the State
    IRS of each employee's residence, so one run produces *several* PAYE rows,
    and the same shape covers pension (per PFA), NHF, NSITF, ITF and benefit
    premiums (per provider).
    """

    PAYE = 'paye'; PENSION = 'pension'; NHF = 'nhf'
    NSITF = 'nsitf'; ITF = 'itf'; BENEFIT = 'benefit'
    TYPE_CHOICES = [
        (PAYE, 'PAYE Tax'),
        (PENSION, 'Pension'),
        (NHF, 'National Housing Fund'),
        (NSITF, 'NSITF / Employee Compensation'),
        (ITF, 'Industrial Training Fund'),
        (BENEFIT, 'Benefit Premium'),
    ]

    PENDING = 'pending'; PARTIAL = 'partial'; REMITTED = 'remitted'
    STATUS_CHOICES = [(PENDING, 'Pending'), (PARTIAL, 'Partially remitted'), (REMITTED, 'Remitted')]

    payroll_run = models.ForeignKey(
        PayrollRun, null=True, blank=True, on_delete=models.CASCADE, related_name='remittances',
    )
    remittance_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    period_year = models.PositiveIntegerField()
    period_month = models.PositiveIntegerField()
    # Who it is owed to. tax_authority is set for PAYE; recipient_name carries
    # the PFA / FMBN / NSITF Board / HMO name for every other type.
    tax_authority = models.ForeignKey(
        TaxAuthority, null=True, blank=True, on_delete=models.SET_NULL, related_name='remittances',
    )
    recipient_name = models.CharField(max_length=200, blank=True)
    basis = models.CharField(max_length=200, blank=True, help_text="Rate / basis description")
    amount_due = MoneyField(default=0)
    amount_paid = MoneyField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    due_date = models.DateField()
    remittance_date = models.DateField(null=True, blank=True)
    reference = models.CharField(max_length=200, blank=True, help_text="Payment reference / schedule ref")
    notes = models.TextField(blank=True)
    # Set once the clearing journal has been posted to the GL
    gl_cleared = models.BooleanField(default=False)

    class Meta:
        ordering = ['-period_year', '-period_month', 'remittance_type', 'recipient_name']
        indexes = [
            models.Index(fields=['organisation', 'status']),
            models.Index(fields=['organisation', 'due_date']),
        ]

    def __str__(self):
        who = self.recipient_name or (self.tax_authority.name if self.tax_authority else '')
        return f"{self.get_remittance_type_display()} {self.period_year}-{self.period_month:02d} — {who}"

    @property
    def balance_due(self):
        return max(Decimal('0'), Decimal(str(self.amount_due)) - Decimal(str(self.amount_paid)))

    @property
    def is_overdue(self):
        from django.utils import timezone
        return self.status != self.REMITTED and self.due_date < timezone.localdate()

    @property
    def days_overdue(self):
        from django.utils import timezone
        if not self.is_overdue:
            return 0
        return (timezone.localdate() - self.due_date).days


class PayrollAdjustment(TenantAwareModel):
    """
    Arrears or back-pay owed to an employee, applied in a nominated run.

    Taxed in the period it is *paid*, which is how PAYE on arrears works in
    practice — the alternative (reopening closed periods) would invalidate
    already-filed returns.
    """

    ARREARS = 'arrears'; BACKPAY = 'backpay'; CORRECTION = 'correction'; ENCASHMENT = 'encashment'
    TYPE_CHOICES = [
        (ARREARS, 'Salary arrears'),
        (BACKPAY, 'Back pay'),
        (CORRECTION, 'Correction'),
        (ENCASHMENT, 'Leave encashment'),
    ]
    PENDING = 'pending'; APPLIED = 'applied'; CANCELLED = 'cancelled'
    STATUS_CHOICES = [(PENDING, 'Pending'), (APPLIED, 'Applied'), (CANCELLED, 'Cancelled')]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='adjustments')
    adjustment_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=ARREARS)
    amount = MoneyField(help_text="Positive to pay, negative to claw back")
    reason = models.CharField(max_length=500)
    # The period the money relates to (may be months before it is paid)
    effective_period_year = models.PositiveIntegerField(null=True, blank=True)
    effective_period_month = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    applied_in_run = models.ForeignKey(
        PayrollRun, null=True, blank=True, on_delete=models.SET_NULL, related_name='applied_adjustments',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee} — {self.get_adjustment_type_display()} {self.amount}"


class PayslipDelivery(TenantAwareModel):
    """Audit trail of payslip delivery. Issuing a payslip is a compliance act."""

    EMAIL = 'email'; PORTAL = 'portal'; DOWNLOAD = 'download'
    CHANNEL_CHOICES = [(EMAIL, 'Email'), (PORTAL, 'Portal'), (DOWNLOAD, 'Manual download')]

    SENT = 'sent'; FAILED = 'failed'; SKIPPED = 'skipped'
    STATUS_CHOICES = [(SENT, 'Sent'), (FAILED, 'Failed'), (SKIPPED, 'Skipped')]

    payslip = models.ForeignKey(PayslipLine, on_delete=models.CASCADE, related_name='deliveries')
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default=EMAIL)
    recipient = models.CharField(max_length=254, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=SENT)
    error = models.CharField(max_length=500, blank=True)
    sent_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='payslip_deliveries')

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Payslip deliveries'

    def __str__(self):
        return f"{self.payslip.employee} — {self.channel} ({self.status})"


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
    WORK_PERMIT = 'work_permit'
    PROFESSIONAL_LICENCE = 'professional_licence'
    OTHER = 'other'
    TYPE_CHOICES = [
        (CV, 'CV / Resume'),
        (ID, 'ID Card / Passport'),
        (CERTIFICATE, 'Certificate / Qualification'),
        (CONTRACT, 'Employment Contract'),
        (WORK_PERMIT, 'Work Permit / Visa'),
        (PROFESSIONAL_LICENCE, 'Professional Licence'),
        (OTHER, 'Other'),
    ]
    # Document types an employee may self-upload via the portal. Contracts and
    # other HR-authored records are deliberately excluded.
    EMPLOYEE_UPLOADABLE_TYPES = [CV, ID, CERTIFICATE, WORK_PERMIT, PROFESSIONAL_LICENCE, OTHER]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='documents')
    name = models.CharField(max_length=300)
    document_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=OTHER)
    file = models.FileField(upload_to=_employee_doc_path, max_length=255)
    file_size = models.PositiveIntegerField(default=0, help_text="File size in bytes")
    expiry_date = models.DateField(null=True, blank=True)
    # ESS self-upload tracking (A.5): distinguishes HR-authored records from
    # employee self-uploads pending review.
    uploaded_by_employee = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='employee_documents_reviewed',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    # Dedup for flag_expiring_documents (payroll.flag_expiring_documents): which
    # of the [60, 30, 7]-day thresholds have already triggered an alert email
    # for THIS document, so a range/catch-up query (needed to survive a missed
    # weekly run) never re-alerts the same threshold twice. Same lightweight
    # "list of already-done markers" pattern as
    # PayrollSettings.public_holidays_seeded_years.
    expiry_alert_thresholds_sent = models.JSONField(blank=True, default=list)

    class Meta:
        ordering = ['document_type', 'name']

    def __str__(self):
        return f"{self.employee} — {self.name}"

    @property
    def file_url(self):
        if self.file:
            return self.file.url
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Leave management
# ══════════════════════════════════════════════════════════════════════════════

class LeaveType(TenantAwareModel):
    """
    A category of leave with its own entitlement and accrual rule.

    Seeded with Nigerian defaults on first use (Labour Act s.18 sets the
    statutory floor at 6 working days of paid annual leave); every field is
    editable because most employers offer more than the floor.
    """

    ANNUAL_GRANT = 'annual_grant'; MONTHLY_ACCRUAL = 'monthly_accrual'
    ACCRUAL_CHOICES = [
        (ANNUAL_GRANT, 'Granted in full at the start of the year'),
        (MONTHLY_ACCRUAL, 'Accrues monthly'),
    ]

    name = models.CharField(max_length=100)
    days_per_year = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    accrual_method = models.CharField(max_length=20, choices=ACCRUAL_CHOICES, default=ANNUAL_GRANT)
    is_paid = models.BooleanField(
        default=True,
        help_text="Unpaid leave falls through to the attendance deduction in payroll",
    )
    carry_forward_max = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        help_text="Maximum unused days that roll into the next year",
    )
    gender_restriction = models.CharField(
        max_length=10, blank=True, default='',
        choices=[('', 'None'), ('male', 'Male only'), ('female', 'Female only')],
    )
    requires_approval = models.BooleanField(default=True)
    requires_document = models.BooleanField(
        default=False, help_text="e.g. a medical certificate for extended sick leave",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        unique_together = [('organisation', 'name')]

    def __str__(self):
        return self.name


class LeaveBalance(TenantAwareModel):
    """Per-employee, per-type, per-year leave ledger."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_balances')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, related_name='balances')
    year = models.PositiveIntegerField()
    entitled_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    accrued_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    carried_forward = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    taken_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    pending_days = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        help_text="Days in submitted-but-unapproved requests, held against the balance",
    )

    class Meta:
        ordering = ['-year', 'leave_type__name']
        unique_together = [('employee', 'leave_type', 'year')]

    def __str__(self):
        return f"{self.employee} — {self.leave_type} {self.year}"

    @property
    def available_days(self):
        """What the employee can actually book right now."""
        return (
            Decimal(str(self.accrued_days))
            + Decimal(str(self.carried_forward))
            - Decimal(str(self.taken_days))
            - Decimal(str(self.pending_days))
        )


class LeaveRequest(TenantAwareModel):
    DRAFT = 'draft'; PENDING = 'pending'; APPROVED = 'approved'
    REJECTED = 'rejected'; CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (DRAFT, 'Draft'), (PENDING, 'Pending approval'), (APPROVED, 'Approved'),
        (REJECTED, 'Rejected'), (CANCELLED, 'Cancelled'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name='requests')
    start_date = models.DateField()
    end_date = models.DateField()
    days = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        help_text="Working days (weekends excluded), computed on save",
    )
    reason = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    # Routed to the employee's manager where one is set, else to any approver
    approver = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='leave_requests_to_approve',
    )
    decided_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='leave_requests_decided',
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=500, blank=True)
    attachment = models.FileField(upload_to='leave_documents/', null=True, blank=True)
    # Warn-and-allow overbooking (A.1). The HR-facing endpoint never hard-blocks
    # a paid-leave request that exceeds the balance; it flags it instead. The
    # ESS-facing endpoint is unchanged and still hard-blocks.
    is_overbooked = models.BooleanField(default=False)
    overbooked_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='leave_requests_overbooked',
    )
    overbooked_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.employee} — {self.leave_type} {self.start_date}→{self.end_date}"

    @staticmethod
    def working_days_between(start, end, holiday_dates=frozenset()):
        """
        Count Mon–Fri days inclusive, excluding any date in ``holiday_dates``.

        ``holiday_dates`` should be preloaded once by the caller (a set of
        ``date`` objects) — never queried per-row here.
        """
        from datetime import timedelta
        if not start or not end or end < start:
            return Decimal('0')
        days = 0
        cur = start
        while cur <= end:
            if cur.weekday() < 5 and cur not in holiday_dates:
                days += 1
            cur += timedelta(days=1)
        return Decimal(str(days))

    def save(self, *args, **kwargs):
        if not self.days:
            self.days = self.working_days_between(self.start_date, self.end_date)
        super().save(*args, **kwargs)


class PublicHoliday(TenantAwareModel):
    """
    An org-recognised public holiday.

    Fixed-date Nigerian holidays (New Year, Workers' Day, Democracy Day,
    Independence Day, Christmas, Boxing Day) are seeded per year by
    ``PublicHolidayService.seed_fixed_dates``. Moveable Islamic/Christian dates
    (Eid, Good Friday, etc.) are NEVER auto-calculated — they are added here
    manually by an admin.
    """

    date = models.DateField()
    name = models.CharField(max_length=200)
    is_recurring_annually = models.BooleanField(
        default=True, help_text="Fixed-date holiday that recurs every year on this month/day",
    )
    # Blank/empty = applies to all states. Some states declare additional
    # local holidays (e.g. a state creation anniversary).
    applies_to_states = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['date']
        unique_together = [('organisation', 'date', 'name')]

    def __str__(self):
        return f"{self.name} ({self.date})"


# ══════════════════════════════════════════════════════════════════════════════
# Benefits administration
# ══════════════════════════════════════════════════════════════════════════════

class BenefitPlan(TenantAwareModel):
    """
    An employee benefit with a provider and a premium split.

    Structurally identical to pension: an employee deduction plus an employer
    cost, remitted to a provider on a schedule — so it reuses
    StatutoryRemittance rather than getting its own remittance pipeline.
    """

    HMO = 'hmo'; LIFE = 'life'; GYM = 'gym'; TRANSPORT = 'transport'; OTHER = 'other'
    TYPE_CHOICES = [
        (HMO, 'Health / HMO'), (LIFE, 'Group life assurance'),
        (GYM, 'Wellness / gym'), (TRANSPORT, 'Transport'), (OTHER, 'Other'),
    ]

    FIXED = 'fixed'; PERCENT_GROSS = 'percent_gross'
    BASIS_CHOICES = [
        (FIXED, 'Fixed amount per month'),
        (PERCENT_GROSS, 'Percentage of gross'),
    ]

    name = models.CharField(max_length=200)
    benefit_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=HMO)
    provider_name = models.CharField(max_length=200)
    basis = models.CharField(max_length=20, choices=BASIS_CHOICES, default=FIXED)
    # Under FIXED these are naira amounts; under PERCENT_GROSS they are percentages.
    employee_contribution = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    employer_contribution = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    remittance_day = models.PositiveSmallIntegerField(
        default=1, help_text="Day of the following month the premium is due",
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['name']
        unique_together = [('organisation', 'name')]

    def __str__(self):
        return f"{self.name} ({self.provider_name})"


class EmployeeBenefit(TenantAwareModel):
    """Enrolment of one employee in one benefit plan."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='benefits')
    plan = models.ForeignKey(BenefitPlan, on_delete=models.CASCADE, related_name='enrolments')
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    # Optional per-employee override (e.g. a family tier costing more)
    employee_contribution_override = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True,
    )
    employer_contribution_override = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True,
    )
    tier = models.CharField(max_length=100, blank=True, help_text="e.g. Individual, Family")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['plan__name']
        unique_together = [('employee', 'plan', 'start_date')]

    def __str__(self):
        return f"{self.employee} — {self.plan}"


# ══════════════════════════════════════════════════════════════════════════════
# Earned wage access (salary advances)
# ══════════════════════════════════════════════════════════════════════════════

class AdvancePolicy(TenantAwareModel):
    """Org-level rules governing salary advances. One row per organisation."""

    is_enabled = models.BooleanField(default=False)
    max_percent_of_accrued = models.DecimalField(
        max_digits=5, decimal_places=2, default=50,
        help_text="Cap as a percentage of net pay accrued so far this period",
    )
    fee_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Fee charged on the advanced amount",
    )
    min_amount = MoneyField(default=5000)
    max_requests_per_period = models.PositiveSmallIntegerField(default=1)
    min_months_employed = models.PositiveSmallIntegerField(default=3)
    require_approval = models.BooleanField(default=True)
    # Underwriting gate: advances are funded from the employer's own cash, so
    # the org must hold at least this much reconciled bank balance to approve.
    min_cash_buffer = MoneyField(
        default=0, help_text="Block approvals when bank balance would fall below this",
    )

    class Meta:
        verbose_name_plural = 'Advance policies'

    def __str__(self):
        return f"Advance policy — {self.organisation}"


class AdvanceRequest(TenantAwareModel):
    """
    An employee's request to draw wages already earned in the current period.

    Not a loan: the entitlement is bounded by what the employee has actually
    accrued (days worked × daily rate), it is employer-funded, and it is
    recovered in full from the same period's payroll.
    """

    PENDING = 'pending'; APPROVED = 'approved'; REJECTED = 'rejected'
    DISBURSED = 'disbursed'; RECOVERED = 'recovered'; CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (PENDING, 'Pending approval'), (APPROVED, 'Approved'), (REJECTED, 'Rejected'),
        (DISBURSED, 'Disbursed'), (RECOVERED, 'Recovered'), (CANCELLED, 'Cancelled'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='advance_requests')
    amount = MoneyField()
    fee = MoneyField(default=0)
    total_recoverable = MoneyField(default=0)
    period_year = models.PositiveIntegerField()
    period_month = models.PositiveIntegerField()
    reason = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    # Snapshot of the eligibility maths at request time, for audit
    accrued_at_request = MoneyField(default=0)
    days_worked_at_request = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    decided_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='advances_decided',
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=500, blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)
    amount_recovered = MoneyField(default=0)
    recovered_in_run = models.ForeignKey(
        PayrollRun, null=True, blank=True, on_delete=models.SET_NULL, related_name='recovered_advances',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee} — advance {self.amount} ({self.status})"

    @property
    def balance_outstanding(self):
        return max(Decimal('0'), Decimal(str(self.total_recoverable)) - Decimal(str(self.amount_recovered)))

    def save(self, *args, **kwargs):
        if not self.total_recoverable:
            self.total_recoverable = Decimal(str(self.amount)) + Decimal(str(self.fee or 0))
        super().save(*args, **kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# Offboarding
# ══════════════════════════════════════════════════════════════════════════════

class OffboardingCase(TenantAwareModel):
    """
    Tracks an employee's exit from initiation through to completion.

    Creating a case (even with a future ``last_working_day``) does NOT revoke
    anything — HR often back-plans an exit weeks ahead. Only an explicit
    ``OffboardingService.complete(case)`` call revokes portal access, because
    that is the point at which the exit is actually final.
    """

    RESIGNATION = 'resignation'
    DISMISSAL_MISCONDUCT = 'dismissal_misconduct'
    DISMISSAL_PERFORMANCE = 'dismissal_performance'
    REDUNDANCY = 'redundancy'
    CONTRACT_END = 'contract_end'
    RETIREMENT = 'retirement'
    DEATH_IN_SERVICE = 'death_in_service'
    REASON_CHOICES = [
        (RESIGNATION, 'Resignation'),
        (DISMISSAL_MISCONDUCT, 'Dismissal — misconduct'),
        (DISMISSAL_PERFORMANCE, 'Dismissal — performance'),
        (REDUNDANCY, 'Redundancy'),
        (CONTRACT_END, 'Contract end'),
        (RETIREMENT, 'Retirement'),
        (DEATH_IN_SERVICE, 'Death in service'),
    ]

    INITIATED = 'initiated'; IN_PROGRESS = 'in_progress'; COMPLETED = 'completed'; CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (INITIATED, 'Initiated'), (IN_PROGRESS, 'In progress'),
        (COMPLETED, 'Completed'), (CANCELLED, 'Cancelled'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='offboarding_cases')
    initiated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='offboarding_cases_initiated')
    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    last_working_day = models.DateField()
    notice_period_days = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=INITIATED)
    completed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='offboarding_cases_completed')
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    # Set once the final-settlement PayrollRun has been created for this case
    final_settlement_run = models.ForeignKey(
        PayrollRun, null=True, blank=True, on_delete=models.SET_NULL, related_name='offboarding_cases',
    )

    class Meta:
        ordering = ['-last_working_day']

    def __str__(self):
        return f"{self.employee} — {self.get_reason_display()} ({self.status})"


class OffboardingChecklistTemplate(TenantAwareModel):
    """Org-level ordered default checklist items applied to every new case."""

    item_name = models.CharField(max_length=300)
    department = models.CharField(max_length=200, blank=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'item_name']

    def __str__(self):
        return self.item_name


DEFAULT_OFFBOARDING_CHECKLIST_ITEMS = [
    ('Company property return', ''),
    ('System / access deprovisioning', 'IT'),
    ('Handover', ''),
    ('Outstanding loans / advances check', 'Finance'),
    ('Statutory sign-off', 'Finance'),
    ('Certificate of service', 'HR'),
    ('Final settlement', 'Finance'),
    ('Exit interview', 'HR'),
]


class ClearanceChecklistItem(TenantAwareModel):
    """One clearance line item for an offboarding case."""

    case = models.ForeignKey(OffboardingCase, on_delete=models.CASCADE, related_name='checklist_items')
    item_name = models.CharField(max_length=300)
    department = models.CharField(max_length=200, blank=True)
    is_cleared = models.BooleanField(default=False)
    cleared_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='clearance_items_cleared')
    cleared_at = models.DateTimeField(null=True, blank=True)
    order = models.PositiveIntegerField(default=0)
    notes = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['order', 'item_name']

    def __str__(self):
        return f"{self.case} — {self.item_name}"


class ExitInterview(TenantAwareModel):
    """Structured exit interview, one per offboarding case."""

    COMPENSATION = 'compensation'
    CAREER_GROWTH = 'career_growth'
    MANAGEMENT = 'management'
    WORK_LIFE_BALANCE = 'work_life_balance'
    RELOCATION = 'relocation'
    HEALTH = 'health'
    OTHER_OFFER = 'other_offer'
    BUSINESS_REASON = 'business_reason'
    OTHER = 'other'
    REASON_CHOICES = [
        (COMPENSATION, 'Compensation'),
        (CAREER_GROWTH, 'Career growth'),
        (MANAGEMENT, 'Management'),
        (WORK_LIFE_BALANCE, 'Work/life balance'),
        (RELOCATION, 'Relocation'),
        (HEALTH, 'Health'),
        (OTHER_OFFER, 'Another offer'),
        (BUSINESS_REASON, 'Business reason (redundancy etc.)'),
        (OTHER, 'Other'),
    ]

    case = models.OneToOneField(OffboardingCase, on_delete=models.CASCADE, related_name='exit_interview')
    conducted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='exit_interviews_conducted')
    reasons_for_leaving = models.JSONField(default=list, blank=True, help_text="List of REASON_CHOICES values")
    would_recommend = models.BooleanField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    is_confidential = models.BooleanField(
        default=True,
        help_text="If True, feedback is visible only to HR/owner/admin roles, never to the employee's manager",
    )

    class Meta:
        pass

    def __str__(self):
        return f"Exit interview — {self.case.employee}"
