"""
Celery beat task: deliver pending connector events (Slack / Google Sheets).

Mirrors apps.integrations.tasks.deliver_pending_webhooks exactly (same
backoff shape, same due-for-retry math) — deliberately not reusing that
task directly since the two delivery mechanisms have different failure
domains (see ConnectorEventDelivery's docstring), but there's no reason for
the *scheduling* logic to diverge.
"""

import logging

from celery import shared_task
from django.utils import timezone

from apps.integrations.models import DomainEvent

from .models import ConnectorConnection, ConnectorEventDelivery
from .services import ConnectorDeliveryService

logger = logging.getLogger(__name__)

BACKOFF_SECONDS_BASE = 60


def _due_for_retry(delivery: ConnectorEventDelivery) -> bool:
    if delivery.attempt_count == 0 or delivery.last_attempted_at is None:
        return True
    backoff = BACKOFF_SECONDS_BASE * (2 ** min(delivery.attempt_count, 5))
    return (timezone.now() - delivery.last_attempted_at).total_seconds() >= backoff


# Every active connection only ever cares about events relevant to what it's
# for — both current connectors want the same two events (invoice.created,
# payment.received); this is not hardcoded further per-connector since
# there's no per-connection event-type selection in v1 (unlike
# WebhookSubscription.event_types, which IS user-configurable).
RELEVANT_EVENT_TYPES = ["invoice.created", "payment.received"]


@shared_task(name="connectors.deliver_pending_connector_events")
def deliver_pending_connector_events():
    delivered = 0
    failed = 0
    skipped = 0

    connections = ConnectorConnection.objects.filter(
        status=ConnectorConnection.Status.ACTIVE,
    ).select_related("organisation")

    for connection in connections:
        events = DomainEvent.objects.filter(
            organisation=connection.organisation,
            event_type__in=RELEVANT_EVENT_TYPES,
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

    logger.info(
        "deliver_pending_connector_events: delivered=%d failed=%d skipped=%d",
        delivered, failed, skipped,
    )
    return {"delivered": delivered, "failed": failed, "skipped": skipped}
