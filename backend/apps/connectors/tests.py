"""
Tests for Connectors (Slack / Google Sheets via Nango).

Covers:
    - Tenant isolation: org A cannot read, connect, restore, disconnect, or
      configure org B's ConnectorConnection through the API.
    - Quota math: Plan.features['max_connectors'] read correctly per tier;
      has_quota_slot / quota_summary arithmetic.
    - Connection lifecycle: quota-gated start_connect_session (plan_quota vs
      paid_addon vs QuotaExceededError), AlreadyConnectedError, webhook
      activation (success + non-terminal failure that must NOT poison
      status), check_and_restore's "never mark failed on first check" rule,
      disconnect.
    - Nango-not-configured fails loudly (NangoNotConfiguredError -> 503),
      never silently no-ops.
    - Webhook signature verification (valid accepted, invalid/missing
      rejected).
    - ₦4,500/month recurring add-on billing: Decimal correctness, PaymentHistory
      CHECK constraint (exactly one target), period length (30 vs 365 days).
"""

import hashlib
import hmac
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.subscriptions.models import PaymentHistory, Plan
from apps.subscriptions.payment_engine import PaymentEngine
from apps.tenancy.models import Membership
from apps.tenancy.services import OrganisationService

from . import nango
from .models import Connector, ConnectorAddonSubscription, ConnectorConnection
from .pricing import CONNECTOR_ADDON_ANNUAL_PRICE, CONNECTOR_ADDON_MONTHLY_PRICE, price_for_interval
from .services import (
    AlreadyConnectedError,
    ConnectorConnectionService,
    ConnectorQuotaService,
    QuotaExceededError,
)


def _make_user(email):
    return User.objects.create_user(
        email=email, password="TestPass123!", first_name="Test", last_name="User", is_verified=True,
    )


def _make_org(user, name="Test Org"):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _add_member(org, user, role=Membership.Role.OWNER):
    membership, _ = Membership.objects.update_or_create(
        user=user, organisation=org, defaults={"role": role, "is_active": True},
    )
    return membership


def _auth_client(user, org):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return client


def _set_plan(org, slug):
    org.subscription.plan = Plan.objects.get(slug=slug)
    org.subscription.status = org.subscription.__class__.Status.ACTIVE
    org.subscription.save()
    return org.subscription


class QuotaMathTests(TestCase):
    """Plan.features['max_connectors'] arithmetic — no live Nango call involved."""

    def setUp(self):
        self.user = _make_user("quota@example.com")
        self.org = _make_org(self.user)

    def test_free_plan_has_zero_connectors(self):
        _set_plan(self.org, "free")
        self.assertEqual(ConnectorQuotaService.max_connectors(self.org), 0)
        self.assertFalse(ConnectorQuotaService.has_quota_slot(self.org))

    def test_professional_plan_has_one_connector(self):
        _set_plan(self.org, "professional")
        self.assertEqual(ConnectorQuotaService.max_connectors(self.org), 1)
        self.assertTrue(ConnectorQuotaService.has_quota_slot(self.org))

    def test_business_plan_has_three_connectors(self):
        _set_plan(self.org, "business")
        self.assertEqual(ConnectorQuotaService.max_connectors(self.org), 3)

    def test_enterprise_plan_has_five_connectors(self):
        _set_plan(self.org, "enterprise")
        self.assertEqual(ConnectorQuotaService.max_connectors(self.org), 5)

    def test_quota_slot_consumed_by_active_plan_quota_connection(self):
        _set_plan(self.org, "professional")  # quota = 1
        self.assertTrue(ConnectorQuotaService.has_quota_slot(self.org))
        ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.SLACK,
            status=ConnectorConnection.Status.ACTIVE,
            billing_mode=ConnectorConnection.BillingMode.PLAN_QUOTA,
        )
        self.assertFalse(ConnectorQuotaService.has_quota_slot(self.org))

    def test_pending_connection_does_not_consume_quota(self):
        _set_plan(self.org, "professional")
        ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.SLACK,
            status=ConnectorConnection.Status.PENDING,
            billing_mode=ConnectorConnection.BillingMode.PLAN_QUOTA,
        )
        self.assertTrue(ConnectorQuotaService.has_quota_slot(self.org))

    def test_paid_addon_connection_does_not_count_against_plan_quota(self):
        _set_plan(self.org, "free")  # quota = 0
        ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.SLACK,
            status=ConnectorConnection.Status.ACTIVE,
            billing_mode=ConnectorConnection.BillingMode.PAID_ADDON,
        )
        # Slot count is scoped to plan_quota connections only.
        self.assertEqual(ConnectorQuotaService.active_plan_quota_count(self.org), 0)


class ConnectorConnectionServiceTests(TestCase):
    """start_connect_session / apply_webhook / check_and_restore / disconnect."""

    def setUp(self):
        self.user = _make_user("svc@example.com")
        self.org = _make_org(self.user)
        _set_plan(self.org, "free")  # quota = 0, forces the paid_addon / exceeded branches

    def test_nango_not_configured_raises_clear_error_not_silent_noop(self):
        """
        Mirrors the current real-world state: no NANGO_SECRET_KEY is set
        anywhere yet. This must fail LOUDLY (a specific exception a caller
        can catch and turn into a 503), never silently no-op or crash with
        an unrelated error.
        """
        _set_plan(self.org, "professional")  # give it quota so we reach the Nango call
        with self.assertRaises(nango.NangoNotConfiguredError):
            ConnectorConnectionService.start_connect_session(self.org, Connector.SLACK, self.user)

    def test_quota_exceeded_raises_before_ever_calling_nango(self):
        # Free plan (quota=0), no add-on — must fail on quota, not reach Nango
        # at all (proven by NOT raising NangoNotConfiguredError here even
        # though NANGO_SECRET_KEY is unset).
        with self.assertRaises(QuotaExceededError):
            ConnectorConnectionService.start_connect_session(self.org, Connector.SLACK, self.user)

    @patch("apps.connectors.nango.create_connect_session")
    @override_settings(NANGO_SECRET_KEY="test_secret")
    def test_start_connect_session_within_quota_succeeds(self, mock_create):
        mock_create.return_value = {"token": "tok_123", "connect_link": "https://nango.dev/connect/tok_123", "expires_at": "2026-01-01T00:00:00Z"}
        _set_plan(self.org, "professional")
        result = ConnectorConnectionService.start_connect_session(self.org, Connector.SLACK, self.user)
        self.assertEqual(result["connect_link"], "https://nango.dev/connect/tok_123")
        conn = ConnectorConnection.objects.get(organisation=self.org, connector_key=Connector.SLACK)
        self.assertEqual(conn.status, ConnectorConnection.Status.PENDING)
        self.assertEqual(conn.billing_mode, ConnectorConnection.BillingMode.PLAN_QUOTA)

    @patch("apps.connectors.nango.create_connect_session")
    @override_settings(NANGO_SECRET_KEY="test_secret")
    def test_start_connect_session_beyond_quota_uses_paid_addon_when_active(self, mock_create):
        mock_create.return_value = {"token": "tok_456", "connect_link": "https://nango.dev/connect/tok_456", "expires_at": "2026-01-01T00:00:00Z"}
        addon = ConnectorAddonSubscription.objects.create(
            organisation=self.org, connector_key=Connector.SLACK,
            status=ConnectorAddonSubscription.Status.ACTIVE,
            interval=ConnectorAddonSubscription.Interval.MONTHLY,
            amount=CONNECTOR_ADDON_MONTHLY_PRICE,
            current_period_end=timezone.now() + timezone.timedelta(days=10),
        )
        result = ConnectorConnectionService.start_connect_session(self.org, Connector.SLACK, self.user)
        self.assertIn("connect_link", result)
        conn = ConnectorConnection.objects.get(organisation=self.org, connector_key=Connector.SLACK)
        self.assertEqual(conn.billing_mode, ConnectorConnection.BillingMode.PAID_ADDON)

    @override_settings(NANGO_SECRET_KEY="test_secret")
    def test_already_active_connection_raises_already_connected(self):
        _set_plan(self.org, "professional")
        ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.SLACK,
            status=ConnectorConnection.Status.ACTIVE,
        )
        with self.assertRaises(AlreadyConnectedError):
            ConnectorConnectionService.start_connect_session(self.org, Connector.SLACK, self.user)

    def test_apply_webhook_activates_connection_on_success(self):
        conn = ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.SLACK,
            status=ConnectorConnection.Status.PENDING, pending_session_token="tok_abc",
        )
        payload = {
            "type": "auth",
            "operation": "creation",
            "connectionId": "conn_xyz",
            "providerConfigKey": "slack",
            "success": True,
            "tags": {"organization_id": str(self.org.id)},
            "metadata": {"team": {"name": "Audity HQ"}},
        }
        ConnectorConnectionService.apply_webhook(payload)
        conn.refresh_from_db()
        self.assertEqual(conn.status, ConnectorConnection.Status.ACTIVE)
        self.assertEqual(conn.nango_connection_id, "conn_xyz")
        self.assertEqual(conn.external_account_label, "Audity HQ")
        self.assertEqual(conn.pending_session_token, "")

    def test_apply_webhook_failure_does_not_poison_status(self):
        """
        A failed auth webhook must NOT flip status to some permanent failed
        state — the user can just click Connect again. This mirrors the
        exact "never mark failed on a not-yet-successful read" lesson from
        the Paystack payment-poll incident (see PaymentEngine.activate).
        """
        conn = ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.SLACK,
            status=ConnectorConnection.Status.PENDING,
        )
        payload = {
            "type": "auth", "operation": "creation", "connectionId": "conn_xyz",
            "providerConfigKey": "slack", "success": False,
            "tags": {"organization_id": str(self.org.id)},
            "error": {"type": "user_cancelled", "description": "closed the window"},
        }
        ConnectorConnectionService.apply_webhook(payload)
        conn.refresh_from_db()
        self.assertEqual(conn.status, ConnectorConnection.Status.PENDING)

    def test_apply_webhook_ignores_non_auth_events(self):
        conn = ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.SLACK,
            status=ConnectorConnection.Status.PENDING,
        )
        ConnectorConnectionService.apply_webhook({"type": "sync", "connectionId": "x"})
        conn.refresh_from_db()
        self.assertEqual(conn.status, ConnectorConnection.Status.PENDING)

    @patch("apps.connectors.nango.list_connections_for_org")
    @override_settings(NANGO_SECRET_KEY="test_secret")
    def test_check_and_restore_never_marks_failed_when_not_yet_complete(self, mock_list):
        mock_list.return_value = []
        conn = ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.SLACK,
            status=ConnectorConnection.Status.PENDING,
        )
        with self.assertRaises(ValueError):
            ConnectorConnectionService.check_and_restore(self.org, Connector.SLACK)
        conn.refresh_from_db()
        # Still PENDING, not some poisoned failed state — the user can retry.
        self.assertEqual(conn.status, ConnectorConnection.Status.PENDING)

    @patch("apps.connectors.nango.list_connections_for_org")
    @override_settings(NANGO_SECRET_KEY="test_secret")
    def test_check_and_restore_activates_when_nango_confirms(self, mock_list):
        mock_list.return_value = [{"connection_id": "conn_999", "provider_config_key": "slack", "metadata": {}}]
        ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.SLACK,
            status=ConnectorConnection.Status.PENDING,
        )
        conn = ConnectorConnectionService.check_and_restore(self.org, Connector.SLACK)
        self.assertEqual(conn.status, ConnectorConnection.Status.ACTIVE)
        self.assertEqual(conn.nango_connection_id, "conn_999")

    def test_check_and_restore_does_not_resurrect_a_revoked_connection(self):
        ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.SLACK,
            status=ConnectorConnection.Status.REVOKED,
        )
        with self.assertRaises(ValueError):
            ConnectorConnectionService.check_and_restore(self.org, Connector.SLACK)

    def test_disconnect_marks_revoked(self):
        ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.SLACK,
            status=ConnectorConnection.Status.ACTIVE, nango_connection_id="conn_1",
        )
        conn = ConnectorConnectionService.disconnect(self.org, Connector.SLACK)
        self.assertEqual(conn.status, ConnectorConnection.Status.REVOKED)
        self.assertIsNotNone(conn.revoked_at)


class WebhookSignatureTests(TestCase):
    def test_valid_signature_accepted(self):
        with override_settings(NANGO_WEBHOOK_SECRET="whsec_123"):
            body = b'{"type":"auth"}'
            sig = hmac.new(b"whsec_123", msg=body, digestmod=hashlib.sha256).hexdigest()
            self.assertTrue(nango.verify_webhook_signature(body, sig))

    def test_invalid_signature_rejected(self):
        with override_settings(NANGO_WEBHOOK_SECRET="whsec_123"):
            self.assertFalse(nango.verify_webhook_signature(b'{"type":"auth"}', "deadbeef"))

    def test_missing_signature_rejected(self):
        with override_settings(NANGO_WEBHOOK_SECRET="whsec_123"):
            self.assertFalse(nango.verify_webhook_signature(b'{"type":"auth"}', ""))

    def test_unconfigured_secret_fails_closed(self):
        # No NANGO_WEBHOOK_SECRET / NANGO_SECRET_KEY set — must reject, not crash.
        self.assertFalse(nango.verify_webhook_signature(b"{}", "anything"))


class ConnectorAddonBillingTests(TestCase):
    """₦4,500/month recurring add-on: Decimal correctness + CHECK constraint."""

    def setUp(self):
        self.user = _make_user("billing@example.com")
        self.org = _make_org(self.user)
        _set_plan(self.org, "free")

    def test_monthly_price_is_exactly_4500_naira(self):
        self.assertEqual(price_for_interval(ConnectorAddonSubscription.Interval.MONTHLY), Decimal("4500.00"))
        self.assertEqual(CONNECTOR_ADDON_MONTHLY_PRICE, Decimal("4500.00"))

    def test_annual_price_is_flat_12x_monthly(self):
        self.assertEqual(price_for_interval(ConnectorAddonSubscription.Interval.ANNUAL), Decimal("54000.00"))
        self.assertEqual(CONNECTOR_ADDON_ANNUAL_PRICE, Decimal("54000.00"))

    @patch("apps.subscriptions.payment_engine.requests.post")
    def test_initiate_creates_pending_payment_with_exact_decimal_amount(self, mock_post):
        resp = MagicMock(status_code=200)
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "status": True,
            "data": {"authorization_url": "https://checkout.paystack.com/xyz", "access_code": "ac_1"},
        }
        mock_post.return_value = resp

        result = PaymentEngine.initiate(
            self.org, PaymentHistory.Kind.CONNECTOR_ADDON,
            (Connector.SLACK, ConnectorAddonSubscription.Interval.MONTHLY),
            self.user.email,
        )
        payment = PaymentHistory.objects.get(provider_payment_id=result["reference"])
        self.assertEqual(payment.amount, Decimal("4500.00"))
        self.assertEqual(payment.expected_amount, Decimal("4500.00"))
        self.assertEqual(payment.status, PaymentHistory.Status.PENDING)
        self.assertEqual(result["amount_kobo"], 450000)

    def test_initiate_rejects_double_purchase_of_active_addon(self):
        ConnectorAddonSubscription.objects.create(
            organisation=self.org, connector_key=Connector.SLACK,
            status=ConnectorAddonSubscription.Status.ACTIVE,
            interval=ConnectorAddonSubscription.Interval.MONTHLY,
            amount=Decimal("4500.00"),
            current_period_end=timezone.now() + timezone.timedelta(days=5),
        )
        with self.assertRaises(ValueError):
            PaymentEngine.initiate(
                self.org, PaymentHistory.Kind.CONNECTOR_ADDON,
                (Connector.SLACK, ConnectorAddonSubscription.Interval.MONTHLY),
                self.user.email,
            )

    @patch("apps.subscriptions.payment_engine.requests.get")
    def test_activate_sets_active_status_and_30_day_period_for_monthly(self, mock_get):
        addon = ConnectorAddonSubscription.objects.create(
            organisation=self.org, connector_key=Connector.SLACK,
            status=ConnectorAddonSubscription.Status.INCOMPLETE,
            interval=ConnectorAddonSubscription.Interval.MONTHLY,
            amount=Decimal("4500.00"),
        )
        payment = PaymentHistory.objects.create(
            kind=PaymentHistory.Kind.CONNECTOR_ADDON,
            organisation=self.org,
            connector_addon_subscription=addon,
            expected_amount=Decimal("4500.00"),
            amount=Decimal("4500.00"),
            status=PaymentHistory.Status.PENDING,
            provider_payment_id="ADDON-TEST1",
        )
        resp = MagicMock(status_code=200)
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "status": True,
            "data": {
                "status": "success", "reference": "ADDON-TEST1", "amount": 450000,
                "metadata": {"org_id": str(self.org.id), "payment_kind": "connector_addon"},
            },
        }
        mock_get.return_value = resp

        PaymentEngine.activate("ADDON-TEST1")
        addon.refresh_from_db()
        payment.refresh_from_db()

        self.assertEqual(payment.status, PaymentHistory.Status.SUCCEEDED)
        self.assertEqual(addon.status, ConnectorAddonSubscription.Status.ACTIVE)
        self.assertIsNotNone(addon.current_period_end)
        delta_days = (addon.current_period_end - addon.current_period_start).days
        self.assertEqual(delta_days, 30)

    @patch("apps.subscriptions.payment_engine.requests.get")
    def test_activate_sets_365_day_period_for_annual(self, mock_get):
        addon = ConnectorAddonSubscription.objects.create(
            organisation=self.org, connector_key=Connector.GOOGLE_SHEETS,
            status=ConnectorAddonSubscription.Status.INCOMPLETE,
            interval=ConnectorAddonSubscription.Interval.ANNUAL,
            amount=Decimal("54000.00"),
        )
        payment = PaymentHistory.objects.create(
            kind=PaymentHistory.Kind.CONNECTOR_ADDON,
            organisation=self.org,
            connector_addon_subscription=addon,
            expected_amount=Decimal("54000.00"),
            amount=Decimal("54000.00"),
            status=PaymentHistory.Status.PENDING,
            provider_payment_id="ADDON-TEST2",
        )
        resp = MagicMock(status_code=200)
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "status": True,
            "data": {
                "status": "success", "reference": "ADDON-TEST2", "amount": 5400000,
                "metadata": {"org_id": str(self.org.id)},
            },
        }
        mock_get.return_value = resp

        PaymentEngine.activate("ADDON-TEST2")
        addon.refresh_from_db()
        delta_days = (addon.current_period_end - addon.current_period_start).days
        self.assertEqual(delta_days, 365)

    def test_check_constraint_rejects_connector_addon_row_with_wrong_target(self):
        """A settled connector_addon PaymentHistory row MUST point at a
        connector_addon_subscription and nothing else — same exactly-one-
        target discipline as subscription/integration rows."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaymentHistory.objects.create(
                    kind=PaymentHistory.Kind.CONNECTOR_ADDON,
                    organisation=self.org,
                    connector_addon_subscription=None,  # missing target
                    amount=Decimal("4500.00"),
                    status=PaymentHistory.Status.SUCCEEDED,
                    provider_payment_id="ADDON-BAD1",
                )


class TenantIsolationAPITests(TestCase):
    """
    Org A must never be able to read, connect, restore, disconnect, or
    configure org B's connectors through the API — the #1 risk in this
    codebase, tested explicitly for every new endpoint per policy.
    """

    def setUp(self):
        self.user_a = _make_user("orga@example.com")
        self.org_a = _make_org(self.user_a, "Org A")
        _add_member(self.org_a, self.user_a)
        _set_plan(self.org_a, "business")

        self.user_b = _make_user("orgb@example.com")
        self.org_b = _make_org(self.user_b, "Org B")
        _add_member(self.org_b, self.user_b)
        _set_plan(self.org_b, "business")

        self.conn_b = ConnectorConnection.objects.create(
            organisation=self.org_b, connector_key=Connector.SLACK,
            status=ConnectorConnection.Status.ACTIVE,
            external_account_label="Org B Workspace",
            nango_connection_id="conn_b_1",
        )

        self.client_a = _auth_client(self.user_a, self.org_a)

    def test_gallery_does_not_leak_other_orgs_connection(self):
        resp = self.client_a.get("/api/v1/connectors/")
        self.assertEqual(resp.status_code, 200)
        slack_entry = next(c for c in resp.data["connectors"] if c["connector_key"] == "slack")
        self.assertIsNone(slack_entry["connection"])  # org A has no connection of its own
        self.assertEqual(resp.data["quota"]["used"], 0)

    def test_cannot_disconnect_other_orgs_connection(self):
        resp = self.client_a.post("/api/v1/connectors/slack/disconnect/")
        # 404 — org A has no row for 'slack' (org B's row is invisible to it)
        self.assertEqual(resp.status_code, 404)
        self.conn_b.refresh_from_db()
        self.assertEqual(self.conn_b.status, ConnectorConnection.Status.ACTIVE)  # untouched

    def test_cannot_restore_other_orgs_connection(self):
        resp = self.client_a.post("/api/v1/connectors/slack/restore/")
        self.assertEqual(resp.status_code, 404)

    def test_cannot_configure_other_orgs_connection(self):
        resp = self.client_a.patch("/api/v1/connectors/slack/config/", {"channel_id": "C_HACK"}, format="json")
        self.assertIn(resp.status_code, (400, 404))
        self.conn_b.refresh_from_db()
        self.assertEqual(self.conn_b.config, {})  # untouched by org A's attempt

    def test_addon_verify_payment_rejects_cross_org_reference(self):
        addon_b = ConnectorAddonSubscription.objects.create(
            organisation=self.org_b, connector_key=Connector.GOOGLE_SHEETS,
            status=ConnectorAddonSubscription.Status.INCOMPLETE,
            interval=ConnectorAddonSubscription.Interval.MONTHLY,
            amount=Decimal("4500.00"),
        )
        PaymentHistory.objects.create(
            kind=PaymentHistory.Kind.CONNECTOR_ADDON,
            organisation=self.org_b,
            connector_addon_subscription=addon_b,
            expected_amount=Decimal("4500.00"),
            amount=Decimal("4500.00"),
            status=PaymentHistory.Status.PENDING,
            provider_payment_id="ADDON-CROSSORG",
        )
        with patch("apps.subscriptions.payment_engine.requests.get") as mock_get:
            resp = MagicMock(status_code=200)
            resp.raise_for_status.return_value = None
            resp.json.return_value = {
                "status": True,
                "data": {
                    "status": "success", "reference": "ADDON-CROSSORG", "amount": 450000,
                    "metadata": {"org_id": str(self.org_b.id)},
                },
            }
            mock_get.return_value = resp
            resp2 = self.client_a.post(
                "/api/v1/connectors/addon/verify-payment/", {"reference": "ADDON-CROSSORG"}, format="json",
            )
        # Org A must not be able to settle/observe org B's payment via this endpoint.
        self.assertEqual(resp2.status_code, 404)

    def test_queryset_isolation_at_orm_level(self):
        """Belt-and-suspenders: even a raw queryset scoped by organisation
        (as every view in this app does) never returns another org's row."""
        qs = ConnectorConnection.objects.filter(organisation=self.org_a)
        self.assertEqual(qs.count(), 0)
        self.assertNotIn(self.conn_b, list(qs))
