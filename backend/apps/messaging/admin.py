from django.contrib import admin

from .models import Conversation, ConversationParticipant, Message, MessageAttachment


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "organisation", "kind", "last_message_at", "last_seq", "is_archived")
    list_filter = ("kind", "is_archived")
    search_fields = ("id", "subject", "pair_key")
    raw_id_fields = ("organisation", "created_by")


@admin.register(ConversationParticipant)
class ConversationParticipantAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "user", "role", "last_read_seq", "muted")
    list_filter = ("role", "muted")
    raw_id_fields = ("organisation", "conversation", "user")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender", "seq", "is_deleted", "created_at")
    list_filter = ("is_deleted",)
    raw_id_fields = ("organisation", "conversation", "sender")


@admin.register(MessageAttachment)
class MessageAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "message", "file_name", "file_size", "content_type")
    raw_id_fields = ("organisation", "message", "conversation")
