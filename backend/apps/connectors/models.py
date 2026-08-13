"""
Connectors — one-click OAuth integrations (Slack, Google Sheets) via Nango.

Architecture (see also apps.connectors.nango and apps.connectors.services):
Nango (nango.dev) is an embedded-auth + API-proxy vendor. It owns the OAuth
dance, token storage, and token refresh for each third-party app. Audity's
own DB NEVER stores a raw OAuth access/refresh token for a connector — only
`nango_connection_id`, an opaque identifier Nango uses to look up the real
credentials when Audity calls Nango's Proxy API on the org's behalf. This is
deliberately why ConnectorConnection has no EncryptedCharField for a token:
there is no token here to encrypt, by design (Nango custody, not ours).

Two billing paths, matching the plan-quota vs. paid-addon split used
elsewhere in the app (see apps.subscriptions.models.Plan.features and
apps.subscriptions.models.OrganisationIntegrationEntitlement for the
precedent this mirrors):
    - plan_quota:  covered by Plan.features['max_connectors'] — no separate
      payment, gated purely by counting the org's existing ACTIVE
      plan_quota connections against the plan's quota.
    - paid_addon:  ₦4,500/connector/month (or /year), an ONGOING recurring
      subscription line-item — NOT a one-time PaymentEngine/IntegrationProduct
      purchase. Modeled by ConnectorAddonSubscription below, which borrows
      Subscription's status/period vocabulary (active/past_due/canceled,
      current_period_start/end) rather than OrganisationIntegrationEntitlement's
      one-time pending/active/revoked semantics, because an add-on connector
      renews every period instead of being unlocked once. See
      apps.subscriptions.payment_engine.ConnectorAddonHandler for how a
      successful/refunded payment is applied, and PaymentHistory.Kind.
      CONNECTOR_ADDON for the payment-side wiring — this reuses the SAME
      PaymentEngine.initiate/activate plumbing (idempotent locking, Paystack
      amount/org verification) that plan subscriptions use, rather than a
      parallel, independently-maintained billing pipeline.
"""

from django.db import models

from apps.core.models import MoneyField, TenantAwareModel


class Connector(models.TextChoices):
    """Launch connectors only — see module docstring. No placeholders for
    LinkedIn/ATS/ERP/WhatsApp; those were explicitly cut from v1.

    GOOGLE_DRIVE and GOOGLE_CALENDAR follow the exact same Nango-OAuth model
    as SLACK/GOOGLE_SHEETS. TELEGRAM is the one deliberate exception — see
    apps.connectors.services' TelegramLinkService docstring and
    apps.connectors.telegram module docstring: there is no per-org OAuth
    grant for Telegram, just one shared bot correlated to an org via a
    linking code. `choices=` here is Python/DRF-level validation only (no DB
    CHECK constraint was ever added on connector_key — see 0001_initial),
    so adding members here needs no migration.
    """

    SLACK = "slack", "Slack"
    GOOGLE_SHEETS = "google_sheets", "Google Sheets"
    GOOGLE_DRIVE = "google_drive", "Google Drive"
    GOOGLE_CALENDAR = "google_calendar", "Google Calendar"
    TELEGRAM = "telegram", "Telegram"


class ConnectorConnection(TenantAwareModel):
    """One org's connection to one connector (Slack or Google Sheets)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    class BillingMode(models.TextChoices):
        PLAN_QUOTA = "plan_quota", "Plan quota"
        PAID_ADDON = "paid_addon", "Paid add-on"

    connector_key = models.CharField(max_length=30, choices=Connector.choices, db_index=True)

    # Nango's own identifier for the underlying OAuth connection. NEVER a raw
    # token — see module docstring. Blank while status=PENDING (set once the
    # Nango webhook/restore-check confirms the connection).
    nango_connection_id = models.CharField(
        max_length=255, blank=True, db_index=True,
        help_text="Nango's connection ID. Never a raw OAuth token — Nango holds those.",
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)

    external_account_label = models.CharField(
        max_length=200, blank=True,
        help_text="Display label, e.g. Slack workspace name — shown as 'Connected as {label}'.",
    )

    # Connector-specific settings, e.g. {"channel_id": "C123"} for Slack or
    # {"spreadsheet_id": "..."} for Google Sheets. Deliberately generic JSON
    # rather than per-connector columns since the two connectors' config
    # shapes don't overlap and a 3rd connector is expected post-v1.
    config = models.JSONField(default=dict, blank=True)

    billing_mode = models.CharField(
        max_length=20, choices=BillingMode.choices, default=BillingMode.PLAN_QUOTA,
    )

    # Short-lived Nango Connect session token, kept only long enough to
    # correlate an in-progress authorization with this row (the poll/
    # silent-check/manual-restore trio uses it to re-query Nango for a
    # connection that may have completed). Cleared once ACTIVE or REVOKED.
    pending_session_token = models.CharField(max_length=255, blank=True)

    connected_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantAwareModel.Meta):
        verbose_name = "Connector Connection"
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "connector_key"],
                name="one_connection_per_org_connector",
            ),
        ]

    def __str__(self):
        return f"ConnectorConnection({self.connector_key}, org={self.organisation_id}, {self.status})"


class ConnectorAddonSubscription(TenantAwareModel):
    """
    Recurring ₦4,500/connector/month (or /year) billing line-item for a
    connector purchased BEYOND the org's plan quota. See module docstring
    for why this borrows Subscription's status/period vocabulary instead of
    OrganisationIntegrationEntitlement's one-time semantics.
    """

    class Status(models.TextChoices):
        INCOMPLETE = "incomplete", "Incomplete"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past Due"
        CANCELED = "canceled", "Canceled"

    class Interval(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        ANNUAL = "annual", "Annual"

    connector_key = models.CharField(max_length=30, choices=Connector.choices, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INCOMPLETE, db_index=True)
    interval = models.CharField(max_length=10, choices=Interval.choices, default=Interval.MONTHLY)

    # Snapshotted at initiate time (₦4,500/month, or the annual equivalent) —
    # never re-derived live at verify time, same discipline PaymentHistory.
    # expected_amount already follows for plan subscriptions.
    amount = MoneyField(help_text="₦4,500/month per connector (or annual equivalent).")

    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)

    provider = models.CharField(max_length=20, default="paystack")
    provider_subscription_id = models.CharField(max_length=255, blank=True)

    connection = models.OneToOneField(
        ConnectorConnection, on_delete=models.CASCADE, related_name="addon_subscription",
        null=True, blank=True,
    )

    class Meta(TenantAwareModel.Meta):
        verbose_name = "Connector Add-on Subscription"
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "connector_key"],
                name="one_addon_per_org_connector",
            ),
        ]

    @property
    def is_active(self) -> bool:
        from django.utils import timezone

        if self.status != self.Status.ACTIVE:
            return False
        if self.current_period_end and timezone.now() > self.current_period_end:
            return False
        return True

    def __str__(self):
        return f"ConnectorAddonSubscription({self.connector_key}, org={self.organisation_id}, {self.status})"


class ConnectorEventDelivery(TenantAwareModel):
    """
    Per-(connection, event) delivery attempt/state for events sent through a
    connector (Slack chat.postMessage / Sheets values.append via Nango's
    Proxy API). Deliberately separate from apps.integrations.WebhookDelivery
    — different transport, different failure mode (a Nango/Slack/Google API
    error is not the same shape as an arbitrary customer webhook target
    timing out) — but reuses the exact same per-(event, subscriber) retry
    shape and DomainEvent as the single source of truth for "what happened",
    exactly like WebhookDelivery does, rather than inventing a third model
    of event delivery.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"

    connection = models.ForeignKey(ConnectorConnection, on_delete=models.CASCADE, related_name="deliveries")
    event = models.ForeignKey("integrations.DomainEvent", on_delete=models.CASCADE, related_name="connector_deliveries")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempt_count = models.PositiveIntegerField(default=0)
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    last_response_code = models.PositiveIntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    MAX_ATTEMPTS = 5

    class Meta(TenantAwareModel.Meta):
        verbose_name = "Connector Event Delivery"
        constraints = [
            models.UniqueConstraint(fields=["connection", "event"], name="one_delivery_per_connection_event"),
        ]

    def __str__(self):
        return f"ConnectorEventDelivery(event={self.event_id}, connection={self.connection_id}, {self.status})"
