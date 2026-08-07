"""
Track C — paid integrations marketplace.

Architecture (outbox pattern):
    DomainEvent      — provider-agnostic "something happened" fact, written in
                        the SAME transaction as the business mutation that
                        caused it. One row per business event, regardless of
                        how many WebhookSubscriptions exist.
    WebhookSubscription — an org's registration of a target URL + list of
                        event_types it wants delivered. Optionally tied to a
                        paid IntegrationProduct entitlement.
    WebhookDelivery  — per-(event, subscription) delivery attempt/state. This
                        is what lets delivery retry independently per
                        subscriber without re-touching DomainEvent.
    OrganisationAPIKey — a Zapier-style API key that authenticates as an org
                        directly (see apps.integrations.authentication),
                        instead of trusting a client-supplied header.

Billing/entitlement layer (IntegrationProduct, OrganisationIntegrationEntitlement,
PaymentEngine, org_can_receive_integration_delivery) already lives in
apps.subscriptions — read-only from here, never modified.
"""

import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.db import models

from apps.core.models import TenantAwareModel


class DomainEvent(TenantAwareModel):
    """
    A single business fact, written once, in the same DB transaction as the
    mutation that produced it (outbox pattern). Never written fire-and-forget
    after commit — that would allow a rolled-back business action to still
    "happen" from an integration's point of view.

    Deliberately has no per-subscriber delivery state on it — see
    WebhookDelivery, which tracks that per (event, subscription) pair so many
    subscribers can retry independently.
    """

    EVENT_TYPES = (
        ("invoice.created", "Invoice created"),
        ("payment.received", "Payment received"),
        ("employee.onboarded", "Employee onboarded"),
    )

    event_type = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField(default=dict)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta(TenantAwareModel.Meta):
        verbose_name = "Domain Event"
        indexes = [
            models.Index(fields=["organisation", "event_type", "-occurred_at"]),
        ]

    def __str__(self):
        return f"DomainEvent({self.event_type}, org={self.organisation_id})"


class WebhookSubscription(TenantAwareModel):
    """
    An org's registration of an outbound webhook target.

    `secret` is generated server-side at creation and used to HMAC-sign
    outbound deliveries (see services.deliver_event_to_subscription). It must
    never be returned by the API after the initial create response — see
    serializers.WebhookSubscriptionSerializer (list/retrieve) vs
    WebhookSubscriptionCreateResponseSerializer (create-only, includes secret
    once).
    """

    target_url = models.URLField(max_length=1000)
    event_types = models.JSONField(default=list, help_text="List of event_type strings this subscription wants.")
    secret = models.CharField(max_length=64, editable=False)
    is_active = models.BooleanField(default=True)
    integration_product = models.ForeignKey(
        "subscriptions.IntegrationProduct",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="webhook_subscriptions",
        help_text="Ties this webhook to a specific paid-integration entitlement, gating delivery.",
    )

    class Meta(TenantAwareModel.Meta):
        verbose_name = "Webhook Subscription"

    def save(self, *args, **kwargs):
        if not self.secret:
            self.secret = secrets.token_hex(32)
        super().save(*args, **kwargs)

    def wants(self, event_type: str) -> bool:
        return event_type in (self.event_types or [])

    def __str__(self):
        return f"WebhookSubscription({self.target_url}, org={self.organisation_id})"


class WebhookDelivery(TenantAwareModel):
    """
    Per-(event, subscription) delivery attempt/state. Kept separate from
    DomainEvent so N subscribers to the same event retry independently and a
    lapsed/gated subscriber never mutates the shared event row.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"

    subscription = models.ForeignKey(WebhookSubscription, on_delete=models.CASCADE, related_name="deliveries")
    event = models.ForeignKey(DomainEvent, on_delete=models.CASCADE, related_name="deliveries")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    last_response_code = models.PositiveIntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    MAX_ATTEMPTS = 5

    class Meta(TenantAwareModel.Meta):
        verbose_name = "Webhook Delivery"
        constraints = [
            models.UniqueConstraint(fields=["subscription", "event"], name="one_delivery_per_subscription_event"),
        ]

    def __str__(self):
        return f"WebhookDelivery(event={self.event_id}, sub={self.subscription_id}, {self.status})"


class OrganisationAPIKey(TenantAwareModel):
    """
    A Zapier-style API key that identifies its owning organisation on its own
    (see apps.integrations.authentication.APIKeyAuthentication) — never via a
    client-supplied X-Organisation-ID header, which is only trustworthy under
    session/JWT auth where org membership was already verified at login.

    The plaintext key is shown to the user exactly once at creation time and
    never stored — only `key_hash` (via Django's own password hasher, the
    same precedent apps.authentication uses for OTP-style secrets — see
    apps/authentication/views.py's _hash_code/_check_code helpers) plus a
    short `key_prefix` for fast lookup without needing to hash-and-compare
    against every active key row.
    """

    name = models.CharField(max_length=200, help_text="Label, e.g. 'Zapier'")
    key_prefix = models.CharField(max_length=12, db_index=True)
    key_hash = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantAwareModel.Meta):
        verbose_name = "Organisation API Key"

    @staticmethod
    def generate_key() -> tuple[str, str, str]:
        """Returns (plaintext_key, key_prefix, key_hash). Plaintext is never stored."""
        plaintext = f"audk_{secrets.token_urlsafe(32)}"
        prefix = plaintext[:12]
        return plaintext, prefix, make_password(plaintext)

    def check_key(self, plaintext: str) -> bool:
        return check_password(plaintext, self.key_hash)

    def __str__(self):
        return f"OrganisationAPIKey({self.name}, {self.key_prefix}…, org={self.organisation_id})"
