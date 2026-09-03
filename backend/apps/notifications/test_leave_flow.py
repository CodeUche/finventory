"""
Leave notifications end to end.

The rule being pinned: when a request is raised, the line manager AND anyone
who can view leave requests are told, so cover exists when the manager is
away. When it is decided, the person whose leave it is hears the outcome —
even though they almost certainly do not hold the leave permission.
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.payroll.models import Employee, LeaveRequest, LeaveType
from apps.payroll.services import LeaveService
from apps.payroll.test_track_a import _make_user, _make_org, _auth_client
from apps.tenancy.models import Membership, ModulePermission

from .models import Notification, NotificationPreference


def _next_working_day() -> date:
    """
    A single-day leave request needs a date that actually contains a working
    day — using bare `date.today()` made this whole suite fail every time it
    ran on a Saturday or Sunday with "That range contains no working days.",
    which is the backend correctly rejecting the input, not a bug. Roll
    forward to the next weekday instead of pinning to "today".
    """
    d = date.today()
    while d.weekday() >= 5:  # 5=Saturday, 6=Sunday
        d += timedelta(days=1)
    return d


def _member(org, email, role="staff", leave_level=None):
    user = _make_user(email)
    membership = Membership.objects.create(
        user=user, organisation=org, role=role, is_active=True,
    )
    if leave_level:
        ModulePermission.objects.create(
            membership=membership, module="leave", access_level=leave_level,
        )
    return user, membership


class LeaveNotificationTests(TestCase):
    def setUp(self):
        from apps.accounting.tests import _upgrade_to_business

        self.owner = _make_user("ln_owner@example.com")
        self.org = _make_org(self.owner, "Leave Notif Org")
        _upgrade_to_business(self.org)

        # The person asking for leave.
        self.staff_user, _ = _member(self.org, "ln_staff@example.com")
        # Their line manager, with the leave tick.
        self.manager_user, _ = _member(self.org, "ln_mgr@example.com", "manager", "edit")
        # Somebody else who can see leave — the cover when the manager is away.
        self.cover_user, _ = _member(self.org, "ln_cover@example.com", "manager", "view")
        # Somebody with no leave access at all.
        self.outsider_user, _ = _member(self.org, "ln_out@example.com")

        self.manager_employee = Employee.objects.create(
            organisation=self.org, employee_id="LN-M", first_name="Mo",
            last_name="Manager", email="ln_mgr@example.com", job_title="Manager",
            hire_date=date.today(), basic_salary=Decimal("300000"),
            user=self.manager_user,
        )
        self.employee = Employee.objects.create(
            organisation=self.org, employee_id="LN-1", first_name="Sam",
            last_name="Staff", email="ln_staff@example.com", job_title="Clerk",
            hire_date=date.today(), basic_salary=Decimal("100000"),
            user=self.staff_user, manager=self.manager_employee,
        )
        self.leave_type = LeaveType.objects.create(
            organisation=self.org, name="Annual", days_per_year=20,
            requires_approval=True,
        )

    def _recipients_of(self, title_contains):
        return {
            n.recipient_id
            for n in Notification.objects.filter(title__icontains=title_contains)
        }

    def _raise_request(self):
        """
        Through /me/, which is the door employees actually use. The
        manager-facing /payroll/leave-requests/ is correctly gated on the leave
        permission — an employee asking for their own time off does not hold
        it, and should not need to.
        """
        client = _auth_client(self.staff_user, self.org)
        working_day = str(_next_working_day())
        with self.captureOnCommitCallbacks(execute=True):
            return client.post("/api/v1/me/leave-requests/", {
            "leave_type": str(self.leave_type.id),
            "start_date": working_day,
            "end_date": working_day,
            "reason": "Family matter",
            }, format="json")

    # --- raising a request ------------------------------------------------

    def test_manager_and_anyone_who_can_view_leave_are_told(self):
        res = self._raise_request()
        self.assertIn(res.status_code, (200, 201), res.content[:300])

        told = self._recipients_of("requested leave")
        self.assertIn(self.manager_user.id, told, "the line manager was not told")
        self.assertIn(
            self.cover_user.id, told,
            "nobody else who can view leave was told — a request raised while "
            "the manager is away would sit unanswered",
        )
        self.assertIn(self.owner.id, told, "the owner was not told")

    def test_someone_without_leave_access_is_not_told(self):
        self._raise_request()
        told = self._recipients_of("requested leave")
        self.assertNotIn(
            self.outsider_user.id, told,
            "a colleague with no leave access was told about someone's leave",
        )

    def test_the_requester_is_not_told_about_their_own_request(self):
        self._raise_request()
        told = self._recipients_of("requested leave")
        self.assertNotIn(self.staff_user.id, told)

    # --- deciding ---------------------------------------------------------

    def test_the_requester_hears_the_outcome_without_holding_the_permission(self):
        self._raise_request()
        leave = LeaveRequest.objects.get(employee=self.employee)
        with self.captureOnCommitCallbacks(execute=True):
            LeaveService.approve(leave, user=self.manager_user, note="Enjoy")

        told = self._recipients_of("was approved")
        self.assertIn(
            self.staff_user.id, told,
            "the person whose leave it is was never told the outcome",
        )

    def test_rejection_is_communicated_too(self):
        self._raise_request()
        leave = LeaveRequest.objects.get(employee=self.employee)
        with self.captureOnCommitCallbacks(execute=True):
            LeaveService.reject(leave, user=self.manager_user, note="Busy period")

        told = self._recipients_of("was declined")
        self.assertIn(self.staff_user.id, told)

    def test_the_decider_is_not_told_of_their_own_decision(self):
        self._raise_request()
        leave = LeaveRequest.objects.get(employee=self.employee)
        with self.captureOnCommitCallbacks(execute=True):
            LeaveService.approve(leave, user=self.manager_user)
        told = self._recipients_of("was approved")
        self.assertNotIn(self.manager_user.id, told)

    # --- email ------------------------------------------------------------

    def test_no_email_unless_the_person_asked_for_it(self):
        with patch("apps.connectors.gmail.GmailService.send_email") as send:
            self._raise_request()
        send.assert_not_called()

    def test_a_mail_failure_never_undoes_the_approval(self):
        """
        The business action has already happened. Throwing here would roll it
        back — an approved leave request must stay approved even if telling
        someone about it fails.
        """
        from apps.connectors.models import Connector, ConnectorConnection

        membership = Membership.objects.get(user=self.staff_user, organisation=self.org)
        NotificationPreference.objects.create(
            organisation=self.org, membership=membership,
            category=Notification.Category.LEAVE, email_enabled=True,
        )
        # A connected mailbox, so the send is actually attempted. Without one
        # the code short-circuits to "no mailbox connected" and the mock below
        # never fires — the test would pass while exercising nothing.
        ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.GMAIL,
            nango_connection_id="test-conn", status=ConnectorConnection.Status.ACTIVE,
        )
        self._raise_request()
        leave = LeaveRequest.objects.get(employee=self.employee)

        with patch(
            "apps.connectors.gmail.GmailService.send_email",
            side_effect=RuntimeError("gmail is down"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                LeaveService.approve(leave, user=self.manager_user)

        leave.refresh_from_db()
        self.assertEqual(
            leave.status, LeaveRequest.APPROVED,
            "a mail failure rolled back the approval",
        )
        note = Notification.objects.filter(
            recipient=self.staff_user, title__icontains="was approved",
        ).first()
        self.assertIsNotNone(note, "the in-app notification was lost with the email")
        self.assertEqual(note.email_status, Notification.EmailStatus.FAILED)

    def test_opted_in_but_no_mailbox_connected_is_recorded_not_silent(self):
        membership = Membership.objects.get(user=self.staff_user, organisation=self.org)
        NotificationPreference.objects.create(
            organisation=self.org, membership=membership,
            category=Notification.Category.LEAVE, email_enabled=True,
        )
        self._raise_request()
        leave = LeaveRequest.objects.get(employee=self.employee)
        with self.captureOnCommitCallbacks(execute=True):
            LeaveService.approve(leave, user=self.manager_user)

        note = Notification.objects.filter(
            recipient=self.staff_user, title__icontains="was approved",
        ).first()
        self.assertEqual(
            note.email_status, Notification.EmailStatus.NO_CONNECTOR,
            "wanting email with no mailbox connected should say so, not fail silently",
        )
