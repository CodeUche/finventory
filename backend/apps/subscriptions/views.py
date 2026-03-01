"""Subscription views."""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsOwnerOrAdmin

from .models import Plan, Subscription
from .serializers import PaymentHistorySerializer, PlanSerializer, SubscriptionSerializer
from .services import SubscriptionService


class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    """GET /api/v1/subscriptions/plans/ — Public plan listing."""

    queryset = Plan.objects.filter(is_active=True, is_public=True)
    serializer_class = PlanSerializer
    permission_classes = [AllowAny]


class SubscriptionViewSet(viewsets.GenericViewSet):
    """Manage the current organisation's subscription."""

    serializer_class = SubscriptionSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get_object(self):
        org = self.request.organisation
        return org.subscription

    @action(detail=False, methods=["get"])
    def current(self, request):
        """GET /api/v1/subscriptions/current/ — Current subscription status."""
        sub = self.get_object()
        if not sub:
            return Response({"detail": "No active subscription."}, status=404)
        return Response(SubscriptionSerializer(sub).data)

    @action(detail=False, methods=["post"])
    def upgrade(self, request):
        """POST /api/v1/subscriptions/upgrade/ — Upgrade/downgrade plan."""
        plan_id = request.data.get("plan_id")
        try:
            plan = Plan.objects.get(id=plan_id, is_active=True)
        except Plan.DoesNotExist:
            return Response({"error": "Plan not found."}, status=400)

        sub = SubscriptionService.upgrade_plan(request.organisation, plan)
        return Response(SubscriptionSerializer(sub).data)

    @action(detail=False, methods=["post"])
    def cancel(self, request):
        """POST /api/v1/subscriptions/cancel/ — Cancel subscription."""
        sub = SubscriptionService.cancel(request.organisation)
        return Response(SubscriptionSerializer(sub).data)

    @action(detail=False, methods=["get"])
    def payments(self, request):
        """GET /api/v1/subscriptions/payments/ — Payment history."""
        sub = self.get_object()
        if not sub:
            return Response([])
        payments = sub.payments.order_by("-created_at")
        return Response(PaymentHistorySerializer(payments, many=True).data)
