from rest_framework import serializers

from .models import Notification, NotificationPreference


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id", "category", "title", "body", "link",
            "is_read", "read_at", "created_at",
        ]
        # Everything here is written by the fan-out, never by the client. The
        # only thing a recipient may change is whether they have read it, and
        # that goes through the mark_read action so read_at is set with it.
        read_only_fields = fields


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ["id", "category", "email_enabled"]
        read_only_fields = ["id"]
