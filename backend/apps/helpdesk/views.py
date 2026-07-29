from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsStaff, IsSuperuser

from . import services
from .models import SupportTicket, TicketComment
from .serializers import SupportTicketSerializer, TicketCommentSerializer


class SupportTicketViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Help-desk tickets for the organisation."""

    serializer_class = SupportTicketSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    filterset_fields = ["status", "priority"]
    search_fields = ["ticket_number", "subject"]

    def get_queryset(self):
        org = self._get_organisation()
        return (SupportTicket.objects.filter(organisation=org)
                .select_related("created_by", "assigned_to", "organisation")
                .prefetch_related("comments__author"))

    def perform_create(self, serializer):
        org = self._get_organisation()
        ticket = serializer.save(
            organisation=org,
            created_by=self.request.user,
            ticket_number=SupportTicket.generate_number(org),
        )
        services.notify_new_ticket(ticket)

    @action(detail=True, methods=["post"])
    def comment(self, request, pk=None):
        ticket = self.get_object()
        body = (request.data.get("body") or "").strip()
        if not body:
            return Response({"error": "Comment body is required"}, status=400)
        c = TicketComment.objects.create(
            organisation=ticket.organisation, ticket=ticket, author=request.user, body=body)
        services.notify_new_comment(c)
        return Response(TicketCommentSerializer(c).data, status=201)

    @action(detail=True, methods=["post"])
    def set_status(self, request, pk=None):
        from django.utils import timezone
        ticket = self.get_object()
        new_status = request.data.get("status")
        valid = [s[0] for s in SupportTicket.Status.choices]
        if new_status not in valid:
            return Response({"error": "Invalid status"}, status=400)
        ticket.status = new_status
        ticket.resolved_at = timezone.now() if new_status == SupportTicket.Status.RESOLVED else ticket.resolved_at
        ticket.save(update_fields=["status", "resolved_at", "updated_at"])
        return Response(SupportTicketSerializer(ticket).data)


class _PlatformPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class PlatformTicketViewSet(viewsets.ReadOnlyModelViewSet):
    """Cross-organisation support inbox — Audity superusers only.

    Read + workflow actions (reply / set status / assign) over every org's
    tickets. This is the vendor-side counterpart to the org-scoped viewset.
    """

    serializer_class = SupportTicketSerializer
    permission_classes = [IsAuthenticated, IsSuperuser]
    pagination_class = _PlatformPagination
    filterset_fields = ["status", "priority"]
    search_fields = ["ticket_number", "subject"]

    def get_queryset(self):
        return (SupportTicket.objects.all()
                .select_related("created_by", "assigned_to", "organisation")
                .prefetch_related("comments__author"))

    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        ticket = self.get_object()
        body = (request.data.get("body") or "").strip()
        if not body:
            return Response({"error": "Reply body is required"}, status=400)
        c = TicketComment.objects.create(
            organisation=ticket.organisation, ticket=ticket, author=request.user, body=body)
        # Support replied → email the customer who raised it.
        services.notify_creator_reply(c)
        return Response(TicketCommentSerializer(c).data, status=201)

    @action(detail=True, methods=["post"])
    def set_status(self, request, pk=None):
        from django.utils import timezone
        ticket = self.get_object()
        new_status = request.data.get("status")
        valid = [s[0] for s in SupportTicket.Status.choices]
        if new_status not in valid:
            return Response({"error": "Invalid status"}, status=400)
        ticket.status = new_status
        ticket.resolved_at = timezone.now() if new_status == SupportTicket.Status.RESOLVED else ticket.resolved_at
        ticket.save(update_fields=["status", "resolved_at", "updated_at"])
        return Response(SupportTicketSerializer(ticket).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        """Assign to self (default) or to a given user id."""
        ticket = self.get_object()
        user_id = request.data.get("user_id")
        if user_id:
            from apps.authentication.models import User
            try:
                assignee = User.objects.get(id=user_id)
            except (User.DoesNotExist, ValueError, TypeError):
                return Response({"error": "User not found"}, status=404)
        else:
            assignee = request.user
        ticket.assigned_to = assignee
        ticket.save(update_fields=["assigned_to", "updated_at"])
        return Response(SupportTicketSerializer(ticket).data)
