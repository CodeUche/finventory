from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import ExportMixin, TenantFilterMixin
from apps.core.permissions import IsStaff

from .models import PurchaseOrder
from .serializers import PurchaseOrderSerializer, ReceiveItemSerializer
from .services import PurchaseService


class PurchaseOrderViewSet(ExportMixin, TenantFilterMixin, viewsets.ModelViewSet):
    export_filename = 'purchase_orders'
    export_fields = [
        ('PO #', 'po_number'),
        ('Order Date', 'order_date'),
        ('Supplier', lambda o: o.supplier.name if o.supplier else 'Walk-in'),
        ('Status', 'status'),
        ('Total', 'total'),
        ('Notes', 'notes'),
    ]
    """
    Manage purchase orders.

    POST /purchases/orders/{id}/receive/ — Mark goods as received.
    """

    queryset = PurchaseOrder.objects.select_related("supplier", "warehouse").prefetch_related("items__product")
    serializer_class = PurchaseOrderSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    filterset_fields = ["status", "supplier"]
    search_fields = ["po_number", "supplier__name"]
    ordering_fields = ["order_date", "total_amount"]

    def get_queryset(self):
        org = self._get_organisation()
        qs = PurchaseOrder.objects.filter(organisation=org).select_related("supplier", "warehouse").prefetch_related("items__product")
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(order_date__gte=date_from)
        if date_to:
            qs = qs.filter(order_date__lte=date_to)
        return qs

    def perform_create(self, serializer):
        org = self.request.organisation
        po_number = PurchaseOrder.generate_number(org)
        serializer.save(
            organisation=org,
            po_number=po_number,
            created_by=self.request.user,
        )

    @action(detail=True, methods=["post"], url_path="clear_receipt")
    def clear_receipt(self, request, pk=None):
        """POST /api/v1/purchases/orders/{id}/clear_receipt/ — remove the attached receipt."""
        po = self.get_object()
        po.receipt.delete(save=True)
        return Response({"receipt": None})

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        """POST /api/v1/purchases/orders/{id}/receive/"""
        po = self.get_object()
        serializer = ReceiveItemSerializer(data=request.data.get("items", []), many=True)
        serializer.is_valid(raise_exception=True)

        po = PurchaseService.receive_purchase_order(po, serializer.validated_data, request.user)
        return Response(PurchaseOrderSerializer(po).data)
