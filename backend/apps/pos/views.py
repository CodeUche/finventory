from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsStaff

from .models import RestaurantTable, POSOrder, KitchenOrderTicket
from .serializers import (
    RestaurantTableSerializer, POSOrderSerializer, KitchenOrderTicketSerializer,
)
from .services import POSOrderService


class RestaurantTableViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = RestaurantTableSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    filterset_fields = ["status", "section", "is_active"]

    def get_queryset(self):
        return RestaurantTable.objects.filter(organisation=self._get_organisation())

    def perform_create(self, serializer):
        serializer.save(organisation=self._get_organisation())


class POSOrderViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = POSOrderSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    filterset_fields = ["status", "order_type", "table"]
    search_fields = ["order_number"]

    def get_queryset(self):
        return (POSOrder.objects.filter(organisation=self._get_organisation())
                .select_related("table", "waiter", "customer", "invoice")
                .prefetch_related("items__product"))

    def create(self, request, *args, **kwargs):
        org = self._get_organisation()
        d = request.data
        try:
            order = POSOrderService.create_order(
                org, created_by=request.user,
                order_type=d.get("order_type", "dine_in"),
                items=d.get("items") or [],
                table_id=d.get("table") or d.get("table_id"),
                waiter_id=d.get("waiter") or d.get("waiter_id"),
                customer_id=d.get("customer") or d.get("customer_id"),
                room_number=d.get("room_number", ""),
                notes=d.get("notes", ""),
                service_charge=d.get("service_charge", 0),
                tip_amount=d.get("tip_amount", 0),
                warehouse_id=d.get("warehouse") or d.get("warehouse_id"),
            )
        except Exception as e:
            return Response({"error": f"{type(e).__name__}: {e}"}, status=422)
        return Response(POSOrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def add_items(self, request, pk=None):
        order = self.get_object()
        try:
            POSOrderService.add_items(order.organisation, order, request.data.get("items") or [])
        except (ValueError, Exception) as e:
            return Response({"error": str(e)}, status=422)
        order.refresh_from_db()
        return Response(POSOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def set_status(self, request, pk=None):
        order = self.get_object()
        try:
            POSOrderService.set_status(order, request.data.get("status"))
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return Response(POSOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def generate_kot(self, request, pk=None):
        order = self.get_object()
        kot = POSOrderService.generate_kot(order.organisation, order, section=request.data.get("section", ""))
        return Response(KitchenOrderTicketSerializer(kot).data, status=201)

    @action(detail=True, methods=["post"])
    def split_bill(self, request, pk=None):
        order = self.get_object()
        try:
            result = POSOrderService.split_bill(
                order, mode=request.data.get("mode", "equal"),
                n=request.data.get("n", 2), splits=request.data.get("splits"))
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return Response(result)

    @action(detail=True, methods=["post"])
    def finalize(self, request, pk=None):
        from django.core.exceptions import PermissionDenied as _PD
        order = self.get_object()
        try:
            result = POSOrderService.finalize_order(
                order.organisation, order,
                tenders=request.data.get("tenders") or request.data.get("payments") or [],
                created_by=request.user)
        except (ValueError, _PD) as e:
            return Response({"error": str(e)}, status=422)
        return Response({
            "order": POSOrderSerializer(result["order"]).data,
            "invoice_id": str(result["invoice"].id),
            "invoice_number": result["invoice"].invoice_number,
        }, status=201)


class KitchenOrderTicketViewSet(TenantFilterMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = KitchenOrderTicketSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    filterset_fields = ["status", "section"]

    def get_queryset(self):
        return (KitchenOrderTicket.objects.filter(organisation=self._get_organisation())
                .select_related("order__table").prefetch_related("order__items__product"))

    @action(detail=True, methods=["post"])
    def set_status(self, request, pk=None):
        kot = self.get_object()
        valid = [s[0] for s in KitchenOrderTicket.Status.choices]
        new_status = request.data.get("status")
        if new_status not in valid:
            return Response({"error": "Invalid status"}, status=400)
        kot.status = new_status
        kot.save(update_fields=["status", "updated_at"])
        return Response(KitchenOrderTicketSerializer(kot).data)
