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
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import gmail, nango, telegram
from .drive import GoogleDriveService
from .models import Connector, ConnectorAddonSubscription, ConnectorConnection, ConnectorEventDelivery

logger = logging.getLogger(__name__)

# How long a Telegram /start linking code stays valid, measured from the
# ConnectorConnection row's updated_at (set the moment the code is minted).
# Comparable in spirit to Nango's own 30-min Connect session lifetime.
TELEGRAM_LINK_EXPIRY = timedelta(minutes=30)


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
        if connector_key in (Connector.GOOGLE_SHEETS, Connector.GOOGLE_DRIVE, Connector.GOOGLE_CALENDAR, Connector.GMAIL):
            user = metadata.get("user") or {}
            return user.get("email") or metadata.get("email") or ""
    except Exception:
        pass
    return ""


class ConnectorConnectionService:

    @staticmethod
    def start_connect_session(organisation, connector_key: str, user) -> dict:
        """
        Validates connector_key + quota, mints a connect session, and
        upserts a PENDING ConnectorConnection row recording which
        billing_mode was granted. Returns { connect_link, expires_at } for
        EVERY connector, Telegram included — this is deliberate: Telegram's
        "connect_link" is a t.me/<bot>?start=<code> deep link rather than a
        Nango Connect URL, but the shape is identical, so the frontend (and
        the poll/restore/disconnect trio below) never needs to know which
        kind of connector it's dealing with. See apps.connectors.telegram's
        module docstring for why Telegram has no OAuth grant at all.

        Raises: ValueError (unknown connector), AlreadyConnectedError,
        QuotaExceededError, nango.NangoNotConfiguredError, nango.NangoAPIError,
        telegram.TelegramNotConfiguredError.
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

            if connector_key == Connector.TELEGRAM:
                # No OAuth call to make — just mint our own opaque code. Still
                # confirm the bot token exists first so this fails loudly
                # (TelegramNotConfiguredError) rather than handing the user a
                # dead deep link, mirroring nango.create_connect_session's
                # own "fail before returning a link" discipline.
                telegram.require_configured()  # raises TelegramNotConfiguredError if no token — no network call
                token = secrets.token_urlsafe(24)
                connect_link = f"https://t.me/{telegram.bot_username()}?start={token}"
                expires_at = (timezone.now() + TELEGRAM_LINK_EXPIRY).isoformat()
            else:
                # Nango call happens INSIDE the lock deliberately kept short
                # — this is a single HTTPS round trip (unlike PaymentEngine's
                # verify, which is why that one is done outside its lock):
                # the window a double-click could exploit is the DB upsert
                # below, and holding the row lock across the Nango call is
                # what prevents two near-simultaneous clicks from both
                # passing the quota check above and creating two sessions.
                session = nango.create_connect_session(
                    organisation_id=str(organisation.id),
                    connector_key=connector_key,
                    user_email=user.email,
                )
                token = session["token"]
                connect_link = session["connect_link"]
                expires_at = session.get("expires_at")

            ConnectorConnection.objects.update_or_create(
                organisation=organisation,
                connector_key=connector_key,
                defaults={
                    "status": ConnectorConnection.Status.PENDING,
                    "billing_mode": billing_mode,
                    "pending_session_token": token,
                },
            )

        return {"connect_link": connect_link, "expires_at": expires_at}

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

        For Telegram there is nothing to "ask" — Telegram's webhook (see
        TelegramLinkService.handle_start) is the ONLY thing that can flip a
        Telegram connection to ACTIVE, so this just re-checks our own DB
        state; if still PENDING it raises exactly like the "not completed
        yet" case below, giving the frontend's poll loop identical behaviour
        either way.

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

        if connector_key == Connector.TELEGRAM:
            raise ValueError("Still waiting for /start to be sent in Telegram.")

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


class TelegramLinkService:
    """
    The server side of Telegram's /start deep-link handshake — see
    apps.connectors.telegram's module docstring for the full flow. The only
    entry point is handle_start, called exclusively from
    apps.connectors.views.telegram_webhook (never from an authenticated
    user-facing endpoint — Telegram itself is the caller).
    """

    @staticmethod
    @transaction.atomic
    def handle_start(*, code: str, chat_id, label: str = "") -> bool:
        """
        Looks up the PENDING ConnectorConnection whose pending_session_token
        matches `code`, confirms it hasn't expired, and activates it with
        the given chat_id. Returns True on success. Never raises — webhook
        handlers must always answer Telegram with 200 regardless of outcome
        (same discipline as ConnectorConnectionService.apply_webhook for
        Nango's webhook), so failures are logged and communicated back to
        the user via a Telegram message instead of an exception.
        """
        if not code:
            return False

        conn = ConnectorConnection.objects.select_for_update().filter(
            connector_key=Connector.TELEGRAM,
            status=ConnectorConnection.Status.PENDING,
            pending_session_token=code,
        ).first()

        if conn is None:
            logger.warning("Telegram /start with unrecognised or already-used code from chat %s", chat_id)
            TelegramLinkService._safe_send(
                chat_id, "This link is invalid or has already been used. Go back to Audity and click Connect again."
            )
            return False

        if timezone.now() - conn.updated_at > TELEGRAM_LINK_EXPIRY:
            logger.warning("Telegram /start with expired code for org %s (chat %s)", conn.organisation_id, chat_id)
            TelegramLinkService._safe_send(
                chat_id, "This link has expired. Go back to Audity and click Connect again."
            )
            return False

        conn.status = ConnectorConnection.Status.ACTIVE
        conn.config = {**(conn.config or {}), "chat_id": chat_id}
        if label:
            conn.external_account_label = label
        conn.connected_at = timezone.now()
        conn.pending_session_token = ""
        conn.save(update_fields=[
            "status", "config", "external_account_label", "connected_at",
            "pending_session_token", "updated_at",
        ])
        logger.info("Telegram connector activated for org=%s chat_id=%s", conn.organisation_id, chat_id)

        TelegramLinkService._safe_send(
            chat_id,
            "✅ Connected! This chat is now linked to your Audity account. "
            "You'll get notified here about new invoices and payments.",
        )
        return True

    @staticmethod
    def _safe_send(chat_id, text: str) -> None:
        """Best-effort confirmation/error message back to the user — a
        failure to send this must never break the linking flow itself."""
        try:
            telegram.send_message(chat_id=chat_id, text=text)
        except (telegram.TelegramNotConfiguredError, telegram.TelegramAPIError) as exc:
            logger.warning("TelegramLinkService: could not message chat %s: %s", chat_id, exc)


def maybe_save_pdf_to_drive(organisation, filename: str, pdf_bytes: bytes) -> None:
    """
    Fire-and-forget hook called from wherever Audity generates a PDF
    server-side (payslips, report exports, the invoice PDF received at
    send-email time — see call sites in apps.payroll.pdf/.views/.tasks/
    .ess_views, apps.reports.exporters.export_pdf, apps.sales.views'
    send_email action). If `organisation` has an ACTIVE Google Drive
    connection with a folder configured, dispatches a Celery task to upload
    it there. A complete no-op (not an error) if Drive isn't connected/
    configured — Drive auto-save is an optional convenience, never a
    blocker for the PDF's actual purpose (download/email/etc). Never raises.
    """
    if organisation is None:
        return
    try:
        conn = ConnectorConnection.objects.filter(
            organisation=organisation, connector_key=Connector.GOOGLE_DRIVE,
            status=ConnectorConnection.Status.ACTIVE,
        ).first()
        if conn is None or not (conn.config or {}).get("folder_id"):
            return

        import base64

        from .tasks import upload_pdf_to_drive
        upload_pdf_to_drive.delay(str(organisation.id), filename, base64.b64encode(pdf_bytes).decode("ascii"))
    except Exception:
        # Fire-and-forget must never break the caller's primary flow (e.g. a
        # customer's invoice email must still send if Drive/Celery hiccups).
        logger.exception("maybe_save_pdf_to_drive: failed to dispatch for org %s", getattr(organisation, "id", None))


# ── Event delivery (Slack / Google Sheets / Telegram / Calendar via proxy) ──

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


def _telegram_message(event) -> str:
    """Deliberately the same content/tone as _slack_message, adapted to
    Telegram's plain/legacy-Markdown sendMessage (single-asterisk bold,
    same as Slack's mrkdwn — no block-kit equivalent needed)."""
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


def _deliver_to_telegram(connection: ConnectorConnection, event) -> tuple[bool, int | None, str]:
    """
    Direct call to Telegram's sendMessage — deliberately NOT routed through
    nango.proxy(). Telegram has no OAuth token for Nango to proxy; the
    connection's own stored chat_id (from TelegramLinkService.handle_start)
    plus the one shared TELEGRAM_BOT_TOKEN is everything needed. See
    apps.connectors.telegram's module docstring.
    """
    chat_id = (connection.config or {}).get("chat_id")
    if not chat_id:
        return False, None, "No Telegram chat linked for this connection."
    # TelegramNotConfiguredError / TelegramAPIError propagate to the caller
    # (ConnectorDeliveryService.deliver_event_to_connection), which already
    # catches both — same contract as _deliver_to_slack/_deliver_to_sheets
    # relying on nango.proxy()'s exceptions propagating.
    resp = telegram.send_message(chat_id=chat_id, text=_telegram_message(event))
    ok = resp.status_code == 200 and (resp.json() or {}).get("ok", False)
    error = "" if ok else (resp.text[:500] if resp.text else f"HTTP {resp.status_code}")
    return ok, resp.status_code, error


def _all_day_event_body(summary: str, description: str, due_date_iso: str) -> dict:
    """Google Calendar all-day event body — `end.date` must be the day AFTER
    `start.date` per Calendar API convention for all-day events."""
    from datetime import date, timedelta as _timedelta

    d = date.fromisoformat(due_date_iso)
    return {
        "summary": summary,
        "description": description,
        "start": {"date": d.isoformat()},
        "end": {"date": (d + _timedelta(days=1)).isoformat()},
    }


def _deliver_to_calendar(connection: ConnectorConnection, event) -> tuple[bool, int | None, str]:
    """
    Creates a Google Calendar all-day event for either an invoice due date
    (event_type="invoice.created") or an upcoming tax/compliance deadline
    (event_type="tax_obligation.upcoming" — see apps.tax.tasks' monthly VAT/
    PAYE obligation generation). Both share the same "due_date" payload key
    by convention so this one deliverer handles both without branching on
    where the due_date came from.

    Returns ok=True with no API call at all when the event has no due_date
    (e.g. a proforma invoice) — that is a legitimate "nothing to schedule"
    outcome, not a delivery failure.
    """
    payload = event.payload or {}
    due_date = payload.get("due_date")
    if not due_date:
        return True, None, ""

    # Google's calendarId path segment must be percent-encoded (it's
    # frequently an email address, e.g. "team@group.calendar.google.com") —
    # nango.proxy passes the path through verbatim, so this must happen here.
    from urllib.parse import quote as _urlquote

    calendar_id = _urlquote((connection.config or {}).get("calendar_id") or "primary", safe="")

    if event.event_type == "invoice.created":
        body = _all_day_event_body(
            summary=f"Invoice {payload.get('invoice_number', '')} due — ₦{payload.get('total_amount', '')}",
            description=f"Audity: invoice {payload.get('invoice_number', '')} payment is due.",
            due_date_iso=due_date,
        )
    elif event.event_type == "tax_obligation.upcoming":
        body = _all_day_event_body(
            summary=f"Tax deadline: {payload.get('label', '')}",
            description="Audity compliance calendar: this filing/remittance is due.",
            due_date_iso=due_date,
        )
    else:
        return True, None, ""  # not a due-date-bearing event type this deliverer handles

    resp = nango.proxy(
        method="POST",
        path=f"calendar/v3/calendars/{calendar_id}/events",
        nango_connection_id=connection.nango_connection_id,
        connector_key=Connector.GOOGLE_CALENDAR,
        json_body=body,
    )
    ok = 200 <= resp.status_code < 300
    error = "" if ok else (resp.text[:500] if resp.text else f"HTTP {resp.status_code}")
    return ok, resp.status_code, error


def _gmail_subject_and_body(event) -> tuple[str, str]:
    """
    Deliberately the same content/occasions as _slack_message/
    _telegram_message, reworded for a plain-text email (no chat markdown) —
    a short notification, not a copy of the invoice/payslip itself. This has
    nothing to do with apps.payroll.tasks' SMTP/Brevo invoice-email sending;
    it is the Gmail notification-channel deliverer only.
    """
    payload = event.payload or {}
    if event.event_type == "invoice.created":
        subject = f"New invoice {payload.get('invoice_number', '')} created"
        body = (
            f"A new invoice ({payload.get('invoice_number', '')}) for "
            f"₦{payload.get('total_amount', '')} was created in Audity."
        )
        return subject, body
    if event.event_type == "payment.received":
        subject = f"Payment received on invoice {payload.get('invoice_number', '')}"
        body = (
            f"A payment of ₦{payload.get('amount', payload.get('total_amount', ''))} was received "
            f"on invoice {payload.get('invoice_number', '')} in Audity."
        )
        return subject, body
    return f"Audity event: {event.event_type}", f"Audity event: {event.event_type}"


def _deliver_to_gmail(connection: ConnectorConnection, event) -> tuple[bool, int | None, str]:
    """
    Sends a notification email via the org's OWN connected Gmail account
    (nango.proxy -> gmail/v1/users/me/messages/send, see apps.connectors.
    gmail.GmailService.send_email) to the recipient the org configured
    (config["notify_email"] — set via ConnectorConfigView, same shape as
    Drive's folder_id/Calendar's calendar_id). Mirrors _deliver_to_calendar's
    "check config, bail out with a clear error if unset" gate exactly.
    """
    notify_email = (connection.config or {}).get("notify_email")
    if not notify_email:
        return False, None, "No notification email configured for this connection."
    subject, body = _gmail_subject_and_body(event)
    return gmail.GmailService.send_email(connection, to_email=notify_email, subject=subject, body_text=body)


_DELIVERERS = {
    Connector.SLACK: _deliver_to_slack,
    Connector.GOOGLE_SHEETS: _deliver_to_sheets,
    Connector.TELEGRAM: _deliver_to_telegram,
    Connector.GOOGLE_CALENDAR: _deliver_to_calendar,
    Connector.GMAIL: _deliver_to_gmail,
    # GOOGLE_DRIVE is deliberately absent — Drive isn't a business-event
    # notification target, it's a PDF-upload sink triggered at PDF
    # generation time (see maybe_save_pdf_to_drive above), not by
    # replaying DomainEvents through the beat task below.
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
        except telegram.TelegramNotConfiguredError as exc:
            ok, status_code, error = False, None, str(exc)
        except telegram.TelegramAPIError as exc:
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
