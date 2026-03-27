"""Celery tasks for subscription lifecycle management."""
import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="subscriptions.expire_subscriptions")
def expire_subscriptions():
    """
    Runs hourly. Marks subscriptions as past_due when their trial or
    billing period has ended. Free plans (price=0) are never expired.
    """
    from .models import Subscription

    now = timezone.now()
    expired_count = 0

    # Trialing subscriptions whose trial_end has passed
    expired_trials = Subscription.objects.filter(
        status=Subscription.Status.TRIALING,
        trial_end__lt=now,
    ).exclude(plan__price=0)

    for sub in expired_trials:
        sub.status = Subscription.Status.PAST_DUE
        sub.save(update_fields=["status", "updated_at"])
        expired_count += 1
        logger.info("Trial expired for subscription %s (org plan: %s)", sub.id, sub.plan.slug)

    # Active subscriptions whose billing period has ended
    expired_active = Subscription.objects.filter(
        status=Subscription.Status.ACTIVE,
        current_period_end__lt=now,
        current_period_end__isnull=False,
    ).exclude(plan__price=0)

    for sub in expired_active:
        sub.status = Subscription.Status.PAST_DUE
        sub.save(update_fields=["status", "updated_at"])
        expired_count += 1
        logger.info("Subscription expired for %s (org plan: %s)", sub.id, sub.plan.slug)

    if expired_count:
        logger.info("expire_subscriptions: marked %d subscriptions as past_due", expired_count)

    return expired_count
