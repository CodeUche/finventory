from decimal import Decimal
from django.db import transaction
from .models import Employee, PayrollRun, PayslipLine


class PayrollService:
    PENSION_RATE_EMPLOYEE = Decimal('0.08')    # 8%
    PENSION_RATE_EMPLOYER = Decimal('0.10')    # 10%
    NHF_RATE = Decimal('0.025')               # 2.5% of basic salary
    NSITF_RATE = Decimal('0.01')              # 1% of gross (employer only)
    # PITA CRA: max(N200,000 p.a., 1% of gross p.a.) + 20% of gross p.a.
    # Monthly equivalents used since payroll works on monthly figures
    CRA_FLAT_ANNUAL = Decimal('200000')       # N200,000 per annum fixed component
    CRA_MIN_RATE = Decimal('0.01')            # 1% of gross (minimum component)
    CRA_RATE = Decimal('0.20')               # 20% of gross (percentage component)

    # 2024 FIRS PAYE brackets (annual)
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
    def calculate_employee_paye(cls, employee):
        gross = employee.gross_salary
        pension_base = employee.basic_salary + employee.housing_allowance + employee.transport_allowance
        employee_pension = pension_base * cls.PENSION_RATE_EMPLOYEE
        nhf = employee.basic_salary * cls.NHF_RATE
        nsitf = gross * cls.NSITF_RATE

        # CRA per PITA s.33(3)(b): max(N200k p.a., 1% of gross p.a.) + 20% of gross p.a.
        # Converted to monthly: max(N200k/12, 1% of monthly gross) + 20% of monthly gross
        cra_flat_monthly = cls.CRA_FLAT_ANNUAL / 12
        cra_min_component = max(cra_flat_monthly, gross * cls.CRA_MIN_RATE)
        cra = cra_min_component + gross * cls.CRA_RATE
        taxable_income = max(Decimal('0'), gross - employee_pension - nhf - cra)
        annual_paye = cls.calculate_annual_paye(taxable_income * 12)
        monthly_paye = annual_paye / 12

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
    @transaction.atomic
    def run_payroll(cls, payroll_run):
        org = payroll_run.organisation
        employees = Employee.objects.filter(organisation=org, is_active=True, termination_date__isnull=True)

        PayslipLine.objects.filter(payroll_run=payroll_run).delete()

        totals = {
            'gross': Decimal('0'), 'deductions': Decimal('0'), 'net': Decimal('0'),
            'paye': Decimal('0'), 'pension_emp': Decimal('0'), 'pension_employer': Decimal('0'),
            'nhf': Decimal('0'), 'nsitf': Decimal('0')
        }

        payslips = []
        for emp in employees:
            calc = cls.calculate_employee_paye(emp)
            ps = PayslipLine(
                organisation=org,
                payroll_run=payroll_run,
                employee=emp,
                **calc,
            )
            payslips.append(ps)
            totals['gross'] += calc['gross_salary']
            totals['deductions'] += calc['total_deductions']
            totals['net'] += calc['net_salary']
            totals['paye'] += calc['paye_tax']
            totals['pension_emp'] += calc['employee_pension']
            totals['pension_employer'] += calc['employer_pension']
            totals['nhf'] += calc['nhf']
            totals['nsitf'] += calc['nsitf']

        PayslipLine.objects.bulk_create(payslips)

        payroll_run.total_gross = totals['gross']
        payroll_run.total_deductions = totals['deductions']
        payroll_run.total_net = totals['net']
        payroll_run.total_paye = totals['paye']
        payroll_run.total_pension_employee = totals['pension_emp']
        payroll_run.total_pension_employer = totals['pension_employer']
        payroll_run.total_nhf = totals['nhf']
        payroll_run.total_nsitf = totals['nsitf']
        payroll_run.status = PayrollRun.PROCESSING
        payroll_run.save()
        return payroll_run
