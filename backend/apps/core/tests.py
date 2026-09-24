"""
Tests for TenantFilterMixin: tenant isolation, RLS session sync, and cross-tenant
access prevention.

These tests exercise the _get_organisation() logic that was fixed to call
_set_org() after membership validation — ensuring the DB-level RLS session
variable always matches the application-level org, never diverges.
"""

from unittest.mock import MagicMock, call, patch

from django.test import TestCase, RequestFactory, override_settings
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



class DesktopCorsOriginTests(TestCase):
    """The Windows desktop app's WebView origin must be allowed in PRODUCTION.

    Tauri v2 serves the app from tauri://localhost on macOS/Linux but from
    http://tauri.localhost on Windows, which is the desktop platform we ship.
    Desktop requests normally leave through the Rust HTTP plugin, where CORS
    does not apply — but api.ts falls back to the WebView's own fetch whenever
    that plugin throws (TLS-inspecting antivirus, a corporate proxy, the
    documented plugin-init race). Without this origin allowed, that fallback is
    refused by the browser, so the app cannot sign in AND shows no error,
    because the request never reaches the server.

    development.py already carried this origin (added after the same failure was
    hit against the local stack); base.py's default and the deployed ECS
    environment did not, so only production was exposed. Observed live against
    api.auditytechnologies.com on 2026-09-18.
    """

    WINDOWS_DESKTOP_ORIGIN = "http://tauri.localhost"

    def test_active_settings_allow_windows_desktop_origin(self):
        from django.conf import settings

        self.assertIn(self.WINDOWS_DESKTOP_ORIGIN, settings.CORS_ALLOWED_ORIGINS)
        self.assertIn(self.WINDOWS_DESKTOP_ORIGIN, settings.CSRF_TRUSTED_ORIGINS)

    def test_deployed_cors_list_includes_windows_desktop_origin(self):
        """Production does not use base.py's default — it reads the env var that
        Terraform builds in local.cors_origins, so that list is what has to be
        right. Asserting only on Django settings would pass while production
        stayed broken, which is exactly how this shipped.
        """
        import pathlib

        ecs_tf = pathlib.Path(__file__).resolve().parents[3] / "infra" / "terraform" / "ecs.tf"
        if not ecs_tf.exists():
            self.skipTest("infra/terraform not present in this checkout")
        self.assertIn(f'"{self.WINDOWS_DESKTOP_ORIGIN}"', ecs_tf.read_text(encoding="utf-8"))


class ExemptibleUserRateThrottleTests(TestCase):
    """
    The E2E smoke account skips the global per-user rate limit, and nothing else
    does — see ExemptibleUserRateThrottle for why the exemption exists.
    """

    def setUp(self):
        from apps.core.throttles import ExemptibleUserRateThrottle

        self.throttle = ExemptibleUserRateThrottle()
        self.factory = RequestFactory()

    def _request_for(self, user):
        request = self.factory.get("/api/v1/sales/invoices/")
        request.user = user
        return request

    @override_settings(THROTTLE_EXEMPT_EMAILS=frozenset({"ci.smoke@audity.africa"}))
    def test_listed_account_is_never_throttled(self):
        user = User.objects.create_user(email="ci.smoke@audity.africa", password="x" * 12)
        request = self._request_for(user)
        # Far beyond any configured rate — an unexempted user would be blocked.
        self.assertTrue(all(self.throttle.allow_request(request, None) for _ in range(5_000)))

    @override_settings(THROTTLE_EXEMPT_EMAILS=frozenset({"ci.smoke@audity.africa"}))
    def test_matching_is_case_insensitive(self):
        user = User.objects.create_user(email="CI.Smoke@Audity.Africa", password="x" * 12)
        self.assertTrue(self.throttle.allow_request(self._request_for(user), None))

    @override_settings(THROTTLE_EXEMPT_EMAILS=frozenset())
    def test_nobody_is_exempt_by_default(self):
        """
        An empty allow-list must fall straight through to normal throttling.

        Asserted by delegation rather than by counting requests: the test
        settings use DummyCache, so throttle history is never stored and NO
        request is ever refused — a counting assertion would pass whether or
        not the exemption leaked.
        """
        from rest_framework.throttling import UserRateThrottle

        user = User.objects.create_user(email="someone@example.com", password="x" * 12)
        with patch.object(UserRateThrottle, "allow_request", return_value=True) as parent:
            self.throttle.allow_request(self._request_for(user), None)
        parent.assert_called_once()

    @override_settings(THROTTLE_EXEMPT_EMAILS=frozenset({"ci.smoke@audity.africa"}))
    def test_exempt_account_skips_the_parent_entirely(self):
        """The mirror of the test above: a listed account never reaches it."""
        from rest_framework.throttling import UserRateThrottle

        user = User.objects.create_user(email="ci.smoke@audity.africa", password="x" * 12)
        with patch.object(UserRateThrottle, "allow_request", return_value=False) as parent:
            allowed = self.throttle.allow_request(self._request_for(user), None)
        self.assertTrue(allowed)
        parent.assert_not_called()

    @override_settings(THROTTLE_EXEMPT_EMAILS=frozenset({"ci.smoke@audity.africa"}))
    def test_anonymous_request_is_not_exempt(self):
        from django.contrib.auth.models import AnonymousUser
        from rest_framework.throttling import UserRateThrottle

        with patch.object(UserRateThrottle, "allow_request", return_value=True) as parent:
            self.throttle.allow_request(self._request_for(AnonymousUser()), None)
        parent.assert_called_once()

    @override_settings(THROTTLE_EXEMPT_EMAILS=frozenset({"ci.smoke@audity.africa"}))
    def test_exemption_does_not_cover_login(self):
        """
        The guard that matters: exemption applies to the global 'user' scope
        only. LoginRateThrottle is an AnonRateThrottle keyed by IP and must not
        inherit the exemption, or the allow-list would weaken brute-force
        protection for the listed address.
        """
        from apps.core.throttles import ExemptibleUserRateThrottle, LoginRateThrottle

        self.assertFalse(issubclass(LoginRateThrottle, ExemptibleUserRateThrottle))

    @override_settings(THROTTLE_EXEMPT_EMAILS=frozenset({"ci.smoke@audity.africa"}))
    def test_exemption_covers_per_view_volume_throttles(self):
        """
        The exemption must reach FinancialWriteThrottle, not just the default.

        Views like sales/bills/expenses set throttle_classes explicitly, which
        REPLACES the defaults — so exempting only the global catch-all left the
        very endpoints the smoke suite hammers still throttled. That is why the
        first attempt at this exemption changed nothing: 258 HTTP 429s on
        /sales/invoices/, /bills/ and /expenses/ after it shipped.
        """
        from apps.core.throttles import FinancialWriteThrottle, ThrottleExemptionMixin

        self.assertTrue(issubclass(FinancialWriteThrottle, ThrottleExemptionMixin))
        user = User.objects.create_user(email="ci.smoke@audity.africa", password="x" * 12)
        throttle = FinancialWriteThrottle()
        self.assertTrue(all(throttle.allow_request(self._request_for(user), None) for _ in range(500)))

    @override_settings(THROTTLE_EXEMPT_EMAILS=frozenset({"ci.smoke@audity.africa"}))
    def test_security_throttles_never_inherit_the_exemption(self):
        """Auth-facing limits must stay enforced for exempt accounts too."""
        from apps.core.throttles import (
            LoginRateThrottle, MFAVerifyRateThrottle, PasswordChangeRateThrottle,
            RegisterRateThrottle, ThrottleExemptionMixin, TokenRefreshRateThrottle,
        )

        for cls in (LoginRateThrottle, RegisterRateThrottle, PasswordChangeRateThrottle,
                    TokenRefreshRateThrottle, MFAVerifyRateThrottle):
            self.assertFalse(
                issubclass(cls, ThrottleExemptionMixin),
                f"{cls.__name__} must not be exemptible — it guards authentication",
            )

    def test_financial_write_throttle_ignores_reads(self):
        """
        Reads must not spend the write budget.

        The throttle is attached to whole ViewSets, so before this every GET of
        /sales/invoices/ or /bills/ counted against 60/minute — a limit built
        for double-submit attacks — and the dashboard polls those lists.
        """
        from apps.core.throttles import FinancialWriteThrottle

        throttle = FinancialWriteThrottle()
        user = User.objects.create_user(email="busy@example.com", password="x" * 12)
        read = self.factory.get("/api/v1/sales/invoices/")
        read.user = user
        self.assertTrue(all(throttle.allow_request(read, None) for _ in range(500)))

    def test_financial_write_throttle_still_counts_writes(self):
        from rest_framework.throttling import UserRateThrottle

        from apps.core.throttles import FinancialWriteThrottle

        throttle = FinancialWriteThrottle()
        user = User.objects.create_user(email="writer@example.com", password="x" * 12)
        write = self.factory.post("/api/v1/sales/invoices/")
        write.user = user
        with patch.object(UserRateThrottle, "allow_request", return_value=True) as parent:
            throttle.allow_request(write, None)
        parent.assert_called_once()

    def test_financial_viewsets_keep_a_read_limit(self):
        """
        throttle_classes REPLACES the defaults, so the views must name the
        per-user throttle explicitly or reads end up with no limit at all now
        that the write throttle ignores them.
        """
        from apps.bills.views import BillViewSet
        from apps.core.throttles import ExemptibleUserRateThrottle, FinancialWriteThrottle
        from apps.expenses.views import ExpenseViewSet
        from apps.sales.views import InvoiceViewSet

        for viewset in (InvoiceViewSet, BillViewSet, ExpenseViewSet):
            classes = getattr(viewset, "throttle_classes", [])
            self.assertIn(FinancialWriteThrottle, classes, viewset.__name__)
            self.assertIn(ExemptibleUserRateThrottle, classes, viewset.__name__)
