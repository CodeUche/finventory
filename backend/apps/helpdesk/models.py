from django.conf import settings
from django.db import models

from apps.core.models import TenantAwareModel


class SupportTicket(TenantAwareModel):
    """A help-desk ticket raised within an organisation."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    ticket_number = models.CharField(max_length=30, db_index=True)
    subject = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    category = models.CharField(max_length=60, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tickets_created")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="tickets_assigned")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantAwareModel.Meta):
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.ticket_number} — {self.subject}"

    @classmethod
    def generate_number(cls, organisation):
        from django.db.models import Max
        import re
        prefix = str(organisation.id).replace("-", "")[:4].upper()
        pat = f"TKT-{prefix}-"
        last = cls.objects.filter(ticket_number__startswith=pat).aggregate(m=Max("ticket_number"))["m"]
        seq = 1
        if last:
            m = re.search(r"-(\d+)$", last)
            seq = (int(m.group(1)) + 1) if m else 1
        candidate = f"{pat}{seq:05d}"
        while cls.objects.filter(ticket_number=candidate).exists():
            seq += 1
            candidate = f"{pat}{seq:05d}"
        return candidate


class TicketComment(TenantAwareModel):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ticket_comments")
    body = models.TextField()

    class Meta(TenantAwareModel.Meta):
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment on {self.ticket_id}"
