import calendar
from datetime import date
from decimal import Decimal

from django.db import transaction

from .models import (
    Attendance, Bonus, Employee, EmployeeLoan, EmployeePenalty,
    EmployeeTaxProfile, PAYERemittance, PayrollRun, PayslipLine,
)


class PayrollService:
    PENSION_RATE_EMPLOYEE = Decimal('0.08')    # 8%
    PENSION_RATE_EMPLOYER = Decimal('0.10')    # 10%
    NHF_RATE = Decimal('0.025')               # 2.5% of basic salary
    NSITF_RATE = Decimal('0.01')              # 1% of gross (employer-borne)
    CRA_FLAT_ANNUAL = Decimal('200000')
    CRA_MIN_RATE = Decimal('0.01')
    CRA_RATE = Decimal('0.20')
    MINIMUM_TAX_RATE = Decimal('0.01')        # 1% of gross — PAYE floor per PITA

    # Standard working hours per month (8 hrs × 26 days)
    MONTHLY_WORKING_HOURS = Decimal('208')
    OVERTIME_MULTIPLIER = Decimal('1.5')

    # PAYE progressive tax brackets (annual taxable income)
    PAYE_BRACKETS = [
        (Decimal('0'), Decimal('300000'), Decimal('0.07')),
        (Decimal('300000'), Decimal('600000'), Decimal('0.11')),
        (Decimal('600000'), Decimal('1100000'), Decimal('0.15')),
        (Decimal('1100000'), Decimal('1600000'), Decimal('0.19')),
        (Decimal('1600000'), Decimal('3200000'), Decimal('0.21')),
        (Decimal('3200000'), None, Decimal('0.24')),
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

    @classmethod
    def calculate_employee_paye(cls, employee, extra_gross=Decimal('0'), tax_profile=None):
        """
        Calculate full payroll figures for one employee.
        extra_gross: bonus + overtime pay added on top of monthly salary.
        tax_profile: optional EmployeeTaxProfile for individual relief overrides.
        """
        gross = employee.gross_salary + extra_gross
        pension_base = employee.basic_salary + employee.housing_allowance + employee.transport_allowance
        employee_pension = pension_base * cls.PENSION_RATE_EMPLOYEE

        # Voluntary pension top-up from tax profile (additional pre-tax deductible)
        if tax_profile and tax_profile.voluntary_pension:
            employee_pension += Decimal(str(tax_profile.voluntary_pension))

        # NHF: apply only if enrolled (default True), or opt-out via tax profile
        nhf_enrolled = (tax_profile.nhf_enrolled if tax_profile else True)
        nhf = (employee.basic_salary * cls.NHF_RATE) if nhf_enrolled else Decimal('0')

        nsitf = gross * cls.NSITF_RATE

        # Life assurance premium deduction (monthly, pre-tax under PITA s.33(5))
        life_assurance = Decimal(str(tax_profile.life_assurance_premium)) if tax_profile else Decimal('0')

        cra_flat_monthly = cls.CRA_FLAT_ANNUAL / 12
        cra_min_component = max(cra_flat_monthly, gross * cls.CRA_MIN_RATE)
        cra = cra_min_component + gross * cls.CRA_RATE
        taxable_income = max(Decimal('0'), gross - employee_pension - nhf - cra - life_assurance)
        annual_paye = cls.calculate_annual_paye(taxable_income * 12)
        monthly_paye = annual_paye / 12

        # Exempt employees (e.g., diplomatic, approved expatriate relief)
        if tax_profile and tax_profile.paye_exempt:
            monthly_paye = Decimal('0')
        else:
            # Minimum tax rule: PAYE cannot be less than 1% of gross (PITA s.37)
            minimum_tax = gross * cls.MINIMUM_TAX_RATE
            monthly_paye = max(monthly_paye, minimum_tax)

        employer_pension = pension_base * cls.PENSION_RATE_EMPLOYER
        total_deductions = employee_pension + nhf + monthly_paye
        net = gross - total_deductions

        return {
            'basic_salary': employee.basic_salary,
            'housing_allowance': employee.housing_allowance,
            'transport_allowance': employee.transport_allowance,
            'leave_allowance': employee.leave_allowance,
            'other_allowances': employee.other_allowances,
            'gross_salary': gross,
            'employee_pension': employee_pension,
            'nhf': nhf,
            'nsitf': nsitf,
            'consolidated_relief_allowance': cra,
            'taxable_income': taxable_income,
            'paye_tax': monthly_paye,
            'employer_pension': employer_pension,
            'total_deductions': total_deductions,
            'net_salary': net,
        }

    @classmethod
    def _calc_overtime_pay(cls, employee, overtime_hours):
        """Calculate overtime pay: hours × (basic / 208 working hours) × 1.5 multiplier."""
        if not overtime_hours or overtime_hours <= 0:
            return Decimal('0')
        hourly = Decimal(str(employee.basic_salary)) / cls.MONTHLY_WORKING_HOURS
        return (hourly * Decimal(str(overtime_hours)) * cls.OVERTIME_MULTIPLIER).quantize(Decimal('0.01'))

    @classmethod
    def _calc_attendance_deduction(cls, gross, absent_days, period_year, period_month):
        """Deduct proportional salary for absent days (absent_days / working_days_in_month × gross)."""
        if not absent_days or absent_days <= 0:
            return Decimal('0')
        # Working days = weekdays in the month
        _, days_in_month = calendar.monthrange(period_year, period_month)
        weekdays = sum(
            1 for d in range(1, days_in_month + 1)
            if calendar.weekday(period_year, period_month, d) < 5  # Mon–Fri
        )
        working_days = Decimal(str(max(weekdays, 1)))
        return (Decimal(str(gross)) * Decimal(str(absent_days)) / working_days).quantize(Decimal('0.01'))

    @classmethod
    @transaction.atomic
    def run_payroll(cls, payroll_run):
        org = payroll_run.organisation
        year = payroll_run.period_year
        month = payroll_run.period_month

        employees = list(
            Employee.objects.filter(organisation=org, is_active=True, termination_date__isnull=True)
        )
        PayslipLine.objects.filter(payroll_run=payroll_run).delete()

        # Pre-load tax profiles keyed by employee_id
        tax_profiles = {
            tp.employee_id: tp
            for tp in EmployeeTaxProfile.objects.filter(
                organisation=org, employee_id__in=[e.id for e in employees]
            )
        }

        emp_ids = [e.id for e in employees]

        # Pre-fetch and lock all pending penalties + active loans
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

        # Pre-fetch pending bonuses for this period
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

        # Pre-fetch attendance records for this period
        attendance_qs = list(
            Attendance.objects.filter(
                organisation=org, employee_id__in=emp_ids,
                date__year=year, date__month=month,
            )
        )
        # Build per-employee: total_overtime_hours + absent_days
        att_overtime_by_emp: dict = {}
        att_absent_by_emp: dict = {}
        for a in attendance_qs:
            eid = a.employee_id
            att_overtime_by_emp[eid] = att_overtime_by_emp.get(eid, Decimal('0')) + Decimal(str(a.overtime_hours or 0))
            # absent=1 day, half_day=0.5 day; present/leave/holiday = 0
            if a.status == Attendance.ABSENT:
                att_absent_by_emp[eid] = att_absent_by_emp.get(eid, Decimal('0')) + Decimal('1')
            elif a.status == Attendance.HALF_DAY:
                att_absent_by_emp[eid] = att_absent_by_emp.get(eid, Decimal('0')) + Decimal('0.5')

        totals = {
            'gross': Decimal('0'), 'deductions': Decimal('0'), 'net': Decimal('0'),
            'paye': Decimal('0'), 'pension_emp': Decimal('0'), 'pension_employer': Decimal('0'),
            'nhf': Decimal('0'), 'nsitf': Decimal('0'),
            'bonus': Decimal('0'), 'overtime': Decimal('0'),
        }

        payslips = []
        penalties_to_update = []
        loans_to_update = []
        bonuses_to_update = []

        for emp in employees:
            # Bonus total
            emp_bonuses = bonuses_by_emp.get(emp.id, [])
            bonus_total = sum(Decimal(str(b.amount)) for b in emp_bonuses)
            for b in emp_bonuses:
                b.status = Bonus.APPLIED
                b.applied_in_run = payroll_run
                bonuses_to_update.append(b)

            # Overtime pay
            overtime_hrs = att_overtime_by_emp.get(emp.id, Decimal('0'))
            overtime_pay = cls._calc_overtime_pay(emp, overtime_hrs)

            extra_gross = bonus_total + overtime_pay

            # PAYE calc on (gross + bonus + overtime), with individual relief overrides
            calc = cls.calculate_employee_paye(emp, extra_gross=extra_gross, tax_profile=tax_profiles.get(emp.id))

            # Attendance deduction (absent days, applied after PAYE)
            absent_days = att_absent_by_emp.get(emp.id, Decimal('0'))
            attendance_ded = cls._calc_attendance_deduction(calc['gross_salary'], absent_days, year, month)

            # Penalties
            emp_penalties = penalties_by_emp.get(emp.id, [])
            penalty_total = sum(Decimal(str(p.amount)) for p in emp_penalties)
            for p in emp_penalties:
                p.status = EmployeePenalty.APPLIED
                p.applied_in_run = payroll_run
                penalties_to_update.append(p)

            # Loan installments
            loan_total = Decimal('0')
            for loan in loans_by_emp.get(emp.id, []):
                installment = Decimal(str(loan.monthly_installment))
                balance = loan.balance_remaining
                deduct = min(installment, balance)
                loan_total += deduct
                loan.amount_repaid = Decimal(str(loan.amount_repaid)) + deduct
                if loan.balance_remaining <= Decimal('0.01'):
                    loan.status = EmployeeLoan.SETTLED
                loans_to_update.append(loan)

            extra = penalty_total + loan_total + attendance_ded
            adjusted_deductions = calc['total_deductions'] + extra
            adjusted_net = max(Decimal('0'), calc['net_salary'] - extra)

            payslips.append(PayslipLine(
                organisation=org,
                payroll_run=payroll_run,
                employee=emp,
                **{k: v for k, v in calc.items() if k not in ('total_deductions', 'net_salary')},
                bonus_amount=bonus_total,
                overtime_amount=overtime_pay,
                attendance_deduction=attendance_ded,
                penalty_deductions=penalty_total,
                loan_deductions=loan_total,
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

        PayslipLine.objects.bulk_create(payslips)

        if penalties_to_update:
            EmployeePenalty.objects.bulk_update(penalties_to_update, ['status', 'applied_in_run'])
        if loans_to_update:
            EmployeeLoan.objects.bulk_update(loans_to_update, ['amount_repaid', 'status'])
        if bonuses_to_update:
            Bonus.objects.bulk_update(bonuses_to_update, ['status', 'applied_in_run'])

        payroll_run.total_gross = totals['gross']
        payroll_run.total_deductions = totals['deductions']
        payroll_run.total_net = totals['net']
        payroll_run.total_paye = totals['paye']
        payroll_run.total_pension_employee = totals['pension_emp']
        payroll_run.total_pension_employer = totals['pension_employer']
        payroll_run.total_nhf = totals['nhf']
        payroll_run.total_nsitf = totals['nsitf']
        payroll_run.total_bonus = totals['bonus']
        payroll_run.total_overtime = totals['overtime']
        payroll_run.status = PayrollRun.PROCESSING
        payroll_run.save()

        # Auto-create PAYE remittance obligation: due 10th of following month
        if month == 12:
            due_year, due_month = year + 1, 1
        else:
            due_year, due_month = year, month + 1
        PAYERemittance.objects.update_or_create(
            organisation=org,
            period_year=year,
            period_month=month,
            defaults={
                'payroll_run': payroll_run,
                'amount_due': totals['paye'],
                'status': PAYERemittance.PENDING,
                'due_date': date(due_year, due_month, 10),
            },
        )
        return payroll_run
