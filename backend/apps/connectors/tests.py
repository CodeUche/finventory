"""
Tests for Connectors (Slack / Google Sheets / Google Drive / Google Calendar
via Nango, Telegram via its own shared-bot linking flow).

Covers:
    - Tenant isolation: org A cannot read, connect, restore, disconnect, or
      configure org B's ConnectorConnection through the API — including the
      3 new connectors and their new endpoints (Drive folders, Telegram
      webhook cannot be used to hijack another org's linking code).
    - Quota math: Plan.features['max_connectors'] read correctly per tier;
      has_quota_slot / quota_summary arithmetic — same shared pool across
      all 5 connector types.
    - Connection lifecycle: quota-gated start_connect_session (plan_quota vs
      paid_addon vs QuotaExceededError), AlreadyConnectedError, webhook
      activation (success + non-terminal failure that must NOT poison
      status), check_and_restore's "never mark failed on first check" rule,
      disconnect.
    - Nango-not-configured fails loudly (NangoNotConfiguredError -> 503),
      never silently no-ops.
    - Webhook signature verification (valid accepted, invalid/missing
      rejected) — Nango's HMAC and Telegram's optional secret token.
    - ₦4,500/month recurring add-on billing: Decimal correctness, PaymentHistory
      CHECK constraint (exactly one target), period length (30 vs 365 days).
    - Telegram's /start linking handshake: code -> chat_id activation,
      expired code, unrecognised code, no-OAuth-via-Nango discipline.
    - Google Calendar deliverer: due-date event creation, no-due-date no-op,
      tax_obligation.upcoming routing.
    - Google Drive: two-step upload (metadata + content), folder-required
      gating, maybe_save_pdf_to_drive's fire-and-forget dispatch contract.
"""

import base64
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
from apps.integrations.models import DomainEvent
from apps.subscriptions.models import PaymentHistory, Plan
from apps.subscriptions.payment_engine import PaymentEngine
from apps.tenancy.models import Membership
from apps.tenancy.services import OrganisationService

from . import nango, telegram
from .drive import GoogleDriveService
from .models import Connector, ConnectorAddonSubscription, ConnectorConnection, ConnectorEventDelivery
from .pricing import CONNECTOR_ADDON_ANNUAL_PRICE, CONNECTOR_ADDON_MONTHLY_PRICE, price_for_interval
from .services import (
    AlreadyConnectedError,
    ConnectorConnectionService,
    ConnectorQuotaService,
    QuotaExceededError,
    TelegramLinkService,
    _deliver_to_calendar,
    _deliver_to_telegram,
    maybe_save_pdf_to_drive,
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


class TelegramLinkServiceTests(TestCase):
    """The /start handshake — code -> chat_id activation. No Nango/OAuth
    involved at all (see apps.connectors.telegram's module docstring)."""

    def setUp(self):
        self.user = _make_user("tg@example.com")
        self.org = _make_org(self.user)
        _set_plan(self.org, "professional")

    @override_settings(TELEGRAM_BOT_TOKEN="test_token", TELEGRAM_BOT_USERNAME="AudityNotifyBot")
    def test_start_connect_session_for_telegram_never_calls_nango(self):
        """Proves the Telegram branch is a genuinely separate code path —
        NANGO_SECRET_KEY is deliberately left unset here, so if this
        accidentally fell through to the Nango call it would raise
        NangoNotConfiguredError instead of succeeding."""
        result = ConnectorConnectionService.start_connect_session(self.org, Connector.TELEGRAM, self.user)
        self.assertTrue(result["connect_link"].startswith("https://t.me/AudityNotifyBot?start="))
        conn = ConnectorConnection.objects.get(organisation=self.org, connector_key=Connector.TELEGRAM)
        self.assertEqual(conn.status, ConnectorConnection.Status.PENDING)
        self.assertTrue(conn.pending_session_token)  # the linking code

    @override_settings(TELEGRAM_BOT_TOKEN="")
    def test_start_connect_session_for_telegram_fails_loudly_without_token(self):
        with self.assertRaises(telegram.TelegramNotConfiguredError):
            ConnectorConnectionService.start_connect_session(self.org, Connector.TELEGRAM, self.user)

    @override_settings(TELEGRAM_BOT_TOKEN="")
    def test_connect_api_returns_503_not_500_when_telegram_unconfigured(self):
        """API-level: TelegramNotConfiguredError must surface as a clean 503
        (ConnectorConnectView), same as NangoNotConfiguredError does for the
        other 4 connectors — not an unhandled 500."""
        _add_member(self.org, self.user)
        client = _auth_client(self.user, self.org)
        resp = client.post("/api/v1/connectors/telegram/connect/")
        self.assertEqual(resp.status_code, 503)

    @override_settings(TELEGRAM_BOT_TOKEN="test_token")
    @patch("apps.connectors.telegram.send_message")
    def test_handle_start_activates_connection_with_chat_id(self, mock_send):
        mock_send.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
        conn = ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.TELEGRAM,
            status=ConnectorConnection.Status.PENDING, pending_session_token="code_abc123",
        )
        ok = TelegramLinkService.handle_start(code="code_abc123", chat_id=987654321, label="jane_doe")
        self.assertTrue(ok)
        conn.refresh_from_db()
        self.assertEqual(conn.status, ConnectorConnection.Status.ACTIVE)
        self.assertEqual(conn.config.get("chat_id"), 987654321)
        self.assertEqual(conn.external_account_label, "jane_doe")
        self.assertEqual(conn.pending_session_token, "")
        self.assertIsNotNone(conn.connected_at)
        mock_send.assert_called_once()  # confirmation message sent back

    @override_settings(TELEGRAM_BOT_TOKEN="test_token")
    @patch("apps.connectors.telegram.send_message")
    def test_handle_start_rejects_unrecognised_code(self, mock_send):
        mock_send.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
        ok = TelegramLinkService.handle_start(code="not_a_real_code", chat_id=1, label="")
        self.assertFalse(ok)

    @override_settings(TELEGRAM_BOT_TOKEN="test_token")
    @patch("apps.connectors.telegram.send_message")
    def test_handle_start_rejects_expired_code(self, mock_send):
        mock_send.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
        conn = ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.TELEGRAM,
            status=ConnectorConnection.Status.PENDING, pending_session_token="stale_code",
        )
        # Simulate the code having been minted over 30 minutes ago.
        ConnectorConnection.objects.filter(pk=conn.pk).update(
            updated_at=timezone.now() - timezone.timedelta(minutes=31)
        )
        ok = TelegramLinkService.handle_start(code="stale_code", chat_id=1, label="")
        self.assertFalse(ok)
        conn.refresh_from_db()
        self.assertEqual(conn.status, ConnectorConnection.Status.PENDING)  # never activated

    @override_settings(TELEGRAM_BOT_TOKEN="test_token")
    @patch("apps.connectors.telegram.send_message")
    def test_handle_start_ignores_org_bs_pending_code_when_looking_up_org_a(self, mock_send):
        """Tenant isolation on the webhook path itself: a code always belongs
        to exactly one org (enforced by the unique random token, not by any
        caller-supplied org id), so this is really testing that the lookup
        is code-keyed and cannot be confused across orgs."""
        mock_send.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
        other_user = _make_user("tgorgb@example.com")
        other_org = _make_org(other_user, "Org B Telegram")
        ConnectorConnection.objects.create(
            organisation=other_org, connector_key=Connector.TELEGRAM,
            status=ConnectorConnection.Status.PENDING, pending_session_token="org_b_code",
        )
        ok = TelegramLinkService.handle_start(code="org_a_guess", chat_id=1, label="")
        self.assertFalse(ok)
        # Org B's own code, used correctly, activates only Org B's row.
        ok2 = TelegramLinkService.handle_start(code="org_b_code", chat_id=222, label="")
        self.assertTrue(ok2)
        conn_b = ConnectorConnection.objects.get(organisation=other_org, connector_key=Connector.TELEGRAM)
        self.assertEqual(conn_b.status, ConnectorConnection.Status.ACTIVE)
        self.assertEqual(conn_b.config.get("chat_id"), 222)


class TelegramWebhookVerificationTests(TestCase):
    def test_no_secret_configured_allows_through(self):
        with override_settings(TELEGRAM_WEBHOOK_SECRET=""):
            self.assertTrue(telegram.verify_webhook_secret("anything"))
            self.assertTrue(telegram.verify_webhook_secret(""))

    def test_secret_configured_requires_exact_match(self):
        with override_settings(TELEGRAM_WEBHOOK_SECRET="whsec_tg_123"):
            self.assertTrue(telegram.verify_webhook_secret("whsec_tg_123"))
            self.assertFalse(telegram.verify_webhook_secret("wrong"))
            self.assertFalse(telegram.verify_webhook_secret(""))


class TelegramWebhookAPITests(TestCase):
    """POST /connectors/webhook/telegram/ — no auth, Telegram is the caller."""

    def setUp(self):
        self.user = _make_user("tgwh@example.com")
        self.org = _make_org(self.user)
        _set_plan(self.org, "professional")
        self.client = APIClient()

    @override_settings(TELEGRAM_BOT_TOKEN="test_token", TELEGRAM_WEBHOOK_SECRET="")
    @patch("apps.connectors.telegram.send_message")
    def test_start_message_activates_connection(self, mock_send):
        mock_send.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
        conn = ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.TELEGRAM,
            status=ConnectorConnection.Status.PENDING, pending_session_token="webhook_code_1",
        )
        payload = {
            "update_id": 1,
            "message": {
                "chat": {"id": 555, "username": "someuser", "type": "private"},
                "text": "/start webhook_code_1",
            },
        }
        resp = self.client.post("/api/v1/connectors/webhook/telegram/", payload, format="json")
        self.assertEqual(resp.status_code, 200)
        conn.refresh_from_db()
        self.assertEqual(conn.status, ConnectorConnection.Status.ACTIVE)
        self.assertEqual(conn.config.get("chat_id"), 555)

    @override_settings(TELEGRAM_WEBHOOK_SECRET="real_secret")
    def test_wrong_secret_token_rejected(self):
        resp = self.client.post(
            "/api/v1/connectors/webhook/telegram/", {"message": {}}, format="json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="wrong_secret",
        )
        self.assertEqual(resp.status_code, 401)

    def test_non_start_message_is_ignored_without_error(self):
        resp = self.client.post(
            "/api/v1/connectors/webhook/telegram/",
            {"message": {"chat": {"id": 1}, "text": "hello there"}}, format="json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_malformed_payload_still_answers_200(self):
        resp = self.client.post("/api/v1/connectors/webhook/telegram/", {"unexpected": "shape"}, format="json")
        self.assertEqual(resp.status_code, 200)


class TelegramDelivererTests(TestCase):
    def setUp(self):
        self.user = _make_user("tgdeliver@example.com")
        self.org = _make_org(self.user)
        self.conn = ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.TELEGRAM,
            status=ConnectorConnection.Status.ACTIVE, config={"chat_id": 42},
        )

    @patch("apps.connectors.telegram.send_message")
    def test_delivers_invoice_created_message(self, mock_send):
        mock_send.return_value = MagicMock(status_code=200, json=lambda: {"ok": True})
        event = DomainEvent.objects.create(
            organisation=self.org, event_type="invoice.created",
            payload={"invoice_number": "INV-001", "total_amount": "5000.00"},
        )
        ok, status_code, error = _deliver_to_telegram(self.conn, event)
        self.assertTrue(ok)
        self.assertEqual(status_code, 200)
        sent_text = mock_send.call_args.kwargs["text"]
        self.assertIn("INV-001", sent_text)
        self.assertIn("5000.00", sent_text)

    def test_no_chat_id_fails_without_calling_telegram(self):
        other_user = _make_user("tgdeliver2@example.com")
        other_org = _make_org(other_user, "Telegram Deliverer Org B")
        conn = ConnectorConnection.objects.create(
            organisation=other_org, connector_key=Connector.TELEGRAM,
            status=ConnectorConnection.Status.ACTIVE, config={},
        )
        event = DomainEvent.objects.create(organisation=other_org, event_type="invoice.created", payload={})
        ok, status_code, error = _deliver_to_telegram(conn, event)
        self.assertFalse(ok)
        self.assertIn("chat", error.lower())


class GoogleCalendarDelivererTests(TestCase):
    def setUp(self):
        self.user = _make_user("cal@example.com")
        self.org = _make_org(self.user)
        self.conn = ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.GOOGLE_CALENDAR,
            status=ConnectorConnection.Status.ACTIVE, nango_connection_id="conn_cal_1",
        )

    @override_settings(NANGO_SECRET_KEY="test_secret")
    @patch("apps.connectors.nango.requests.request")
    def test_invoice_due_date_creates_all_day_event(self, mock_request):
        mock_request.return_value = MagicMock(status_code=200, text="{}", json=lambda: {"id": "evt_1"})
        event = DomainEvent.objects.create(
            organisation=self.org, event_type="invoice.created",
            payload={"invoice_number": "INV-002", "total_amount": "1000.00", "due_date": "2026-09-01"},
        )
        ok, status_code, error = _deliver_to_calendar(self.conn, event)
        self.assertTrue(ok)
        call_kwargs = mock_request.call_args.kwargs
        self.assertIn("calendars/primary/events", mock_request.call_args.args[1])
        body = call_kwargs["json"]
        self.assertEqual(body["start"]["date"], "2026-09-01")
        self.assertEqual(body["end"]["date"], "2026-09-02")  # end = start + 1 day, all-day convention

    def test_invoice_without_due_date_is_a_noop_not_a_failure(self):
        event = DomainEvent.objects.create(
            organisation=self.org, event_type="invoice.created",
            payload={"invoice_number": "INV-003", "total_amount": "1000.00", "due_date": None},
        )
        ok, status_code, error = _deliver_to_calendar(self.conn, event)
        self.assertTrue(ok)
        self.assertIsNone(status_code)  # no API call was made at all

    @override_settings(NANGO_SECRET_KEY="test_secret")
    @patch("apps.connectors.nango.requests.request")
    def test_tax_obligation_upcoming_creates_deadline_event(self, mock_request):
        mock_request.return_value = MagicMock(status_code=200, text="{}", json=lambda: {"id": "evt_2"})
        event = DomainEvent.objects.create(
            organisation=self.org, event_type="tax_obligation.upcoming",
            payload={"label": "VAT Return — July 2026", "due_date": "2026-08-21", "amount_due": "0"},
        )
        ok, status_code, error = _deliver_to_calendar(self.conn, event)
        self.assertTrue(ok)
        body = mock_request.call_args.kwargs["json"]
        self.assertIn("VAT Return", body["summary"])

    def test_uses_configured_calendar_id_not_always_primary(self):
        self.conn.config = {"calendar_id": "team@group.calendar.google.com"}
        self.conn.save(update_fields=["config"])
        with override_settings(NANGO_SECRET_KEY="test_secret"), \
             patch("apps.connectors.nango.requests.request") as mock_request:
            mock_request.return_value = MagicMock(status_code=200, text="{}", json=lambda: {"id": "evt_3"})
            event = DomainEvent.objects.create(
                organisation=self.org, event_type="invoice.created",
                payload={"invoice_number": "INV-004", "total_amount": "1", "due_date": "2026-09-10"},
            )
            _deliver_to_calendar(self.conn, event)
            self.assertIn("calendars/team%40group.calendar.google.com/events", mock_request.call_args.args[1])


class ConnectorEventTypeRoutingTests(TestCase):
    """apps.connectors.tasks.CONNECTOR_EVENT_TYPES — Calendar must not
    receive payment.received (no due-date concept), Drive must not appear
    at all (it's not a DomainEvent-replay target)."""

    def test_calendar_does_not_subscribe_to_payment_received(self):
        from .tasks import CONNECTOR_EVENT_TYPES
        self.assertNotIn("payment.received", CONNECTOR_EVENT_TYPES[Connector.GOOGLE_CALENDAR])
        self.assertIn("tax_obligation.upcoming", CONNECTOR_EVENT_TYPES[Connector.GOOGLE_CALENDAR])

    def test_drive_has_no_entry_in_event_routing(self):
        from .tasks import CONNECTOR_EVENT_TYPES
        self.assertNotIn(Connector.GOOGLE_DRIVE, CONNECTOR_EVENT_TYPES)

    def test_telegram_subscribes_to_same_events_as_slack(self):
        from .tasks import CONNECTOR_EVENT_TYPES
        self.assertEqual(
            set(CONNECTOR_EVENT_TYPES[Connector.TELEGRAM]), set(CONNECTOR_EVENT_TYPES[Connector.SLACK]),
        )


class GoogleDriveServiceTests(TestCase):
    def setUp(self):
        self.user = _make_user("drive@example.com")
        self.org = _make_org(self.user)
        self.conn = ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.GOOGLE_DRIVE,
            status=ConnectorConnection.Status.ACTIVE, nango_connection_id="conn_drive_1",
            config={"folder_id": "folder_abc"},
        )

    def test_no_folder_configured_fails_without_any_api_call(self):
        other_user = _make_user("drive2@example.com")
        other_org = _make_org(other_user, "Drive Service Org B")
        conn = ConnectorConnection.objects.create(
            organisation=other_org, connector_key=Connector.GOOGLE_DRIVE,
            status=ConnectorConnection.Status.PENDING, config={},
        )
        ok, error = GoogleDriveService.upload_pdf(conn, "test.pdf", b"%PDF-1.4 fake")
        self.assertFalse(ok)
        self.assertIn("folder", error.lower())

    @override_settings(NANGO_SECRET_KEY="test_secret")
    @patch("apps.connectors.nango.requests.request")
    def test_upload_pdf_two_step_metadata_then_content(self, mock_request):
        mock_request.side_effect = [
            MagicMock(status_code=200, text="{}", json=lambda: {"id": "file_123"}),  # metadata create
            MagicMock(status_code=200, text="{}"),  # content upload
        ]
        ok, error = GoogleDriveService.upload_pdf(self.conn, "Invoice-001.pdf", b"%PDF-1.4 fake bytes")
        self.assertTrue(ok)
        self.assertEqual(mock_request.call_count, 2)
        first_call, second_call = mock_request.call_args_list
        self.assertEqual(first_call.kwargs["json"]["parents"], ["folder_abc"])
        self.assertEqual(second_call.kwargs["data"], b"%PDF-1.4 fake bytes")
        self.assertEqual(second_call.kwargs["headers"]["Content-Type"], "application/pdf")

    @override_settings(NANGO_SECRET_KEY="test_secret")
    @patch("apps.connectors.nango.requests.request")
    def test_metadata_step_failure_never_attempts_content_upload(self, mock_request):
        mock_request.return_value = MagicMock(status_code=403, text="forbidden")
        ok, error = GoogleDriveService.upload_pdf(self.conn, "test.pdf", b"bytes")
        self.assertFalse(ok)
        self.assertEqual(mock_request.call_count, 1)


class MaybeSavePdfToDriveTests(TestCase):
    """The fire-and-forget hook called from payroll/reports/sales PDF
    generation call sites — must never raise, must no-op when Drive isn't
    connected/configured, must dispatch a Celery task when it is."""

    def setUp(self):
        self.user = _make_user("hook@example.com")
        self.org = _make_org(self.user)

    def test_noop_when_no_drive_connection(self):
        # No exception, no dispatch — nothing to assert on except "didn't raise".
        maybe_save_pdf_to_drive(self.org, "file.pdf", b"bytes")

    def test_noop_when_connected_but_no_folder_configured(self):
        ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.GOOGLE_DRIVE,
            status=ConnectorConnection.Status.ACTIVE, config={},
        )
        with patch("apps.connectors.tasks.upload_pdf_to_drive.delay") as mock_delay:
            maybe_save_pdf_to_drive(self.org, "file.pdf", b"bytes")
            mock_delay.assert_not_called()

    def test_dispatches_task_when_connected_and_configured(self):
        ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.GOOGLE_DRIVE,
            status=ConnectorConnection.Status.ACTIVE, config={"folder_id": "f1"},
        )
        with patch("apps.connectors.tasks.upload_pdf_to_drive.delay") as mock_delay:
            maybe_save_pdf_to_drive(self.org, "Payslip-E001-2026-08.pdf", b"raw pdf bytes")
            mock_delay.assert_called_once()
            args = mock_delay.call_args.args
            self.assertEqual(args[0], str(self.org.id))
            self.assertEqual(args[1], "Payslip-E001-2026-08.pdf")
            self.assertEqual(base64.b64decode(args[2]), b"raw pdf bytes")

    def test_never_raises_even_if_dispatch_itself_errors(self):
        with patch("apps.connectors.tasks.upload_pdf_to_drive.delay", side_effect=Exception("broker down")):
            ConnectorConnection.objects.create(
                organisation=self.org, connector_key=Connector.GOOGLE_DRIVE,
                status=ConnectorConnection.Status.ACTIVE, config={"folder_id": "f1"},
            )
            maybe_save_pdf_to_drive(self.org, "file.pdf", b"bytes")  # must not raise


class NewConnectorsGalleryAndConfigAPITests(TestCase):
    """API-level smoke coverage for the 3 new connectors sharing the exact
    same gallery/config endpoints as Slack/Sheets."""

    def setUp(self):
        self.user = _make_user("gallery@example.com")
        self.org = _make_org(self.user)
        _add_member(self.org, self.user)
        _set_plan(self.org, "enterprise")  # quota=5, room for all 5 connectors
        self.client = _auth_client(self.user, self.org)

    def test_gallery_lists_all_five_connectors(self):
        resp = self.client.get("/api/v1/connectors/")
        self.assertEqual(resp.status_code, 200)
        keys = {c["connector_key"] for c in resp.data["connectors"]}
        self.assertEqual(keys, {"slack", "google_sheets", "google_drive", "google_calendar", "telegram"})

    def test_quota_pool_is_shared_across_connector_types(self):
        """Connecting one of each of 3 different connector types consumes 3
        of the shared quota slots — nothing connector-specific about
        counting (confirms the frontend's 'same plan-quota pool' premise)."""
        for key in (Connector.SLACK, Connector.GOOGLE_DRIVE, Connector.TELEGRAM):
            ConnectorConnection.objects.create(
                organisation=self.org, connector_key=key,
                status=ConnectorConnection.Status.ACTIVE,
                billing_mode=ConnectorConnection.BillingMode.PLAN_QUOTA,
            )
        self.assertEqual(ConnectorQuotaService.active_plan_quota_count(self.org), 3)
        resp = self.client.get("/api/v1/connectors/")
        self.assertEqual(resp.data["quota"]["used"], 3)

    def test_config_endpoint_accepts_drive_folder_id(self):
        ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.GOOGLE_DRIVE,
            status=ConnectorConnection.Status.ACTIVE,
        )
        resp = self.client.patch(
            "/api/v1/connectors/google_drive/config/", {"folder_id": "f_xyz"}, format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["config"]["folder_id"], "f_xyz")

    def test_config_endpoint_accepts_calendar_id(self):
        ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.GOOGLE_CALENDAR,
            status=ConnectorConnection.Status.ACTIVE,
        )
        resp = self.client.patch(
            "/api/v1/connectors/google_calendar/config/", {"calendar_id": "team@x.com"}, format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["config"]["calendar_id"], "team@x.com")

    def test_telegram_has_no_configurable_keys(self):
        """Telegram's only 'config' (chat_id) is set exclusively by the
        webhook handshake — the config endpoint must reject any attempt to
        set it directly through the authenticated API."""
        ConnectorConnection.objects.create(
            organisation=self.org, connector_key=Connector.TELEGRAM,
            status=ConnectorConnection.Status.ACTIVE,
        )
        resp = self.client.patch(
            "/api/v1/connectors/telegram/config/", {"chat_id": "999"}, format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_drive_folders_endpoint_returns_empty_list_when_not_connected(self):
        resp = self.client.get("/api/v1/connectors/google-drive/folders/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["folders"], [])


class NewConnectorsTenantIsolationTests(TestCase):
    """Same discipline as TenantIsolationAPITests above, applied to the 3
    new connectors and their new endpoints."""

    def setUp(self):
        self.user_a = _make_user("newconn_a@example.com")
        self.org_a = _make_org(self.user_a, "New Conn Org A")
        _add_member(self.org_a, self.user_a)
        _set_plan(self.org_a, "business")

        self.user_b = _make_user("newconn_b@example.com")
        self.org_b = _make_org(self.user_b, "New Conn Org B")
        _add_member(self.org_b, self.user_b)
        _set_plan(self.org_b, "business")

        self.conn_b_drive = ConnectorConnection.objects.create(
            organisation=self.org_b, connector_key=Connector.GOOGLE_DRIVE,
            status=ConnectorConnection.Status.ACTIVE, config={"folder_id": "org_b_folder"},
        )
        self.conn_b_telegram = ConnectorConnection.objects.create(
            organisation=self.org_b, connector_key=Connector.TELEGRAM,
            status=ConnectorConnection.Status.ACTIVE, config={"chat_id": 111},
        )
        self.client_a = _auth_client(self.user_a, self.org_a)

    def test_org_a_cannot_read_org_bs_drive_or_telegram_connection(self):
        resp = self.client_a.get("/api/v1/connectors/")
        by_key = {c["connector_key"]: c for c in resp.data["connectors"]}
        self.assertIsNone(by_key["google_drive"]["connection"])
        self.assertIsNone(by_key["telegram"]["connection"])

    def test_org_a_cannot_reconfigure_org_bs_drive_folder(self):
        resp = self.client_a.patch(
            "/api/v1/connectors/google_drive/config/", {"folder_id": "hacked"}, format="json",
        )
        self.assertEqual(resp.status_code, 400)  # org A has no active Drive connection of its own
        self.conn_b_drive.refresh_from_db()
        self.assertEqual(self.conn_b_drive.config["folder_id"], "org_b_folder")  # untouched

    def test_org_a_cannot_disconnect_org_bs_telegram(self):
        resp = self.client_a.post("/api/v1/connectors/telegram/disconnect/")
        self.assertEqual(resp.status_code, 404)
        self.conn_b_telegram.refresh_from_db()
        self.assertEqual(self.conn_b_telegram.status, ConnectorConnection.Status.ACTIVE)

    def test_org_a_google_drive_folders_view_never_sees_org_bs_connection(self):
        """org A has no Drive connection of its own, so the folders endpoint
        must return [] rather than accidentally listing org B's folders."""
        resp = self.client_a.get("/api/v1/connectors/google-drive/folders/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["folders"], [])
