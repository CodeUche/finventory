"""
Per-person module access (finding H-2).

The owner ticks boxes saying which modules each team member may use. Before
this, those ticks were read only by the browser: useModuleAccess.ts hid menu
items and blocked routes, while the server checked just the organisation's PLAN
and the person's ROLE. Neither looks at the ticks.

So a team member with HR unticked saw no HR menu, and could still ask the
server for the staff list and receive salaries, national ID numbers, pension
numbers and bank details. Across the whole backend the ticks were consulted in
exactly one place.

These tests pin the server to the same rule the browser already applies, so the
two cannot drift:

    superuser / owner / admin  → full access, ticks ignored
    everyone else              → no record means no access
      none  → nothing   view → read   write → read+create   edit → everything

The negative cases prove the hole is shut. The positive cases matter just as
much: a permission fix that locks out the people who are supposed to have
access is an outage, not a fix.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.payroll.models import Employee
from apps.payroll.test_track_a import _make_user, _make_org, _auth_client
from apps.tenancy.models import Membership, ModulePermission


def _member(org, email, role, module=None, level=None):
    """A member of `org` with an optional tick for one module."""
    user = _make_user(email)
    membership = Membership.objects.create(
        user=user, organisation=org, role=role, is_active=True,
    )
    if module:
        ModulePermission.objects.create(
            membership=membership, module=module, access_level=level,
        )
    return user, _auth_client(user, org), membership


class HRModuleAccessTests(TestCase):
    """HR is the module that exposed real harm: pay, NIN, pension, bank."""

    def setUp(self):
        from apps.accounting.tests import _upgrade_to_business

        self.owner = _make_user("mod_owner@example.com")
        self.org = _make_org(self.owner, "Module Org")
        _upgrade_to_business(self.org)
        self.owner_client = _auth_client(self.owner, self.org)
        Employee.objects.create(
            organisation=self.org, employee_id="M-1",
            first_name="Ada", last_name="Pay", email="ada@example.com",
            hire_date=date.today(), basic_salary=Decimal("500000"),
        )

    def _list(self, client):
        return client.get("/api/v1/payroll/employees/")

    # --- the hole ---------------------------------------------------------

    def test_staff_without_the_hr_tick_cannot_read_the_staff_list(self):
        _, client, _ = _member(self.org, "mod_nohr@example.com", "staff")
        res = self._list(client)
        self.assertEqual(
            res.status_code, 403,
            "a team member with no HR access read the staff list — salaries, "
            "national ID numbers and bank details (H-2)",
        )

    def test_staff_ticked_none_cannot_read_it_either(self):
        _, client, _ = _member(
            self.org, "mod_none@example.com", "staff", "payroll", "none",
        )
        self.assertEqual(self._list(client).status_code, 403)

    def test_view_only_cannot_create_an_employee(self):
        _, client, _ = _member(
            self.org, "mod_view@example.com", "staff", "payroll", "view",
        )
        res = client.post("/api/v1/payroll/employees/", {
            "employee_id": "M-2", "first_name": "New", "last_name": "Hire",
            "email": "new@example.com", "hire_date": str(date.today()), "job_title": "Clerk",
            "basic_salary": "100000",
        }, format="json")
        self.assertEqual(
            res.status_code, 403,
            "'view only' was able to create a record",
        )

    def test_write_cannot_delete_an_existing_record(self):
        """`write` means enter new work, not change or remove what exists."""
        _, client, _ = _member(
            self.org, "mod_write@example.com", "staff", "payroll", "write",
        )
        emp = Employee.objects.first()
        res = client.delete(f"/api/v1/payroll/employees/{emp.id}/")
        self.assertEqual(res.status_code, 403)

    # --- what must keep working ------------------------------------------

    def test_owner_is_unaffected(self):
        """Owners bypass the ticks entirely — that is the documented design."""
        self.assertEqual(self._list(self.owner_client).status_code, 200)

    def test_admin_is_unaffected(self):
        _, client, _ = _member(self.org, "mod_admin@example.com", "admin")
        self.assertEqual(
            self._list(client).status_code, 200,
            "an admin was blocked — admins are meant to bypass the ticks",
        )

    def test_a_granted_member_can_read(self):
        _, client, _ = _member(
            self.org, "mod_ok@example.com", "staff", "payroll", "view",
        )
        res = self._list(client)
        self.assertEqual(
            res.status_code, 200,
            "a member who WAS granted HR access got blocked — this fix would "
            "be an outage rather than a fix",
        )

    def test_edit_level_can_create(self):
        _, client, _ = _member(
            self.org, "mod_edit@example.com", "staff", "payroll", "edit",
        )
        res = client.post("/api/v1/payroll/employees/", {
            "employee_id": "M-3", "first_name": "Full", "last_name": "Access",
            "email": "full@example.com", "hire_date": str(date.today()), "job_title": "Clerk",
            "basic_salary": "100000",
        }, format="json")
        self.assertIn(res.status_code, (200, 201), res.content[:300])

    def test_leave_access_does_not_grant_salary_access(self):
        """
        The model separates 'leave' from 'payroll' precisely so a line manager
        can approve time off without seeing anyone's pay. That separation is
        meaningless unless the server honours it.
        """
        _, client, _ = _member(
            self.org, "mod_leave@example.com", "staff", "leave", "edit",
        )
        self.assertEqual(
            self._list(client).status_code, 403,
            "a leave-only grant leaked access to salaries",
        )


class ModuleKeysAgreeTests(TestCase):
    """
    The tick an owner can set and the tick the server demands must be the same
    string. If they drift, one of two bad things happens:

      server asks for a key the UI cannot grant  → nobody can ever get access
      UI grants a key the server ignores         → the tick does nothing

    Both shipped at least once. `leave` was in the model and in the server
    guard but missing from ALL_MODULES in SettingsPage.tsx, so no owner could
    grant it and every non-owner would have been locked out of leave for good.
    Recurring invoices had its own route and tick in the UI while the server
    gated it under `sales`.

    Reading the real files keeps this honest — a hand-copied list here would
    drift with everything else.
    """

    SETTINGS_PAGE = "../frontend/src/pages/SettingsPage.tsx"

    def _ui_grantable_keys(self):
        import os
        import re
        path = os.path.join(os.path.dirname(__file__), "..", "..", self.SETTINGS_PAGE)
        path = os.path.normpath(path)
        if not os.path.exists(path):
            self.skipTest("frontend not present in this checkout")
        src = open(path, encoding="utf-8").read()
        # Split on "= [" first: the declaration itself contains "]" in
        # `{ key: ModuleKey; label: string }[]`, so splitting on "]" alone
        # slices an empty block and the test passes or fails for the wrong
        # reason.
        block = src.split("const ALL_MODULES", 1)[1].split("= [", 1)[1].split("]", 1)[0]
        return set(re.findall(r"key:\s*'([a-z_]+)'", block))

    def _server_required_keys(self):
        """Every key any viewset actually demands, read from the source."""
        import glob
        import os
        import re
        base = os.path.join(os.path.dirname(__file__), "..")
        keys = set()
        for f in glob.glob(os.path.join(base, "*", "views.py")):
            src = open(f, encoding="utf-8").read()
            keys |= set(re.findall(r'requires_module\(\s*"([a-z_]+)"\s*\)', src))
        return keys

    def test_every_key_the_server_demands_can_be_granted_in_the_ui(self):
        server = self._server_required_keys()
        ui = self._ui_grantable_keys()
        ungrantable = sorted(server - ui)
        self.assertEqual(
            ungrantable, [],
            f"the server requires {ungrantable} but an owner cannot tick "
            f"{'it' if len(ungrantable) == 1 else 'them'} in Settings — every "
            f"non-owner would be locked out of that area permanently. Add it to "
            f"ALL_MODULES in SettingsPage.tsx.",
        )

    def test_server_keys_are_real_module_choices(self):
        """Guards a typo: requires_module('payrol') would silently deny everyone."""
        valid = {k for k, _ in ModulePermission.MODULE_CHOICES}
        unknown = sorted(self._server_required_keys() - valid)
        self.assertEqual(
            unknown, [],
            f"{unknown} is not in ModulePermission.MODULE_CHOICES, so no "
            f"permission row can ever match it and access is denied to all",
        )


class ReportsModuleAccessTests(TestCase):
    """
    The report endpoints checked role only. A team member refused /customers/
    and /sales/invoices/ could read the same customers — names, emails, phones,
    balances — and every sale through /reports/customer-details/ and friends.
    """

    REPORTS = (
        "/api/v1/reports/customer-details/",
        "/api/v1/reports/sales-by-customer/",
        "/api/v1/reports/pnl/",
    )

    def setUp(self):
        self.owner = _make_user("rep_owner@example.com")
        self.org = _make_org(self.owner, "Reports Org")
        self.owner_client = _auth_client(self.owner, self.org)

    def test_staff_without_the_reports_tick_cannot_read_reports(self):
        _, client, _ = _member(self.org, "rep_none@example.com", "staff")
        for url in self.REPORTS:
            self.assertEqual(
                client.get(url).status_code, 403,
                f"{url} answered a team member with no Reports access",
            )

    def test_staff_with_the_reports_tick_can(self):
        _, client, _ = _member(self.org, "rep_view@example.com", "staff", "reports", "view")
        for url in self.REPORTS:
            self.assertEqual(client.get(url).status_code, 200, url)

    def test_owner_is_unaffected(self):
        for url in self.REPORTS:
            self.assertEqual(self.owner_client.get(url).status_code, 200, url)


class SalaryAdvanceAccessTests(TestCase):
    """
    Salary advances checked role and plan only, so a staff member with no HR
    access could read an employee's accrued pay, raise an advance for them and
    approve — i.e. disburse — it themselves.
    """

    def setUp(self):
        from apps.payroll.models import AdvancePolicy, AdvanceRequest

        self.owner = _make_user("adv_owner@example.com")
        self.org = _make_org(self.owner, "Advance Org")
        self.owner_client = _auth_client(self.owner, self.org)
        AdvancePolicy.objects.update_or_create(organisation=self.org, defaults={"is_enabled": True})
        self.emp = Employee.objects.create(
            organisation=self.org, employee_id="A-1",
            first_name="Ada", last_name="Pay", email="adv_emp@example.com",
            hire_date=date(2025, 1, 6), basic_salary=Decimal("300000"),
        )
        self.advance = AdvanceRequest.objects.create(
            organisation=self.org, employee=self.emp, amount=Decimal("6000"),
            total_recoverable=Decimal("6000"), period_year=2026, period_month=6,
        )

    def _approve(self, client):
        return client.post(f"/api/v1/payroll/advances/{self.advance.id}/approve/", {}, format="json")

    def test_staff_without_hr_access_cannot_read_or_raise_advances(self):
        _, client, _ = _member(self.org, "adv_none@example.com", "staff")
        self.assertEqual(client.get("/api/v1/payroll/advances/").status_code, 403)
        self.assertEqual(
            client.get(f"/api/v1/payroll/advances/eligibility/{self.emp.id}/").status_code, 403,
            "eligibility exposes the employee's accrued pay",
        )
        res = client.post("/api/v1/payroll/advances/", {"employee": str(self.emp.id), "amount": "6000"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_staff_cannot_approve_even_with_hr_edit(self):
        _, client, _ = _member(self.org, "adv_edit@example.com", "staff", "payroll", "edit")
        self.assertEqual(self._approve(client).status_code, 403)
        self.advance.refresh_from_db()
        self.assertEqual(self.advance.status, "pending")

    def test_manager_with_hr_access_can_approve(self):
        _, client, _ = _member(self.org, "adv_mgr@example.com", "manager", "payroll", "edit")
        res = self._approve(client)
        self.assertNotEqual(res.status_code, 403, res.content[:300])

    def test_no_one_approves_their_own_advance(self):
        user, client, _ = _member(self.org, "adv_self@example.com", "manager", "payroll", "edit")
        self.emp.user = user
        self.emp.save(update_fields=["user"])
        self.assertEqual(self._approve(client).status_code, 403)
        self.advance.refresh_from_db()
        self.assertEqual(self.advance.status, "pending")

