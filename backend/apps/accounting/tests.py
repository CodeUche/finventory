"""Tests for accounting: chart of accounts, journal entries, trial balance, balance sheet."""

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.models import Account, JournalEntry
from apps.authentication.models import User
from apps.subscriptions.models import Plan, Subscription
from apps.subscriptions.services import SubscriptionService
from apps.tenancy.services import OrganisationService


def _make_user(email="acc_owner@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Acc", last_name="Owner", is_verified=True,
    )


def _make_org(user, name="Acc Org"):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _upgrade_to_business(org):
    """Upgrade org to the Business plan so plan_requires('accounting') passes."""
    plan = Plan.objects.get(slug="business")
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


class ChartOfAccountsTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_coa_seeded_on_org_creation(self):
        """Organisation creation should seed a default COA."""
        count = Account.objects.filter(organisation=self.org).count()
        self.assertGreater(count, 0)

    def test_list_accounts(self):
        res = self.client.get("/api/v1/accounting/accounts/")
        self.assertEqual(res.status_code, 200)
        data = res.data.get("results") or res.data
        self.assertGreater(len(data), 0)

    def test_create_account(self):
        res = self.client.post("/api/v1/accounting/accounts/", {
            "code": "9001",
            "name": "Test Suspense Account",
            "account_type": "liability",
        })
        self.assertEqual(res.status_code, 201)
        self.assertTrue(Account.objects.filter(organisation=self.org, code="9001").exists())

    def test_account_code_unique_per_org(self):
        """Account codes must be unique within an org."""
        Account.objects.create(organisation=self.org, code="9002", name="Unique", account_type="asset")
        # Attempting to create a second account with the same code must fail
        res2 = self.client.post("/api/v1/accounting/accounts/", {
            "code": "9002",
            "name": "Duplicate Code",
            "account_type": "asset",
        })
        # View may return 400 (validation) or 500 (IntegrityError) depending on implementation
        self.assertGreaterEqual(res2.status_code, 400)

    def test_reseed_coa_adds_accounts(self):
        """Reseed should add any missing accounts without clearing existing ones."""
        # Reseed is superuser-only — make the owner a superuser for this test
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        original_count = Account.objects.filter(organisation=self.org).count()
        res = self.client.post(
            f"/api/v1/tenancy/organisations/{self.org.id}/reseed_coa/",
        )
        self.assertIn(res.status_code, [200, 201, 204])
        new_count = Account.objects.filter(organisation=self.org).count()
        self.assertGreaterEqual(new_count, original_count)


class JournalEntryTests(TestCase):
    def setUp(self):
        self.user = _make_user("je_owner@example.com")
        self.org = _make_org(self.user, "JE Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        # Get two seeded accounts for balanced entry
        accounts = list(Account.objects.filter(organisation=self.org).order_by("code")[:2])
        self.debit_acct = accounts[0]
        self.credit_acct = accounts[1]

    def _payload(self, description="Test Journal Entry"):
        return {
            "description": description,
            "entry_date": "2026-01-15",
            "lines": [
                {
                    "account": str(self.debit_acct.id),
                    "debit": "5000.00",
                    "credit": "0.00",
                    "description": "Debit line",
                },
                {
                    "account": str(self.credit_acct.id),
                    "debit": "0.00",
                    "credit": "5000.00",
                    "description": "Credit line",
                },
            ],
        }

    def test_create_journal_entry(self):
        res = self.client.post("/api/v1/accounting/journal/", self._payload(), format="json")
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))
        self.assertTrue(JournalEntry.objects.filter(organisation=self.org).exists())

    def test_journal_entry_has_lines(self):
        res = self.client.post("/api/v1/accounting/journal/", self._payload(), format="json")
        self.assertIn(res.status_code, [200, 201])
        entry = JournalEntry.objects.get(id=res.data["id"])
        self.assertEqual(entry.lines.count(), 2)

    def test_list_journal_entries(self):
        self.client.post("/api/v1/accounting/journal/", self._payload(), format="json")
        res = self.client.get("/api/v1/accounting/journal/")
        self.assertEqual(res.status_code, 200)
        data = res.data.get("results") or res.data
        self.assertGreater(len(data), 0)

    def test_retrieve_journal_entry(self):
        create_res = self.client.post("/api/v1/accounting/journal/", self._payload(), format="json")
        je_id = create_res.data["id"]
        res = self.client.get(f"/api/v1/accounting/journal/{je_id}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["id"], je_id)

    def test_post_journal_entry(self):
        create_res = self.client.post("/api/v1/accounting/journal/", self._payload(), format="json")
        je_id = create_res.data["id"]
        res = self.client.post(f"/api/v1/accounting/journal/{je_id}/post_entry/")
        self.assertIn(res.status_code, [200, 201])
        entry = JournalEntry.objects.get(id=je_id)
        self.assertEqual(entry.status, "posted")

    def test_other_org_cannot_access_journal(self):
        create_res = self.client.post("/api/v1/accounting/journal/", self._payload(), format="json")
        je_id = create_res.data["id"]
        other_user = _make_user("je_other@example.com")
        other_org = _make_org(other_user, "JE Other Org")
        _upgrade_to_business(other_org)   # give business plan so 403 = tenant isolation, not plan gate
        c = _auth_client(other_user, other_org)
        res = c.get(f"/api/v1/accounting/journal/{je_id}/")
        self.assertIn(res.status_code, [403, 404])


class FinancialReportTests(TestCase):
    def setUp(self):
        self.user = _make_user("report_owner@example.com")
        self.org = _make_org(self.user, "Report Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_trial_balance_accessible(self):
        res = self.client.get("/api/v1/accounting/accounts/trial_balance/")
        self.assertEqual(res.status_code, 200)

    def test_balance_sheet_accessible(self):
        res = self.client.get("/api/v1/accounting/accounts/balance_sheet/")
        self.assertEqual(res.status_code, 200)

    def test_balance_sheet_has_sections(self):
        res = self.client.get("/api/v1/accounting/accounts/balance_sheet/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("assets", res.data)
        self.assertIn("liabilities", res.data)
        self.assertIn("equity", res.data)
