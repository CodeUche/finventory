"""Till session endpoints — open, count, close, Z-report."""

import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsStaff
from apps.inventory.models import Warehouse

from .models import TillSession
from .till_serializers import TillSessionSerializer
from .till_services import TillService, TillSessionError

logger = logging.getLogger(__name__)


class TillSessionViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = TillSessionSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["status", "location"]

    def get_queryset(self):
        return (
            TillSession.objects
            .filter(organisation=self._get_organisation())
            .select_related("opened_by", "closed_by", "location")
            .prefetch_related("tender_counts")
        )

    @action(detail=False, methods=["get"])
    def current(self, request):
        """The signed-in cashier's open till, with live expected figures.

        Deliberately does NOT include what was counted — the count is blind.
        """
        org = self._get_organisation()
        session = TillService.current_session(org, request.user)
        if session is None:
            return Response({"open": False})
        return Response({"open": True, **TillService.summary(session)})

    @action(detail=False, methods=["post"])
    def open(self, request):
        org = self._get_organisation()
        location = None
        if request.data.get("location"):
            location = Warehouse.objects.filter(
                organisation=org, id=request.data["location"],
            ).first()
        try:
            session = TillService.open_session(
                org, request.user,
                opening_float=request.data.get("opening_float", 0),
                location=location,
                notes=request.data.get("notes", ""),
            )
        except TillSessionError as exc:
            return Response({"error": str(exc)}, status=422)
        return Response(TillSessionSerializer(session).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        session = self.get_object()
        try:
            session = TillService.close_session(
                session, request.user,
                counted=request.data.get("counted") or {},
                reason=request.data.get("reason", ""),
                notes=request.data.get("notes", ""),
            )
        except TillSessionError as exc:
            return Response({"error": str(exc)}, status=422)
        return Response(TillService.z_report(session))

    @action(detail=True, methods=["get"])
    def z_report(self, request, pk=None):
        return Response(TillService.z_report(self.get_object()))
