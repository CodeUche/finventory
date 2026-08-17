"""
NEW-18 — a new organisation must actually get its opening data.

This is the test the SQLite suite structurally cannot provide. Row-level
security does not exist on SQLite, so the bug is invisible there: every seeding
INSERT succeeds and the suite stays green while production silently creates
empty organisations.

    pytest -c pytest_postgres.ini apps/tenancy/test_org_seeding_rls.py

What went wrong
---------------
create_organisation sets both RLS GUCs transaction-locally inside its
atomic() block, then seeds AFTER that block commits. By then the setting is
back to the SENTINEL org, which matches no row, so the policy's WITH CHECK
refused every insert. Each seeder caught its own exception and logged a
warning, so nothing surfaced.

13 of the 24 organisations in production have no chart of accounts because of
this. All 13 were created after the commit that introduced the atomic block;
none of the 5 created before it are affected.
"""

import unittest
import uuid

from django.test import TransactionTestCase

from apps.accounting.models import Account
from apps.authentication.models import User
from apps.core.rls_testing import as_app_role, assert_rls_is_really_on, rls_available
from apps.tax.models import TaxConfig
from apps.tenancy.services import OrganisationService


def _new_owner():
    return User.objects.create_user(
        email=f"seed_{uuid.uuid4().hex[:8]}@example.com",
        password="TestPass123!",
        first_name="Seed", last_name="Owner", is_verified=True,
    )


@unittest.skipUnless(
    rls_available(), "PostgreSQL required — this bug cannot occur on SQLite"
)
class NewOrganisationIsSeededUnderRLS(TransactionTestCase):
    """
    Created as the unprivileged role, which is what the web service uses.

    Running as the owner/superuser role would bypass RLS entirely and the test
    would pass against the broken code — the reason the existing suite never
    caught this.
    """

    def test_the_policy_is_actually_on(self):
        """
        Guard against a vacuous pass. If RLS were off on this table the
        seeding assertions below would succeed no matter what the code did.
        """
        with as_app_role():
            assert_rls_is_really_on(self, "accounting_account")

    def test_a_new_organisation_gets_its_chart_of_accounts(self):
        owner = _new_owner()
        with as_app_role():
            org = OrganisationService.create_organisation(
                name=f"Seed Test {uuid.uuid4().hex[:6]}",
                owner=owner,
                extra={"currency": "NGN", "country": "NG"},
            )

        accounts = Account.objects.filter(organisation=org).count()
        self.assertGreater(
            accounts, 0,
            "the new organisation has no chart of accounts — it would land on "
            "an empty account picker and could not start a reconciliation",
        )

    def test_a_new_organisation_gets_its_tax_configuration(self):
        owner = _new_owner()
        with as_app_role():
            org = OrganisationService.create_organisation(
                name=f"Seed Tax {uuid.uuid4().hex[:6]}",
                owner=owner,
                extra={"currency": "NGN", "country": "NG"},
            )

        self.assertGreater(
            TaxConfig.objects.filter(organisation=org).count(), 0,
            "the new organisation has no tax configuration, so income tax "
            "calculation raises ValueError for it",
        )

    def test_the_context_is_handed_back_clean(self):
        """
        Seeding must not leave a live tenant bound to the connection. It runs
        outside the request's own context, and whatever executes next on this
        connection would inherit it.
        """
        from django.db import connection

        from apps.core.middleware import SENTINEL

        owner = _new_owner()
        with as_app_role():
            OrganisationService.create_organisation(
                name=f"Seed Ctx {uuid.uuid4().hex[:6]}",
                owner=owner,
                extra={"currency": "NGN", "country": "NG"},
            )
            with connection.cursor() as cur:
                cur.execute("SELECT current_setting('app.current_org_id', TRUE)")
                left_behind = cur.fetchone()[0]

        self.assertEqual(
            left_behind, SENTINEL,
            "org creation left a live tenant context on the connection",
        )
