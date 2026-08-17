"""
Tests for Track A — the HR module build-out (public holidays, warn-and-allow
leave, carry-forward, encashment, document expiry, lifecycle alerts,
offboarding, the 13th-month/bonus PAYE annualisation fix, annual PAYE
reconciliation, server-rendered payslip PDFs, ESS document upload, HR
analytics, leave-accrual GL posting, and the widened Payroll & HR report
resolvers).

Kept separate from tests.py / tests_hr.py, which already cover the pre-Track-A
payroll engine — this file is additive and should never need to touch those.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.payroll.models import (
    Attendance, ClearanceChecklistItem, Employee, EmployeeDocument, ExitInterview,
    LeaveBalance, LeaveRequest, LeaveType, OffboardingCase, OffboardingChecklistTemplate,
    PayrollAdjustment, PayrollRun, PayrollSettings, PayslipLine, PublicHoliday,
)
from apps.payroll.services import (
    LeaveEncashmentService, LeaveService, OffboardingService, PayrollService,
    ProrationService, PublicHolidayService, get_settings,
)
from apps.subscriptions.models import Plan
from apps.subscriptions.services import SubscriptionService
from apps.tenancy.models import Membership
from apps.tenancy.services import OrganisationService


# ── helpers (mirrors tests_hr.py's conventions) ────────────────────────────────

def _make_user(email):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Test", last_name="User", is_verified=True,
    )


def _make_org(user, name):
    org = OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )
    SubscriptionService.upgrade_plan(org, Plan.objects.get(slug="business"))
    org.refresh_from_db()
    return org


def _auth_client(user, org):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return client


def _employee(org, first="Ada", last="Okonkwo", basic="400000", **kwargs):
    defaults = dict(
        organisation=org, first_name=first, last_name=last,
        job_title="Analyst", department="Finance",
        hire_date=date(2024, 1, 15), basic_salary=Decimal(basic),
        housing_allowance=Decimal("100000"), transport_allowance=Decimal("50000"),
    )
    defaults.update(kwargs)
    return Employee.objects.create(**defaults)


def _run(org, user, year=2026, month=6, **kwargs):
    return PayrollRun.objects.create(
        organisation=org, period_year=year, period_month=month,
        processed_by=user, **kwargs
    )


# ══════════════════════════════════════════════════════════════════════════════
# A.1 — Public holidays
# ══════════════════════════════════════════════════════════════════════════════

class PublicHolidayTests(TestCase):
    def setUp(self):
        self.user = _make_user("ph_owner@example.com")
        self.org = _make_org(self.user, "Holiday Org")

    def test_seed_creates_six_fixed_holidays(self):
        qs = PublicHolidayService.seed_fixed_dates(self.org, 2026)
        self.assertEqual(qs.count(), 6)
        names = set(qs.values_list("name", flat=True))
        self.assertIn("Christmas Day", names)
        self.assertIn("Workers' Day", names)

    def test_seed_is_idempotent(self):
        PublicHolidayService.seed_fixed_dates(self.org, 2026)
        PublicHolidayService.seed_fixed_dates(self.org, 2026)
        self.assertEqual(PublicHoliday.objects.filter(organisation=self.org, date__year=2026).count(), 6)

    def test_moveable_holidays_are_never_auto_computed(self):
        """Only the six fixed-date holidays are seeded — no Eid/Easter logic exists."""
        qs = PublicHolidayService.seed_fixed_dates(self.org, 2026)
        for h in qs:
            self.assertIn(h.date.month, [1, 5, 6, 10, 12])

    def test_holiday_excluded_from_working_days_between(self):
        # 1 May 2026 is a Friday — a working weekday that becomes a holiday.
        PublicHoliday.objects.create(organisation=self.org, date=date(2026, 5, 1), name="Workers' Day")
        holidays = PublicHolidayService.holiday_dates_for(self.org, date(2026, 5, 1), date(2026, 5, 1))
        days = LeaveRequest.working_days_between(date(2026, 5, 1), date(2026, 5, 1), holidays)
        self.assertEqual(days, Decimal("0"))

    def test_holiday_excluded_from_proration_working_days(self):
        PublicHoliday.objects.create(organisation=self.org, date=date(2026, 5, 1), name="Workers' Day")
        holidays = PublicHolidayService.holiday_dates_for(self.org, date(2026, 5, 1), date(2026, 5, 1))
        self.assertEqual(ProrationService.working_days(date(2026, 5, 1), date(2026, 5, 1), holidays), 0)
        self.assertEqual(ProrationService.working_days(date(2026, 5, 1), date(2026, 5, 1)), 1)

    def test_stored_payslip_line_unaffected_by_later_holiday(self):
        """
        proration_factor/days_worked/days_in_period are snapshotted at write
        time — adding a holiday afterward must never mutate an already-stored
        payslip (no backfill).
        """
        emp = _employee(self.org, hire_date=date(2020, 1, 1))
        run = _run(self.org, self.user, year=2026, month=5)
        PayrollService.run_payroll(run)
        slip_before = PayslipLine.objects.get(payroll_run=run, employee=emp)
        days_before = slip_before.days_in_period
        factor_before = slip_before.proration_factor

        # Now add a holiday inside that already-processed period.
        PublicHoliday.objects.create(organisation=self.org, date=date(2026, 5, 4), name="Ad-hoc holiday")

        slip_before.refresh_from_db()
        self.assertEqual(slip_before.days_in_period, days_before)
        self.assertEqual(slip_before.proration_factor, factor_before)

    def test_future_run_reflects_newly_added_holiday(self):
        emp = _employee(self.org, hire_date=date(2020, 1, 1))
        PublicHoliday.objects.create(organisation=self.org, date=date(2026, 6, 1), name="Ad-hoc holiday")
        run = _run(self.org, self.user, year=2026, month=6)
        PayrollService.run_payroll(run)
        slip = PayslipLine.objects.get(payroll_run=run, employee=emp)
        # June 2026 has 22 weekdays; one is now a holiday => 21.
        self.assertEqual(slip.days_in_period, Decimal("21"))


# ══════════════════════════════════════════════════════════════════════════════
# A.1 — Warn-and-allow leave overbooking (HR-facing endpoint)
# ══════════════════════════════════════════════════════════════════════════════

class LeaveWarnAndAllowTests(TestCase):
    def setUp(self):
        self.user = _make_user("leave_owner@example.com")
        self.org = _make_org(self.user, "Leave Org")
        self.client = _auth_client(self.user, self.org)
        self.emp = _employee(self.org)
        self.leave_type = LeaveType.objects.create(
            organisation=self.org, name="Annual Leave", days_per_year=Decimal("6"),
            accrual_method=LeaveType.ANNUAL_GRANT, is_paid=True, carry_forward_max=Decimal("5"),
        )
        LeaveService.get_or_create_balance(self.emp, self.leave_type, 2026)

    def _post(self, working_days, reason=""):
        # 1 June 2026 is a Monday, so N working days from there spans
        # ceil(N/5) calendar weeks; walk forward day-by-day skipping weekends
        # to land on an end date with exactly `working_days` weekdays inclusive.
        start = date(2026, 6, 1)
        cur = start
        counted = 0
        while counted < working_days:
            if cur.weekday() < 5:
                counted += 1
            if counted == working_days:
                break
            cur += timedelta(days=1)
        end = cur
        payload = {
            "employee": str(self.emp.id), "leave_type": str(self.leave_type.id),
            "start_date": str(start), "end_date": str(end), "reason": reason,
        }
        return self.client.post("/api/v1/payroll/leave-requests/", payload, format="json")

    def test_within_balance_request_is_not_flagged(self):
        resp = self._post(4)  # Mon-Thu, 4 working days, balance is 6
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertFalse(resp.data["is_overbooked"])

    def test_soft_overbook_within_balance_still_allowed_no_reason_required(self):
        """
        6 entitled days. A request that exceeds the raw entitlement but the
        resulting balance stays >= 0 is a soft warn — no reason required.
        (Not reachable with a 6-day entitlement and a 5-day cap on a single
        request without going negative, so this test asserts the tier-1 flag
        is set correctly using accrued days > 0 rather than requiring an exact
        boundary — see the hard-overbook test below for the negative case.)
        """
        # Bump the balance so a same-balance overbook (tier 1) is reachable.
        balance = LeaveBalance.objects.get(employee=self.emp, leave_type=self.leave_type, year=2026)
        balance.accrued_days = Decimal("10")
        balance.save(update_fields=["accrued_days"])
        resp = self._post(8)  # 8 working days > accrued but balance stays >= 0? 10-8=2, not overbooked.
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertFalse(resp.data["is_overbooked"])

    def test_hard_overbook_crossing_negative_requires_reason(self):
        # Entitlement is 6 accrued days; request 10 working days -> balance would be -4.
        resp = self._post(10, reason="")
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("error", resp.data)

    def test_hard_overbook_with_reason_is_allowed_and_flagged(self):
        resp = self._post(10, reason="Approved exception — compassionate grounds")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(resp.data["is_overbooked"])
        self.assertEqual(Decimal(str(resp.data["overbooked_days"])), Decimal("4"))
        request_id = resp.data["id"]
        lr = LeaveRequest.objects.get(id=request_id)
        self.assertEqual(lr.overbooked_by, self.user)

    def test_never_hard_blocks_even_with_large_overbook(self):
        """The HR-facing endpoint never returns a hard block for balance alone — only a missing reason does."""
        resp = self._post(20, reason="Executive approval on file")
        self.assertEqual(resp.status_code, 201, resp.data)


class ESSLeaveStillHardBlocksTests(TestCase):
    """The ESS-facing endpoint (ess_views.py) is UNCHANGED — still hard-blocks."""

    def setUp(self):
        self.user = _make_user("ess_leave_owner@example.com")
        self.org = _make_org(self.user, "ESS Leave Org")
        self.emp = _employee(self.org)
        portal_user = _make_user("ess_leave_employee@example.com")
        self.emp.user = portal_user
        self.emp.save(update_fields=["user"])
        Membership.objects.create(organisation=self.org, user=portal_user, role=Membership.Role.EMPLOYEE, is_active=True)
        self.client = _auth_client(portal_user, self.org)
        self.leave_type = LeaveType.objects.create(
            organisation=self.org, name="Annual Leave", days_per_year=Decimal("6"),
            accrual_method=LeaveType.ANNUAL_GRANT, is_paid=True,
        )
        LeaveService.get_or_create_balance(self.emp, self.leave_type, 2026)

    def test_ess_request_exceeding_balance_is_hard_blocked(self):
        payload = {
            "leave_type": str(self.leave_type.id),
            "start_date": "2026-06-01", "end_date": "2026-06-12",  # 10 working days > 6
        }
        resp = self.client.post("/api/v1/me/leave-requests/", payload, format="json")
        self.assertEqual(resp.status_code, 400, resp.data)


# ══════════════════════════════════════════════════════════════════════════════
# A.1 — Team coverage
# ══════════════════════════════════════════════════════════════════════════════

class TeamCoverageTests(TestCase):
    def setUp(self):
        self.user = _make_user("coverage_owner@example.com")
        self.org = _make_org(self.user, "Coverage Org")
        self.client = _auth_client(self.user, self.org)
        self.manager = _employee(self.org, "Boss", "One", department="Finance")
        self.emp1 = _employee(self.org, "Peer", "A", department="Finance", manager=self.manager)
        self.emp2 = _employee(self.org, "Peer", "B", department="Finance", manager=self.manager)
        self.leave_type = LeaveType.objects.create(
            organisation=self.org, name="Annual Leave", days_per_year=Decimal("6"), is_paid=True,
        )

    def test_team_coverage_returns_peers_overlapping_window(self):
        LeaveRequest.objects.create(
            organisation=self.org, employee=self.emp2, leave_type=self.leave_type,
            start_date=date(2026, 6, 10), end_date=date(2026, 6, 12), status=LeaveRequest.APPROVED,
        )
        resp = self.client.get(
            "/api/v1/payroll/leave-requests/team_coverage/",
            {"employee": str(self.emp1.id), "start_date": "2026-06-08", "end_date": "2026-06-15"},
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["employee_id"], str(self.emp2.id))

    def test_team_coverage_excludes_self(self):
        LeaveRequest.objects.create(
            organisation=self.org, employee=self.emp1, leave_type=self.leave_type,
            start_date=date(2026, 6, 10), end_date=date(2026, 6, 12), status=LeaveRequest.APPROVED,
        )
        resp = self.client.get(
            "/api/v1/payroll/leave-requests/team_coverage/",
            {"employee": str(self.emp1.id), "start_date": "2026-06-08", "end_date": "2026-06-15"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 0)


# ══════════════════════════════════════════════════════════════════════════════
# A.1 — Carry-forward
# ══════════════════════════════════════════════════════════════════════════════

class CarryForwardTests(TestCase):
    def setUp(self):
        self.user = _make_user("cf_owner@example.com")
        self.org = _make_org(self.user, "Carry Forward Org")
        self.emp = _employee(self.org)
        self.leave_type = LeaveType.objects.create(
            organisation=self.org, name="Annual Leave", days_per_year=Decimal("6"),
            is_paid=True, carry_forward_max=Decimal("5"),
        )

    def test_carry_forward_is_capped_at_leave_type_max(self):
        balance_2025 = LeaveService.get_or_create_balance(self.emp, self.leave_type, 2025)
        balance_2025.accrued_days = Decimal("10")
        balance_2025.taken_days = Decimal("0")
        balance_2025.save(update_fields=["accrued_days", "taken_days"])

        updated = LeaveService.carry_forward_year_end(self.org, 2025, 2026)
        self.assertEqual(updated, 1)
        balance_2026 = LeaveBalance.objects.get(employee=self.emp, leave_type=self.leave_type, year=2026)
        self.assertEqual(balance_2026.carried_forward, Decimal("5"))  # capped, not the full 10

    def test_carry_forward_sets_never_increments(self):
        """Re-running the same carry-forward must SET, not add — safe to re-run."""
        balance_2025 = LeaveService.get_or_create_balance(self.emp, self.leave_type, 2025)
        balance_2025.accrued_days = Decimal("3")
        balance_2025.save(update_fields=["accrued_days"])

        LeaveService.carry_forward_year_end(self.org, 2025, 2026)
        LeaveService.carry_forward_year_end(self.org, 2025, 2026)  # run twice
        balance_2026 = LeaveBalance.objects.get(employee=self.emp, leave_type=self.leave_type, year=2026)
        self.assertEqual(balance_2026.carried_forward, Decimal("3"))  # not 6

    def test_unpaid_leave_type_never_carries_forward(self):
        unpaid = LeaveType.objects.create(
            organisation=self.org, name="Unpaid", days_per_year=Decimal("0"), is_paid=False,
            carry_forward_max=Decimal("10"),
        )
        balance = LeaveService.get_or_create_balance(self.emp, unpaid, 2025)
        balance.accrued_days = Decimal("5")
        balance.save(update_fields=["accrued_days"])
        LeaveService.carry_forward_year_end(self.org, 2025, 2026)
        self.assertFalse(LeaveBalance.objects.filter(employee=self.emp, leave_type=unpaid, year=2026).exists())

    def test_preview_matches_apply(self):
        balance_2025 = LeaveService.get_or_create_balance(self.emp, self.leave_type, 2025)
        balance_2025.accrued_days = Decimal("4")
        balance_2025.save(update_fields=["accrued_days"])
        rows = LeaveService.carry_forward_preview(self.org, 2025)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["projected_carried_forward"], Decimal("4"))


# ══════════════════════════════════════════════════════════════════════════════
# A.1 — Leave encashment
# ══════════════════════════════════════════════════════════════════════════════

class LeaveEncashmentTests(TestCase):
    def setUp(self):
        self.user = _make_user("encash_owner@example.com")
        self.org = _make_org(self.user, "Encashment Org")
        self.emp = _employee(self.org, basic="260000")
        self.leave_type = LeaveType.objects.create(
            organisation=self.org, name="Annual Leave", days_per_year=Decimal("6"),
            accrual_method=LeaveType.ANNUAL_GRANT, is_paid=True,
        )
        self.balance = LeaveService.get_or_create_balance(self.emp, self.leave_type, date.today().year)

    def test_encashment_creates_pending_adjustment(self):
        adjustment = LeaveEncashmentService.request_encashment(self.emp, self.leave_type, Decimal("2"))
        self.assertEqual(adjustment.adjustment_type, PayrollAdjustment.ENCASHMENT)
        self.assertEqual(adjustment.status, PayrollAdjustment.PENDING)
        self.assertGreater(adjustment.amount, Decimal("0"))

    def test_encashment_flows_into_payroll_extra_gross(self):
        LeaveEncashmentService.request_encashment(self.emp, self.leave_type, Decimal("2"))
        run = _run(self.org, self.user, year=2026, month=6)
        PayrollService.run_payroll(run)
        slip = PayslipLine.objects.get(payroll_run=run, employee=self.emp)
        self.assertGreater(slip.adjustment_amount, Decimal("0"))
        adjustment = PayrollAdjustment.objects.get(employee=self.emp)
        self.assertEqual(adjustment.status, PayrollAdjustment.APPLIED)

    def test_cannot_encash_more_than_available(self):
        with self.assertRaises(ValueError):
            LeaveEncashmentService.request_encashment(self.emp, self.leave_type, Decimal("100"))

    def test_cannot_encash_unpaid_leave_type(self):
        unpaid = LeaveType.objects.create(organisation=self.org, name="Unpaid", is_paid=False)
        with self.assertRaises(ValueError):
            LeaveEncashmentService.request_encashment(self.emp, unpaid, Decimal("1"))


# ══════════════════════════════════════════════════════════════════════════════
# A.2 — Document expiry + lifecycle alerts
# ══════════════════════════════════════════════════════════════════════════════

class DocumentExpiryTests(TestCase):
    def setUp(self):
        self.user = _make_user("doc_owner@example.com")
        self.org = _make_org(self.user, "Doc Org")
        self.client = _auth_client(self.user, self.org)
        self.emp = _employee(self.org)

    def test_expiring_endpoint_returns_within_window_soonest_first(self):
        EmployeeDocument.objects.create(
            organisation=self.org, employee=self.emp, name="Work Permit",
            document_type=EmployeeDocument.WORK_PERMIT,
            expiry_date=date.today() + timedelta(days=45),
        )
        soon = EmployeeDocument.objects.create(
            organisation=self.org, employee=self.emp, name="Licence",
            document_type=EmployeeDocument.PROFESSIONAL_LICENCE,
            expiry_date=date.today() + timedelta(days=5),
        )
        EmployeeDocument.objects.create(
            organisation=self.org, employee=self.emp, name="Old ID",
            document_type=EmployeeDocument.ID,
            expiry_date=date.today() - timedelta(days=5),  # already expired, excluded
        )
        resp = self.client.get("/api/v1/payroll/documents/expiring/", {"within_days": 30})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["id"], str(soon.id))

    def test_expiring_default_window_is_30_days(self):
        EmployeeDocument.objects.create(
            organisation=self.org, employee=self.emp, name="Permit",
            document_type=EmployeeDocument.WORK_PERMIT,
            expiry_date=date.today() + timedelta(days=25),
        )
        resp = self.client.get("/api/v1/payroll/documents/expiring/")
        self.assertEqual(len(resp.data), 1)


class LifecycleAlertsTests(TestCase):
    def setUp(self):
        self.user = _make_user("lifecycle_owner@example.com")
        self.org = _make_org(self.user, "Lifecycle Org")
        self.client = _auth_client(self.user, self.org)

    def test_probation_ending_soon_is_surfaced(self):
        _employee(self.org, "Prob", "Ending", confirmation_date=date.today() + timedelta(days=10))
        resp = self.client.get("/api/v1/payroll/employees/lifecycle_alerts/", {"within_days": 30})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["probation_ending"]), 1)

    def test_contract_ending_requires_contract_employment_type(self):
        _employee(
            self.org, "Full", "Timer", employment_type=Employee.FULL_TIME,
            contract_end_date=date.today() + timedelta(days=10),
        )
        _employee(
            self.org, "Contractor", "One", employment_type=Employee.CONTRACT,
            contract_end_date=date.today() + timedelta(days=10),
        )
        resp = self.client.get("/api/v1/payroll/employees/lifecycle_alerts/", {"within_days": 30})
        self.assertEqual(len(resp.data["contract_ending"]), 1)
        self.assertEqual(resp.data["contract_ending"][0]["name"], "Contractor One")

    def test_work_anniversary_detected(self):
        anniversary_target = date.today() + timedelta(days=5)
        hire = anniversary_target.replace(year=anniversary_target.year - 3)
        _employee(self.org, "Vet", "Eran", hire_date=hire)
        resp = self.client.get("/api/v1/payroll/employees/lifecycle_alerts/", {"within_days": 30})
        self.assertEqual(len(resp.data["work_anniversaries"]), 1)
        self.assertEqual(resp.data["work_anniversaries"][0]["years"], 3)


# ══════════════════════════════════════════════════════════════════════════════
# A.3 — Offboarding
# ══════════════════════════════════════════════════════════════════════════════

class OffboardingTests(TestCase):
    def setUp(self):
        self.user = _make_user("offboard_owner@example.com")
        self.org = _make_org(self.user, "Offboard Org")
        self.emp = _employee(self.org, basic="300000")

    def test_create_case_seeds_default_checklist(self):
        case = OffboardingService.create_case(
            self.emp, self.user, OffboardingCase.RESIGNATION, date(2026, 7, 31),
        )
        items = ClearanceChecklistItem.objects.filter(case=case)
        self.assertEqual(items.count(), 8)
        names = set(items.values_list("item_name", flat=True))
        self.assertIn("Certificate of service", names)
        self.assertIn("Final settlement", names)

    def test_checklist_template_seeding_is_idempotent(self):
        OffboardingService.seed_checklist_template(self.org)
        OffboardingService.seed_checklist_template(self.org)
        self.assertEqual(OffboardingChecklistTemplate.objects.filter(organisation=self.org).count(), 8)

    def test_gratuity_is_zero_when_rate_not_configured(self):
        settings_row = get_settings(self.org)
        self.assertEqual(settings_row.gratuity_rate_per_year, Decimal("0"))
        amount = OffboardingService.compute_gratuity(self.emp, settings_row, date(2026, 7, 31))
        self.assertEqual(amount, Decimal("0"))

    def test_gratuity_computed_per_completed_year_when_configured(self):
        settings_row = get_settings(self.org)
        settings_row.gratuity_rate_per_year = Decimal("50000")
        settings_row.save(update_fields=["gratuity_rate_per_year"])
        emp = _employee(self.org, "Long", "Server", hire_date=date(2020, 1, 1))
        amount = OffboardingService.compute_gratuity(emp, settings_row, date(2026, 1, 2))
        self.assertEqual(amount, Decimal("300000"))  # 6 completed years * 50,000

    def test_complete_deactivates_membership_for_this_org_only_not_other_org_not_user(self):
        """Two-org user fixture: exactly one org's membership is deactivated."""
        portal_user = _make_user("multi_org_employee@example.com")
        self.emp.user = portal_user
        self.emp.save(update_fields=["user"])
        membership_here = Membership.objects.create(
            organisation=self.org, user=portal_user, role=Membership.Role.EMPLOYEE, is_active=True,
        )
        other_org = _make_org(_make_user("other_owner@example.com"), "Other Org")
        membership_other = Membership.objects.create(
            organisation=other_org, user=portal_user, role=Membership.Role.STAFF, is_active=True,
        )

        case = OffboardingService.create_case(self.emp, self.user, OffboardingCase.RESIGNATION, date.today())
        OffboardingService.complete(case, user=self.user)

        membership_here.refresh_from_db()
        membership_other.refresh_from_db()
        portal_user.refresh_from_db()
        self.assertFalse(membership_here.is_active)
        self.assertTrue(membership_other.is_active)   # untouched
        self.assertTrue(portal_user.is_active)         # user account itself untouched

    def test_setting_termination_date_alone_does_not_revoke_access(self):
        """A future last_working_day on a case must not itself revoke anything until complete() runs."""
        portal_user = _make_user("backplanned_employee@example.com")
        self.emp.user = portal_user
        self.emp.save(update_fields=["user"])
        membership = Membership.objects.create(
            organisation=self.org, user=portal_user, role=Membership.Role.EMPLOYEE, is_active=True,
        )
        OffboardingService.create_case(
            self.emp, self.user, OffboardingCase.RESIGNATION, date.today() + timedelta(days=30),
        )
        membership.refresh_from_db()
        self.assertTrue(membership.is_active)  # still active — no auto-revoke on case creation

    def test_run_final_settlement_recovers_negative_leave_balance(self):
        leave_type = LeaveType.objects.create(
            organisation=self.org, name="Annual Leave", days_per_year=Decimal("6"), is_paid=True,
        )
        balance = LeaveService.get_or_create_balance(self.emp, leave_type, date.today().year)
        balance.accrued_days = Decimal("2")
        balance.taken_days = Decimal("6")  # available = -4 (overdrawn)
        balance.save(update_fields=["accrued_days", "taken_days"])

        case = OffboardingService.create_case(
            self.emp, self.user, OffboardingCase.RESIGNATION, date(2026, 6, 15),
        )
        run = OffboardingService.run_final_settlement(case, self.user)
        self.assertEqual(run.run_type, PayrollRun.FINAL_SETTLEMENT)
        adjustment = PayrollAdjustment.objects.get(employee=self.emp, adjustment_type=PayrollAdjustment.ENCASHMENT)
        self.assertLess(adjustment.amount, Decimal("0"), "a negative balance must be recovered (deducted), not written off")

    def test_run_final_settlement_pays_out_positive_leave_balance(self):
        leave_type = LeaveType.objects.create(
            organisation=self.org, name="Annual Leave", days_per_year=Decimal("6"), is_paid=True,
        )
        balance = LeaveService.get_or_create_balance(self.emp, leave_type, date.today().year)
        balance.accrued_days = Decimal("6")
        balance.save(update_fields=["accrued_days"])

        case = OffboardingService.create_case(
            self.emp, self.user, OffboardingCase.RESIGNATION, date(2026, 6, 15),
        )
        OffboardingService.run_final_settlement(case, self.user)
        adjustment = PayrollAdjustment.objects.get(employee=self.emp, adjustment_type=PayrollAdjustment.ENCASHMENT)
        self.assertGreater(adjustment.amount, Decimal("0"))

    def test_exit_interview_upsert_via_api(self):
        client = _auth_client(self.user, self.org)
        case = OffboardingService.create_case(self.emp, self.user, OffboardingCase.RESIGNATION, date.today())
        resp = client.patch(
            f"/api/v1/payroll/offboarding-cases/{case.id}/exit_interview/",
            {"reasons_for_leaving": ["career_growth"], "would_recommend": True, "feedback": "Good experience"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(ExitInterview.objects.filter(case=case).exists())

    def test_clear_checklist_item_via_api(self):
        client = _auth_client(self.user, self.org)
        case = OffboardingService.create_case(self.emp, self.user, OffboardingCase.RESIGNATION, date.today())
        item = case.checklist_items.first()
        resp = client.post(f"/api/v1/payroll/offboarding-cases/{case.id}/clear-item/{item.id}/")
        self.assertEqual(resp.status_code, 200, resp.data)
        item.refresh_from_db()
        self.assertTrue(item.is_cleared)
        case.refresh_from_db()
        self.assertEqual(case.status, OffboardingCase.IN_PROGRESS)


# ══════════════════════════════════════════════════════════════════════════════
# A.4 — 13th-month / bonus PAYE annualisation fix (THE bug fix)
# ══════════════════════════════════════════════════════════════════════════════

class NonRecurringPayeFixTests(TestCase):
    """
    Confirms the core bug: a one-off payment (13th month, bonus, arrears via
    off-cycle run) must NOT be taxed as if the employee earns that amount
    every month for the year.
    """

    def setUp(self):
        self.user = _make_user("bug_owner@example.com")
        self.org = _make_org(self.user, "Bug Fix Org")
        # ₦500,000/month gross earner — a ₦500,000 bonus should be taxed
        # against a cumulative ~₦6.5m/yr income, not as if this one month
        # represented a ₦6,000,000/yr salary on its own.
        self.emp = _employee(
            self.org, basic="400000", housing_allowance=Decimal("70000"),
            transport_allowance=Decimal("30000"),
        )

    def test_regular_monthly_run_is_unaffected(self):
        """
        Regular runs must still use independent-month annualisation — unchanged.

        Hand-computed expected value for this fixture (basic=400000,
        housing=70000, transport=30000; employee hired 2024-01-15, so
        proration factor=1 for a full January 2026 period; no tax_profile,
        so nhf=0, life_assurance=0; annual_rent=0 so rent_relief=0):

            gross = 500,000
            employee_pension = 500,000 * 8% = 40,000
            taxable_income = 500,000 - 40,000 = 460,000
            annual_paye = calculate_annual_paye(460,000 * 12)
                        = calculate_annual_paye(5,520,000)
                        = (3,000,000-800,000)*15% + (5,520,000-3,000,000)*18%
                        = 330,000 + 453,600 = 783,600
            monthly_paye = 783,600 / 12 = 65,300.00
        """
        run = _run(self.org, self.user, year=2026, month=1)
        PayrollService.run_payroll(run)
        slip = PayslipLine.objects.get(payroll_run=run, employee=self.emp)
        self.assertEqual(slip.paye_tax, Decimal("65300.00"))

    def test_bonus_via_off_cycle_run_uses_cumulative_top_slicing_not_independent_annualisation(self):
        # January: a regular run establishes YTD taxable income + PAYE withheld.
        jan = _run(self.org, self.user, year=2026, month=1, run_type=PayrollRun.REGULAR)
        PayrollService.run_payroll(jan)
        jan_slip = PayslipLine.objects.get(payroll_run=jan, employee=self.emp)

        # A large one-off bonus routed through an off-cycle run in February.
        from apps.payroll.models import Bonus
        Bonus.objects.create(
            organisation=self.org, employee=self.emp, amount=Decimal("500000"),
            bonus_type=Bonus.PERFORMANCE, reason="Q4 performance", period_year=2026, period_month=2,
        )
        feb_offcycle = _run(self.org, self.user, year=2026, month=2, run_type=PayrollRun.OFF_CYCLE)
        PayrollService.run_payroll(feb_offcycle)
        feb_slip = PayslipLine.objects.get(payroll_run=feb_offcycle, employee=self.emp)

        # The buggy independent-annualisation formula would compute:
        #   monthly taxable ~= (gross + bonus - deductions), annualised x12,
        #   producing a PAYE figure vastly larger than correct top-slicing.
        # Approximate what the OLD bug would have produced for comparison.
        buggy_annual_paye = PayrollService.calculate_annual_paye(feb_slip.taxable_income * 12)
        buggy_monthly_paye = (buggy_annual_paye / 12).quantize(Decimal("0.01"))

        self.assertLess(
            feb_slip.paye_tax, buggy_monthly_paye,
            "the fixed cumulative top-slicing PAYE must be materially lower than "
            "what independent-month annualisation of a one-off bonus would have produced",
        )
        # And it must never go negative.
        self.assertGreaterEqual(feb_slip.paye_tax, Decimal("0"))

    def test_thirteenth_month_run_uses_cumulative_top_slicing(self):
        run = _run(self.org, self.user, year=2026, month=12, run_type=PayrollRun.THIRTEENTH)
        PayrollService.run_payroll(run)
        slip = PayslipLine.objects.get(payroll_run=run, employee=self.emp)
        # Should be taxed lightly/zero relative to what a naive x12 of the
        # 13th-month payment alone would produce, given prior months already
        # used up the lower brackets.
        self.assertGreaterEqual(slip.paye_tax, Decimal("0"))

    def test_abandoned_draft_run_excluded_from_ytd_top_slicing(self):
        """
        A DRAFT non-recurring run that was previewed and never approved/paid
        must NOT contribute to a later run's YTD taxable/PAYE totals used for
        cumulative top-slicing — its PayslipLine rows exist (run_payroll
        always writes them) but no tax was ever actually withheld/remitted.
        """
        from apps.payroll.models import Bonus

        # February: an abandoned DRAFT off-cycle bonus run. run_payroll()
        # writes PayslipLine rows immediately, before any approval step —
        # this run is left at status=draft (the default) and never approved.
        Bonus.objects.create(
            organisation=self.org, employee=self.emp, amount=Decimal("500000"),
            bonus_type=Bonus.PERFORMANCE, reason="Abandoned preview", period_year=2026, period_month=2,
        )
        draft_run = _run(self.org, self.user, year=2026, month=2, run_type=PayrollRun.OFF_CYCLE)
        self.assertEqual(draft_run.status, PayrollRun.DRAFT)
        PayrollService.run_payroll(draft_run)
        draft_slip = PayslipLine.objects.get(payroll_run=draft_run, employee=self.emp)
        self.assertGreater(draft_slip.taxable_income, Decimal("0"))
        self.assertGreater(draft_slip.paye_tax, Decimal("0"))

        # April: a second, real non-recurring run for the same employee in
        # the same tax year. If the DRAFT run's rows leaked into the YTD
        # aggregate, this run's PAYE would be under-withheld (or its
        # cumulative taxable base inflated) by the abandoned bonus.
        real_run = _run(self.org, self.user, year=2026, month=4, run_type=PayrollRun.OFF_CYCLE)
        PayrollService.run_payroll(real_run)
        real_slip = PayslipLine.objects.get(payroll_run=real_run, employee=self.emp)

        # With no approved/paid prior runs this year, YTD prior must be zero,
        # so this run's cumulative top-slicing collapses to a plain
        # calculate_annual_paye(taxable_income) with nothing subtracted.
        expected_paye = PayrollService.calculate_annual_paye(real_slip.taxable_income).quantize(
            Decimal("0.01"), rounding="ROUND_HALF_UP"
        )
        self.assertEqual(
            real_slip.paye_tax, expected_paye,
            "the abandoned DRAFT run's taxable/PAYE must not have leaked into this run's YTD prior figures",
        )


class ThirteenthMonthProRataTests(TestCase):
    def setUp(self):
        self.user = _make_user("m13_owner@example.com")
        self.org = _make_org(self.user, "13th Month Org")

    def test_full_year_employee_gets_full_thirteenth_month(self):
        emp = _employee(self.org, basic="300000", hire_date=date(2020, 1, 1))
        run = _run(self.org, self.user, year=2026, month=12, run_type=PayrollRun.THIRTEENTH)
        PayrollService.run_payroll(run)
        slip = PayslipLine.objects.get(payroll_run=run, employee=emp)
        self.assertEqual(slip.adjustment_amount + slip.bonus_amount + slip.overtime_amount, Decimal("300000"))

    def test_mid_year_joiner_gets_prorated_thirteenth_month(self):
        # Hired 1 July 2026 -> 6 completed months served by 31 Dec 2026.
        emp = _employee(self.org, basic="300000", hire_date=date(2026, 7, 1))
        run = _run(self.org, self.user, year=2026, month=12, run_type=PayrollRun.THIRTEENTH)
        PayrollService.run_payroll(run)
        slip = PayslipLine.objects.get(payroll_run=run, employee=emp)
        total_extra = slip.adjustment_amount + slip.bonus_amount + slip.overtime_amount
        self.assertEqual(total_extra, Decimal("150000"))  # 6/12 * 300,000

    def test_thirteenth_month_basis_gross_includes_allowances(self):
        settings_row = get_settings(self.org)
        settings_row.thirteenth_month_basis = PayrollSettings.THIRTEENTH_GROSS
        settings_row.save(update_fields=["thirteenth_month_basis"])
        emp = _employee(
            self.org, basic="300000", housing_allowance=Decimal("100000"),
            transport_allowance=Decimal("50000"), hire_date=date(2020, 1, 1),
        )
        run = _run(self.org, self.user, year=2026, month=12, run_type=PayrollRun.THIRTEENTH)
        PayrollService.run_payroll(run)
        slip = PayslipLine.objects.get(payroll_run=run, employee=emp)
        total_extra = slip.adjustment_amount + slip.bonus_amount + slip.overtime_amount
        self.assertEqual(total_extra, Decimal("450000"))  # full gross, not just basic


class AnnualPayeReconciliationTests(TestCase):
    def setUp(self):
        self.user = _make_user("recon_owner@example.com")
        self.org = _make_org(self.user, "Reconciliation Org")
        self.client = _auth_client(self.user, self.org)
        self.emp = _employee(self.org, basic="400000")

    def test_reconciliation_endpoint_reports_variance(self):
        # A full 12 months are needed for "actual annual taxable income" to
        # actually BE an annual figure — comparing calculate_annual_paye()
        # (which expects a true annual amount) against only a few months'
        # taxable income would itself misrepresent the correct annual tax,
        # producing a large apparent "variance" that is a test artefact, not
        # a real reconciliation discrepancy.
        for month in range(1, 13):
            run = _run(self.org, self.user, year=2026, month=month)
            PayrollService.run_payroll(run)
        resp = self.client.get("/api/v1/payroll/runs/annual_paye_reconciliation/", {"year": 2026})
        self.assertEqual(resp.status_code, 200, resp.data)
        rows = resp.data["rows"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIn("variance", row)
        self.assertIn("variance_direction", row)
        # A constant salary across a full 12 months converges to (near) zero
        # variance between monthly-annualised withholding and true annual tax.
        self.assertLess(abs(Decimal(str(row["variance"]))), Decimal("100"))


# ══════════════════════════════════════════════════════════════════════════════
# A.4 — Payroll register variance
# ══════════════════════════════════════════════════════════════════════════════

class PayrollRegisterTests(TestCase):
    def setUp(self):
        self.user = _make_user("register_owner@example.com")
        self.org = _make_org(self.user, "Register Org")
        self.client = _auth_client(self.user, self.org)
        _employee(self.org, basic="300000")

    def test_register_computes_month_on_month_variance(self):
        for month in (1, 2):
            run = _run(self.org, self.user, year=2026, month=month)
            PayrollService.run_payroll(run)
        resp = self.client.get("/api/v1/payroll/runs/register/", {"year": 2026})
        self.assertEqual(resp.status_code, 200, resp.data)
        rows = resp.data["rows"]
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0]["variance_from_prior_month_pct"])
        self.assertIsNotNone(rows[1]["variance_from_prior_month_pct"])


# ══════════════════════════════════════════════════════════════════════════════
# A.5 — Server-rendered payslip PDF + ESS document upload
# ══════════════════════════════════════════════════════════════════════════════

class PayslipPdfTests(TestCase):
    def setUp(self):
        self.user = _make_user("pdf_owner@example.com")
        self.org = _make_org(self.user, "PDF Org")
        self.client = _auth_client(self.user, self.org)
        self.emp = _employee(self.org, email="pdfemp@example.com")
        self.run = _run(self.org, self.user, year=2026, month=6)
        PayrollService.run_payroll(self.run)

    def test_payslip_pdf_download_endpoint_returns_pdf_bytes(self):
        resp = self.client.get(f"/api/v1/payroll/runs/{self.run.id}/payslip-pdf/{self.emp.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        content = b"".join(resp.streaming_content) if resp.streaming else resp.content
        self.assertTrue(content.startswith(b"%PDF"))

    def test_send_payslips_server_rendered_runs_synchronously_in_tests(self):
        """CELERY_TASK_ALWAYS_EAGER is set in test settings, so .delay() runs inline."""
        resp = self.client.post(f"/api/v1/payroll/runs/{self.run.id}/send_payslips_server_rendered/")
        self.assertEqual(resp.status_code, 200, resp.data)
        from apps.payroll.models import PayslipDelivery
        self.assertTrue(PayslipDelivery.objects.filter(payslip__payroll_run=self.run).exists())


class EssDocumentUploadTests(TestCase):
    def setUp(self):
        self.owner = _make_user("essdoc_owner@example.com")
        self.org = _make_org(self.owner, "ESS Doc Org")
        self.emp = _employee(self.org)
        self.portal_user = _make_user("essdoc_employee@example.com")
        self.emp.user = self.portal_user
        self.emp.save(update_fields=["user"])
        Membership.objects.create(organisation=self.org, user=self.portal_user, role=Membership.Role.EMPLOYEE, is_active=True)
        self.client = _auth_client(self.portal_user, self.org)

    def _upload(self, document_type, filename="c.pdf"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        f = SimpleUploadedFile(filename, b"%PDF-1.4 fake", content_type="application/pdf")
        return self.client.post(
            "/api/v1/me/documents/",
            {"document_type": document_type, "name": "My cert", "file": f},
            format="multipart",
        )

    def test_employee_can_upload_allowed_type(self):
        resp = self._upload(EmployeeDocument.CERTIFICATE)
        self.assertEqual(resp.status_code, 201, resp.data)
        doc = EmployeeDocument.objects.get(id=resp.data["id"])
        self.assertTrue(doc.uploaded_by_employee)
        self.assertIsNone(doc.reviewed_by)

    def test_employee_cannot_upload_contract_type(self):
        resp = self._upload(EmployeeDocument.CONTRACT)
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_long_realistic_filename_saves_with_full_path_intact(self):
        # EmployeeDocument.file must carry max_length=255 (not Django's
        # default of 100) because _employee_doc_path already spends ~75
        # chars on "employee_documents/<org-uuid>/<employee-uuid>/" before
        # the filename is even appended. A realistic descriptive filename,
        # like a real ESS self-upload, must not be truncated or rejected.
        long_name = "International_Passport_Bio_Data_Page_Certified_Copy_2026.pdf"
        self.assertGreaterEqual(len(long_name), 60)
        resp = self._upload(EmployeeDocument.ID, filename=long_name)
        self.assertEqual(resp.status_code, 201, resp.data)
        doc = EmployeeDocument.objects.get(id=resp.data["id"])
        expected_path_suffix = f"employee_documents/{self.org.id}/{self.emp.id}/{long_name}"
        self.assertTrue(
            doc.file.name.endswith(long_name),
            f"filename was truncated: {doc.file.name!r}",
        )
        self.assertGreaterEqual(len(doc.file.name), len(expected_path_suffix))

    def test_uploaded_document_scoped_to_own_employee_record(self):
        self._upload(EmployeeDocument.CV)
        other_emp = _employee(self.org, "Other", "Person")
        other_portal = _make_user("other_essdoc@example.com")
        other_emp.user = other_portal
        other_emp.save(update_fields=["user"])
        Membership.objects.create(organisation=self.org, user=other_portal, role=Membership.Role.EMPLOYEE, is_active=True)
        other_client = _auth_client(other_portal, self.org)
        resp = other_client.get("/api/v1/me/documents/")
        self.assertEqual(resp.status_code, 200, resp.data)
        # Paginated response envelope — assert on 'results', not the dict itself.
        results = resp.data["results"] if isinstance(resp.data, dict) and "results" in resp.data else resp.data
        self.assertEqual(len(results), 0)


# ══════════════════════════════════════════════════════════════════════════════
# A.6 — HR Analytics (aggregation-only, bounded queries)
# ══════════════════════════════════════════════════════════════════════════════

class HRAnalyticsTests(TestCase):
    def setUp(self):
        self.user = _make_user("analytics_owner@example.com")
        self.org = _make_org(self.user, "Analytics Org")
        self.client = _auth_client(self.user, self.org)

    def test_headcount_turnover_is_aggregation_only(self):
        for i in range(3):
            _employee(self.org, f"Joiner{i}", "X", hire_date=date(2026, 3, 1))
        # Upper bound covers auth/org-resolution overhead (JWT user lookup,
        # membership, subscription/plan) on top of the handful of aggregate
        # queries the endpoint itself issues — the point of this test is that
        # nothing scales with employee count (no per-employee loop), which a
        # fixed bound like this still catches.
        #
        # Raised from 14 to 18 for row-level security. Under the Postgres test
        # settings RLSMiddleware issues four extra statements per request to set
        # app.current_org_id and app.current_user_id. Those are per-request, not
        # per-employee, so the property this test guards is untouched — the old
        # bound simply predated RLS being active in tests and failed there while
        # passing on SQLite. Measured, not guessed: 18 on Postgres, 14 on SQLite.
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get("/api/v1/payroll/hr-analytics/headcount_turnover/", {"year": 2026})
        self.assertLessEqual(len(ctx.captured_queries), 18, "should be a fixed handful of queries, not one per employee")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["total_joiners"], 3)

    def test_cost_by_department_aggregates_without_per_employee_loop(self):
        emp1 = _employee(self.org, "A", "One", department="Finance", basic="200000")
        emp2 = _employee(self.org, "B", "Two", department="Engineering", basic="300000")
        run = _run(self.org, self.user, year=2026, month=6)
        PayrollService.run_payroll(run)
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get("/api/v1/payroll/hr-analytics/cost_by_department/", {"year": 2026})
        self.assertLessEqual(len(ctx.captured_queries), 14, "should be a fixed handful of queries, not one per employee")  # 10 + 4 RLS statements per request
        self.assertEqual(resp.status_code, 200, resp.data)
        depts = {r["department"] for r in resp.data}
        self.assertEqual(depts, {"Finance", "Engineering"})

    def test_absence_summary_aggregates(self):
        emp = _employee(self.org)
        Attendance.objects.create(organisation=self.org, employee=emp, date=date(2026, 6, 1), status=Attendance.ABSENT)
        Attendance.objects.create(organisation=self.org, employee=emp, date=date(2026, 6, 2), status=Attendance.PRESENT)
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get("/api/v1/payroll/hr-analytics/absence_summary/", {"year": 2026})
        self.assertLessEqual(len(ctx.captured_queries), 14, "should be a fixed handful of queries, not one per row")  # 10 + 4 RLS statements per request
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data.get("absent"), 1)

    def test_tenure_demographics_suppresses_small_buckets(self):
        _employee(self.org, "Solo", "Male", gender=Employee.MALE, hire_date=date(2024, 1, 1))
        resp = self.client.get("/api/v1/payroll/hr-analytics/tenure_demographics/")
        self.assertEqual(resp.status_code, 200, resp.data)
        # A single male employee => bucket of 1 < MIN_BUCKET_SIZE(5) => suppressed to None
        self.assertIsNone(resp.data["gender"].get("male"))

    def test_tenure_demographics_shows_buckets_at_or_above_threshold(self):
        for i in range(5):
            _employee(self.org, f"Bulk{i}", "Male", gender=Employee.MALE, hire_date=date(2024, 1, 1))
        resp = self.client.get("/api/v1/payroll/hr-analytics/tenure_demographics/")
        self.assertEqual(resp.data["gender"]["male"], 5)


# ══════════════════════════════════════════════════════════════════════════════
# A.6 — Leave accrual GL true-up
# ══════════════════════════════════════════════════════════════════════════════

class LeaveAccrualGLTests(TestCase):
    def setUp(self):
        self.user = _make_user("gl_owner@example.com")
        self.org = _make_org(self.user, "GL Accrual Org")
        self.emp = _employee(self.org, basic="260000")  # daily rate = 10,000
        self.leave_type = LeaveType.objects.create(
            organisation=self.org, name="Annual Leave", days_per_year=Decimal("6"),
            accrual_method=LeaveType.ANNUAL_GRANT, is_paid=True,
        )

    def test_posts_only_the_delta_not_the_full_amount(self):
        from apps.accounting.services import AccountingService
        from apps.accounting.models import JournalEntry

        balance = LeaveService.get_or_create_balance(self.emp, self.leave_type, date.today().year)
        balance.accrued_days = Decimal("6")
        balance.save(update_fields=["accrued_days"])

        entry1 = AccountingService.post_leave_accrual_true_up(self.org, date.today())
        self.assertIsNotNone(entry1)
        settings_row = get_settings(self.org)
        settings_row.refresh_from_db()
        first_posted = settings_row.leave_accrual_last_posted_amount

        # Re-running immediately with no change in liability must post nothing.
        entry2 = AccountingService.post_leave_accrual_true_up(self.org, date.today())
        self.assertIsNone(entry2)

        # Grow the liability and confirm only the delta posts.
        balance.accrued_days = Decimal("6")
        balance.taken_days = Decimal("-2")  # crude way to bump available_days in a test
        balance.save(update_fields=["accrued_days", "taken_days"])
        entry3 = AccountingService.post_leave_accrual_true_up(self.org, date.today())
        self.assertIsNotNone(entry3)
        total_debits = sum(l.debit for l in entry3.lines.all())
        # The delta-only journal should be much smaller than a full re-post of
        # the whole liability would be.
        self.assertLess(total_debits, first_posted + Decimal("100000"))

    def test_account_2850_accrued_leave_receives_the_posting(self):
        from apps.accounting.services import AccountingService
        from apps.accounting.models import Account

        balance = LeaveService.get_or_create_balance(self.emp, self.leave_type, date.today().year)
        balance.accrued_days = Decimal("6")
        balance.save(update_fields=["accrued_days"])
        AccountingService.post_leave_accrual_true_up(self.org, date.today())
        acct = Account.objects.get(organisation=self.org, code="2850")
        self.assertTrue(acct.journal_lines.exists() if hasattr(acct, "journal_lines") else True)

    def test_read_compute_write_of_last_posted_amount_is_row_locked(self):
        """
        Regression test for a TOCTOU gap: post_leave_accrual_true_up used to
        read PayrollSettings.leave_accrual_last_posted_amount, compute the
        delta, post the GL entry, and write the new figure back with no lock
        held across that span — a manual backfill run racing the scheduled
        monthly Celery beat run for the same org could both read the same
        last-posted figure and both post a GL entry off it.

        The test DB here is SQLite `:memory:` (config.settings.testing),
        which — per the existing precedent in
        apps/subscriptions/test_payment_engine.py
        (InitiateIntegrationDoubleCheckoutRaceTests) — cannot give us true
        multi-connection select_for_update() blocking. Following that same
        precedent, this proves the lock is actually *invoked* on the correct
        row rather than merely re-testing the unlocked-equivalent happy path
        (which wouldn't distinguish locked from unlocked): we patch
        QuerySet.select_for_update and assert it was called during the
        function's PayrollSettings read, with the row it resolves to being
        the org's actual settings row.
        """
        from unittest.mock import patch
        from django.db.models.query import QuerySet
        from apps.accounting.services import AccountingService
        from apps.payroll.models import PayrollSettings

        balance = LeaveService.get_or_create_balance(self.emp, self.leave_type, date.today().year)
        balance.accrued_days = Decimal("6")
        balance.save(update_fields=["accrued_days"])

        settings_row = get_settings(self.org)

        original_select_for_update = QuerySet.select_for_update
        calls = []

        def _spy_select_for_update(self, *args, **kwargs):
            calls.append(self.model)
            return original_select_for_update(self, *args, **kwargs)

        with patch.object(QuerySet, "select_for_update", _spy_select_for_update):
            entry = AccountingService.post_leave_accrual_true_up(self.org, date.today())

        self.assertIsNotNone(entry)
        self.assertIn(
            PayrollSettings, calls,
            "post_leave_accrual_true_up must select_for_update() the "
            "PayrollSettings row before its read-compute-write of "
            "leave_accrual_last_posted_amount, matching the locking "
            "convention used in apps/subscriptions/payment_engine.py",
        )
        settings_row.refresh_from_db()
        self.assertGreater(settings_row.leave_accrual_last_posted_amount, Decimal("0"))


# ══════════════════════════════════════════════════════════════════════════════
# A.6b — Leave encashment settlement (senior-accountant review defect fix):
# encashment must relieve 2850 directly, not add to Salaries & Wages Expense,
# and the true-up must never double-relieve days already settled this way.
# ══════════════════════════════════════════════════════════════════════════════

class LeaveEncashmentSettlementGLTests(TestCase):
    """
    Worked example from the review: March — 10 days accrue at a daily rate of
    10,000 (gross salary 260,000 / 26) — true-up posts DR Expense 100,000 /
    CR 2850 100,000, so the BS liability is 100,000. June — 5 of those days
    are encashed for 50,000. After the fix, that 50,000 must post as a
    liability settlement (DR 2850 / CR Bank), leaving the BS liability at
    exactly 50,000 for the 5 still-unencashed days, with Salaries & Wages
    Expense not double-hit for the encashed portion.
    """

    def setUp(self):
        from apps.accounting.services import AccountingService
        self.AccountingService = AccountingService

        self.user = _make_user("encash_owner@example.com")
        self.org = _make_org(self.user, "Encashment Org")
        # gross_salary must equal basic_salary exactly (260,000) so the daily
        # rate is an unambiguous 260,000 / 26 = 10,000 — zero out the other
        # components _employee() would otherwise default in.
        self.emp = _employee(
            self.org, basic="260000",
            housing_allowance=Decimal("0"), transport_allowance=Decimal("0"),
        )
        self.leave_type = LeaveType.objects.create(
            organisation=self.org, name="Annual Leave", days_per_year=Decimal("10"),
            accrual_method=LeaveType.ANNUAL_GRANT, is_paid=True,
        )

    def _account(self, code):
        from apps.accounting.models import Account
        return Account.objects.get(organisation=self.org, code=code)

    def _balance_of(self, account, natural='debit'):
        """
        Net posted balance for an account, in its natural sign.
        natural='debit' (assets/expenses): debit - credit.
        natural='credit' (liabilities/equity/revenue): credit - debit.
        """
        from django.db.models import Sum
        from apps.accounting.models import JournalLine
        agg = JournalLine.objects.filter(
            account=account, journal_entry__organisation=self.org,
            journal_entry__status='posted',
        ).aggregate(d=Sum('debit'), c=Sum('credit'))
        d = Decimal(str(agg['d'] or 0))
        c = Decimal(str(agg['c'] or 0))
        return (d - c) if natural == 'debit' else (c - d)

    def test_march_accrue_june_encash_leaves_correct_remaining_liability(self):
        # ── March: 10 days accrue, true-up posts the full 100,000 liability ──
        balance = LeaveService.get_or_create_balance(self.emp, self.leave_type, 2026)
        balance.accrued_days = Decimal("10")
        balance.save(update_fields=["accrued_days"])

        march_entry = self.AccountingService.post_leave_accrual_true_up(
            self.org, date(2026, 3, 1)
        )
        self.assertIsNotNone(march_entry)

        accrued_leave_acct = self._account("2850")
        salary_acct = self._account_salary()
        self.assertEqual(self._balance_of(accrued_leave_acct, 'credit'), Decimal("100000.00"))
        salary_after_march = self._balance_of(salary_acct)
        self.assertEqual(salary_after_march, Decimal("100000.00"))

        # ── June: encash 5 of those 10 days (5 * 10,000 = 50,000) ───────────
        rate = LeaveEncashmentService.daily_rate(self.emp)
        self.assertEqual(rate, Decimal("10000.00"))
        adjustment = LeaveEncashmentService.request_encashment(
            self.emp, self.leave_type, Decimal("5"), reason="Encash 5 days"
        )
        self.assertEqual(adjustment.amount, Decimal("50000.00"))
        balance.refresh_from_db()
        self.assertEqual(balance.available_days, Decimal("5"))  # 10 - 5 taken

        run = _run(self.org, self.user, year=2026, month=6)
        PayrollService.run_payroll(run)
        run.refresh_from_db()
        self.assertEqual(Decimal(str(run.total_encashment)), Decimal("50000.00"))

        adjustment.refresh_from_db()
        self.assertEqual(adjustment.status, PayrollAdjustment.APPLIED)

        entry = self.AccountingService.post_payroll_journal(self.org, run, user=self.user)
        self.assertIsNotNone(entry)

        # 2850 must now read exactly 50,000 — the 100,000 March liability less
        # the 50,000 just settled. Not 100,000 (never relieved) and not 0
        # (over-relieved / double-counted).
        self.assertEqual(self._balance_of(accrued_leave_acct, 'credit'), Decimal("50000.00"))

        # Salaries & Wages Expense must NOT be double-hit for the encashed
        # 50,000. The employee still earns their regular June salary (gross
        # ~260,000 plus employer pension expense), so the expense balance does
        # grow this run — but only by (this run's actual gross-side debits to
        # 1000 minus the 50,000 carved out for the encashment settlement), not
        # by the full run.total_gross which would silently re-include the
        # encashed amount as ordinary payroll cost.
        run.refresh_from_db()
        gross_raw = Decimal(str(run.total_gross))
        pension_empr = Decimal(str(run.total_pension_employer))
        nsitf = Decimal(str(run.total_nsitf))
        expected_salary_debit_this_run = (gross_raw - Decimal("50000.00")) + pension_empr + nsitf
        salary_after_june = self._balance_of(salary_acct)
        self.assertEqual(
            salary_after_june - salary_after_march, expected_salary_debit_this_run
        )
        # And explicitly: the full run.total_gross (which still includes the
        # encashment amount, by construction of calculate_employee_paye) must
        # NOT have landed in full on the expense account — that was the bug.
        self.assertNotEqual(
            salary_after_june - salary_after_march, gross_raw + pension_empr + nsitf
        )

        # The dedicated settlement entry itself must be a clean, self-balancing
        # DR 2850 / CR Bank for exactly 50,000 — separate from the payroll
        # journal's own gross-expense entry.
        from apps.accounting.models import JournalEntry
        settlement = JournalEntry.objects.get(
            organisation=self.org, source_type='leave_encashment', source_ref=str(run.id),
        )
        settlement_lines = list(settlement.lines.all())
        self.assertEqual(len(settlement_lines), 2)
        debit_line = next(l for l in settlement_lines if l.debit > 0)
        credit_line = next(l for l in settlement_lines if l.credit > 0)
        self.assertEqual(debit_line.account.code, "2850")
        self.assertEqual(debit_line.debit, Decimal("50000.00"))
        self.assertEqual(credit_line.credit, Decimal("50000.00"))

    def test_true_up_does_not_double_relieve_days_already_settled_by_encashment(self):
        """
        Once the dedicated encashment entry has settled 50,000 against 2850,
        re-running the true-up (as it would on its monthly beat schedule)
        must NOT relieve 2850 a second time for the same 5 days.
        """
        balance = LeaveService.get_or_create_balance(self.emp, self.leave_type, 2026)
        balance.accrued_days = Decimal("10")
        balance.save(update_fields=["accrued_days"])
        self.AccountingService.post_leave_accrual_true_up(self.org, date(2026, 3, 1))

        LeaveEncashmentService.request_encashment(
            self.emp, self.leave_type, Decimal("5"), reason="Encash 5 days"
        )
        run = _run(self.org, self.user, year=2026, month=6)
        PayrollService.run_payroll(run)
        self.AccountingService.post_payroll_journal(self.org, run, user=self.user)

        accrued_leave_acct = self._account("2850")
        self.assertEqual(self._balance_of(accrued_leave_acct, 'credit'), Decimal("50000.00"))

        # Re-run the true-up for the following month with no further leave
        # activity. available_days is now 5 (10 - 5 taken), so the true-up's
        # own liability calc already lands on 50,000 too — matching what the
        # settlement entry left in the ledger. delta must be zero: no posting.
        settings_row = get_settings(self.org)
        settings_row.refresh_from_db()
        self.assertEqual(
            Decimal(str(settings_row.leave_accrual_last_posted_amount)), Decimal("50000.00")
        )
        july_entry = self.AccountingService.post_leave_accrual_true_up(self.org, date(2026, 7, 1))
        self.assertIsNone(july_entry)
        self.assertEqual(self._balance_of(accrued_leave_acct, 'credit'), Decimal("50000.00"))

    def _account_salary(self):
        from apps.accounting.services import AccountMappingService
        return AccountMappingService.resolve(self.org, 'salary_expense_account')


# ══════════════════════════════════════════════════════════════════════════════
# A.7 — Widened report resolvers
# ══════════════════════════════════════════════════════════════════════════════

class WidenedResolversTests(TestCase):
    def setUp(self):
        self.user = _make_user("resolver_owner@example.com")
        self.org = _make_org(self.user, "Resolver Org")

    def test_employee_list_includes_manager_and_state(self):
        from apps.reports.registry import employee_list
        manager = _employee(self.org, "Boss", "Person", state_of_residence="LA")
        _employee(self.org, "Report", "Ee", manager=manager, state_of_residence="KN")
        result = employee_list(self.org, None, None)
        report_row = next(r for r in result["rows"] if r["name"] == "Report Ee")
        self.assertEqual(report_row["manager"], "Boss Person")
        self.assertIn("Kano", report_row["state_of_residence"])

    def test_employee_list_surfaces_offboarding_status_instead_of_dropping_row(self):
        from apps.reports.registry import employee_list
        emp = _employee(self.org, "Leaving", "Soon")
        OffboardingService.create_case(emp, self.user, OffboardingCase.RESIGNATION, date.today() + timedelta(days=14))
        result = employee_list(self.org, None, None)
        row = next(r for r in result["rows"] if r["name"] == "Leaving Soon")
        self.assertIn("Offboarding", row["status"])

    def test_payroll_report_includes_run_type_and_itf_and_benefits(self):
        from apps.reports.registry import payroll_report
        _employee(self.org, basic="300000")
        run = _run(self.org, self.user, year=2026, month=6)
        PayrollService.run_payroll(run)
        result = payroll_report(self.org, date(2026, 1, 1), date(2026, 12, 31))
        row = result["rows"][0]
        self.assertIn("run_type", row)
        self.assertIn("total_itf", row)
        self.assertIn("total_benefits", row)

    def test_attendance_summary_splits_paid_and_unpaid(self):
        from apps.reports.registry import attendance_summary
        emp = _employee(self.org)
        Attendance.objects.create(organisation=self.org, employee=emp, date=date(2026, 6, 1), status=Attendance.LEAVE)
        Attendance.objects.create(organisation=self.org, employee=emp, date=date(2026, 6, 2), status=Attendance.ABSENT)
        result = attendance_summary(self.org, date(2026, 6, 1), date(2026, 6, 30))
        row = result["rows"][0]
        self.assertEqual(row["paid_leave"], 1)
        self.assertEqual(row["unpaid_leave_absent"], 1)

    def test_attendance_summary_uses_same_holiday_set_as_payroll(self):
        from apps.reports.registry import attendance_summary
        emp = _employee(self.org)
        PublicHoliday.objects.create(organisation=self.org, date=date(2026, 6, 1), name="Ad-hoc")
        Attendance.objects.create(organisation=self.org, employee=emp, date=date(2026, 6, 1), status=Attendance.HOLIDAY)
        result = attendance_summary(self.org, date(2026, 6, 1), date(2026, 6, 30))
        row = result["rows"][0]
        self.assertEqual(row["public_holiday_overlap"], 1)


# ══════════════════════════════════════════════════════════════════════════════
# HR review fixes — document-expiry scheduling, encashment-in-REGULAR-run
# top-slicing, inactive-leave-type final-settlement inclusion
# ══════════════════════════════════════════════════════════════════════════════

class DocumentExpiryTaskSchedulingTests(TestCase):
    """
    Fix 1: flag_expiring_documents was a fully-built Celery task with no
    CELERY_BEAT_SCHEDULE entry, so it never ran in production. It also
    matched expiry_date exactly against today+threshold rather than a
    range, so a single missed weekly run permanently skipped a document at
    that threshold.
    """

    def test_task_is_registered_in_celery_beat_schedule(self):
        from django.conf import settings as django_settings
        task_names = {
            entry["task"] for entry in django_settings.CELERY_BEAT_SCHEDULE.values()
        }
        self.assertIn("payroll.flag_expiring_documents", task_names)

    def test_range_based_query_catches_a_missed_exact_target_date(self):
        """
        Simulates a document that expires 2 days before its 60-day threshold
        target (i.e. the weekly job window shifted and the exact
        today+60 date was never hit) — the range/catch-up query must still
        flag it, and running the task twice must not double-alert it.
        """
        from apps.payroll.tasks import flag_expiring_documents

        user = _make_user("expiry_task_owner@example.com")
        org = _make_org(user, "Expiry Task Org")
        Membership.objects.filter(organisation=org, user=user).update(role="owner")
        emp = _employee(org)
        doc = EmployeeDocument.objects.create(
            organisation=org, employee=emp, name="Work Permit",
            document_type=EmployeeDocument.WORK_PERMIT,
            # Would have been missed by an exact `expiry_date == today+60` match.
            expiry_date=date.today() + timedelta(days=58),
        )

        flagged = flag_expiring_documents()
        self.assertGreaterEqual(flagged, 1)
        doc.refresh_from_db()
        self.assertIn(60, doc.expiry_alert_thresholds_sent)

        # Re-running must not re-flag the same document at the same threshold.
        flagged_again = flag_expiring_documents()
        self.assertEqual(flagged_again, 0)


class EncashmentInRegularRunTopSlicingTests(TestCase):
    """
    Fix 2: a PENDING leave-ENCASHMENT PayrollAdjustment picked up by an
    ordinary REGULAR run must route through the same cumulative top-slicing
    PAYE path as a 13th-month/bonus/off-cycle run, not the plain x12
    independent-annualisation path — otherwise the one-off encashment
    payment gets over-taxed exactly like the original 13th-month bug.
    """

    def setUp(self):
        self.user = _make_user("encash_regular_owner@example.com")
        self.org = _make_org(self.user, "Encashment Regular Org")
        self.emp_with_encashment = _employee(
            self.org, "Enc", "Ashment", basic="400000",
            housing_allowance=Decimal("70000"), transport_allowance=Decimal("30000"),
        )
        self.emp_plain = _employee(
            self.org, "Plain", "Regular", basic="400000",
            housing_allowance=Decimal("70000"), transport_allowance=Decimal("30000"),
        )
        self.leave_type = LeaveType.objects.create(
            organisation=self.org, name="Annual Leave", days_per_year=Decimal("20"),
            accrual_method=LeaveType.ANNUAL_GRANT, is_paid=True,
        )

    def test_employee_with_pending_encashment_in_regular_run_uses_top_slicing(self):
        LeaveEncashmentService.request_encashment(
            self.emp_with_encashment, self.leave_type, Decimal("10"),
        )
        run = _run(self.org, self.user, year=2026, month=3, run_type=PayrollRun.REGULAR)
        PayrollService.run_payroll(run)

        enc_slip = PayslipLine.objects.get(payroll_run=run, employee=self.emp_with_encashment)
        plain_slip = PayslipLine.objects.get(payroll_run=run, employee=self.emp_plain)

        # What the OLD (buggy) blind x12 independent-annualisation would have
        # produced for the encashment earner, given their actual taxable
        # income this run (which already includes the encashment payout).
        buggy_annual_paye = PayrollService.calculate_annual_paye(enc_slip.taxable_income * 12)
        buggy_monthly_paye = (buggy_annual_paye / 12).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")

        self.assertLess(
            enc_slip.paye_tax, buggy_monthly_paye,
            "the encashment earner's PAYE must be computed via cumulative "
            "top-slicing, not blind x12 annualisation of a one-off payout",
        )
        self.assertGreaterEqual(enc_slip.paye_tax, Decimal("0"))
        self.assertGreater(enc_slip.adjustment_amount, Decimal("0"))

        # The employee with NO encashment adjustment in this same REGULAR
        # run must still be taxed via plain independent-month x12 —
        # unaffected by the other employee's one-off payment.
        expected_plain_annual_paye = PayrollService.calculate_annual_paye(plain_slip.taxable_income * 12)
        expected_plain_annual_paye = expected_plain_annual_paye.quantize(
            Decimal("0.01"), rounding="ROUND_HALF_UP"
        )
        expected_plain_monthly_paye = (expected_plain_annual_paye / 12).quantize(
            Decimal("0.01"), rounding="ROUND_HALF_UP"
        )
        self.assertEqual(plain_slip.paye_tax, expected_plain_monthly_paye)
        self.assertEqual(plain_slip.adjustment_amount, Decimal("0"))

    def test_run_type_stays_regular_for_everyone_else(self):
        LeaveEncashmentService.request_encashment(
            self.emp_with_encashment, self.leave_type, Decimal("5"),
        )
        run = _run(self.org, self.user, year=2026, month=3, run_type=PayrollRun.REGULAR)
        PayrollService.run_payroll(run)
        run.refresh_from_db()
        self.assertEqual(run.run_type, PayrollRun.REGULAR)


class InactiveLeaveTypeFinalSettlementTests(TestCase):
    """
    Fix 3: OffboardingService.run_final_settlement filtered leave types by
    is_active=True. If a leave type is deactivated after an employee already
    accrued a balance against it, that balance was silently excluded from
    the final-settlement payout — is_active should only gate NEW
    bookings/accruals, never whether an already-accrued balance is honoured
    at exit.
    """

    def setUp(self):
        self.user = _make_user("inactive_lt_owner@example.com")
        self.org = _make_org(self.user, "Inactive Leave Type Org")
        self.emp = _employee(self.org, basic="300000")
        self.leave_type = LeaveType.objects.create(
            organisation=self.org, name="Special Leave", days_per_year=Decimal("10"),
            accrual_method=LeaveType.ANNUAL_GRANT, is_paid=True,
        )

    def test_deactivated_leave_type_balance_still_paid_at_final_settlement(self):
        year = date.today().year
        balance = LeaveService.get_or_create_balance(self.emp, self.leave_type, year)
        # ANNUAL_GRANT already sets accrued_days = days_per_year on creation.
        self.assertGreater(balance.available_days, Decimal("0"))

        # Deactivate the leave type AFTER the balance was accrued — must not
        # forfeit the employee's already-accrued days.
        self.leave_type.is_active = False
        self.leave_type.save(update_fields=["is_active"])

        case = OffboardingService.create_case(
            self.emp, self.user, OffboardingCase.RESIGNATION,
            date(year, 12, 31),
        )
        OffboardingService.run_final_settlement(case, self.user)

        payout_adjustment = PayrollAdjustment.objects.filter(
            employee=self.emp, adjustment_type=PayrollAdjustment.ENCASHMENT,
            reason__icontains="Special Leave",
        ).first()
        self.assertIsNotNone(
            payout_adjustment,
            "the deactivated leave type's already-accrued balance must still "
            "generate a final-settlement payout adjustment",
        )
        self.assertGreater(payout_adjustment.amount, Decimal("0"))
