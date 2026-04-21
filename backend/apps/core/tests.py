"""
Tests for TenantFilterMixin: tenant isolation, RLS session sync, and cross-tenant
access prevention.

These tests exercise the _get_organisation() logic that was fixed to call
_set_org() after membership validation — ensuring the DB-level RLS session
variable always matches the application-level org, never diverges.
"""

from unittest.mock import MagicMock, call, patch

from django.test import TestCase, RequestFactory
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.core.exceptions import TenantViolationError
from apps.core.mixins import TenantFilterMixin
from apps.tenancy.models import Membership, Organisation
from apps.tenancy.services import OrganisationService


# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_user(email="core_owner@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Core", last_name="User", is_verified=True,
    )


def _make_org(user, name="Core Test Org"):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _auth_client(user, org):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return client


# ── Unit tests for _get_organisation() ───────────────────────────────────────

class GetOrganisationUnitTests(TestCase):
    """
    Unit-test _get_organisation() in isolation using mocks.

    These do not hit the database for the mixin logic — they verify the
    call sequence: resolve_organisation → _set_org → return org.
    """

    def _make_mixin_instance(self, organisation=None):
        """Create a minimal TenantFilterMixin instance with a mocked request."""
        mixin = TenantFilterMixin()
        mixin.request = MagicMock()
        mixin.request.user = MagicMock()
        mixin.request.user.id = "test-user-id"
        mixin.request.organisation = organisation
        return mixin

    def test_returns_cached_org_when_already_set(self):
        """If request.organisation is already populated, return it without re-resolving."""
        fake_org = MagicMock()
        mixin = self._make_mixin_instance(organisation=fake_org)

        with patch("apps.tenancy.middleware.resolve_organisation") as mock_resolve:
            result = mixin._get_organisation()

        self.assertIs(result, fake_org)
        mock_resolve.assert_not_called()

    def test_calls_set_org_after_resolution(self):
        """
        Critical: after resolve_organisation() returns a validated org,
        _set_org must be called with the org's UUID so the DB session
        variable matches the app-level org.

        This is the core of the RLS sync fix.
        """
        mixin = self._make_mixin_instance(organisation=None)

        fake_org = MagicMock()
        fake_org.id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        with patch("apps.tenancy.middleware.resolve_organisation", return_value=fake_org), \
             patch("apps.core.middleware._set_org") as mock_set_org:
            result = mixin._get_organisation()

        self.assertIs(result, fake_org)
        mock_set_org.assert_called_once_with("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    def test_raises_tenant_violation_when_org_not_resolved(self):
        """If resolve_organisation() returns None, TenantViolationError must be raised."""
        mixin = self._make_mixin_instance(organisation=None)

        with patch("apps.tenancy.middleware.resolve_organisation", return_value=None), \
             patch("apps.core.middleware._set_org") as mock_set_org:
            with self.assertRaises(TenantViolationError):
                mixin._get_organisation()

        mock_set_org.assert_not_called()

    def test_set_org_exception_does_not_propagate(self):
        """
        An exception in _set_org (e.g. SQLite, network blip) must never
        prevent the request from completing — it must be swallowed.
        """
        mixin = self._make_mixin_instance(organisation=None)

        fake_org = MagicMock()
        fake_org.id = "11111111-2222-3333-4444-555555555555"

        with patch("apps.tenancy.middleware.resolve_organisation", return_value=fake_org), \
             patch("apps.core.middleware._set_org", side_effect=Exception("DB connection lost")):
            # Should NOT raise — the exception must be caught internally
            result = mixin._get_organisation()

        self.assertIs(result, fake_org)

    def test_set_org_called_with_string_not_uuid_object(self):
        """
        _set_org receives a plain string, not a UUID object.
        PostgreSQL set_config() requires a string; passing a UUID would
        fail silently or raise a TypeError.
        """
        mixin = self._make_mixin_instance(organisation=None)

        import uuid
        fake_org = MagicMock()
        fake_org.id = uuid.UUID("cafecafe-cafe-cafe-cafe-cafecafecafe")

        with patch("apps.tenancy.middleware.resolve_organisation", return_value=fake_org), \
             patch("apps.core.middleware._set_org") as mock_set_org:
            mixin._get_organisation()

        args, _ = mock_set_org.call_args
        self.assertIsInstance(args[0], str)
        self.assertEqual(args[0], "cafecafe-cafe-cafe-cafe-cafecafecafe")


# ── Integration tests: cross-tenant isolation ─────────────────────────────────

class TenantIsolationIntegrationTests(TestCase):
    """
    Integration tests that call real API endpoints and verify that data
    belonging to one organisation is never visible to another.
    """

    def setUp(self):
        self.user_a = _make_user("tenant_a@example.com")
        self.user_b = _make_user("tenant_b@example.com")
        self.org_a = _make_org(self.user_a, "Org Alpha")
        self.org_b = _make_org(self.user_b, "Org Beta")
        self.client_a = _auth_client(self.user_a, self.org_a)
        self.client_b = _auth_client(self.user_b, self.org_b)

    def test_user_a_cannot_read_org_b_products(self):
        """Products created in Org B must be invisible to Org A."""
        # Create a product in Org B
        res = self.client_b.post("/api/v1/inventory/products/", {
            "sku": "CROSS-TENANT-SKU",
            "name": "Org B Secret Product",
            "selling_price": "100.00",
            "cost_price": "50.00",
            "product_type": "physical",
        })
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        product_id = res.data["id"]

        # Org A cannot list it
        res_list = self.client_a.get("/api/v1/inventory/products/")
        self.assertEqual(res_list.status_code, 200)
        results = res_list.data.get("results") if isinstance(res_list.data, dict) else res_list.data
        ids = [p["id"] for p in (results or [])]
        self.assertNotIn(product_id, ids)

        # Org A cannot retrieve it directly
        res_detail = self.client_a.get(f"/api/v1/inventory/products/{product_id}/")
        self.assertIn(res_detail.status_code, [403, 404])

    def test_user_a_cannot_modify_org_b_product(self):
        """PATCH/PUT to another org's product must be blocked."""
        res = self.client_b.post("/api/v1/inventory/products/", {
            "sku": "MODIFY-BLOCK",
            "name": "Org B Protected",
            "selling_price": "200.00",
            "cost_price": "100.00",
            "product_type": "physical",
        })
        self.assertEqual(res.status_code, 201)
        product_id = res.data["id"]

        res_patch = self.client_a.patch(
            f"/api/v1/inventory/products/{product_id}/",
            {"name": "Hijacked name"},
            format="json",
        )
        self.assertIn(res_patch.status_code, [403, 404])

        # Confirm the product is still intact in Org B
        res_check = self.client_b.get(f"/api/v1/inventory/products/{product_id}/")
        self.assertEqual(res_check.status_code, 200)
        self.assertEqual(res_check.data["name"], "Org B Protected")

    def test_unauthenticated_request_blocked(self):
        """Requests with no JWT must be rejected before any data is accessed."""
        anon = APIClient()
        res = anon.get("/api/v1/inventory/products/")
        self.assertIn(res.status_code, [401, 403])

    def test_wrong_org_header_blocked(self):
        """
        A valid JWT for User A with Org B's ID in the header must be blocked
        (no membership → TenantViolationError → 403).
        """
        bad_client = APIClient()
        refresh = RefreshToken.for_user(self.user_a)
        bad_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
            HTTP_X_ORGANISATION_ID=str(self.org_b.id),  # org A user claims org B
        )
        res = bad_client.get("/api/v1/inventory/products/")
        self.assertIn(res.status_code, [403, 404])

    def test_member_can_only_see_own_org_customers(self):
        """Customers created in Org A are not visible from Org B."""
        self.client_a.post("/api/v1/customers/", {
            "name": "Alpha Corp",
            "email": "alpha@corp.com",
        })
        res = self.client_b.get("/api/v1/customers/")
        self.assertEqual(res.status_code, 200)
        results = res.data.get("results") if isinstance(res.data, dict) else res.data
        names = [c["name"] for c in (results or [])]
        self.assertNotIn("Alpha Corp", names)


# ── RLS fallback-path sync test ───────────────────────────────────────────────

class RLSSyncFallbackTest(TestCase):
    """
    Verifies the specific bug scenario that was fixed:

    BEFORE the fix:
        - User sends no X-Organisation-ID header
        - RLSMiddleware sets DB session to SENTINEL
        - resolve_organisation() returns user's first org (fallback path)
        - DB session stayed SENTINEL → RLS blocked all queries

    AFTER the fix:
        - _get_organisation() calls _set_org(org.id) after validation
        - DB session is corrected to the validated org
        - Queries succeed

    We can't exercise real PostgreSQL RLS in SQLite tests, but we can verify
    that _set_org is called with the fallback org's ID — which is the
    correction the fix introduces.
    """

    def test_fallback_resolution_triggers_set_org(self):
        """
        When no header is sent, resolve_organisation falls back to the user's
        first org. _get_organisation() must then call _set_org with that org's
        ID to correct the DB session (which RLSMiddleware left as SENTINEL).
        """
        user = _make_user("fallback_test@example.com")
        org = _make_org(user, "Fallback Org")

        mixin = TenantFilterMixin()
        mixin.request = MagicMock()
        mixin.request.user = user
        mixin.request.organisation = None  # Simulates: no header, TenantMiddleware set None
        # Also simulate no _raw_org_id so resolve_organisation uses fallback path
        mixin.request._raw_org_id = None

        with patch("apps.core.middleware._set_org") as mock_set_org:
            # Call the real resolve_organisation (no mock) + real _set_org spy
            result = mixin._get_organisation()

        self.assertIsNotNone(result)
        self.assertEqual(result.id, org.id)
        # The critical assertion: _set_org was called with the fallback org's UUID
        # (may be called more than once — belt-and-suspenders — but always with the right ID)
        mock_set_org.assert_called_with(str(org.id))
        self.assertGreaterEqual(mock_set_org.call_count, 1)
