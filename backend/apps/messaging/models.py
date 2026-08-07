"""
Isolated in-app instant messaging (Track B).

Architecture (deliberate — see task spec, do not redesign):
    Conversation / Message are ordinary TenantAwareModels scoped to the CLIENT
    organisation, exactly like every other tenant-owned model in this codebase.
    They are NOT RLS-exempt and there is no separate FirmClientLink model.

    A firm's accountant participates in a client-org conversation as an
    ordinary Membership row in that client org, using the narrow
    Membership.Role.PARTNER_CONTACT role (NOT the existing 'accountant' role,
    which grants real payroll/salary access across most modules). See
    apps.core.permissions.ROLE_HIERARCHY — partner_contact sits below viewer
    so every existing role-gated endpoint refuses it by construction.

No WebSockets / Django Channels — pure REST with seq-based cursor pagination.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TenantAwareModel


class Conversation(TenantAwareModel):
    """A messaging thread scoped to one organisation."""

    class Kind(models.TextChoices):
        DIRECT = "direct", "Direct (1:1)"
        # No other kind is valid in v1 — enforced in clean() / serializer.

    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.DIRECT)
    subject = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_conversations",
    )
    is_archived = models.BooleanField(default=False)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_message_preview = models.CharField(max_length=200, blank=True)
    # Deterministic "min(uid)_max(uid)" string for the two participants of a
    # DIRECT conversation. Only meaningful for kind=DIRECT — left blank/null
    # for any other kind so the unique_together below never collides them
    # (Postgres treats multiple NULLs in a unique index as distinct, which is
    # exactly what we want: many non-direct conversations, at most one direct
    # thread per pair per org).
    pair_key = models.CharField(max_length=80, null=True, blank=True, db_index=True)
    # Denormalized running counter, bumped atomically on every message insert
    # inside Conversation.objects.select_for_update() (see services.create_message).
    last_seq = models.PositiveIntegerField(default=0)

    class Meta(TenantAwareModel.Meta):
        verbose_name = "Conversation"
        unique_together = [["organisation", "pair_key"]]
        indexes = [
            models.Index(fields=["organisation", "-last_message_at"]),
        ]

    def clean(self):
        super().clean()
        if self.kind not in (self.Kind.DIRECT,):
            raise ValidationError({"kind": "Only 'direct' conversations are supported in v1."})

    def __str__(self):
        return f"Conversation({self.id}) in {self.organisation_id}"

    @staticmethod
    def build_pair_key(user_id_a, user_id_b) -> str:
        """Deterministic 'min(uid)_max(uid)' key for a direct conversation pair."""
        a, b = str(user_id_a), str(user_id_b)
        lo, hi = sorted([a, b])
        return f"{lo}_{hi}"


class ConversationParticipant(TenantAwareModel):
    """Membership of a user in a Conversation, with per-user read state."""

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="participants"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversation_participations",
    )
    role = models.CharField(max_length=20, default="member")
    joined_at = models.DateTimeField(auto_now_add=True)
    # Unread = conversation.last_seq - last_read_seq
    last_read_seq = models.PositiveIntegerField(default=0)
    muted = models.BooleanField(default=False)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantAwareModel.Meta):
        verbose_name = "Conversation Participant"
        unique_together = [["conversation", "user"]]
        indexes = [
            models.Index(fields=["organisation", "user"]),
        ]

    def __str__(self):
        return f"{self.user_id} in {self.conversation_id}"


class Message(TenantAwareModel):
    """
    A single message. Soft-delete (inherited is_deleted/deleted_at) doubles
    as "unsend" — do NOT add a second delete flag.
    """

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_messages",
    )
    body = models.TextField()
    # Assigned via select_for_update() on the parent Conversation inside
    # transaction.atomic() — see apps.messaging.services.create_message.
    # Never assign this directly in a view.
    seq = models.PositiveIntegerField()
    # Client-supplied idempotency token for offline-retry safety. Partially
    # unique with conversation where not null (see Meta.constraints).
    client_nonce = models.CharField(max_length=100, null=True, blank=True)

    class Meta(TenantAwareModel.Meta):
        verbose_name = "Message"
        ordering = ["seq"]
        indexes = [
            models.Index(fields=["conversation", "seq"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "client_nonce"],
                condition=models.Q(client_nonce__isnull=False),
                name="messaging_message_unique_conversation_nonce",
            ),
        ]

    def __str__(self):
        return f"Message({self.id}) seq={self.seq} in {self.conversation_id}"


class MessageAttachment(TenantAwareModel):
    """
    A file attached to a message. Created standalone (message=None) via
    POST .../attachments/, then linked to a Message on send.
    """

    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="attachments",
        null=True,
        blank=True,
    )
    # Kept for future scoping/validation even before the attachment is linked
    # to a specific message — conversation the attachment was uploaded into.
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="pending_attachments",
        null=True,
        blank=True,
    )
    file = models.FileField(upload_to="messaging_attachments/%Y/%m/")
    file_name = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveIntegerField(default=0)
    content_type = models.CharField(max_length=100, blank=True)
    checksum = models.CharField(max_length=128, blank=True)

    class Meta(TenantAwareModel.Meta):
        verbose_name = "Message Attachment"

    def __str__(self):
        return f"Attachment({self.id}) {self.file_name}"
