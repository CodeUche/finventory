"""Tests for subscription plans, service layer, and payment endpoints."""

from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.authentication.models import User
from apps.subscriptions.models import PaymentHistory, Plan, Subscription
from apps.subscriptions.services import PaystackSubscriptionService, SubscriptionService
from apps.tenancy.models import Organisation


def _make_user(email="owner@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!", first_name="Owner", last_name="User",
        is_verified=True,
    )


def _make_org(user, name="Test Org"):
    from apps.tenancy.services import OrganisationService
    return OrganisationService.create_organisation(
        name=name,
        owner=user,
        extra={"currency": "NGN", "country": "NG"},
    )


class PlanModelTests(TestCase):
    def test_plans_seeded(self):
        """Migration 0003 should have seeded Starter, Professional, Business."""
        slugs = list(Plan.objects.values_list("slug", flat=True))
        self.assertIn("starter", slugs)
        self.assertIn("professional", slugs)
        self.assertIn("business", slugs)

    def test_free_plan_seeded(self):
        self.assertTrue(Plan.objects.filter(slug="free").exists())

    def test_free_plan_is_public(self):
        # Free plan is intentionally public so users can see it on the plan picker
        free = Plan.objects.get(slug="free")
        self.assertTrue(free.is_public)

    def test_paid_plans_are_public(self):
        # Starter is now a legacy plan (is_public=False); only professional and business are public paid plans
        for slug in ("professional", "business"):
            plan = Plan.objects.get(slug=slug)
            self.assertTrue(plan.is_public, f"{slug} should be public")

    def test_plan_feature_getter(self):
        plan = Plan.objects.get(slug="professional")
        # Canonical migration sets professional max_products to 999999 (unlimited)
        self.assertEqual(plan.get_feature("max_products"), 999999)
        self.assertEqual(plan.get_feature("max_users"), 3)
        self.assertIsNone(plan.get_feature("nonexistent"))


class SubscriptionServiceTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        self.plan = Plan.objects.get(slug="professional")

    def test_create_trial(self):
        # Org already has a subscription from org creation — reset for this test
        self.org.subscription = None
        self.org.save()
        sub = SubscriptionService.create_trial(self.org, self.plan)
        self.assertEqual(sub.status, Subscription.Status.TRIALING)
        self.assertIsNotNone(sub.trial_end)

    def test_upgrade_plan(self):
        business = Plan.objects.get(slug="business")
        sub = SubscriptionService.upgrade_plan(self.org, business)
        self.assertEqual(sub.plan.slug, "business")
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)

    def test_cancel(self):
        sub = SubscriptionService.cancel(self.org)
        self.assertEqual(sub.status, Subscription.Status.CANCELED)
        self.assertIsNotNone(sub.canceled_at)

    def test_check_feature_active(self):
        sub = self.org.subscription
        sub.status = Subscription.Status.ACTIVE
        sub.plan = Plan.objects.get(slug="business")
        sub.save()
        self.assertTrue(SubscriptionService.check_feature(self.org, "multi_warehouse"))

    def test_check_feature_canceled_returns_false(self):
        sub = self.org.subscription
        sub.status = Subscription.Status.CANCELED
        sub.save()
        self.assertFalse(SubscriptionService.check_feature(self.org, "multi_warehouse"))


class PaystackSubscriptionServiceTests(TestCase):
    def setUp(self):
        self.user = _make_user("paystack@example.com")
        self.org = _make_org(self.user, "Paystack Org")
        self.plan = Plan.objects.get(slug="professional")

    @patch("apps.subscriptions.services.requests.post")
    def test_initiate_payment_success(self, mock_post):
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "status": True,
            "data": {
                "authorization_url": "https://checkout.paystack.com/test",
                "access_code": "abc123",
                "reference": "SUB-TEST123",
            },
        }
        mock_post.return_value = mock_resp

        result = PaystackSubscriptionService.initiate_payment(
            self.org, self.plan, "paystack@example.com"
        )
        self.assertIn("authorization_url", result)
        self.assertIn("reference", result)
        self.assertTrue(result["reference"].startswith("SUB-"))

    @patch("apps.subscriptions.payment_engine.requests.post")
    def test_initiate_payment_paystack_error_raises(self, mock_post):
        # NOTE: initiate_payment now delegates to PaymentEngine, which makes
        # its Paystack HTTP calls from apps.subscriptions.payment_engine, not
        # apps.subscriptions.services — patch target updated accordingly.
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"status": False, "message": "Invalid key"}
        mock_post.return_value = mock_resp

        with self.assertRaises(ValueError) as ctx:
            PaystackSubscriptionService.initiate_payment(
                self.org, self.plan, "paystack@example.com"
            )
        self.assertIn("Paystack error", str(ctx.exception))

    @patch("apps.subscriptions.payment_engine.requests.get")
    @patch("apps.subscriptions.payment_engine.requests.post")
    def test_verify_payment_success(self, mock_post, mock_get):
        # NOTE: verify_payment now delegates to PaymentEngine.activate, which
        # requires a PaymentHistory row to already exist (created by
        # initiate_payment) — row-locked idempotent settlement replaces the
        # old get_or_create-on-verify behavior. Realistic flow: initiate then verify.
        init_resp = MagicMock(status_code=200)
        init_resp.raise_for_status.return_value = None
        init_resp.json.return_value = {
            "status": True,
            "data": {
                "authorization_url": "https://checkout.paystack.com/test",
                "access_code": "abc123",
                "reference": "SUB-VERIFY123",
            },
        }
        mock_post.return_value = init_resp

        with patch("apps.subscriptions.payment_engine.uuid.uuid4") as mock_uuid:
            mock_uuid.return_value.hex = "VERIFY123000000"
            PaystackSubscriptionService.initiate_payment(self.org, self.plan, "paystack@example.com")

        verify_resp = MagicMock(status_code=200)
        verify_resp.raise_for_status.return_value = None
        verify_resp.json.return_value = {
            "status": True,
            "data": {
                "status": "success",
                "reference": "SUB-VERIFY123000000",
                "amount": int(self.plan.price * 100),
                "metadata": {
                    "plan_id": str(self.plan.id),
                    "org_id": str(self.org.id),
                },
            },
        }
        mock_get.return_value = verify_resp

        sub = PaystackSubscriptionService.verify_payment(self.org, "SUB-VERIFY123000000")
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertEqual(sub.plan.slug, "professional")
        self.assertEqual(sub.provider, "paystack")

    def test_verify_payment_unknown_reference_raises(self):
        # A reference never created via initiate_payment cannot be verified —
        # PaymentEngine.activate requires the PaymentHistory row to pre-exist.
        with self.assertRaises(ValueError):
            PaystackSubscriptionService.verify_payment(self.org, "SUB-NEVER-INITIATED")

    def test_activate_from_webhook_missing_metadata_is_silent(self):
        # Should not raise even with bad data
        PaystackSubscriptionService.activate_from_webhook({})
        PaystackSubscriptionService.activate_from_webhook({"metadata": {}})

    def test_activate_subscription_idempotent(self):
        """Calling _activate_subscription twice with same reference is safe."""
        PaystackSubscriptionService._activate_subscription(
            self.org, self.plan, "SUB-IDEM001", 1500000
        )
        PaystackSubscriptionService._activate_subscription(
            self.org, self.plan, "SUB-IDEM001", 1500000
        )
        count = PaymentHistory.objects.filter(
            subscription=self.org.subscription,
            provider_payment_id="SUB-IDEM001",
        ).count()
        self.assertEqual(count, 1)


class SubscriptionAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _make_user("api@example.com")
        self.org = _make_org(self.user, "API Org")

        # Authenticate
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
            HTTP_X_ORGANISATION_ID=str(self.org.id),
        )

    def test_list_plans_public_no_auth(self):
        client = APIClient()
        res = client.get("/api/v1/subscriptions/plans/")
        self.assertEqual(res.status_code, 200)
        slugs = [p["slug"] for p in res.data["results"] if "slug" in p]
        # Free plan is public so users can see it on the plan picker
        self.assertIn("free", slugs)
        # Core paid plans are also public
        self.assertIn("professional", slugs)
        self.assertIn("business", slugs)

    def test_current_subscription(self):
        res = self.client.get("/api/v1/subscriptions/current/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("plan", res.data)
        self.assertIn("status", res.data)

    def test_initiate_payment_free_plan_rejected(self):
        free = Plan.objects.get(slug="free")
        res = self.client.post(
            "/api/v1/subscriptions/initiate-payment/",
            {"plan_id": str(free.id)},
        )
        self.assertEqual(res.status_code, 400)

    @patch("apps.subscriptions.services.requests.post")
    def test_initiate_payment_returns_authorization_url(self, mock_post):
        plan = Plan.objects.get(slug="starter")
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "status": True,
            "data": {
                "authorization_url": "https://checkout.paystack.com/xyz",
                "access_code": "xyz",
                "reference": "SUB-XYZ",
            },
        }
        mock_post.return_value = mock_resp

        res = self.client.post(
            "/api/v1/subscriptions/initiate-payment/",
            {"plan_id": str(plan.id)},
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn("authorization_url", res.data)
        self.assertIn("reference", res.data)

    def test_payment_history_empty(self):
        res = self.client.get("/api/v1/subscriptions/payments/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, [])
