"""Celery tasks for subscription lifecycle management."""
import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="subscriptions.confirm_pending_commissions")
def confirm_pending_commissions():
    """
    Runs every 6 hours. Promotes CommissionLedger pending → confirmed
    for entries older than 48 hours (chargeback window).
    """
    from apps.tenancy.commission_service import CommissionService
    count = CommissionService.confirm_pending()
    return count


@shared_task(name="subscriptions.flag_stale_pending_commissions")
def flag_stale_pending_commissions():
    """
    Runs daily. Logs a warning for any pending commission entries
    older than 7 days — indicates a likely webhook delivery failure.
    """
    from apps.tenancy.models import CommissionLedger
    from datetime import timedelta
    cutoff = timezone.now() - timedelta(days=7)
    stale = CommissionLedger.objects.filter(
        status=CommissionLedger.Status.PENDING,
        created_at__lt=cutoff,
    ).count()
    if stale:
        logger.warning("flag_stale_pending: %d commission entries older than 7 days — check webhook delivery", stale)
    return stale


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
