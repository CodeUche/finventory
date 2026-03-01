"""
Subscription service layer.

Provides feature-gate checking and plan lifecycle management.
Payment provider is abstracted — swap _charge_provider() for real Stripe calls.
"""

import logging
from datetime import timedelta

from django.utils import timezone

from .models import PaymentHistory, Plan, Subscription

logger = logging.getLogger(__name__)


class SubscriptionService:

    @staticmethod
    def create_trial(organisation, plan: Plan) -> Subscription:
        """Start a free trial for a new organisation."""
        trial_end = timezone.now() + timedelta(days=plan.trial_days)
        sub = Subscription.objects.create(
            plan=plan,
            status=Subscription.Status.TRIALING,
            trial_end=trial_end,
            current_period_start=timezone.now(),
            current_period_end=trial_end,
        )
        organisation.subscription = sub
        organisation.save(update_fields=["subscription"])
        logger.info("Trial started for org %s on plan %s", organisation.id, plan.name)
        return sub

    @staticmethod
    def upgrade_plan(organisation, new_plan: Plan) -> Subscription:
        """Upgrade/downgrade to a different plan."""
        sub = organisation.subscription
        if not sub:
            return SubscriptionService.create_trial(organisation, new_plan)
        sub.plan = new_plan
        sub.status = Subscription.Status.ACTIVE
        sub.current_period_start = timezone.now()
        sub.current_period_end = timezone.now() + timedelta(days=30)
        sub.save()
        logger.info("Org %s upgraded to plan %s", organisation.id, new_plan.name)
        return sub

    @staticmethod
    def cancel(organisation) -> Subscription:
        """Cancel a subscription at period end."""
        sub = organisation.subscription
        if sub:
            sub.status = Subscription.Status.CANCELED
            sub.canceled_at = timezone.now()
            sub.save()
        return sub

    @staticmethod
    def check_feature(organisation, feature_key: str, threshold=None) -> bool:
        """
        Returns True if the organisation's active subscription
        permits the given feature.

        Usage:
            if not SubscriptionService.check_feature(org, "multi_warehouse"):
                raise SubscriptionRequiredError(...)
        """
        sub = getattr(organisation, "subscription", None)
        if sub is None:
            return False
        return sub.can_use_feature(feature_key, threshold=threshold)

    @staticmethod
    def get_plan_limits(organisation) -> dict:
        """Return all feature values for the current plan."""
        sub = getattr(organisation, "subscription", None)
        if sub:
            return sub.plan.features
        return {}

    @staticmethod
    def _charge_provider(subscription: Subscription, amount, currency: str) -> PaymentHistory:
        """
        Mock payment charging. Replace with real provider SDK calls.

        Stripe example:
            stripe.PaymentIntent.create(amount=amount, currency=currency)
        """
        payment = PaymentHistory.objects.create(
            subscription=subscription,
            amount=amount,
            currency=currency,
            status=PaymentHistory.Status.SUCCEEDED,
            description=f"Subscription payment for {subscription.plan.name}",
        )
        return payment
