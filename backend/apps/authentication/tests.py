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
