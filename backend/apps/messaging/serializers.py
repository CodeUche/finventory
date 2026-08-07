from django.urls import reverse
from rest_framework import serializers

from .models import Conversation, ConversationParticipant, Message, MessageAttachment


class MessageAttachmentSerializer(serializers.ModelSerializer):
    """
    Deliberately does NOT serialize the raw `file` field — DRF's FileField
    renders that as `file.url`, i.e. a directly-usable, unauthenticated
    storage URL (local MEDIA_URL or a long-TTL S3 signed URL cached in the
    API response). Instead this exposes `download_url`, which points at
    MessageAttachmentDownloadView — participant-gated, auth-required, and
    (for S3) freshly short-TTL-signed on every request.
    """

    download_url = serializers.SerializerMethodField()

    class Meta:
        model = MessageAttachment
        fields = [
            "id", "message", "download_url", "file_name", "file_size",
            "content_type", "checksum", "created_at",
        ]
        read_only_fields = ["id", "message", "created_at"]

    def get_download_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get("request")
        path = reverse("messaging-attachment-download", kwargs={"pk": obj.pk})
        return request.build_absolute_uri(path) if request is not None else path


class MessageSerializer(serializers.ModelSerializer):
    attachments = MessageAttachmentSerializer(many=True, read_only=True)
    sender_email = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id", "conversation", "sender", "sender_email", "body", "seq",
            "client_nonce", "attachments", "is_deleted", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "conversation", "sender", "seq", "created_at", "updated_at"]

    def get_sender_email(self, obj):
        return obj.sender.email if obj.sender_id else None


class ConversationParticipantSerializer(serializers.ModelSerializer):
    user_email = serializers.SerializerMethodField()

    class Meta:
        model = ConversationParticipant
        fields = [
            "id", "conversation", "user", "user_email", "role",
            "joined_at", "last_read_seq", "muted", "left_at",
        ]
        read_only_fields = ["id", "conversation", "joined_at"]

    def get_user_email(self, obj):
        return obj.user.email if obj.user_id else None


class ConversationSerializer(serializers.ModelSerializer):
    participants = ConversationParticipantSerializer(many=True, read_only=True)
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id", "kind", "subject", "created_by", "is_archived",
            "last_message_at", "last_message_preview", "last_seq",
            "participants", "unread_count", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "created_by", "last_message_at", "last_message_preview",
            "last_seq", "created_at", "updated_at",
        ]

    def validate_kind(self, value):
        if value != Conversation.Kind.DIRECT:
            raise serializers.ValidationError("Only 'direct' conversations are supported in v1.")
        return value

    def get_unread_count(self, obj):
        request = self.context.get("request")
        if request is None or not request.user or not request.user.is_authenticated:
            return 0
        participant = next(
            (p for p in obj.participants.all() if p.user_id == request.user.id), None
        )
        if participant is None:
            return 0
        return max(obj.last_seq - participant.last_read_seq, 0)
