"""Tests for authentication: register, login, lockout, password reset OTP."""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.authentication.models import PasswordResetOTP, User
from apps.tenancy.models import Membership, Organisation


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
