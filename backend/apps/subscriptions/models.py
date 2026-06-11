"""
Subscription and plan models.

Architecture:
    - Plans define feature sets and limits.
    - Subscriptions link an Organisation to a Plan with billing state.
    - Feature flags are stored as JSON for flexibility without schema migrations.
    - Payment provider abstraction: provider-specific IDs stored as strings.

Scaling:
    - Future Stripe integration: replace mocked payment calls with
      stripe.Subscription.create() in SubscriptionService.
    - Webhook endpoint will update subscription status asynchronously.
"""

from django.db import models

from apps.core.models import MoneyField, TimeStampedModel


class Plan(TimeStampedModel):
    """
    Subscription plan definition.

    Features stored as JSON allow adding new gates without migrations.

    Example features dict:
    {
        "max_products": 500,
        "max_users": 5,
        "multi_warehouse": false,
        "advanced_reports": true,
        "api_access": false,
        "tax_engine": "basic"   // or "advanced"
    }
    """

    class Interval(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        ANNUAL = "annual", "Annual"

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    price = MoneyField(help_text="Price per interval in the org's currency")
    interval = models.CharField(max_length=10, choices=Interval.choices, default=Interval.MONTHLY)
    trial_days = models.PositiveIntegerField(default=30)
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=True, help_text="Visible on pricing page")

    # Feature gate map — evaluated by SubscriptionService.can_use_feature()
    features = models.JSONField(default=dict)

    # Display order on pricing page
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta(TimeStampedModel.Meta):
        ordering = ["display_order", "price"]
        verbose_name = "Plan"

    def __str__(self):
        return f"{self.name} ({self.interval})"

    def get_feature(self, key, default=None):
        """Safe feature getter."""
        return self.features.get(key, default)


class Subscription(TimeStampedModel):
    """
    Links an Organisation to a Plan with billing lifecycle state.

    Status transitions:
        trialing → active → past_due → canceled
                                     → unpaid
    """

    class Status(models.TextChoices):
        TRIALING = "trialing", "Trialing"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past Due"
        CANCELED = "canceled", "Canceled"
        UNPAID = "unpaid", "Unpaid"
        INCOMPLETE = "incomplete", "Incomplete"

    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.TRIALING, db_index=True
    )
    trial_end = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)

    # Payment provider abstraction (Stripe-ready)
    provider = models.CharField(max_length=50, default="mock", help_text="e.g. stripe, paystack")
    provider_subscription_id = models.CharField(max_length=255, blank=True)
    provider_customer_id = models.CharField(max_length=255, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = "Subscription"

    def __str__(self):
        return f"Subscription({self.plan.name}, {self.status})"

    @property
    def is_active(self) -> bool:
        """Returns True if the subscription grants feature access."""
        from django.utils import timezone
        now = timezone.now()
        if self.status == self.Status.ACTIVE:
            # Free plans (price=0) have no period_end → always active
            if self.current_period_end and now > self.current_period_end:
                return False
            return True
        if self.status == self.Status.TRIALING:
            if self.trial_end and now > self.trial_end:
                return False
            return True
        return False

    def can_use_feature(self, feature_key: str, threshold=None) -> bool:
        """
        Check if the current plan grants access to a feature.

        Args:
            feature_key: Feature key from Plan.features dict.
            threshold: If int, checks feature value >= threshold.
        """
        if not self.is_active:
            return False
        value = self.plan.get_feature(feature_key)
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if threshold is not None:
            return int(value) >= int(threshold)
        return bool(value)


class PaymentHistory(TimeStampedModel):
    """Record of each payment event."""

    class Status(models.TextChoices):
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name="payments"
    )
    amount = MoneyField()
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(max_length=20, choices=Status.choices)
    provider_payment_id = models.CharField(max_length=255, blank=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = "Payment History"
        verbose_name_plural = "Payment Histories"
