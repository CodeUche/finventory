"""
Tests for the HR module: proration, run types, compensation history, state-routed
PAYE, ITF, leave, benefits, salary advances, GL balance and ESS tenant isolation.

Kept separate from tests.py so the original payroll regression suite stays
readable as the "did we break what already worked" gate.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.payroll.models import (
    AdvancePolicy, AdvanceRequest, Attendance, BenefitPlan, Bonus, CompensationRecord,
    Employee, EmployeeBenefit, EmployeeLoan, EmployeePenalty, LeaveBalance,
    LeaveRequest, LeaveType, PayrollAdjustment, PayrollRun, PayslipLine,
    StatutoryRemittance, TaxAuthority,
)
from apps.payroll.services import (
    CompensationService, EWAService, LeaveService, PayrollService,
    ProrationService, RemittanceService, TaxAuthorityService, get_settings,
)
from apps.subscriptions.models import Plan
from apps.subscriptions.services import SubscriptionService
from apps.tenancy.models import Membership
from apps.tenancy.services import OrganisationService


# ── helpers ───────────────────────────────────────────────────────────────────

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


class ProrationTests(TestCase):
    """Working-day proration for joiners, leavers and full-period employees."""

    def setUp(self):
        self.user = _make_user("pro_owner@example.com")
        self.org = _make_org(self.user, "Proration Org")

    def test_full_month_employee_is_not_prorated(self):
        emp = _employee(self.org, hire_date=date(2020, 1, 1))
        factor, worked, total = ProrationService.factor_for(
            emp, date(2026, 6, 1), date(2026, 6, 30)
        )
        self.assertEqual(factor, Decimal("1.0000"))
        self.assertEqual(worked, total)

    def test_mid_month_joiner_is_prorated(self):
        # June 2026: 1 Jun is a Monday; 22 working days in the month.
        emp = _employee(self.org, hire_date=date(2026, 6, 16))
        factor, worked, total = ProrationService.factor_for(
            emp, date(2026, 6, 1), date(2026, 6, 30)
        )
        self.assertLess(factor, Decimal("1"))
        self.assertGreater(factor, Decimal("0"))
        self.assertEqual(worked, ProrationService.working_days(date(2026, 6, 16), date(2026, 6, 30)))
        self.assertEqual(total, Decimal(str(ProrationService.working_days(date(2026, 6, 1), date(2026, 6, 30)))))

    def test_leaver_is_prorated_to_termination_date(self):
        emp = _employee(self.org, hire_date=date(2020, 1, 1), termination_date=date(2026, 6, 10))
        factor, worked, _ = ProrationService.factor_for(
            emp, date(2026, 6, 1), date(2026, 6, 30)
        )
        self.assertLess(factor, Decimal("1"))
        self.assertEqual(worked, ProrationService.working_days(date(2026, 6, 1), date(2026, 6, 10)))

    def test_employee_hired_after_period_gets_zero(self):
        emp = _employee(self.org, hire_date=date(2026, 8, 1))
        factor, worked, _ = ProrationService.factor_for(
            emp, date(2026, 6, 1), date(2026, 6, 30)
        )
        self.assertEqual(factor, Decimal("0"))
        self.assertEqual(worked, Decimal("0"))

    def test_run_prorates_pay_and_stores_factor(self):
        full = _employee(self.org, "Full", "Timer", hire_date=date(2020, 1, 1))
        joiner = _employee(self.org, "New", "Joiner", hire_date=date(2026, 6, 16))
        run = _run(self.org, self.user)
        PayrollService.run_payroll(run)

        full_slip = PayslipLine.objects.get(payroll_run=run, employee=full)
        joiner_slip = PayslipLine.objects.get(payroll_run=run, employee=joiner)

        self.assertEqual(full_slip.proration_factor, Decimal("1.0000"))
        self.assertLess(joiner_slip.proration_factor, Decimal("1"))
        self.assertLess(joiner_slip.gross_salary, full_slip.gross_salary)
        self.assertGreater(joiner_slip.days_worked, 0)

    def test_leaver_receives_a_final_settlement_instead_of_vanishing(self):
        """The old engine filtered out anyone with a termination_date entirely."""
        leaver = _employee(
            self.org, "Bola", "Eze",
            hire_date=date(2020, 1, 1), termination_date=date(2026, 6, 12),
        )
        run = _run(self.org, self.user)
        PayrollService.run_payroll(run)

        slip = PayslipLine.objects.filter(payroll_run=run, employee=leaver).first()
        self.assertIsNotNone(slip, "terminated employee must still be paid for days worked")
        self.assertGreater(slip.net_salary, 0)

    def test_employee_terminated_before_period_is_excluded(self):
        _employee(self.org, "Gone", "Already",
                  hire_date=date(2020, 1, 1), termination_date=date(2026, 5, 1))
        run = _run(self.org, self.user)
        PayrollService.run_payroll(run)
        self.assertEqual(run.payslips.count(), 0)


class RunTypeTests(TestCase):
    def setUp(self):
        self.user = _make_user("runtype_owner@example.com")
        self.org = _make_org(self.user, "RunType Org")
        self.client = _auth_client(self.user, self.org)
        _employee(self.org)

    def test_off_cycle_run_coexists_with_the_regular_run(self):
        r1 = self.client.post("/api/v1/payroll/runs/", {
            "period_year": 2026, "period_month": 7,
        })
        self.assertEqual(r1.status_code, 201, msg=str(r1.data))
        r2 = self.client.post("/api/v1/payroll/runs/", {
            "period_year": 2026, "period_month": 7, "run_type": "off_cycle",
        })
        self.assertEqual(r2.status_code, 201, msg=str(r2.data))
        self.assertEqual(
            PayrollRun.objects.filter(
                organisation=self.org, period_year=2026, period_month=7
            ).count(), 2,
        )

    def test_second_regular_run_for_a_month_is_still_rejected(self):
        """The constraint we replaced was protecting exactly this."""
        self.client.post("/api/v1/payroll/runs/", {"period_year": 2026, "period_month": 8})
        second = self.client.post("/api/v1/payroll/runs/", {
            "period_year": 2026, "period_month": 8,
        })
        self.assertEqual(second.status_code, 400, msg=str(second.data))

    def test_multiple_off_cycle_runs_increment_sequence(self):
        self.client.post("/api/v1/payroll/runs/", {
            "period_year": 2026, "period_month": 9, "run_type": "off_cycle"})
        self.client.post("/api/v1/payroll/runs/", {
            "period_year": 2026, "period_month": 9, "run_type": "off_cycle"})
        seqs = sorted(
            PayrollRun.objects.filter(
                organisation=self.org, period_year=2026, period_month=9,
                run_type=PayrollRun.OFF_CYCLE,
            ).values_list('sequence', flat=True)
        )
        self.assertEqual(seqs, [1, 2])

    def test_run_number_encodes_the_run_type(self):
        res = self.client.post("/api/v1/payroll/runs/", {
            "period_year": 2026, "period_month": 10, "run_type": "thirteenth_month",
        })
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertIn("M13", res.data["run_number"])

    def test_invalid_run_type_is_rejected(self):
        res = self.client.post("/api/v1/payroll/runs/", {
            "period_year": 2026, "period_month": 11, "run_type": "nonsense",
        })
        self.assertEqual(res.status_code, 400)

    def test_recalculate_refuses_after_transfers_started(self):
        res = self.client.post("/api/v1/payroll/runs/", {"period_year": 2026, "period_month": 12})
        run_id = res.data["id"]
        PayslipLine.objects.filter(payroll_run_id=run_id).update(
            transfer_status=PayslipLine.TRANSFER_SUCCESS
        )
        again = self.client.post(f"/api/v1/payroll/runs/{run_id}/recalculate/")
        self.assertEqual(again.status_code, 400)


class CompensationHistoryTests(TestCase):
    def setUp(self):
        self.user = _make_user("comp_owner@example.com")
        self.org = _make_org(self.user, "Comp Org")
        self.emp = _employee(self.org, hire_date=date(2024, 1, 1), basic="300000")

    def test_record_change_mirrors_onto_the_employee(self):
        CompensationService.record_change(
            self.emp, date(2026, 4, 1), reason=CompensationRecord.PROMOTION,
            basic_salary=Decimal("500000"),
        )
        self.emp.refresh_from_db()
        self.assertEqual(Decimal(str(self.emp.basic_salary)), Decimal("500000"))

    def test_components_resolve_as_of_a_date(self):
        CompensationService.record_change(
            self.emp, date(2024, 1, 1), reason=CompensationRecord.HIRE,
            basic_salary=Decimal("300000"),
        )
        CompensationService.record_change(
            self.emp, date(2026, 4, 1), reason=CompensationRecord.PROMOTION,
            basic_salary=Decimal("500000"),
        )
        records = {}
        for rec in CompensationRecord.objects.filter(employee=self.emp).order_by('-effective_date'):
            records.setdefault(rec.employee_id, []).append(rec)

        before = CompensationService.components_as_of(self.emp, date(2026, 3, 31), records)
        after = CompensationService.components_as_of(self.emp, date(2026, 5, 31), records)
        self.assertEqual(before['basic_salary'], Decimal("300000"))
        self.assertEqual(after['basic_salary'], Decimal("500000"))

    def test_falls_back_to_employee_columns_when_no_record_exists(self):
        comp = CompensationService.components_as_of(self.emp, date(2026, 6, 30))
        self.assertEqual(comp['basic_salary'], Decimal("300000"))

    def test_run_uses_the_rate_in_force_for_the_period(self):
        CompensationService.record_change(
            self.emp, date(2024, 1, 1), reason=CompensationRecord.HIRE,
            basic_salary=Decimal("300000"),
        )
        CompensationService.record_change(
            self.emp, date(2026, 7, 1), reason=CompensationRecord.PROMOTION,
            basic_salary=Decimal("900000"),
        )
        june = _run(self.org, self.user, month=6)
        PayrollService.run_payroll(june)
        slip = PayslipLine.objects.get(payroll_run=june, employee=self.emp)
        # June predates the July raise
        self.assertEqual(Decimal(str(slip.basic_salary)), Decimal("300000.00"))


class AdjustmentTests(TestCase):
    def setUp(self):
        self.user = _make_user("adj_owner@example.com")
        self.org = _make_org(self.user, "Adjustment Org")
        self.emp = _employee(self.org)

    def test_arrears_are_paid_and_marked_applied(self):
        adj = PayrollAdjustment.objects.create(
            organisation=self.org, employee=self.emp,
            adjustment_type=PayrollAdjustment.ARREARS,
            amount=Decimal("75000"), reason="Backdated April raise",
        )
        run = _run(self.org, self.user)
        PayrollService.run_payroll(run)

        slip = PayslipLine.objects.get(payroll_run=run, employee=self.emp)
        adj.refresh_from_db()
        self.assertEqual(Decimal(str(slip.adjustment_amount)), Decimal("75000"))
        self.assertEqual(adj.status, PayrollAdjustment.APPLIED)
        self.assertEqual(adj.applied_in_run_id, run.id)

    def test_arrears_increase_gross_and_therefore_paye(self):
        run_without = _run(self.org, self.user, month=5)
        PayrollService.run_payroll(run_without)
        base_paye = PayslipLine.objects.get(payroll_run=run_without).paye_tax

        PayrollAdjustment.objects.create(
            organisation=self.org, employee=self.emp,
            amount=Decimal("200000"), reason="Arrears",
        )
        run_with = _run(self.org, self.user, month=6)
        PayrollService.run_payroll(run_with)
        with_paye = PayslipLine.objects.get(payroll_run=run_with).paye_tax
        self.assertGreater(with_paye, base_paye)

    def test_applied_adjustment_is_not_paid_twice(self):
        PayrollAdjustment.objects.create(
            organisation=self.org, employee=self.emp,
            amount=Decimal("50000"), reason="Arrears",
        )
        first = _run(self.org, self.user, month=5)
        PayrollService.run_payroll(first)
        second = _run(self.org, self.user, month=6)
        PayrollService.run_payroll(second)
        slip2 = PayslipLine.objects.get(payroll_run=second, employee=self.emp)
        self.assertEqual(Decimal(str(slip2.adjustment_amount)), Decimal("0"))


class StateRoutedPayeTests(TestCase):
    def setUp(self):
        self.user = _make_user("paye_owner@example.com")
        self.org = _make_org(self.user, "PAYE Org")
        TaxAuthorityService.seed(self.org)

    def test_seed_creates_all_states_and_is_idempotent(self):
        TaxAuthorityService.seed(self.org)
        self.assertEqual(TaxAuthority.objects.filter(organisation=self.org).count(), 37)

    def test_paye_splits_by_state_of_residence(self):
        _employee(self.org, "Lagos", "Staff", state_of_residence="LA")
        _employee(self.org, "Kano", "Staff", state_of_residence="KN")
        _employee(self.org, "Lagos2", "Staff", state_of_residence="LA")

        run = _run(self.org, self.user)
        PayrollService.run_payroll(run)

        paye_rows = StatutoryRemittance.objects.filter(
            organisation=self.org, payroll_run=run,
            remittance_type=StatutoryRemittance.PAYE,
        )
        self.assertEqual(paye_rows.count(), 2, "one obligation per state, not one per run")
        names = {r.tax_authority.name for r in paye_rows if r.tax_authority}
        self.assertTrue(any("Lagos" in n for n in names))
        self.assertTrue(any("Kano" in n for n in names))

    def test_paye_total_across_authorities_equals_the_run_total(self):
        _employee(self.org, "A", "One", state_of_residence="LA")
        _employee(self.org, "B", "Two", state_of_residence="FC")
        run = _run(self.org, self.user)
        PayrollService.run_payroll(run)

        split_total = sum(
            Decimal(str(r.amount_due))
            for r in StatutoryRemittance.objects.filter(
                payroll_run=run, remittance_type=StatutoryRemittance.PAYE)
        )
        self.assertEqual(split_total, Decimal(str(run.total_paye)))

    def test_employee_without_a_state_lands_in_an_unassigned_row(self):
        _employee(self.org, "No", "State", state_of_residence="")
        run = _run(self.org, self.user)
        PayrollService.run_payroll(run)
        row = StatutoryRemittance.objects.filter(
            payroll_run=run, remittance_type=StatutoryRemittance.PAYE,
            tax_authority__isnull=True,
        ).first()
        self.assertIsNotNone(row)
        self.assertIn("Unassigned", row.recipient_name)

    def test_pension_splits_by_pfa(self):
        _employee(self.org, "A", "One", pfa_name="ARM Pension")
        _employee(self.org, "B", "Two", pfa_name="Stanbic IBTC")
        _employee(self.org, "C", "Three", pfa_name="ARM Pension")
        run = _run(self.org, self.user)
        PayrollService.run_payroll(run)

        pension_rows = StatutoryRemittance.objects.filter(
            payroll_run=run, remittance_type=StatutoryRemittance.PENSION,
        )
        self.assertEqual(pension_rows.count(), 2)

    def test_paye_due_date_is_the_tenth_of_the_following_month(self):
        _employee(self.org, state_of_residence="LA")
        run = _run(self.org, self.user, year=2026, month=6)
        PayrollService.run_payroll(run)
        row = StatutoryRemittance.objects.filter(
            payroll_run=run, remittance_type=StatutoryRemittance.PAYE).first()
        self.assertEqual(row.due_date, date(2026, 7, 10))

    def test_december_paye_rolls_into_january(self):
        _employee(self.org, state_of_residence="LA")
        run = _run(self.org, self.user, year=2026, month=12)
        PayrollService.run_payroll(run)
        row = StatutoryRemittance.objects.filter(
            payroll_run=run, remittance_type=StatutoryRemittance.PAYE).first()
        self.assertEqual(row.due_date, date(2027, 1, 10))


class ITFTests(TestCase):
    def setUp(self):
        self.user = _make_user("itf_owner@example.com")
        self.org = _make_org(self.user, "ITF Org")

    def test_itf_is_off_below_five_employees(self):
        for i in range(3):
            _employee(self.org, f"E{i}", "Staff")
        run = _run(self.org, self.user)
        PayrollService.run_payroll(run)
        self.assertEqual(Decimal(str(run.total_itf)), Decimal("0"))

    def test_itf_auto_asserts_at_five_employees(self):
        for i in range(5):
            _employee(self.org, f"E{i}", "Staff")
        run = _run(self.org, self.user)
        PayrollService.run_payroll(run)
        self.assertGreater(Decimal(str(run.total_itf)), Decimal("0"))
        self.assertTrue(get_settings(self.org).itf_applicable)

    def test_itf_is_one_percent_of_gross(self):
        for i in range(5):
            _employee(self.org, f"E{i}", "Staff")
        run = _run(self.org, self.user)
        PayrollService.run_payroll(run)
        expected = (Decimal(str(run.total_gross)) * Decimal("0.01")).quantize(Decimal("0.01"))
        self.assertEqual(Decimal(str(run.total_itf)), expected)

    def test_itf_accrues_annually_without_double_counting(self):
        for i in range(5):
            _employee(self.org, f"E{i}", "Staff")
        r1 = _run(self.org, self.user, month=1)
        PayrollService.run_payroll(r1)
        r2 = _run(self.org, self.user, month=2)
        PayrollService.run_payroll(r2)

        rows = StatutoryRemittance.objects.filter(
            organisation=self.org, remittance_type=StatutoryRemittance.ITF)
        self.assertEqual(rows.count(), 1, "one accumulating ITF row per year")
        expected = Decimal(str(r1.total_itf)) + Decimal(str(r2.total_itf))
        self.assertEqual(Decimal(str(rows.first().amount_due)), expected)

    def test_itf_is_due_the_following_april(self):
        for i in range(5):
            _employee(self.org, f"E{i}", "Staff")
        run = _run(self.org, self.user, year=2026, month=6)
        PayrollService.run_payroll(run)
        row = StatutoryRemittance.objects.get(
            organisation=self.org, remittance_type=StatutoryRemittance.ITF)
        self.assertEqual(row.due_date, date(2027, 4, 1))


class LeaveTests(TestCase):
    def setUp(self):
        self.user = _make_user("leave_owner@example.com")
        self.org = _make_org(self.user, "Leave Org")
        self.client = _auth_client(self.user, self.org)
        self.emp = _employee(self.org, hire_date=date(2020, 1, 1))
        LeaveService.seed_defaults(self.org)
        self.annual = LeaveType.objects.get(organisation=self.org, name="Annual Leave")
        self.unpaid = LeaveType.objects.get(organisation=self.org, name="Unpaid Leave")

    def test_defaults_are_seeded_once(self):
        LeaveService.seed_defaults(self.org)
        self.assertEqual(LeaveType.objects.filter(organisation=self.org).count(), 6)

    def test_working_days_excludes_weekends(self):
        # Mon 1 Jun 2026 -> Sun 7 Jun 2026 = 5 working days
        self.assertEqual(
            LeaveRequest.working_days_between(date(2026, 6, 1), date(2026, 6, 7)),
            Decimal("5"),
        )

    def test_approving_paid_leave_writes_leave_attendance(self):
        req = LeaveRequest.objects.create(
            organisation=self.org, employee=self.emp, leave_type=self.annual,
            start_date=date(2026, 6, 8), end_date=date(2026, 6, 10),
        )
        LeaveService.approve(req, user=self.user)
        rows = Attendance.objects.filter(
            employee=self.emp, date__gte=date(2026, 6, 8), date__lte=date(2026, 6, 10))
        self.assertEqual(rows.count(), 3)
        self.assertTrue(all(r.status == Attendance.LEAVE for r in rows))

    def test_approving_unpaid_leave_writes_absent_attendance(self):
        req = LeaveRequest.objects.create(
            organisation=self.org, employee=self.emp, leave_type=self.unpaid,
            start_date=date(2026, 6, 8), end_date=date(2026, 6, 9),
        )
        LeaveService.approve(req, user=self.user)
        rows = Attendance.objects.filter(
            employee=self.emp, date__gte=date(2026, 6, 8), date__lte=date(2026, 6, 9))
        self.assertTrue(all(r.status == Attendance.ABSENT for r in rows))

    def test_paid_leave_costs_the_employee_nothing_in_payroll(self):
        req = LeaveRequest.objects.create(
            organisation=self.org, employee=self.emp, leave_type=self.annual,
            start_date=date(2026, 6, 8), end_date=date(2026, 6, 12),
        )
        LeaveService.approve(req, user=self.user)
        run = _run(self.org, self.user, month=6)
        PayrollService.run_payroll(run)
        slip = PayslipLine.objects.get(payroll_run=run, employee=self.emp)
        self.assertEqual(Decimal(str(slip.attendance_deduction)), Decimal("0"))

    def test_unpaid_leave_flows_into_the_attendance_deduction(self):
        req = LeaveRequest.objects.create(
            organisation=self.org, employee=self.emp, leave_type=self.unpaid,
            start_date=date(2026, 6, 8), end_date=date(2026, 6, 12),
        )
        LeaveService.approve(req, user=self.user)
        run = _run(self.org, self.user, month=6)
        PayrollService.run_payroll(run)
        slip = PayslipLine.objects.get(payroll_run=run, employee=self.emp)
        self.assertGreater(Decimal(str(slip.attendance_deduction)), Decimal("0"))

    def test_approval_moves_days_from_pending_to_taken(self):
        balance = LeaveService.get_or_create_balance(self.emp, self.annual, 2026)
        balance.accrued_days = Decimal("6")
        balance.pending_days = Decimal("3")
        balance.save()

        req = LeaveRequest.objects.create(
            organisation=self.org, employee=self.emp, leave_type=self.annual,
            start_date=date(2026, 6, 8), end_date=date(2026, 6, 10), days=Decimal("3"),
        )
        LeaveService.approve(req, user=self.user)
        balance.refresh_from_db()
        self.assertEqual(balance.pending_days, Decimal("0.00"))
        self.assertEqual(balance.taken_days, Decimal("3.00"))

    def test_rejection_releases_the_pending_hold(self):
        balance = LeaveService.get_or_create_balance(self.emp, self.annual, 2026)
        balance.pending_days = Decimal("2")
        balance.save()
        req = LeaveRequest.objects.create(
            organisation=self.org, employee=self.emp, leave_type=self.annual,
            start_date=date(2026, 6, 8), end_date=date(2026, 6, 9), days=Decimal("2"),
        )
        LeaveService.reject(req, user=self.user)
        balance.refresh_from_db()
        self.assertEqual(balance.pending_days, Decimal("0.00"))

    def test_cancelling_approved_leave_clears_the_attendance_rows(self):
        req = LeaveRequest.objects.create(
            organisation=self.org, employee=self.emp, leave_type=self.annual,
            start_date=date(2026, 6, 8), end_date=date(2026, 6, 10),
        )
        LeaveService.approve(req, user=self.user)
        LeaveService.cancel(req, user=self.user)
        self.assertEqual(
            Attendance.objects.filter(
                employee=self.emp, date__gte=date(2026, 6, 8), date__lte=date(2026, 6, 10)
            ).count(), 0,
        )

    def test_monthly_accrual_adds_one_twelfth(self):
        LeaveService.accrue_month(self.org, 2026, 1)
        balance = LeaveBalance.objects.get(
            employee=self.emp, leave_type=self.annual, year=2026)
        self.assertEqual(balance.accrued_days, Decimal("0.50"))  # 6 days / 12

    def test_accrual_never_exceeds_the_annual_entitlement(self):
        for month in range(1, 13):
            LeaveService.accrue_month(self.org, 2026, month)
        for _ in range(6):
            LeaveService.accrue_month(self.org, 2026, 12)
        balance = LeaveBalance.objects.get(
            employee=self.emp, leave_type=self.annual, year=2026)
        self.assertLessEqual(balance.accrued_days, self.annual.days_per_year)

    def test_gender_restricted_leave_is_rejected_for_the_wrong_gender(self):
        maternity = LeaveType.objects.get(organisation=self.org, name="Maternity Leave")
        self.emp.gender = "male"
        self.emp.save()
        res = self.client.post("/api/v1/payroll/leave-requests/", {
            "employee": str(self.emp.id), "leave_type": str(maternity.id),
            "start_date": "2026-09-01", "end_date": "2026-09-30",
        })
        self.assertEqual(res.status_code, 400, msg=str(res.data))

    def test_overlapping_leave_is_rejected(self):
        LeaveRequest.objects.create(
            organisation=self.org, employee=self.emp, leave_type=self.annual,
            start_date=date(2026, 6, 8), end_date=date(2026, 6, 12),
            status=LeaveRequest.APPROVED,
        )
        res = self.client.post("/api/v1/payroll/leave-requests/", {
            "employee": str(self.emp.id), "leave_type": str(self.annual.id),
            "start_date": "2026-06-10", "end_date": "2026-06-15",
        })
        self.assertEqual(res.status_code, 400, msg=str(res.data))

    def test_end_before_start_is_rejected(self):
        res = self.client.post("/api/v1/payroll/leave-requests/", {
            "employee": str(self.emp.id), "leave_type": str(self.annual.id),
            "start_date": "2026-06-15", "end_date": "2026-06-10",
        })
        self.assertEqual(res.status_code, 400)


class BenefitTests(TestCase):
    def setUp(self):
        self.user = _make_user("ben_owner@example.com")
        self.org = _make_org(self.user, "Benefit Org")
        self.emp = _employee(self.org)
        self.plan = BenefitPlan.objects.create(
            organisation=self.org, name="Hygeia Family", benefit_type=BenefitPlan.HMO,
            provider_name="Hygeia HMO", basis=BenefitPlan.FIXED,
            employee_contribution=Decimal("12000"), employer_contribution=Decimal("18000"),
        )
        EmployeeBenefit.objects.create(
            organisation=self.org, employee=self.emp, plan=self.plan,
            start_date=date(2024, 1, 1),
        )

    def test_fixed_benefit_is_deducted_from_net(self):
        run = _run(self.org, self.user)
        PayrollService.run_payroll(run)
        slip = PayslipLine.objects.get(payroll_run=run, employee=self.emp)
        self.assertEqual(Decimal(str(slip.benefit_deductions)), Decimal("12000"))
        self.assertEqual(Decimal(str(slip.benefit_employer_cost)), Decimal("18000"))

    def test_percentage_benefit_scales_with_gross(self):
        self.plan.basis = BenefitPlan.PERCENT_GROSS
        self.plan.employee_contribution = Decimal("2")
        self.plan.employer_contribution = Decimal("3")
        self.plan.save()
        run = _run(self.org, self.user)
        PayrollService.run_payroll(run)
        slip = PayslipLine.objects.get(payroll_run=run, employee=self.emp)
        expected = (Decimal(str(slip.gross_salary)) * Decimal("2") / 100).quantize(Decimal("0.01"))
        self.assertEqual(Decimal(str(slip.benefit_deductions)), expected)

    def test_benefit_creates_a_remittance_per_provider(self):
        run = _run(self.org, self.user)
        PayrollService.run_payroll(run)
        row = StatutoryRemittance.objects.filter(
            payroll_run=run, remittance_type=StatutoryRemittance.BENEFIT).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.recipient_name, "Hygeia HMO")
        self.assertEqual(Decimal(str(row.amount_due)), Decimal("30000"))

    def test_ended_enrolment_is_not_charged(self):
        EmployeeBenefit.objects.filter(employee=self.emp).update(end_date=date(2026, 1, 1))
        run = _run(self.org, self.user, month=6)
        PayrollService.run_payroll(run)
        slip = PayslipLine.objects.get(payroll_run=run, employee=self.emp)
        self.assertEqual(Decimal(str(slip.benefit_deductions)), Decimal("0"))


class AdvanceTests(TestCase):
    def setUp(self):
        self.user = _make_user("adv_owner@example.com")
        self.org = _make_org(self.user, "Advance Org")
        self.client = _auth_client(self.user, self.org)
        self.emp = _employee(self.org, hire_date=date(2020, 1, 1))
        self.policy = EWAService.get_policy(self.org)
        self.policy.is_enabled = True
        self.policy.fee_percent = Decimal("2")
        self.policy.save()

    def test_disabled_policy_blocks_eligibility(self):
        self.policy.is_enabled = False
        self.policy.save()
        info = EWAService.eligibility(self.emp)
        self.assertFalse(info['eligible'])

    def test_new_hire_below_service_threshold_is_ineligible(self):
        recent = _employee(self.org, "Very", "New", hire_date=date.today())
        info = EWAService.eligibility(recent)
        self.assertFalse(info['eligible'])
        self.assertTrue(any("months of service" in r for r in info['reasons']))

    def test_available_is_capped_at_the_configured_percentage(self):
        info = EWAService.eligibility(self.emp)
        self.assertLessEqual(
            Decimal(str(info['available'])),
            (Decimal(str(info['accrued_net'])) * Decimal("50") / 100).quantize(Decimal("0.01")),
        )

    def test_requesting_more_than_available_is_refused(self):
        info = EWAService.eligibility(self.emp)
        too_much = Decimal(str(info['available'])) + Decimal("100000")
        with self.assertRaises(ValueError):
            EWAService.request(self.emp, too_much)

    def test_fee_is_applied_to_the_recoverable_total(self):
        info = EWAService.eligibility(self.emp)
        amount = (Decimal(str(info['available'])) / 2).quantize(Decimal("0.01"))
        if amount <= 0:
            self.skipTest("no accrued entitlement in this period")
        advance = EWAService.request(self.emp, amount)
        self.assertEqual(
            Decimal(str(advance.total_recoverable)),
            amount + (amount * Decimal("2") / 100).quantize(Decimal("0.01")),
        )

    def test_disbursed_advance_is_recovered_in_the_next_run(self):
        advance = AdvanceRequest.objects.create(
            organisation=self.org, employee=self.emp,
            amount=Decimal("50000"), fee=Decimal("1000"),
            total_recoverable=Decimal("51000"),
            period_year=2026, period_month=6,
            status=AdvanceRequest.DISBURSED,
        )
        run = _run(self.org, self.user, month=6)
        PayrollService.run_payroll(run)
        slip = PayslipLine.objects.get(payroll_run=run, employee=self.emp)
        advance.refresh_from_db()
        self.assertEqual(Decimal(str(slip.advance_deductions)), Decimal("51000"))
        self.assertEqual(advance.status, AdvanceRequest.RECOVERED)
        self.assertEqual(advance.recovered_in_run_id, run.id)

    def test_recovered_advance_is_not_taken_twice(self):
        AdvanceRequest.objects.create(
            organisation=self.org, employee=self.emp,
            amount=Decimal("20000"), total_recoverable=Decimal("20000"),
            period_year=2026, period_month=5, status=AdvanceRequest.DISBURSED,
        )
        first = _run(self.org, self.user, month=5)
        PayrollService.run_payroll(first)
        second = _run(self.org, self.user, month=6)
        PayrollService.run_payroll(second)
        slip = PayslipLine.objects.get(payroll_run=second, employee=self.emp)
        self.assertEqual(Decimal(str(slip.advance_deductions)), Decimal("0"))

    def test_cash_buffer_gate_blocks_approval(self):
        self.policy.min_cash_buffer = Decimal("999999999")
        self.policy.save()
        can_fund, reason = EWAService.can_employer_fund(self.org, Decimal("10000"))
        self.assertFalse(can_fund)
        self.assertIn("cash buffer", reason)


class PayrollGLBalanceTests(TestCase):
    """
    The payroll journal must balance with every kind of deduction present.

    post_journal_entry raises on imbalance, so an unbalanced journal shows up as
    gl_post_status='failed' rather than as a visible error — which is how the
    missing penalty/loan/attendance credit lines went unnoticed.
    """

    def setUp(self):
        self.user = _make_user("gl_owner@example.com")
        self.org = _make_org(self.user, "GL Org")
        self.emp = _employee(self.org, hire_date=date(2020, 1, 1))

    def _post(self, run):
        from apps.accounting.services import AccountingService
        return AccountingService.post_payroll_journal(self.org, run, user=self.user)

    def test_simple_run_balances(self):
        run = _run(self.org, self.user)
        PayrollService.run_payroll(run)
        entry = self._post(run)
        self.assertIsNotNone(entry)

    def test_run_with_penalty_loan_and_absence_balances(self):
        EmployeePenalty.objects.create(
            organisation=self.org, employee=self.emp, reason="Late",
            amount=Decimal("5000"), penalty_date=date(2026, 6, 3),
        )
        EmployeeLoan.objects.create(
            organisation=self.org, employee=self.emp,
            principal_amount=Decimal("120000"), duration_months=12,
            start_date=date(2026, 1, 1),
        )
        Attendance.objects.create(
            organisation=self.org, employee=self.emp,
            date=date(2026, 6, 3), status=Attendance.ABSENT,
        )
        run = _run(self.org, self.user, month=6)
        PayrollService.run_payroll(run)

        slip = PayslipLine.objects.get(payroll_run=run)
        self.assertGreater(Decimal(str(slip.penalty_deductions)), 0)
        self.assertGreater(Decimal(str(slip.loan_deductions)), 0)
        self.assertGreater(Decimal(str(slip.attendance_deduction)), 0)

        entry = self._post(run)
        self.assertIsNotNone(entry, "journal must post with all deduction types present")

    def test_run_with_benefits_and_itf_balances(self):
        for i in range(5):
            _employee(self.org, f"X{i}", "Staff")
        plan = BenefitPlan.objects.create(
            organisation=self.org, name="HMO", provider_name="Hygeia",
            employee_contribution=Decimal("8000"), employer_contribution=Decimal("12000"),
        )
        EmployeeBenefit.objects.create(
            organisation=self.org, employee=self.emp, plan=plan, start_date=date(2020, 1, 1),
        )
        run = _run(self.org, self.user, month=6)
        PayrollService.run_payroll(run)
        self.assertGreater(Decimal(str(run.total_itf)), 0)
        entry = self._post(run)
        self.assertIsNotNone(entry)

    def test_journal_debits_equal_credits(self):
        from apps.accounting.models import JournalLine

        EmployeePenalty.objects.create(
            organisation=self.org, employee=self.emp, reason="Late",
            amount=Decimal("5000"), penalty_date=date(2026, 6, 3),
        )
        run = _run(self.org, self.user, month=6)
        PayrollService.run_payroll(run)
        entry = self._post(run)
        lines = JournalLine.objects.filter(journal_entry=entry)
        debits = sum(Decimal(str(line.debit)) for line in lines)
        credits = sum(Decimal(str(line.credit)) for line in lines)
        self.assertEqual(debits, credits)


class RemittanceClearingTests(TestCase):
    def setUp(self):
        self.user = _make_user("rem_owner@example.com")
        self.org = _make_org(self.user, "Remittance Org")
        self.client = _auth_client(self.user, self.org)
        _employee(self.org, state_of_residence="LA")
        self.run = _run(self.org, self.user)
        PayrollService.run_payroll(self.run)

    def test_mark_remitted_sets_status_and_reference(self):
        row = StatutoryRemittance.objects.filter(
            payroll_run=self.run, remittance_type=StatutoryRemittance.PAYE).first()
        res = self.client.post(
            f"/api/v1/payroll/remittances/{row.id}/mark_remitted/",
            {"reference": "LIRS-2026-06-001"},
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        row.refresh_from_db()
        self.assertEqual(row.status, StatutoryRemittance.REMITTED)
        self.assertEqual(row.reference, "LIRS-2026-06-001")

    def test_partial_payment_sets_partial_status(self):
        row = StatutoryRemittance.objects.filter(
            payroll_run=self.run, remittance_type=StatutoryRemittance.PAYE).first()
        half = (Decimal(str(row.amount_due)) / 2).quantize(Decimal("0.01"))
        RemittanceService.mark_remitted(row, amount=half)
        row.refresh_from_db()
        self.assertEqual(row.status, StatutoryRemittance.PARTIAL)

    def test_remitting_twice_is_refused(self):
        row = StatutoryRemittance.objects.filter(
            payroll_run=self.run, remittance_type=StatutoryRemittance.PAYE).first()
        self.client.post(f"/api/v1/payroll/remittances/{row.id}/mark_remitted/", {})
        again = self.client.post(f"/api/v1/payroll/remittances/{row.id}/mark_remitted/", {})
        self.assertEqual(again.status_code, 400)

    def test_rerunning_payroll_preserves_a_filed_remittance(self):
        row = StatutoryRemittance.objects.filter(
            payroll_run=self.run, remittance_type=StatutoryRemittance.PAYE).first()
        RemittanceService.mark_remitted(row, reference="FILED-001")
        RemittanceService.generate_for_run(self.run)
        row.refresh_from_db()
        self.assertEqual(row.reference, "FILED-001")

    def test_summary_endpoint_reports_outstanding(self):
        res = self.client.get("/api/v1/payroll/remittances/summary/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("outstanding", res.data)
        self.assertGreater(Decimal(res.data["outstanding"]), 0)

    def test_pension_schedule_groups_by_pfa(self):
        res = self.client.get("/api/v1/payroll/remittances/schedule/?type=pension")
        self.assertEqual(res.status_code, 200)
        self.assertIn("groups", res.data)


class ESSIsolationTests(TestCase):
    """
    The highest-risk surface in the module: the first non-operator user class to
    touch tenant data. Every endpoint must be scoped to the caller's own
    employee record and to nothing else.
    """

    def setUp(self):
        self.owner = _make_user("ess_owner@example.com")
        self.org = _make_org(self.owner, "ESS Org")
        self.owner_client = _auth_client(self.owner, self.org)

        self.alice = _employee(self.org, "Alice", "A", email="alice@ess.test",
                               hire_date=date(2020, 1, 1))
        self.bob = _employee(self.org, "Bob", "B", email="bob@ess.test",
                             hire_date=date(2020, 1, 1))

        # Second organisation, entirely separate
        self.other_owner = _make_user("ess_other@example.com")
        self.other_org = _make_org(self.other_owner, "Other ESS Org")
        self.carol = _employee(self.other_org, "Carol", "C", email="carol@ess.test",
                               hire_date=date(2020, 1, 1))

        run = _run(self.org, self.owner)
        PayrollService.run_payroll(run)
        other_run = _run(self.other_org, self.other_owner)
        PayrollService.run_payroll(other_run)

        self.alice_user = self._invite(self.alice)
        self.alice_client = self._ess_client(self.alice_user)

    def _invite(self, employee):
        import secrets
        user = User.objects.create_user(
            email=employee.email, password=secrets.token_urlsafe(9),
            first_name=employee.first_name, last_name=employee.last_name,
            is_verified=True,
        )
        user.save()
        Membership.objects.create(
            organisation=employee.organisation, user=user,
            role=Membership.Role.EMPLOYEE, is_active=True,
        )
        employee.user = user
        employee.save(update_fields=['user'])
        return user

    def _ess_client(self, user):
        client = APIClient()
        refresh = RefreshToken.for_user(user)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
        return client

    def test_employee_sees_only_their_own_payslips(self):
        res = self.alice_client.get("/api/v1/me/payslips/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        ids = {str(row["employee"]) for row in res.data}
        self.assertEqual(ids, {str(self.alice.id)})

    def test_employee_cannot_see_a_colleagues_payslip(self):
        bob_slip = PayslipLine.objects.filter(employee=self.bob).first()
        res = self.alice_client.get(f"/api/v1/me/payslips/{bob_slip.id}/")
        self.assertIn(res.status_code, [403, 404])

    def test_employee_cannot_see_another_orgs_payslip(self):
        carol_slip = PayslipLine.objects.filter(employee=self.carol).first()
        res = self.alice_client.get(f"/api/v1/me/payslips/{carol_slip.id}/")
        self.assertIn(res.status_code, [403, 404])

    def test_org_header_cannot_widen_access(self):
        """A forged X-Organisation-ID must not reach another org's data."""
        client = self._ess_client(self.alice_user)
        client.credentials(
            HTTP_AUTHORIZATION=client._credentials['HTTP_AUTHORIZATION'],
            HTTP_X_ORGANISATION_ID=str(self.other_org.id),
        )
        res = client.get("/api/v1/me/payslips/")
        self.assertEqual(res.status_code, 200)
        ids = {str(row["employee"]) for row in res.data}
        self.assertEqual(ids, {str(self.alice.id)})

    def test_user_without_an_employee_record_is_refused(self):
        stranger = _make_user("stranger@ess.test")
        client = self._ess_client(stranger)
        res = client.get("/api/v1/me/summary/")
        self.assertEqual(res.status_code, 403)

    def test_employee_cannot_reach_the_operator_endpoints(self):
        res = self.alice_client.get("/api/v1/payroll/employees/")
        self.assertIn(res.status_code, [403, 404])

    def test_employee_cannot_run_payroll(self):
        res = self.alice_client.post("/api/v1/payroll/runs/", {
            "period_year": 2026, "period_month": 7})
        self.assertIn(res.status_code, [403, 404])

    def test_profile_patch_ignores_pay_fields(self):
        res = self.alice_client.patch("/api/v1/me/profile/", {
            "phone": "08030000000",
            "basic_salary": "99999999",
            "job_title": "CEO",
        })
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.phone, "08030000000")
        self.assertNotEqual(str(self.alice.basic_salary), "99999999")
        self.assertEqual(self.alice.job_title, "Analyst")

    def test_leave_request_cannot_be_booked_for_a_colleague(self):
        LeaveService.seed_defaults(self.org)
        annual = LeaveType.objects.get(organisation=self.org, name="Annual Leave")
        balance = LeaveService.get_or_create_balance(self.alice, annual, 2026)
        balance.accrued_days = Decimal("10")
        balance.save()

        res = self.alice_client.post("/api/v1/me/leave-requests/", {
            "employee": str(self.bob.id),          # forged
            "leave_type": str(annual.id),
            "start_date": "2026-06-08", "end_date": "2026-06-09",
        })
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        created = LeaveRequest.objects.get(id=res.data["id"])
        self.assertEqual(created.employee_id, self.alice.id,
                         "the employee must come from the session, not the payload")

    def test_leave_beyond_balance_is_refused(self):
        LeaveService.seed_defaults(self.org)
        annual = LeaveType.objects.get(organisation=self.org, name="Annual Leave")
        balance = LeaveService.get_or_create_balance(self.alice, annual, 2026)
        balance.accrued_days = Decimal("1")
        balance.save()
        res = self.alice_client.post("/api/v1/me/leave-requests/", {
            "leave_type": str(annual.id),
            "start_date": "2026-06-08", "end_date": "2026-06-19",
        })
        self.assertEqual(res.status_code, 400)

    def test_summary_returns_only_own_data(self):
        res = self.alice_client.get("/api/v1/me/summary/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["employee"]["id"], str(self.alice.id))
        self.assertEqual(res.data["organisation"]["name"], "ESS Org")

    def test_documents_are_scoped(self):
        res = self.alice_client.get("/api/v1/me/documents/")
        self.assertEqual(res.status_code, 200)

    def test_advances_are_scoped(self):
        AdvanceRequest.objects.create(
            organisation=self.org, employee=self.bob, amount=Decimal("10000"),
            total_recoverable=Decimal("10000"), period_year=2026, period_month=6,
        )
        res = self.alice_client.get("/api/v1/me/advances/")
        self.assertEqual(res.status_code, 200)
        rows = res.data.get("results") if isinstance(res.data, dict) else res.data
        self.assertEqual(len(rows), 0)


class PortalInviteTests(TestCase):
    def setUp(self):
        self.user = _make_user("invite_owner@example.com")
        self.org = _make_org(self.user, "Invite Org")
        self.client = _auth_client(self.user, self.org)
        self.emp = _employee(self.org, email="newstarter@invite.test")

    def test_invite_creates_a_sub_account(self):
        res = self.client.post(f"/api/v1/payroll/employees/{self.emp.id}/invite_portal/")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.emp.refresh_from_db()
        self.assertIsNotNone(self.emp.user)
        self.assertFalse(
            self.emp.user.is_sub_account,
            'portal users sign in with their email on the main login; the '
            'is_sub_account flag would force them onto /staff-login, which '
            'resolves a username against an organisation slug',
        )
        self.assertTrue(self.emp.user.must_change_password)

    def test_invite_requires_an_email(self):
        emp = _employee(self.org, "No", "Email", email="")
        res = self.client.post(f"/api/v1/payroll/employees/{emp.id}/invite_portal/")
        self.assertEqual(res.status_code, 400)

    def test_double_invite_is_refused(self):
        self.client.post(f"/api/v1/payroll/employees/{self.emp.id}/invite_portal/")
        again = self.client.post(f"/api/v1/payroll/employees/{self.emp.id}/invite_portal/")
        self.assertEqual(again.status_code, 400)

    def test_revoke_removes_access(self):
        self.client.post(f"/api/v1/payroll/employees/{self.emp.id}/invite_portal/")
        res = self.client.post(f"/api/v1/payroll/employees/{self.emp.id}/revoke_portal/")
        self.assertEqual(res.status_code, 200)
        self.emp.refresh_from_db()
        self.assertIsNone(self.emp.user)


class OrgChartTests(TestCase):
    def setUp(self):
        self.user = _make_user("chart_owner@example.com")
        self.org = _make_org(self.user, "Chart Org")
        self.client = _auth_client(self.user, self.org)
        self.ceo = _employee(self.org, "Chidi", "Bello")
        self.head = _employee(self.org, "Ada", "Okonkwo", manager=self.ceo)
        self.analyst = _employee(self.org, "Tunde", "Danjuma", manager=self.head)

    def test_chart_nests_reports_under_managers(self):
        res = self.client.get("/api/v1/payroll/employees/org_chart/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(len(res.data), 1)
        root = res.data[0]
        self.assertEqual(root["name"], "Chidi Bello")
        self.assertEqual(len(root["children"]), 1)
        self.assertEqual(root["children"][0]["children"][0]["name"], "Tunde Danjuma")

    def test_self_management_is_rejected(self):
        res = self.client.patch(
            f"/api/v1/payroll/employees/{self.head.id}/",
            {"manager": str(self.head.id)},
        )
        self.assertEqual(res.status_code, 400)

    def test_circular_reporting_is_rejected(self):
        res = self.client.patch(
            f"/api/v1/payroll/employees/{self.ceo.id}/",
            {"manager": str(self.analyst.id)},
        )
        self.assertEqual(res.status_code, 400, msg=str(res.data))


class BankExportTests(TestCase):
    def setUp(self):
        self.user = _make_user("bank_owner@example.com")
        self.org = _make_org(self.user, "Bank Org")
        self.client = _auth_client(self.user, self.org)
        _employee(self.org, bank_code="058", account_number="0123456789",
                  account_name="Ada Okonkwo", state_of_residence="LA")
        self.run = _run(self.org, self.user)
        PayrollService.run_payroll(self.run)

    def test_export_returns_a_workbook(self):
        res = self.client.get(f"/api/v1/payroll/runs/{self.run.id}/export_bank_file/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("spreadsheetml", res["Content-Type"])

    def test_employer_cost_includes_employee_pension(self):
        """
        The old bank-file grand total omitted the 8% employee contribution,
        understating what the employer actually has to fund.
        """
        res = self.client.get(f"/api/v1/payroll/runs/{self.run.id}/")
        cost = Decimal(res.data["employer_cost"])
        components = (
            Decimal(str(self.run.total_net))
            + Decimal(str(self.run.total_paye))
            + Decimal(str(self.run.total_pension_employee))
            + Decimal(str(self.run.total_pension_employer))
            + Decimal(str(self.run.total_nhf))
            + Decimal(str(self.run.total_nsitf))
            + Decimal(str(self.run.total_itf))
        )
        self.assertEqual(cost, components)
        self.assertGreater(
            cost,
            Decimal(str(self.run.total_net)) + Decimal(str(self.run.total_paye)),
        )
