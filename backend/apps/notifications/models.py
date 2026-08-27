"""
In-app notifications, with optional delivery by email.

Why this exists
---------------
Before this, the notification bell computed everything in the browser: it
polled nine business endpoints on a timer and worked out alerts client-side.
That has three consequences. Nothing is stored, so nothing can be marked read.
Nothing is addressed to a person, so it cannot say "your leave was approved".
And nothing exists unless the browser is open, so nobody can be *told*
anything — they can only come and look.

Design follows the outbox pattern the codebase already uses. DomainEvent is
the fact ("leave.approved happened"); a Notification is one recipient's copy
of it. That mirrors DomainEvent/WebhookDelivery, where the event carries no
per-subscriber state so each recipient succeeds or fails independently.

Email goes out through the organisation's OWN connected mailbox (the Gmail
connector), not a generic Audity address, so a leave decision arrives from
hr@theircompany.com. That is the difference between a notification and a
business communication.
"""

from django.db import models

from apps.authentication.models import User
from apps.core.models import TenantAwareModel


class Notification(TenantAwareModel):
    """One recipient's copy of something that happened."""

    class Category(models.TextChoices):
        LEAVE = "leave", "Leave"
        PAYROLL = "payroll", "Payroll"
        SALES = "sales", "Sales"
        BILLS = "bills", "Bills"
        INVENTORY = "inventory", "Inventory"
        TAX = "tax", "Tax"
        SYSTEM = "system", "System"
        MESSAGES = "messages", "Messages"

    class EmailStatus(models.TextChoices):
        NOT_REQUESTED = "not_requested", "Not requested"
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        NO_CONNECTOR = "no_connector", "No mailbox connected"

    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications",
    )
    # Nullable so a notification can be raised directly, without an event —
    # and so purging old events never deletes someone's unread list.
    event = models.ForeignKey(
        "integrations.DomainEvent", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="notifications",
    )
    category = models.CharField(
        max_length=20, choices=Category.choices, default=Category.SYSTEM, db_index=True,
    )
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    # Where the bell should take you. Stored rather than derived so the link
    # survives the record it points at being renamed or moved.
    link = models.CharField(max_length=300, blank=True)

    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    email_status = models.CharField(
        max_length=20, choices=EmailStatus.choices, default=EmailStatus.NOT_REQUESTED,
    )
    email_error = models.TextField(blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantAwareModel.Meta):
        verbose_name = "Notification"
        # Newest first, and never unordered: paginating an unordered queryset
        # gives a different order between runs (the NEW-5 flake).
        ordering = ["-created_at"]
        indexes = [
            # The bell's only hot query: my unread, newest first.
            models.Index(fields=["recipient", "is_read", "-created_at"]),
        ]

    def __str__(self):
        return f"Notification({self.category}, to={self.recipient_id})"


class NotificationPreference(TenantAwareModel):
    """
    Per-person, per-category delivery choice.

    Keyed on Membership rather than User: the same person may sit in two
    organisations and want to be emailed about one and not the other.

    In-app is always on — it is the record of what happened, not a channel you
    opt out of. Email is opt-in, and off by default so nobody is mailed
    without asking.
    """

    membership = models.ForeignKey(
        "tenancy.Membership", on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    category = models.CharField(max_length=20, choices=Notification.Category.choices)
    email_enabled = models.BooleanField(default=False)

    class Meta(TenantAwareModel.Meta):
        verbose_name = "Notification Preference"
        ordering = ["category"]
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "category"],
                name="uniq_notification_pref_per_membership_category",
            ),
        ]

    def __str__(self):
        return f"NotificationPreference({self.category}, email={self.email_enabled})"
