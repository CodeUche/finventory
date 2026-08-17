"""
The bell, and the settings behind it.

Deliberately narrow: a person sees their own notifications and nobody else's.
There is no org-wide list, because a notification is addressed to a person —
letting a manager read the whole organisation's bell would leak, for example,
that a colleague requested leave.
"""

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin

from .models import Notification, NotificationPreference
from .serializers import NotificationPreferenceSerializer, NotificationSerializer


class NotificationViewSet(TenantFilterMixin, viewsets.ReadOnlyModelViewSet):
    """
    GET /notifications/            — my notifications, newest first
    GET /notifications/unread_count/
    POST /notifications/{id}/mark_read/
    POST /notifications/mark_all_read/

    Read-only by design: notifications are raised by the system, never posted
    by a client. Deliberately NOT gated on a module tick — being told that
    your own leave was approved must not depend on holding the leave
    permission.
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        org = self._get_organisation()
        # recipient=request.user is the whole access rule: your bell is yours.
        qs = Notification.objects.filter(organisation=org, recipient=self.request.user)
        if self.request.query_params.get("unread") == "true":
            qs = qs.filter(is_read=False)
        if category := self.request.query_params.get("category"):
            qs = qs.filter(category=category)
        return qs

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        return Response({"count": self.get_queryset().filter(is_read=False).count()})

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=["is_read", "read_at", "updated_at"])
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        updated = self.get_queryset().filter(is_read=False).update(
            is_read=True, read_at=timezone.now(),
        )
        return Response({"marked": updated})


class NotificationPreferenceViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """
    My own delivery choices for this organisation. In-app is always on; this
    controls whether a category is also emailed.
    """

    serializer_class = NotificationPreferenceSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "put", "patch", "head", "options"]

    def get_queryset(self):
        org = self._get_organisation()
        return NotificationPreference.objects.filter(
            organisation=org, membership__user=self.request.user,
        )

    @action(detail=False, methods=["get", "put"])
    def mine(self, request):
        """
        GET  — every category with its current setting, defaults filled in.
        PUT  — {"leave": true, "sales": false, ...}
        """
        org = self._get_organisation()
        membership = request.user.memberships.filter(
            organisation=org, is_active=True,
        ).first()
        if not membership:
            return Response(
                {"error": {"message": "You are not a member of this organisation."}},
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.method == "PUT":
            for category, enabled in (request.data or {}).items():
                if category not in dict(Notification.Category.choices):
                    continue
                NotificationPreference.objects.update_or_create(
                    organisation=org, membership=membership, category=category,
                    defaults={"email_enabled": bool(enabled)},
                )

        existing = {
            p.category: p.email_enabled
            for p in NotificationPreference.objects.filter(
                organisation=org, membership=membership,
            )
        }
        return Response({
            category: existing.get(category, False)
            for category, _ in Notification.Category.choices
        })
