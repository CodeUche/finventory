"""
Messaging service layer — seq assignment and message creation.

seq must be assigned under a row lock on the parent Conversation to avoid a
race between two concurrent sends landing on the same seq value. Never
assign Message.seq inline in a view — always go through create_message().
"""

import logging

from django.db import transaction
from django.utils import timezone

from .models import Conversation, ConversationParticipant, Message

logger = logging.getLogger(__name__)


def _truncate_preview(body: str, length: int = 200) -> str:
    body = (body or "").strip()
    if len(body) <= length:
        return body
    return body[: length - 1].rstrip() + "…"


def create_message(*, conversation: Conversation, sender, body: str, client_nonce: str = None) -> tuple[Message, bool]:
    """
    Create a message in `conversation`, assigning the next seq atomically.

    Idempotent on (conversation, client_nonce): if a message with the same
    client_nonce already exists in this conversation, returns the EXISTING
    message (no duplicate row, no error).

    Returns (message, created) — created=False when the idempotent path
    returned an existing row.
    """
    if client_nonce:
        existing = Message.objects.filter(
            conversation=conversation, client_nonce=client_nonce
        ).first()
        if existing is not None:
            return existing, False

    with transaction.atomic():
        # Lock the parent Conversation row so concurrent sends serialize on
        # last_seq — this is what makes seq assignment race-free.
        locked_conversation = Conversation.objects.select_for_update().get(
            pk=conversation.pk
        )

        # Re-check idempotency inside the lock in case of a true concurrent
        # retry that raced past the pre-lock check above.
        if client_nonce:
            existing = Message.objects.filter(
                conversation=locked_conversation, client_nonce=client_nonce
            ).first()
            if existing is not None:
                return existing, False

        next_seq = locked_conversation.last_seq + 1
        message = Message.objects.create(
            organisation=locked_conversation.organisation,
            conversation=locked_conversation,
            sender=sender,
            body=body,
            seq=next_seq,
            client_nonce=client_nonce or None,
        )

        locked_conversation.last_seq = next_seq
        locked_conversation.last_message_at = timezone.now()
        locked_conversation.last_message_preview = _truncate_preview(body)
        locked_conversation.save(
            update_fields=["last_seq", "last_message_at", "last_message_preview", "updated_at"]
        )

    return message, True


def get_or_create_direct_conversation(*, organisation, user, other_user):
    """
    Find an existing DIRECT conversation between user and other_user in
    `organisation` (by pair_key), or create one + two participant rows
    atomically.

    Returns (conversation, created).
    """
    pair_key = Conversation.build_pair_key(user.id, other_user.id)

    existing = Conversation.objects.filter(
        organisation=organisation, kind=Conversation.Kind.DIRECT, pair_key=pair_key
    ).first()
    if existing is not None:
        return existing, False

    with transaction.atomic():
        conversation, created = Conversation.objects.get_or_create(
            organisation=organisation,
            kind=Conversation.Kind.DIRECT,
            pair_key=pair_key,
            defaults={"created_by": user},
        )
        if created:
            for participant_user in (user, other_user):
                ConversationParticipant.objects.get_or_create(
                    organisation=organisation,
                    conversation=conversation,
                    user=participant_user,
                    defaults={"role": "member"},
                )

    return conversation, created


def mark_read(*, conversation: Conversation, user) -> ConversationParticipant:
    """Set the caller's last_read_seq to the conversation's current last_seq."""
    # select_for_update() requires an open transaction — without it Postgres/
    # Django raises TransactionManagementError on every call, turning this
    # into a 500 on every "open a conversation" action (confirmed via a real
    # browser click-through, not just theoretical).
    with transaction.atomic():
        participant = ConversationParticipant.objects.select_for_update().get(
            conversation=conversation, user=user
        )
        if participant.last_read_seq != conversation.last_seq:
            participant.last_read_seq = conversation.last_seq
            participant.save(update_fields=["last_read_seq", "updated_at"])
    return participant
