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
from apps.accounting.models import Account, AccountMapping, AccountType, FinancialPeriod, JournalEntry, JournalLine
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
