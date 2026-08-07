"""
Celery beat task: deliver pending webhook events.

Runs frequently (every 1-2 minutes — see CELERY_BEAT_SCHEDULE in
config/settings/base.py) since webhook delivery should feel near-real-time,
unlike this codebase's other weekly/monthly scheduled jobs.
"""

import logging

from celery import shared_task
from django.utils import timezone

from .models import DomainEvent, WebhookDelivery, WebhookSubscription
from .services import deliver_event_to_subscription

logger = logging.getLogger(__name__)

# Exponential backoff (seconds) indexed by attempt_count so far: don't retry a
# failed delivery immediately, wait 2^attempt minutes (capped).
BACKOFF_SECONDS_BASE = 60


def _due_for_retry(delivery: WebhookDelivery) -> bool:
    if delivery.attempt_count == 0 or delivery.last_attempted_at is None:
        return True
    backoff = BACKOFF_SECONDS_BASE * (2 ** min(delivery.attempt_count, 5))
    return (timezone.now() - delivery.last_attempted_at).total_seconds() >= backoff


@shared_task(name="integrations.deliver_pending_webhooks")
def deliver_pending_webhooks():
    """
    For every active WebhookSubscription, find DomainEvents matching its
    event_types that don't yet have a DELIVERED WebhookDelivery row, and
    attempt delivery (subject to gating + backoff).
    """
    delivered = 0
    failed = 0
    skipped = 0

    subscriptions = WebhookSubscription.objects.filter(is_active=True).select_related(
        "organisation", "integration_product"
    )

    for subscription in subscriptions:
        events = DomainEvent.objects.filter(
            organisation=subscription.organisation,
            event_type__in=(subscription.event_types or []),
        ).exclude(
            deliveries__subscription=subscription,
            deliveries__status=WebhookDelivery.Status.DELIVERED,
        )

        for event in events:
            existing = WebhookDelivery.objects.filter(subscription=subscription, event=event).first()
            if existing is not None:
                if existing.status == WebhookDelivery.Status.FAILED:
                    continue  # permanently exhausted or permanently gated
                if not _due_for_retry(existing):
                    skipped += 1
                    continue

            try:
                delivery = deliver_event_to_subscription(subscription, event)
            except Exception:
                logger.exception(
                    "Unexpected error delivering event %s to subscription %s",
                    event.id, subscription.id,
                )
                continue

            if delivery.status == WebhookDelivery.Status.DELIVERED:
                delivered += 1
            elif delivery.status == WebhookDelivery.Status.FAILED:
                failed += 1
            else:
                skipped += 1

    logger.info(
        "deliver_pending_webhooks: delivered=%d failed=%d skipped=%d",
        delivered, failed, skipped,
    )
    return {"delivered": delivered, "failed": failed, "skipped": skipped}
