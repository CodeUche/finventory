"""
Legacy report routes (/reports/account-statement/, /customer-details/, ...) and
the remaining hardening of the report engine.

These routes used to need only the Reports tick, so a Reports-only member could
read the full ledger of any account, the customer master (names, emails, phones,
balances: personal data), cost price and margin, AR/AP ageing, VAT and expense
breakdowns. Each route now names the module whose data it shows and is judged by
the same user_can_run_report as the registry reports.
"""

import json
import types
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from apps.core.permissions import user_can_run_report
from apps.core.test_module_access import _member
from apps.payroll.test_track_a import _auth_client, _make_org, _make_user
from apps.reports import registry
from apps.reports.tests.test_report_permissions import (
    ALL_KEYS, EXPECTED_REPORTS_OWNED, _run, _tick_member,
)
from apps.reports.views import (
    BaseDateRangeView, ReportBulkExportView, _ReportRouteAccess,
)
from apps.tenancy.models import Membership, ModulePermission

# route -> (module, role the normal screen needs, owner/admin only)
GATED_ROUTES = {
    "account-statement": ("accounting", "accountant", False),
    "customer-details": ("customers", "staff", False),
    "customer-balance": ("customers", "staff", False),
    "product-details": ("inventory", "staff", True),
    "inventory": ("inventory", "staff", True),
    "ar-aging": ("sales", "staff", False),
    "ap-aging": ("bills", "staff", False),
    "vat-summary": ("tax", "accountant", False),
    "expenses": ("expenses", "staff", False),
    "payments-by-customer": ("sales", "staff", False),
    "customer-payments": ("sales", "staff", False),
    "customer-invoices": ("sales", "staff", False),
}
# Intentionally Reports-tick-only content.
REPORTS_ROUTES = [
    "sales", "top-products", "top-customers", "pnl", "cash-flow",
    "sales-by-customer", "sales-by-product", "payment-methods",
]
REPORTS_VIEW_CLASSES = {
    "SalesSummaryView", "TopProductsView", "TopCustomersView", "ProfitAndLossView",
    "CashFlowView", "SalesByCustomerView", "SalesByProductView", "PaymentMethodsView",
    "ReportCatalogView", "ReportDispatchView", "ReportBulkExportView",
}


def _get(client, route, **params):
    params.setdefault("period", "all")
    return client.get(f"/api/v1/reports/{route}/", params)


class LegacyRouteAccessTests(TestCase):
    def setUp(self):
        self.owner = _make_user("lg_owner@example.com")
        self.org = _make_org(self.owner, "Legacy Report Org")

    def test_reports_only_member_is_refused_every_gated_route(self):
        for role in ("staff", "manager", "accountant"):
            _, client, _ = _tick_member(self.org, f"lg_ro_{role}@example.com", role, ["reports"])
            for route in GATED_ROUTES:
                with self.subTest(role=role, route=route):
                    self.assertEqual(_get(client, route).status_code, 403)

    def test_reports_only_member_still_gets_the_reports_content(self):
        _, client, _ = _tick_member(self.org, "lg_ro_ok@example.com", "staff", ["reports"])
        for route in REPORTS_ROUTES:
            with self.subTest(route=route):
                self.assertEqual(_get(client, route).status_code, 200)

    def test_matching_tick_opens_its_route(self):
        n = 0
        for route, (module, role, owner_admin_only) in GATED_ROUTES.items():
            n += 1
            _, client, _ = _tick_member(
                self.org, f"lg_ok_{n}@example.com", role, ["reports", module])
            with self.subTest(route=route):
                res = _get(client, route)
                if owner_admin_only:
                    # Cost-bearing: even with the tick, only owners/admins.
                    self.assertEqual(res.status_code, 403)
                else:
                    self.assertNotEqual(res.status_code, 403, res.content[:200])
                    self.assertLess(res.status_code, 500)

    def test_wrong_module_tick_is_refused(self):
        _, client, _ = _tick_member(
            self.org, "lg_wrong@example.com", "accountant", ["reports", "quotes", "budget"])
        for route in GATED_ROUTES:
            with self.subTest(route=route):
                self.assertEqual(_get(client, route).status_code, 403)

    def test_module_tick_without_reports_tick_is_refused(self):
        n = 0
        for route, (module, role, _) in GATED_ROUTES.items():
            n += 1
            _, client, _ = _tick_member(self.org, f"lg_nr_{n}@example.com", role, [module], "edit")
            with self.subTest(route=route):
                self.assertEqual(_get(client, route).status_code, 403)

    def test_accounting_and_tax_routes_also_need_the_accountant_role(self):
        for n, route in enumerate(("account-statement", "vat-summary")):
            module = GATED_ROUTES[route][0]
            _, client, _ = _tick_member(
                self.org, f"lg_role_{n}@example.com", "staff", ["reports", module], "edit")
            with self.subTest(route=route):
                self.assertEqual(_get(client, route).status_code, 403)

    def test_cost_bearing_routes_are_owner_admin_only(self):
        _, admin, _ = _member(self.org, "lg_admin@example.com", "admin")
        owner = _auth_client(self.owner, self.org)
        for route in ("product-details", "inventory"):
            for who, client in (("owner", owner), ("admin", admin)):
                with self.subTest(route=route, who=who):
                    self.assertEqual(_get(client, route).status_code, 200)

    def test_owner_and_admin_reach_every_legacy_route(self):
        _, admin, _ = _member(self.org, "lg_admin2@example.com", "admin")
        for who, client in (("owner", _auth_client(self.owner, self.org)), ("admin", admin)):
            for route in list(GATED_ROUTES) + REPORTS_ROUTES:
                with self.subTest(who=who, route=route):
                    self.assertNotEqual(_get(client, route).status_code, 403)

    def test_excel_and_pdf_exports_of_a_forbidden_legacy_route_are_refused(self):
        _, client, _ = _tick_member(self.org, "lg_fmt@example.com", "staff", ["reports"])
        for fmt in ("excel", "pdf"):
            with self.subTest(fmt=fmt):
                self.assertEqual(_get(client, "customer-details", format=fmt).status_code, 403)
                self.assertEqual(_get(client, "pnl", format=fmt).status_code, 200)

    def test_customer_master_does_not_leak_in_the_refusal(self):
        from apps.customers.models import Customer
        Customer.objects.create(
            organisation=self.org, name="Secret Buyer Ltd", email="secret@buyer.example")
        _, client, _ = _tick_member(self.org, "lg_leak@example.com", "staff", ["reports"])
        for route in ("customer-details", "customer-balance"):
            body = _get(client, route).content.decode()
            self.assertNotIn("Secret Buyer", body)
            self.assertNotIn("secret@buyer.example", body)

    def test_member_of_another_tenant_gets_403(self):
        other_owner = _make_user("lg_other@example.com")
        other_org = _make_org(other_owner, "Other Legacy Org")
        _, client, _ = _tick_member(
            other_org, "lg_cross@example.com", "staff", ["reports", "customers"], "edit")
        client.credentials(
            HTTP_AUTHORIZATION=client._credentials["HTTP_AUTHORIZATION"],
            HTTP_X_ORGANISATION_ID=str(self.org.id),
        )
        self.assertEqual(_get(client, "customer-details").status_code, 403)


class LowRolesAndInactiveMembershipTests(TestCase):
    def setUp(self):
        self.owner = _make_user("lr_owner@example.com")
        self.org = _make_org(self.owner, "Low Role Org")

    def test_viewer_and_employee_roles_get_403_everywhere_in_reports(self):
        for role in ("viewer", "employee"):
            _, client, _ = _tick_member(
                self.org, f"lr_{role}@example.com", role,
                ["reports", "payroll", "accounting", "customers", "sales"], "edit")
            with self.subTest(role=role, what="catalog"):
                self.assertEqual(client.get("/api/v1/reports/catalog/").status_code, 403)
            for key in ("profit-loss", "employee-list", "trial-balance"):
                with self.subTest(role=role, key=key):
                    self.assertEqual(_run(client, key).status_code, 403)
            for route in list(GATED_ROUTES) + REPORTS_ROUTES:
                with self.subTest(role=role, route=route):
                    self.assertEqual(_get(client, route).status_code, 403)

    def test_inactive_membership_is_refused(self):
        _, client, membership = _tick_member(
            self.org, "lr_inactive@example.com", "staff", ["reports", "payroll"], "edit")
        self.assertEqual(_run(client, "employee-list").status_code, 200)
        Membership.objects.filter(pk=membership.pk).update(is_active=False)
        self.assertEqual(_run(client, "employee-list").status_code, 403)
        self.assertEqual(client.get("/api/v1/reports/catalog/").status_code, 403)
        self.assertEqual(_get(client, "pnl").status_code, 403)


class PlanGateTests(TestCase):
    """Accounting, payroll and bills reports honour the plan for non-admins."""

    KEYS = {"accounting": "trial-balance", "payroll": "employee-list", "bills": "pay-bills"}

    def setUp(self):
        self.owner = _make_user("pgx_owner@example.com")
        self.org = _make_org(self.owner, "Plan Gate Org")
        self.members = {}
        for module in self.KEYS:
            role = "accountant" if module == "accounting" else "staff"
            _, client, _ = _tick_member(
                self.org, f"pgx_{module}@example.com", role, ["reports", module])
            self.members[module] = client

    def _all_open(self):
        for module, key in self.KEYS.items():
            self.assertEqual(_run(self.members[module], key).status_code, 200, key)

    def test_all_open_on_the_business_plan(self):
        self._all_open()

    def test_cancelled_subscription_blocks_them_but_not_the_owner(self):
        sub = self.org.subscription
        sub.status = "canceled"
        sub.save()
        for module, key in self.KEYS.items():
            with self.subTest(key=key):
                self.assertEqual(_run(self.members[module], key).status_code, 403)
        owner = _auth_client(self.owner, self.org)
        for key in self.KEYS.values():
            self.assertEqual(_run(owner, key).status_code, 200)
        # Reports-owned content is not plan-gated by module.
        self.assertEqual(_run(self.members["payroll"], "profit-loss").status_code, 200)

    def test_expired_trial_blocks_them(self):
        from datetime import timedelta
        from django.utils import timezone
        sub = self.org.subscription
        sub.status = "trialing"
        sub.trial_end = timezone.now() - timedelta(days=1)
        sub.save()
        for module, key in self.KEYS.items():
            with self.subTest(key=key):
                self.assertEqual(_run(self.members[module], key).status_code, 403)


class RouteDeclarationMetaTests(TestCase):
    def _subclasses(self):
        out, stack = [], list(BaseDateRangeView.__subclasses__())
        while stack:
            cls = stack.pop()
            out.append(cls)
            stack.extend(cls.__subclasses__())
        return out

    def test_every_report_view_declares_a_valid_module(self):
        valid = {m for m, _ in ModulePermission.MODULE_CHOICES}
        found = self._subclasses()
        self.assertGreaterEqual(len(found), 23)
        for cls in found:
            with self.subTest(view=cls.__name__):
                self.assertIn(cls.module, valid, f"{cls.__name__} declares no module")

    def test_reports_only_views_are_exactly_the_allowlist(self):
        reports_owned = {c.__name__ for c in self._subclasses() if c.module == "reports"}
        self.assertEqual(reports_owned, REPORTS_VIEW_CLASSES)

    def test_gated_routes_table_matches_the_views(self):
        by_route = {}
        for cls in self._subclasses():
            by_route[cls.__name__] = cls
        expected = {
            "AccountStatementView": ("accounting", False),
            "CustomerDetailsView": ("customers", False),
            "CustomerBalanceView": ("customers", False),
            "ProductDetailsView": ("inventory", True),
            "InventoryValuationView": ("inventory", True),
            "ARAgingView": ("sales", False),
            "APAgingView": ("bills", False),
            "VATSummaryView": ("tax", False),
            "ExpenseBreakdownView": ("expenses", False),
            "PaymentsByCustomerView": ("sales", False),
            "CustomerPaymentsView": ("sales", False),
            "CustomerInvoicesView": ("sales", False),
        }
        for name, (module, oa) in expected.items():
            with self.subTest(view=name):
                self.assertEqual(by_route[name].module, module)
                self.assertEqual(by_route[name].owner_admin_only, oa)

    def test_a_view_with_no_declared_module_is_refused_even_for_an_owner(self):
        # A stand-in view (not a real subclass, so it cannot leak into the other
        # meta tests) that forgot to declare what it shows.
        undeclared = types.SimpleNamespace(module=None, also_modules=(), owner_admin_only=False)
        owner = _make_user("meta_owner@example.com")
        req = APIRequestFactory().get("/")
        req.user = owner
        req.organisation = _make_org(owner, "Meta Org")
        self.assertFalse(_ReportRouteAccess().has_permission(req, undeclared))

    def test_stock_valuation_is_owner_admin_only_in_the_registry(self):
        self.assertTrue(registry.get("stock-valuation").owner_admin_only)
        self.assertFalse(registry.get("stock-report").owner_admin_only)

    def test_stock_valuation_refused_for_a_member_with_the_inventory_tick(self):
        owner = _make_user("sv_owner@example.com")
        org = _make_org(owner, "Valuation Org")
        _, client, _ = _tick_member(org, "sv_inv@example.com", "manager", ["reports", "inventory"], "edit")
        self.assertEqual(_run(client, "stock-valuation").status_code, 403)
        self.assertEqual(_run(client, "stock-report").status_code, 200)
        self.assertEqual(_run(_auth_client(owner, org), "stock-valuation").status_code, 200)


class CatalogQueryBudgetTests(TestCase):
    def setUp(self):
        self.owner = _make_user("qb_owner@example.com")
        self.org = _make_org(self.owner, "Query Budget Org")

    def test_judging_all_34_reports_costs_a_handful_of_queries(self):
        _, _, membership = _tick_member(
            self.org, "qb_member@example.com", "accountant",
            ["reports", "accounting", "payroll", "tax", "bills"])
        req = APIRequestFactory().get("/")
        req.user = membership.user
        req.organisation = self.org
        with CaptureQueriesContext(connection) as ctx:
            allowed = [k for k in ALL_KEYS if user_can_run_report(req, registry.get(k))]
        self.assertGreater(len(allowed), 3)
        self.assertLessEqual(len(ctx), 8, [q["sql"][:80] for q in ctx.captured_queries])

    def test_catalog_endpoint_query_count_is_bounded(self):
        _, client, _ = _tick_member(
            self.org, "qb_member2@example.com", "accountant",
            ["reports", "accounting", "payroll", "tax", "bills"])
        client.get("/api/v1/reports/catalog/")  # warm caches (content types etc.)
        with CaptureQueriesContext(connection) as ctx:
            res = client.get("/api/v1/reports/catalog/")
        self.assertEqual(res.status_code, 200)
        self.assertLessEqual(len(ctx), 30, len(ctx))

    def test_a_second_pass_over_all_reports_on_the_same_request_is_free(self):
        """Role, ticks and plan are read once per request, then judged in memory."""
        _, _, membership = _tick_member(
            self.org, "qb_member3@example.com", "staff", ["reports", "payroll"])
        req = APIRequestFactory().get("/")
        req.user = membership.user
        req.organisation = self.org
        for k in ALL_KEYS:
            user_can_run_report(req, registry.get(k))
        with CaptureQueriesContext(connection) as ctx:
            for k in ALL_KEYS:
                user_can_run_report(req, registry.get(k))
        self.assertEqual(len(ctx), 0)


class BulkEmailToTests(TestCase):
    def setUp(self):
        self.owner = _make_user("em_owner@example.com")
        self.org = _make_org(self.owner, "Email Org")
        _, self.client, _ = _tick_member(
            self.org, "em_mgr@example.com", "manager", ["reports"], "write")

    def _post(self, keys, email_to):
        return self.client.post(
            "/api/v1/reports/export-bulk/",
            {"keys": keys, "period": "all", "email_to": email_to}, format="json")

    def test_bad_addresses_are_refused_with_400_and_nothing_is_sent(self):
        bad = [
            "a@example.com\r\nBcc: spy@example.com",
            "a@example.com\nBcc: spy@example.com",
            "a@example.com,b@example.com",
            "a@example.com;b@example.com",
            "Name <a@example.com>",
            "not-an-address",
            "a@example.com " + "x" * 300,
            ("x" * 250) + "@example.com",
            "a b@example.com",
        ]
        with mock.patch.object(ReportBulkExportView, "_email_file") as sender:
            for value in bad:
                with self.subTest(value=value[:40]):
                    res = self._post(["profit-loss"], value)
                    self.assertEqual(res.status_code, 400, res.content[:200])
                    self.assertIn("email", res.json()["error"].lower())
            res = self.client.post(
                "/api/v1/reports/export-bulk/",
                {"keys": ["profit-loss"], "period": "all", "email_to": ["a@example.com"]},
                format="json")
            self.assertEqual(res.status_code, 400)
            sender.assert_not_called()

    def test_a_valid_address_reaches_the_sender_trimmed(self):
        def fake(self_view, request, org, email_to, filename, content_type, file_bytes, skipped):
            return Response({"message": "sent", "to": email_to})

        with mock.patch.object(ReportBulkExportView, "_email_file", fake):
            res = self._post(["profit-loss"], "  Someone@Example.com ")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["to"], "Someone@Example.com")

    def test_emailing_only_forbidden_reports_sends_nothing(self):
        with mock.patch.object(ReportBulkExportView, "_email_file") as sender:
            res = self._post(["employee-list", "customers-report"], "a@example.com")
        self.assertEqual(res.status_code, 422)
        sender.assert_not_called()
        self.assertEqual({s["reason"] for s in res.json()["skipped"]}, {"No access"})

    def test_reports_only_manager_cannot_pull_gated_legacy_keys_in_bulk(self):
        res = self.client.post(
            "/api/v1/reports/export-bulk/",
            {"keys": ALL_KEYS, "period": "all"}, format="json")
        self.assertEqual(res.status_code, 200)
        skipped = json.loads(res["X-Reports-Skipped"])
        self.assertEqual(
            {s["key"] for s in skipped if s["reason"] == "No access"},
            set(ALL_KEYS) - set(EXPECTED_REPORTS_OWNED),
        )
