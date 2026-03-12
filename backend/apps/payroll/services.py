from decimal import Decimal
from django.db import transaction
from .models import Employee, EmployeePenalty, EmployeeLoan, PayrollRun, PayslipLine


class PayrollService:
    PENSION_RATE_EMPLOYEE = Decimal('0.08')    # 8%
    PENSION_RATE_EMPLOYER = Decimal('0.10')    # 10%
    NHF_RATE = Decimal('0.025')               # 2.5% of basic salary
    NSITF_RATE = Decimal('0.01')              # 1% of gross (employer only)
    CRA_FLAT_ANNUAL = Decimal('200000')
    CRA_MIN_RATE = Decimal('0.01')
    CRA_RATE = Decimal('0.20')

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
        employees = list(
            Employee.objects.filter(organisation=org, is_active=True, termination_date__isnull=True)
        )
        PayslipLine.objects.filter(payroll_run=payroll_run).delete()

        emp_ids = [e.id for e in employees]

        # Pre-fetch and lock all pending penalties + active loans for this org's employees
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

        totals = {
            'gross': Decimal('0'), 'deductions': Decimal('0'), 'net': Decimal('0'),
            'paye': Decimal('0'), 'pension_emp': Decimal('0'), 'pension_employer': Decimal('0'),
            'nhf': Decimal('0'), 'nsitf': Decimal('0'),
        }

        payslips = []
        penalties_to_update = []
        loans_to_update = []

        for emp in employees:
            calc = cls.calculate_employee_paye(emp)

            # Penalties: sum all pending and mark applied
            emp_penalties = penalties_by_emp.get(emp.id, [])
            penalty_total = sum(Decimal(str(p.amount)) for p in emp_penalties)
            for p in emp_penalties:
                p.status = EmployeePenalty.APPLIED
                p.applied_in_run = payroll_run
                penalties_to_update.append(p)

            # Loan installments: deduct each active loan's monthly installment
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

            extra = penalty_total + loan_total
            adjusted_deductions = calc['total_deductions'] + extra
            adjusted_net = max(Decimal('0'), calc['net_salary'] - extra)

            payslips.append(PayslipLine(
                organisation=org,
                payroll_run=payroll_run,
                employee=emp,
                **{k: v for k, v in calc.items() if k not in ('total_deductions', 'net_salary')},
                penalty_deductions=penalty_total,
                loan_deductions=loan_total,
                total_deductions=adjusted_deductions,
                net_salary=adjusted_net,
            ))

            totals['gross'] += calc['gross_salary']
            totals['deductions'] += adjusted_deductions
            totals['net'] += adjusted_net
            totals['paye'] += calc['paye_tax']
            totals['pension_emp'] += calc['employee_pension']
            totals['pension_employer'] += calc['employer_pension']
            totals['nhf'] += calc['nhf']
            totals['nsitf'] += calc['nsitf']

        PayslipLine.objects.bulk_create(payslips)

        if penalties_to_update:
            EmployeePenalty.objects.bulk_update(penalties_to_update, ['status', 'applied_in_run'])
        if loans_to_update:
            EmployeeLoan.objects.bulk_update(loans_to_update, ['amount_repaid', 'status'])

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
