from rest_framework import serializers

from .models import SupportTicket, TicketComment


class TicketCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.get_full_name", read_only=True)

    class Meta:
        model = TicketComment
        fields = ["id", "ticket", "author", "author_name", "body", "created_at"]
        read_only_fields = ["id", "author", "author_name", "created_at"]


class SupportTicketSerializer(serializers.ModelSerializer):
    comments = TicketCommentSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True)
    assigned_to_name = serializers.CharField(source="assigned_to.get_full_name", read_only=True, default=None)

    class Meta:
        model = SupportTicket
        fields = ["id", "ticket_number", "subject", "description", "status", "priority",
                  "category", "created_by", "created_by_name", "assigned_to", "assigned_to_name",
                  "resolved_at", "comments", "created_at", "updated_at"]
        read_only_fields = ["id", "ticket_number", "created_by", "created_by_name",
                            "assigned_to_name", "resolved_at", "comments", "created_at", "updated_at"]
