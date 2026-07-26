from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import ExportMixin, TenantFilterMixin
from apps.core.permissions import IsStaff, plan_requires

_PlanPurchases = plan_requires('purchases')

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
    permission_classes = [IsAuthenticated, IsStaff, _PlanPurchases]
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
        import logging
        logger = logging.getLogger(__name__)
        try:
            org = self._get_organisation()
            po_number = PurchaseOrder.generate_number(org)
            serializer.save(
                organisation=org,
                po_number=po_number,
                created_by=self.request.user,
            )
        except Exception as exc:
            logger.exception("PurchaseOrder create failed: %s", exc)
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"error": f"[{type(exc).__name__}] {exc}"})

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

    @action(detail=True, methods=["post"], url_path="quick-receive")
    def quick_receive(self, request, pk=None):
        """
        POST /api/v1/purchases/orders/{id}/quick-receive/
        Receive all unreceived items at their ordered quantities in one click.
        Called from the notification bell "Mark as Received" button.
        """
        po = self.get_object()
        closed = {PurchaseOrder.Status.RECEIVED, PurchaseOrder.Status.CLOSED, PurchaseOrder.Status.CANCELED}
        if po.status in closed:
            return Response({"error": "This PO has already been fully received or closed."}, status=status.HTTP_400_BAD_REQUEST)

        items = []
        for item in po.items.all():
            remaining = item.quantity_ordered - item.quantity_received
            if remaining > 0:
                items.append({"item_id": str(item.id), "quantity_received": float(remaining)})

        if not items:
            return Response({"error": "All items on this PO have already been received."}, status=status.HTTP_400_BAD_REQUEST)

        po = PurchaseService.receive_purchase_order(po, items, request.user)
        return Response(PurchaseOrderSerializer(po).data)

    @action(detail=False, methods=["get"], url_path="eta-alerts")
    def eta_alerts(self, request):
        """
        GET /api/v1/purchases/orders/eta-alerts/
        Returns POs grouped by delivery urgency:
          - arriving_tomorrow: expected_date = tomorrow, still pending
          - due_today:         expected_date = today, still pending
          - overdue:           expected_date < today, still pending (up to 20, oldest first)
        Only returns POs with an expected_date set; draft/sent/partially_received statuses only.
        """
        from datetime import date, timedelta
        from decimal import Decimal

        org = self._get_organisation()
        today = date.today()
        tomorrow = today + timedelta(days=1)
        pending = [
            PurchaseOrder.Status.DRAFT,
            PurchaseOrder.Status.SENT,
            PurchaseOrder.Status.PARTIALLY_RECEIVED,
        ]

        base_qs = PurchaseOrder.objects.filter(
            organisation=org,
            status__in=pending,
            expected_date__isnull=False,
        ).select_related("supplier").prefetch_related("items")

        def _fmt(po, as_of=today):
            return {
                "id": str(po.id),
                "po_number": po.po_number,
                "supplier_name": po.supplier.name if po.supplier else "Walk-in",
                "expected_date": str(po.expected_date),
                "days_overdue": max(0, (as_of - po.expected_date).days),
                "item_count": po.items.count(),
                "total_amount": str(po.total_amount),
            }

        arriving_tomorrow = [_fmt(p) for p in base_qs.filter(expected_date=tomorrow)]
        due_today = [_fmt(p) for p in base_qs.filter(expected_date=today)]
        overdue = [_fmt(p) for p in base_qs.filter(expected_date__lt=today).order_by("expected_date")[:20]]

        return Response({
            "arriving_tomorrow": arriving_tomorrow,
            "due_today": due_today,
            "overdue": overdue,
        })


from .models import PurchaseReturn  # noqa: E402
from .serializers import PurchaseReturnSerializer  # noqa: E402
from .services import PurchaseReturnService  # noqa: E402


class PurchaseReturnViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """List/create supplier purchase returns. Returns are immutable once created."""

    serializer_class = PurchaseReturnSerializer
    permission_classes = [IsAuthenticated, IsStaff, _PlanPurchases]
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["supplier", "purchase_order"]
    search_fields = ["return_number"]

    def get_queryset(self):
        org = self._get_organisation()
        return (PurchaseReturn.objects.filter(organisation=org)
                .select_related("supplier", "purchase_order")
                .prefetch_related("items__product"))

    def create(self, request, *args, **kwargs):
        from apps.inventory.models import Product
        org = self._get_organisation()
        po_id = request.data.get("purchase_order_id") or request.data.get("purchase_order")
        items = request.data.get("items") or []
        try:
            po = PurchaseOrder.objects.get(id=po_id, organisation=org)
        except PurchaseOrder.DoesNotExist:
            return Response({"error": "Purchase order not found"}, status=404)
        try:
            pret = PurchaseReturnService.process_return(
                org, po, items,
                return_date=request.data.get("return_date") or None,
                refund_method=request.data.get("refund_method", "ap"),
                reason=request.data.get("reason", ""),
                created_by=request.user,
            )
        except (ValueError, Product.DoesNotExist) as e:
            return Response({"error": str(e)}, status=422)
        except Exception as e:
            return Response({"error": f"Could not process return: {type(e).__name__}: {e}"}, status=422)
        return Response(PurchaseReturnSerializer(pret).data, status=status.HTTP_201_CREATED)
