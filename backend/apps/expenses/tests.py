"""Tests for the expenses app Phase 2 budgeting upgrade: ExpenseCategory ->
GL account link, and its wiring into post_expense_journal
(apps.accounting.services). See apps/budgets/tests.py for the corresponding
BudgetService._actual_for_line coverage."""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.models import Account
from apps.accounting.services import AccountingService, AccountMappingService
from apps.authentication.models import User
from apps.expenses.models import Expense, ExpenseCategory
from apps.subscriptions.models import Plan
from apps.subscriptions.services import SubscriptionService
from apps.tenancy.services import OrganisationService


def _make_user(email="exp_owner@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Exp", last_name="Owner", is_verified=True,
    )


def _make_org(user, name="Exp Org"):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _upgrade_to_business(org):
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


class ExpenseCategoryAccountFieldTests(TestCase):
    """Serializer round-trip + tenant isolation for ExpenseCategory.account."""

    def setUp(self):
        self.owner = _make_user("cat_owner@example.com")
        self.org = _make_org(self.owner, "Cat Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.owner, self.org)
        self.category = ExpenseCategory.objects.create(organisation=self.org, name="Utilities")

    def test_map_category_to_own_org_account(self):
        account = Account.objects.get(organisation=self.org, code="6200")
        res = self.client.patch(
            f"/api/v1/expenses/categories/{self.category.id}/", {"account": str(account.id)}
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(str(res.data["account"]), str(account.id))
        self.assertEqual(res.data["account_code"], "6200")
        self.category.refresh_from_db()
        self.assertEqual(self.category.account_id, account.id)

    def test_cannot_map_category_to_another_orgs_account(self):
        """Tenant isolation: rejecting a foreign-org Account PK on write is the
        gate that keeps _actual_for_line's real JournalLine query (Phase 2)
        from ever being pointed at another org's ledger."""
        other_owner = _make_user("cat_other_owner@example.com")
        other_org = _make_org(other_owner, "Cat Other Org")
        foreign_account = Account.objects.get(organisation=other_org, code="6200")
        res = self.client.patch(
            f"/api/v1/expenses/categories/{self.category.id}/", {"account": str(foreign_account.id)}
        )
        self.assertEqual(res.status_code, 400, msg=str(res.data))
        self.category.refresh_from_db()
        self.assertIsNone(self.category.account_id)

    def test_account_optional_defaults_null(self):
        res = self.client.post("/api/v1/expenses/categories/", {"name": "Fresh Category"})
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertIsNone(res.data["account"])


class ExpenseJournalAccountRoutingTests(TestCase):
    """post_expense_journal: a category with a mapped GL account routes its
    debit there; an unmapped category keeps posting to
    general_expense_account exactly as before (strict opt-in, zero
    behaviour change by default)."""

    def setUp(self):
        self.owner = _make_user("route_owner@example.com")
        self.org = _make_org(self.owner, "Route Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.owner, self.org)
        self.general_expense = AccountMappingService.resolve(self.org, "general_expense_account")
        self.utilities_account = Account.objects.get(organisation=self.org, code="6200")
        self.assertNotEqual(self.general_expense.id, self.utilities_account.id)

    def _gl_balance(self, account):
        return AccountingService._ledger_balance(account)

    def test_mapped_category_posts_to_its_own_account(self):
        ExpenseCategory.objects.create(
            organisation=self.org, name="Utilities Mapped", account=self.utilities_account,
        )
        res = self.client.post("/api/v1/expenses/", {
            "category_label": "Utilities Mapped", "amount": "12000", "is_income": False,
            "description": "NEPA bill", "expense_date": "2026-03-10", "payment_method": "cash",
        })
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        exp = Expense.objects.get(id=res.data["id"])
        self.assertEqual(exp.gl_post_status, "posted")
        self.assertEqual(self._gl_balance(self.utilities_account), Decimal("12000"))
        self.assertEqual(self._gl_balance(self.general_expense), Decimal("0"))

    def test_unmapped_category_still_posts_to_general_expense_account(self):
        res = self.client.post("/api/v1/expenses/", {
            "category_label": "Random Unmapped Category", "amount": "5000", "is_income": False,
            "description": "Sundry spend", "expense_date": "2026-03-10", "payment_method": "cash",
        })
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        exp = Expense.objects.get(id=res.data["id"])
        self.assertEqual(exp.gl_post_status, "posted")
        self.assertEqual(self._gl_balance(self.general_expense), Decimal("5000"))
        self.assertEqual(self._gl_balance(self.utilities_account), Decimal("0"))

    def test_income_category_account_link_is_ignored(self):
        """category.account is only consulted on the expense branch — income
        postings (DR Cash / CR revenue) are untouched by this change."""
        revenue_account = AccountMappingService.resolve(self.org, "revenue_account")
        ExpenseCategory.objects.create(
            organisation=self.org, name="Freelance Income", is_income=True,
            account=self.utilities_account,
        )
        res = self.client.post("/api/v1/expenses/", {
            "category_label": "Freelance Income", "amount": "7000", "is_income": True,
            "description": "Side gig", "expense_date": "2026-03-10", "payment_method": "cash",
        })
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(self._gl_balance(revenue_account), Decimal("7000"))
        self.assertEqual(self._gl_balance(self.utilities_account), Decimal("0"))

    def test_bank_payment_method_still_credits_bank_not_cash(self):
        """Regression guard: the payment-method branching (bank/cheque/card
        vs cash) must be byte-for-byte unchanged by the account-routing edit —
        only the DEBIT side's account selection changed."""
        bank_account = AccountMappingService.resolve(self.org, "bank_account")
        cash_account = AccountMappingService.resolve(self.org, "cash_account")
        ExpenseCategory.objects.create(
            organisation=self.org, name="Utilities Bank Pay", account=self.utilities_account,
        )
        res = self.client.post("/api/v1/expenses/", {
            "category_label": "Utilities Bank Pay", "amount": "3000", "is_income": False,
            "description": "Bank-paid bill", "expense_date": "2026-03-10", "payment_method": "bank",
        })
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(self._gl_balance(self.utilities_account), Decimal("3000"))
        self.assertEqual(self._gl_balance(bank_account), Decimal("-3000"))
        self.assertEqual(self._gl_balance(cash_account), Decimal("0"))
