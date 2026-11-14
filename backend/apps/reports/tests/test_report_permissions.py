"""
Per-report access on the unified report engine.

Before this fix a member holding ONLY the "Reports" tick, role staff, could read
every registry report through GET /reports/r/<key>/ and /reports/catalog/:
employee salaries, payroll (gross/net/PAYE/pension), trial balance, the whole
ledger, the fixed-asset register, supplier and customer masters. The normal
screens for the same data need the accounting / payroll / tax / ... tick, a
higher role and the right plan. POST /reports/export-bulk/ bundled those sheets
and could email them.

Every report now declares the module tick that owns its data, and the engine
checks the same tick (plus the role and plan the normal screen needs).
"""

import io
import json
from unittest import mock

import openpyxl
from django.test import TestCase
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from apps.core.permissions import user_can_run_report
from apps.core.test_module_access import _member
from apps.payroll.test_track_a import _auth_client, _employee, _make_org, _make_user
from apps.reports import registry
from apps.reports.views import ReportBulkExportView
from apps.tenancy.models import ModulePermission

ALL_REPORTS = list(registry._REGISTRY.values())
ALL_KEYS = [rd.key for rd in ALL_REPORTS]
VALID_MODULES = {m for m, _ in ModulePermission.MODULE_CHOICES}
REPORTS_OWNED = sorted(rd.key for rd in ALL_REPORTS if rd.module == "reports")

# Reports that stay behind the "Reports" tick alone. Kept here as an explicit
# list so moving one is a visible decision, not a silent drift.
EXPECTED_REPORTS_OWNED = ["cash-flow", "profit-loss", "sales-by-customer"]

# Modules whose normal screens also demand the accountant role.
ACCOUNTANT_MODULES = {"accounting", "tax"}


def _tick_member(org, email, role, modules, level="view"):
    """A member with a tick for every module in `modules` (all at `level`)."""
    user, client, membership = _member(org, email, role)
    for m in modules:
        ModulePermission.objects.create(membership=membership, module=m, access_level=level)
    return user, client, membership


def _run(client, key, **params):
    params.setdefault("period", "all")
    return client.get(f"/api/v1/reports/r/{key}/", params)


class RegistryDeclarationTests(TestCase):
    def test_there_are_34_reports(self):
        self.assertEqual(len(ALL_KEYS), 34)

    def test_every_key_declares_a_valid_module(self):
        for rd in ALL_REPORTS:
            with self.subTest(key=rd.key):
                self.assertIn(rd.module, VALID_MODULES)
                for extra in rd.also_modules:
                    self.assertIn(extra, VALID_MODULES)

    def test_reports_owned_list_is_exactly_the_three_by_design(self):
        self.assertEqual(REPORTS_OWNED, EXPECTED_REPORTS_OWNED)

    def test_sensitive_keys_are_owned_by_their_module(self):
        expected = {
            "employee-list": "payroll", "payroll-report": "payroll",
            "attendance-summary": "payroll", "trial-balance": "accounting",
            "gl-detail": "accounting", "account-list": "accounting",
            "asset-register": "accounting", "vat-return": "tax",
            "tax-summary": "tax", "suppliers-report": "suppliers",
            "customers-report": "customers", "stock-report": "inventory",
            "stock-valuation": "inventory",
        }
        for key, module in expected.items():
            with self.subTest(key=key):
                self.assertEqual(registry.get(key).module, module)


class ReportsOnlyMemberTests(TestCase):
    """The reported hole: reports tick and nothing else."""

    def setUp(self):
        self.owner = _make_user("rp_owner@example.com")
        self.org = _make_org(self.owner, "Report Perm Org")
        self.owner_client = _auth_client(self.owner, self.org)

    def _check(self, role):
        _, client, _ = _tick_member(self.org, f"rp_{role}_only@example.com", role, ["reports"])
        for rd in ALL_REPORTS:
            with self.subTest(role=role, key=rd.key):
                res = _run(client, rd.key)
                if rd.module == "reports":
                    self.assertEqual(res.status_code, 200, res.content[:200])
                else:
                    self.assertEqual(
                        res.status_code, 403,
                        f"reports-only {role} read '{rd.key}' (owned by {rd.module})",
                    )

    def test_reports_only_staff(self):
        self._check("staff")

    def test_reports_only_manager(self):
        self._check("manager")

    def test_reports_only_accountant(self):
        # An accountant role still needs the accounting/tax TICK for those reports.
        self._check("accountant")

    def test_owner_and_admin_run_every_report(self):
        _, admin_client, _ = _member(self.org, "rp_admin@example.com", "admin")
        for who, client in (("owner", self.owner_client), ("admin", admin_client)):
            for rd in ALL_REPORTS:
                with self.subTest(who=who, key=rd.key):
                    res = _run(client, rd.key)
                    self.assertEqual(res.status_code, 200, res.content[:200])

    def test_forbidden_response_is_plain_and_leaks_nothing(self):
        _employee(self.org, basic="987654")
        _, client, _ = _tick_member(self.org, "rp_leak@example.com", "staff", ["reports"])
        res = _run(client, "employee-list")
        self.assertEqual(res.status_code, 403)
        body = res.content.decode()
        self.assertNotIn("987654", body)
        self.assertNotIn("basic_salary", body)
        self.assertIn("do not have access", body)

    def test_salary_leak_leave_only_member(self):
        """Same style as core/test_module_access.py: leave is not payroll."""
        _, client, _ = _tick_member(
            self.org, "rp_leave@example.com", "staff", ["leave", "reports"], "edit")
        self.assertEqual(_run(client, "employee-list").status_code, 403)
        self.assertEqual(_run(client, "payroll-report").status_code, 403)

    def test_export_formats_share_the_same_gate(self):
        _, client, _ = _tick_member(self.org, "rp_fmt@example.com", "staff", ["reports"])
        for fmt in ("excel", "pdf"):
            with self.subTest(fmt=fmt):
                self.assertEqual(_run(client, "employee-list", format=fmt).status_code, 403)
                self.assertEqual(_run(client, "profit-loss", format=fmt).status_code, 200)


class PerModuleTests(TestCase):
    """Reports tick + exactly one module tick: that module's keys open, no others."""

    def setUp(self):
        self.owner = _make_user("pm_owner@example.com")
        self.org = _make_org(self.owner, "Per Module Org")

    def test_each_module_opens_only_its_own_reports(self):
        modules = sorted({rd.module for rd in ALL_REPORTS} - {"reports"})
        for n, module in enumerate(modules):
            role = "accountant" if module in ACCOUNTANT_MODULES else "staff"
            _, client, _ = _tick_member(
                self.org, f"pm_{n}@example.com", role, ["reports", module])
            for rd in ALL_REPORTS:
                single = rd.module in ("reports", module) and set(rd.also_modules) <= {module}
                single = single and not rd.owner_admin_only or rd.module == "reports"
                with self.subTest(module=module, key=rd.key):
                    res = _run(client, rd.key)
                    if single:
                        self.assertEqual(res.status_code, 200, res.content[:200])
                    else:
                        self.assertEqual(res.status_code, 403)

    def test_payments_needs_both_bills_and_expenses(self):
        _, only_bills, _ = _tick_member(self.org, "pm_b@example.com", "staff", ["reports", "bills"])
        _, only_exp, _ = _tick_member(self.org, "pm_e@example.com", "staff", ["reports", "expenses"])
        _, both, _ = _tick_member(
            self.org, "pm_be@example.com", "staff", ["reports", "bills", "expenses"])
        self.assertEqual(_run(only_bills, "payments").status_code, 403)
        self.assertEqual(_run(only_exp, "payments").status_code, 403)
        self.assertEqual(_run(both, "payments").status_code, 200)

    def test_module_tick_alone_without_reports_tick_is_still_refused(self):
        _, client, _ = _tick_member(self.org, "pm_noreports@example.com", "staff", ["payroll"])
        self.assertEqual(_run(client, "employee-list").status_code, 403)

    def test_view_level_tick_is_enough_to_read(self):
        _, client, _ = _tick_member(
            self.org, "pm_view@example.com", "staff", ["reports", "payroll"], "view")
        self.assertEqual(_run(client, "employee-list").status_code, 200)

    def test_accounting_tick_without_accountant_role_is_refused(self):
        """Normal accounting screens are IsAccountant; the report must not be looser."""
        for module in sorted(ACCOUNTANT_MODULES):
            _, client, _ = _tick_member(
                self.org, f"pm_role_{module}@example.com", "staff", ["reports", module], "edit")
            for rd in ALL_REPORTS:
                if rd.module == module:
                    with self.subTest(module=module, key=rd.key):
                        self.assertEqual(_run(client, rd.key).status_code, 403)

    def test_user_can_run_report_helper_matches(self):
        _, _, membership = _tick_member(
            self.org, "pm_helper@example.com", "staff", ["reports", "payroll"])
        req = APIRequestFactory().get("/")
        req.user = membership.user
        req.organisation = self.org
        self.assertTrue(user_can_run_report(req, registry.get("employee-list")))
        self.assertTrue(user_can_run_report(req, registry.get("profit-loss")))
        self.assertFalse(user_can_run_report(req, registry.get("trial-balance")))


class PayrollPlanGateTests(TestCase):
    def test_employee_list_respects_the_payroll_plan_gate(self):
        from apps.subscriptions.models import Plan
        from apps.subscriptions.services import SubscriptionService

        owner = _make_user("pg_owner@example.com")
        org = _make_org(owner, "No Payroll Plan Org")
        plan = Plan.objects.create(
            slug="nopayroll", name="No Payroll", price=1000, interval="monthly",
            features={"modules": ["reports", "sales", "customers"]},
        )
        SubscriptionService.upgrade_plan(org, plan)
        org.refresh_from_db()

        _, client, _ = _tick_member(org, "pg_staff@example.com", "staff", ["reports", "payroll"])
        self.assertEqual(_run(client, "employee-list").status_code, 403)
        # Reports-owned reports are unaffected by the payroll plan gate.
        self.assertEqual(_run(client, "profit-loss").status_code, 200)
        # Owners keep seeing everything.
        self.assertEqual(_run(_auth_client(owner, org), "employee-list").status_code, 200)


class CatalogFilteringTests(TestCase):
    def setUp(self):
        self.owner = _make_user("cat_owner@example.com")
        self.org = _make_org(self.owner, "Catalog Org")

    @staticmethod
    def _keys(client):
        res = client.get("/api/v1/reports/catalog/")
        assert res.status_code == 200, res.content[:200]
        return sorted(r["key"] for r in res.json()["reports"])

    def test_reports_only_member_sees_only_reports_owned_keys(self):
        _, client, _ = _tick_member(self.org, "cat_ro@example.com", "staff", ["reports"])
        self.assertEqual(self._keys(client), EXPECTED_REPORTS_OWNED)

    def test_owner_and_admin_see_all_34(self):
        _, admin_client, _ = _member(self.org, "cat_admin@example.com", "admin")
        for client in (_auth_client(self.owner, self.org), admin_client):
            self.assertEqual(self._keys(client), sorted(ALL_KEYS))
            self.assertEqual(len(self._keys(client)), 34)

    def test_member_with_one_module_sees_reports_plus_that_module(self):
        _, client, _ = _tick_member(
            self.org, "cat_pay@example.com", "staff", ["reports", "payroll"])
        expected = sorted(rd.key for rd in ALL_REPORTS if rd.module in ("reports", "payroll"))
        self.assertEqual(self._keys(client), expected)

    def test_no_reports_tick_gets_403(self):
        _, client, _ = _tick_member(self.org, "cat_none@example.com", "staff", ["payroll"])
        self.assertEqual(client.get("/api/v1/reports/catalog/").status_code, 403)


class BulkExportTests(TestCase):
    def setUp(self):
        self.owner = _make_user("bk_owner@example.com")
        self.org = _make_org(self.owner, "Bulk Org")
        # Bulk export needs manager + reports write.
        _, self.client, _ = _tick_member(
            self.org, "bk_mgr@example.com", "manager", ["reports"], "write")

    def _post(self, client, keys, **extra):
        return client.post(
            "/api/v1/reports/export-bulk/",
            {"keys": keys, "period": "all", "combine": True, **extra}, format="json")

    @staticmethod
    def _sheet_titles(content):
        return openpyxl.load_workbook(io.BytesIO(content)).sheetnames

    def test_no_access_keys_are_skipped_and_get_no_sheet(self):
        res = self._post(self.client, ALL_KEYS)
        self.assertEqual(res.status_code, 200)
        skipped = json.loads(res["X-Reports-Skipped"])
        denied = {s["key"] for s in skipped if s["reason"] == "No access"}
        self.assertEqual(denied, set(ALL_KEYS) - set(EXPECTED_REPORTS_OWNED))
        titles = self._sheet_titles(res.content)
        self.assertEqual(len(titles), 3)
        for forbidden in ("Employee List", "Payroll Report", "Trial Balance"):
            self.assertNotIn(forbidden, titles)

    def test_only_forbidden_keys_gives_422_not_500(self):
        res = self._post(self.client, ["employee-list", "payroll-report"])
        self.assertEqual(res.status_code, 422)
        self.assertEqual({s["reason"] for s in res.json()["skipped"]}, {"No access"})

    def test_email_attachment_is_filtered_the_same_way(self):
        captured = {}

        def fake_email(self_view, request, org, email_to, filename, content_type,
                       file_bytes, skipped):
            captured["bytes"] = file_bytes
            captured["skipped"] = skipped
            return Response({"message": "sent", "skipped": skipped})

        with mock.patch.object(ReportBulkExportView, "_email_file", fake_email):
            res = self._post(self.client, ["profit-loss", "employee-list", "payroll-report"],
                             email_to="someone@example.com")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self._sheet_titles(captured["bytes"]), ["Profit & Loss"])
        self.assertEqual(
            sorted(s["key"] for s in captured["skipped"]), ["employee-list", "payroll-report"])

    def test_owner_bulk_export_contains_the_sheets(self):
        res = self._post(_auth_client(self.owner, self.org), ["profit-loss", "employee-list"])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(self._sheet_titles(res.content)), 2)

    def test_manager_with_payroll_tick_gets_the_payroll_sheet(self):
        _, client, _ = _tick_member(
            self.org, "bk_mgr2@example.com", "manager", ["reports", "payroll"], "write")
        res = self._post(client, ["profit-loss", "employee-list"])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(self._sheet_titles(res.content)), 2)


class TenantIsolationTests(TestCase):
    def test_member_of_org_a_gets_403_with_org_b_header(self):
        a_owner = _make_user("ti_a@example.com")
        b_owner = _make_user("ti_b@example.com")
        org_a = _make_org(a_owner, "Tenant A")
        org_b = _make_org(b_owner, "Tenant B")
        _, client_a, _ = _tick_member(org_a, "ti_member@example.com", "staff", ["reports"])
        auth = client_a._credentials["HTTP_AUTHORIZATION"]
        # Same credentials, but pointed at org B.
        client_a.credentials(HTTP_AUTHORIZATION=auth, HTTP_X_ORGANISATION_ID=str(org_b.id))
        self.assertEqual(_run(client_a, "profit-loss").status_code, 403)
        self.assertEqual(client_a.get("/api/v1/reports/catalog/").status_code, 403)
        # Even org A's OWNER cannot use org B's id.
        owner_client = _auth_client(a_owner, org_a)
        owner_client.credentials(
            HTTP_AUTHORIZATION=owner_client._credentials["HTTP_AUTHORIZATION"],
            HTTP_X_ORGANISATION_ID=str(org_b.id),
        )
        self.assertEqual(_run(owner_client, "employee-list").status_code, 403)
