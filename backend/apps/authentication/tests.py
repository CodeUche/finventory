"""Tests for authentication: register, login, lockout, password reset OTP."""

import base64
import json

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.authentication.models import PasswordResetOTP, User
from apps.tenancy.models import Membership, Organisation
from apps.tenancy.services import OrganisationService


class RegisterTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("auth-register")
        # Clear throttle cache so each test gets a fresh rate-limit window
        cache.clear()

    def _payload(self, **overrides):
        base = {
            "email": "test@example.com",
            "password": "StrongPass123!",
            "password_confirm": "StrongPass123!",
            "first_name": "Test",
            "last_name": "User",
        }
        base.update(overrides)
        return base

    def test_register_success(self):
        res = self.client.post(self.url, self._payload())
        self.assertEqual(res.status_code, 201)
        # Registration now returns a message, NOT tokens — user must verify email first
        self.assertIn("message", res.data)
        self.assertTrue(User.objects.filter(email="test@example.com").exists())

    def test_register_duplicate_email(self):
        # Create a fully-established user (with an active membership) to verify
        # that the orphan-cleanup logic does NOT delete active accounts.
        user = User.objects.create_user(
            email="dup@example.com", password="pass", first_name="A", last_name="B"
        )
        org = Organisation.objects.create(name="Test Org", slug="test-org-dup", currency="NGN", owner=user)
        Membership.objects.create(user=user, organisation=org, role="owner", is_active=True)
        res = self.client.post(self.url, self._payload(email="dup@example.com"))
        self.assertEqual(res.status_code, 400)

    def test_register_email_normalised_lowercase(self):
        res = self.client.post(self.url, self._payload(email="UPPER@EXAMPLE.COM"))
        self.assertEqual(res.status_code, 201)
        # Email should be normalised to lowercase in the database
        self.assertTrue(User.objects.filter(email="upper@example.com").exists())

    def test_register_password_mismatch_rejected(self):
        res = self.client.post(
            self.url,
            self._payload(password="StrongPass123!", password_confirm="Different456!"),
        )
        self.assertEqual(res.status_code, 400)

    def test_register_short_password_rejected(self):
        res = self.client.post(
            self.url,
            self._payload(password="short", password_confirm="short"),
        )
        self.assertEqual(res.status_code, 400)


class LoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("auth-login")
        self.user = User.objects.create_user(
            email="login@example.com",
            password="ValidPass123!",
            first_name="Login",
            last_name="User",
            is_verified=True,  # Pre-verified so login tests work without email flow
        )

    def test_login_success(self):
        res = self.client.post(self.url, {
            "email": "login@example.com",
            "password": "ValidPass123!",
        })
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)
        self.assertIn("user", res.data)

    def test_login_writes_audit_log_with_ip(self):
        from apps.core.models import AuditLog

        res = self.client.post(
            self.url,
            {"email": "login@example.com", "password": "ValidPass123!"},
            REMOTE_ADDR="203.0.113.5",
        )
        self.assertEqual(res.status_code, 200)

        entry = AuditLog.objects.filter(
            action=AuditLog.LOGIN, user_id=self.user.id
        ).order_by("-created_at").first()
        self.assertIsNotNone(entry)
        self.assertTrue(entry.ip_address)
        self.assertEqual(entry.user_email, self.user.email)

    def test_login_wrong_password(self):
        res = self.client.post(self.url, {
            "email": "login@example.com",
            "password": "WrongPassword!",
        })
        self.assertEqual(res.status_code, 401)

    def test_login_unknown_email(self):
        res = self.client.post(self.url, {
            "email": "nobody@example.com",
            "password": "SomePass123!",
        })
        self.assertEqual(res.status_code, 401)

    def test_account_lockout_after_five_failures(self):
        for _ in range(5):
            self.client.post(self.url, {
                "email": "login@example.com",
                "password": "WrongPass!",
            })
        # Refresh from DB — the view modifies the DB object, not our in-memory ref
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_locked)

        # Next attempt should be blocked even with correct password
        res = self.client.post(self.url, {
            "email": "login@example.com",
            "password": "ValidPass123!",
        })
        self.assertEqual(res.status_code, 429)

    def test_successful_login_clears_failure_counter(self):
        self.user.failed_login_attempts = 3
        self.user.save(update_fields=["failed_login_attempts"])

        self.client.post(self.url, {
            "email": "login@example.com",
            "password": "ValidPass123!",
        })
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 0)


class PasswordResetOTPTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="reset@example.com",
            password="OldPass123456!",
            first_name="Reset",
            last_name="User",
        )
        self.request_url = reverse("auth-password-reset")
        self.confirm_url = reverse("auth-password-reset-confirm")
        self.client = APIClient()

    def test_request_reset_known_email_returns_200(self):
        res = self.client.post(self.request_url, {"email": "reset@example.com"})
        self.assertEqual(res.status_code, 200)

    def test_request_reset_unknown_email_returns_200(self):
        res = self.client.post(self.request_url, {"email": "nobody@example.com"})
        self.assertEqual(res.status_code, 200)

    def test_otp_generate_creates_hashed_record(self):
        code = PasswordResetOTP.generate(self.user)
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())
        otp = PasswordResetOTP.objects.filter(user=self.user, used=False).first()
        self.assertIsNotNone(otp)
        self.assertNotEqual(otp.code_hash, code)

    def test_otp_verify_correct_code(self):
        code = PasswordResetOTP.generate(self.user)
        otp = PasswordResetOTP.objects.filter(user=self.user, used=False).first()
        self.assertTrue(otp.verify(code))

    def test_otp_verify_wrong_code_fails(self):
        PasswordResetOTP.generate(self.user)
        otp = PasswordResetOTP.objects.filter(user=self.user, used=False).first()
        self.assertFalse(otp.verify("000000"))

    def test_generate_invalidates_previous_otp(self):
        PasswordResetOTP.generate(self.user)
        PasswordResetOTP.generate(self.user)
        # First OTP should now be marked used
        otps = list(PasswordResetOTP.objects.filter(user=self.user).order_by("created_at"))
        self.assertTrue(otps[0].used)
        self.assertFalse(otps[1].used)

    def test_confirm_marks_otp_used(self):
        code = PasswordResetOTP.generate(self.user)
        res = self.client.post(self.confirm_url, {
            "email": "reset@example.com",
            "code": code,
            "new_password": "NewStrongPass456!",
            "confirm_password": "NewStrongPass456!",
        })
        self.assertEqual(res.status_code, 200)
        otp = PasswordResetOTP.objects.filter(user=self.user).first()
        self.assertTrue(otp.used)

    def test_confirm_password_mismatch(self):
        code = PasswordResetOTP.generate(self.user)
        res = self.client.post(self.confirm_url, {
            "email": "reset@example.com",
            "code": code,
            "new_password": "NewStrongPass456!",
            "confirm_password": "DifferentPass789!",
        })
        self.assertEqual(res.status_code, 400)

    def test_confirm_password_too_short(self):
        code = PasswordResetOTP.generate(self.user)
        res = self.client.post(self.confirm_url, {
            "email": "reset@example.com",
            "code": code,
            "new_password": "short",
            "confirm_password": "short",
        })
        self.assertEqual(res.status_code, 400)

    def test_confirm_resets_lockout(self):
        from datetime import timedelta
        from django.utils import timezone
        self.user.failed_login_attempts = 5
        self.user.locked_until = timezone.now() + timedelta(minutes=30)
        self.user.save()

        code = PasswordResetOTP.generate(self.user)
        self.client.post(self.confirm_url, {
            "email": "reset@example.com",
            "code": code,
            "new_password": "NewStrongPass456!",
            "confirm_password": "NewStrongPass456!",
        })
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_locked)
        self.assertEqual(self.user.failed_login_attempts, 0)


def _decode_jwt_payload(token: str) -> dict:
    """Decode the payload segment of a JWT without verifying the signature."""
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (4 - len(payload_b64) % 4)
    return json.loads(base64.b64decode(payload_b64).decode())


class LoginOrganisationsTests(TestCase):
    """
    Verify that LoginView always returns a non-empty `organisations` list for
    existing users, preventing the onboarding-redirect regression.

    Root cause of the bug: the org query ran outside atomic(), so set_config
    (transaction-local) reverted to SENTINEL after the membership query committed,
    causing org_select RLS to block all rows.  The JWT-decode shortcut bypasses
    this by reading org IDs directly from the already-issued JWT token.

    These tests run on SQLite (testing.py), so set_config calls raise
    OperationalError — the ORM fallback in get_token() kicks in and populates
    the JWT memberships claim.  The JWT-decode shortcut in LoginView.post then
    reads those IDs, so organisations is populated regardless of DB backend.
    """

    def setUp(self):
        self.client = APIClient()
        self.url = reverse("auth-login")
        cache.clear()

        self.user = User.objects.create_user(
            email="existing@example.com",
            password="ValidPass123!",
            first_name="Existing",
            last_name="User",
            is_verified=True,
        )
        # Create an organisation — OrganisationService.create_organisation also
        # creates the Membership row, which is what get_token ORM fallback reads.
        self.org = OrganisationService.create_organisation(
            name="Existing Corp",
            owner=self.user,
            extra={"currency": "NGN", "country": "NG"},
        )

    def _login(self):
        return self.client.post(self.url, {
            "email": "existing@example.com",
            "password": "ValidPass123!",
        })

    # ── Core regression test ──────────────────────────────────────────────────

    def test_login_returns_non_empty_organisations_for_member(self):
        """Existing user with an org must NOT be routed to /onboarding."""
        res = self._login()
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIn("organisations", res.data)
        orgs = res.data["organisations"]
        self.assertIsInstance(orgs, list)
        self.assertGreater(len(orgs), 0, "organisations must not be empty for a user with a membership")

    def test_login_organisations_contain_correct_org_id(self):
        res = self._login()
        self.assertEqual(res.status_code, 200)
        org_ids = [o["id"] for o in res.data["organisations"]]
        self.assertIn(str(self.org.id), org_ids)

    def test_login_organisations_have_onboarding_completed(self):
        """Every org stub returned must have onboarding_completed=True so the
        frontend ProtectedRoute sets onboardingDone=true and navigates to /dashboard."""
        res = self._login()
        self.assertEqual(res.status_code, 200)
        for org in res.data["organisations"]:
            self.assertTrue(
                org.get("onboarding_completed"),
                f"org {org.get('id')} missing onboarding_completed=True",
            )

    # ── JWT memberships claim ─────────────────────────────────────────────────

    def test_jwt_access_token_contains_memberships_claim(self):
        """JWT must embed memberships so the JWT-decode shortcut can read them."""
        res = self._login()
        self.assertEqual(res.status_code, 200)
        payload = _decode_jwt_payload(res.data["access"])
        self.assertIn("memberships", payload)
        memberships = payload["memberships"]
        self.assertIsInstance(memberships, dict)
        self.assertGreater(len(memberships), 0, "memberships claim must not be empty")

    def test_jwt_memberships_claim_contains_correct_org(self):
        res = self._login()
        payload = _decode_jwt_payload(res.data["access"])
        self.assertIn(str(self.org.id), payload["memberships"])

    def test_jwt_memberships_role_is_owner(self):
        res = self._login()
        payload = _decode_jwt_payload(res.data["access"])
        self.assertEqual(payload["memberships"].get(str(self.org.id)), "owner")

    # ── New user (no org) ─────────────────────────────────────────────────────

    def test_login_returns_empty_organisations_for_new_user(self):
        """A freshly registered user with no org should get an empty list (not crash)."""
        no_org_user = User.objects.create_user(
            email="noorg@example.com",
            password="ValidPass123!",
            is_verified=True,
        )
        res = self.client.post(self.url, {
            "email": "noorg@example.com",
            "password": "ValidPass123!",
        })
        self.assertEqual(res.status_code, 200)
        self.assertIn("organisations", res.data)
        self.assertEqual(res.data["organisations"], [])

    # ── _get_user_organisations helper ───────────────────────────────────────

    def test_get_user_organisations_returns_list_without_crashing(self):
        """_get_user_organisations must never raise — on SQLite it returns []."""
        from apps.authentication.views import _get_user_organisations
        result = _get_user_organisations(self.user)
        # On SQLite, set_config fails → exception caught → returns []
        # On PostgreSQL with proper RLS setup it would return the org list.
        self.assertIsInstance(result, list)

    # ── Response shape ────────────────────────────────────────────────────────

    def test_login_response_has_user_profile(self):
        res = self._login()
        self.assertEqual(res.status_code, 200)
        self.assertIn("user", res.data)
        user_data = res.data["user"]
        self.assertEqual(user_data["email"], "existing@example.com")
        self.assertIn("is_superuser", user_data)
        self.assertIn("is_verified", user_data)

    def test_login_response_has_both_tokens(self):
        res = self._login()
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.data)
        self.assertIn("refresh", res.data)

    # ── Multi-org user ────────────────────────────────────────────────────────

    def test_login_returns_all_organisations_for_multi_org_user(self):
        """A user who is a member of two orgs should get both in the response."""
        second_user = User.objects.create_user(
            email="second_owner@example.com",
            password="ValidPass123!",
            is_verified=True,
        )
        second_org = OrganisationService.create_organisation(
            name="Second Org",
            owner=second_user,
            extra={"currency": "NGN", "country": "NG"},
        )
        # Add self.user as a member of the second org
        Membership.objects.create(
            user=self.user,
            organisation=second_org,
            role=Membership.Role.STAFF,
            is_active=True,
        )
        res = self._login()
        self.assertEqual(res.status_code, 200)
        org_ids = {o["id"] for o in res.data["organisations"]}
        self.assertIn(str(self.org.id), org_ids)
        self.assertIn(str(second_org.id), org_ids)


# ─────────────────────────────────────────────────────────────────────────────
# Deep login-flow unit tests
# These cover each individual step of the login → /dashboard routing chain so
# that any regression is caught before it reaches production.
# ─────────────────────────────────────────────────────────────────────────────

class GetTokenMembershipsTests(TestCase):
    """
    Unit tests for CustomTokenObtainPairSerializer.get_token().

    On SQLite the raw-SQL attempts raise OperationalError (no set_config
    function).  The ORM fallback must still populate the memberships claim.
    """

    def _make_user_with_org(self, email="tkn@example.com"):
        user = User.objects.create_user(
            email=email, password="ValidPass123!", is_verified=True,
        )
        org = OrganisationService.create_organisation(
            name="Token Test Org", owner=user,
            extra={"currency": "NGN", "country": "NG"},
        )
        return user, org

    def _get_token_payload(self, user):
        from apps.authentication.serializers import CustomTokenObtainPairSerializer
        token = CustomTokenObtainPairSerializer.get_token(user)
        raw = str(token.access_token)
        b64 = raw.split(".")[1]
        b64 += "=" * (4 - len(b64) % 4)
        return json.loads(base64.b64decode(b64).decode())

    def test_get_token_embeds_memberships_for_member(self):
        user, org = self._make_user_with_org()
        payload = self._get_token_payload(user)
        self.assertIn("memberships", payload)
        self.assertIn(str(org.id), payload["memberships"])

    def test_get_token_memberships_role_is_owner(self):
        user, org = self._make_user_with_org("tkn2@example.com")
        payload = self._get_token_payload(user)
        self.assertEqual(payload["memberships"][str(org.id)], "owner")

    def test_get_token_memberships_empty_for_user_without_org(self):
        user = User.objects.create_user(
            email="tkn_noorg@example.com", password="ValidPass123!", is_verified=True,
        )
        payload = self._get_token_payload(user)
        self.assertIn("memberships", payload)
        self.assertEqual(payload["memberships"], {})

    def test_get_token_includes_email_claim(self):
        user, _ = self._make_user_with_org("tkn3@example.com")
        payload = self._get_token_payload(user)
        self.assertEqual(payload["email"], "tkn3@example.com")

    def test_get_token_includes_token_version_claim(self):
        user, _ = self._make_user_with_org("tkn4@example.com")
        payload = self._get_token_payload(user)
        self.assertIn("token_version", payload)

    def test_get_token_does_not_raise_on_sqlite(self):
        """ORM fallback must not raise — raw SQL fails silently on SQLite."""
        user, _ = self._make_user_with_org("tkn5@example.com")
        from apps.authentication.serializers import CustomTokenObtainPairSerializer
        # Should complete without exception
        try:
            CustomTokenObtainPairSerializer.get_token(user)
        except Exception as exc:
            self.fail(f"get_token raised {exc!r} on SQLite")


class GetUserOrganisationsTests(TestCase):
    """
    Unit tests for _get_user_organisations() view helper.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            email="guorg@example.com", password="ValidPass123!", is_verified=True,
        )
        self.org = OrganisationService.create_organisation(
            name="GUOrg", owner=self.user,
            extra={"currency": "NGN", "country": "NG"},
        )

    def test_returns_list(self):
        from apps.authentication.views import _get_user_organisations
        result = _get_user_organisations(self.user)
        self.assertIsInstance(result, list)

    def test_returns_org_for_member_via_orm_fallback(self):
        """On SQLite the ORM fallback must return the org."""
        from apps.authentication.views import _get_user_organisations
        result = _get_user_organisations(self.user)
        # SQLite: raw SQL fails → ORM fallback runs
        # ORM fallback queries Membership → tenancy_organisation directly.
        # On SQLite there's no RLS so it always works.
        org_ids = [o["id"] for o in result]
        self.assertIn(str(self.org.id), org_ids)

    def test_returns_empty_list_for_user_without_org(self):
        from apps.authentication.views import _get_user_organisations
        no_org = User.objects.create_user(
            email="guorg_noorg@example.com", password="ValidPass123!", is_verified=True,
        )
        result = _get_user_organisations(no_org)
        self.assertEqual(result, [])

    def test_never_raises(self):
        from apps.authentication.views import _get_user_organisations
        try:
            _get_user_organisations(self.user)
        except Exception as exc:
            self.fail(f"_get_user_organisations raised {exc!r}")

    def test_org_dict_has_required_fields(self):
        from apps.authentication.views import _get_user_organisations
        result = _get_user_organisations(self.user)
        if not result:
            self.skipTest("No orgs returned on this DB backend (raw SQL failed)")
        org = result[0]
        for field in ("id", "onboarding_completed"):
            self.assertIn(field, org, f"Missing field: {field}")

    def test_org_stubs_have_id_field(self):
        """Each org dict returned must have a non-empty id.
        ProtectedRoute uses !!organisation?.id for the onboardingDone check —
        onboarding_completed is NOT used in the routing decision.
        """
        from apps.authentication.views import _get_user_organisations
        result = _get_user_organisations(self.user)
        for o in result:
            self.assertTrue(
                o.get("id"),
                f"Org stub missing id field: {o}",
            )


class LoginViewOrgsEndToEndTests(TestCase):
    """
    End-to-end simulation of the login response → ProtectedRoute routing.

    Each test asserts that the conditions the frontend uses to decide
    onboardingDone are satisfied in the login response.
    """

    def setUp(self):
        self.client = APIClient()
        self.url = reverse("auth-login")
        cache.clear()

        self.user = User.objects.create_user(
            email="e2e@example.com",
            password="ValidPass123!",
            first_name="End",
            last_name="ToEnd",
            is_verified=True,
        )
        self.org = OrganisationService.create_organisation(
            name="E2E Org",
            owner=self.user,
            extra={"currency": "NGN", "country": "NG"},
        )

    def _login(self):
        return self.client.post(self.url, {
            "email": "e2e@example.com",
            "password": "ValidPass123!",
        })

    def test_response_status_is_200(self):
        res = self._login()
        self.assertEqual(res.status_code, 200, res.data)

    def test_response_has_access_token(self):
        res = self._login()
        self.assertIn("access", res.data)
        self.assertIsInstance(res.data["access"], str)
        self.assertGreater(len(res.data["access"]), 20)

    def test_response_has_refresh_token(self):
        res = self._login()
        self.assertIn("refresh", res.data)

    def test_response_has_user_object(self):
        res = self._login()
        self.assertIn("user", res.data)
        self.assertEqual(res.data["user"]["email"], "e2e@example.com")

    def test_response_has_organisations_list(self):
        res = self._login()
        self.assertIn("organisations", res.data)
        self.assertIsInstance(res.data["organisations"], list)

    def test_organisations_non_empty_for_existing_member(self):
        """THE CORE REGRESSION TEST: existing user must NOT see empty orgs."""
        res = self._login()
        orgs = res.data.get("organisations", [])
        self.assertGreater(
            len(orgs), 0,
            "organisations is empty — user would be redirected to /onboarding",
        )

    def test_organisations_contain_correct_org_id(self):
        res = self._login()
        org_ids = [o["id"] for o in res.data["organisations"]]
        self.assertIn(str(self.org.id), org_ids)

    def test_jwt_shortcut_populates_organisations(self):
        """JWT shortcut: decode access token → read memberships → build stubs."""
        res = self._login()
        self.assertEqual(res.status_code, 200)
        access = res.data["access"]
        payload = _decode_jwt_payload(access)
        # JWT must have memberships so the shortcut can produce the stubs
        self.assertGreater(
            len(payload.get("memberships", {})), 0,
            "JWT memberships claim is empty — JWT shortcut would fail",
        )
        # And the final organisations list must contain the org
        org_ids = [o["id"] for o in res.data["organisations"]]
        self.assertIn(str(self.org.id), org_ids)

    def test_onboarding_done_condition_is_satisfied(self):
        """
        Simulate the frontend ProtectedRoute onboardingDone check:
            onboardingDone = user.is_superuser || !!firstOrg
        With a real org in the response, firstOrg must be truthy.
        """
        res = self._login()
        user_data = res.data.get("user", {})
        orgs = res.data.get("organisations", [])
        first_org = orgs[0] if orgs else None
        onboarding_done = user_data.get("is_superuser") or bool(first_org)
        self.assertTrue(
            onboarding_done,
            "Frontend would redirect to /onboarding — "
            f"is_superuser={user_data.get('is_superuser')}, first_org={first_org}",
        )

    def test_signout_then_signin_still_returns_org(self):
        """Simulates sign-out / sign-in cycle: second login must still return org."""
        # First login
        res1 = self._login()
        self.assertEqual(res1.status_code, 200)
        # Second login (simulates sign-out then sign-in)
        res2 = self._login()
        self.assertEqual(res2.status_code, 200)
        orgs = res2.data.get("organisations", [])
        self.assertGreater(len(orgs), 0, "Second login returned empty organisations")
        self.assertIn(str(self.org.id), [o["id"] for o in orgs])

    def test_unverified_user_cannot_login(self):
        """Unverified users must be blocked with 403."""
        unverified = User.objects.create_user(
            email="unverified@example.com",
            password="ValidPass123!",
            is_verified=False,
        )
        res = self.client.post(self.url, {
            "email": "unverified@example.com",
            "password": "ValidPass123!",
        })
        self.assertEqual(res.status_code, 403)
        self.assertIn("email_not_verified", str(res.data))

    def test_sub_account_cannot_use_main_login(self):
        """Sub-accounts must be rejected with 403 at the main login endpoint."""
        sub = User.objects.create_user(
            email="sub@example.com",
            password="ValidPass123!",
            is_verified=True,
            is_sub_account=True,
        )
        res = self.client.post(self.url, {
            "email": "sub@example.com",
            "password": "ValidPass123!",
        })
        self.assertEqual(res.status_code, 403)


class ProtectedRouteConditionsTests(TestCase):
    """
    Verify the ProtectedRoute logic conditions from the backend's perspective.

    ProtectedRoute uses:
        onboardingDone = user.is_superuser || user.is_sub_account || !!organisation?.id

    This test class confirms the login response supplies the data needed to
    satisfy that condition for a regular owner user.
    """

    def setUp(self):
        self.client = APIClient()
        self.url = reverse("auth-login")
        cache.clear()

    def _create_owner(self, email):
        user = User.objects.create_user(
            email=email, password="ValidPass123!", is_verified=True,
        )
        org = OrganisationService.create_organisation(
            name=f"Org for {email}", owner=user,
            extra={"currency": "NGN", "country": "NG"},
        )
        return user, org

    def _login(self, email):
        return self.client.post(self.url, {"email": email, "password": "ValidPass123!"})

    def test_is_superuser_false_for_regular_user(self):
        """Regular owner must not be flagged as superuser."""
        self._create_owner("pr_owner@example.com")
        res = self._login("pr_owner@example.com")
        self.assertFalse(res.data["user"]["is_superuser"])

    def test_is_sub_account_false_for_regular_user(self):
        self._create_owner("pr_owner2@example.com")
        res = self._login("pr_owner2@example.com")
        self.assertFalse(res.data["user"]["is_sub_account"])

    def test_first_org_is_present_for_owner(self):
        """organisations[0] must exist → !!organisation?.id is truthy → /dashboard."""
        user, org = self._create_owner("pr_owner3@example.com")
        res = self._login("pr_owner3@example.com")
        orgs = res.data.get("organisations", [])
        self.assertTrue(len(orgs) > 0 and orgs[0].get("id"),
                        f"No org in response — user would land on /onboarding. orgs={orgs}")

    def test_protected_route_condition_met_for_owner(self):
        """Full simulation: owner gets onboardingDone=True from response data."""
        user, org = self._create_owner("pr_owner4@example.com")
        res = self._login("pr_owner4@example.com")
        u = res.data["user"]
        orgs = res.data.get("organisations", [])
        first_org = orgs[0] if orgs else None
        onboarding_done = u["is_superuser"] or u["is_sub_account"] or bool(first_org and first_org.get("id"))
        self.assertTrue(onboarding_done,
                        f"ProtectedRoute would send to /onboarding. "
                        f"is_superuser={u['is_superuser']}, first_org={first_org}")


# ─────────────────────────────────────────────────────────────────────────────
# Offline re-authentication (desktop)
# The Tauri app clears auth state on every launch, so after an offline restart
# the user is locked out even though their data is cached locally.  These
# tests cover the verifier issuance / status / revocation endpoints and the
# invalidation hooks in the password-change and password-reset flows.
# ─────────────────────────────────────────────────────────────────────────────

class OfflineVerifierIssueTests(TestCase):
    """POST /api/v1/auth/offline-verifier/ — issuance and rotation."""

    PASSWORD = "ValidPass123!"

    def setUp(self):
        self.client = APIClient()
        self.url = reverse("auth-offline-verifier")
        cache.clear()
        self.user = User.objects.create_user(
            email="offline@example.com",
            password=self.PASSWORD,
            first_name="Off",
            last_name="Line",
            is_verified=True,
        )
        self.client.force_authenticate(self.user)

    def _issue(self, password=None, **extra):
        return self.client.post(self.url, {"password": password or self.PASSWORD, **extra})

    def test_issue_requires_authentication(self):
        """A verifier grants offline entry — anonymous callers must get 401."""
        self.client.force_authenticate(user=None)
        res = self._issue()
        self.assertEqual(res.status_code, 401)

    def test_issue_requires_password_field(self):
        res = self.client.post(self.url, {})
        self.assertEqual(res.status_code, 400)

    def test_issue_with_wrong_password_rejected(self):
        """A stolen access token alone must not be enough to mint a verifier."""
        res = self._issue(password="WrongPassword!")
        self.assertEqual(res.status_code, 400)
        self.assertIn("invalid_password", str(res.data))
        # No record must be created on a failed attempt
        from apps.authentication.models import OfflineVerifier
        self.assertFalse(OfflineVerifier.objects.filter(user=self.user).exists())

    def test_issue_returns_full_verifier_payload(self):
        res = self._issue()
        self.assertEqual(res.status_code, 200, res.data)
        v = res.data["verifier"]
        for field in ("algorithm", "iterations", "salt", "hash", "user_id",
                      "email", "mfa_enabled", "token_version", "issued_at",
                      "expires_at", "organisations"):
            self.assertIn(field, v, f"Missing verifier field: {field}")
        self.assertEqual(v["algorithm"], "pbkdf2_sha256")
        self.assertEqual(v["user_id"], str(self.user.pk))
        self.assertEqual(v["email"], "offline@example.com")

    def test_issued_hash_matches_independent_recompute(self):
        """The client must be able to re-derive the hash offline from
        (password, salt, iterations) — verify the server's derivation is
        exactly standard PBKDF2-HMAC-SHA256."""
        import hashlib
        res = self._issue()
        v = res.data["verifier"]
        recomputed = hashlib.pbkdf2_hmac(
            "sha256",
            self.PASSWORD.encode(),
            base64.b64decode(v["salt"]),
            v["iterations"],
        )
        self.assertEqual(base64.b64encode(recomputed).decode(), v["hash"])

    def test_issued_hash_is_not_the_primary_password_hash(self):
        """The verifier must be an independent derivation with its own salt —
        never the raw hash from authentication_user."""
        res = self._issue()
        v = res.data["verifier"]
        self.user.refresh_from_db()
        self.assertNotIn(v["hash"], self.user.password)
        self.assertNotIn(v["salt"], self.user.password)

    def test_secret_material_never_stored_server_side(self):
        """A DB breach must not yield a second crackable copy of the password:
        the model row holds metadata only."""
        from apps.authentication.models import OfflineVerifier
        res = self._issue()
        v = res.data["verifier"]
        record = OfflineVerifier.objects.get(user=self.user)
        field_names = {f.name for f in record._meta.get_fields()}
        self.assertNotIn("hash", field_names)
        self.assertNotIn("salt", field_names)
        # And nothing on the row contains the secret values
        for f in ("device_label",):
            self.assertNotIn(v["hash"], getattr(record, f))
            self.assertNotIn(v["salt"], getattr(record, f))

    def test_reissue_rotates_salt_and_hash(self):
        """Re-issuing must produce fresh secret material and keep exactly one
        row per user (old expiry windows must not survive rotation)."""
        from apps.authentication.models import OfflineVerifier
        first = self._issue().data["verifier"]
        second = self._issue().data["verifier"]
        self.assertNotEqual(first["salt"], second["salt"])
        self.assertNotEqual(first["hash"], second["hash"])
        self.assertEqual(OfflineVerifier.objects.filter(user=self.user).count(), 1)

    def test_expiry_is_fourteen_days_out(self):
        from datetime import datetime, timedelta, timezone as dt_tz
        res = self._issue()
        expires = datetime.fromisoformat(res.data["verifier"]["expires_at"])
        delta = expires - datetime.now(dt_tz.utc)
        self.assertGreater(delta, timedelta(days=13))
        self.assertLessEqual(delta, timedelta(days=14))

    def test_device_label_is_stored_for_auditing(self):
        from apps.authentication.models import OfflineVerifier
        res = self._issue(device_label="Ade's ThinkPad")
        self.assertEqual(res.status_code, 200)
        record = OfflineVerifier.objects.get(user=self.user)
        self.assertEqual(record.device_label, "Ade's ThinkPad")

    def test_organisations_snapshot_included_for_member(self):
        """The offline grace session needs tenant context without a network
        call, so the issuance response snapshots org memberships."""
        OrganisationService.create_organisation(
            name="Offline Org", owner=self.user,
            extra={"currency": "NGN", "country": "NG"},
        )
        res = self._issue()
        orgs = res.data["verifier"]["organisations"]
        self.assertIsInstance(orgs, list)
        self.assertGreater(len(orgs), 0)


class OfflineVerifierStatusAndRevokeTests(TestCase):
    """GET /offline-verifier/status/ and DELETE /offline-verifier/."""

    PASSWORD = "ValidPass123!"

    def setUp(self):
        self.client = APIClient()
        self.issue_url = reverse("auth-offline-verifier")
        self.status_url = reverse("auth-offline-verifier-status")
        cache.clear()
        self.user = User.objects.create_user(
            email="offline-status@example.com",
            password=self.PASSWORD,
            is_verified=True,
        )
        self.client.force_authenticate(self.user)

    def _issue(self):
        return self.client.post(self.issue_url, {"password": self.PASSWORD})

    def test_status_requires_authentication(self):
        self.client.force_authenticate(user=None)
        res = self.client.get(self.status_url)
        self.assertEqual(res.status_code, 401)

    def test_status_not_issued(self):
        res = self.client.get(self.status_url)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["active"])
        self.assertEqual(res.data["reason"], "not_issued")
        self.assertIn("token_version", res.data)

    def test_status_active_after_issue(self):
        self._issue()
        res = self.client.get(self.status_url)
        self.assertTrue(res.data["active"])
        self.assertIsNone(res.data["reason"])

    def test_revoke_marks_inactive(self):
        self._issue()
        res = self.client.delete(self.issue_url)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["revoked"])
        status_res = self.client.get(self.status_url)
        self.assertFalse(status_res.data["active"])
        self.assertEqual(status_res.data["reason"], "revoked")

    def test_revoke_is_idempotent(self):
        """Revoking with no verifier (or twice) must not error — the client
        may call this defensively on logout."""
        res = self.client.delete(self.issue_url)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["revoked"])

    def test_expired_verifier_reports_expired(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.authentication.models import OfflineVerifier
        self._issue()
        OfflineVerifier.objects.filter(user=self.user).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        res = self.client.get(self.status_url)
        self.assertFalse(res.data["active"])
        self.assertEqual(res.data["reason"], "expired")

    def test_status_reports_current_token_version(self):
        """The client compares this against the version embedded in its cached
        verifier to detect password changes made on another device."""
        self._issue()
        self.user.token_version = 5
        self.user.save(update_fields=["token_version"])
        res = self.client.get(self.status_url)
        self.assertEqual(res.data["token_version"], 5)
        # And the verifier itself is now stale
        self.assertFalse(res.data["active"])
        self.assertEqual(res.data["reason"], "password_changed")


class OfflineVerifierInvalidationTests(TestCase):
    """Password change / reset must invalidate the verifier server-side."""

    PASSWORD = "OldPass123456!"

    def setUp(self):
        self.client = APIClient()
        self.issue_url = reverse("auth-offline-verifier")
        cache.clear()
        self.user = User.objects.create_user(
            email="offline-inval@example.com",
            password=self.PASSWORD,
            first_name="Inval",
            last_name="User",
            is_verified=True,
        )
        self.client.force_authenticate(self.user)
        self.client.post(self.issue_url, {"password": self.PASSWORD})

    def _get_record(self):
        from apps.authentication.models import OfflineVerifier
        return OfflineVerifier.objects.get(user=self.user)

    def test_password_change_revokes_verifier(self):
        res = self.client.post(reverse("auth-change-password"), {
            "current_password": self.PASSWORD,
            "new_password": "NewStrongPass456!",
            "confirm_password": "NewStrongPass456!",
        })
        self.assertEqual(res.status_code, 200, res.data)
        record = self._get_record()
        self.assertTrue(record.revoked)
        self.assertFalse(record.is_active)

    def test_password_change_makes_verifier_stale_via_token_version(self):
        """Even without the explicit revoke, the token_version bump alone must
        mark the verifier stale — defence in depth."""
        self.client.post(reverse("auth-change-password"), {
            "current_password": self.PASSWORD,
            "new_password": "NewStrongPass456!",
            "confirm_password": "NewStrongPass456!",
        })
        record = self._get_record()
        self.assertTrue(record.is_stale)

    def test_password_reset_revokes_verifier(self):
        code = PasswordResetOTP.generate(self.user)
        anon = APIClient()
        res = anon.post(reverse("auth-password-reset-confirm"), {
            "email": "offline-inval@example.com",
            "code": code,
            "new_password": "NewStrongPass456!",
            "confirm_password": "NewStrongPass456!",
        })
        self.assertEqual(res.status_code, 200, res.data)
        record = self._get_record()
        self.assertTrue(record.revoked)
        self.assertFalse(record.is_active)
