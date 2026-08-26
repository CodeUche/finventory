"""Tests for the budgets app Phase 1 upgrade: approve action, budget_type/
account/date fields, the monitoring endpoint, and the Expense.budget-link
variance fix (an expense explicitly linked to Budget A must never be
attributed to Budget B just because both have a same-named category)."""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.models import Account
from apps.accounting.services import AccountingService
from apps.authentication.models import User
from apps.budgets.models import Budget, BudgetLine
from apps.budgets.services import BudgetService
from apps.core.models import AuditLog
from apps.expenses.models import Expense, ExpenseCategory
from apps.subscriptions.models import Plan
from apps.subscriptions.services import SubscriptionService
from apps.tenancy.models import Membership
from apps.tenancy.services import OrganisationService


def _make_user(email="budget_owner@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Budget", last_name="Owner", is_verified=True,
    )


def _make_org(user, name="Budget Org"):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _upgrade_to_business(org):
    """See apps/accounting/tests.py — same reasoning, seeded here so this
    suite doesn't depend on run order for the Business plan row."""
    plan, _ = Plan.objects.get_or_create(
        slug="business",
        defaults={
            "name": "Business",
            "price": 30000,
            "interval": "monthly",
            "features": {"modules": [
                "invoicing", "sales", "customers", "expenses", "inventory",
                "suppliers", "purchases", "quotes", "recurring", "budget",
                "reports", "payroll", "accounting", "owner_analytics",
                "audit_log", "team", "tax", "bills",
            ]},
        },
    )
    SubscriptionService.upgrade_plan(org, plan)
    org.refresh_from_db()


def _auth_client(user, org):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return client


class BudgetApproveTests(TestCase):
    def setUp(self):
        self.owner = _make_user("approve_owner@example.com")
        self.org = _make_org(self.owner, "Approve Org")
        _upgrade_to_business(self.org)
        self.owner_client = _auth_client(self.owner, self.org)
        self.budget = Budget.objects.create(
            organisation=self.org, name="2026 Ops Budget", fiscal_year=2026,
        )

    def test_owner_can_approve(self):
        res = self.owner_client.post(f"/api/v1/budgets/{self.budget.id}/approve/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.approved_by_id, self.owner.id)
        self.assertIsNotNone(self.budget.approved_at)

    def test_approve_writes_audit_log(self):
        before_count = AuditLog.objects.filter(model_name='Budget', action=AuditLog.UPDATE).count()
        res = self.owner_client.post(f"/api/v1/budgets/{self.budget.id}/approve/")
        self.assertEqual(res.status_code, 200)
        after_count = AuditLog.objects.filter(model_name='Budget', action=AuditLog.UPDATE).count()
        self.assertEqual(after_count, before_count + 1)
        entry = AuditLog.objects.filter(model_name='Budget', action=AuditLog.UPDATE).latest('created_at')
        self.assertEqual(entry.object_id, str(self.budget.id))
        self.assertIn('approved_by', entry.changes)

    def test_staff_cannot_approve(self):
        """Below-manager roles are blocked — IsManagerOrSuperuser, same gate
        as the rest of the viewset. No new role tier was invented."""
        staff_user = _make_user("approve_staff@example.com")
        Membership.objects.create(
            user=staff_user, organisation=self.org, role="staff", is_active=True,
        )
        staff_client = _auth_client(staff_user, self.org)
        res = staff_client.post(f"/api/v1/budgets/{self.budget.id}/approve/")
        self.assertEqual(res.status_code, 403)
        self.budget.refresh_from_db()
        self.assertIsNone(self.budget.approved_by_id)

    def test_manager_can_approve(self):
        """A manager passes IsManagerOrSuperuser, but the viewset also stacks
        requires_module('budget') — a non-admin role needs an explicit
        ModulePermission grant too (owners/admins bypass by design, everyone
        else needs the ticks). Grant it here to exercise the realistic path."""
        from apps.tenancy.models import ModulePermission
        manager_user = _make_user("approve_manager@example.com")
        membership = Membership.objects.create(
            user=manager_user, organisation=self.org, role="manager", is_active=True,
        )
        ModulePermission.objects.create(membership=membership, module="budget", access_level="edit")
        manager_client = _auth_client(manager_user, self.org)
        res = manager_client.post(f"/api/v1/budgets/{self.budget.id}/approve/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))


class BudgetFieldsTests(TestCase):
    """Additive Phase 1 fields round-trip correctly and don't break the
    pre-existing serializer contract."""

    def setUp(self):
        self.owner = _make_user("fields_owner@example.com")
        self.org = _make_org(self.owner, "Fields Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.owner, self.org)

    def test_create_capital_budget_with_dates(self):
        res = self.client.post("/api/v1/budgets/", {
            "name": "2026 Capex", "fiscal_year": 2026, "period_type": "annual",
            "budget_type": "capital", "start_date": "2026-01-01", "end_date": "2026-12-31",
        })
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(res.data["budget_type"], "capital")
        self.assertEqual(res.data["start_date"], "2026-01-01")

    def test_default_budget_type_is_operational(self):
        res = self.client.post("/api/v1/budgets/", {"name": "Plain", "fiscal_year": 2026})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["budget_type"], "operational")

    def test_approved_by_not_writable_via_patch(self):
        """approved_by/approved_at are read-only on the serializer — only the
        approve action may set them."""
        budget = Budget.objects.create(organisation=self.org, name="Guard", fiscal_year=2026)
        other_user = _make_user("fields_other@example.com")
        res = self.client.patch(f"/api/v1/budgets/{budget.id}/", {"approved_by": str(other_user.id)})
        self.assertEqual(res.status_code, 200)
        budget.refresh_from_db()
        self.assertIsNone(budget.approved_by_id)

    def test_add_line_with_account(self):
        budget = Budget.objects.create(organisation=self.org, name="With Account", fiscal_year=2026)
        account = Account.objects.filter(organisation=self.org).first()
        self.assertIsNotNone(account, "COA should be auto-seeded on org creation")
        res = self.client.post(f"/api/v1/budgets/{budget.id}/add_line/", {
            "category_name": "Utilities", "category_type": "expense",
            "budgeted_amount": "50000", "account": str(account.id),
        })
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(str(res.data["account"]), str(account.id))
        self.assertEqual(res.data["account_code"], account.code)

    def test_line_without_account_still_works(self):
        """Existing lines with no account set must keep working — null
        account is not an error."""
        budget = Budget.objects.create(organisation=self.org, name="No Account", fiscal_year=2026)
        res = self.client.post(f"/api/v1/budgets/{budget.id}/add_line/", {
            "category_name": "Misc", "category_type": "expense", "budgeted_amount": "1000",
        })
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertIsNone(res.data["account"])
        variance_res = self.client.get(f"/api/v1/budgets/{budget.id}/variance/")
        self.assertEqual(variance_res.status_code, 200)
        self.assertEqual(Decimal(str(variance_res.data[0]["actual_amount"])), Decimal("0"))


class BudgetMonitoringTests(TestCase):
    def setUp(self):
        self.owner = _make_user("monitor_owner@example.com")
        self.org = _make_org(self.owner, "Monitor Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.owner, self.org)

        self.active_op = Budget.objects.create(
            organisation=self.org, name="Active Ops", fiscal_year=2026,
            status=Budget.ACTIVE, budget_type=Budget.OPERATIONAL,
        )
        self.active_cap = Budget.objects.create(
            organisation=self.org, name="Active Capex", fiscal_year=2026,
            status=Budget.ACTIVE, budget_type=Budget.CAPITAL,
        )
        self.draft_budget = Budget.objects.create(
            organisation=self.org, name="Draft Budget", fiscal_year=2026,
            status=Budget.DRAFT, budget_type=Budget.OPERATIONAL,
        )
        for b in (self.active_op, self.active_cap, self.draft_budget):
            BudgetLine.objects.create(
                organisation=self.org, budget=b, category_name="Rent",
                category_type="expense", budgeted_amount=Decimal("10000"),
            )

    def test_monitoring_defaults_to_active_only(self):
        res = self.client.get("/api/v1/budgets/monitoring/")
        self.assertEqual(res.status_code, 200)
        budget_ids = {row["budget_id"] for row in res.data}
        self.assertIn(str(self.active_op.id), budget_ids)
        self.assertIn(str(self.active_cap.id), budget_ids)
        self.assertNotIn(str(self.draft_budget.id), budget_ids)

    def test_monitoring_status_all_includes_draft(self):
        res = self.client.get("/api/v1/budgets/monitoring/", {"status": "all"})
        self.assertEqual(res.status_code, 200)
        budget_ids = {row["budget_id"] for row in res.data}
        self.assertIn(str(self.draft_budget.id), budget_ids)

    def test_monitoring_budget_type_filter(self):
        res = self.client.get("/api/v1/budgets/monitoring/", {"budget_type": "capital"})
        self.assertEqual(res.status_code, 200)
        budget_ids = {row["budget_id"] for row in res.data}
        self.assertIn(str(self.active_cap.id), budget_ids)
        self.assertNotIn(str(self.active_op.id), budget_ids)

    def test_monitoring_row_shape(self):
        res = self.client.get("/api/v1/budgets/monitoring/", {"budget_type": "operational"})
        self.assertEqual(res.status_code, 200)
        row = next(r for r in res.data if r["budget_id"] == str(self.active_op.id))
        for key in [
            'id', 'budget_id', 'budget_name', 'budget_type', 'category_name',
            'category_type', 'period_month', 'budgeted_amount', 'actual_amount',
            'variance', 'over_budget', 'account',
        ]:
            self.assertIn(key, row)
        self.assertEqual(row['budget_name'], 'Active Ops')
        self.assertIsNone(row['account'])


class BudgetVarianceLinkFixTests(TestCase):
    """Regression coverage for the known bug: get_variance_report used to
    match purely on category name + fiscal year, ignoring Expense.budget
    entirely. An expense explicitly linked to Budget A would leak into
    Budget B's variance whenever both budgets had a line with the same
    category name. This would have failed under the old logic."""

    def setUp(self):
        self.owner = _make_user("link_owner@example.com")
        self.org = _make_org(self.owner, "Link Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.owner, self.org)

        self.category = ExpenseCategory.objects.create(organisation=self.org, name="Utilities")

        self.budget_a = Budget.objects.create(organisation=self.org, name="Budget A", fiscal_year=2026)
        self.budget_b = Budget.objects.create(organisation=self.org, name="Budget B", fiscal_year=2026)
        self.line_a = BudgetLine.objects.create(
            organisation=self.org, budget=self.budget_a, category=self.category,
            category_name="Utilities", category_type="expense", budgeted_amount=Decimal("20000"),
        )
        self.line_b = BudgetLine.objects.create(
            organisation=self.org, budget=self.budget_b, category=self.category,
            category_name="Utilities", category_type="expense", budgeted_amount=Decimal("20000"),
        )

    def _make_expense(self, amount, budget=None):
        return Expense.objects.create(
            organisation=self.org, category=self.category, amount=Decimal(amount),
            description="NEPA bill", expense_date=timezone.datetime(2026, 3, 10).date(),
            recorded_by=self.owner, budget=budget,
        )

    def test_expense_linked_to_budget_a_only_counts_for_a(self):
        self._make_expense("15000", budget=self.budget_a)

        report_a = BudgetService.get_variance_report(self.budget_a)
        report_b = BudgetService.get_variance_report(self.budget_b)

        self.assertEqual(Decimal(str(report_a[0]["actual_amount"])), Decimal("15000"))
        # The old logic (category + fiscal year only, no budget filter) would
        # have matched this expense into Budget B's report too — it must not.
        self.assertEqual(Decimal(str(report_b[0]["actual_amount"])), Decimal("0"))

    def test_unlinked_expense_falls_back_to_category_match_for_both(self):
        """An expense nobody has explicitly tagged to a budget keeps today's
        behaviour: matched by category name/fiscal year against every budget
        line that shares the category — this is the pre-existing fallback,
        not a new bug."""
        self._make_expense("5000", budget=None)

        report_a = BudgetService.get_variance_report(self.budget_a)
        report_b = BudgetService.get_variance_report(self.budget_b)

        self.assertEqual(Decimal(str(report_a[0]["actual_amount"])), Decimal("5000"))
        self.assertEqual(Decimal(str(report_b[0]["actual_amount"])), Decimal("5000"))

    def test_monitoring_endpoint_respects_the_same_fix(self):
        """The monitoring endpoint must be consistent with get_variance_report."""
        self.budget_a.status = Budget.ACTIVE
        self.budget_a.save(update_fields=['status'])
        self.budget_b.status = Budget.ACTIVE
        self.budget_b.save(update_fields=['status'])
        self._make_expense("15000", budget=self.budget_a)

        res = self.client.get("/api/v1/budgets/monitoring/")
        self.assertEqual(res.status_code, 200)
        row_a = next(r for r in res.data if r["budget_id"] == str(self.budget_a.id))
        row_b = next(r for r in res.data if r["budget_id"] == str(self.budget_b.id))
        self.assertEqual(Decimal(str(row_a["actual_amount"])), Decimal("15000"))
        self.assertEqual(Decimal(str(row_b["actual_amount"])), Decimal("0"))

    def test_expense_linked_to_a_via_api_shows_in_a_monitoring_row(self):
        """End-to-end regression matching the spec's E2E scenario: create an
        expense through the API with budget=budget_a set (the same field the
        Expenses page 'Link to Budget' dropdown writes), and confirm it shows
        up correctly in Budget A's monitoring row."""
        self.budget_a.status = Budget.ACTIVE
        self.budget_a.save(update_fields=['status'])
        res = self.client.post("/api/v1/expenses/", {
            "category_label": "Utilities", "amount": "8000", "is_income": False,
            "description": "Water bill", "expense_date": "2026-03-15",
            "budget": str(self.budget_a.id),
        })
        self.assertEqual(res.status_code, 201, msg=str(res.data))

        mon_res = self.client.get("/api/v1/budgets/monitoring/")
        row_a = next(r for r in mon_res.data if r["budget_id"] == str(self.budget_a.id))
        self.assertEqual(Decimal(str(row_a["actual_amount"])), Decimal("8000"))


class BudgetLineGLAccountActualTests(TestCase):
    """Phase 2: when a BudgetLine.account is set, Actual is computed from
    real posted JournalLine data for that account — not a category-name
    guess. This is what makes the Phase 1 account link more than cosmetic."""

    def setUp(self):
        self.owner = _make_user("gl_owner@example.com")
        self.org = _make_org(self.owner, "GL Actual Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.owner, self.org)
        self.utilities = Account.objects.get(organisation=self.org, code="6200")
        self.cash = Account.objects.get(organisation=self.org, code="1001")

    def _post_je(self, amount, entry_date, debit_account, credit_account=None):
        zero = Decimal("0")
        credit_account = credit_account or self.cash
        return AccountingService.post_journal_entry(
            self.org, "Test JE", entry_date,
            [(debit_account, Decimal(amount), zero), (credit_account, zero, Decimal(amount))],
            self.owner,
        )

    def test_actual_computed_from_posted_journal_lines(self):
        budget = Budget.objects.create(
            organisation=self.org, name="GL Budget", fiscal_year=2026, status=Budget.ACTIVE,
        )
        line = BudgetLine.objects.create(
            organisation=self.org, budget=budget, category_name="Utilities",
            category_type="expense", budgeted_amount=Decimal("20000"), account=self.utilities,
        )
        self._post_je("8000", timezone.datetime(2026, 3, 5).date(), self.utilities)
        self._post_je("4500", timezone.datetime(2026, 3, 20).date(), self.utilities)

        actual = BudgetService._actual_for_line(line, budget, self.org)
        self.assertEqual(actual, Decimal("12500"))

    def test_actual_respects_period_month_filter(self):
        budget = Budget.objects.create(
            organisation=self.org, name="GL Monthly Budget", fiscal_year=2026, status=Budget.ACTIVE,
        )
        line = BudgetLine.objects.create(
            organisation=self.org, budget=budget, category_name="Utilities",
            category_type="expense", period_month=3,
            budgeted_amount=Decimal("10000"), account=self.utilities,
        )
        self._post_je("8000", timezone.datetime(2026, 3, 5).date(), self.utilities)   # in period
        self._post_je("9000", timezone.datetime(2026, 4, 5).date(), self.utilities)   # different month

        actual = BudgetService._actual_for_line(line, budget, self.org)
        self.assertEqual(actual, Decimal("8000"))

    def test_actual_ignores_entries_outside_fiscal_year(self):
        budget = Budget.objects.create(
            organisation=self.org, name="GL FY Budget", fiscal_year=2026, status=Budget.ACTIVE,
        )
        line = BudgetLine.objects.create(
            organisation=self.org, budget=budget, category_name="Utilities",
            category_type="expense", budgeted_amount=Decimal("10000"), account=self.utilities,
        )
        self._post_je("3000", timezone.datetime(2026, 6, 1).date(), self.utilities)
        self._post_je("6000", timezone.datetime(2025, 12, 31).date(), self.utilities)  # prior year

        actual = BudgetService._actual_for_line(line, budget, self.org)
        self.assertEqual(actual, Decimal("3000"))

    def test_credit_normal_account_nets_correctly(self):
        """A revenue (credit-normal) account's Actual = credits - debits, the
        mirror image of the debit-normal expense case."""
        revenue = Account.objects.get(organisation=self.org, code="4001")
        budget = Budget.objects.create(
            organisation=self.org, name="Revenue Budget", fiscal_year=2026, status=Budget.ACTIVE,
        )
        line = BudgetLine.objects.create(
            organisation=self.org, budget=budget, category_name="Sales",
            category_type="revenue", budgeted_amount=Decimal("50000"), account=revenue,
        )
        self._post_je("15000", timezone.datetime(2026, 3, 1).date(), self.cash, credit_account=revenue)

        actual = BudgetService._actual_for_line(line, budget, self.org)
        self.assertEqual(actual, Decimal("15000"))

    def test_line_without_account_ignores_raw_gl_activity(self):
        """A BudgetLine with no account link must ignore raw GL postings on
        that account entirely and keep using the Phase 1 category-match path
        — confirms the two branches are properly gated on line.account_id."""
        budget = Budget.objects.create(
            organisation=self.org, name="No Account Budget", fiscal_year=2026, status=Budget.ACTIVE,
        )
        line = BudgetLine.objects.create(
            organisation=self.org, budget=budget, category_name="Utilities",
            category_type="expense", budgeted_amount=Decimal("10000"),
        )
        self._post_je("9999", timezone.datetime(2026, 3, 5).date(), self.utilities)
        actual = BudgetService._actual_for_line(line, budget, self.org)
        self.assertEqual(actual, Decimal("0"))

    def test_end_to_end_expense_in_mapped_category_reflects_in_monitoring(self):
        """Full Phase 2 chain: category mapped to a GL account -> expense
        posts to that account -> a BudgetLine pointing at the same account
        shows the real posted amount via the /monitoring/ endpoint."""
        category = ExpenseCategory.objects.create(
            organisation=self.org, name="Utilities E2E", account=self.utilities,
        )
        budget = Budget.objects.create(
            organisation=self.org, name="E2E Budget", fiscal_year=2026, status=Budget.ACTIVE,
        )
        line = BudgetLine.objects.create(
            organisation=self.org, budget=budget, category=category, category_name="Utilities E2E",
            category_type="expense", budgeted_amount=Decimal("20000"), account=self.utilities,
        )
        res = self.client.post("/api/v1/expenses/", {
            "category_label": "Utilities E2E", "amount": "6500", "is_income": False,
            "description": "Water + electricity", "expense_date": "2026-03-12", "payment_method": "cash",
        })
        self.assertEqual(res.status_code, 201, msg=str(res.data))

        mon_res = self.client.get("/api/v1/budgets/monitoring/")
        self.assertEqual(mon_res.status_code, 200)
        row = next(r for r in mon_res.data if r["id"] == str(line.id))
        self.assertEqual(Decimal(str(row["actual_amount"])), Decimal("6500"))


class BudgetLineAccountTenantIsolationTests(TestCase):
    """Regression coverage for the IDOR closed alongside Phase 2: since
    _actual_for_line now queries real JournalLine data for line.account,
    a foreign-org Account PK slipped into add_line would leak that org's GL
    activity into this org's Budget Monitoring page. Must be rejected."""

    def setUp(self):
        self.owner = _make_user("iso_owner@example.com")
        self.org = _make_org(self.owner, "Iso Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.owner, self.org)
        self.other_owner = _make_user("iso_other_owner@example.com")
        self.other_org = _make_org(self.other_owner, "Iso Other Org")

    def test_add_line_rejects_foreign_org_account(self):
        budget = Budget.objects.create(organisation=self.org, name="Iso Budget", fiscal_year=2026)
        foreign_account = Account.objects.get(organisation=self.other_org, code="6200")
        res = self.client.post(f"/api/v1/budgets/{budget.id}/add_line/", {
            "category_name": "Utilities", "category_type": "expense",
            "budgeted_amount": "5000", "account": str(foreign_account.id),
        })
        self.assertEqual(res.status_code, 400, msg=str(res.data))
        self.assertEqual(budget.lines.count(), 0)
