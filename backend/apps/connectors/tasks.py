"""
Celery beat task: deliver pending connector events (Slack / Google Sheets /
Telegram / Google Calendar) + upload_pdf_to_drive (Google Drive's PDF
auto-save, dispatched on-demand rather than on this task's schedule — see
its own docstring below).

Mirrors apps.integrations.tasks.deliver_pending_webhooks exactly (same
backoff shape, same due-for-retry math) — deliberately not reusing that
task directly since the two delivery mechanisms have different failure
domains (see ConnectorEventDelivery's docstring), but there's no reason for
the *scheduling* logic to diverge.
"""

import logging

from celery import shared_task
from django.utils import timezone

from apps.core.tenant_context import for_each_organisation
from apps.integrations.models import DomainEvent

from .models import Connector, ConnectorConnection, ConnectorEventDelivery
from .services import ConnectorDeliveryService

logger = logging.getLogger(__name__)

BACKOFF_SECONDS_BASE = 60


def _due_for_retry(delivery: ConnectorEventDelivery) -> bool:
    if delivery.attempt_count == 0 or delivery.last_attempted_at is None:
        return True
    backoff = BACKOFF_SECONDS_BASE * (2 ** min(delivery.attempt_count, 5))
    return (timezone.now() - delivery.last_attempted_at).total_seconds() >= backoff


# Which DomainEvent types each connector cares about — per-connector now
# (not a single flat list) because Calendar's use case (schedule a due-date
# event) doesn't fit "payment.received" the way a chat notification does,
# and Drive doesn't participate in this event-replay pipeline at all (see
# GOOGLE_DRIVE's absence from _DELIVERERS in services.py — it's a
# PDF-upload sink triggered at generation time, not a notification target).
# Still not user-configurable per-connection in v1 (unlike
# WebhookSubscription.event_types).
CONNECTOR_EVENT_TYPES = {
    Connector.SLACK: ["invoice.created", "payment.received"],
    Connector.GOOGLE_SHEETS: ["invoice.created", "payment.received"],
    Connector.TELEGRAM: ["invoice.created", "payment.received"],
    Connector.GOOGLE_CALENDAR: ["invoice.created", "tax_obligation.upcoming"],
    Connector.GMAIL: ["invoice.created", "payment.received"],
}


@shared_task(name="connectors.deliver_pending_connector_events")
def deliver_pending_connector_events():
    # Works through the companies one at a time, naming each before it asks
    # for anything. Without that, once the connector tables are covered by the
    # database lock-down this job would ask for "all connections", get nothing
    # back, and report delivered=0 while looking healthy (NEW-15).
    counts = {"delivered": 0, "failed": 0, "skipped": 0}

    def _deliver_for_one_company(org):
        delivered = 0
        failed = 0
        skipped = 0

        connections = ConnectorConnection.objects.filter(
            organisation=org, status=ConnectorConnection.Status.ACTIVE,
        ).select_related("organisation")

        for connection in connections:
            relevant_event_types = CONNECTOR_EVENT_TYPES.get(connection.connector_key)
            if not relevant_event_types:
                continue  # e.g. GOOGLE_DRIVE — not part of this delivery pipeline

            events = DomainEvent.objects.filter(
                organisation=connection.organisation,
                event_type__in=relevant_event_types,
            ).exclude(
                connector_deliveries__connection=connection,
                connector_deliveries__status=ConnectorEventDelivery.Status.DELIVERED,
            )

            for event in events:
                existing = ConnectorEventDelivery.objects.filter(connection=connection, event=event).first()
                if existing is not None:
                    if existing.status == ConnectorEventDelivery.Status.FAILED:
                        continue
                    if not _due_for_retry(existing):
                        skipped += 1
                        continue

                try:
                    delivery = ConnectorDeliveryService.deliver_event_to_connection(connection, event)
                except Exception:
                    logger.exception(
                        "Unexpected error delivering event %s to connector connection %s",
                        event.id, connection.id,
                    )
                    continue

                if delivery.status == ConnectorEventDelivery.Status.DELIVERED:
                    delivered += 1
                elif delivery.status == ConnectorEventDelivery.Status.FAILED:
                    failed += 1
                else:
                    skipped += 1

        counts["delivered"] += delivered
        counts["failed"] += failed
        counts["skipped"] += skipped
        return delivered

    for_each_organisation(
        _deliver_for_one_company,
        task_name="connectors.deliver_pending_connector_events",
    )

    logger.info(
        "deliver_pending_connector_events: delivered=%d failed=%d skipped=%d",
        counts["delivered"], counts["failed"], counts["skipped"],
    )
    return counts


@shared_task(name="connectors.upload_pdf_to_drive", bind=True, max_retries=3, default_retry_delay=60)
def upload_pdf_to_drive(self, organisation_id: str, filename: str, pdf_base64: str):
    """
    Dispatched on-demand (not on a beat schedule) by
    apps.connectors.services.maybe_save_pdf_to_drive at the moment a PDF is
    actually generated server-side (payslip / report export / invoice
    email attachment) — there is no DomainEvent-replay path for this
    because the PDF bytes only exist momentarily at generation time, not as
    something a beat task could reconstruct later from a JSON payload.

    Retries on transient failure (Drive/Nango hiccup) up to 3 times with a
    60s backoff; a final failure is only logged — Drive auto-save is a
    convenience, never something that should page anyone or block the
    document's primary delivery path.
    """
    import base64

    from apps.tenancy.models import Organisation

    from . import nango
    from .drive import GoogleDriveService
    from .models import Connector, ConnectorConnection

    try:
        organisation = Organisation.objects.get(id=organisation_id)
    except Organisation.DoesNotExist:
        logger.warning("upload_pdf_to_drive: organisation %s not found", organisation_id)
        return

    connection = ConnectorConnection.objects.filter(
        organisation=organisation, connector_key=Connector.GOOGLE_DRIVE,
        status=ConnectorConnection.Status.ACTIVE,
    ).first()
    if connection is None:
        logger.info("upload_pdf_to_drive: org %s no longer has an active Drive connection — skipping", organisation_id)
        return

    pdf_bytes = base64.b64decode(pdf_base64)
    try:
        ok, error = GoogleDriveService.upload_pdf(connection, filename, pdf_bytes)
    except (nango.NangoNotConfiguredError, nango.NangoAPIError) as exc:
        raise self.retry(exc=exc)

    if not ok:
        logger.warning("upload_pdf_to_drive: failed for org=%s file=%s: %s", organisation_id, filename, error)
    return {"ok": ok}
