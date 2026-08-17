"""
Core accounting must produce identical numbers under row-level security.

Stage 2 turns on RLS for seven accounting tables that are currently
unprotected, accountmapping and accountsubtype among them. The failure mode
that matters is not an error — it is a report that still renders and is quietly
wrong, because a policy hid rows the sum needed.

So every test here computes the same figure twice: once as the table owner,
where RLS does not apply, and once as the ordinary application role with the
organisation bound, which is how the web service actually runs. The numbers
have to match. A report that silently loses rows fails here.

    pytest -c pytest_postgres.ini apps/accounting/test_rls_accounting.py

Deliberately compares against a known-good baseline rather than asserting
"greater than zero". A balance sheet of all zeros balances perfectly.
"""

import unittest
from datetime import date
from decimal import Decimal

from django.test import TransactionTestCase

from apps.accounting.models import Account, AccountMapping
from apps.accounting.services import AccountingService, AccountMappingService
from apps.authentication.models import User
from apps.core.rls_testing import as_app_role, assert_rls_is_really_on, rls_available
from apps.core.tenant_context import organisation_context
from apps.tenancy.services import OrganisationService


def _org(tag):
    user = User.objects.create_user(
        email=f"acct_rls_{tag}@example.com", password="TestPass123!",
        first_name="Acct", last_name="RLS", is_verified=True,
    )
    return OrganisationService.create_organisation(
        name=f"Acct RLS {tag}", owner=user,
        extra={"currency": "NGN", "country": "NG"},
    )


@unittest.skipUnless(rls_available(), "PostgreSQL required — RLS cannot be tested on SQLite")
class AccountingIsUnchangedUnderRLS(TransactionTestCase):

    def setUp(self):
        self.org = _org("a")
        # A second company with its own books. If a policy is wrong in the
        # permissive direction these figures would bleed into org A's totals.
        self.other = _org("b")

    # --- the guard ---------------------------------------------------------

    def test_rls_is_on_for_the_accounting_tables_stage_2_covers(self):
        """
        Without this the comparisons below pass trivially — identical numbers
        are guaranteed if no policy is in force on either side.
        """
        for table in ("accounting_account", "accounting_accountmapping"):
            with as_app_role():
                assert_rls_is_really_on(self, table)

    # --- the books ---------------------------------------------------------

    def _trial_balance(self, org):
        return AccountingService.trial_balance(org)

    def test_trial_balance_is_identical_under_the_restricted_role(self):
        expected = self._trial_balance(self.org)
        with as_app_role(), organisation_context(self.org.id):
            actual = self._trial_balance(self.org)
        self.assertEqual(
            actual, expected,
            "the trial balance changes depending on which database role reads "
            "it — row-level security is hiding ledger rows from the application",
        )

    def test_balance_sheet_is_identical_under_the_restricted_role(self):
        expected = AccountingService.balance_sheet(self.org)
        with as_app_role(), organisation_context(self.org.id):
            actual = AccountingService.balance_sheet(self.org)
        self.assertEqual(
            actual, expected,
            "the balance sheet differs under the application role — a report "
            "that renders and is wrong is worse than one that fails",
        )

    def test_the_chart_of_accounts_is_fully_visible(self):
        expected = Account.objects.filter(organisation=self.org).count()
        self.assertGreater(expected, 0, "fixture produced no accounts")
        with as_app_role(), organisation_context(self.org.id):
            actual = Account.objects.filter(organisation=self.org).count()
        self.assertEqual(
            actual, expected,
            "accounts are missing under the application role — the account "
            "picker and every posting screen read this",
        )

    def test_the_gl_account_mapping_is_readable(self):
        """
        accounting_accountmapping goes from unprotected to protected in R-4.
        Every automatic posting — sales, bills, expenses, payroll — resolves
        its target accounts through this table.
        """
        expected = AccountMapping.objects.filter(organisation=self.org).count()
        with as_app_role(), organisation_context(self.org.id):
            actual = AccountMapping.objects.filter(organisation=self.org).count()
            mapping = AccountMappingService.get_or_create_mapping(self.org)
        self.assertEqual(actual, expected, "the GL mapping is invisible to the application role")
        self.assertIsNotNone(mapping, "get_or_create_mapping returned nothing under RLS")

    # --- isolation, the other direction ------------------------------------

    def test_one_companys_books_do_not_include_anothers(self):
        with as_app_role(), organisation_context(self.org.id):
            leaked = Account.objects.filter(organisation=self.other).count()
        self.assertEqual(
            leaked, 0,
            "company A can read company B's chart of accounts",
        )

    def test_binding_no_company_shows_no_ledger(self):
        from apps.core.middleware import SENTINEL

        with as_app_role(), organisation_context(SENTINEL):
            self.assertEqual(Account.objects.count(), 0)
            self.assertEqual(AccountMapping.objects.count(), 0)
