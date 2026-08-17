"""
Tests for tenant context in Celery tasks (finding NEW-7).

Background
----------
Celery workers do not run RLSMiddleware, so tasks inherit the SENTINEL org id.
Against an RLS-protected table that matches no row, so every cross-tenant sweep
silently processed nothing in production while logging success.

These tests assert the two properties that make the fix real:
  1. every active organisation gets its own RLS context, and
  2. the SENTINEL is restored afterwards, so a worker never leaks one tenant's
     context into the next task it picks up.

Note on the test backend: config.settings.testing uses SQLite, which has no RLS
and where _set_org is a deliberate no-op. These tests therefore assert on the
*context-setting calls* rather than on row visibility — a Postgres-backed
integration test is required to prove actual isolation, tracked as NEW-8.
"""

from unittest.mock import call, patch

from django.test import TestCase

from apps.core.middleware import SENTINEL
from apps.core.tenant_context import for_each_organisation, organisation_context
from apps.authentication.models import User
from apps.tenancy.models import Organisation
from apps.tenancy.services import OrganisationService


def _make_org(email, name):
    user = User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="T", last_name="U", is_verified=True,
    )
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


class OrganisationContextTests(TestCase):
    def test_sets_org_then_restores_sentinel(self):
        with patch("apps.core.tenant_context._set_org") as m:
            with organisation_context("abc-123"):
                self.assertEqual(m.call_args_list, [call("abc-123")])
            self.assertEqual(m.call_args_list, [call("abc-123"), call(SENTINEL)])

    def test_restores_sentinel_even_when_body_raises(self):
        """A failing task must not leave a live tenant context on the worker."""
        with patch("apps.core.tenant_context._set_org") as m:
            with self.assertRaises(ValueError):
                with organisation_context("abc-123"):
                    raise ValueError("boom")
            self.assertEqual(m.call_args_list[-1], call(SENTINEL))


class ForEachOrganisationTests(TestCase):
    def setUp(self):
        self.org_a = _make_org("ctx_a@example.com", "Ctx Org A")
        self.org_b = _make_org("ctx_b@example.com", "Ctx Org B")

    def test_runs_once_per_active_organisation(self):
        seen = []
        result = for_each_organisation(lambda org: seen.append(org.id), task_name="t")
        self.assertCountEqual(seen, [self.org_a.id, self.org_b.id])
        self.assertEqual(result["organisations"], 2)

    def test_enumeration_is_not_empty(self):
        """
        Guards the failure mode that caused NEW-7: if tenancy_organisation ever
        becomes RLS-protected, enumeration returns nothing and every sweep
        silently processes zero tenants while still reporting success.
        """
        result = for_each_organisation(lambda org: 0, task_name="t")
        self.assertGreater(
            result["organisations"], 0,
            "organisation enumeration returned nothing — every scheduled task "
            "would silently no-op",
        )

    def test_sets_context_for_each_org(self):
        with patch("apps.core.tenant_context._set_org") as m:
            for_each_organisation(lambda org: None, task_name="t")
        org_calls = [c for c in m.call_args_list if c != call(SENTINEL)]
        self.assertCountEqual(
            [c.args[0] for c in org_calls],
            [str(self.org_a.id), str(self.org_b.id)],
        )

    def test_one_org_failing_does_not_abort_the_sweep(self):
        seen = []

        def flaky(org):
            seen.append(org.id)
            if org.id == self.org_a.id:
                raise RuntimeError("bad tenant data")
            return 5

        result = for_each_organisation(flaky, task_name="t")
        self.assertEqual(len(seen), 2, "sweep stopped early on the first failure")
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["processed"], 5)

    def test_sums_integer_results(self):
        result = for_each_organisation(lambda org: 3, task_name="t")
        self.assertEqual(result["processed"], 6)

    def test_skips_inactive_organisations(self):
        Organisation.objects.filter(id=self.org_b.id).update(is_active=False)
        seen = []
        for_each_organisation(lambda org: seen.append(org.id), task_name="t")
        self.assertEqual(seen, [self.org_a.id])


class ScheduledTasksUseTenantContextTests(TestCase):
    """
    Every cross-tenant scheduled task must establish per-org RLS context.

    This is the regression guard for NEW-7 itself: a task that queries tenant
    tables without entering an organisation context reads zero rows in
    production. Asserting on the source keeps a newly-added sweep from
    reintroducing the bug — it fails loudly at review time rather than silently
    at 00:05 in production.
    """

    # Every scheduled sweep that touches at least one RLS-protected table.
    #
    # The webhook, connector-event and tax sweeps were left off this list
    # originally, on the stated grounds that they touched no protected table.
    # That was true when it was written and is no longer: the staged RLS
    # batches bring integrations_domainevent, integrations_webhookdelivery,
    # integrations_webhooksubscription, connectors_connectoreventdelivery,
    # connectors_connectorconnection and tax_taxobligation under policy. The
    # moment those migrations deploy, all five tasks below would have begun
    # processing zero rows and reporting success — and the two webhook sweeps
    # are the busiest jobs on the scheduler, so the silence would have been
    # expensive. Converted and listed here as NEW-15.
    #
    # apps.subscriptions is still absent, and correctly so: it only touches
    # tenancy_organisation and the plan tables, none of which are RLS-covered
    # in any batch. Check the batch migrations before adding anything here.
    CROSS_TENANT_TASKS = [
        ("apps.sales.tasks", "mark_overdue_invoices"),
        ("apps.sales.tasks", "generate_recurring_invoices"),
        ("apps.sales.tasks", "create_year_archive_folders"),
        ("apps.accounting.tasks", "run_monthly_depreciation"),
        ("apps.bills.tasks", "create_bill_year_archive_folders"),
        ("apps.expenses.tasks", "archive_to_monthly_folders"),
        ("apps.payroll.tasks", "accrue_monthly_leave"),
        ("apps.payroll.tasks", "carry_forward_leave"),
        ("apps.payroll.tasks", "flag_expiring_documents"),
        ("apps.payroll.tasks", "post_leave_accrual_true_up_task"),
        ("apps.payroll.tasks", "expire_stale_advances"),
        ("apps.einvoicing.tasks", "report_b2c_invoices"),
        ("apps.einvoicing.tasks", "retry_failed_submissions"),
        # NEW-15
        ("apps.integrations.tasks", "deliver_pending_webhooks"),
        ("apps.connectors.tasks", "deliver_pending_connector_events"),
        ("apps.tax.tasks", "generate_monthly_vat_obligations"),
        ("apps.tax.tasks", "generate_monthly_paye_obligations"),
        ("apps.tax.tasks", "flag_overdue_tax_obligations"),
    ]

    def test_task_module_imports_tenant_context(self):
        import importlib
        import inspect

        for module_name, func_name in self.CROSS_TENANT_TASKS:
            mod = importlib.import_module(module_name)
            fn = getattr(mod, func_name)
            src = inspect.getsource(fn)
            # Either helper is acceptable. for_each_organisation is the usual
            # shape; a task that already had its own organisation loop just
            # opens organisation_context inside it, which is the same guarantee
            # with a smaller diff.
            self.assertTrue(
                "for_each_organisation" in src or "organisation_context" in src,
                f"{module_name}.{func_name} sweeps tenant tables without "
                f"per-organisation RLS context — it will silently process "
                f"zero rows in production (NEW-7)",
            )
