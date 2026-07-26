from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsStaff

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
                .select_related("created_by", "assigned_to")
                .prefetch_related("comments__author"))

    def perform_create(self, serializer):
        org = self._get_organisation()
        serializer.save(
            organisation=org,
            created_by=self.request.user,
            ticket_number=SupportTicket.generate_number(org),
        )

    @action(detail=True, methods=["post"])
    def comment(self, request, pk=None):
        ticket = self.get_object()
        body = (request.data.get("body") or "").strip()
        if not body:
            return Response({"error": "Comment body is required"}, status=400)
        c = TicketComment.objects.create(
            organisation=ticket.organisation, ticket=ticket, author=request.user, body=body)
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
