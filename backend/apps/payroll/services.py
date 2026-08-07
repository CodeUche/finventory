import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from .constants import (
    DEFAULT_LEAVE_TYPES, FIXED_DATE_PUBLIC_HOLIDAYS, ITF_DUE_DAY, ITF_DUE_MONTH,
    NIGERIAN_STATES, REMITTANCE_DEADLINE_DAY, STATE_LOOKUP, WORKING_DAYS_PER_MONTH,
)
from .models import (
    AdvancePolicy, AdvanceRequest, Attendance, BenefitPlan, Bonus, ClearanceChecklistItem,
    CompensationRecord, DEFAULT_OFFBOARDING_CHECKLIST_ITEMS, Employee, EmployeeBenefit,
    EmployeeDocument, EmployeeLoan, EmployeePenalty, EmployeeTaxProfile, ExitInterview,
    LeaveBalance, LeaveRequest, LeaveType, OffboardingCase, OffboardingChecklistTemplate,
    PayrollAdjustment, PayrollRun, PayrollSettings, PayslipLine, PublicHoliday,
    StatutoryRemittance, TaxAuthority,
)

ZERO = Decimal('0')
CENTS = Decimal('0.01')


def _d(value):
    """Coerce anything money-shaped to Decimal without float contamination."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def get_settings(organisation):
    """Fetch (creating if absent) the org's payroll settings row."""
    obj, _ = PayrollSettings.objects.get_or_create(organisation=organisation)
    return obj


class TaxAuthorityService:
    """Seeds and resolves the State IRS an employee's PAYE is owed to."""

    @staticmethod
    def seed(organisation):
        """Idempotently create the 36 states + FCT for an organisation."""
        existing = set(
            TaxAuthority.objects.filter(organisation=organisation)
            .values_list('state_code', flat=True)
        )
        to_create = [
            TaxAuthority(
                organisation=organisation, state_code=code, name=name, portal_url=url,
            )
            for code, _label, name, url in NIGERIAN_STATES
            if code not in existing
        ]
        if to_create:
            TaxAuthority.objects.bulk_create(to_create)
        settings_row = get_settings(organisation)
        if not settings_row.tax_authorities_seeded:
            settings_row.tax_authorities_seeded = True
            settings_row.save(update_fields=['tax_authorities_seeded'])
        return TaxAuthority.objects.filter(organisation=organisation)

    @staticmethod
    def resolve(organisation, state_code):
        """Return the authority for a state code, seeding on first miss."""
        if not state_code:
            return None
        auth = TaxAuthority.objects.filter(
            organisation=organisation, state_code=state_code
        ).first()
        if auth is None and state_code in STATE_LOOKUP:
            TaxAuthorityService.seed(organisation)
            auth = TaxAuthority.objects.filter(
                organisation=organisation, state_code=state_code
            ).first()
        return auth


class CompensationService:
    """Effective-dated salary resolution."""

    COMPONENTS = (
        'basic_salary', 'housing_allowance', 'transport_allowance',
        'leave_allowance', 'other_allowances',
    )

    @classmethod
    def components_as_of(cls, employee, as_of, records_by_emp=None):
        """
        Salary components in force on ``as_of``.

        Falls back to the Employee columns when no record covers the date —
        which is the case for every employee until the backfill migration or
        their first raise, so existing orgs keep working unchanged.
        """
        if records_by_emp is not None:
            records = records_by_emp.get(employee.id, [])
        else:
            records = list(
                CompensationRecord.objects
                .filter(employee=employee, effective_date__lte=as_of)
                .order_by('-effective_date')[:1]
            )
        applicable = None
        for rec in records:
            if rec.effective_date <= as_of:
                applicable = rec
                break
        source = applicable or employee
        return {field: _d(getattr(source, field, 0)) for field in cls.COMPONENTS}

    @classmethod
    def record_change(cls, employee, effective_date, reason='adjustment', notes='', **components):
        """
        Write a compensation record and mirror it onto the Employee row.

        The mirror keeps ``Employee.basic_salary`` authoritative for every
        existing read path (exports, serializers, the advance calculator) while
        the history table carries the audit trail.
        """
        values = {
            field: _d(components.get(field, getattr(employee, field, 0)))
            for field in cls.COMPONENTS
        }
        record, _created = CompensationRecord.objects.update_or_create(
            organisation=employee.organisation,
            employee=employee,
            effective_date=effective_date,
            defaults={'reason': reason, 'notes': notes, **values},
        )
        latest = (
            CompensationRecord.objects
            .filter(employee=employee)
            .order_by('-effective_date')
            .first()
        )
        if latest and latest.effective_date == effective_date:
            for field, val in values.items():
                setattr(employee, field, val)
            employee.save(update_fields=list(values.keys()))
        return record


class ProrationService:
    """
    Working-day proration for joiners, leavers and mid-period contract ends.

    Uses working days (Mon–Fri) rather than calendar days so that someone who
    joins on the 28th of a month whose last three days are a weekend is not
    paid for days they were never going to work.
    """

    @staticmethod
    def working_days(start, end, holiday_dates: 'set' = frozenset()):
        """
        Count Mon–Fri days in [start, end], excluding any date present in
        ``holiday_dates``. Callers processing many employees in a loop MUST
        preload ``holiday_dates`` once (a set of ``date``) before the loop —
        never query per-employee here, following the same preload pattern
        already used for tax_profiles/comp_records in ``run_payroll``.
        """
        if not start or not end or end < start:
            return 0
        total = 0
        cur = start
        while cur <= end:
            if cur.weekday() < 5 and cur not in holiday_dates:
                total += 1
            cur += timedelta(days=1)
        return total

    @classmethod
    def factor_for(cls, employee, period_start, period_end, holiday_dates: 'set' = frozenset()):
        """
        Return (factor, days_worked, days_in_period).

        factor is 1 for anyone employed for the whole period; it never exceeds
        1 and never goes below 0.
        """
        days_in_period = cls.working_days(period_start, period_end, holiday_dates)
        if days_in_period == 0:
            return Decimal('1'), ZERO, ZERO

        effective_start = period_start
        if employee.hire_date and employee.hire_date > period_start:
            effective_start = employee.hire_date

        effective_end = period_end
        for candidate in (employee.termination_date, employee.contract_end_date):
            if candidate and candidate < effective_end:
                effective_end = candidate

        if effective_end < effective_start:
            return ZERO, ZERO, Decimal(str(days_in_period))

        days_worked = cls.working_days(effective_start, effective_end, holiday_dates)
        factor = (Decimal(str(days_worked)) / Decimal(str(days_in_period))).quantize(
            Decimal('0.0001')
        )
        factor = max(ZERO, min(Decimal('1'), factor))
        return factor, Decimal(str(days_worked)), Decimal(str(days_in_period))


class PublicHolidayService:
    """Seeds fixed-date Nigerian public holidays and loads them for proration."""

    @staticmethod
    def seed_fixed_dates(organisation, year):
        """
        Idempotently create the fixed-date holidays for one calendar year.

        Moveable Islamic/Christian dates are never computed — only the six
        fixed-date holidays in FIXED_DATE_PUBLIC_HOLIDAYS are seeded here.
        """
        settings_row = get_settings(organisation)
        seeded_years = list(settings_row.public_holidays_seeded_years or [])
        if year in seeded_years:
            return PublicHoliday.objects.filter(organisation=organisation, date__year=year)

        existing = set(
            PublicHoliday.objects.filter(organisation=organisation, date__year=year)
            .values_list('date', 'name')
        )
        to_create = []
        for month, day, name in FIXED_DATE_PUBLIC_HOLIDAYS:
            d = date(year, month, day)
            if (d, name) not in existing:
                to_create.append(PublicHoliday(
                    organisation=organisation, date=d, name=name,
                    is_recurring_annually=True, applies_to_states=[],
                ))
        if to_create:
            PublicHoliday.objects.bulk_create(to_create)

        seeded_years.append(year)
        settings_row.public_holidays_seeded_years = seeded_years
        settings_row.save(update_fields=['public_holidays_seeded_years'])
        return PublicHoliday.objects.filter(organisation=organisation, date__year=year)

    @staticmethod
    def holiday_dates_for(organisation, start, end):
        """Return a set of ``date`` for every holiday overlapping [start, end]. One query."""
        return set(
            PublicHoliday.objects.filter(
                organisation=organisation, date__gte=start, date__lte=end,
            ).values_list('date', flat=True)
        )


class PayrollService:
    PENSION_RATE_EMPLOYEE = Decimal('0.08')    # 8%
    PENSION_RATE_EMPLOYER = Decimal('0.10')    # 10%
    NHF_RATE = Decimal('0.025')               # 2.5% of basic salary (voluntary — NHF Act)
    NSITF_RATE = Decimal('0.01')              # 1% of gross (employer-borne)
    ITF_RATE = Decimal('0.01')                # 1% of annual payroll (employer-borne)
    ITF_MIN_HEADCOUNT = 5                     # ITF Act s.6(1)
    RENT_RELIEF_RATE = Decimal('0.20')        # NTA 2025: 20% of annual rent paid
    RENT_RELIEF_CAP = Decimal('500000')       # NTA 2025: capped at ₦500,000 per annum

    # Standard working hours per month (8 hrs × 26 days)
    MONTHLY_WORKING_HOURS = Decimal('208')
    OVERTIME_MULTIPLIER = Decimal('1.5')

    # NTA 2025 Fourth Schedule — PAYE bands (annual chargeable income), effective 1 Jan 2026.
    # Replaces repealed PITA schedule (7–24%).
    PAYE_BRACKETS = [
        (Decimal('0'),        Decimal('800000'),   Decimal('0.00')),   # 0%
        (Decimal('800000'),   Decimal('3000000'),  Decimal('0.15')),   # 15%
        (Decimal('3000000'),  Decimal('12000000'), Decimal('0.18')),   # 18%
        (Decimal('12000000'), Decimal('25000000'), Decimal('0.21')),   # 21%
        (Decimal('25000000'), Decimal('50000000'), Decimal('0.23')),   # 23%
        (Decimal('50000000'), None,                Decimal('0.25')),   # 25%
    ]

    @classmethod
    def calculate_annual_paye(cls, taxable_annual_income):
        tax = Decimal('0')
        for lower, upper, rate in cls.PAYE_BRACKETS:
            if taxable_annual_income <= lower:
                break
            bracket_upper = upper if upper is not None else taxable_annual_income
            taxable_in_bracket = min(taxable_annual_income, bracket_upper) - lower
            if taxable_in_bracket <= 0:
                continue
            tax += taxable_in_bracket * rate
        return tax

    # Run types whose extra_gross is a one-off payment rather than a recurring
    # monthly entitlement. These must NOT be taxed by independent-month
    # annualisation (× 12) — see calculate_employee_paye's ytd_* params.
    NON_RECURRING_RUN_TYPES = (
        PayrollRun.THIRTEENTH, PayrollRun.SUPPLEMENTARY,
        PayrollRun.OFF_CYCLE, PayrollRun.FINAL_SETTLEMENT,
    )

    @classmethod
    def calculate_employee_paye(
        cls, employee, extra_gross=Decimal('0'), tax_profile=None,
        components=None, proration_factor=None,
        ytd_taxable_prior=None, ytd_paye_withheld_prior=None,
    ):
        """
        Calculate full payroll figures for one employee (NTA 2025 rules).

        components:        salary components in force for the period (from
                           CompensationService); falls back to the Employee row.
        proration_factor:  applied to the salary components only. Bonuses,
                           overtime and arrears are paid in full because they
                           are earned events, not time-based entitlements.
        extra_gross:       bonus + overtime + adjustments added on top.

        Tax methodology — two modes:

        1. Regular monthly runs (ytd_taxable_prior is None): PAYE is computed
           by annualising the *actual* monthly taxable pay (× 12), consistent
           with how this engine has always worked. For a mid-month joiner this
           slightly under-deducts in month one and self-corrects across the
           year. This mode is UNCHANGED.

        2. Non-recurring payments — 13th month, bonus, arrears, encashment,
           off-cycle/supplementary runs (ytd_taxable_prior is not None):
           independent-month annualisation is WRONG here. Multiplying a
           one-off ₦500,000 December bonus by 12 taxes it as if the employee
           earns ₦6,000,000/year for the whole year, pushing it into a far
           higher bracket than it belongs in. Instead this uses cumulative
           top-slicing: tax is computed on the employee's actual cumulative
           taxable income for the tax year to date (``ytd_taxable_prior``)
           plus this payment, under the same PAYE bracket table; the tax
           already withheld year-to-date (``ytd_paye_withheld_prior``) is
           then subtracted, and only the difference is withheld now.
        """
        comp = components or {
            f: _d(getattr(employee, f, 0)) for f in CompensationService.COMPONENTS
        }
        factor = Decimal('1') if proration_factor is None else _d(proration_factor)

        prorated = {k: (v * factor).quantize(CENTS) for k, v in comp.items()}
        base_gross = sum(prorated.values(), ZERO)
        gross = base_gross + _d(extra_gross)

        pension_base = (
            prorated['basic_salary'] + prorated['housing_allowance']
            + prorated['transport_allowance']
        )
        employee_pension = pension_base * cls.PENSION_RATE_EMPLOYEE

        # Voluntary pension top-up from tax profile (additional pre-tax deductible)
        if tax_profile and tax_profile.voluntary_pension:
            employee_pension += _d(tax_profile.voluntary_pension)

        # NHF: voluntary for private-sector employees (NHF Act; default opt-in=False)
        nhf_enrolled = (tax_profile.nhf_enrolled if tax_profile else False)
        nhf = (prorated['basic_salary'] * cls.NHF_RATE) if nhf_enrolled else ZERO

        nsitf = gross * cls.NSITF_RATE

        # Life assurance premium deduction (still deductible under NTA 2025)
        life_assurance = _d(tax_profile.life_assurance_premium) if tax_profile else ZERO

        # NTA 2025: Rent Relief replaces CRA — 20% of annual rent paid, capped ₦500,000
        annual_rent = _d(getattr(employee, 'annual_rent', 0))
        annual_rent_relief = min(annual_rent * cls.RENT_RELIEF_RATE, cls.RENT_RELIEF_CAP)
        monthly_rent_relief = annual_rent_relief / 12

        taxable_income = max(
            ZERO,
            gross - employee_pension - nhf - monthly_rent_relief - life_assurance,
        )

        if ytd_taxable_prior is not None:
            # ── Cumulative top-slicing for non-recurring payments ────────────
            ytd_prior = _d(ytd_taxable_prior)
            withheld_prior = _d(ytd_paye_withheld_prior)
            cumulative_taxable = ytd_prior + taxable_income
            tax_on_cumulative = cls.calculate_annual_paye(cumulative_taxable).quantize(
                CENTS, rounding='ROUND_HALF_UP'
            )
            monthly_paye = max(ZERO, tax_on_cumulative - withheld_prior)
        else:
            annual_paye = cls.calculate_annual_paye(taxable_income * 12)
            # Quantize once at the annual total, then divide — no per-bracket rounding drift
            annual_paye = annual_paye.quantize(CENTS, rounding='ROUND_HALF_UP')
            monthly_paye = (annual_paye / 12).quantize(CENTS, rounding='ROUND_HALF_UP')

        # Exempt employees (diplomatic, approved expatriate relief)
        if tax_profile and tax_profile.paye_exempt:
            monthly_paye = ZERO
        # NTA 2025 abolished individual minimum tax — income ≤ ₦800k/yr is simply 0%

        employer_pension = pension_base * cls.PENSION_RATE_EMPLOYER
        total_deductions = employee_pension + nhf + monthly_paye
        net = gross - total_deductions

        return {
            **prorated,
            'gross_salary': gross,
            'employee_pension': employee_pension,
            'nhf': nhf,
            'nsitf': nsitf,
            'rent_relief': monthly_rent_relief,
            'taxable_income': taxable_income,
            'paye_tax': monthly_paye,
            'employer_pension': employer_pension,
            'total_deductions': total_deductions,
            'net_salary': net,
        }

    @staticmethod
    def _months_served_in_year(employee, year, as_of):
        """
        Whole calendar months served within ``year`` up to ``as_of``, capped
        at 12 and floored at 0. An employee hired mid-year accrues a
        proportionate 13th-month payout rather than a full month's worth
        regardless of tenure.
        """
        hire = employee.hire_date
        if not hire:
            return 0
        year_start = date(year, 1, 1)
        effective_start = max(hire, year_start)
        if effective_start > as_of:
            return 0
        months = (as_of.year - effective_start.year) * 12 + (as_of.month - effective_start.month)
        if as_of.day < effective_start.day:
            months -= 1
        months += 1  # inclusive of the start month once a full month has elapsed
        return max(0, min(12, months))

    @classmethod
    def _calc_overtime_pay(cls, basic_salary, overtime_hours):
        """Calculate overtime pay: hours × (basic / 208 working hours) × 1.5 multiplier."""
        if not overtime_hours or overtime_hours <= 0:
            return ZERO
        hourly = _d(basic_salary) / cls.MONTHLY_WORKING_HOURS
        return (hourly * _d(overtime_hours) * cls.OVERTIME_MULTIPLIER).quantize(CENTS)

    @classmethod
    def _calc_attendance_deduction(cls, gross, absent_days, working_days):
        """Deduct proportional salary for absent days."""
        if not absent_days or absent_days <= 0 or not working_days:
            return ZERO
        return (_d(gross) * _d(absent_days) / _d(working_days)).quantize(CENTS)

    @classmethod
    def _benefit_amounts(cls, enrolments, gross):
        """Return (employee_share, employer_share) across a set of enrolments."""
        emp_total = ZERO
        er_total = ZERO
        for enrolment in enrolments:
            plan = enrolment.plan
            emp_rate = enrolment.employee_contribution_override
            er_rate = enrolment.employer_contribution_override
            emp_rate = _d(plan.employee_contribution if emp_rate is None else emp_rate)
            er_rate = _d(plan.employer_contribution if er_rate is None else er_rate)
            if plan.basis == BenefitPlan.PERCENT_GROSS:
                emp_total += (_d(gross) * emp_rate / 100).quantize(CENTS)
                er_total += (_d(gross) * er_rate / 100).quantize(CENTS)
            else:
                emp_total += emp_rate
                er_total += er_rate
        return emp_total, er_total

    # ── the run ──────────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def run_payroll(cls, payroll_run):
        org = payroll_run.organisation
        year = payroll_run.period_year
        month = payroll_run.period_month
        period_start = payroll_run.period_start or date(year, month, 1)
        period_end = payroll_run.period_end or date(
            year, month, calendar.monthrange(year, month)[1]
        )

        # Everyone employed for any part of the period — including leavers, who
        # the old engine dropped entirely (so they were never paid a final
        # settlement) via a blanket termination_date__isnull=True filter.
        employees = list(
            Employee.objects
            .filter(organisation=org, is_active=True)
            .filter(hire_date__lte=period_end)
            .exclude(termination_date__lt=period_start)
        )
        PayslipLine.objects.filter(payroll_run=payroll_run).delete()

        emp_ids = [e.id for e in employees]

        # ── Pre-load everything the loop needs (no per-employee queries) ─────
        tax_profiles = {
            tp.employee_id: tp
            for tp in EmployeeTaxProfile.objects.filter(
                organisation=org, employee_id__in=emp_ids
            )
        }

        comp_records: dict = {}
        for rec in CompensationRecord.objects.filter(
            organisation=org, employee_id__in=emp_ids, effective_date__lte=period_end
        ).order_by('employee_id', '-effective_date'):
            comp_records.setdefault(rec.employee_id, []).append(rec)

        pending_penalties = list(
            EmployeePenalty.objects
            .filter(organisation=org, employee_id__in=emp_ids, status=EmployeePenalty.PENDING)
            .select_for_update()
        )
        penalties_by_emp: dict = {}
        for p in pending_penalties:
            penalties_by_emp.setdefault(p.employee_id, []).append(p)

        active_loans = list(
            EmployeeLoan.objects
            .filter(organisation=org, employee_id__in=emp_ids, status=EmployeeLoan.ACTIVE)
            .select_for_update()
        )
        loans_by_emp: dict = {}
        for loan in active_loans:
            loans_by_emp.setdefault(loan.employee_id, []).append(loan)

        pending_bonuses = list(
            Bonus.objects
            .filter(
                organisation=org, employee_id__in=emp_ids,
                status=Bonus.PENDING, period_year=year, period_month=month,
            )
            .select_for_update()
        )
        bonuses_by_emp: dict = {}
        for b in pending_bonuses:
            bonuses_by_emp.setdefault(b.employee_id, []).append(b)

        pending_adjustments = list(
            PayrollAdjustment.objects
            .filter(organisation=org, employee_id__in=emp_ids, status=PayrollAdjustment.PENDING)
            .select_for_update()
        )
        adjustments_by_emp: dict = {}
        for adj in pending_adjustments:
            adjustments_by_emp.setdefault(adj.employee_id, []).append(adj)

        outstanding_advances = list(
            AdvanceRequest.objects
            .filter(
                organisation=org, employee_id__in=emp_ids,
                status=AdvanceRequest.DISBURSED,
            )
            .select_for_update()
        )
        advances_by_emp: dict = {}
        for adv in outstanding_advances:
            advances_by_emp.setdefault(adv.employee_id, []).append(adv)

        benefit_enrolments = list(
            EmployeeBenefit.objects
            .filter(
                organisation=org, employee_id__in=emp_ids, is_active=True,
                start_date__lte=period_end,
            )
            .exclude(end_date__lt=period_start)
            .select_related('plan')
        )
        benefits_by_emp: dict = {}
        for enrolment in benefit_enrolments:
            if enrolment.plan.is_active:
                benefits_by_emp.setdefault(enrolment.employee_id, []).append(enrolment)

        attendance_qs = list(
            Attendance.objects.filter(
                organisation=org, employee_id__in=emp_ids,
                date__gte=period_start, date__lte=period_end,
            )
        )
        att_overtime_by_emp: dict = {}
        att_absent_by_emp: dict = {}
        for a in attendance_qs:
            eid = a.employee_id
            att_overtime_by_emp[eid] = att_overtime_by_emp.get(eid, ZERO) + _d(a.overtime_hours)
            # absent=1 day, half_day=0.5 day; present/leave/holiday = 0.
            # Approved *paid* leave writes status='leave' and so costs nothing;
            # unpaid leave writes status='absent' and falls through to here.
            if a.status == Attendance.ABSENT:
                att_absent_by_emp[eid] = att_absent_by_emp.get(eid, ZERO) + Decimal('1')
            elif a.status == Attendance.HALF_DAY:
                att_absent_by_emp[eid] = att_absent_by_emp.get(eid, ZERO) + Decimal('0.5')

        authorities = {
            a.state_code: a for a in TaxAuthority.objects.filter(organisation=org)
        }

        # Preloaded once, matching the tax_profiles/comp_records pattern above —
        # no per-employee holiday query inside the loop.
        holiday_dates = PublicHolidayService.holiday_dates_for(org, period_start, period_end)

        # ── YTD figures for non-recurring payment types (A.4) ────────────────
        # 13th month / bonus / arrears / off-cycle / supplementary / final-
        # settlement runs must NOT annualise the payment independently — see
        # calculate_employee_paye's cumulative top-slicing mode. One aggregate
        # query for every employee in this run, never per-employee.
        is_non_recurring = payroll_run.run_type in cls.NON_RECURRING_RUN_TYPES
        thirteenth_basis = get_settings(org).thirteenth_month_basis

        # A PENDING leave-encashment adjustment landing in an otherwise
        # REGULAR run is a one-off payment too — same over-annualisation risk
        # as a 13th-month/bonus run, just for a single employee instead of
        # the whole run. Determined per-employee (a REGULAR run stays
        # REGULAR for everyone else in it); pending_adjustments/
        # adjustments_by_emp are already preloaded above.
        encashment_emp_ids = {
            adj.employee_id for adj in pending_adjustments
            if adj.adjustment_type == PayrollAdjustment.ENCASHMENT
        }
        # Employees needing cumulative top-slicing this run: every employee
        # if the run itself is non-recurring, plus (for a REGULAR/other run)
        # anyone carrying a pending encashment this period.
        top_slicing_emp_ids = (
            set(emp_ids) if is_non_recurring else encashment_emp_ids
        )

        ytd_taxable_by_emp: dict = {}
        ytd_paye_by_emp: dict = {}
        if top_slicing_emp_ids:
            from django.db.models import Sum as _Sum
            ytd_rows = (
                PayslipLine.objects
                .filter(
                    organisation=org, employee_id__in=top_slicing_emp_ids,
                    payroll_run__period_year=year,
                    # Only count runs that actually reached a committed state.
                    # DRAFT/PROCESSING runs can be previewed and abandoned, but
                    # run_payroll() writes PayslipLine rows on every calculation
                    # (delete-and-recreate) well before approval — an abandoned
                    # preview run must not inflate YTD PAYE already withheld.
                    payroll_run__status__in=[PayrollRun.APPROVED, PayrollRun.PAID],
                )
                .exclude(payroll_run=payroll_run)
                .values('employee_id')
                .annotate(taxable=_Sum('taxable_income'), paye=_Sum('paye_tax'))
            )
            for row in ytd_rows:
                ytd_taxable_by_emp[row['employee_id']] = _d(row['taxable'])
                ytd_paye_by_emp[row['employee_id']] = _d(row['paye'])

        totals = {
            'gross': ZERO, 'deductions': ZERO, 'net': ZERO,
            'paye': ZERO, 'pension_emp': ZERO, 'pension_employer': ZERO,
            'nhf': ZERO, 'nsitf': ZERO, 'bonus': ZERO, 'overtime': ZERO,
            'benefits': ZERO, 'benefits_er': ZERO, 'encashment': ZERO,
        }

        payslips = []
        penalties_to_update = []
        loans_to_update = []
        bonuses_to_update = []
        adjustments_to_update = []
        advances_to_update = []

        for emp in employees:
            components = CompensationService.components_as_of(emp, period_end, comp_records)
            factor, days_worked, days_in_period = ProrationService.factor_for(
                emp, period_start, period_end, holiday_dates
            )

            # Bonuses — paid in full, not prorated
            emp_bonuses = bonuses_by_emp.get(emp.id, [])
            bonus_total = sum((_d(b.amount) for b in emp_bonuses), ZERO)
            for b in emp_bonuses:
                b.status = Bonus.APPLIED
                b.applied_in_run = payroll_run
                bonuses_to_update.append(b)

            # Arrears / back-pay / encashment — taxed in the period paid.
            # Encashment is tracked as its own sub-total (not just folded into
            # adjustment_total) because it is a settlement of the Accrued Leave
            # liability (GL account 2850), not fresh payroll expense — see
            # AccountingService.post_leave_encashment_settlement. It still adds
            # to extra_gross/PAYE like any other adjustment (the employee is
            # taxed on the cash they receive); only the GL routing differs.
            emp_adjustments = adjustments_by_emp.get(emp.id, [])
            adjustment_total = sum((_d(a.amount) for a in emp_adjustments), ZERO)
            encashment_total = sum(
                (_d(a.amount) for a in emp_adjustments
                 if a.adjustment_type == PayrollAdjustment.ENCASHMENT),
                ZERO,
            )
            for a in emp_adjustments:
                a.status = PayrollAdjustment.APPLIED
                a.applied_in_run = payroll_run
                adjustments_to_update.append(a)

            overtime_hrs = att_overtime_by_emp.get(emp.id, ZERO)
            overtime_pay = cls._calc_overtime_pay(components['basic_salary'], overtime_hrs)

            extra_gross = bonus_total + overtime_pay + adjustment_total

            # 13th-month pro-rata (A.4): months_served/12 × basic-or-gross,
            # instead of paying a full month regardless of tenure. Salary
            # components are zeroed for this run type (the payout itself
            # becomes the sole earnings line via extra_gross) so the payslip
            # cannot double-count a regular month's basic pay.
            if payroll_run.run_type == PayrollRun.THIRTEENTH:
                # basis_value must be computed from the UNPRORATED, full
                # monthly components — this run type pays a fraction of a
                # full month's basic/gross, not a fraction of an
                # already-prorated figure.
                months_served = cls._months_served_in_year(emp, year, period_end)
                basis_value = (
                    components['basic_salary'] if thirteenth_basis == PayrollSettings.THIRTEENTH_BASIC
                    else sum(components.values(), ZERO)
                )
                thirteenth_month_amount = (
                    basis_value * Decimal(months_served) / Decimal('12')
                ).quantize(CENTS)
                # Stored as bonus_amount so it is visible on the payslip as its
                # own line, not buried inside gross_salary.
                bonus_total += thirteenth_month_amount
                extra_gross += thirteenth_month_amount
                # Salary components themselves are not re-paid in a 13th-month run.
                factor = ZERO
                components = {k: ZERO for k in components}

            # Per-employee determination: this employee's PAYE routes through
            # cumulative top-slicing if either the whole run is non-recurring,
            # or — for an otherwise-REGULAR run — THIS employee specifically
            # carries a pending leave-encashment adjustment this period. Other
            # employees in the same REGULAR run are unaffected.
            paye_kwargs = {}
            if emp.id in top_slicing_emp_ids:
                paye_kwargs['ytd_taxable_prior'] = ytd_taxable_by_emp.get(emp.id, ZERO)
                paye_kwargs['ytd_paye_withheld_prior'] = ytd_paye_by_emp.get(emp.id, ZERO)

            calc = cls.calculate_employee_paye(
                emp,
                extra_gross=extra_gross,
                tax_profile=tax_profiles.get(emp.id),
                components=components,
                proration_factor=factor,
                **paye_kwargs,
            )

            absent_days = att_absent_by_emp.get(emp.id, ZERO)
            attendance_ded = cls._calc_attendance_deduction(
                calc['gross_salary'], absent_days, days_in_period
            )

            emp_penalties = penalties_by_emp.get(emp.id, [])
            penalty_total = sum((_d(p.amount) for p in emp_penalties), ZERO)
            for p in emp_penalties:
                p.status = EmployeePenalty.APPLIED
                p.applied_in_run = payroll_run
                penalties_to_update.append(p)

            loan_total = ZERO
            for loan in loans_by_emp.get(emp.id, []):
                installment = _d(loan.monthly_installment)
                balance = loan.balance_remaining
                deduct = min(installment, balance)
                if deduct <= ZERO:
                    continue
                loan_total += deduct
                loan.amount_repaid = _d(loan.amount_repaid) + deduct
                if loan.balance_remaining <= CENTS:
                    loan.status = EmployeeLoan.SETTLED
                loans_to_update.append(loan)

            # Salary advances recover in full from the period they were drawn
            # against, using the same mechanism as a loan installment.
            advance_total = ZERO
            for adv in advances_by_emp.get(emp.id, []):
                outstanding = adv.balance_outstanding
                if outstanding <= ZERO:
                    continue
                advance_total += outstanding
                adv.amount_recovered = _d(adv.amount_recovered) + outstanding
                adv.status = AdvanceRequest.RECOVERED
                adv.recovered_in_run = payroll_run
                advances_to_update.append(adv)

            benefit_emp, benefit_er = cls._benefit_amounts(
                benefits_by_emp.get(emp.id, []), calc['gross_salary']
            )

            extra_deductions = (
                penalty_total + loan_total + attendance_ded + advance_total + benefit_emp
            )
            adjusted_deductions = calc['total_deductions'] + extra_deductions
            adjusted_net = max(ZERO, calc['net_salary'] - extra_deductions)

            authority = authorities.get(emp.state_of_residence) if emp.state_of_residence else None

            payslips.append(PayslipLine(
                organisation=org,
                payroll_run=payroll_run,
                employee=emp,
                **{k: v for k, v in calc.items() if k not in ('total_deductions', 'net_salary')},
                proration_factor=factor,
                days_worked=days_worked,
                days_in_period=days_in_period,
                tax_authority=authority,
                bonus_amount=bonus_total,
                overtime_amount=overtime_pay,
                adjustment_amount=adjustment_total,
                attendance_deduction=attendance_ded,
                penalty_deductions=penalty_total,
                loan_deductions=loan_total,
                advance_deductions=advance_total,
                benefit_deductions=benefit_emp,
                benefit_employer_cost=benefit_er,
                total_deductions=adjusted_deductions,
                net_salary=adjusted_net,
                transfer_status=PayslipLine.TRANSFER_PENDING,
            ))

            totals['gross'] += calc['gross_salary']
            totals['deductions'] += adjusted_deductions
            totals['net'] += adjusted_net
            totals['paye'] += calc['paye_tax']
            totals['pension_emp'] += calc['employee_pension']
            totals['pension_employer'] += calc['employer_pension']
            totals['nhf'] += calc['nhf']
            totals['nsitf'] += calc['nsitf']
            totals['bonus'] += bonus_total
            totals['overtime'] += overtime_pay
            totals['benefits'] += benefit_emp
            totals['benefits_er'] += benefit_er
            totals['encashment'] += encashment_total

        PayslipLine.objects.bulk_create(payslips)

        if penalties_to_update:
            EmployeePenalty.objects.bulk_update(penalties_to_update, ['status', 'applied_in_run'])
        if loans_to_update:
            EmployeeLoan.objects.bulk_update(loans_to_update, ['amount_repaid', 'status'])
        if bonuses_to_update:
            Bonus.objects.bulk_update(bonuses_to_update, ['status', 'applied_in_run'])
        if adjustments_to_update:
            PayrollAdjustment.objects.bulk_update(
                adjustments_to_update, ['status', 'applied_in_run']
            )
        if advances_to_update:
            AdvanceRequest.objects.bulk_update(
                advances_to_update, ['amount_recovered', 'status', 'recovered_in_run']
            )

        # ── ITF: 1% of payroll, employer-borne, accrued monthly ──────────────
        settings_row = get_settings(org)
        if settings_row.itf_auto_assert and not settings_row.itf_applicable:
            headcount = Employee.objects.filter(organisation=org, is_active=True).count()
            if headcount >= cls.ITF_MIN_HEADCOUNT:
                settings_row.itf_applicable = True
                settings_row.save(update_fields=['itf_applicable'])
        itf = (totals['gross'] * cls.ITF_RATE).quantize(CENTS) if settings_row.itf_applicable else ZERO

        payroll_run.total_gross = totals['gross']
        payroll_run.total_deductions = totals['deductions']
        payroll_run.total_net = totals['net']
        payroll_run.total_paye = totals['paye']
        payroll_run.total_pension_employee = totals['pension_emp']
        payroll_run.total_pension_employer = totals['pension_employer']
        payroll_run.total_nhf = totals['nhf']
        payroll_run.total_nsitf = totals['nsitf']
        payroll_run.total_itf = itf
        payroll_run.total_benefits = totals['benefits']
        payroll_run.total_benefits_employer = totals['benefits_er']
        payroll_run.total_bonus = totals['bonus']
        payroll_run.total_overtime = totals['overtime']
        payroll_run.total_encashment = totals['encashment']
        payroll_run.status = PayrollRun.PROCESSING
        payroll_run.save()

        RemittanceService.generate_for_run(payroll_run)
        return payroll_run


class RemittanceService:
    """
    Turns a completed payroll run into the statutory obligations it creates.

    PAYE is split per State IRS and pension per PFA because neither authority
    accepts a blended schedule — a single lump figure cannot actually be filed.
    """

    @staticmethod
    def _due_date(year, month, day):
        """Day-of-month in the month following the payroll period."""
        if month == 12:
            due_year, due_month = year + 1, 1
        else:
            due_year, due_month = year, month + 1
        last_day = calendar.monthrange(due_year, due_month)[1]
        return date(due_year, due_month, min(day, last_day))

    @classmethod
    @transaction.atomic
    def generate_for_run(cls, payroll_run):
        org = payroll_run.organisation
        year, month = payroll_run.period_year, payroll_run.period_month

        # Rebuild this run's obligations from scratch, but never touch one that
        # has already been remitted — that reference has been filed.
        StatutoryRemittance.objects.filter(
            organisation=org, payroll_run=payroll_run,
        ).exclude(status=StatutoryRemittance.REMITTED).delete()

        payslips = list(
            payroll_run.payslips.select_related('employee', 'tax_authority').all()
        )
        rows = []

        # ── PAYE, split by the employee's state of residence ────────────────
        paye_by_authority: dict = {}
        unassigned_paye = ZERO
        for slip in payslips:
            amount = _d(slip.paye_tax)
            if amount <= ZERO:
                continue
            if slip.tax_authority_id:
                key = slip.tax_authority_id
                paye_by_authority[key] = paye_by_authority.get(key, ZERO) + amount
            else:
                unassigned_paye += amount

        authority_map = {
            a.id: a for a in TaxAuthority.objects.filter(
                organisation=org, id__in=list(paye_by_authority.keys())
            )
        }
        paye_due = cls._due_date(year, month, REMITTANCE_DEADLINE_DAY['paye'])
        for auth_id, amount in paye_by_authority.items():
            auth = authority_map.get(auth_id)
            rows.append(StatutoryRemittance(
                organisation=org, payroll_run=payroll_run,
                remittance_type=StatutoryRemittance.PAYE,
                period_year=year, period_month=month,
                tax_authority=auth,
                recipient_name=auth.name if auth else '',
                basis='NTA 2025 progressive bands',
                amount_due=amount, due_date=paye_due,
            ))
        if unassigned_paye > ZERO:
            # Employees with no state of residence recorded. Surfaced as its own
            # row rather than silently folded into another state's schedule.
            rows.append(StatutoryRemittance(
                organisation=org, payroll_run=payroll_run,
                remittance_type=StatutoryRemittance.PAYE,
                period_year=year, period_month=month,
                recipient_name='Unassigned — set state of residence',
                basis='NTA 2025 progressive bands',
                amount_due=unassigned_paye, due_date=paye_due,
            ))

        # ── Pension, split by PFA ───────────────────────────────────────────
        pension_by_pfa: dict = {}
        for slip in payslips:
            total = _d(slip.employee_pension) + _d(slip.employer_pension)
            if total <= ZERO:
                continue
            pfa = (slip.employee.pfa_name or '').strip() or 'Unassigned PFA'
            pension_by_pfa[pfa] = pension_by_pfa.get(pfa, ZERO) + total

        pension_due = cls._due_date(year, month, REMITTANCE_DEADLINE_DAY['pension'])
        for pfa, amount in pension_by_pfa.items():
            rows.append(StatutoryRemittance(
                organisation=org, payroll_run=payroll_run,
                remittance_type=StatutoryRemittance.PENSION,
                period_year=year, period_month=month,
                recipient_name=pfa,
                basis='18% of emoluments (8% employee + 10% employer)',
                amount_due=amount, due_date=pension_due,
            ))

        # ── NHF and NSITF ───────────────────────────────────────────────────
        if _d(payroll_run.total_nhf) > ZERO:
            rows.append(StatutoryRemittance(
                organisation=org, payroll_run=payroll_run,
                remittance_type=StatutoryRemittance.NHF,
                period_year=year, period_month=month,
                recipient_name='Federal Mortgage Bank of Nigeria (FMBN)',
                basis='2.5% of basic salary',
                amount_due=_d(payroll_run.total_nhf),
                due_date=cls._due_date(year, month, REMITTANCE_DEADLINE_DAY['nhf']),
            ))
        if _d(payroll_run.total_nsitf) > ZERO:
            rows.append(StatutoryRemittance(
                organisation=org, payroll_run=payroll_run,
                remittance_type=StatutoryRemittance.NSITF,
                period_year=year, period_month=month,
                recipient_name='NSITF Board',
                basis='1% of gross — employer-borne',
                amount_due=_d(payroll_run.total_nsitf),
                due_date=cls._due_date(year, month, REMITTANCE_DEADLINE_DAY['nsitf']),
            ))

        # ── Benefit premiums, split by provider ─────────────────────────────
        benefit_by_provider: dict = {}
        if _d(payroll_run.total_benefits) + _d(payroll_run.total_benefits_employer) > ZERO:
            enrolments = EmployeeBenefit.objects.filter(
                organisation=org, is_active=True,
                employee__in=[s.employee_id for s in payslips],
            ).select_related('plan')
            gross_by_emp = {s.employee_id: _d(s.gross_salary) for s in payslips}
            by_emp: dict = {}
            for enrolment in enrolments:
                by_emp.setdefault(enrolment.employee_id, []).append(enrolment)
            for emp_id, emp_enrolments in by_emp.items():
                for enrolment in emp_enrolments:
                    emp_share, er_share = PayrollService._benefit_amounts(
                        [enrolment], gross_by_emp.get(emp_id, ZERO)
                    )
                    provider = enrolment.plan.provider_name or enrolment.plan.name
                    benefit_by_provider[provider] = (
                        benefit_by_provider.get(provider, ZERO) + emp_share + er_share
                    )
        for provider, amount in benefit_by_provider.items():
            if amount <= ZERO:
                continue
            rows.append(StatutoryRemittance(
                organisation=org, payroll_run=payroll_run,
                remittance_type=StatutoryRemittance.BENEFIT,
                period_year=year, period_month=month,
                recipient_name=provider,
                basis='Benefit premium (employee + employer share)',
                amount_due=amount,
                due_date=cls._due_date(year, month, 1),
            ))

        if rows:
            StatutoryRemittance.objects.bulk_create(rows)

        cls._accrue_itf(payroll_run)
        return rows

    @classmethod
    def _accrue_itf(cls, payroll_run):
        """
        ITF is an annual levy due 1 April of the following year, so it is
        accumulated into a single row per year rather than one per run.
        """
        org = payroll_run.organisation
        year = payroll_run.period_year
        itf_amount = _d(payroll_run.total_itf)
        if itf_amount <= ZERO:
            return None

        row = StatutoryRemittance.objects.filter(
            organisation=org, remittance_type=StatutoryRemittance.ITF,
            period_year=year, period_month=0,
        ).first()

        # Recompute from all runs in the year so re-running a month cannot
        # double-count the levy.
        year_total = sum(
            (_d(r.total_itf) for r in PayrollRun.objects.filter(
                organisation=org, period_year=year,
            )),
            ZERO,
        )
        due = date(year + 1, ITF_DUE_MONTH, ITF_DUE_DAY)
        if row is None:
            row = StatutoryRemittance.objects.create(
                organisation=org, payroll_run=None,
                remittance_type=StatutoryRemittance.ITF,
                period_year=year, period_month=0,
                recipient_name='Industrial Training Fund (ITF)',
                basis='1% of annual payroll — employer-borne',
                amount_due=year_total, due_date=due,
            )
        elif row.status != StatutoryRemittance.REMITTED:
            row.amount_due = year_total
            row.due_date = due
            row.save(update_fields=['amount_due', 'due_date'])
        return row

    @staticmethod
    def mark_remitted(remittance, amount=None, reference='', remittance_date=None, user=None):
        """Record a payment against an obligation and clear the GL liability."""
        from django.utils import timezone

        paid = _d(amount) if amount is not None else _d(remittance.amount_due)
        remittance.amount_paid = _d(remittance.amount_paid) + paid
        remittance.reference = reference or remittance.reference
        remittance.remittance_date = remittance_date or timezone.localdate()
        if remittance.amount_paid >= _d(remittance.amount_due):
            remittance.status = StatutoryRemittance.REMITTED
        else:
            remittance.status = StatutoryRemittance.PARTIAL
        remittance.save(update_fields=[
            'amount_paid', 'reference', 'remittance_date', 'status',
        ])

        if remittance.status == StatutoryRemittance.REMITTED and not remittance.gl_cleared:
            try:
                from apps.accounting.services import AccountingService
                posted = AccountingService.post_remittance_clearing(remittance, user=user)
                if posted:
                    remittance.gl_cleared = True
                    remittance.save(update_fields=['gl_cleared'])
            except Exception:
                # A GL posting failure must not lose the record that the money
                # was actually remitted; gl_cleared stays False for retry.
                pass
        return remittance


class LeaveService:
    """Leave entitlement, accrual and the bridge into attendance."""

    @staticmethod
    def seed_defaults(organisation):
        """Create the Nigerian default leave types once per organisation."""
        settings_row = get_settings(organisation)
        existing = set(
            LeaveType.objects.filter(organisation=organisation).values_list('name', flat=True)
        )
        to_create = [
            LeaveType(
                organisation=organisation, name=name, days_per_year=Decimal(str(days)),
                accrual_method=accrual, is_paid=is_paid,
                carry_forward_max=Decimal(str(carry)), gender_restriction=gender,
            )
            for name, days, accrual, is_paid, carry, gender in DEFAULT_LEAVE_TYPES
            if name not in existing
        ]
        if to_create:
            LeaveType.objects.bulk_create(to_create)
        if not settings_row.leave_seeded:
            settings_row.leave_seeded = True
            settings_row.save(update_fields=['leave_seeded'])
        return LeaveType.objects.filter(organisation=organisation)

    @staticmethod
    def get_or_create_balance(employee, leave_type, year):
        balance, created = LeaveBalance.objects.get_or_create(
            organisation=employee.organisation,
            employee=employee, leave_type=leave_type, year=year,
            defaults={'entitled_days': leave_type.days_per_year},
        )
        if created and leave_type.accrual_method == LeaveType.ANNUAL_GRANT:
            balance.accrued_days = leave_type.days_per_year
            balance.save(update_fields=['accrued_days'])
        return balance

    @classmethod
    def accrue_month(cls, organisation, year, month):
        """
        Add one month's share of entitlement to every monthly-accrual balance.

        Pro-rated for anyone hired mid-year: an employee hired in September
        accrues four months, not twelve.
        """
        monthly_types = list(LeaveType.objects.filter(
            organisation=organisation, is_active=True,
            accrual_method=LeaveType.MONTHLY_ACCRUAL,
        ))
        if not monthly_types:
            return 0

        employees = list(Employee.objects.filter(
            organisation=organisation, is_active=True, termination_date__isnull=True,
        ))
        period_end = date(year, month, calendar.monthrange(year, month)[1])
        updated = 0
        for emp in employees:
            if emp.hire_date and emp.hire_date > period_end:
                continue
            for leave_type in monthly_types:
                if leave_type.gender_restriction and emp.gender != leave_type.gender_restriction:
                    continue
                balance = cls.get_or_create_balance(emp, leave_type, year)
                monthly_share = (_d(leave_type.days_per_year) / 12).quantize(Decimal('0.01'))
                ceiling = _d(leave_type.days_per_year)
                if _d(balance.accrued_days) + monthly_share > ceiling:
                    monthly_share = max(ZERO, ceiling - _d(balance.accrued_days))
                if monthly_share <= ZERO:
                    continue
                balance.accrued_days = _d(balance.accrued_days) + monthly_share
                balance.save(update_fields=['accrued_days'])
                updated += 1
        return updated

    @classmethod
    @transaction.atomic
    def approve(cls, leave_request, user=None, note=''):
        """
        Approve a request and write the attendance rows that carry it into payroll.

        This is the whole reason leave lives inside the ERP: paid leave writes
        status='leave' (which the payroll engine already ignores), unpaid leave
        writes status='absent' (which falls through to the existing attendance
        deduction). No new deduction path is introduced.
        """
        from django.utils import timezone

        if leave_request.status == LeaveRequest.APPROVED:
            return leave_request

        leave_request.status = LeaveRequest.APPROVED
        leave_request.decided_by = user
        leave_request.decided_at = timezone.now()
        leave_request.decision_note = note
        leave_request.save(update_fields=[
            'status', 'decided_by', 'decided_at', 'decision_note',
        ])

        cls._write_attendance(leave_request)

        balance = cls.get_or_create_balance(
            leave_request.employee, leave_request.leave_type, leave_request.start_date.year
        )
        days = _d(leave_request.days)
        balance.pending_days = max(ZERO, _d(balance.pending_days) - days)
        balance.taken_days = _d(balance.taken_days) + days
        balance.save(update_fields=['pending_days', 'taken_days'])
        return leave_request

    @staticmethod
    def _write_attendance(leave_request):
        status = (
            Attendance.LEAVE if leave_request.leave_type.is_paid else Attendance.ABSENT
        )
        emp = leave_request.employee
        cur = leave_request.start_date
        rows = []
        while cur <= leave_request.end_date:
            if cur.weekday() < 5:
                rows.append(Attendance(
                    organisation=emp.organisation, employee=emp, date=cur,
                    status=status,
                    notes=f"{leave_request.leave_type.name} (auto)",
                ))
            cur += timedelta(days=1)
        for row in rows:
            Attendance.objects.update_or_create(
                employee=row.employee, date=row.date,
                defaults={
                    'organisation': row.organisation,
                    'status': row.status,
                    'notes': row.notes,
                },
            )

    @classmethod
    @transaction.atomic
    def reject(cls, leave_request, user=None, note=''):
        from django.utils import timezone

        leave_request.status = LeaveRequest.REJECTED
        leave_request.decided_by = user
        leave_request.decided_at = timezone.now()
        leave_request.decision_note = note
        leave_request.save(update_fields=[
            'status', 'decided_by', 'decided_at', 'decision_note',
        ])
        balance = cls.get_or_create_balance(
            leave_request.employee, leave_request.leave_type, leave_request.start_date.year
        )
        balance.pending_days = max(ZERO, _d(balance.pending_days) - _d(leave_request.days))
        balance.save(update_fields=['pending_days'])
        return leave_request

    @classmethod
    @transaction.atomic
    def cancel(cls, leave_request, user=None):
        """Cancel a request, releasing held or taken days and clearing attendance."""
        was_approved = leave_request.status == LeaveRequest.APPROVED
        leave_request.status = LeaveRequest.CANCELLED
        leave_request.save(update_fields=['status'])

        balance = cls.get_or_create_balance(
            leave_request.employee, leave_request.leave_type, leave_request.start_date.year
        )
        days = _d(leave_request.days)
        if was_approved:
            balance.taken_days = max(ZERO, _d(balance.taken_days) - days)
            Attendance.objects.filter(
                employee=leave_request.employee,
                date__gte=leave_request.start_date,
                date__lte=leave_request.end_date,
                notes__endswith='(auto)',
            ).delete()
        else:
            balance.pending_days = max(ZERO, _d(balance.pending_days) - days)
        balance.save(update_fields=['taken_days', 'pending_days'])
        return leave_request

    @classmethod
    def carry_forward_year_end(cls, organisation, prior_year, new_year):
        """
        Recompute-and-SET (never increment) new_year's ``carried_forward`` for
        every employee/paid-leave-type balance to
        min(prior_year_available_days, leave_type.carry_forward_max).

        Safe to re-run: since this always overwrites rather than adds, running
        it twice for the same year pair is a no-op the second time (assuming
        no new leave activity happened in between).
        """
        prior_balances = list(
            LeaveBalance.objects.filter(organisation=organisation, year=prior_year)
            .select_related('leave_type', 'employee')
        )
        updated = 0
        for prior in prior_balances:
            if not prior.leave_type.is_paid:
                continue
            carry = min(max(ZERO, prior.available_days), _d(prior.leave_type.carry_forward_max))
            new_balance = cls.get_or_create_balance(prior.employee, prior.leave_type, new_year)
            if _d(new_balance.carried_forward) != carry:
                new_balance.carried_forward = carry
                new_balance.save(update_fields=['carried_forward'])
                updated += 1
        return updated

    @classmethod
    def carry_forward_preview(cls, organisation, prior_year):
        """
        Read-only preview of what a carry-forward run would set for each
        employee/leave-type, without writing anything. Powers the frontend's
        year-end review table.
        """
        prior_balances = (
            LeaveBalance.objects.filter(
                organisation=organisation, year=prior_year, leave_type__is_paid=True,
            )
            .select_related('leave_type', 'employee')
        )
        rows = []
        for prior in prior_balances:
            carry = min(max(ZERO, prior.available_days), _d(prior.leave_type.carry_forward_max))
            if carry <= ZERO:
                continue
            rows.append({
                'employee_id': str(prior.employee_id),
                'employee_name': prior.employee.full_name,
                'leave_type': prior.leave_type.name,
                'available_days': prior.available_days,
                'carry_forward_max': prior.leave_type.carry_forward_max,
                'projected_carried_forward': carry,
            })
        return rows


class LeaveEncashmentService:
    """
    Leave encashment: converting unused paid-leave days into cash, via the
    existing PayrollAdjustment mechanism (ENCASHMENT type) so it flows into
    PayrollService's extra_gross the same way arrears/back-pay already do.
    """

    @staticmethod
    def daily_rate(employee):
        """Gross monthly salary / WORKING_DAYS_PER_MONTH — the standard Nigerian
        payroll convention for a daily-rate conversion. Shares its divisor with
        AccountingService.post_leave_accrual_true_up's daily-rate calc via the
        single canonical constant in constants.py, so the two can never
        silently diverge."""
        gross = _d(employee.gross_salary)
        return (gross / Decimal(WORKING_DAYS_PER_MONTH)).quantize(CENTS)

    @classmethod
    @transaction.atomic
    def request_encashment(cls, employee, leave_type, days, reason=''):
        """
        Create a pending PayrollAdjustment(ENCASHMENT) for ``days`` of the
        given paid leave type, and hold those days against the balance
        (mirrors how a leave request holds pending_days).
        """
        if not leave_type.is_paid:
            raise ValueError('Only paid leave types can be encashed.')
        days = _d(days)
        if days <= ZERO:
            raise ValueError('Days must be greater than zero.')

        balance = LeaveService.get_or_create_balance(employee, leave_type, date.today().year)
        if days > balance.available_days:
            raise ValueError(
                f'Only {balance.available_days} days are available to encash.'
            )

        rate = cls.daily_rate(employee)
        amount = (rate * days).quantize(CENTS)

        adjustment = PayrollAdjustment.objects.create(
            organisation=employee.organisation,
            employee=employee,
            adjustment_type=PayrollAdjustment.ENCASHMENT,
            amount=amount,
            reason=reason or f'Leave encashment — {leave_type.name} ({days} days)',
            status=PayrollAdjustment.PENDING,
        )
        balance.taken_days = _d(balance.taken_days) + days
        balance.save(update_fields=['taken_days'])
        return adjustment


class EWAService:
    """
    Earned wage access: an advance on wages already earned this period.

    Employer-funded and employer-recovered, which is what keeps it outside
    consumer-lending territory. Eligibility is bounded by accrued earnings, and
    approval is additionally gated on the organisation's own cash position —
    the underwriting signal an HR-only platform does not hold.
    """

    @staticmethod
    def get_policy(organisation):
        policy, _ = AdvancePolicy.objects.get_or_create(organisation=organisation)
        return policy

    @classmethod
    def accrued_net(cls, employee, as_of=None):
        """
        Net pay earned so far this period.

        Uses the same proration machinery as the payroll run, so the number an
        employee sees in the portal is the number the run will produce.
        """
        as_of = as_of or date.today()
        period_start = date(as_of.year, as_of.month, 1)
        period_end = date(as_of.year, as_of.month, calendar.monthrange(as_of.year, as_of.month)[1])

        days_in_period = ProrationService.working_days(period_start, period_end)
        effective_start = max(period_start, employee.hire_date or period_start)
        days_worked = ProrationService.working_days(effective_start, min(as_of, period_end))
        if days_in_period == 0:
            return ZERO, ZERO, ZERO

        components = CompensationService.components_as_of(employee, period_end)
        full_factor = Decimal('1')
        profile = EmployeeTaxProfile.objects.filter(employee=employee).first()
        full_calc = PayrollService.calculate_employee_paye(
            employee, tax_profile=profile, components=components, proration_factor=full_factor,
        )
        full_net = _d(full_calc['net_salary'])
        earned_factor = (Decimal(str(days_worked)) / Decimal(str(days_in_period))).quantize(
            Decimal('0.0001')
        )
        accrued = (full_net * earned_factor).quantize(CENTS)
        return accrued, Decimal(str(days_worked)), Decimal(str(days_in_period))

    @classmethod
    def eligibility(cls, employee, as_of=None):
        """Return a dict describing what this employee may draw right now."""
        as_of = as_of or date.today()
        policy = cls.get_policy(employee.organisation)
        accrued, days_worked, days_in_period = cls.accrued_net(employee, as_of)

        reasons = []
        if not policy.is_enabled:
            reasons.append('Salary advances are not enabled for this organisation')

        if employee.hire_date:
            months_employed = (
                (as_of.year - employee.hire_date.year) * 12
                + (as_of.month - employee.hire_date.month)
            )
        else:
            months_employed = 0
        if months_employed < policy.min_months_employed:
            reasons.append(
                f'Requires {policy.min_months_employed} months of service '
                f'({months_employed} completed)'
            )

        taken = AdvanceRequest.objects.filter(
            employee=employee, period_year=as_of.year, period_month=as_of.month,
        ).exclude(status__in=[AdvanceRequest.REJECTED, AdvanceRequest.CANCELLED])
        if taken.count() >= policy.max_requests_per_period:
            reasons.append('Advance limit for this period already reached')

        already = sum((_d(a.amount) for a in taken), ZERO)
        cap = (accrued * _d(policy.max_percent_of_accrued) / 100).quantize(CENTS)
        available = max(ZERO, cap - already)
        if available < _d(policy.min_amount):
            reasons.append(f'Below the minimum advance of {policy.min_amount}')

        return {
            'eligible': not reasons,
            'reasons': reasons,
            'accrued_net': accrued,
            'available': available,
            'cap': cap,
            'already_drawn': already,
            'days_worked': days_worked,
            'days_in_period': days_in_period,
            'fee_percent': _d(policy.fee_percent),
            'min_amount': _d(policy.min_amount),
            'max_percent_of_accrued': _d(policy.max_percent_of_accrued),
        }

    @classmethod
    def can_employer_fund(cls, organisation, amount):
        """
        The ledger-underwriting gate.

        Reads the organisation's own cash position — the thing a payroll-only
        platform cannot see — and refuses an advance that would push the
        business below its configured buffer.
        """
        policy = cls.get_policy(organisation)
        if _d(policy.min_cash_buffer) <= ZERO:
            return True, ''
        try:
            from apps.accounting.services import AccountingService
            cash = _d(AccountingService.get_cash_position(organisation))
        except Exception:
            # If the ledger cannot be read, do not block payroll operations.
            return True, ''
        if cash - _d(amount) < _d(policy.min_cash_buffer):
            return False, (
                f'Approving this advance would leave the business below its '
                f'{policy.min_cash_buffer} cash buffer'
            )
        return True, ''

    @classmethod
    @transaction.atomic
    def request(cls, employee, amount, reason='', as_of=None):
        as_of = as_of or date.today()
        amount = _d(amount)
        info = cls.eligibility(employee, as_of)
        if not info['eligible']:
            raise ValueError('; '.join(info['reasons']))
        if amount > info['available']:
            raise ValueError(
                f"Requested {amount} exceeds the available {info['available']}"
            )
        policy = cls.get_policy(employee.organisation)
        fee = (amount * _d(policy.fee_percent) / 100).quantize(CENTS)
        return AdvanceRequest.objects.create(
            organisation=employee.organisation,
            employee=employee,
            amount=amount,
            fee=fee,
            total_recoverable=amount + fee,
            period_year=as_of.year,
            period_month=as_of.month,
            reason=reason,
            accrued_at_request=info['accrued_net'],
            days_worked_at_request=info['days_worked'],
            status=AdvanceRequest.PENDING if policy.require_approval else AdvanceRequest.APPROVED,
        )


class OffboardingService:
    """Employee exit workflow: case creation, clearance checklist, final settlement, revocation."""

    @staticmethod
    def seed_checklist_template(organisation):
        """Idempotently create the org's default checklist template items."""
        existing = set(
            OffboardingChecklistTemplate.objects.filter(organisation=organisation)
            .values_list('item_name', flat=True)
        )
        to_create = [
            OffboardingChecklistTemplate(
                organisation=organisation, item_name=name, department=dept, order=i,
            )
            for i, (name, dept) in enumerate(DEFAULT_OFFBOARDING_CHECKLIST_ITEMS)
            if name not in existing
        ]
        if to_create:
            OffboardingChecklistTemplate.objects.bulk_create(to_create)
        return OffboardingChecklistTemplate.objects.filter(organisation=organisation)

    @classmethod
    @transaction.atomic
    def create_case(cls, employee, initiated_by, reason, last_working_day, notice_period_days=0, notes=''):
        """Create a case and populate its checklist from the org's template."""
        case = OffboardingCase.objects.create(
            organisation=employee.organisation,
            employee=employee,
            initiated_by=initiated_by,
            reason=reason,
            last_working_day=last_working_day,
            notice_period_days=notice_period_days,
            notes=notes,
        )
        templates = cls.seed_checklist_template(employee.organisation)
        items = [
            ClearanceChecklistItem(
                organisation=employee.organisation, case=case,
                item_name=t.item_name, department=t.department, order=t.order,
            )
            for t in templates
        ]
        if items:
            ClearanceChecklistItem.objects.bulk_create(items)
        return case

    @staticmethod
    def compute_gratuity(employee, settings_row, last_working_day):
        """
        Gratuity = gratuity_rate_per_year × completed years of service.

        There is NO universal Nigerian statutory gratuity formula, so this is
        purely a per-org policy figure (PayrollSettings.gratuity_rate_per_year,
        default 0 = off). Routed as fully taxable ordinary income — no
        exemption logic is applied here, pending practitioner confirmation of
        whether any portion of gratuity qualifies for tax-exempt treatment
        under NTA 2025.
        """
        rate = _d(settings_row.gratuity_rate_per_year)
        if rate <= ZERO or not employee.hire_date:
            return ZERO
        days_served = (last_working_day - employee.hire_date).days
        completed_years = max(0, days_served // 365)
        return (rate * completed_years).quantize(CENTS)

    @classmethod
    @transaction.atomic
    def run_final_settlement(cls, case, processed_by):
        """
        Raise a FINAL_SETTLEMENT payroll run for the departing employee,
        including: pro-rated final pay (via the normal run engine, since
        termination_date bounds proration automatically), unused-leave
        encashment (positive balance) or recovery (negative balance — a
        NEGATIVE balance at exit is deducted, never written off), and
        gratuity if the org has a policy rate configured.
        """
        employee = case.employee
        org = employee.organisation
        settings_row = get_settings(org)
        year, month = case.last_working_day.year, case.last_working_day.month

        # Unused leave payout / recovery across every paid leave type the
        # employee could plausibly carry a balance for. ``is_active`` only
        # gates whether a leave type accepts NEW bookings/accruals going
        # forward — it must NOT gate whether an already-accrued balance is
        # honoured at exit. A type deactivated after the employee accrued
        # against it would otherwise be silently skipped here, and the
        # employee would lose real encashable days with no payout and no
        # error. So: every leave type the employee has a LeaveBalance row for
        # this year, plus every currently-active paid type (covers a type the
        # employee never touched but is still entitled to at exit), unioned
        # and de-duplicated — filtered only by is_paid, never by is_active.
        existing_balance_type_ids = set(
            LeaveBalance.objects.filter(
                organisation=org, employee=employee, year=year, leave_type__is_paid=True,
            ).values_list('leave_type_id', flat=True)
        )
        active_paid_type_ids = set(
            LeaveType.objects.filter(
                organisation=org, is_paid=True, is_active=True,
            ).values_list('id', flat=True)
        )
        leave_type_ids = existing_balance_type_ids | active_paid_type_ids
        for leave_type in LeaveType.objects.filter(organisation=org, id__in=leave_type_ids):
            balance = LeaveService.get_or_create_balance(employee, leave_type, year)
            available = balance.available_days
            if available == ZERO:
                continue
            rate = LeaveEncashmentService.daily_rate(employee)
            if available > ZERO:
                amount = (rate * available).quantize(CENTS)
                reason = f'Final settlement — unused {leave_type.name} payout ({available} days)'
            else:
                # Negative balance: recovered (deducted), not written off.
                amount = (rate * available).quantize(CENTS)  # available is negative → amount negative
                reason = f'Final settlement — {leave_type.name} recovery (overdrawn {-available} days)'
            PayrollAdjustment.objects.create(
                organisation=org, employee=employee,
                adjustment_type=PayrollAdjustment.ENCASHMENT,
                amount=amount, reason=reason, status=PayrollAdjustment.PENDING,
            )

        gratuity = cls.compute_gratuity(employee, settings_row, case.last_working_day)
        if gratuity > ZERO:
            PayrollAdjustment.objects.create(
                organisation=org, employee=employee,
                adjustment_type=PayrollAdjustment.BACKPAY,
                amount=gratuity,
                reason=(
                    f'Gratuity — {gratuity} (taxable ordinary income; '
                    f'exemption treatment pending practitioner sign-off)'
                ),
                status=PayrollAdjustment.PENDING,
            )

        last = (
            PayrollRun.objects
            .filter(organisation=org, period_year=year, period_month=month, run_type=PayrollRun.FINAL_SETTLEMENT)
            .order_by('-sequence').first()
        )
        next_seq = (last.sequence + 1) if last else 1
        run = PayrollRun.objects.create(
            organisation=org, period_year=year, period_month=month,
            run_type=PayrollRun.FINAL_SETTLEMENT, sequence=next_seq,
            processed_by=processed_by,
            period_start=date(year, month, 1),
            period_end=case.last_working_day,
            pay_frequency=settings_row.default_pay_frequency,
        )
        run = PayrollService.run_payroll(run)
        case.final_settlement_run = run
        case.save(update_fields=['final_settlement_run'])
        return run

    @classmethod
    @transaction.atomic
    def complete(cls, case, user=None):
        """
        Finalize an offboarding case: deactivate the Membership row for THIS
        organisation only — never the User account, since a user may hold
        memberships in other organisations. This is only ever triggered by an
        explicit finalize action, never by merely setting termination_date
        (HR routinely back-plans a future termination date without meaning to
        revoke access yet).
        """
        from apps.tenancy.models import Membership

        employee = case.employee
        employee.termination_date = employee.termination_date or case.last_working_day
        employee.is_active = False
        employee.save(update_fields=['termination_date', 'is_active'])

        if employee.user_id:
            Membership.objects.filter(
                organisation=employee.organisation, user=employee.user,
            ).update(is_active=False)

        from django.utils import timezone
        case.status = OffboardingCase.COMPLETED
        case.completed_by = user
        case.completed_at = timezone.now()
        case.save(update_fields=['status', 'completed_by', 'completed_at'])
        return case
