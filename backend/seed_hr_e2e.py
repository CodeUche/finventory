"""
Seed a throwaway database for the HR module browser E2E run.

Usage:
    DB_NAME=finventory_hrtest python seed_hr_e2e.py

Creates one organisation with an owner, five employees spanning the cases the HR
module has to get right (full-month, mid-month joiner, leaver, no state of
residence, portal user), plus a benefit plan and a payroll run.
"""

import os
import sys
from datetime import date
from decimal import Decimal

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from django.core.cache import cache  # noqa: E402
from django.conf import settings  # noqa: E402

from apps.authentication.models import User  # noqa: E402
from apps.payroll.models import (  # noqa: E402
    BenefitPlan, Employee, EmployeeBenefit, PayrollRun,
)
from apps.payroll.services import (  # noqa: E402
    EWAService, LeaveService, PayrollService, TaxAuthorityService,
)
from apps.subscriptions.models import Plan  # noqa: E402
from apps.subscriptions.services import SubscriptionService  # noqa: E402
from apps.tenancy.models import Membership  # noqa: E402
from apps.tenancy.services import OrganisationService  # noqa: E402

OWNER_EMAIL = "hr.owner@audity.test"
OWNER_PASSWORD = "HrTestPass123!"
EMPLOYEE_EMAIL = "ada.okonkwo@audity.test"
EMPLOYEE_PASSWORD = "EmpTestPass123!"


def main():
    if User.objects.filter(email=OWNER_EMAIL).exists():
        print("already seeded")
        return

    owner = User.objects.create_user(
        email=OWNER_EMAIL, password=OWNER_PASSWORD,
        first_name="Chidi", last_name="Bello", is_verified=True,
    )
    # Without this the terms gate modal covers the app and intercepts every click.
    owner.terms_accepted_version = settings.LEGAL_TERMS_VERSION
    owner.save()

    org = OrganisationService.create_organisation(
        name="Nexa Foods Ltd", owner=owner,
        extra={"currency": "NGN", "country": "NG"},
    )
    SubscriptionService.upgrade_plan(org, Plan.objects.get(slug="business"))
    org.refresh_from_db()

    TaxAuthorityService.seed(org)
    LeaveService.seed_defaults(org)

    common = dict(
        organisation=org, job_title="Analyst", department="Finance",
        housing_allowance=Decimal("100000"), transport_allowance=Decimal("50000"),
        bank_name="Guaranty Trust Bank", bank_code="058",
        account_number="0123456789",
    )

    manager = Employee.objects.create(
        first_name="Chidi", last_name="Bello", email="chidi.bello@audity.test",
        hire_date=date(2019, 1, 7), basic_salary=Decimal("1250000"),
        state_of_residence="FC", pfa_name="ARM Pension", gender="male",
        account_name="Chidi Bello", **common,
    )

    ada = Employee.objects.create(
        first_name="Ada", last_name="Okonkwo", email=EMPLOYEE_EMAIL,
        hire_date=date(2020, 3, 2), basic_salary=Decimal("840000"),
        state_of_residence="LA", pfa_name="ARM Pension", gender="female",
        manager=manager, account_name="Ada Okonkwo", **common,
    )

    Employee.objects.create(
        first_name="Tunde", last_name="Danjuma", email="tunde@audity.test",
        # Mid-month joiner — must be prorated.
        hire_date=date(2026, 6, 16), basic_salary=Decimal("312000"),
        state_of_residence="KD", pfa_name="Stanbic IBTC", gender="male",
        manager=ada, account_name="Tunde Danjuma", **common,
    )

    Employee.objects.create(
        first_name="Bola", last_name="Eze", email="bola@audity.test",
        # Leaver — must still receive a final settlement.
        hire_date=date(2021, 5, 4), termination_date=date(2026, 6, 12),
        basic_salary=Decimal("241800"), state_of_residence="AB",
        pfa_name="Stanbic IBTC", gender="female",
        manager=ada, account_name="Bola Eze", **common,
    )

    Employee.objects.create(
        first_name="Musa", last_name="Yusuf", email="musa@audity.test",
        hire_date=date(2022, 9, 1), basic_salary=Decimal("585000"),
        # Deliberately no state of residence — PAYE must surface as unassigned.
        state_of_residence="", pfa_name="", gender="male",
        manager=manager, account_name="Musa Yusuf", **common,
    )

    plan = BenefitPlan.objects.create(
        organisation=org, name="Hygeia Family", benefit_type=BenefitPlan.HMO,
        provider_name="Hygeia HMO", basis=BenefitPlan.FIXED,
        employee_contribution=Decimal("12000"), employer_contribution=Decimal("18000"),
    )
    EmployeeBenefit.objects.create(
        organisation=org, employee=ada, plan=plan,
        start_date=date(2024, 1, 1), tier="Family",
    )

    policy = EWAService.get_policy(org)
    policy.is_enabled = True
    policy.fee_percent = Decimal("2")
    policy.min_months_employed = 3
    policy.save()

    run = PayrollRun.objects.create(
        organisation=org, period_year=2026, period_month=6, processed_by=owner,
    )
    PayrollService.run_payroll(run)

    # Portal login for Ada
    emp_user = User.objects.create_user(
        email=EMPLOYEE_EMAIL, password=EMPLOYEE_PASSWORD,
        first_name="Ada", last_name="Okonkwo", is_verified=True,
    )
    emp_user.terms_accepted_version = settings.LEGAL_TERMS_VERSION
    emp_user.save()
    Membership.objects.create(
        organisation=org, user=emp_user,
        role=Membership.Role.EMPLOYEE, is_active=True,
    )
    ada.user = emp_user
    ada.save(update_fields=["user"])

    # The user throttle (1000/hour) survives across runs and silently degrades
    # the app once exhausted — clear it for both seeded users.
    for u in (owner, emp_user):
        cache.delete(f"throttle_user_{u.pk}")

    print("seeded org:", org.id)
    print("owner:", OWNER_EMAIL, OWNER_PASSWORD)
    print("employee:", EMPLOYEE_EMAIL, EMPLOYEE_PASSWORD)
    print("run:", run.run_number, "gross:", run.total_gross, "itf:", run.total_itf)
    print("payslips:", run.payslips.count())
    print("remittances:", run.remittances.count())


if __name__ == "__main__":
    sys.exit(main())
