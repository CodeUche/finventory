"""
Row-level-security integration tests (finding NEW-8).

These are the tests the SQLite suite structurally cannot provide. They require
PostgreSQL and are skipped otherwise::

    pytest -c pytest_postgres.ini apps/core/test_rls_integration.py

What they establish, in order of importance:

1. RLS is genuinely in force (not vacuously passing) — assert_rls_is_really_on.
2. A tenant sees its own rows and none of another tenant's.
3. Code running WITHOUT org context sees nothing — the NEW-7 failure mode.
4. Scheduled tasks, run through for_each_organisation, see each tenant's rows.

Test 3 is the important one. It fails against the pre-NEW-7 task code and
passes after, which is exactly the signal the old suite could never produce.

All data here is synthetic. No production data is copied into any test
environment.
"""

import uuid

from django.db import connection
from django.test import TestCase, tag
from django.test.utils import override_settings

from apps.authentication.models import User
from apps.core.middleware import SENTINEL, _set_org
from apps.core.rls_testing import as_app_role, assert_rls_is_really_on, rls_available
from apps.core.tenant_context import for_each_organisation, organisation_context
from apps.tenancy.services import OrganisationService

import unittest


def _make_org(email, name):
    user = User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="T", last_name="U", is_verified=True,
    )
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


@unittest.skipUnless(rls_available(), "PostgreSQL required — RLS cannot be tested on SQLite")
@tag("rls")
class TenantIsolationTests(TestCase):
    """Two synthetic tenants; prove the database keeps them apart."""

    def setUp(self):
        from apps.customers.models import Customer

        self.org_a = _make_org(f"rls_a_{uuid.uuid4().hex[:8]}@example.com", "RLS Org A")
        self.org_b = _make_org(f"rls_b_{uuid.uuid4().hex[:8]}@example.com", "RLS Org B")

        # Created as the owner (RLS not applied), which is what the app's own
        # service layer does during setup.
        self.cust_a = Customer.objects.create(organisation=self.org_a, name="Customer A")
        self.cust_b = Customer.objects.create(organisation=self.org_b, name="Customer B")
        _set_org(SENTINEL)

    def tearDown(self):
        _set_org(SENTINEL)

    def test_rls_is_actually_enforced(self):
        """Fails loudly if the suite would otherwise pass vacuously."""
        with as_app_role():
            assert_rls_is_really_on(self, "customers_customer")

    def test_tenant_sees_only_its_own_rows(self):
        from apps.customers.models import Customer

        with as_app_role(), organisation_context(self.org_a.id):
            names = set(Customer.objects.values_list("name", flat=True))
        self.assertEqual(
            names, {"Customer A"},
            "org A saw rows outside its own tenant — isolation is broken",
        )

    def test_other_tenants_rows_are_invisible(self):
        from apps.customers.models import Customer

        with as_app_role(), organisation_context(self.org_a.id):
            leaked = Customer.objects.filter(id=self.cust_b.id).exists()
        self.assertFalse(
            leaked,
            "org A could read org B's customer by primary key — cross-tenant leak",
        )

    def test_legitimate_owner_still_sees_its_data(self):
        """
        The positive half. RLS failures are silent — a wrong policy hides rows
        rather than erroring — so asserting presence matters as much as absence.
        """
        from apps.customers.models import Customer

        with as_app_role(), organisation_context(self.org_b.id):
            names = set(Customer.objects.values_list("name", flat=True))
        self.assertEqual(
            names, {"Customer B"},
            "org B could not see its OWN data — policy is too restrictive",
        )


@unittest.skipUnless(rls_available(), "PostgreSQL required — RLS cannot be tested on SQLite")
@tag("rls")
class MissingOrgContextTests(TestCase):
    """
    Reproducer for NEW-7.

    Celery does not run RLSMiddleware, so a task inherits the SENTINEL org id,
    which matches no row. Before the fix every scheduled sweep silently
    processed nothing while logging success.
    """

    def setUp(self):
        from apps.customers.models import Customer

        self.org = _make_org(f"rls_ctx_{uuid.uuid4().hex[:8]}@example.com", "RLS Ctx Org")
        Customer.objects.create(organisation=self.org, name="Ctx Customer")
        _set_org(SENTINEL)

    def tearDown(self):
        _set_org(SENTINEL)

    def test_without_org_context_a_task_sees_nothing(self):
        """
        This is the exact production failure: data exists, the query succeeds,
        and zero rows come back. No exception is raised anywhere.
        """
        from apps.customers.models import Customer

        with as_app_role():
            _set_org(SENTINEL)
            visible = Customer.objects.count()

        self.assertEqual(
            visible, 0,
            "expected the SENTINEL to hide all rows; if this fails, RLS is not "
            "being enforced and the rest of this suite proves nothing",
        )

        # ...and the same query inside a context sees the row. The contrast is
        # the point: identical code, different context, opposite result.
        with as_app_role(), organisation_context(self.org.id):
            visible_in_context = Customer.objects.count()
        self.assertEqual(
            visible_in_context, 1,
            "for_each_organisation's context did not make the tenant's own rows "
            "visible — scheduled tasks would still process nothing (NEW-7)",
        )

    def test_for_each_organisation_sees_each_tenants_rows(self):
        """End-to-end: the helper the 13 converted tasks rely on."""
        from apps.customers.models import Customer

        seen = {}

        def _count(org):
            seen[org.name] = Customer.objects.count()
            return seen[org.name]

        with as_app_role():
            result = for_each_organisation(_count, task_name="test")

        self.assertGreaterEqual(result["organisations"], 1)
        self.assertEqual(
            seen.get("RLS Ctx Org"), 1,
            "the sweep saw zero rows for a tenant that has data — this is "
            "precisely the NEW-7 regression",
        )
        self.assertEqual(result["failed"], 0)
