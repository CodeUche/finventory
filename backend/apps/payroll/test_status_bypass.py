"""
Payroll status-bypass tests (finding NEW-1).

Two separate holes, same shape as H-4/H-5/M-1: a field write reaching a state
that is supposed to require an event.

1. StatutoryRemittance — `status` was PATCHable, so an obligation could be
   marked "remitted" without RemittanceService.mark_remitted() ever running.
   That service records the payment AND posts the clearing journal, so the
   bypass leaves the liability sitting on the balance sheet forever while the
   compliance screen shows it settled. Tax records that claim money reached
   FIRS when it did not are the worst possible thing to get wrong here.

2. LeaveRequest — `status` was PATCHable by any staff-level user, so an
   employee could approve their own leave request. A dedicated `approve`
   action already exists and is what the UI uses.

3. EmployeeLoan — there is NO approval workflow (statuses are active/settled/
   cancelled only), so self-approval is not possible. The real hole is
   different: `status` is writable while `amount_repaid` is read-only, and
   SETTLED is legitimately reached only by PayrollService when the balance
   reaches zero. A staff user could therefore mark their own loan settled,
   writing off the outstanding balance and stopping payroll deductions.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.payroll.models import (
    AdvanceRequest, Employee, EmployeeLoan, LeaveRequest, LeaveType,
    StatutoryRemittance,
)
from apps.payroll.test_track_a import _make_user, _make_org, _auth_client
from apps.tenancy.models import Membership


def _add_member(org, email, role):
    """Create a user holding `role` in `org` and return an authed client."""
    user = _make_user(email)
    Membership.objects.create(user=user, organisation=org, role=role, is_active=True)
    return user, _auth_client(user, org)


class RemittanceStatusBypassTests(TestCase):
    def setUp(self):
        self.owner = _make_user("remit_owner@example.com")
        self.org = _make_org(self.owner, "Remit Org")
        self.client = _auth_client(self.owner, self.org)
        self.remittance = StatutoryRemittance.objects.create(
            organisation=self.org,
            remittance_type="paye",
            period_year=date.today().year,
            period_month=date.today().month,
            amount_due=Decimal("50000"),
            due_date=date.today(),
            status=StatutoryRemittance.PENDING,
        )

    def _patch(self, payload):
        return self.client.patch(
            f"/api/v1/payroll/remittances/{self.remittance.id}/", payload, format="json",
        )

    def test_cannot_mark_remitted_via_patch(self):
        res = self._patch({"status": StatutoryRemittance.REMITTED})
        self.assertIn(
            res.status_code, (400, 422),
            "PATCH marked a statutory obligation remitted without recording the "
            "payment or posting the clearing journal (NEW-1)",
        )
        self.remittance.refresh_from_db()
        self.assertEqual(self.remittance.status, StatutoryRemittance.PENDING)
        self.assertFalse(self.remittance.gl_cleared)

    def test_cannot_set_partial_via_patch(self):
        res = self._patch({"status": StatutoryRemittance.PARTIAL})
        self.assertIn(res.status_code, (400, 422))
        self.remittance.refresh_from_db()
        self.assertEqual(self.remittance.status, StatutoryRemittance.PENDING)

    def test_cannot_write_amount_paid_directly(self):
        """amount_paid is derived from recorded payments, never asserted."""
        res = self._patch({"amount_paid": "50000"})
        self.assertIn(res.status_code, (400, 422))
        self.remittance.refresh_from_db()
        self.assertEqual(self.remittance.amount_paid, Decimal("0"))

    def test_can_still_edit_notes_and_reference(self):
        res = self._patch({"notes": "Cheque raised, awaiting clearance", "reference": "CHQ-1"})
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.remittance.refresh_from_db()
        self.assertEqual(self.remittance.notes, "Cheque raised, awaiting clearance")
        self.assertEqual(self.remittance.reference, "CHQ-1")

    def test_mark_remitted_action_still_works(self):
        """The legitimate path must stay open — this is what CompliancePage uses."""
        res = self.client.post(
            f"/api/v1/payroll/remittances/{self.remittance.id}/mark_remitted/",
            {"reference": "FIRS-REF-1", "amount_paid": "50000"},
            format="json",
        )
        self.assertIn(res.status_code, (200, 201), res.content[:300])
        self.remittance.refresh_from_db()
        self.assertEqual(self.remittance.status, StatutoryRemittance.REMITTED)


class LeaveAndLoanSelfApprovalTests(TestCase):
    """A staff-level user must not be able to approve their own request."""

    def setUp(self):
        self.owner = _make_user("appr_owner@example.com")
        self.org = _make_org(self.owner, "Approval Org")
        self.staff_user, self.staff_client = _add_member(
            self.org, "appr_staff@example.com", "staff",
        )
        self.employee = Employee.objects.create(
            organisation=self.org, employee_id="E-1",
            first_name="Sam", last_name="Staff", email="appr_staff@example.com",
            hire_date=date.today(), basic_salary=Decimal("100000"),
        )
        self.leave_type = LeaveType.objects.create(
            organisation=self.org, name="Annual", days_per_year=20,
        )
        self.leave = LeaveRequest.objects.create(
            organisation=self.org, employee=self.employee, leave_type=self.leave_type,
            start_date=date.today(), end_date=date.today(), days=1,
            status=LeaveRequest.PENDING,
        )
        self.loan = EmployeeLoan.objects.create(
            organisation=self.org, employee=self.employee,
            principal_amount=Decimal("200000"), duration_months=10,
            start_date=date.today(), status=EmployeeLoan.ACTIVE,
        )

    def test_staff_cannot_approve_own_leave_via_patch(self):
        res = self.staff_client.patch(
            f"/api/v1/payroll/leave-requests/{self.leave.id}/",
            {"status": LeaveRequest.APPROVED}, format="json",
        )
        self.assertIn(
            res.status_code, (400, 403, 422),
            "a staff user approved their own leave request by PATCHing status",
        )
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, LeaveRequest.PENDING)

    def test_staff_cannot_write_off_own_loan_via_patch(self):
        """
        SETTLED is reached only by PayrollService once the balance is repaid.
        Setting it directly writes off the outstanding amount and stops the
        payroll deduction.
        """
        res = self.staff_client.patch(
            f"/api/v1/payroll/loans/{self.loan.id}/",
            {"status": EmployeeLoan.SETTLED}, format="json",
        )
        self.assertIn(
            res.status_code, (400, 403, 422),
            "a staff user marked their own loan settled while amount_repaid "
            "was still 0 — the debt is written off and deductions stop",
        )
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.status, EmployeeLoan.ACTIVE)

    def test_manager_can_still_use_the_leave_approve_action(self):
        """The legitimate path must stay open for someone with authority."""
        _, mgr_client = _add_member(self.org, "appr_mgr@example.com", "manager")
        res = mgr_client.post(
            f"/api/v1/payroll/leave-requests/{self.leave.id}/approve/", {}, format="json",
        )
        self.assertIn(res.status_code, (200, 201), res.content[:300])
        self.leave.refresh_from_db()
        self.assertEqual(self.leave.status, LeaveRequest.APPROVED)


class LoanApprovalWorkflowTests(TestCase):
    """
    Finding NEW-10 — self-issued credit.

    Before this workflow, EmployeeLoanViewSet.perform_create was just
    serializer.save(organisation=...) behind IsStaff, and a new loan defaulted
    to ACTIVE. Any staff-level user could therefore create a loan for
    themselves that payroll began deducting immediately, with no approval and
    no second pair of eyes.

    Loans now start PENDING (inert — PayrollService filters on ACTIVE) and only
    a manager can create or approve one. A manager cannot approve their own.
    """

    def setUp(self):
        self.owner = _make_user("loanflow_owner@example.com")
        self.org = _make_org(self.owner, "Loan Flow Org")
        self.owner_client = _auth_client(self.owner, self.org)
        self.staff_user, self.staff_client = _add_member(
            self.org, "loanflow_staff@example.com", "staff",
        )
        self.mgr_user, self.mgr_client = _add_member(
            self.org, "loanflow_mgr@example.com", "manager",
        )
        self.employee = Employee.objects.create(
            organisation=self.org, employee_id="LE-1",
            first_name="Ada", last_name="Staff", email="loanflow_staff@example.com",
            hire_date=date.today(), basic_salary=Decimal("100000"),
            user=self.staff_user,
        )
        # An employee record tied to the manager, to test self-approval.
        self.mgr_employee = Employee.objects.create(
            organisation=self.org, employee_id="LE-2",
            first_name="Mgr", last_name="Person", email="loanflow_mgr@example.com",
            hire_date=date.today(), basic_salary=Decimal("300000"),
            user=self.mgr_user,
        )

    def _loan_payload(self, employee):
        return {
            "employee": str(employee.id),
            "principal_amount": "200000",
            "duration_months": 10,
            "start_date": str(date.today()),
        }

    # --- creation is a manager decision ---------------------------------

    def test_staff_cannot_create_a_loan(self):
        res = self.staff_client.post(
            "/api/v1/payroll/loans/", self._loan_payload(self.employee), format="json",
        )
        self.assertEqual(
            res.status_code, 403,
            "a staff user issued company credit to themselves (NEW-10)",
        )
        self.assertFalse(EmployeeLoan.objects.exists())

    def test_manager_can_create_a_loan(self):
        res = self.mgr_client.post(
            "/api/v1/payroll/loans/", self._loan_payload(self.employee), format="json",
        )
        self.assertIn(res.status_code, (200, 201), res.content[:300])

    def test_new_loan_starts_pending_and_does_not_deduct(self):
        self.mgr_client.post(
            "/api/v1/payroll/loans/", self._loan_payload(self.employee), format="json",
        )
        loan = EmployeeLoan.objects.get()
        self.assertEqual(
            loan.status, EmployeeLoan.PENDING,
            "a new loan went straight to active without approval",
        )
        # PayrollService only ever deducts against ACTIVE loans, so PENDING is
        # inert by construction rather than by a separate guard.
        self.assertNotEqual(loan.status, EmployeeLoan.ACTIVE)

    # --- approval -------------------------------------------------------

    def _make_pending_loan(self, employee):
        return EmployeeLoan.objects.create(
            organisation=self.org, employee=employee,
            principal_amount=Decimal("200000"), duration_months=10,
            start_date=date.today(), status=EmployeeLoan.PENDING,
        )

    def test_manager_approval_activates_the_loan_and_records_who(self):
        loan = self._make_pending_loan(self.employee)
        res = self.mgr_client.post(
            f"/api/v1/payroll/loans/{loan.id}/approve/", {"note": "Approved"}, format="json",
        )
        self.assertIn(res.status_code, (200, 201), res.content[:300])
        loan.refresh_from_db()
        self.assertEqual(loan.status, EmployeeLoan.ACTIVE)
        self.assertEqual(loan.approved_by_id, self.mgr_user.id)
        self.assertIsNotNone(loan.approved_at)

    def test_staff_cannot_approve(self):
        loan = self._make_pending_loan(self.employee)
        res = self.staff_client.post(f"/api/v1/payroll/loans/{loan.id}/approve/", {}, format="json")
        self.assertEqual(res.status_code, 403)
        loan.refresh_from_db()
        self.assertEqual(loan.status, EmployeeLoan.PENDING)

    def test_manager_cannot_approve_their_own_loan(self):
        """The second pair of eyes has to belong to someone else."""
        loan = self._make_pending_loan(self.mgr_employee)
        res = self.mgr_client.post(f"/api/v1/payroll/loans/{loan.id}/approve/", {}, format="json")
        self.assertEqual(
            res.status_code, 403,
            "a manager approved their own loan — the approval step is decorative",
        )
        loan.refresh_from_db()
        self.assertEqual(loan.status, EmployeeLoan.PENDING)

    def test_another_manager_can_approve_it(self):
        """Self-approval is blocked, not manager approval generally."""
        _, other_mgr_client = _add_member(self.org, "loanflow_mgr2@example.com", "manager")
        loan = self._make_pending_loan(self.mgr_employee)
        res = other_mgr_client.post(f"/api/v1/payroll/loans/{loan.id}/approve/", {}, format="json")
        self.assertIn(res.status_code, (200, 201), res.content[:300])
        loan.refresh_from_db()
        self.assertEqual(loan.status, EmployeeLoan.ACTIVE)

    def test_cannot_activate_by_patching_status(self):
        """The approval step must not be reachable as a field write."""
        loan = self._make_pending_loan(self.employee)
        res = self.mgr_client.patch(
            f"/api/v1/payroll/loans/{loan.id}/",
            {"status": EmployeeLoan.ACTIVE}, format="json",
        )
        self.assertIn(res.status_code, (400, 403, 422))
        loan.refresh_from_db()
        self.assertEqual(loan.status, EmployeeLoan.PENDING)

    def test_reject_marks_it_rejected(self):
        loan = self._make_pending_loan(self.employee)
        res = self.mgr_client.post(
            f"/api/v1/payroll/loans/{loan.id}/reject/", {"note": "Not this quarter"}, format="json",
        )
        self.assertIn(res.status_code, (200, 201), res.content[:300])
        loan.refresh_from_db()
        self.assertEqual(loan.status, EmployeeLoan.REJECTED)
        self.assertEqual(loan.decision_note, "Not this quarter")

    def test_cannot_approve_an_already_active_loan(self):
        loan = self._make_pending_loan(self.employee)
        self.mgr_client.post(f"/api/v1/payroll/loans/{loan.id}/approve/", {}, format="json")
        res = self.mgr_client.post(f"/api/v1/payroll/loans/{loan.id}/approve/", {}, format="json")
        self.assertEqual(res.status_code, 400, "double approval was allowed")
