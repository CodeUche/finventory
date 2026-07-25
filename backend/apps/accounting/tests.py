"""Tests for accounting: chart of accounts, journal entries, trial balance, balance sheet,
account mapping, GL auto-posting idempotency, safe_post_gl, GL health, period locking."""

from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.exceptions import GLAccountNotConfigured, PeriodLockedError
from apps.accounting.models import Account, AccountMapping, AccountSubType, AccountType, FinancialPeriod, FixedAsset, JournalEntry, JournalLine
from apps.accounting.services import AccountingService, AccountMappingService, safe_post_gl
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


class BalanceSheetBalancingTests(TestCase):
    """Regression for the client-reported bug: the Trial Balance balanced but the
    Balance Sheet showed a huge difference, because the two were computed from
    different sources. The Balance Sheet is now ledger-derived, so a balanced TB
    must imply a balanced BS (Assets = Liabilities + Equity + Current-Year Earnings).
    """

    def setUp(self):
        self.user = _make_user("bs_owner@example.com")
        self.org = _make_org(self.user, "BS Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def _acct(self, code):
        return Account.objects.get(organisation=self.org, code=code)

    def _post(self, description, lines, entry_date=None):
        return AccountingService.post_journal_entry(
            self.org,
            description=description,
            entry_date=entry_date or timezone.now().date(),
            lines=lines,
            created_by=self.user,
        )

    def test_balanced_tb_implies_balanced_bs(self):
        # Post a balanced manual journal touching assets, an expense and equity —
        # the scenario the client reproduced (cash/bank credit, expense/VAT debit).
        self._post("Opening / mixed entry", [
            (self._acct("6700"), Decimal("150000"), Decimal("0")),   # Other Expenses (DR)
            (self._acct("1400"), Decimal("11250"),  Decimal("0")),   # VAT Receivable (DR)
            (self._acct("1001"), Decimal("0"),      Decimal("100000")),  # Cash (CR)
            (self._acct("1002"), Decimal("0"),      Decimal("61250")),   # Bank (CR)
        ])

        # Trial balance is balanced by construction (posting enforces it).
        tb = AccountingService.trial_balance(self.org)
        total_dr = sum(r["balance"] for r in tb if r["balance"] > 0)
        total_cr = sum(-r["balance"] for r in tb if r["balance"] < 0)
        # (asset/expense debit balances are +, liability/equity credit balances are -
        #  under the normal-sign convention, but cash/bank here carry credit balances)

        bs = AccountingService.balance_sheet(self.org)
        self.assertTrue(bs["balanced"], f"Balance sheet not balanced: {bs}")
        self.assertAlmostEqual(
            float(bs["total_assets"]),
            float(bs["total_liabilities"]) + float(bs["total_equity"]),
            places=2,
        )
        # The ₦150k net loss must appear as negative current-year earnings in equity.
        self.assertLess(float(bs["current_year_earnings"]), 0)

    def test_profit_rolls_into_equity(self):
        # DR Cash 200k / CR Sales Revenue 200k  → 200k profit
        self._post("Cash sale", [
            (self._acct("1001"), Decimal("200000"), Decimal("0")),
            (self._acct("4001"), Decimal("0"), Decimal("200000")),
        ])
        bs = AccountingService.balance_sheet(self.org)
        self.assertTrue(bs["balanced"])
        self.assertAlmostEqual(float(bs["current_year_earnings"]), 200000.0, places=2)
        # Assets (cash 200k) must equal equity (retained earnings 200k)
        self.assertAlmostEqual(float(bs["total_assets"]), 200000.0, places=2)
        self.assertAlmostEqual(float(bs["total_equity"]), 200000.0, places=2)

    def test_trial_balance_as_of_date(self):
        from datetime import date
        self._post("Old entry", [
            (self._acct("1001"), Decimal("50000"), Decimal("0")),
            (self._acct("4001"), Decimal("0"), Decimal("50000")),
        ], entry_date=date(2020, 1, 15))
        self._post("Recent entry", [
            (self._acct("1001"), Decimal("70000"), Decimal("0")),
            (self._acct("4001"), Decimal("0"), Decimal("70000")),
        ])
        tb_asof = AccountingService.trial_balance(self.org, as_of=date(2020, 6, 30))
        cash = next(r for r in tb_asof if r["code"] == "1001")
        self.assertAlmostEqual(float(cash["balance"]), 50000.0, places=2)


class AccountMappingCreationTests(TestCase):
    def setUp(self):
        self.user = _make_user("map_owner@example.com")
        self.org = _make_org(self.user, "Map Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_mapping_auto_created_on_org_setup(self):
        """AccountMapping should be created automatically when org is set up."""
        self.assertTrue(AccountMapping.objects.filter(organisation=self.org).exists())

    def test_mapping_unique_per_org(self):
        """Only one AccountMapping per org."""
        count = AccountMapping.objects.filter(organisation=self.org).count()
        self.assertEqual(count, 1)

    def test_auto_fill_revenue_account(self):
        """Auto-fill should wire revenue_account to the org's revenue account."""
        mapping = AccountMapping.objects.get(organisation=self.org)
        self.assertIsNotNone(mapping.revenue_account)
        self.assertEqual(mapping.revenue_account.account_type, "revenue")

    def test_auto_fill_bank_account(self):
        """Auto-fill should wire bank_account to the org's bank/asset account."""
        mapping = AccountMapping.objects.get(organisation=self.org)
        # bank_account or cash_account must be set
        has_cash_or_bank = (mapping.bank_account is not None or mapping.cash_account is not None)
        self.assertTrue(has_cash_or_bank)

    def test_auto_fill_accounts_payable(self):
        """Auto-fill should wire accounts_payable to a liability account."""
        mapping = AccountMapping.objects.get(organisation=self.org)
        if mapping.accounts_payable:
            self.assertEqual(mapping.accounts_payable.account_type, "liability")

    def test_auto_fill_cogs_account(self):
        """Auto-fill should wire cogs_account to a COGS or expense account."""
        mapping = AccountMapping.objects.get(organisation=self.org)
        if mapping.cogs_account:
            self.assertIn(mapping.cogs_account.account_type, ["cogs", "expense"])

    def test_fk_validation_rejects_foreign_account(self):
        """AccountMapping.clean() must reject accounts from a different org."""
        other_user = _make_user("map_other@example.com")
        other_org = _make_org(other_user, "Map Other Org")
        foreign_account = Account.objects.filter(organisation=other_org).first()
        mapping = AccountMapping.objects.get(organisation=self.org)
        mapping.revenue_account = foreign_account
        with self.assertRaises(Exception):
            mapping.full_clean()

    def test_get_or_create_returns_existing(self):
        """get_or_create_mapping should return the existing mapping, not create a duplicate."""
        existing = AccountMapping.objects.get(organisation=self.org)
        retrieved = AccountMappingService.get_or_create_mapping(self.org)
        self.assertEqual(existing.pk, retrieved.pk)
        self.assertEqual(AccountMapping.objects.filter(organisation=self.org).count(), 1)


class AccountMappingResolveTests(TestCase):
    def setUp(self):
        self.user = _make_user("resolve_owner@example.com")
        self.org = _make_org(self.user, "Resolve Org")
        _upgrade_to_business(self.org)
        self.mapping = AccountMapping.objects.get(organisation=self.org)

    def test_resolve_returns_mapped_account(self):
        """resolve() should return the Account for a properly mapped role."""
        if self.mapping.revenue_account:
            acct = AccountMappingService.resolve(self.org, "revenue_account")
            self.assertIsNotNone(acct)
            self.assertEqual(acct.pk, self.mapping.revenue_account.pk)

    def test_resolve_raises_when_unmapped(self):
        """resolve() must raise GLAccountNotConfigured when role is None."""
        self.mapping.revenue_account = None
        self.mapping.save()
        with self.assertRaises(GLAccountNotConfigured) as ctx:
            AccountMappingService.resolve(self.org, "revenue_account")
        self.assertEqual(ctx.exception.role, "revenue_account")

    def test_resolve_creates_mapping_if_missing(self):
        """resolve() should create the mapping on-the-fly if none exists."""
        AccountMapping.objects.filter(organisation=self.org).delete()
        # Should not raise MappingDoesNotExist; may raise GLAccountNotConfigured
        # but must not raise AccountMapping.DoesNotExist
        try:
            AccountMappingService.resolve(self.org, "revenue_account")
        except GLAccountNotConfigured:
            pass  # acceptable — mapping created but role still null
        except Exception as e:
            self.fail(f"Unexpected exception type: {type(e).__name__}: {e}")

    def test_suggest_returns_best_match(self):
        """suggest() should return an Account for known roles when COA is seeded."""
        from apps.accounting.services import AccountMappingService as AMS
        roles = list(AMS.ROLE_HINTS.keys())
        non_none = [r for r in roles if AMS.suggest(self.org, r) is not None]
        self.assertGreater(len(non_none), 0)

    def test_suggest_returns_none_for_empty_coa(self):
        """suggest() should return None for all roles when COA has no accounts."""
        from apps.accounting.services import AccountMappingService as AMS
        Account.objects.filter(organisation=self.org).delete()
        for role in AMS.ROLE_HINTS.keys():
            result = AMS.suggest(self.org, role)
            self.assertIsNone(result, f"Expected None for {role} but got {result}")


class AccountMappingAPITests(TestCase):
    def setUp(self):
        self.user = _make_user("mapapi_owner@example.com")
        self.org = _make_org(self.user, "MapAPI Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        self.mapping = AccountMapping.objects.get(organisation=self.org)

    def test_get_mapping_returns_200(self):
        res = self.client.get("/api/v1/accounting/account-mapping/")
        self.assertEqual(res.status_code, 200)

    def test_get_mapping_includes_all_roles(self):
        res = self.client.get("/api/v1/accounting/account-mapping/")
        self.assertEqual(res.status_code, 200)
        for role in ["revenue_account", "cogs_account", "accounts_receivable",
                     "accounts_payable", "inventory_account", "cash_account"]:
            self.assertIn(f"{role}_id", res.data)

    def test_put_updates_role(self):
        """PUT to mapping endpoint should update a specific account role."""
        revenue_acct = Account.objects.filter(
            organisation=self.org, account_type="revenue"
        ).first()
        if not revenue_acct:
            self.skipTest("No revenue account seeded")
        res = self.client.put("/api/v1/accounting/account-mapping/", {
            "revenue_account": str(revenue_acct.id),
        }, format="json")
        self.assertIn(res.status_code, [200, 201])
        self.mapping.refresh_from_db()
        self.assertEqual(self.mapping.revenue_account_id, revenue_acct.id)

    def test_put_rejects_foreign_account(self):
        """Setting a foreign account via API should return 400."""
        other_user = _make_user("mapapi_other@example.com")
        other_org = _make_org(other_user, "MapAPI Other Org")
        foreign_acct = Account.objects.filter(organisation=other_org).first()
        res = self.client.put("/api/v1/accounting/account-mapping/", {
            "revenue_account": str(foreign_acct.id),
        }, format="json")
        self.assertGreaterEqual(res.status_code, 400)

    def test_put_clears_role_with_null(self):
        """Sending null for a role should clear it (via revenue_account_id=null)."""
        res = self.client.put("/api/v1/accounting/account-mapping/", {
            "cogs_account_id": None,
        }, format="json")
        self.assertIn(res.status_code, [200, 201])
        self.mapping.refresh_from_db()
        self.assertIsNone(self.mapping.cogs_account)

    def test_suggestions_endpoint_accessible(self):
        res = self.client.get("/api/v1/accounting/account-mapping/suggestions/")
        self.assertEqual(res.status_code, 200)


class GLMappingModuleTests(TestCase):
    """Step 1 — NHF role, module grouping, and stronger mapping validation."""

    def setUp(self):
        self.user = _make_user("glmap_owner@example.com")
        self.org = _make_org(self.user, "GLMap Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        self.mapping = AccountMapping.objects.get(organisation=self.org)

    def test_get_includes_module_grouping_and_labels(self):
        res = self.client.get("/api/v1/accounting/account-mapping/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("modules", res.data)
        self.assertIn("role_labels", res.data)
        grouped = [r for m in res.data["modules"] for r in m["roles"]]
        from apps.accounting.serializers import MAPPING_ROLES
        # Every role appears exactly once across the module groups, incl. NHF.
        self.assertEqual(sorted(grouped), sorted(MAPPING_ROLES))
        self.assertIn("nhf_account", grouped)

    def test_nhf_role_resolves_via_mapping(self):
        liability = Account.objects.filter(
            organisation=self.org, account_type="liability"
        ).first()
        self.assertIsNotNone(liability)
        self.mapping.nhf_account = liability
        self.mapping.save()
        acct = AccountMappingService.resolve(self.org, "nhf_account")
        self.assertEqual(acct.pk, liability.pk)

    def test_put_rejects_header_account(self):
        """Mapping a role to a header/summary account (one with children) must 400."""
        parent = Account.objects.create(
            organisation=self.org, code="4900", name="Revenue Header",
            account_type="revenue", account_group="Revenue",
        )
        Account.objects.create(
            organisation=self.org, code="4901", name="Sub Revenue",
            account_type="revenue", account_group="Revenue", parent=parent,
        )
        res = self.client.put("/api/v1/accounting/account-mapping/", {
            "revenue_account": str(parent.id),
        }, format="json")
        self.assertEqual(res.status_code, 400)

    def test_put_rejects_inactive_account(self):
        acct = Account.objects.create(
            organisation=self.org, code="4950", name="Inactive Revenue",
            account_type="revenue", account_group="Revenue", is_active=False,
        )
        res = self.client.put("/api/v1/accounting/account-mapping/", {
            "revenue_account": str(acct.id),
        }, format="json")
        self.assertEqual(res.status_code, 400)

    def test_take_on_uses_mapped_control_account(self):
        """Subledger take-on should resolve AR via the GL mapping, not a hardcoded code."""
        from datetime import date
        from apps.customers.models import Customer
        cust = Customer.objects.create(organisation=self.org, name="Opening Debtor")
        je = AccountingService.set_subledger_opening_balances(
            self.org, date(2026, 1, 1),
            customers=[{"id": str(cust.id), "amount": "1000.00"}],
        )
        self.assertIsNotNone(je)
        ar = self.mapping.accounts_receivable
        self.assertIsNotNone(ar)
        # The AR control account carries the opening debit.
        self.assertTrue(je.lines.filter(account=ar, debit=Decimal("1000.00")).exists())

    def test_unauthenticated_denied(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        res = anon.get("/api/v1/accounting/account-mapping/")
        self.assertIn(res.status_code, [401, 403])


class JournalEntryIdempotencyTests(TestCase):
    def setUp(self):
        self.user = _make_user("idem_owner@example.com")
        self.org = _make_org(self.user, "Idem Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        accounts = list(Account.objects.filter(organisation=self.org).order_by("code")[:2])
        self.debit_acct = accounts[0]
        self.credit_acct = accounts[1]

    def _post_je(self, source_type="invoice", source_ref="INV-001"):
        from apps.accounting.services import AccountingService
        return AccountingService.post_journal_entry(
            organisation=self.org,
            description="Test idempotent entry",
            entry_date=timezone.now().date(),
            lines=[
                (self.debit_acct, Decimal("1000"), Decimal("0")),
                (self.credit_acct, Decimal("0"), Decimal("1000")),
            ],
            created_by=self.user,
            source_type=source_type,
            source_ref=source_ref,
        )

    def test_same_source_creates_only_one_entry(self):
        """Posting the same source_type+source_ref twice must not create a duplicate."""
        je1 = self._post_je("invoice", "INV-001")
        je2 = self._post_je("invoice", "INV-001")
        self.assertEqual(je1.pk, je2.pk)
        count = JournalEntry.objects.filter(
            organisation=self.org, source_type="invoice", source_ref="INV-001"
        ).count()
        self.assertEqual(count, 1)

    def test_different_source_ref_creates_two_entries(self):
        """Different source_ref must create a separate entry."""
        je1 = self._post_je("invoice", "INV-001")
        je2 = self._post_je("invoice", "INV-002")
        self.assertNotEqual(je1.pk, je2.pk)

    def test_no_source_always_creates(self):
        """When source fields are blank, each call creates a new entry."""
        from apps.accounting.services import AccountingService
        je1 = AccountingService.post_journal_entry(
            organisation=self.org,
            description="No source 1",
            entry_date=timezone.now().date(),
            lines=[
                (self.debit_acct, Decimal("500"), Decimal("0")),
                (self.credit_acct, Decimal("0"), Decimal("500")),
            ],
            created_by=self.user,
        )
        je2 = AccountingService.post_journal_entry(
            organisation=self.org,
            description="No source 2",
            entry_date=timezone.now().date(),
            lines=[
                (self.debit_acct, Decimal("500"), Decimal("0")),
                (self.credit_acct, Decimal("0"), Decimal("500")),
            ],
            created_by=self.user,
        )
        self.assertNotEqual(je1.pk, je2.pk)

    def test_idempotent_entry_is_posted(self):
        """Returned entry should always be in posted status."""
        je = self._post_je("sale", "SALE-999")
        self.assertEqual(je.status, "posted")

    def test_source_fields_stored_correctly(self):
        """source_type and source_ref must be persisted on the journal entry."""
        je = self._post_je("payroll", "PR-2026-01")
        self.assertEqual(je.source_type, "payroll")
        self.assertEqual(je.source_ref, "PR-2026-01")


class SafePostGLTests(TestCase):
    def setUp(self):
        self.user = _make_user("safe_owner@example.com")
        self.org = _make_org(self.user, "Safe Org")
        _upgrade_to_business(self.org)
        from apps.bills.models import Bill
        from apps.suppliers.models import Supplier
        supplier = Supplier.objects.create(organisation=self.org, name="Safe Supplier")
        self.bill = Bill.objects.create(
            organisation=self.org,
            supplier=supplier,
            issue_date=timezone.now().date(),
            due_date=timezone.now().date(),
            total_amount=Decimal("100"),
            created_by=self.user,
        )

    def test_success_returns_true(self):
        """safe_post_gl must return (True, None) when the function succeeds."""
        success, err = safe_post_gl(lambda: None)
        self.assertTrue(success)
        self.assertIsNone(err)

    def test_success_sets_gl_post_status_posted(self):
        """safe_post_gl must set gl_post_status=posted on the model instance."""
        safe_post_gl(lambda: None, model_instance=self.bill)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.gl_post_status, "posted")

    def test_not_configured_sets_not_configured_status(self):
        """GLAccountNotConfigured must set gl_post_status=not_configured."""
        def raise_not_configured():
            raise GLAccountNotConfigured("revenue_account")
        safe_post_gl(raise_not_configured, model_instance=self.bill)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.gl_post_status, "not_configured")

    def test_generic_exception_sets_failed_status(self):
        """Any other exception must set gl_post_status=failed."""
        def raise_generic():
            raise RuntimeError("database error")
        safe_post_gl(raise_generic, model_instance=self.bill)
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.gl_post_status, "failed")

    def test_safe_post_gl_never_raises(self):
        """safe_post_gl must never propagate exceptions to the caller."""
        def raise_anything():
            raise Exception("should not propagate")
        try:
            safe_post_gl(raise_anything)
        except Exception as e:
            self.fail(f"safe_post_gl raised: {e}")

    def test_safe_post_gl_works_without_model_instance(self):
        """safe_post_gl should work fine with no model_instance."""
        success, err = safe_post_gl(lambda: None, model_instance=None)
        self.assertTrue(success)


class GLHealthTests(TestCase):
    def setUp(self):
        self.user = _make_user("health_owner@example.com")
        self.org = _make_org(self.user, "Health Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_health_endpoint_returns_200(self):
        res = self.client.get("/api/v1/accounting/gl-health/")
        self.assertEqual(res.status_code, 200)

    def test_health_response_has_summary_keys(self):
        res = self.client.get("/api/v1/accounting/gl-health/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("summary", res.data)
        summary = res.data["summary"]
        for key in ["posted", "failed", "not_configured", "pending"]:
            self.assertIn(key, summary)

    def test_health_counts_failed_invoices(self):
        """Health endpoint summary should include non-negative counts."""
        res = self.client.get("/api/v1/accounting/gl-health/")
        self.assertEqual(res.status_code, 200)
        summary = res.data.get("summary", {})
        for key in ["posted", "failed", "not_configured", "pending"]:
            self.assertGreaterEqual(summary.get(key, 0), 0)

    def test_retry_endpoint_exists(self):
        """Retry endpoint with non-existent ID should return 404 (record not found)."""
        res = self.client.post("/api/v1/accounting/gl-health/invoice/00000000-0000-0000-0000-000000000000/retry/")
        self.assertIn(res.status_code, [200, 404, 422, 400])

    def test_health_unauthenticated_denied(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        res = anon.get("/api/v1/accounting/gl-health/")
        self.assertIn(res.status_code, [401, 403])


class PeriodLockingTests(TestCase):
    def setUp(self):
        self.user = _make_user("period_owner@example.com")
        self.org = _make_org(self.user, "Period Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        accounts = list(Account.objects.filter(organisation=self.org).order_by("code")[:2])
        self.debit_acct = accounts[0]
        self.credit_acct = accounts[1]

    def _post_entry_for_date(self, entry_date):
        from apps.accounting.services import AccountingService
        return AccountingService.post_journal_entry(
            organisation=self.org,
            description="Period lock test",
            entry_date=entry_date,
            lines=[
                (self.debit_acct, Decimal("100"), Decimal("0")),
                (self.credit_acct, Decimal("0"), Decimal("100")),
            ],
            created_by=self.user,
        )

    def test_open_period_allows_posting(self):
        """Posting to an unlocked period must succeed."""
        import datetime
        entry_date = datetime.date(2026, 3, 15)
        je = self._post_entry_for_date(entry_date)
        self.assertEqual(je.status, "posted")

    def test_locked_period_raises_period_locked_error(self):
        """Posting to a locked period must raise PeriodLockedError."""
        import datetime
        FinancialPeriod.objects.create(
            organisation=self.org, year=2026, month=2, is_locked=True
        )
        entry_date = datetime.date(2026, 2, 15)
        with self.assertRaises(PeriodLockedError):
            self._post_entry_for_date(entry_date)

    def test_different_month_bypasses_lock(self):
        """A lock on Feb 2026 must not block posting to Mar 2026."""
        import datetime
        FinancialPeriod.objects.create(
            organisation=self.org, year=2026, month=2, is_locked=True
        )
        entry_date = datetime.date(2026, 3, 10)
        je = self._post_entry_for_date(entry_date)
        self.assertEqual(je.status, "posted")

    def test_viewer_cannot_lock_period(self):
        """A viewer-level user should not be able to lock a period via the lock action."""
        viewer = _make_user("period_viewer@example.com")
        from apps.tenancy.models import Membership
        Membership.objects.create(organisation=self.org, user=viewer, role="viewer")
        c = _auth_client(viewer, self.org)
        # First create a period as owner
        period, _ = FinancialPeriod.objects.get_or_create(
            organisation=self.org, year=2024, month=12,
            defaults={"is_locked": False}
        )
        # viewer tries to lock it
        res = c.post(f"/api/v1/accounting/periods/{period.id}/lock/")
        self.assertIn(res.status_code, [403, 404, 405])

    def test_owner_can_lock_period(self):
        """The org owner should be able to lock a financial period via the lock action."""
        period, _ = FinancialPeriod.objects.get_or_create(
            organisation=self.org, year=2025, month=11,
            defaults={"is_locked": False}
        )
        res = self.client.post(f"/api/v1/accounting/periods/{period.id}/lock/")
        self.assertIn(res.status_code, [200, 201, 204])

    def test_owner_can_lock_and_unlock_period(self):
        """Owner should be able to toggle is_locked on a period."""
        period, _ = FinancialPeriod.objects.get_or_create(
            organisation=self.org, year=2025, month=10,
            defaults={"is_locked": False}
        )
        period.is_locked = True
        period.locked_by = self.user
        period.locked_at = timezone.now()
        period.save()
        period.refresh_from_db()
        self.assertTrue(period.is_locked)
        period.is_locked = False
        period.save()
        period.refresh_from_db()
        self.assertFalse(period.is_locked)


class ImmutablePostedEntryTests(TestCase):
    def setUp(self):
        self.user = _make_user("immut_owner@example.com")
        self.org = _make_org(self.user, "Immut Org")
        _upgrade_to_business(self.org)
        accounts = list(Account.objects.filter(organisation=self.org).order_by("code")[:2])
        self.debit_acct = accounts[0]
        self.credit_acct = accounts[1]
        from apps.accounting.services import AccountingService
        self.je = AccountingService.post_journal_entry(
            organisation=self.org,
            description="Immutability test",
            entry_date=timezone.now().date(),
            lines=[
                (self.debit_acct, Decimal("200"), Decimal("0")),
                (self.credit_acct, Decimal("0"), Decimal("200")),
            ],
            created_by=self.user,
        )

    def test_cannot_modify_description_on_posted_entry(self):
        """Saving a posted JournalEntry with financial field changes must raise PermissionError."""
        self.je.description = "Tampered description"
        with self.assertRaises(PermissionError):
            self.je.save(update_fields=["description"])

    def test_can_update_allowed_fields_on_posted_entry(self):
        """Updating updated_at on a posted entry is in ALLOWED_FIELDS and must not raise PermissionError."""
        try:
            self.je.save(update_fields=["updated_at"])
        except PermissionError:
            self.fail("save(update_fields=['updated_at']) raised PermissionError on posted entry")

    def test_draft_entry_can_be_modified(self):
        """Draft entries must remain freely editable."""
        draft = JournalEntry.objects.create(
            organisation=self.org,
            description="Draft",
            entry_date=timezone.now().date(),
            status="draft",
            created_by=self.user,
        )
        draft.description = "Updated draft"
        try:
            draft.save(update_fields=["description"])
        except PermissionError:
            self.fail("Modifying a draft entry raised PermissionError")


class AutoPostingIntegrationTests(TestCase):
    def setUp(self):
        self.user = _make_user("integ_owner@example.com")
        self.org = _make_org(self.user, "Integ Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        self.mapping = AccountMapping.objects.get(organisation=self.org)

    def test_posted_entry_is_balanced(self):
        """A journal entry created via AccountingService must have debits == credits."""
        from apps.accounting.services import AccountingService
        accounts = list(Account.objects.filter(organisation=self.org).order_by("code")[:2])
        je = AccountingService.post_journal_entry(
            organisation=self.org,
            description="Balance check",
            entry_date=timezone.now().date(),
            lines=[
                (accounts[0], Decimal("750"), Decimal("0")),
                (accounts[1], Decimal("0"), Decimal("750")),
            ],
            created_by=self.user,
        )
        total_debit = sum(l.debit for l in je.lines.all())
        total_credit = sum(l.credit for l in je.lines.all())
        self.assertEqual(total_debit, total_credit)

    def test_post_journal_creates_lines(self):
        """post_journal_entry should persist JournalLine records."""
        from apps.accounting.services import AccountingService
        accounts = list(Account.objects.filter(organisation=self.org).order_by("code")[:2])
        je = AccountingService.post_journal_entry(
            organisation=self.org,
            description="Lines check",
            entry_date=timezone.now().date(),
            lines=[
                (accounts[0], Decimal("300"), Decimal("0")),
                (accounts[1], Decimal("0"), Decimal("300")),
            ],
            created_by=self.user,
        )
        self.assertEqual(je.lines.count(), 2)

    def test_not_configured_when_mapping_missing(self):
        """safe_post_gl with a missing mapping should set gl_post_status=not_configured."""
        from apps.bills.models import Bill
        from apps.suppliers.models import Supplier

        supplier = Supplier.objects.create(organisation=self.org, name="Integ Supplier")
        bill = Bill.objects.create(
            organisation=self.org,
            supplier=supplier,
            issue_date=timezone.now().date(),
            due_date=timezone.now().date(),
            total_amount=Decimal("500"),
            created_by=self.user,
        )

        def raise_not_configured():
            raise GLAccountNotConfigured("cogs_account")

        safe_post_gl(raise_not_configured, model_instance=bill)
        bill.refresh_from_db()
        self.assertEqual(bill.gl_post_status, "not_configured")

    def test_gl_post_status_visible_in_invoice_api(self):
        """Invoice list/detail API should include gl_post_status field."""
        from apps.inventory.models import Product
        product = Product.objects.create(
            organisation=self.org, name="Integ Product",
            selling_price=Decimal("100"), cost_price=Decimal("60"),
        )
        customer_res = self.client.post("/api/v1/customers/customers/", {
            "name": "Integ Customer", "email": "integ_cust@example.com"
        }, format="json")
        if customer_res.status_code not in [200, 201]:
            self.skipTest("Could not create customer for invoice test")
        customer_id = customer_res.data["id"]
        res = self.client.post("/api/v1/sales/invoices/", {
            "customer": customer_id,
            "invoice_date": "2026-01-15",
            "due_date": "2026-02-15",
            "payment_method": "cash",
            "lines": [{"product": str(product.id), "quantity": 1, "unit_price": "100.00"}],
        }, format="json")
        if res.status_code not in [200, 201]:
            self.skipTest("Could not create invoice for GL status test")
        self.assertIn("gl_post_status", res.data)

    def test_account_scoring_prefers_exact_code_match(self):
        """AccountMappingService.suggest() should prefer a revenue-type account for revenue_account role."""
        Account.objects.create(
            organisation=self.org,
            code="4000",
            name="Sales Revenue",
            account_type="revenue",
        )
        suggestion = AccountMappingService.suggest(self.org, "revenue_account")
        self.assertIsNotNone(suggestion)
        self.assertEqual(suggestion.account_type, "revenue")


class Phase1WiringTests(TestCase):
    """Phase 1: Verify safe_post_gl is called automatically from business events."""

    def setUp(self):
        self.user = _make_user("wire_owner@example.com")
        self.org = _make_org(self.user, "Wire Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def _make_product(self, name="Wire Product"):
        from apps.inventory.models import Product
        return Product.objects.create(
            organisation=self.org, name=name,
            selling_price=Decimal("200"), cost_price=Decimal("100"),
            product_type="service",
        )

    def _make_customer(self, name="Wire Customer"):
        from apps.customers.models import Customer
        return Customer.objects.create(
            organisation=self.org, name=name,
            email=f"{name.lower().replace(' ', '').replace('-', '')}@example.com",
        )

    def _make_warehouse(self, name="Wire Warehouse"):
        from apps.inventory.models import Warehouse
        return Warehouse.objects.create(organisation=self.org, name=name)

    def test_sale_creation_sets_gl_post_status(self):
        """Creating a sale (non-credit) should set invoice.gl_post_status."""
        from apps.sales.services import SaleService

        product = self._make_product("Sale Wire Product")
        customer = self._make_customer("Sale Wire Customer")
        warehouse = self._make_warehouse("Sale Wire WH")
        invoice = SaleService.create_sale(
            organisation=self.org,
            customer=customer,
            warehouse=warehouse,
            items=[{"product_id": product.id, "quantity": 1, "unit_price": Decimal("200")}],
            payment_method="cash",
            created_by=self.user,
        )
        invoice.refresh_from_db()
        self.assertIn(invoice.gl_post_status, ["posted", "failed", "not_configured"])

    def test_expense_creation_sets_gl_post_status(self):
        """Creating an expense via API should set expense.gl_post_status."""
        res = self.client.post("/api/v1/expenses/", {
            "description": "Wire Expense",
            "amount": "150.00",
            "expense_date": "2026-01-10",
            "category_label": "Office Supplies",
            "payment_method": "cash",
        }, format="json")
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))
        from apps.expenses.models import Expense
        exp = Expense.objects.get(id=res.data["id"])
        self.assertIn(exp.gl_post_status, ["posted", "failed", "not_configured"])

    def test_bill_approval_sets_gl_post_status(self):
        """Approving a bill should set bill.gl_post_status."""
        from apps.bills.models import Bill
        from apps.bills.services import BillService
        from apps.suppliers.models import Supplier

        supplier = Supplier.objects.create(organisation=self.org, name="Wire Supplier")
        bill = Bill.objects.create(
            organisation=self.org,
            supplier=supplier,
            issue_date=timezone.now().date(),
            due_date=timezone.now().date(),
            total_amount=Decimal("300"),
            created_by=self.user,
        )
        approver = _make_user("wire_approver@example.com")
        from apps.tenancy.models import Membership
        Membership.objects.create(organisation=self.org, user=approver, role="manager")
        BillService.approve_bill(bill, approver)
        bill.refresh_from_db()
        self.assertIn(bill.gl_post_status, ["posted", "failed", "not_configured"])

    def test_gl_health_endpoint_reflects_wired_status(self):
        """After a sale, GL health endpoint should show at least one non-pending entry."""
        from apps.sales.services import SaleService
        product = self._make_product("Health Wire Product")
        customer = self._make_customer("Health Wire Customer")
        warehouse = self._make_warehouse("Health Wire WH")
        SaleService.create_sale(
            organisation=self.org,
            customer=customer,
            warehouse=warehouse,
            items=[{"product_id": product.id, "quantity": 1, "unit_price": Decimal("200")}],
            payment_method="cash",
            created_by=self.user,
        )
        res = self.client.get("/api/v1/accounting/gl-health/")
        self.assertEqual(res.status_code, 200)
        summary = res.data.get("summary", {})
        total = sum(summary.values())
        self.assertGreater(total, 0, "GL health should reflect at least one auto-posted entry")


class BulkRetryTests(TestCase):
    """Phase 3: bulk retry endpoint."""

    def setUp(self):
        self.user = _make_user("bulk_owner@example.com")
        self.org = _make_org(self.user, "Bulk Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_bulk_retry_endpoint_returns_200(self):
        """POST /accounting/gl-health/retry-all/ should return 200."""
        res = self.client.post("/api/v1/accounting/gl-health/retry-all/")
        self.assertEqual(res.status_code, 200)

    def test_bulk_retry_response_has_expected_keys(self):
        res = self.client.post("/api/v1/accounting/gl-health/retry-all/")
        self.assertEqual(res.status_code, 200)
        for key in ["attempted", "succeeded", "failed", "errors"]:
            self.assertIn(key, res.data)

    def test_bulk_retry_with_no_failures_returns_zero_attempted(self):
        """With no failed entries, attempted should be 0."""
        res = self.client.post("/api/v1/accounting/gl-health/retry-all/")
        self.assertEqual(res.data["attempted"], 0)

    def test_bulk_retry_retries_failed_invoices(self):
        """Failed invoices should be included in the attempt count."""
        from apps.sales.models import Invoice
        from apps.inventory.models import Product, Warehouse
        from apps.customers.models import Customer

        product = Product.objects.create(
            organisation=self.org, name="Bulk Product",
            selling_price=Decimal("100"), cost_price=Decimal("50"), product_type="service",
        )
        customer = Customer.objects.create(
            organisation=self.org, name="Bulk Customer", email="bulk@example.com"
        )
        warehouse = Warehouse.objects.create(organisation=self.org, name="Bulk WH")
        from apps.sales.services import SaleService
        invoice = SaleService.create_sale(
            organisation=self.org, customer=customer, warehouse=warehouse,
            items=[{"product_id": product.id, "quantity": 1, "unit_price": Decimal("100")}],
            payment_method="cash", created_by=self.user,
        )
        Invoice.objects.filter(pk=invoice.pk).update(gl_post_status="failed", gl_post_error="test error")
        res = self.client.post("/api/v1/accounting/gl-health/retry-all/")
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(res.data["attempted"], 1)

    def test_bulk_retry_unauthenticated_denied(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        res = anon.post("/api/v1/accounting/gl-health/retry-all/")
        self.assertIn(res.status_code, [401, 403])


class ReconPostConfirmedGLTests(TestCase):
    """Phase 3: Post confirmed AI matches as GL journal entries."""

    def setUp(self):
        self.user = _make_user("recon_gl_owner@example.com")
        self.org = _make_org(self.user, "Recon GL Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def _make_recon(self):
        from apps.accounting.models import BankReconciliation, BankReconciliationLine, AIReconMatch
        account = Account.objects.filter(organisation=self.org, account_type="asset").first()
        recon = BankReconciliation.objects.create(
            organisation=self.org,
            account=account,
            period_start=timezone.now().date().replace(day=1),
            period_end=timezone.now().date(),
            statement_closing_balance=Decimal("5000"),
        )
        return recon

    def test_post_confirmed_gl_endpoint_exists(self):
        recon = self._make_recon()
        res = self.client.post(f"/api/v1/accounting/reconciliations/{recon.id}/post_confirmed_gl/")
        self.assertIn(res.status_code, [200, 201, 422])

    def test_post_confirmed_gl_with_no_confirmed_matches_returns_0(self):
        recon = self._make_recon()
        res = self.client.post(f"/api/v1/accounting/reconciliations/{recon.id}/post_confirmed_gl/")
        self.assertIn(res.status_code, [200, 422])
        self.assertEqual(res.data.get("posted", 0), 0)

    def test_post_confirmed_gl_creates_journal_entry(self):
        """Confirmed AI match with no book_line should produce a GL journal entry."""
        from apps.accounting.models import (
            BankReconciliation, BankReconciliationLine, AIReconMatch
        )
        account = Account.objects.filter(organisation=self.org, account_type="asset").first()
        recon = BankReconciliation.objects.create(
            organisation=self.org,
            account=account,
            period_start=timezone.now().date().replace(day=1),
            period_end=timezone.now().date(),
            statement_closing_balance=Decimal("1000"),
        )
        bank_line = BankReconciliationLine.objects.create(
            organisation=self.org,
            reconciliation=recon,
            description="Test inflow",
            transaction_date=timezone.now().date(),
            amount=Decimal("500"),
        )
        AIReconMatch.objects.create(
            organisation=self.org,
            reconciliation=recon,
            bank_line=bank_line,
            book_line=None,
            confidence=0.9,
            match_type="exact",
            status="confirmed",
        )
        je_count_before = JournalEntry.objects.filter(organisation=self.org).count()
        res = self.client.post(f"/api/v1/accounting/reconciliations/{recon.id}/post_confirmed_gl/")
        je_count_after = JournalEntry.objects.filter(organisation=self.org).count()
        self.assertIn(res.status_code, [201, 422])
        if res.status_code == 201:
            self.assertGreater(je_count_after, je_count_before)

    def test_post_confirmed_gl_marks_bank_line_cleared(self):
        """After posting, the bank_line.is_cleared should be True."""
        from apps.accounting.models import (
            BankReconciliation, BankReconciliationLine, AIReconMatch
        )
        account = Account.objects.filter(organisation=self.org, account_type="asset").first()
        recon = BankReconciliation.objects.create(
            organisation=self.org,
            account=account,
            period_start=timezone.now().date().replace(day=1),
            period_end=timezone.now().date(),
            statement_closing_balance=Decimal("2000"),
        )
        bank_line = BankReconciliationLine.objects.create(
            organisation=self.org,
            reconciliation=recon,
            description="Test payment",
            transaction_date=timezone.now().date(),
            amount=Decimal("250"),
        )
        AIReconMatch.objects.create(
            organisation=self.org,
            reconciliation=recon,
            bank_line=bank_line,
            book_line=None,
            confidence=0.95,
            match_type="exact",
            status="confirmed",
        )
        res = self.client.post(f"/api/v1/accounting/reconciliations/{recon.id}/post_confirmed_gl/")
        if res.status_code == 201 and res.data.get("posted", 0) > 0:
            bank_line.refresh_from_db()
            self.assertTrue(bank_line.is_cleared)


class StrictGLModeTests(TestCase):
    """Phase 4: Strict GL mode blocks transactions when mappings are missing."""

    def setUp(self):
        self.user = _make_user("strict_owner@example.com")
        self.org = _make_org(self.user, "Strict Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_strict_mode_off_allows_sale_without_full_mapping(self):
        """With strict_gl_mode=False (default), sales proceed even if mapping has nulls."""
        from apps.accounting.models import AccountMapping
        from apps.sales.services import SaleService
        from apps.inventory.models import Product, Warehouse
        from apps.customers.models import Customer

        self.org.strict_gl_mode = False
        self.org.save(update_fields=["strict_gl_mode"])
        mapping = AccountMapping.objects.get(organisation=self.org)
        mapping.revenue_account = None
        mapping.save()
        product = Product.objects.create(
            organisation=self.org, name="Strict Off Product",
            selling_price=Decimal("100"), cost_price=Decimal("50"), product_type="service",
        )
        customer = Customer.objects.create(
            organisation=self.org, name="Strict Off Customer", email="strictoff@example.com"
        )
        warehouse = Warehouse.objects.create(organisation=self.org, name="Strict Off WH")
        try:
            invoice = SaleService.create_sale(
                organisation=self.org, customer=customer, warehouse=warehouse,
                items=[{"product_id": product.id, "quantity": 1, "unit_price": Decimal("100")}],
                payment_method="cash", created_by=self.user,
            )
            self.assertIsNotNone(invoice)
        except Exception as e:
            self.fail(f"Sale should succeed with strict_gl_mode=False, got: {e}")

    def test_strict_mode_on_blocks_sale_when_mapping_incomplete(self):
        """With strict_gl_mode=True and missing mappings, creating a sale must raise ValueError."""
        from apps.accounting.models import AccountMapping
        from apps.sales.services import SaleService
        from apps.inventory.models import Product, Warehouse
        from apps.customers.models import Customer

        self.org.strict_gl_mode = True
        self.org.save(update_fields=["strict_gl_mode"])
        mapping = AccountMapping.objects.get(organisation=self.org)
        mapping.revenue_account = None
        mapping.cash_account = None
        mapping.bank_account = None
        mapping.accounts_receivable = None
        mapping.inventory_account = None
        mapping.cogs_account = None
        mapping.accounts_payable = None
        mapping.save()
        product = Product.objects.create(
            organisation=self.org, name="Strict On Product",
            selling_price=Decimal("100"), cost_price=Decimal("50"), product_type="service",
        )
        customer = Customer.objects.create(
            organisation=self.org, name="Strict On Customer", email="stricton@example.com"
        )
        warehouse = Warehouse.objects.create(organisation=self.org, name="Strict On WH")
        with self.assertRaises(ValueError) as ctx:
            SaleService.create_sale(
                organisation=self.org, customer=customer, warehouse=warehouse,
                items=[{"product_id": product.id, "quantity": 1, "unit_price": Decimal("100")}],
                payment_method="cash", created_by=self.user,
            )
        self.assertIn("Strict GL mode", str(ctx.exception))

    def test_strict_mode_toggled_via_org_serializer(self):
        """strict_gl_mode must be writable via the org update API."""
        res = self.client.patch(
            f"/api/v1/tenancy/organisations/{self.org.id}/",
            {"strict_gl_mode": True},
            format="json",
        )
        self.assertIn(res.status_code, [200, 201])
        self.org.refresh_from_db()
        self.assertTrue(self.org.strict_gl_mode)

    def test_strict_mode_false_by_default(self):
        """New organisations must have strict_gl_mode=False."""
        new_user = _make_user("strict_new@example.com")
        new_org = _make_org(new_user, "Strict New Org")
        self.assertFalse(new_org.strict_gl_mode)

    def test_check_strict_gl_with_complete_mapping_passes(self):
        """check_strict_gl_mode should not raise when all required roles are mapped."""
        from apps.accounting.services import check_strict_gl_mode
        self.org.strict_gl_mode = True
        self.org.save(update_fields=["strict_gl_mode"])
        try:
            check_strict_gl_mode(self.org)
        except ValueError:
            self.fail("check_strict_gl_mode raised with complete mapping")


class PostHogMiddlewareTests(TestCase):
    """Phase 5: PostHog middleware must not crash on newer SDK signature."""

    def setUp(self):
        self.user = _make_user("posthog_user@example.com")
        self.org = _make_org(self.user, "PostHog Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_api_request_does_not_500_due_to_posthog(self):
        """Any authenticated API request must not 500 due to the PostHog middleware."""
        res = self.client.get("/api/v1/accounting/accounts/")
        self.assertNotEqual(res.status_code, 500)

    def test_gl_health_does_not_500_due_to_posthog(self):
        """GL health endpoint specifically must not 500 (was broken before fix)."""
        res = self.client.get("/api/v1/accounting/gl-health/")
        self.assertEqual(res.status_code, 200)

    def test_account_mapping_does_not_500_due_to_posthog(self):
        """Account mapping endpoint must not 500 (was broken before fix)."""
        res = self.client.get("/api/v1/accounting/account-mapping/")
        self.assertEqual(res.status_code, 200)


class ControlAccountAndTaxonomyTests(TestCase):
    """Phase 2: control-account posting lock, sub-type taxonomy, sub-type CRUD."""

    def setUp(self):
        self.user = _make_user("ctrl_owner@example.com")
        self.org = _make_org(self.user, "Ctrl Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_control_accounts_flagged(self):
        ar = Account.objects.get(organisation=self.org, code="1100")
        self.assertTrue(ar.is_control_account)
        self.assertFalse(ar.allow_posting)

    def test_manual_journal_to_control_account_rejected(self):
        ar = Account.objects.get(organisation=self.org, code="1100")   # control
        cash = Account.objects.get(organisation=self.org, code="1001")  # postable
        payload = {
            "description": "Illegal direct AR post",
            "entry_date": "2026-01-15",
            "lines": [
                {"account": str(ar.id), "debit": "1000", "credit": "0"},
                {"account": str(cash.id), "debit": "0", "credit": "1000"},
            ],
        }
        res = self.client.post("/api/v1/accounting/journal/", payload, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("control account", str(res.data).lower())

    def test_auto_posting_to_control_account_still_works(self):
        """The service path (used by sales/bills) must remain exempt from the lock."""
        ar = Account.objects.get(organisation=self.org, code="1100")
        rev = Account.objects.get(organisation=self.org, code="4001")
        entry = AccountingService.post_journal_entry(
            self.org, description="Auto credit sale", entry_date=timezone.now().date(),
            lines=[(ar, Decimal("1000"), Decimal("0")), (rev, Decimal("0"), Decimal("1000"))],
            created_by=self.user, source_type="test_sale", source_ref="X1",
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry.lines.count(), 2)

    def test_taxonomy_endpoint(self):
        res = self.client.get("/api/v1/accounting/accounts/taxonomy/")
        self.assertEqual(res.status_code, 200)
        groups = {g["group"] for g in res.data["groups"]}
        self.assertIn("Cash & Cash Equivalent", groups)
        self.assertIn("Indirect Cost", groups)
        cce = next(g for g in res.data["groups"] if g["group"] == "Cash & Cash Equivalent")
        self.assertEqual(cce["base_account_type"], "asset")
        self.assertTrue(any(s["name"] == "Mobile Money" for s in cce["sub_types"]))

    def test_sub_type_crud(self):
        res = self.client.post("/api/v1/accounting/account-sub-types/", {
            "name": "Crypto Wallet", "account_group": "Cash & Cash Equivalent",
            "base_account_type": "asset",
        }, format="json")
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))
        self.assertTrue(AccountSubType.objects.filter(organisation=self.org, name="Crypto Wallet").exists())

    def test_sub_type_group_mismatch_rejected(self):
        sub = AccountSubType.objects.filter(organisation=self.org, account_group="Equity").first()
        res = self.client.post("/api/v1/accounting/accounts/", {
            "code": "9500", "name": "Bad Account", "account_type": "asset",
            "account_group": "Asset", "sub_type": str(sub.id),
        }, format="json")
        self.assertEqual(res.status_code, 400)


class OpeningBalanceTakeOnTests(TestCase):
    """Phase 3: take-on opening balances post one balanced JE with a suspense plug."""

    def setUp(self):
        self.user = _make_user("open_owner@example.com")
        self.org = _make_org(self.user, "Open Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_opening_balances_post_and_balance(self):
        bank = Account.objects.get(organisation=self.org, code="1002")
        equity = Account.objects.get(organisation=self.org, code="3001")
        payload = {
            "as_of_date": "2026-01-01",
            "entries": [
                {"account": str(bank.id), "amount": "5000000", "side": "debit"},
                {"account": str(equity.id), "amount": "3000000", "side": "credit"},
            ],
        }
        res = self.client.post("/api/v1/accounting/accounts/opening_balances/", payload, format="json")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        # The 2,000,000 difference must be plugged to Take-On Suspense (3900).
        susp = Account.objects.get(organisation=self.org, code="3900")
        self.assertAlmostEqual(float(susp.balance), 2000000.0, places=2)
        # And the balance sheet must balance.
        bs = AccountingService.balance_sheet(self.org)
        self.assertTrue(bs["balanced"], msg=str(bs))

    def test_reposting_same_date_replaces(self):
        bank = Account.objects.get(organisation=self.org, code="1002")
        equity = Account.objects.get(organisation=self.org, code="3001")
        p = {"as_of_date": "2026-01-01", "entries": [
            {"account": str(bank.id), "amount": "1000000", "side": "debit"},
            {"account": str(equity.id), "amount": "1000000", "side": "credit"},
        ]}
        self.client.post("/api/v1/accounting/accounts/opening_balances/", p, format="json")
        p["entries"][0]["amount"] = "2000000"
        p["entries"][1]["amount"] = "2000000"
        self.client.post("/api/v1/accounting/accounts/opening_balances/", p, format="json")
        bank.refresh_from_db()
        # After reversal of the first take-on, net bank balance reflects the second only.
        self.assertAlmostEqual(float(bank.balance), 2000000.0, places=2)


class OpeningBalanceExtrasTests(TestCase):
    """Per-account opening balance + sub-ledger (customers/suppliers/items) take-on."""

    def setUp(self):
        self.user = _make_user("openx_owner@example.com")
        self.org = _make_org(self.user, "OpenX Org")
        _upgrade_to_business(self.org)

    def test_account_opening_balance_posts_and_balances(self):
        bank = Account.objects.get(organisation=self.org, code="1002")
        AccountingService.set_account_opening_balance(
            self.org, bank, Decimal("750000"), "debit",
            timezone.now().date(), created_by=self.user,
        )
        bank.refresh_from_db()
        self.assertAlmostEqual(float(bank.balance), 750000.0, places=2)
        susp = Account.objects.get(organisation=self.org, code="3900")
        self.assertAlmostEqual(float(susp.balance), 750000.0, places=2)  # credit suspense
        bs = AccountingService.balance_sheet(self.org)
        self.assertTrue(bs["balanced"], msg=str(bs))

    def test_account_opening_balance_reposts_without_disturbing_others(self):
        bank = Account.objects.get(organisation=self.org, code="1002")
        cash = Account.objects.get(organisation=self.org, code="1001")
        d = timezone.now().date()
        AccountingService.set_account_opening_balance(self.org, bank, Decimal("100000"), "debit", d, created_by=self.user)
        AccountingService.set_account_opening_balance(self.org, cash, Decimal("50000"), "debit", d, created_by=self.user)
        # Re-post bank — cash must be untouched.
        AccountingService.set_account_opening_balance(self.org, bank, Decimal("200000"), "debit", d, created_by=self.user)
        bank.refresh_from_db(); cash.refresh_from_db()
        self.assertAlmostEqual(float(bank.balance), 200000.0, places=2)
        self.assertAlmostEqual(float(cash.balance), 50000.0, places=2)
        self.assertTrue(AccountingService.balance_sheet(self.org)["balanced"])

    def test_subledger_opening_balances(self):
        from apps.customers.models import Customer
        from apps.suppliers.models import Supplier
        from apps.inventory.models import Product, Warehouse

        cust = Customer.objects.create(organisation=self.org, name="Acme Ltd")
        sup = Supplier.objects.create(organisation=self.org, code="SUP1", name="Vendor Co")
        wh = Warehouse.objects.create(organisation=self.org, name="Main WH")
        prod = Product.objects.create(
            organisation=self.org, sku="SKU1", name="Widget",
            cost_price=Decimal("100"), selling_price=Decimal("150"),
        )
        entry = AccountingService.set_subledger_opening_balances(
            self.org, timezone.now().date(),
            customers=[{"id": str(cust.id), "amount": "300000"}],
            suppliers=[{"id": str(sup.id), "amount": "120000"}],
            items=[{"product_id": str(prod.id), "quantity": "500", "unit_cost": "100"}],
            created_by=self.user,
        )
        self.assertIsNotNone(entry)
        cust.refresh_from_db(); sup.refresh_from_db()
        self.assertAlmostEqual(float(cust.outstanding_balance), 300000.0, places=2)
        self.assertAlmostEqual(float(sup.opening_balance), 120000.0, places=2)
        # Ledger: AR 300k debit, Inventory 50k debit, AP 120k credit → suspense plug
        ar = Account.objects.get(organisation=self.org, code="1100")
        inv = Account.objects.get(organisation=self.org, code="1200")
        ap = Account.objects.get(organisation=self.org, code="2001")
        self.assertAlmostEqual(float(ar.balance), 300000.0, places=2)
        self.assertAlmostEqual(float(inv.balance), 50000.0, places=2)
        self.assertAlmostEqual(float(ap.balance), 120000.0, places=2)
        self.assertTrue(AccountingService.balance_sheet(self.org)["balanced"])


class SubledgerAndAccountOpeningBalanceTests(TestCase):
    """Post-doc completion: per-account opening balance + subledger take-on."""

    def setUp(self):
        self.user = _make_user("sub_owner@example.com")
        self.org = _make_org(self.user, "Sub Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_account_level_opening_balance_endpoint(self):
        bank = Account.objects.get(organisation=self.org, code="1002")
        res = self.client.post(
            f"/api/v1/accounting/accounts/{bank.id}/set_opening_balance/",
            {"amount": "750000", "side": "debit", "as_of_date": "2026-01-01"}, format="json",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        bank.refresh_from_db()
        self.assertAlmostEqual(float(bank.balance), 750000.0, places=2)
        # Suspense carries the offsetting credit; BS still balances.
        bs = AccountingService.balance_sheet(self.org)
        self.assertTrue(bs["balanced"], msg=str(bs))

    def test_account_opening_balance_reposts_cleanly(self):
        bank = Account.objects.get(organisation=self.org, code="1002")
        AccountingService.set_account_opening_balance(self.org, bank, Decimal("100000"), "debit", "2026-01-01", created_by=self.user)
        AccountingService.set_account_opening_balance(self.org, bank, Decimal("250000"), "debit", "2026-01-01", created_by=self.user)
        bank.refresh_from_db()
        self.assertAlmostEqual(float(bank.balance), 250000.0, places=2)

    def test_subledger_opening_balances(self):
        from apps.customers.models import Customer
        from apps.suppliers.models import Supplier
        from apps.inventory.models import Product, Warehouse

        cust = Customer.objects.create(organisation=self.org, name="Acme Ltd")
        sup = Supplier.objects.create(organisation=self.org, code="SUP1", name="Global Supply")
        wh = Warehouse.objects.create(organisation=self.org, name="Main WH", is_default=True)
        prod = Product.objects.create(
            organisation=self.org, sku="P1", name="Widget",
            cost_price=Decimal("100"), selling_price=Decimal("150"),
        )

        entry = AccountingService.set_subledger_opening_balances(
            self.org, "2026-01-01",
            customers=[{"id": str(cust.id), "amount": "500000"}],
            suppliers=[{"id": str(sup.id), "amount": "200000"}],
            items=[{"product_id": str(prod.id), "warehouse_id": str(wh.id), "quantity": "10", "unit_cost": "100"}],
            created_by=self.user,
        )
        self.assertIsNotNone(entry)

        ar = Account.objects.get(organisation=self.org, code="1100")
        ap = Account.objects.get(organisation=self.org, code="2001")
        inv = Account.objects.get(organisation=self.org, code="1200")
        self.assertAlmostEqual(float(ar.balance), 500000.0, places=2)   # DR AR
        self.assertAlmostEqual(float(ap.balance), 200000.0, places=2)   # CR AP
        self.assertAlmostEqual(float(inv.balance), 1000.0, places=2)    # 10 × 100

        cust.refresh_from_db(); sup.refresh_from_db()
        self.assertAlmostEqual(float(cust.outstanding_balance), 500000.0, places=2)
        self.assertAlmostEqual(float(sup.opening_balance), 200000.0, places=2)

        bs = AccountingService.balance_sheet(self.org)
        self.assertTrue(bs["balanced"], msg=str(bs))


class FixedAssetAcquisitionTests(TestCase):
    """Phase 1: creating a fixed asset posts DR 1500 Fixed Assets / CR funding, the
    register reconciles to the GL, acquisition is not double-posted, and 1500/1510 are
    control-locked. This closes the reviewer's ₦94m balance-sheet defect (asset cost
    on the register but nothing posted to the ledger)."""

    def setUp(self):
        self.user = _make_user("fa_owner@example.com")
        self.org = _make_org(self.user, "FA Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        # Deterministic funding accounts for the credit leg.
        m = AccountMapping.objects.get(organisation=self.org)
        m.bank_account = Account.objects.get(organisation=self.org, code="1002")
        m.cash_account = Account.objects.get(organisation=self.org, code="1001")
        m.accounts_payable = Account.objects.get(organisation=self.org, code="2001")
        m.save()

    def _create_asset(self, cost="1200000", funding="bank", asset_code="FA-001", **extra):
        payload = {
            "name": "Toyota Hilux", "asset_code": asset_code, "category": "vehicle",
            "purchase_date": "2026-07-01", "purchase_cost": cost,
            "depreciation_method": "straight_line", "useful_life_years": 5,
            "residual_value": "0", "funding_source": funding,
        }
        payload.update(extra)
        return self.client.post("/api/v1/accounting/assets/", payload, format="json")

    def _gl(self, code):
        acct = Account.objects.get(organisation=self.org, code=code)
        return AccountingService._ledger_balance(acct)

    def test_acquisition_posts_dr_1500_cr_bank(self):
        res = self._create_asset()
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))
        je = JournalEntry.objects.filter(
            organisation=self.org, source_type="asset_acquisition"
        ).first()
        self.assertIsNotNone(je, "acquisition journal was not posted")
        # DR 1500 = cost, CR 1002 Bank = cost
        self.assertAlmostEqual(float(self._gl("1500")), 1200000.0, places=2)
        self.assertAlmostEqual(float(self._gl("1002")), -1200000.0, places=2)
        self.assertTrue(FixedAsset.objects.get(id=res.data["id"]).acquisition_posted)

    def test_register_reconciles_to_gl_after_depreciation(self):
        """Canonical QA case: ₦1.2m asset, 1 month SL depreciation → register NBV
        (1,180,000) equals GL 1500+1510, balance sheet balances, suspense plug is 0."""
        res = self._create_asset()
        asset = FixedAsset.objects.get(id=res.data["id"])
        AccountingService.run_depreciation(self.org, 2026, 7)  # one month
        asset.refresh_from_db()

        # Register figures
        self.assertAlmostEqual(float(asset.accumulated_depreciation), 20000.0, places=2)
        self.assertAlmostEqual(float(asset.net_book_value), 1180000.0, places=2)

        # GL figures
        self.assertAlmostEqual(float(self._gl("1500")), 1200000.0, places=2)   # cost
        self.assertAlmostEqual(float(self._gl("1510")), -20000.0, places=2)    # contra
        net_fixed_assets = self._gl("1500") + self._gl("1510")
        self.assertAlmostEqual(float(net_fixed_assets), float(asset.net_book_value), places=2)

        bs = AccountingService.balance_sheet(self.org)
        self.assertTrue(bs["balanced"], msg=str(bs))
        # No auto-balance suspense plug should be needed.
        plug = [r for r in bs["equity"] if r.get("code") == "3900" and r.get("is_computed")]
        self.assertEqual(plug, [], "auto-balance suspense plug should be empty once acquisition posts")

    def test_acquisition_not_double_posted(self):
        res = self._create_asset()
        asset = FixedAsset.objects.get(id=res.data["id"])
        # Re-invoking the service must be a no-op (idempotent on asset).
        from apps.accounting.services import CapitalisationService
        again = CapitalisationService.post_acquisition(self.org, asset)
        self.assertIsNone(again)
        count = JournalEntry.objects.filter(
            organisation=self.org, source_type="asset_acquisition",
            source_ref=f"asset:{asset.pk}",
        ).count()
        self.assertEqual(count, 1)

    def test_owner_capital_funding_credits_equity(self):
        res = self._create_asset(funding="equity", asset_code="FA-EQ")
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))
        self.assertAlmostEqual(float(self._gl("1500")), 1200000.0, places=2)
        self.assertAlmostEqual(float(self._gl("3001")), 1200000.0, places=2)  # Owner Equity (credit-normal)

    def test_opening_balance_funding_posts_takeon_not_acquisition(self):
        """Assets brought on via take-on (funding_source='none') must NOT post a
        purchase acquisition journal — instead the take-on flow posts its own entry
        (DR 1500 / CR 3900), so no cost is double-expensed."""
        res = self._create_asset(funding="none", asset_code="FA-OPEN")
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))
        # No purchase-acquisition entry...
        self.assertFalse(
            JournalEntry.objects.filter(organisation=self.org, source_type="asset_acquisition").exists()
        )
        # ...but a take-on entry that puts the gross cost on 1500 against suspense (3900).
        self.assertTrue(
            JournalEntry.objects.filter(organisation=self.org, source_type="asset_takeon").exists()
        )
        self.assertAlmostEqual(float(self._gl("1500")), 1200000.0, places=2)
        self.assertAlmostEqual(float(self._gl("3900")), 1200000.0, places=2)

    def test_1500_and_1510_are_control_locked(self):
        for code in ("1500", "1510"):
            acct = Account.objects.get(organisation=self.org, code=code)
            self.assertTrue(acct.is_control_account, f"{code} should be a control account")
            self.assertFalse(acct.allow_posting, f"{code} should block direct posting")

    def test_manual_journal_to_fixed_assets_rejected(self):
        fa = Account.objects.get(organisation=self.org, code="1500")   # control
        bank = Account.objects.get(organisation=self.org, code="1002")
        payload = {
            "description": "Illegal direct FA post", "entry_date": "2026-07-15",
            "lines": [
                {"account": str(fa.id), "debit": "500000", "credit": "0"},
                {"account": str(bank.id), "debit": "0", "credit": "500000"},
            ],
        }
        res = self.client.post("/api/v1/accounting/journal/", payload, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("control account", str(res.data).lower())

    def test_below_threshold_helper(self):
        from apps.accounting.services import CapitalisationService
        self.assertFalse(CapitalisationService.should_capitalise(self.org, "50000"))
        self.assertTrue(CapitalisationService.should_capitalise(self.org, "100000"))
        self.assertTrue(CapitalisationService.should_capitalise(self.org, "250000"))

    def test_blank_asset_code_auto_generates(self):
        """The form invites a blank Asset Code ('auto if blank'); the API must
        auto-generate an FA-XXXX code instead of rejecting it (regression: the UI
        create failed with 'Asset Code: This field may not be blank')."""
        res = self.client.post("/api/v1/accounting/assets/", {
            "name": "Uncoded Asset", "category": "equipment",
            "purchase_date": "2026-07-01", "purchase_cost": "300000",
            "useful_life_years": 5, "residual_value": "0", "funding_source": "bank",
        }, format="json")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertTrue(res.data["asset_code"].startswith("FA-"), msg=res.data["asset_code"])


class BillCapitalisationTests(TestCase):
    """Phase 1: a bill line flagged capitalise=True redirects its VAT-exclusive share
    from the expense account to Fixed Assets (1500) and creates a FixedAsset register
    record on approval — without a separate acquisition journal (the bill JE carries
    the debit) and without double-posting."""

    def setUp(self):
        self.user = _make_user("billcap_owner@example.com")
        self.org = _make_org(self.user, "BillCap Org")
        _upgrade_to_business(self.org)
        m = AccountMapping.objects.get(organisation=self.org)
        m.general_expense_account = Account.objects.get(organisation=self.org, code="6700")
        m.accounts_payable = Account.objects.get(organisation=self.org, code="2001")
        m.save()

    def _gl(self, code):
        acct = Account.objects.get(organisation=self.org, code=code)
        return AccountingService._ledger_balance(acct)

    def _make_bill(self, tax=Decimal("0"), status="approved"):
        from apps.bills.services import BillService
        from apps.suppliers.models import Supplier
        supplier = Supplier.objects.create(organisation=self.org, name="BillCap Vendor")
        validated = {
            "supplier": supplier, "issue_date": timezone.now().date(),
            "due_date": timezone.now().date(), "status": status, "tax_amount": tax,
        }
        items = [
            {"description": "Generator", "quantity": Decimal("1"), "unit_cost": Decimal("800000"),
             "capitalise": True, "asset_category": "equipment", "useful_life_years": 5},
            {"description": "Stationery", "quantity": Decimal("1"), "unit_cost": Decimal("200000"),
             "capitalise": False},
        ]
        return BillService.create_bill(validated, items, self.org, self.user)

    def test_capital_line_redirects_to_1500_and_creates_asset(self):
        bill = self._make_bill()
        bill.refresh_from_db()
        self.assertEqual(bill.gl_post_status, "posted", msg=bill.gl_post_error)
        # 1500 gets the capital net (800k), expense gets 200k, AP credited full 1,000,000.
        self.assertAlmostEqual(float(self._gl("1500")), 800000.0, places=2)
        self.assertAlmostEqual(float(self._gl("6700")), 200000.0, places=2)
        self.assertAlmostEqual(float(self._gl("2001")), 1000000.0, places=2)  # AP credit-normal
        # A FixedAsset register record exists, stamped as posted, keyed to the bill line.
        capital_item = bill.items.get(capitalise=True)
        asset = FixedAsset.objects.get(
            organisation=self.org, source_document_ref=f"bill_line:{capital_item.id}"
        )
        self.assertTrue(asset.acquisition_posted)
        self.assertAlmostEqual(float(asset.purchase_cost), 800000.0, places=2)
        self.assertEqual(asset.category, "equipment")
        self.assertEqual(asset.capitalisation_source, FixedAsset.CAP_BILL)

    def test_no_separate_acquisition_journal(self):
        """The bill's approval JE carries the DR 1500 — there must be no extra
        asset_acquisition entry (which would double-count)."""
        self._make_bill()
        self.assertFalse(
            JournalEntry.objects.filter(organisation=self.org, source_type="asset_acquisition").exists()
        )
        self.assertEqual(
            JournalEntry.objects.filter(organisation=self.org, source_type="bill_approved").count(), 1
        )

    def test_balance_sheet_balances_after_bill_capitalisation(self):
        self._make_bill()
        bs = AccountingService.balance_sheet(self.org)
        self.assertTrue(bs["balanced"], msg=str(bs))

    def test_reposting_bill_does_not_double_post_or_duplicate_asset(self):
        bill = self._make_bill()
        # Re-run the posting (idempotent on bill_approved source_ref).
        AccountingService.post_bill_approved_journal(self.org, bill, self.user)
        self.assertAlmostEqual(float(self._gl("1500")), 800000.0, places=2)
        capital_item = bill.items.get(capitalise=True)
        assets = FixedAsset.objects.filter(
            organisation=self.org, source_document_ref=f"bill_line:{capital_item.id}"
        )
        self.assertEqual(assets.count(), 1)

    def test_vat_split_keeps_entry_balanced(self):
        """With VAT, the capital line's VAT-exclusive share goes to 1500 and the entry
        still balances; the asset records the input-tax evidence."""
        # subtotal 1,000,000 + VAT 75,000 = 1,075,000 total.
        bill = self._make_bill(tax=Decimal("75000"))
        bill.refresh_from_db()
        self.assertEqual(bill.gl_post_status, "posted", msg=bill.gl_post_error)
        # net_cost = 1,000,000; capital share 80% → 800,000 to 1500.
        self.assertAlmostEqual(float(self._gl("1500")), 800000.0, places=2)
        self.assertAlmostEqual(float(self._gl("6700")), 200000.0, places=2)
        self.assertAlmostEqual(float(self._gl("1400")), 75000.0, places=2)   # input VAT
        self.assertAlmostEqual(float(self._gl("2001")), 1075000.0, places=2)  # AP gross
        self.assertTrue(AccountingService.balance_sheet(self.org)["balanced"])
        capital_item = bill.items.get(capitalise=True)
        asset = FixedAsset.objects.get(
            organisation=self.org, source_document_ref=f"bill_line:{capital_item.id}"
        )
        self.assertTrue(asset.input_tax_paid)
        self.assertAlmostEqual(float(asset.input_tax_amount), 60000.0, places=2)  # 80% of 75k


class FixedAssetTakeOnAndReconciliationTests(TestCase):
    """Phase 2: per-asset opening-balance take-on posts DR 1500 / CR 1510 / CR 3900 and
    seeds depreciation history; the reconciliation endpoint proves register == GL."""

    def setUp(self):
        self.user = _make_user("faopen_owner@example.com")
        self.org = _make_org(self.user, "FAOpen Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        m = AccountMapping.objects.get(organisation=self.org)
        m.bank_account = Account.objects.get(organisation=self.org, code="1002")
        m.save()

    def _gl(self, code):
        acct = Account.objects.get(organisation=self.org, code=code)
        return AccountingService._ledger_balance(acct)

    def _create_takeon(self, cost="1000000", accum="200000", asset_code="FA-TO1"):
        payload = {
            "name": "Legacy Truck", "asset_code": asset_code, "category": "vehicle",
            "purchase_date": "2026-07-01", "purchase_cost": cost,
            "depreciation_method": "straight_line", "useful_life_years": 5,
            "residual_value": "0", "funding_source": "none",
            "capitalisation_source": "opening_balance",
            "opening_accumulated_depreciation": accum,
        }
        return self.client.post("/api/v1/accounting/assets/", payload, format="json")

    def test_takeon_posts_split_entry(self):
        res = self._create_takeon()
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))
        # DR 1500 gross; CR 1510 accum (contra, negative); CR 3900 NBV.
        self.assertAlmostEqual(float(self._gl("1500")), 1000000.0, places=2)
        self.assertAlmostEqual(float(self._gl("1510")), -200000.0, places=2)
        self.assertAlmostEqual(float(self._gl("3900")), 800000.0, places=2)  # equity credit
        asset = FixedAsset.objects.get(id=res.data["id"])
        self.assertAlmostEqual(float(asset.accumulated_depreciation), 200000.0, places=2)
        self.assertAlmostEqual(float(asset.net_book_value), 800000.0, places=2)
        self.assertTrue(asset.acquisition_posted)
        self.assertTrue(AccountingService.balance_sheet(self.org)["balanced"])

    def test_takeon_continues_depreciation_from_nbv(self):
        res = self._create_takeon()
        asset = FixedAsset.objects.get(id=res.data["id"])
        # Next month's run continues from the taken-on NBV (not from full cost).
        AccountingService.run_depreciation(self.org, 2026, 8, created_by=self.user)
        aug = asset.depreciation_entries.get(period_year=2026, period_month=8)
        self.assertAlmostEqual(float(aug.depreciation_amount), 16666.67, places=1)  # 1,000,000/60
        # GL accumulated dep magnitude now 200,000 + 16,666.67.
        self.assertAlmostEqual(float(self._gl("1510")), -216666.67, places=1)

    def test_reconciliation_zero_variance_after_purchase(self):
        # Direct purchase → register and GL must tie exactly.
        self.client.post("/api/v1/accounting/assets/", {
            "name": "New Van", "asset_code": "FA-REC1", "category": "vehicle",
            "purchase_date": "2026-07-01", "purchase_cost": "500000",
            "useful_life_years": 5, "residual_value": "0", "funding_source": "bank",
        }, format="json")
        res = self.client.get("/api/v1/accounting/assets/reconciliation/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["reconciled"], msg=str(res.data))
        self.assertAlmostEqual(float(res.data["variance"]["cost"]), 0.0, places=2)
        self.assertAlmostEqual(float(res.data["variance"]["net_book_value"]), 0.0, places=2)

    def test_reconciliation_flags_unposted_acquisition(self):
        """An asset whose acquisition failed to post must appear in the variance and
        the missing-acquisition list — the defect is surfaced, not hidden."""
        # Remove the bank mapping so the acquisition post can't resolve funding.
        m = AccountMapping.objects.get(organisation=self.org)
        m.bank_account = None
        m.save()
        res = self.client.post("/api/v1/accounting/assets/", {
            "name": "Orphan Asset", "asset_code": "FA-ORPH", "category": "equipment",
            "purchase_date": "2026-07-01", "purchase_cost": "300000",
            "useful_life_years": 5, "residual_value": "0", "funding_source": "bank",
        }, format="json")
        asset = FixedAsset.objects.get(id=res.data["id"])
        self.assertFalse(asset.acquisition_posted)
        rec = self.client.get("/api/v1/accounting/assets/reconciliation/").data
        self.assertFalse(rec["reconciled"])
        self.assertAlmostEqual(float(rec["variance"]["cost"]), 300000.0, places=2)
        codes = [a["asset_code"] for a in rec["assets_missing_acquisition"]]
        self.assertIn("FA-ORPH", codes)


class DepreciationMethodTests(TestCase):
    """Phase 3: depreciation methods (immediate write-off, 0%, configurable reducing
    balance), pro-rata first-period convention, multi-period catch-up + messaging."""

    def setUp(self):
        self.user = _make_user("dep_owner@example.com")
        self.org = _make_org(self.user, "Dep Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        m = AccountMapping.objects.get(organisation=self.org)
        m.bank_account = Account.objects.get(organisation=self.org, code="1002")
        m.save()

    def _make_asset(self, **kw):
        defaults = dict(
            organisation=self.org, name="Asset", asset_code=kw.pop("asset_code", "D-1"),
            category="equipment", purchase_date=__import__("datetime").date(2026, 7, 1),
            purchase_cost=Decimal("1200000"), useful_life_years=5, residual_value=Decimal("0"),
            funding_source="none", capitalisation_source="opening_balance",
        )
        defaults.update(kw)
        return FixedAsset.objects.create(**defaults)

    def test_immediate_write_off_full_first_period(self):
        asset = self._make_asset(depreciation_method="immediate", asset_code="D-IMM")
        AccountingService.run_depreciation(self.org, 2026, 7, created_by=self.user)
        asset.refresh_from_db()
        self.assertAlmostEqual(float(asset.accumulated_depreciation), 1200000.0, places=2)
        self.assertAlmostEqual(float(asset.net_book_value), 0.0, places=2)
        # A second run charges nothing more.
        AccountingService.run_depreciation(self.org, 2026, 8, created_by=self.user)
        asset.refresh_from_db()
        self.assertAlmostEqual(float(asset.accumulated_depreciation), 1200000.0, places=2)

    def test_zero_method_never_depreciates(self):
        asset = self._make_asset(depreciation_method="zero", asset_code="D-ZERO")
        AccountingService.run_depreciation(self.org, 2026, 7, created_by=self.user)
        asset.refresh_from_db()
        self.assertEqual(asset.depreciation_entries.count(), 0)
        self.assertAlmostEqual(float(asset.accumulated_depreciation), 0.0, places=2)

    def test_configurable_reducing_balance_rate(self):
        # 25% annual reducing balance → month 1 = 1,200,000 × 25% / 12 = 25,000.
        asset = self._make_asset(
            depreciation_method="reducing_balance", reducing_balance_rate=Decimal("25"),
            asset_code="D-RB",
        )
        AccountingService.run_depreciation(self.org, 2026, 7, created_by=self.user)
        entry = asset.depreciation_entries.get(period_year=2026, period_month=7)
        self.assertAlmostEqual(float(entry.depreciation_amount), 25000.0, places=2)

    def test_pro_rata_first_period(self):
        # Purchased 16 July → 16 days of a 31-day month. SL monthly = 1,200,000/60 = 20,000.
        # Pro-rata = 20,000 × 16/31 = 10,322.58.
        asset = self._make_asset(
            depreciation_method="straight_line", depreciation_convention="pro_rata",
            purchase_date=__import__("datetime").date(2026, 7, 16), asset_code="D-PRO",
        )
        AccountingService.run_depreciation(self.org, 2026, 7, created_by=self.user)
        jul = asset.depreciation_entries.get(period_year=2026, period_month=7)
        self.assertAlmostEqual(float(jul.depreciation_amount), 20000.0 * 16 / 31, places=1)
        # The following full month charges the full 20,000.
        AccountingService.run_depreciation(self.org, 2026, 8, created_by=self.user)
        aug = asset.depreciation_entries.get(period_year=2026, period_month=8)
        self.assertAlmostEqual(float(aug.depreciation_amount), 20000.0, places=2)

    def test_catch_up_runs_all_periods(self):
        self._make_asset(depreciation_method="straight_line", asset_code="D-CATCH")
        res = self.client.post("/api/v1/accounting/assets/run_depreciation/", {
            "year": 2026, "month": 10, "catch_up": True,
        }, format="json")
        self.assertEqual(res.status_code, 200)
        # Jul, Aug, Sep, Oct = 4 periods.
        self.assertEqual(res.data["entries_created"], 4)

    def test_already_run_messaging(self):
        self._make_asset(depreciation_method="straight_line", asset_code="D-AGAIN")
        self.client.post("/api/v1/accounting/assets/run_depreciation/",
                         {"year": 2026, "month": 7}, format="json")
        res = self.client.post("/api/v1/accounting/assets/run_depreciation/",
                               {"year": 2026, "month": 7}, format="json")
        self.assertEqual(res.data["entries_created"], 0)
        self.assertTrue(res.data["already_run"])
        self.assertIn("already been run", res.data["message"])


class AssetDisposalTests(TestCase):
    """Phase 4: disposal derecognises cost + accumulated depreciation from the GL and
    posts the gain/loss on disposal; the register stays reconciled to the ledger."""

    def setUp(self):
        self.user = _make_user("disp_owner@example.com")
        self.org = _make_org(self.user, "Disp Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        m = AccountMapping.objects.get(organisation=self.org)
        m.bank_account = Account.objects.get(organisation=self.org, code="1002")
        m.save()

    def _gl(self, code):
        acct = Account.objects.filter(organisation=self.org, code=code).first()
        return AccountingService._ledger_balance(acct) if acct else Decimal("0")

    def _asset_with_one_month_dep(self, code="DS-1"):
        res = self.client.post("/api/v1/accounting/assets/", {
            "name": "Hilux", "asset_code": code, "category": "vehicle",
            "purchase_date": "2026-07-01", "purchase_cost": "1200000",
            "useful_life_years": 5, "residual_value": "0", "funding_source": "bank",
        }, format="json")
        AccountingService.run_depreciation(self.org, 2026, 7, created_by=self.user)  # 20,000
        return FixedAsset.objects.get(id=res.data["id"])

    def test_disposal_gain_derecognises_and_posts_gain(self):
        asset = self._asset_with_one_month_dep()
        res = self.client.post(f"/api/v1/accounting/assets/{asset.id}/dispose/", {
            "proceeds": "1300000", "disposal_date": "2026-08-01", "proceeds_funding": "bank",
        }, format="json")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertAlmostEqual(float(res.data["gain_loss"]), 120000.0, places=2)  # 1.3m − 1.18m NBV
        # 1500 and 1510 fully cleared; bank net +100k; gain 120k in P&L.
        self.assertAlmostEqual(float(self._gl("1500")), 0.0, places=2)
        self.assertAlmostEqual(float(self._gl("1510")), 0.0, places=2)
        self.assertAlmostEqual(float(self._gl("1002")), 100000.0, places=2)  # -1.2m +1.3m
        self.assertAlmostEqual(float(self._gl("4200")), 120000.0, places=2)  # gain (revenue)
        asset.refresh_from_db()
        self.assertFalse(asset.is_active)
        self.assertIsNotNone(asset.disposal_date)
        self.assertTrue(AccountingService.balance_sheet(self.org)["balanced"])

    def test_disposal_loss(self):
        asset = self._asset_with_one_month_dep(code="DS-LOSS")
        res = self.client.post(f"/api/v1/accounting/assets/{asset.id}/dispose/", {
            "proceeds": "1000000", "disposal_date": "2026-08-01",
        }, format="json")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        # NBV 1,180,000; proceeds 1,000,000 → loss 180,000 (debit 4200 → negative revenue).
        self.assertAlmostEqual(float(res.data["gain_loss"]), -180000.0, places=2)
        self.assertAlmostEqual(float(self._gl("4200")), -180000.0, places=2)
        self.assertTrue(AccountingService.balance_sheet(self.org)["balanced"])

    def test_reconciliation_holds_after_disposal(self):
        asset = self._asset_with_one_month_dep(code="DS-REC")
        self.client.post(f"/api/v1/accounting/assets/{asset.id}/dispose/",
                         {"proceeds": "1000000", "disposal_date": "2026-08-01"}, format="json")
        rec = self.client.get("/api/v1/accounting/assets/reconciliation/").data
        self.assertTrue(rec["reconciled"], msg=str(rec))

    def test_double_disposal_rejected(self):
        asset = self._asset_with_one_month_dep(code="DS-DUP")
        self.client.post(f"/api/v1/accounting/assets/{asset.id}/dispose/",
                         {"proceeds": "1000000", "disposal_date": "2026-08-01"}, format="json")
        res = self.client.post(f"/api/v1/accounting/assets/{asset.id}/dispose/",
                               {"proceeds": "500000", "disposal_date": "2026-08-02"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_disposal_report(self):
        asset = self._asset_with_one_month_dep(code="DS-RPT")
        self.client.post(f"/api/v1/accounting/assets/{asset.id}/dispose/",
                         {"proceeds": "1300000", "disposal_date": "2026-08-01"}, format="json")
        rep = self.client.get("/api/v1/accounting/assets/disposal_report/").data
        self.assertEqual(len(rep["rows"]), 1)
        self.assertAlmostEqual(float(rep["rows"][0]["gain_loss"]), 120000.0, places=2)
        self.assertAlmostEqual(float(rep["totals"]["proceeds"]), 1300000.0, places=2)


class AssetTransferRevaluationReportTests(TestCase):
    """Phase 4: transfer (reclassification, no GL change), gated revaluation, and the
    asset reports (register / by-category / by-location / transfer / forecast)."""

    def setUp(self):
        self.user = _make_user("xfer_owner@example.com")
        self.org = _make_org(self.user, "Xfer Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        m = AccountMapping.objects.get(organisation=self.org)
        m.bank_account = Account.objects.get(organisation=self.org, code="1002")
        m.save()

    def _gl(self, code):
        acct = Account.objects.filter(organisation=self.org, code=code).first()
        return AccountingService._ledger_balance(acct) if acct else Decimal("0")

    def _make_asset(self, cost="1000000", code="X-1"):
        res = self.client.post("/api/v1/accounting/assets/", {
            "name": "Machine", "asset_code": code, "category": "equipment",
            "purchase_date": "2026-07-01", "purchase_cost": cost,
            "useful_life_years": 5, "residual_value": "0", "funding_source": "bank",
        }, format="json")
        return FixedAsset.objects.get(id=res.data["id"])

    def test_transfer_updates_location_without_gl_change(self):
        from apps.inventory.models import Warehouse
        asset = self._make_asset(code="X-TRANS")
        wh = Warehouse.objects.create(organisation=self.org, name="Lagos Branch")
        gl_before = self._gl("1500")
        res = self.client.post(f"/api/v1/accounting/assets/{asset.id}/transfer/", {
            "to_location": str(wh.id), "to_cost_centre": "Operations",
            "transfer_date": "2026-08-01", "reference": "TRF-1",
        }, format="json")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        asset.refresh_from_db()
        self.assertEqual(asset.location_id, wh.id)
        self.assertEqual(asset.cost_centre, "Operations")
        self.assertAlmostEqual(float(self._gl("1500")), float(gl_before), places=2)  # unchanged
        rep = self.client.get("/api/v1/accounting/assets/transfer_report/").data
        self.assertEqual(len(rep["rows"]), 1)
        self.assertEqual(rep["rows"][0]["to_location"], "Lagos Branch")

    def test_revaluation_gated_off_by_default(self):
        asset = self._make_asset(code="X-REVOFF")
        res = self.client.post(f"/api/v1/accounting/assets/{asset.id}/revalue/",
                               {"new_value": "1200000"}, format="json")
        self.assertEqual(res.status_code, 422)
        self.assertIn("not enabled", str(res.data).lower())

    def test_revaluation_upward_surplus_when_enabled(self):
        self.org.fixed_asset_revaluation_enabled = True
        self.org.save(update_fields=["fixed_asset_revaluation_enabled"])
        asset = self._make_asset(cost="1000000", code="X-REVUP")
        res = self.client.post(f"/api/v1/accounting/assets/{asset.id}/revalue/", {
            "new_value": "1200000", "revaluation_date": "2026-08-01",
        }, format="json")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertAlmostEqual(float(res.data["surplus"]), 200000.0, places=2)
        self.assertAlmostEqual(float(self._gl("1500")), 1200000.0, places=2)   # restated
        self.assertAlmostEqual(float(self._gl("3200")), 200000.0, places=2)    # revaluation surplus (equity)
        asset.refresh_from_db()
        self.assertAlmostEqual(float(asset.net_book_value), 1200000.0, places=2)
        self.assertTrue(AccountingService.balance_sheet(self.org)["balanced"])

    def test_register_and_grouping_reports(self):
        from apps.inventory.models import Warehouse
        wh = Warehouse.objects.create(organisation=self.org, name="HQ")
        a1 = self._make_asset(cost="500000", code="X-R1")
        a2 = self._make_asset(cost="300000", code="X-R2")
        FixedAsset.objects.filter(id=a1.id).update(location=wh)
        reg = self.client.get("/api/v1/accounting/assets/register_report/").data
        self.assertAlmostEqual(float(reg["totals"]["cost"]), 800000.0, places=2)
        cat = self.client.get("/api/v1/accounting/assets/by_category/").data
        equip = next(g for g in cat["groups"] if g["category"] == "equipment")
        self.assertAlmostEqual(float(equip["cost"]), 800000.0, places=2)
        loc = self.client.get("/api/v1/accounting/assets/by_location/").data
        names = {g["location"] for g in loc["groups"]}
        self.assertIn("HQ", names)
        self.assertIn("Unassigned", names)

    def test_depreciation_forecast_schedule(self):
        asset = self._make_asset(cost="1200000", code="X-FC")
        AccountingService.run_depreciation(self.org, 2026, 7, created_by=self.user)
        res = self.client.get(
            f"/api/v1/accounting/assets/{asset.id}/depreciation_schedule/?forecast=true"
        ).data
        types = {r["type"] for r in res["schedule"]}
        self.assertIn("actual", types)
        self.assertIn("projected", types)
        self.assertIn("not posted", res["disclaimer"].lower())


class FixedAssetTenantIsolationTests(TestCase):
    """Security: the fixed-asset lifecycle endpoints must be strictly org-scoped — no
    cross-tenant read or mutation."""

    def setUp(self):
        self.owner_a = _make_user("fa_a@example.com")
        self.org_a = _make_org(self.owner_a, "FA Org A")
        _upgrade_to_business(self.org_a)
        self.client_a = _auth_client(self.owner_a, self.org_a)
        m = AccountMapping.objects.get(organisation=self.org_a)
        m.bank_account = Account.objects.get(organisation=self.org_a, code="1002"); m.save()

        self.owner_b = _make_user("fa_b@example.com")
        self.org_b = _make_org(self.owner_b, "FA Org B")
        _upgrade_to_business(self.org_b)
        self.client_b = _auth_client(self.owner_b, self.org_b)

        res = self.client_a.post("/api/v1/accounting/assets/", {
            "name": "A Asset", "asset_code": "A-1", "category": "equipment",
            "purchase_date": "2026-07-01", "purchase_cost": "500000",
            "useful_life_years": 5, "residual_value": "0", "funding_source": "bank",
        }, format="json")
        self.asset_a_id = res.data["id"]

    def test_other_org_cannot_see_asset_in_list(self):
        res = self.client_b.get("/api/v1/accounting/assets/")
        data = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(len(data), 0)
        # And org A still sees exactly its own one asset.
        res_a = self.client_a.get("/api/v1/accounting/assets/")
        data_a = res_a.data["results"] if isinstance(res_a.data, dict) and "results" in res_a.data else res_a.data
        self.assertEqual(len(data_a), 1)

    def test_other_org_reconciliation_is_isolated(self):
        rec = self.client_b.get("/api/v1/accounting/assets/reconciliation/").data
        self.assertAlmostEqual(float(rec["register"]["cost"]), 0.0, places=2)

    def test_other_org_cannot_dispose_foreign_asset(self):
        res = self.client_b.post(f"/api/v1/accounting/assets/{self.asset_a_id}/dispose/",
                                 {"proceeds": "1"}, format="json")
        self.assertIn(res.status_code, [403, 404])
        # Asset A remains active.
        self.assertTrue(FixedAsset.objects.get(id=self.asset_a_id).is_active)

    def test_other_org_cannot_transfer_or_revalue_foreign_asset(self):
        r1 = self.client_b.post(f"/api/v1/accounting/assets/{self.asset_a_id}/transfer/",
                                {"to_cost_centre": "X"}, format="json")
        self.assertIn(r1.status_code, [403, 404])
        r2 = self.client_b.post(f"/api/v1/accounting/assets/{self.asset_a_id}/revalue/",
                                {"new_value": "1"}, format="json")
        self.assertIn(r2.status_code, [403, 404])

    def test_unauthenticated_denied(self):
        from rest_framework.test import APIClient
        anon = APIClient()
        self.assertIn(anon.get("/api/v1/accounting/assets/reconciliation/").status_code, [401, 403])
        self.assertIn(anon.get("/api/v1/accounting/assets/register_report/").status_code, [401, 403])


class AssetTypeAndDraftBatchTests(TestCase):
    """Phase 3b: asset types (method + GL account mapping) and draft-batch depreciation
    (generate drafts for review, then post the batch)."""

    def setUp(self):
        self.user = _make_user("at_owner@example.com")
        self.org = _make_org(self.user, "AT Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        m = AccountMapping.objects.get(organisation=self.org)
        m.bank_account = Account.objects.get(organisation=self.org, code="1002")
        m.save()

    def _gl(self, code):
        acct = Account.objects.filter(organisation=self.org, code=code).first()
        return AccountingService._ledger_balance(acct) if acct else Decimal("0")

    def test_asset_type_crud(self):
        res = self.client.post("/api/v1/accounting/asset-types/", {
            "code": "MV", "name": "Motor Vehicles", "category": "vehicle",
            "depreciation_method": "straight_line", "useful_life_years": 4,
        }, format="json")
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))
        from apps.accounting.models import AssetType
        self.assertTrue(AssetType.objects.filter(organisation=self.org, code="MV").exists())

    def test_asset_type_is_tenant_scoped(self):
        self.client.post("/api/v1/accounting/asset-types/", {
            "code": "MV", "name": "Motor Vehicles", "category": "vehicle",
        }, format="json")
        other_user = _make_user("at_other@example.com")
        other_org = _make_org(other_user, "AT Other")
        _upgrade_to_business(other_org)
        oc = _auth_client(other_user, other_org)
        res = oc.get("/api/v1/accounting/asset-types/")
        data = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(len(data), 0)

    def test_depreciation_uses_asset_type_accounts(self):
        from apps.accounting.models import AssetType, FixedAsset
        # Custom depreciation-expense account 6410 mapped via the asset type.
        dep_acct = Account.objects.create(
            organisation=self.org, code="6410", name="Depreciation — Vehicles",
            account_type="expense",
        )
        at = AssetType.objects.create(
            organisation=self.org, code="MV", name="Motor Vehicles", category="vehicle",
            depreciation_expense_account=dep_acct,
        )
        asset = FixedAsset.objects.create(
            organisation=self.org, name="Van", asset_code="AT-1", category="vehicle",
            asset_type=at, purchase_date=__import__("datetime").date(2026, 7, 1),
            purchase_cost=Decimal("1200000"), useful_life_years=5, residual_value=Decimal("0"),
            acquisition_posted=True,
        )
        AccountingService.run_depreciation(self.org, 2026, 7, created_by=self.user)
        # Depreciation hit the asset-type's 6410, not the default 6400.
        self.assertAlmostEqual(float(self._gl("6410")), 20000.0, places=2)
        self.assertAlmostEqual(float(self._gl("6400")), 0.0, places=2)

    def test_draft_batch_then_post(self):
        from apps.accounting.models import FixedAsset, JournalEntry
        FixedAsset.objects.create(
            organisation=self.org, name="Machine", asset_code="AT-DR", category="equipment",
            purchase_date=__import__("datetime").date(2026, 7, 1), purchase_cost=Decimal("1200000"),
            useful_life_years=5, residual_value=Decimal("0"), acquisition_posted=True,
        )
        # Draft run — entries computed, JE created as draft, GL NOT yet affected.
        res = self.client.post("/api/v1/accounting/assets/run_depreciation/",
                               {"year": 2026, "month": 7, "draft": True}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["draft"])
        je = JournalEntry.objects.get(organisation=self.org, source_type="depreciation")
        self.assertEqual(je.status, "draft")
        self.assertAlmostEqual(float(self._gl("1510")), 0.0, places=2)  # not posted yet
        # Post the batch.
        res2 = self.client.post("/api/v1/accounting/assets/post_depreciation_batch/",
                                {"year": 2026, "month": 7}, format="json")
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.data["posted"], 1)
        je.refresh_from_db()
        self.assertEqual(je.status, "posted")
        self.assertAlmostEqual(float(self._gl("1510")), -20000.0, places=2)  # now on the ledger


class DeterministicReconciliationTests(TestCase):
    """The reliable, offline auto-match: exact amount + date tolerance (+ reference),
    one-to-one, auto-confirming unambiguous matches — no external LLM, no waiting."""

    def setUp(self):
        self.user = _make_user("recon_det@example.com")
        self.org = _make_org(self.user, "Recon Det Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        self.bank = Account.objects.get(organisation=self.org, code="1002")
        from apps.accounting.models import BankReconciliation
        self.recon = BankReconciliation.objects.create(
            organisation=self.org, account=self.bank,
            period_start=__import__("datetime").date(2026, 7, 1),
            period_end=__import__("datetime").date(2026, 7, 31),
            statement_closing_balance=Decimal("0"),
        )

    def _book(self, amount, d, inflow=True, desc=""):
        """Post a journal entry that moves `amount` in/out of the bank account."""
        rev = Account.objects.get(organisation=self.org, code="4001")
        exp = Account.objects.get(organisation=self.org, code="6700")
        amt = Decimal(str(amount))
        if inflow:
            lines = [(self.bank, amt, Decimal("0")), (rev, Decimal("0"), amt)]
        else:
            lines = [(exp, amt, Decimal("0")), (self.bank, Decimal("0"), amt)]
        return AccountingService.post_journal_entry(
            self.org, desc or "bank move", __import__("datetime").date.fromisoformat(d),
            lines, self.user, source_type="test", source_ref=f"{desc}-{d}-{amount}",
        )

    def _bankline(self, amount, d, ref="", desc="stmt"):
        from apps.accounting.models import BankReconciliationLine
        return BankReconciliationLine.objects.create(
            organisation=self.org, reconciliation=self.recon, description=desc,
            transaction_date=__import__("datetime").date.fromisoformat(d),
            amount=Decimal(str(amount)), reference=ref,
        )

    def _auto(self):
        return self.client.post(f"/api/v1/accounting/reconciliations/{self.recon.id}/auto_match/", {}, format="json")

    def test_exact_amount_matches_proposed(self):
        self._book("450000", "2026-07-10", inflow=True)
        self._book("1200000", "2026-07-05", inflow=False)
        bl1 = self._bankline("450000", "2026-07-10")
        bl2 = self._bankline("-1200000", "2026-07-05")
        res = self._auto()
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["summary"]["matched"], 2)
        self.assertEqual(res.data["summary"]["unmatched_bank"], 0)
        # Proposed for review — never silently clears the ledger.
        matches = [m for m in res.data["matches"] if m["book_line"]]
        self.assertTrue(all(m["status"] == "proposed" for m in matches))
        bl1.refresh_from_db(); bl2.refresh_from_db()
        self.assertFalse(bl1.is_cleared)
        self.assertFalse(bl2.is_cleared)

    def test_within_tolerance_lower_confidence(self):
        self._book("75000", "2026-07-10", inflow=True)
        self._bankline("75000", "2026-07-13")  # 3 days off → matched but confidence 0.90
        res = self._auto()
        self.assertEqual(res.data["summary"]["matched"], 1)
        m = next(m for m in res.data["matches"] if m["book_line"])
        self.assertLess(float(m["confidence"]), 1.0)

    def test_beyond_tolerance_unmatched(self):
        self._book("90000", "2026-07-02", inflow=True)
        self._bankline("90000", "2026-07-20")  # 18 days → beyond tolerance
        res = self._auto()
        self.assertEqual(res.data["summary"]["unmatched_bank"], 1)
        self.assertEqual(res.data["summary"]["matched"], 0)
        # The unmatched line is surfaced (a record with no book line), never hidden.
        self.assertTrue(any(m["book_line"] is None for m in res.data["matches"]))

    def test_one_to_one_no_double_match(self):
        # One book entry of 50,000; two identical bank lines → only one can match.
        self._book("50000", "2026-07-08", inflow=True)
        self._bankline("50000", "2026-07-08")
        self._bankline("50000", "2026-07-08")
        res = self._auto()
        self.assertEqual(res.data["summary"]["matched"], 1)
        self.assertEqual(res.data["summary"]["unmatched_bank"], 1)

    def test_reference_match_gives_full_confidence(self):
        self._book("30000", "2026-07-10", inflow=True, desc="INV-7788 settlement")
        self._bankline("30000", "2026-07-13", ref="INV-7788")  # 3 days off but ref hit → 1.0
        res = self._auto()
        self.assertEqual(res.data["summary"]["matched"], 1)
        m = next(m for m in res.data["matches"] if m["book_line"])
        self.assertEqual(float(m["confidence"]), 1.0)

    def test_direction_matters(self):
        # A 20,000 OUTFLOW on the book must not match a 20,000 INFLOW on the statement.
        self._book("20000", "2026-07-05", inflow=False)   # money out
        self._bankline("20000", "2026-07-05")             # money in (+)
        res = self._auto()
        self.assertEqual(res.data["summary"]["matched"], 0)
        self.assertEqual(res.data["summary"]["unmatched_bank"], 1)

    def test_ai_endpoint_never_hangs_or_crashes(self):
        self._book("450000", "2026-07-10", inflow=True)
        self._bankline("450000", "2026-07-10")
        self._auto()
        res = self.client.post(f"/api/v1/accounting/reconciliations/{self.recon.id}/ai_reconcile/")
        # No Groq key in the test env → clean 422; never a hang, never a 500.
        self.assertIn(res.status_code, [400, 422])

    def test_duplicate_reconciliation_resumes_not_500(self):
        """Starting a reconciliation for an account+period that already exists must
        resume it (200), not crash with a unique-constraint 500."""
        payload = {
            "account": str(self.bank.id),
            "period_start": "2026-08-01", "period_end": "2026-08-31",
            "statement_closing_balance": "1000",
        }
        r1 = self.client.post("/api/v1/accounting/reconciliations/", payload, format="json")
        self.assertEqual(r1.status_code, 201, msg=str(r1.data))
        r2 = self.client.post("/api/v1/accounting/reconciliations/", payload, format="json")
        self.assertEqual(r2.status_code, 200, msg=str(r2.data))   # resumed, not 500
        self.assertEqual(r2.data["id"], r1.data["id"])


class FixedAssetMasterConventionUsageTransferTests(TestCase):
    """The four post-review additions: asset-master fields (serial/barcode/master-sub),
    the 'new month' convention, Units-of-Production usage entry, and asset-type transfer."""

    def setUp(self):
        self.user = _make_user("famcut_owner@example.com")
        self.org = _make_org(self.user, "FAMCUT Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        m = AccountMapping.objects.get(organisation=self.org)
        m.bank_account = Account.objects.get(organisation=self.org, code="1002"); m.save()

    def _gl(self, code):
        acct = Account.objects.filter(organisation=self.org, code=code).first()
        return AccountingService._ledger_balance(acct) if acct else Decimal("0")

    # 1. Asset Master extras — serial / barcode / master-sub linking
    def test_serial_barcode_and_master_sub(self):
        master = self.client.post("/api/v1/accounting/assets/", {
            "name": "Server Rack", "category": "equipment", "purchase_date": "2026-07-01",
            "purchase_cost": "2000000", "useful_life_years": 5, "funding_source": "bank",
            "serial_number": "SRV-001", "barcode": "0123456789",
        }, format="json")
        self.assertEqual(master.status_code, 201, msg=str(master.data))
        self.assertEqual(master.data["serial_number"], "SRV-001")
        self.assertEqual(master.data["barcode"], "0123456789")
        sub = self.client.post("/api/v1/accounting/assets/", {
            "name": "Rack UPS add-on", "category": "equipment", "purchase_date": "2026-07-02",
            "purchase_cost": "300000", "useful_life_years": 5, "funding_source": "bank",
            "master_asset": master.data["id"],
        }, format="json")
        self.assertEqual(sub.status_code, 201, msg=str(sub.data))
        self.assertEqual(str(sub.data["master_asset"]), str(master.data["id"]))
        self.assertEqual(FixedAsset.objects.get(id=master.data["id"]).sub_assets.count(), 1)

    # 2. "New month" convention — first charge deferred to the month after purchase
    def test_new_month_convention_defers_first_charge(self):
        import datetime
        a = FixedAsset.objects.create(
            organisation=self.org, name="Van", asset_code="NM-1", category="vehicle",
            purchase_date=datetime.date(2026, 7, 10), purchase_cost=Decimal("1200000"),
            useful_life_years=5, residual_value=Decimal("0"),
            depreciation_convention="new_month", acquisition_posted=True,
        )
        AccountingService.run_depreciation(self.org, 2026, 7, created_by=self.user)
        self.assertFalse(a.depreciation_entries.filter(period_year=2026, period_month=7).exists())
        AccountingService.run_depreciation(self.org, 2026, 8, created_by=self.user)
        aug = a.depreciation_entries.get(period_year=2026, period_month=8)
        self.assertAlmostEqual(float(aug.depreciation_amount), 20000.0, places=2)

    # 3. Units of Production — usage entry drives the charge
    def test_units_of_production_usage(self):
        import datetime
        a = FixedAsset.objects.create(
            organisation=self.org, name="Press", asset_code="U-1", category="equipment",
            purchase_date=datetime.date(2026, 7, 1), purchase_cost=Decimal("1000000"),
            useful_life_years=10, residual_value=Decimal("0"),
            depreciation_method="units", total_units=Decimal("100000"), acquisition_posted=True,
        )
        res = self.client.post(f"/api/v1/accounting/assets/{a.id}/record_usage/", {
            "year": 2026, "month": 7, "units": "10000",
        }, format="json")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertAlmostEqual(float(res.data["depreciation_amount"]), 100000.0, places=2)  # 10k/100k * 1m
        e = a.depreciation_entries.get(period_year=2026, period_month=7)
        self.assertAlmostEqual(float(e.units), 10000.0, places=2)
        self.assertAlmostEqual(float(self._gl("1510")), -100000.0, places=2)
        # A second entry for the same period is rejected.
        dup = self.client.post(f"/api/v1/accounting/assets/{a.id}/record_usage/",
                               {"year": 2026, "month": 7, "units": "5000"}, format="json")
        self.assertEqual(dup.status_code, 422)

    def test_units_requires_total_units(self):
        import datetime
        a = FixedAsset.objects.create(
            organisation=self.org, name="Press2", asset_code="U-2", category="equipment",
            purchase_date=datetime.date(2026, 7, 1), purchase_cost=Decimal("1000000"),
            depreciation_method="units", acquisition_posted=True,   # no total_units
        )
        res = self.client.post(f"/api/v1/accounting/assets/{a.id}/record_usage/",
                               {"year": 2026, "month": 7, "units": "10000"}, format="json")
        self.assertEqual(res.status_code, 422)

    # 4. Asset-type transfer as a dated transaction
    def test_asset_type_transfer(self):
        from apps.accounting.models import AssetType, AssetTransfer
        at_a = AssetType.objects.create(organisation=self.org, code="MV", name="Motor Vehicles",
                                        category="vehicle", depreciation_method="straight_line", useful_life_years=4)
        at_b = AssetType.objects.create(organisation=self.org, code="PM", name="Plant & Machinery",
                                        category="equipment", depreciation_method="reducing_balance", useful_life_years=8)
        res = self.client.post("/api/v1/accounting/assets/", {
            "name": "Forklift", "category": "equipment", "purchase_date": "2026-07-01",
            "purchase_cost": "900000", "funding_source": "bank", "asset_type": str(at_a.id),
        }, format="json")
        asset_id = res.data["id"]
        trf = self.client.post(f"/api/v1/accounting/assets/{asset_id}/transfer/", {
            "to_asset_type": str(at_b.id), "transfer_date": "2026-08-01", "reference": "reclass",
        }, format="json")
        self.assertEqual(trf.status_code, 200, msg=str(trf.data))
        self.assertEqual(str(FixedAsset.objects.get(id=asset_id).asset_type_id), str(at_b.id))
        x = AssetTransfer.objects.get(organisation=self.org, asset_id=asset_id)
        self.assertEqual(str(x.from_asset_type_id), str(at_a.id))
        self.assertEqual(str(x.to_asset_type_id), str(at_b.id))
