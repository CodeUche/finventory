"""
Service layer for Connectors.

Three responsibilities:
    1. ConnectorQuotaService — is this org allowed to connect another
       connector right now, and under which billing_mode (plan_quota vs.
       paid_addon)?
    2. ConnectorConnectionService — the connection lifecycle: start a Nango
       Connect session, apply the Nango webhook / restore-check when it
       completes, disconnect.
    3. ConnectorDeliveryService — deliver a DomainEvent to an org's active
       Slack/Google Sheets connections via Nango's Proxy API. Kept separate
       from apps.integrations.services.deliver_event_to_subscription (see
       ConnectorEventDelivery's docstring) but reuses DomainEvent as the
       single source of truth for "what happened".
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from . import nango
from .models import Connector, ConnectorAddonSubscription, ConnectorConnection, ConnectorEventDelivery

logger = logging.getLogger(__name__)


class QuotaExceededError(Exception):
    """Raised when an org has no free plan-quota slot and no active paid add-on."""


class AlreadyConnectedError(Exception):
    """Raised when the org already has an ACTIVE connection for this connector."""


def _plan(organisation):
    sub = getattr(organisation, "subscription", None)
    return sub.plan if sub is not None else None


class ConnectorQuotaService:

    @staticmethod
    def max_connectors(organisation) -> int:
        plan = _plan(organisation)
        if plan is None:
            return 0
        try:
            return int(plan.features.get("max_connectors", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def active_plan_quota_count(organisation) -> int:
        return ConnectorConnection.objects.filter(
            organisation=organisation,
            status=ConnectorConnection.Status.ACTIVE,
            billing_mode=ConnectorConnection.BillingMode.PLAN_QUOTA,
        ).count()

    @staticmethod
    def has_quota_slot(organisation) -> bool:
        return ConnectorQuotaService.active_plan_quota_count(organisation) < ConnectorQuotaService.max_connectors(organisation)

    @staticmethod
    def quota_summary(organisation) -> dict:
        """Powers the "Business plan — 1 of 3 used" indicator on the gallery page."""
        plan = _plan(organisation)
        return {
            "plan_name": plan.name if plan else None,
            "used": ConnectorQuotaService.active_plan_quota_count(organisation),
            "max": ConnectorQuotaService.max_connectors(organisation),
        }


def _extract_label(connector_key: str, data: dict) -> str:
    """
    Best-effort extraction of a human display label ("Connected as {label}")
    from whatever metadata Nango/the provider handed back. Provider metadata
    shapes are not part of Nango's stable contract, so every path here is
    optional and this NEVER raises — worst case the connection is still
    marked active with an empty label and the UI just shows "Connected".
    """
    try:
        metadata = data.get("metadata") or {}
        if connector_key == Connector.SLACK:
            team = metadata.get("team") or {}
            return team.get("name") or metadata.get("team_name") or metadata.get("workspace_name") or ""
        if connector_key == Connector.GOOGLE_SHEETS:
            user = metadata.get("user") or {}
            return user.get("email") or metadata.get("email") or ""
    except Exception:
        pass
    return ""


class ConnectorConnectionService:

    @staticmethod
    def start_connect_session(organisation, connector_key: str, user) -> dict:
        """
        Validates connector_key + quota, mints a Nango Connect session, and
        upserts a PENDING ConnectorConnection row recording which
        billing_mode was granted. Returns { connect_link, expires_at }.

        Raises: ValueError (unknown connector), AlreadyConnectedError,
        QuotaExceededError, nango.NangoNotConfiguredError, nango.NangoAPIError.
        """
        if connector_key not in Connector.values:
            raise ValueError(f"Unknown connector: {connector_key!r}")

        with transaction.atomic():
            existing = ConnectorConnection.objects.select_for_update().filter(
                organisation=organisation, connector_key=connector_key,
            ).first()
            if existing is not None and existing.status == ConnectorConnection.Status.ACTIVE:
                raise AlreadyConnectedError(f"{connector_key} is already connected.")

            if ConnectorQuotaService.has_quota_slot(organisation):
                billing_mode = ConnectorConnection.BillingMode.PLAN_QUOTA
            else:
                addon = ConnectorAddonSubscription.objects.filter(
                    organisation=organisation, connector_key=connector_key,
                ).first()
                if addon is not None and addon.is_active:
                    billing_mode = ConnectorConnection.BillingMode.PAID_ADDON
                else:
                    raise QuotaExceededError(
                        "Your plan's connector quota is used up. Add this connector for "
                        "₦4,500/month to continue, or upgrade your plan."
                    )

            # Nango call happens INSIDE the lock deliberately kept short —
            # this is a single HTTPS round trip (unlike PaymentEngine's
            # verify, which is why that one is done outside its lock): the
            # window a double-click could exploit is the DB upsert below,
            # and holding the row lock across the Nango call is what
            # prevents two near-simultaneous clicks from both passing the
            # quota check above and creating two sessions.
            session = nango.create_connect_session(
                organisation_id=str(organisation.id),
                connector_key=connector_key,
                user_email=user.email,
            )

            ConnectorConnection.objects.update_or_create(
                organisation=organisation,
                connector_key=connector_key,
                defaults={
                    "status": ConnectorConnection.Status.PENDING,
                    "billing_mode": billing_mode,
                    "pending_session_token": session["token"],
                },
            )

        return {"connect_link": session["connect_link"], "expires_at": session.get("expires_at")}

    @staticmethod
    @transaction.atomic
    def apply_webhook(payload: dict) -> None:
        """
        Applies a Nango `type=auth` webhook: flips the matching
        ConnectorConnection to ACTIVE (on success) and records
        nango_connection_id + external_account_label. Never raises — the
        webhook view always answers 200 (same "don't retry-storm us on a
        payload shape we didn't anticipate" discipline as the Paystack
        webhook handler).
        """
        if payload.get("type") != "auth":
            return  # not a connection-lifecycle event — nothing to do here

        connection_id = payload.get("connectionId")
        provider_config_key = payload.get("providerConfigKey")
        tags = payload.get("tags") or payload.get("endUser") or {}
        org_id = tags.get("organization_id") or tags.get("organizationId")

        if not connection_id or not provider_config_key or not org_id:
            logger.error("Nango auth webhook missing required fields: %s", payload)
            return

        connector_key = None
        for key in Connector.values:
            try:
                if nango.integration_id_for(key) == provider_config_key:
                    connector_key = key
                    break
            except ValueError:
                continue
        if connector_key is None:
            logger.warning("Nango auth webhook: unrecognised providerConfigKey %r", provider_config_key)
            return

        try:
            conn = ConnectorConnection.objects.select_for_update().get(
                organisation_id=org_id, connector_key=connector_key,
            )
        except ConnectorConnection.DoesNotExist:
            logger.warning(
                "Nango auth webhook: no ConnectorConnection for org=%s connector=%s "
                "(connection_id=%s) — ignoring.", org_id, connector_key, connection_id,
            )
            return

        if not payload.get("success", False):
            # A genuine terminal failure from Nango (e.g. the user closed the
            # consent screen, or the provider rejected the grant) — unlike
            # PaymentEngine.activate's transient "not yet paid" polls, this
            # IS an explicit signal from the provider, so it's safe to log
            # loudly. It deliberately does NOT flip status away from PENDING
            # though: the user can simply click "Connect" again, and leaving
            # it PENDING (rather than a new REVOKED-like terminal state)
            # keeps the UI's "Connecting…" affordance meaningful rather than
            # introducing a fourth status value for one edge case.
            error = payload.get("error") or {}
            logger.warning(
                "Nango auth webhook reported failure for org=%s connector=%s: %s",
                org_id, connector_key, error,
            )
            return

        conn.status = ConnectorConnection.Status.ACTIVE
        conn.nango_connection_id = connection_id
        label = _extract_label(connector_key, payload)
        if label:
            conn.external_account_label = label
        conn.connected_at = timezone.now()
        conn.pending_session_token = ""
        conn.save(update_fields=[
            "status", "nango_connection_id", "external_account_label",
            "connected_at", "pending_session_token", "updated_at",
        ])
        logger.info("Connector activated via webhook: org=%s connector=%s", org_id, connector_key)

    @staticmethod
    @transaction.atomic
    def check_and_restore(organisation, connector_key: str) -> ConnectorConnection:
        """
        Silently asks Nango whether a connection now exists, for the
        poll / silent-check-on-load / manual-"Restore access" trio — the
        exact same three-layer pattern as
        SubscriptionViewSet.restore_integration_payment, applied to the
        Nango OAuth handoff instead of Paystack checkout, because opening
        the Connect UI in the system browser on desktop has the identical
        "no automatic way back into the app" problem.

        Raises ValueError if there's nothing to restore (never marks
        anything permanently failed on a not-yet-complete check).
        """
        conn = ConnectorConnection.objects.select_for_update().filter(
            organisation=organisation, connector_key=connector_key,
        ).first()
        if conn is None:
            raise ValueError("No connection attempt found for this connector.")
        if conn.status == ConnectorConnection.Status.ACTIVE:
            return conn  # idempotent no-op — duplicate poll tick after webhook already landed
        if conn.status == ConnectorConnection.Status.REVOKED:
            # Explicitly disconnected — a stale Nango-side connection must
            # never silently resurrect it. The user must click Connect again.
            raise ValueError("This connector was disconnected. Click Connect to reconnect.")

        matches = nango.list_connections_for_org(
            organisation_id=str(organisation.id), connector_key=connector_key,
        )
        if not matches:
            raise ValueError("No completed connection found yet.")

        latest = matches[0]
        conn.status = ConnectorConnection.Status.ACTIVE
        conn.nango_connection_id = latest.get("connection_id", "")
        label = _extract_label(connector_key, latest)
        if label:
            conn.external_account_label = label
        conn.connected_at = timezone.now()
        conn.pending_session_token = ""
        conn.save(update_fields=[
            "status", "nango_connection_id", "external_account_label",
            "connected_at", "pending_session_token", "updated_at",
        ])
        return conn

    @staticmethod
    def disconnect(organisation, connector_key: str) -> ConnectorConnection:
        conn = ConnectorConnection.objects.filter(
            organisation=organisation, connector_key=connector_key,
        ).first()
        if conn is None:
            raise ValueError("No connection found for this connector.")

        if conn.nango_connection_id:
            nango.delete_connection(nango_connection_id=conn.nango_connection_id, connector_key=connector_key)

        conn.status = ConnectorConnection.Status.REVOKED
        conn.revoked_at = timezone.now()
        conn.pending_session_token = ""
        conn.save(update_fields=["status", "revoked_at", "pending_session_token", "updated_at"])
        return conn


# ── Event delivery (Slack / Google Sheets via Nango Proxy) ─────────────────

def _slack_message(event) -> str:
    payload = event.payload or {}
    if event.event_type == "invoice.created":
        return (
            f"\U0001F9FE New invoice *{payload.get('invoice_number', '')}* created "
            f"for ₦{payload.get('total_amount', '')}"
        )
    if event.event_type == "payment.received":
        return (
            f"\U0001F4B0 Payment received on invoice *{payload.get('invoice_number', '')}* "
            f"(₦{payload.get('amount', payload.get('total_amount', ''))})"
        )
    return f"Audity event: {event.event_type}"


def _deliver_to_slack(connection: ConnectorConnection, event) -> tuple[bool, int | None, str]:
    channel_id = (connection.config or {}).get("channel_id")
    if not channel_id:
        return False, None, "No Slack channel configured for this connection."
    resp = nango.proxy(
        method="POST",
        path="chat.postMessage",
        nango_connection_id=connection.nango_connection_id,
        connector_key=Connector.SLACK,
        json_body={"channel": channel_id, "text": _slack_message(event)},
    )
    ok = resp.status_code == 200 and (resp.json() or {}).get("ok", False)
    error = "" if ok else (resp.text[:500] if resp.text else f"HTTP {resp.status_code}")
    return ok, resp.status_code, error


def _deliver_to_sheets(connection: ConnectorConnection, event) -> tuple[bool, int | None, str]:
    config = connection.config or {}
    spreadsheet_id = config.get("spreadsheet_id")
    if not spreadsheet_id:
        return False, None, "No Google Sheet configured for this connection."
    sheet_range = config.get("sheet_range") or "Sheet1"
    payload = event.payload or {}
    row = [
        event.occurred_at.isoformat() if event.occurred_at else "",
        event.event_type,
        payload.get("invoice_number", ""),
        str(payload.get("total_amount", payload.get("amount", ""))),
    ]
    resp = nango.proxy(
        method="POST",
        path=f"v4/spreadsheets/{spreadsheet_id}/values/{sheet_range}:append",
        params={"valueInputOption": "USER_ENTERED"},
        nango_connection_id=connection.nango_connection_id,
        connector_key=Connector.GOOGLE_SHEETS,
        json_body={"values": [row]},
    )
    ok = 200 <= resp.status_code < 300
    error = "" if ok else (resp.text[:500] if resp.text else f"HTTP {resp.status_code}")
    return ok, resp.status_code, error


_DELIVERERS = {
    Connector.SLACK: _deliver_to_slack,
    Connector.GOOGLE_SHEETS: _deliver_to_sheets,
}


class ConnectorDeliveryService:

    @staticmethod
    def deliver_event_to_connection(connection: ConnectorConnection, event) -> ConnectorEventDelivery:
        """
        Deliver one DomainEvent to one active connector connection,
        synchronously. Used by both the Celery beat task
        (tasks.deliver_pending_connector_events) and any future
        "send test event" action — the same code path either way, matching
        apps.integrations.services.deliver_event_to_subscription's shape.
        """
        delivery, _ = ConnectorEventDelivery.objects.get_or_create(
            organisation=connection.organisation, connection=connection, event=event,
        )
        if delivery.status == ConnectorEventDelivery.Status.DELIVERED:
            return delivery

        if connection.status != ConnectorConnection.Status.ACTIVE:
            return delivery  # paused, not failed — mirrors org_can_receive_integration_delivery's gating

        deliverer = _DELIVERERS.get(connection.connector_key)
        if deliverer is None:
            delivery.status = ConnectorEventDelivery.Status.FAILED
            delivery.last_error = f"No deliverer for connector {connection.connector_key!r}."
            delivery.save(update_fields=["status", "last_error", "updated_at"])
            return delivery

        delivery.attempt_count += 1
        delivery.last_attempted_at = timezone.now()
        try:
            ok, status_code, error = deliverer(connection, event)
        except nango.NangoNotConfiguredError as exc:
            ok, status_code, error = False, None, str(exc)
        except nango.NangoAPIError as exc:
            ok, status_code, error = False, None, str(exc)
        except Exception as exc:  # never let a delivery attempt crash the caller
            logger.exception("Unexpected error delivering event %s to connection %s", event.id, connection.id)
            ok, status_code, error = False, None, str(exc)[:500]

        delivery.last_response_code = status_code
        if ok:
            delivery.status = ConnectorEventDelivery.Status.DELIVERED
            delivery.last_error = ""
        else:
            delivery.last_error = error[:2000]
            if delivery.attempt_count >= ConnectorEventDelivery.MAX_ATTEMPTS:
                delivery.status = ConnectorEventDelivery.Status.FAILED
            else:
                delivery.status = ConnectorEventDelivery.Status.PENDING

        delivery.save(update_fields=[
            "status", "attempt_count", "last_attempted_at",
            "last_response_code", "last_error", "updated_at",
        ])
        return delivery
