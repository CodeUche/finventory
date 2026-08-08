"""
Tests for apps.subscriptions.payment_engine.PaymentEngine.

Covers: idempotent re-activation, cross-kind reference collision, amount
mismatch, org mismatch, refund handling (full/partial), the delivery-lapse
gate primitive, and the regression test proving the real production bug
(charge webhooks signed with Audity's own Paystack secret never reached
activate_from_webhook because there is no PaymentGatewayConfig row for the
platform's own account) is fixed.
"""

import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.models import User
from apps.subscriptions.models import (
    IntegrationProduct,
    OrganisationIntegrationEntitlement,
    PaymentHistory,
    Plan,
    Subscription,
)
from apps.subscriptions.payment_engine import PaymentEngine, org_can_receive_integration_delivery
from apps.tenancy.models import Organisation


def _make_user(email="payeng@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!", first_name="Pay", last_name="Eng",
        is_verified=True,
    )


def _make_org(user, name="PayEngine Org"):
    from apps.tenancy.services import OrganisationService
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _paystack_verify_success(amount_kobo, org_id, plan_id=None, product_key=None, reference="REF"):
    metadata = {"org_id": str(org_id)}
    if plan_id:
        metadata["plan_id"] = str(plan_id)
    if product_key:
        metadata["product_key"] = product_key
    resp = MagicMock(status_code=200)
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "status": True,
        "data": {
            "status": "success",
            "reference": reference,
            "amount": amount_kobo,
            "metadata": metadata,
        },
    }
    return resp


class PaymentEngineActivateTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        self.plan = Plan.objects.get(slug="professional")
        # get_or_create, not create: apps.integrations' seed data migration
        # (0002_seed_integration_products) now seeds a real "zapier"
        # IntegrationProduct row as part of the test DB's migration history,
        # so an unconditional .create() with the same key collides on the
        # unique constraint. Reuse the seeded row if present.
        self.product, _ = IntegrationProduct.objects.get_or_create(
            key="zapier", defaults={"name": "Zapier Connector", "price": Decimal("5000.00")},
        )

    def _create_pending_subscription_payment(self, reference="SUB-TESTREF1"):
        # A settled (non-PENDING) subscription-kind row must have `subscription`
        # set (DB CHECK constraint) — mirrors PaymentEngine._initiate_subscription's
        # eager Subscription resolution.
        sub = self.org.subscription
        return PaymentHistory.objects.create(
            kind=PaymentHistory.Kind.SUBSCRIPTION,
            organisation=self.org,
            subscription=sub,
            expected_amount=self.plan.price,
            amount=self.plan.price,
            status=PaymentHistory.Status.PENDING,
            provider_payment_id=reference,
            description="Pending payment for Professional plan",
        )

    def _create_pending_integration_payment(self, reference="INT-TESTREF1"):
        entitlement = OrganisationIntegrationEntitlement.objects.create(
            organisation=self.org, product=self.product,
            status=OrganisationIntegrationEntitlement.Status.PENDING,
        )
        payment = PaymentHistory.objects.create(
            kind=PaymentHistory.Kind.INTEGRATION,
            organisation=self.org,
            integration_entitlement=entitlement,
            expected_amount=self.product.price,
            amount=self.product.price,
            status=PaymentHistory.Status.PENDING,
            provider_payment_id=reference,
            description="Pending payment for Zapier integration",
        )
        return payment, entitlement

    @patch("apps.subscriptions.payment_engine.requests.get")
    def test_activate_subscription_success(self, mock_get):
        payment = self._create_pending_subscription_payment("SUB-ACT1")
        amount_kobo = int(self.plan.price * 100)
        mock_get.return_value = _paystack_verify_success(
            amount_kobo, self.org.id, plan_id=self.plan.id, reference="SUB-ACT1",
        )

        result = PaymentEngine.activate("SUB-ACT1")

        self.assertEqual(result.status, PaymentHistory.Status.SUCCEEDED)
        self.org.refresh_from_db()
        self.assertEqual(self.org.subscription.status, Subscription.Status.ACTIVE)
        self.assertEqual(self.org.subscription.plan.slug, "professional")

    @patch("apps.subscriptions.payment_engine.requests.get")
    def test_activate_integration_success(self, mock_get):
        payment, entitlement = self._create_pending_integration_payment("INT-ACT1")
        amount_kobo = int(self.product.price * 100)
        mock_get.return_value = _paystack_verify_success(
            amount_kobo, self.org.id, product_key=self.product.key, reference="INT-ACT1",
        )

        result = PaymentEngine.activate("INT-ACT1")

        self.assertEqual(result.status, PaymentHistory.Status.SUCCEEDED)
        entitlement.refresh_from_db()
        self.assertEqual(entitlement.status, OrganisationIntegrationEntitlement.Status.ACTIVE)
        self.assertIsNotNone(entitlement.purchased_at)

    @patch("apps.subscriptions.payment_engine.requests.get")
    def test_activate_is_idempotent_on_duplicate_delivery(self, mock_get):
        """Calling activate() twice for the same succeeded reference is a clean
        no-op on the second call — Paystack is hit at most once."""
        self._create_pending_subscription_payment("SUB-IDEMP1")
        amount_kobo = int(self.plan.price * 100)
        mock_get.return_value = _paystack_verify_success(
            amount_kobo, self.org.id, plan_id=self.plan.id, reference="SUB-IDEMP1",
        )

        first = PaymentEngine.activate("SUB-IDEMP1")
        second = PaymentEngine.activate("SUB-IDEMP1")

        self.assertEqual(first.status, PaymentHistory.Status.SUCCEEDED)
        self.assertEqual(second.status, PaymentHistory.Status.SUCCEEDED)
        self.assertEqual(mock_get.call_count, 1)

    def test_reference_claimed_by_subscription_rejected_as_integration_target(self):
        """provider_payment_id is globally unique — a reference already used
        by a subscription PaymentHistory row cannot be reused for an
        integration PaymentHistory row."""
        self._create_pending_subscription_payment("SUB-SHARED1")
        entitlement = OrganisationIntegrationEntitlement.objects.create(
            organisation=self.org, product=self.product,
        )
        with self.assertRaises(IntegrityError):
            PaymentHistory.objects.create(
                kind=PaymentHistory.Kind.INTEGRATION,
                organisation=self.org,
                integration_entitlement=entitlement,
                expected_amount=self.product.price,
                amount=self.product.price,
                status=PaymentHistory.Status.PENDING,
                provider_payment_id="SUB-SHARED1",  # collides with the subscription ref
            )

    @patch("apps.subscriptions.payment_engine.requests.get")
    def test_underpayment_rejected(self, mock_get):
        """Genuine underpayment (actual < expected) is the real risk this
        check exists for — reject it and mark the row FAILED."""
        self._create_pending_subscription_payment("SUB-BADAMT")
        short_amount_kobo = int(self.plan.price * 100) - 500000  # way short
        mock_get.return_value = _paystack_verify_success(
            short_amount_kobo, self.org.id, plan_id=self.plan.id, reference="SUB-BADAMT",
        )

        with self.assertRaises(ValueError) as ctx:
            PaymentEngine.activate("SUB-BADAMT")
        self.assertIn("Amount mismatch", str(ctx.exception))

        payment = PaymentHistory.objects.get(provider_payment_id="SUB-BADAMT")
        self.assertEqual(payment.status, PaymentHistory.Status.FAILED)

    @patch("apps.subscriptions.payment_engine.requests.get")
    def test_overpayment_accepted(self, mock_get):
        """Regression test for a confirmed production incident: Paystack can
        add its own convenience fee on top of the initialized amount (seen on
        the bank_transfer channel — a real ₦15,000 integration purchase came
        back as ₦15,329.95) and passes that cost to the customer, so a
        genuinely successful payment can legitimately verify ABOVE what we
        expected. That must succeed, not be rejected as a "mismatch" — only
        underpayment is a real risk."""
        payment, entitlement = self._create_pending_integration_payment("INT-OVERPAID")
        over_amount_kobo = int(self.product.price * 100) + 32995  # Paystack fee on top
        mock_get.return_value = _paystack_verify_success(
            over_amount_kobo, self.org.id, product_key=self.product.key, reference="INT-OVERPAID",
        )

        result = PaymentEngine.activate("INT-OVERPAID")

        self.assertEqual(result.status, PaymentHistory.Status.SUCCEEDED)
        entitlement.refresh_from_db()
        self.assertEqual(entitlement.status, OrganisationIntegrationEntitlement.Status.ACTIVE)

    @patch("apps.subscriptions.payment_engine.requests.get")
    def test_transient_not_yet_successful_status_does_not_poison_payment(self, mock_get):
        """Regression test for the other half of the same production
        incident: activate() is now polled repeatedly (background poll right
        after checkout opens, a silent check on every page load, the manual
        "Restore access" button) and the very first tick typically fires
        before the customer has finished paying. A transient Paystack status
        (still "abandoned"/pending at that moment) must leave the row PENDING
        so a later, genuine success can still be recorded — not permanently
        mark it FAILED on the first premature check."""
        payment, entitlement = self._create_pending_integration_payment("INT-NOTYET")
        resp = MagicMock(status_code=200)
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"status": True, "data": {"status": "abandoned"}}
        mock_get.return_value = resp

        with self.assertRaises(ValueError):
            PaymentEngine.activate("INT-NOTYET")

        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentHistory.Status.PENDING)

        # The genuine success arrives later — activate() must still be able
        # to settle it, proving the row was never poisoned.
        amount_kobo = int(self.product.price * 100)
        mock_get.return_value = _paystack_verify_success(
            amount_kobo, self.org.id, product_key=self.product.key, reference="INT-NOTYET",
        )
        result = PaymentEngine.activate("INT-NOTYET")
        self.assertEqual(result.status, PaymentHistory.Status.SUCCEEDED)
        entitlement.refresh_from_db()
        self.assertEqual(entitlement.status, OrganisationIntegrationEntitlement.Status.ACTIVE)

    @patch("apps.subscriptions.payment_engine.requests.get")
    def test_explicit_failed_status_still_marks_payment_failed(self, mock_get):
        """A genuinely TERMINAL Paystack status ("failed") is still allowed
        to poison the row — only the transient/ambiguous statuses were the
        bug."""
        payment, _entitlement = self._create_pending_integration_payment("INT-REALLYFAILED")
        resp = MagicMock(status_code=200)
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"status": True, "data": {"status": "failed"}}
        mock_get.return_value = resp

        with self.assertRaises(ValueError):
            PaymentEngine.activate("INT-REALLYFAILED")

        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentHistory.Status.FAILED)

    @patch("apps.subscriptions.payment_engine.requests.get")
    def test_org_mismatch_rejected(self, mock_get):
        self._create_pending_subscription_payment("SUB-BADORG")
        other_user = _make_user("other@example.com")
        other_org = _make_org(other_user, "Other Org")
        amount_kobo = int(self.plan.price * 100)
        mock_get.return_value = _paystack_verify_success(
            amount_kobo, other_org.id, plan_id=self.plan.id, reference="SUB-BADORG",
        )

        with self.assertRaises(ValueError) as ctx:
            PaymentEngine.activate("SUB-BADORG")
        self.assertIn("Organisation mismatch", str(ctx.exception))

        payment = PaymentHistory.objects.get(provider_payment_id="SUB-BADORG")
        self.assertEqual(payment.status, PaymentHistory.Status.FAILED)


class VerifyIntegrationPaymentIDORTests(TestCase):
    """
    Regression tests for the cross-tenant IDOR on
    SubscriptionViewSet.verify_integration_payment (views.py): an
    authenticated caller from Org X must not be able to settle or read
    another org's (Org Y's) integration PaymentHistory row merely by
    knowing/guessing its INT-XXXXXXXX reference. PaymentEngine.activate()
    itself has no org context, so the ownership check must live in the view
    — mirroring PaystackSubscriptionService.verify_payment's existing
    payment.organisation_id != organisation.id check.
    """

    def setUp(self):
        self.client = APIClient()

        self.owner_x = _make_user("orgx-owner@example.com")
        self.org_x = _make_org(self.owner_x, "Org X")
        self.owner_y = _make_user("orgy-owner@example.com")
        self.org_y = _make_org(self.owner_y, "Org Y")

        self.product = IntegrationProduct.objects.create(
            key="hubspot", name="HubSpot Connector", price=Decimal("7500.00"),
        )

        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(self.owner_x)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
            HTTP_X_ORGANISATION_ID=str(self.org_x.id),
        )

    def _create_pending_integration_payment_for(self, org, reference):
        entitlement = OrganisationIntegrationEntitlement.objects.create(
            organisation=org, product=self.product,
            status=OrganisationIntegrationEntitlement.Status.PENDING,
        )
        payment = PaymentHistory.objects.create(
            kind=PaymentHistory.Kind.INTEGRATION,
            organisation=org,
            integration_entitlement=entitlement,
            expected_amount=self.product.price,
            amount=self.product.price,
            status=PaymentHistory.Status.PENDING,
            provider_payment_id=reference,
            description=f"Pending payment for {self.product.name} integration",
        )
        return payment, entitlement

    @patch("apps.subscriptions.payment_engine.requests.get")
    def test_cross_org_reference_returns_404_with_no_payment_data_leaked(self, mock_get):
        """PoC: Org X's authenticated session POSTs a reference belonging to
        Org Y's PaymentHistory row. Paystack verification genuinely succeeds
        (so this proves the check is NOT merely 'reject before verifying'),
        but the response must still be a 404 with no payment amount/currency/
        description disclosed to Org X."""
        payment_y, entitlement_y = self._create_pending_integration_payment_for(
            self.org_y, "INT-BELONGSTOY01",
        )
        amount_kobo = int(self.product.price * 100)
        mock_get.return_value = _paystack_verify_success(
            amount_kobo, self.org_y.id, product_key=self.product.key,
            reference="INT-BELONGSTOY01",
        )

        response = self.client.post(
            "/api/v1/subscriptions/integrations/verify-payment/",
            {"reference": "INT-BELONGSTOY01"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        body = str(response.data)
        # No cross-org information disclosure: amount/description must not leak.
        self.assertNotIn("7500", body)
        self.assertNotIn("HubSpot", body)
        self.assertNotIn(str(payment_y.id), body)

        # PaymentEngine.activate() still ran to completion (it can't grant
        # something unpaid) — Org Y's own payment/entitlement really are
        # settled server-side; the view just refuses to hand the result to
        # Org X. This documents that behavior rather than asserting it should
        # be different (activate()'s core locking logic is out of scope here).
        payment_y.refresh_from_db()
        entitlement_y.refresh_from_db()
        self.assertEqual(payment_y.status, PaymentHistory.Status.SUCCEEDED)
        self.assertEqual(entitlement_y.status, OrganisationIntegrationEntitlement.Status.ACTIVE)

    @patch("apps.subscriptions.payment_engine.requests.get")
    def test_same_org_reference_still_succeeds(self, mock_get):
        """Happy path must not regress: an org verifying its OWN integration
        payment reference still gets 200 with the payment data."""
        payment_x, entitlement_x = self._create_pending_integration_payment_for(
            self.org_x, "INT-BELONGSTOX01",
        )
        amount_kobo = int(self.product.price * 100)
        mock_get.return_value = _paystack_verify_success(
            amount_kobo, self.org_x.id, product_key=self.product.key,
            reference="INT-BELONGSTOX01",
        )

        response = self.client.post(
            "/api/v1/subscriptions/integrations/verify-payment/",
            {"reference": "INT-BELONGSTOX01"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], PaymentHistory.Status.SUCCEEDED)
        entitlement_x.refresh_from_db()
        self.assertEqual(entitlement_x.status, OrganisationIntegrationEntitlement.Status.ACTIVE)


class PaymentEngineRefundTests(TestCase):
    def setUp(self):
        self.user = _make_user("refund@example.com")
        self.org = _make_org(self.user, "Refund Org")
        self.product = IntegrationProduct.objects.create(
            key="slack-connector", name="Slack Connector", price=Decimal("10000.00"),
        )
        self.entitlement = OrganisationIntegrationEntitlement.objects.create(
            organisation=self.org, product=self.product,
            status=OrganisationIntegrationEntitlement.Status.ACTIVE,
            purchased_at=timezone.now(),
        )
        self.payment = PaymentHistory.objects.create(
            kind=PaymentHistory.Kind.INTEGRATION,
            organisation=self.org,
            integration_entitlement=self.entitlement,
            expected_amount=self.product.price,
            amount=self.product.price,
            status=PaymentHistory.Status.SUCCEEDED,
            provider_payment_id="INT-REFUND1",
        )

    def test_full_refund_revokes_entitlement(self):
        refund_data = {
            "amount": int(self.product.price * 100),
            "transaction": {"reference": "INT-REFUND1"},
        }
        PaymentEngine.handle_refund_webhook(refund_data)

        self.entitlement.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.entitlement.status, OrganisationIntegrationEntitlement.Status.REVOKED)
        self.assertEqual(self.entitlement.revoked_reason, "refunded")
        self.assertEqual(self.payment.status, PaymentHistory.Status.REFUNDED)

    def test_partial_refund_leaves_entitlement_active(self):
        refund_data = {
            "amount": int(Decimal("2000.00") * 100),  # less than full 10000
            "transaction": {"reference": "INT-REFUND1"},
        }
        with self.assertLogs("apps.subscriptions.payment_engine", level="WARNING") as cm:
            PaymentEngine.handle_refund_webhook(refund_data)
        self.assertTrue(any("Partial refund" in msg for msg in cm.output))

        self.entitlement.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertEqual(self.entitlement.status, OrganisationIntegrationEntitlement.Status.ACTIVE)
        self.assertEqual(self.payment.status, PaymentHistory.Status.PARTIALLY_REFUNDED)


class InitiateIntegrationDoubleCheckoutRaceTests(TestCase):
    """
    Regression tests for the double-purchase race in
    PaymentEngine._initiate_integration: two near-simultaneous purchase
    requests for the same (org, product) must not both mint separate
    Paystack references for one entitlement.

    The test DB is SQLite `:memory:` (config.settings.testing), which does
    not give us true multi-connection select_for_update() blocking the way
    Postgres threading tests would — there is no existing precedent for a
    threading-based lock test anywhere in this codebase (checked: no
    apps/*/tests*.py uses `threading`/`Thread(` against a lock). Instead
    these tests prove the check-then-act contract directly: the entitlement
    lookup, ACTIVE check, and in-flight-PENDING-payment check all happen
    inside one atomic block before the PaymentHistory row commits, so a
    second call that runs after the first has committed correctly sees the
    first's PENDING row and is rejected — the same outcome select_for_update
    guarantees under real concurrency (the second caller blocks until the
    first commits, then sees the same state this test sets up directly).
    """

    def setUp(self):
        self.user = _make_user("race@example.com")
        self.org = _make_org(self.user, "Race Org")
        self.product = IntegrationProduct.objects.create(
            key="race-connector", name="Race Connector", price=Decimal("3000.00"),
        )

    def _init_ok_response(self):
        """Paystack's initialize response doesn't echo our reference in
        `data` (it's only ever passed in `reference` on our own request
        payload) — the mock just needs a plausible envelope."""
        resp = MagicMock(status_code=200)
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "status": True,
            "data": {
                "authorization_url": "https://checkout.paystack.com/test",
                "access_code": "code123",
            },
        }
        return resp

    @patch("apps.subscriptions.payment_engine.requests.post")
    def test_second_purchase_call_rejected_while_first_payment_pending(self, mock_post):
        """First call succeeds and leaves a PENDING PaymentHistory row +
        reference. A second purchase call for the same (org, product) made
        before the first payment resolves must be rejected — not issue a
        second independent Paystack reference."""
        mock_post.return_value = self._init_ok_response()

        first_result = PaymentEngine.initiate(
            self.org, PaymentHistory.Kind.INTEGRATION, self.product, "race@example.com",
        )
        self.assertTrue(first_result["reference"].startswith("INT-"))

        with self.assertRaises(ValueError) as ctx:
            PaymentEngine.initiate(
                self.org, PaymentHistory.Kind.INTEGRATION, self.product, "race@example.com",
            )
        self.assertIn("already in progress", str(ctx.exception))

        # Only one Paystack initialize call happened, and only one
        # PaymentHistory row exists for this entitlement — no double-charge
        # risk from a second independent reference.
        self.assertEqual(mock_post.call_count, 1)
        count = PaymentHistory.objects.filter(
            kind=PaymentHistory.Kind.INTEGRATION,
            integration_entitlement__organisation=self.org,
            integration_entitlement__product=self.product,
        ).count()
        self.assertEqual(count, 1)

    @patch("apps.subscriptions.payment_engine.requests.post")
    def test_purchase_rejected_once_entitlement_is_active(self, mock_post):
        """Existing ACTIVE-status guard still works after the locking change."""
        mock_post.return_value = self._init_ok_response()
        entitlement = OrganisationIntegrationEntitlement.objects.create(
            organisation=self.org, product=self.product,
            status=OrganisationIntegrationEntitlement.Status.ACTIVE,
            purchased_at=timezone.now(),
        )
        with self.assertRaises(ValueError) as ctx:
            PaymentEngine.initiate(
                self.org, PaymentHistory.Kind.INTEGRATION, self.product, "race@example.com",
            )
        self.assertIn("already owns this integration", str(ctx.exception))
        mock_post.assert_not_called()

    @patch("apps.subscriptions.payment_engine.requests.post")
    def test_new_purchase_allowed_after_prior_payment_failed(self, mock_post):
        """A previously FAILED payment (e.g. abandoned checkout) must not
        permanently block re-purchase — only a live PENDING row blocks."""
        entitlement = OrganisationIntegrationEntitlement.objects.create(
            organisation=self.org, product=self.product,
            status=OrganisationIntegrationEntitlement.Status.PENDING,
        )
        PaymentHistory.objects.create(
            kind=PaymentHistory.Kind.INTEGRATION,
            organisation=self.org,
            integration_entitlement=entitlement,
            expected_amount=self.product.price,
            amount=self.product.price,
            status=PaymentHistory.Status.FAILED,
            provider_payment_id="INT-OLDFAILED01",
        )
        mock_post.return_value = self._init_ok_response()

        result = PaymentEngine.initiate(
            self.org, PaymentHistory.Kind.INTEGRATION, self.product, "race@example.com",
        )
        self.assertTrue(result["reference"].startswith("INT-"))
        mock_post.assert_called_once()


class DeliveryLapseGateTests(TestCase):
    def setUp(self):
        self.user = _make_user("gate@example.com")
        self.org = _make_org(self.user, "Gate Org")

    def test_active_subscription_can_receive_delivery(self):
        sub = self.org.subscription
        sub.status = Subscription.Status.ACTIVE
        sub.current_period_end = timezone.now() + timezone.timedelta(days=10)
        sub.save()
        self.assertTrue(org_can_receive_integration_delivery(self.org))

    def test_trialing_subscription_can_receive_delivery(self):
        sub = self.org.subscription
        sub.status = Subscription.Status.TRIALING
        sub.trial_end = timezone.now() + timezone.timedelta(days=5)
        sub.save()
        self.assertTrue(org_can_receive_integration_delivery(self.org))

    def test_past_due_subscription_blocks_delivery(self):
        sub = self.org.subscription
        sub.status = Subscription.Status.PAST_DUE
        sub.save()
        self.assertFalse(org_can_receive_integration_delivery(self.org))

    def test_canceled_subscription_blocks_delivery(self):
        sub = self.org.subscription
        sub.status = Subscription.Status.CANCELED
        sub.save()
        self.assertFalse(org_can_receive_integration_delivery(self.org))

    def test_expired_active_subscription_blocks_delivery(self):
        sub = self.org.subscription
        sub.status = Subscription.Status.ACTIVE
        sub.current_period_end = timezone.now() - timezone.timedelta(days=1)
        sub.save()
        self.assertFalse(org_can_receive_integration_delivery(self.org))

    def test_no_subscription_blocks_delivery(self):
        self.org.subscription = None
        self.org.save()
        self.assertFalse(org_can_receive_integration_delivery(self.org))


class WebhookRoutingRegressionTests(TestCase):
    """
    Proves the confirmed production bug is fixed: a genuine Paystack webhook
    signed with Audity's OWN platform secret (settings.PAYSTACK_SECRET_KEY)
    — as opposed to any merchant's PaymentGatewayConfig secret — must route
    to PaymentEngine.activate via the real HTTP webhook route, not just via
    a direct Python call.
    """

    def setUp(self):
        self.user = _make_user("webhook@example.com")
        self.org = _make_org(self.user, "Webhook Org")
        self.plan = Plan.objects.get(slug="professional")
        self.client = APIClient()

    def _sign(self, raw_body: bytes) -> str:
        return hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode(), msg=raw_body, digestmod=hashlib.sha512,
        ).hexdigest()

    @patch("apps.subscriptions.payment_engine.PaymentEngine.activate")
    def test_platform_signed_webhook_routes_to_payment_engine(self, mock_activate):
        mock_activate.return_value = MagicMock()
        payload = {
            "event": "charge.success",
            "data": {
                "reference": "SUB-WEBHOOKTEST1",
                "amount": int(self.plan.price * 100),
                "metadata": {
                    "payment_kind": "subscription",
                    "plan_id": str(self.plan.id),
                    "org_id": str(self.org.id),
                },
            },
        }
        raw_body = json.dumps(payload).encode()
        signature = self._sign(raw_body)

        response = self.client.post(
            "/api/v1/payments/webhook/paystack/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)
        mock_activate.assert_called_once_with("SUB-WEBHOOKTEST1")

    def test_unsigned_webhook_falls_through_to_unverified(self):
        """A request signed with neither the platform secret nor any merchant
        config secret must still fall through to the existing unverified/400
        response — no regression on the legacy merchant path."""
        payload = {
            "event": "charge.success",
            "data": {
                "reference": "SUB-UNSIGNED1",
                "amount": 100000,
                "metadata": {"payment_kind": "subscription"},
            },
        }
        raw_body = json.dumps(payload).encode()

        response = self.client.post(
            "/api/v1/payments/webhook/paystack/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE="deadbeef" * 16,  # garbage signature
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["status"], "unverified")
