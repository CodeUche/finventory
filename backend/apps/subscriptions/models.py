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
from django.db.models import Q

from apps.core.models import MoneyField, TenantAwareModel, TimeStampedModel


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
    """
    Record of each payment event — the single source of truth for money moved
    through Audity's own (platform-level) Paystack account.

    Generalised beyond subscriptions so a one-time marketplace purchase (see
    IntegrationProduct/OrganisationIntegrationEntitlement below) shares one
    payment pipeline with subscription billing instead of a second, separately
    -maintained "twin" that can silently drift out of sync on security fixes.

    `on_delete=PROTECT` on both target FKs, not `SET_NULL`: a payment record is
    a financial fact and must never be silently orphaned by deleting the thing
    it paid for. `Subscription` has no soft-delete (unlike most tenant models)
    and `Organisation.subscription` is itself SET_NULL, so a real delete path
    exists — PROTECT makes that delete fail loudly instead of nulling evidence.
    """

    class Kind(models.TextChoices):
        SUBSCRIPTION = "subscription", "Subscription"
        INTEGRATION = "integration", "Integration purchase"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"

    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.SUBSCRIPTION)
    # Server-set at initiate time from request.organisation — never derived
    # from client input at verify/activate time (see PaymentEngine).
    organisation = models.ForeignKey(
        "tenancy.Organisation", on_delete=models.PROTECT, related_name="payment_history",
        null=True, blank=True,  # nullable only for pre-existing rows predating this field
    )

    subscription = models.ForeignKey(
        Subscription, on_delete=models.PROTECT, related_name="payments",
        null=True, blank=True,
    )
    integration_entitlement = models.ForeignKey(
        "OrganisationIntegrationEntitlement", on_delete=models.PROTECT, related_name="payments",
        null=True, blank=True,
    )

    provider = models.CharField(max_length=20, default="paystack")
    # Unique across the WHOLE table, not just within one subscription — this is
    # what makes a reference belong to exactly one payment, ever, and rejects a
    # reference minted by one flow being replayed against the other kind.
    provider_payment_id = models.CharField(max_length=255, unique=True, blank=True)

    # Snapshotted at initiate time from Plan.price / IntegrationProduct.price —
    # never re-derived live at verify time, so a price change mid-flight can
    # neither under-charge an old reference nor false-reject a legitimate one.
    expected_amount = MoneyField(null=True, blank=True)
    amount = MoneyField()
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUCCEEDED)
    description = models.CharField(max_length=255, blank=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = "Payment History"
        verbose_name_plural = "Payment Histories"
        constraints = [
            models.CheckConstraint(
                check=(
                    Q(status="pending")
                    | Q(kind="subscription", subscription__isnull=False, integration_entitlement__isnull=True)
                    | Q(kind="integration", integration_entitlement__isnull=False, subscription__isnull=True)
                ),
                name="payment_history_exactly_one_target_when_settled",
            ),
        ]

    def __str__(self):
        return f"PaymentHistory({self.kind}, {self.provider_payment_id}, {self.status})"


class IntegrationProduct(TimeStampedModel):
    """
    A one-time-fee item in the integrations marketplace (a webhook/Zapier
    connector to some external tool). Deliberately NOT recurring — see
    OrganisationIntegrationEntitlement for the "did they buy it" state, and
    PaymentHistory.Kind.INTEGRATION for the money side.
    """

    key = models.SlugField(unique=True)
    name = models.CharField(max_length=200)
    price = MoneyField(help_text="One-time fee, in the org's currency")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(TimeStampedModel.Meta):
        verbose_name = "Integration Product"
        ordering = ["name"]

    def __str__(self):
        return self.name


class OrganisationIntegrationEntitlement(TenantAwareModel):
    """
    One org's purchase of one IntegrationProduct.

    `status` mirrors Subscription's own status-lifecycle language deliberately
    (pending/active/revoked), not a bare boolean — PENDING is a real state (a
    PaymentHistory row was created at initiate time pointing here, but payment
    hasn't been confirmed yet) distinct from REVOKED, and collapsing the two
    into is_active=False was exactly the ambiguity that broke the very first
    draft of this design (see PaymentEngine module docstring).

    Survives a lapsed/canceled Subscription by design — the org paid for this
    separately and does not lose it or need to re-purchase it. What actually
    gates the org's *use* of it (whether the webhook-delivery Celery task
    actually fires right now) is Subscription.is_active, checked fresh at
    delivery time — see apps/integrations. That mirrors the exact
    reads-still-work/writes-blocked rule SubscriptionActive already enforces
    everywhere else in the app, rather than inventing a bespoke policy here.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    product = models.ForeignKey(IntegrationProduct, on_delete=models.PROTECT, related_name="entitlements")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    purchased_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(
        max_length=200, blank=True,
        help_text="e.g. 'refunded', 'manual', 'payment_abandoned'",
    )

    class Meta:
        verbose_name = "Organisation Integration Entitlement"
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "product"], name="one_entitlement_per_org_product",
            ),
        ]

    def __str__(self):
        return f"{self.organisation_id} → {self.product.key} ({self.status})"
