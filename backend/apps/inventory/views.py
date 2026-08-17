"""Inventory ViewSets."""

import django_filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsManager, IsManagerOrSuperuser, IsStaff
from apps.core.permissions import requires_module
# The owner's per-person ticks, enforced server-side (H-2). Mirrors
# useModuleAccess.ts: owners and admins bypass; for everyone else no
# record means no access, and only what was granted is granted.
_ModAccess_inventory = requires_module("inventory")


from .models import Batch, Category, Product, StockItem, StockMovement, Warehouse
from .serializers import (
    BatchSerializer,
    CategorySerializer,
    ProductSerializer,
    StockAdjustmentSerializer,
    StockItemSerializer,
    StockMovementSerializer,
    StockTransferSerializer,
    WarehouseSerializer,
)
from .services import InventoryService


class ProductFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    sku = django_filters.CharFilter(lookup_expr="icontains")
    category = django_filters.UUIDFilter()
    is_active = django_filters.BooleanFilter()
    min_price = django_filters.NumberFilter(field_name="selling_price", lookup_expr="gte")
    max_price = django_filters.NumberFilter(field_name="selling_price", lookup_expr="lte")

    class Meta:
        model = Product
        fields = ["name", "sku", "category", "is_active", "brand"]


class CategoryViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated, IsStaff, _ModAccess_inventory]
    search_fields = ["name"]


class WarehouseViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    queryset = Warehouse.objects.filter(is_active=True)
    serializer_class = WarehouseSerializer
    permission_classes = [IsAuthenticated, IsManager, _ModAccess_inventory]

    def create(self, request, *args, **kwargs):
        from django.db import IntegrityError, transaction
        from apps.subscriptions.services import SubscriptionService
        from apps.tenancy.models import Organisation
        org = self._get_organisation()
        try:
            with transaction.atomic():
                Organisation.objects.select_for_update().get(pk=org.pk)
                count = Warehouse.objects.filter(organisation=org, is_active=True).count()
                err = SubscriptionService.get_write_limit_error(org, "max_warehouses", count)
                if err:
                    return Response({"error": err, "upgrade_required": True}, status=402)
                return super().create(request, *args, **kwargs)
        except IntegrityError:
            return Response(
                {"error": "A warehouse with that name already exists in your organisation."},
                status=400,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("Warehouse create failed: %s", exc)
            return Response({"error": str(exc)}, status=400)


class ProductViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """
    Full CRUD for products / SKUs.

    GET /inventory/products/low-stock/ — products below reorder level
    """

    queryset = Product.objects.select_related("category", "tax_class")
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated, IsStaff, _ModAccess_inventory]
    filterset_class = ProductFilter
    search_fields = ["name", "sku", "barcode", "brand"]
    ordering_fields = ["name", "selling_price", "created_at"]

    def _slim_requested(self) -> bool:
        # Slim list is OPT-IN (?slim=1) for backward compatibility: installed
        # desktop builds older than the hydrating edit-form still prefill from
        # the list payload — serving them a slim list would blank fields on
        # their next edit-save. Old clients never send the param → full payload.
        return self.request.query_params.get("slim") == "1"

    def get_serializer_class(self):
        # LIST gets the slim payload when the client asks for it;
        # detail/create/update always keep the full serializer.
        if self.action == "list" and self._slim_requested():
            from .serializers import ProductListSerializer
            return ProductListSerializer
        return super().get_serializer_class()

    def get_queryset(self):
        """
        Annotate per-product aggregates as subqueries so the serializer never
        issues per-object queries. Without this, listing N products cost 2N+1
        queries (total_stock + quantity_incoming each) — multi-second responses
        for large catalogues that overran the client's request timeout and made
        the app fall back to offline mode ("cannot see my inventory").
        """
        from django.db.models import DecimalField, F, OuterRef, Subquery, Sum, Value
        from django.db.models.functions import Coalesce
        from apps.purchases.models import PurchaseOrderItem

        dec = DecimalField(max_digits=15, decimal_places=2)
        stock_sq = (
            StockItem.objects.filter(product=OuterRef("pk"))
            .values("product")
            .annotate(t=Sum("quantity_on_hand"))
            .values("t")[:1]
        )
        incoming_sq = (
            PurchaseOrderItem.objects.filter(
                product=OuterRef("pk"),
                purchase_order__status__in=["draft", "sent", "partially_received"],
            )
            .values("product")
            .annotate(t=Sum(F("quantity_ordered") - F("quantity_received")))
            .values("t")[:1]
        )
        qs = super().get_queryset().annotate(
            _total_stock=Coalesce(Subquery(stock_sq, output_field=dec), Value(0, output_field=dec)),
        )
        # quantity_incoming is not in the slim list payload — skip its subquery
        # only when the slim list was requested.
        if not (self.action == "list" and self._slim_requested()):
            qs = qs.annotate(
                _quantity_incoming=Coalesce(Subquery(incoming_sq, output_field=dec), Value(0, output_field=dec)),
            )
        return qs

    def create(self, request, *args, **kwargs):
        from django.db import transaction
        from apps.subscriptions.services import SubscriptionService
        from apps.tenancy.models import Organisation
        org = self._get_organisation()
        with transaction.atomic():
            Organisation.objects.select_for_update().get(pk=org.pk)
            count = Product.objects.filter(organisation=org).count()
            err = SubscriptionService.get_write_limit_error(org, "max_products", count)
            if err:
                return Response({"error": err, "upgrade_required": True}, status=402)
            return super().create(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """
        Delete a product and its associated stock data.

        Allowed only when the product has never appeared on a financial document
        (invoice, purchase order, or return).  StockItems and Batches are removed
        via CASCADE.  StockMovement ledger entries are preserved for audit purposes
        but their product FK is nullified (SET_NULL) — they do NOT appear in any
        user-facing document, so nullifying them is safe.

        Returns 422 with a human-readable message if the product is referenced
        by a financial document, so the frontend can display it directly.
        """
        from django.db import transaction
        from apps.sales.models import SaleItem, SaleReturnItem
        from apps.purchases.models import PurchaseOrderItem

        instance = self.get_object()

        # --- Guard: block deletion if product is on any financial document ---
        # These are immutable records; removing the product FK would corrupt them.
        # Operators should deactivate the product (is_active=False) instead.
        if SaleItem.objects.filter(product=instance).exists():
            return Response(
                {
                    'error': (
                        f'"{instance.name}" appears on one or more sales invoices and '
                        'cannot be deleted. Deactivate it instead.'
                    )
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if PurchaseOrderItem.objects.filter(
            product=instance,
            purchase_order__is_deleted=False,
        ).exists():
            return Response(
                {
                    'error': (
                        f'"{instance.name}" appears on one or more purchase orders and '
                        'cannot be deleted. Deactivate it instead.'
                    )
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if SaleReturnItem.objects.filter(product=instance).exists():
            return Response(
                {
                    'error': (
                        f'"{instance.name}" appears on one or more return records and '
                        'cannot be deleted. Deactivate it instead.'
                    )
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # --- Safe to delete ---
        # StockItem and Batch are removed via CASCADE on Product.
        # StockMovement.product becomes NULL (SET_NULL) — ledger rows are kept
        # for audit but are no longer tied to an active product.
        product_id = str(instance.pk)
        product_repr = str(instance)

        with transaction.atomic():
            instance.delete()

        # Best-effort audit log (non-fatal if it fails)
        try:
            from apps.core.models import AuditLog
            AuditLog.log(
                action=AuditLog.DELETE,
                user=request.user,
                model_name='Product',
                object_id=product_id,
                object_repr=product_repr,
                request=request,
            )
        except Exception:
            pass

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"], url_path="low-stock")
    def low_stock(self, request):
        """GET /api/v1/inventory/products/low-stock/"""
        org = self._get_organisation()
        items = InventoryService.get_low_stock_products(org)
        data = list(StockItemSerializer(items, many=True).data)

        # Also surface products that have never had any stock movement (quantity = 0)
        # but have a non-zero reorder level — they are effectively out of stock.
        product_ids_with_stock = StockItem.objects.filter(
            organisation=org
        ).values_list("product_id", flat=True)
        no_movement_products = Product.objects.filter(
            organisation=org,
            is_active=True,
        ).exclude(id__in=product_ids_with_stock)
        for p in no_movement_products:
            data.append({
                "id": None,
                "product": str(p.id),
                "product_name": p.name,
                "product_sku": p.sku,
                "warehouse": None,
                "warehouse_name": "No stock received",
                "quantity_on_hand": "0.00",
                "quantity_reserved": "0.00",
                "quantity_available": "0.00",
                "is_low_stock": True,
            })
        return Response(data)

    @action(detail=False, methods=["delete"], url_path="bulk-delete",
            permission_classes=[IsAuthenticated, IsManagerOrSuperuser])
    def bulk_delete(self, request):
        """
        DELETE /api/v1/inventory/products/bulk-delete/
        Body: { "ids": ["<uuid>", ...] }  — delete specific products
              (omit or pass empty list to delete ALL products in the org)

        Products referenced by invoices, purchase orders, or returns are skipped
        (not deleted) and their names are returned in the response.
        """
        from django.db import transaction
        from apps.sales.models import SaleItem, SaleReturnItem
        from apps.purchases.models import PurchaseOrderItem
        from apps.core.models import AuditLog

        org = self._get_organisation()
        ids = request.data.get("ids") or []

        qs = Product.objects.filter(organisation=org)
        if ids:
            qs = qs.filter(id__in=ids)

        # Determine which products are referenced and must be skipped
        referenced_ids = set()
        referenced_ids.update(
            SaleItem.objects.filter(product__organisation=org).values_list("product_id", flat=True)
        )
        referenced_ids.update(
            PurchaseOrderItem.objects.filter(
                product__organisation=org,
                purchase_order__is_deleted=False,
            ).values_list("product_id", flat=True)
        )
        referenced_ids.update(
            SaleReturnItem.objects.filter(product__organisation=org).values_list("product_id", flat=True)
        )

        to_delete = qs.exclude(id__in=referenced_ids)
        skipped = list(qs.filter(id__in=referenced_ids).values_list("name", flat=True))

        deleted_count = 0
        with transaction.atomic():
            for product in to_delete:
                product_id = str(product.pk)
                product_repr = str(product)
                product.delete()
                deleted_count += 1
                try:
                    AuditLog.log(
                        action=AuditLog.DELETE,
                        user=request.user,
                        model_name='Product',
                        object_id=product_id,
                        object_repr=product_repr,
                        request=request,
                    )
                except Exception:
                    pass

        return Response({
            "deleted": deleted_count,
            "skipped": skipped,
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"])
    def valuation(self, request):
        """GET /api/v1/inventory/products/valuation/ — Inventory value report."""
        from decimal import Decimal
        items = InventoryService.get_stock_valuation(self._get_organisation())
        item_data = [
            {
                "product": i.product.name,
                "sku": i.product.sku,
                "warehouse": i.warehouse.name,
                "quantity": i.quantity_on_hand,
                "unit_cost": i.product.cost_price,
                "total_value": i.total_value,
            }
            for i in items
        ]
        total = sum(Decimal(str(d["total_value"])) for d in item_data)
        return Response({"total_inventory_value": total, "items": item_data})

    @action(detail=False, methods=["get"], url_path="stock-availability")
    def stock_availability(self, request):
        """
        GET /api/v1/inventory/products/stock-availability/
        ?date_to=YYYY-MM-DD  (optional — defaults to today)

        Returns all products with current stock levels vs min/max safety levels.
        """
        from apps.inventory.models import StockItem
        org = self._get_organisation()
        products = self.get_queryset()
        stock_map: dict = {}
        for si in StockItem.objects.filter(organisation=org).select_related("product", "warehouse"):
            pid = str(si.product_id)
            if pid not in stock_map:
                stock_map[pid] = {"qty": 0, "warehouses": []}
            stock_map[pid]["qty"] += si.quantity_on_hand
            stock_map[pid]["warehouses"].append({
                "warehouse": si.warehouse.name,
                "qty": si.quantity_on_hand,
            })

        data = []
        for p in products:
            pid = str(p.id)
            qty = stock_map.get(pid, {}).get("qty", 0)
            warehouses = stock_map.get(pid, {}).get("warehouses", [])
            status = "ok"
            if qty <= 0:
                status = "out_of_stock"
            elif qty <= p.reorder_level:
                status = "low"
            elif p.max_stock_level and qty >= p.max_stock_level:
                status = "overstocked"
            data.append({
                "id": str(p.id),
                "sku": p.sku,
                "name": p.name,
                "category": p.category.name if p.category else None,
                "unit_of_measure": p.unit_of_measure,
                "quantity_on_hand": qty,
                "min_safety_level": p.reorder_level,
                "max_safety_level": p.max_stock_level,
                "reorder_quantity": p.reorder_quantity,
                "quantity_in_pack": float(p.quantity_in_pack),
                "cost_price": float(p.cost_price),
                "selling_price": float(p.selling_price),
                "status": status,
                "warehouses": warehouses,
            })
        return Response(data)

    @action(detail=False, methods=["get"], url_path="usage-report")
    def usage_report(self, request):
        """
        GET /api/v1/inventory/products/usage-report/?date_from=&date_to=
        Stock usage (sales deductions) over a date range — summary + transaction breakdown.
        """
        from django.db.models import Sum
        from apps.inventory.models import StockMovement

        org = self._get_organisation()
        date_from_str = request.query_params.get("date_from")
        date_to_str = request.query_params.get("date_to")

        qs = StockMovement.objects.filter(
            organisation=org,
            movement_type=StockMovement.MovementType.SALE_OUT,
        )
        if date_from_str:
            qs = qs.filter(created_at__date__gte=date_from_str)
        if date_to_str:
            qs = qs.filter(created_at__date__lte=date_to_str)

        # Summary rows (aggregated by product)
        summary_rows = (
            qs.values("product__id", "product__sku", "product__name", "product__unit_of_measure")
            .annotate(total_used=Sum("quantity"))
            .order_by("-total_used")
        )
        summary = [
            {
                "id": str(r["product__id"]),
                "sku": r["product__sku"],
                "name": r["product__name"],
                "unit_of_measure": r["product__unit_of_measure"],
                "total_used": abs(float(r["total_used"] or 0)),
            }
            for r in summary_rows
        ]

        # Per-transaction breakdown (most recent 500)
        transactions = []
        for m in qs.select_related("product", "warehouse", "batch", "created_by").order_by("-created_at")[:500]:
            by = ""
            if m.created_by:
                by = f"{m.created_by.first_name} {m.created_by.last_name}".strip() or m.created_by.email

            # Try to fetch customer from invoice via reference (invoice_number stored in reference)
            customer_name = ""
            try:
                from apps.sales.models import Invoice
                inv = Invoice.objects.filter(
                    organisation=org, invoice_number=m.reference
                ).select_related("customer").first()
                if inv and inv.customer:
                    customer_name = inv.customer.name
                elif inv and inv.sold_by:
                    pass  # no customer (walk-in)
            except Exception:
                pass

            transactions.append({
                "date": m.created_at.strftime("%Y-%m-%d %H:%M"),
                "product_name": m.product.name,
                "product_sku": m.product.sku,
                "warehouse": m.warehouse.name,
                "quantity": abs(float(m.quantity)),
                "unit_cost": str(m.unit_cost) if m.unit_cost else "",
                "invoice_no": m.reference or "",
                "customer": customer_name,
                "batch_number": m.batch.batch_number if m.batch else "",
                "sold_by": by,
                "notes": m.notes,
            })

        return Response({"summary": summary, "transactions": transactions})

    @action(detail=False, methods=["get"], url_path="transfer-report")
    def transfer_report(self, request):
        """
        GET /api/v1/inventory/products/transfer-report/?date_from=&date_to=
        Stock transfer and purchase-in history with full traceability.
        """
        from apps.inventory.models import StockMovement

        org = self._get_organisation()
        date_from_str = request.query_params.get("date_from")
        date_to_str = request.query_params.get("date_to")

        qs = StockMovement.objects.filter(
            organisation=org,
            movement_type__in=[
                StockMovement.MovementType.TRANSFER_IN,
                StockMovement.MovementType.TRANSFER_OUT,
                StockMovement.MovementType.PURCHASE_IN,
            ],
        ).select_related("product", "warehouse", "batch", "created_by")
        if date_from_str:
            qs = qs.filter(created_at__date__gte=date_from_str)
        if date_to_str:
            qs = qs.filter(created_at__date__lte=date_to_str)

        movements = list(qs.order_by("-created_at")[:500])

        # For PURCHASE_IN: look up supplier via PO reference
        po_refs = {m.reference for m in movements if m.movement_type == StockMovement.MovementType.PURCHASE_IN and m.reference}
        supplier_map = {}
        if po_refs:
            try:
                from apps.purchases.models import PurchaseOrder
                for po in PurchaseOrder.objects.filter(
                    organisation=org, po_number__in=po_refs
                ).select_related("supplier"):
                    supplier_map[po.po_number] = po.supplier.name if po.supplier else ""
            except Exception:
                pass

        data = []
        for m in movements:
            by = ""
            if m.created_by:
                by = f"{m.created_by.first_name} {m.created_by.last_name}".strip() or m.created_by.email

            supplier = ""
            if m.movement_type == StockMovement.MovementType.PURCHASE_IN and m.reference:
                supplier = supplier_map.get(m.reference, "")

            data.append({
                "id": str(m.id),
                "date": m.created_at.strftime("%Y-%m-%d %H:%M"),
                "movement_type": m.movement_type,
                "movement_label": m.get_movement_type_display(),
                "product_name": m.product.name,
                "product_sku": m.product.sku,
                "warehouse": m.warehouse.name,
                "quantity": float(abs(m.quantity)),
                "unit_cost": str(m.unit_cost) if m.unit_cost else "",
                "reference": m.reference,
                "supplier": supplier,
                "batch_number": m.batch.batch_number if m.batch else "",
                "batch_expiry": str(m.batch.expiry_date) if m.batch and m.batch.expiry_date else "",
                "received_by": by,
                "notes": m.notes,
            })
        return Response(data)

    @action(detail=False, methods=["get"], url_path="stock-card")
    def stock_card(self, request):
        """
        GET /api/v1/inventory/products/stock-card/?product_id=&date_from=&date_to=
        Returns full stock movement history for a product as a stock card
        with DATE, IN, OUT, BALANCE, INVOICE_NO, REMARK columns.
        """
        from apps.inventory.models import StockMovement
        org = self._get_organisation()
        product_id = request.query_params.get("product_id")
        date_from_str = request.query_params.get("date_from")
        date_to_str = request.query_params.get("date_to")

        if not product_id:
            return Response({"error": "product_id is required"}, status=400)

        qs = StockMovement.objects.filter(
            organisation=org, product_id=product_id,
        ).select_related("product", "warehouse", "batch", "created_by").order_by("created_at")

        if date_from_str:
            qs = qs.filter(created_at__date__gte=date_from_str)
        if date_to_str:
            qs = qs.filter(created_at__date__lte=date_to_str)

        # Compute running balance
        IN_TYPES = {
            StockMovement.MovementType.PURCHASE_IN,
            StockMovement.MovementType.ADJUSTMENT_IN,
            StockMovement.MovementType.TRANSFER_IN,
        }
        balance = 0.0
        data = []
        for m in qs:
            qty = float(m.quantity)
            if m.movement_type in IN_TYPES:
                in_qty, out_qty = qty, 0
                balance += qty
            else:
                in_qty, out_qty = 0, qty
                balance -= qty

            by = ""
            if m.created_by:
                by = f"{m.created_by.first_name} {m.created_by.last_name}".strip() or m.created_by.email

            data.append({
                "date": m.created_at.strftime("%Y-%m-%d %H:%M"),
                "warehouse": m.warehouse.name,
                "in": in_qty if in_qty else None,
                "out": out_qty if out_qty else None,
                "balance": balance,
                "unit_cost": str(m.unit_cost) if m.unit_cost else "",
                "invoice_no": m.reference or "",
                "batch_number": m.batch.batch_number if m.batch else "",
                "remark": m.notes or m.movement_type.replace("_", " ").title(),
                "created_by": by,
            })

        product = self.get_queryset().filter(id=product_id).first()
        return Response({
            "product": {"id": product_id, "name": product.name if product else "", "sku": product.sku if product else ""},
            "rows": data,
        })


class BatchViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    queryset = Batch.objects.select_related("product", "warehouse")
    serializer_class = BatchSerializer
    permission_classes = [IsAuthenticated, IsStaff, _ModAccess_inventory]
    filterset_fields = ["product", "warehouse", "is_active"]
    search_fields = ["product__name", "product__sku", "batch_number"]

    def get_queryset(self):
        from django.utils import timezone
        qs = super().get_queryset()
        expiry_status = self.request.query_params.get("expiry_status")
        today = timezone.now().date()
        if expiry_status == "expired":
            qs = qs.filter(expiry_date__lt=today)
        elif expiry_status == "expiring":
            from datetime import timedelta
            qs = qs.filter(expiry_date__gte=today, expiry_date__lt=today + timedelta(days=30))
        elif expiry_status == "ok":
            from datetime import timedelta
            qs = qs.filter(expiry_date__gte=today + timedelta(days=30))
        return qs


class StockItemViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """
    Stock levels per product/warehouse.

    Read operations: all staff.
    DELETE: managers only — zeroes out the stock via an ADJUSTMENT_OUT movement
            (preserving ledger integrity) then removes the StockItem record.
    Create / update are not exposed; all mutations go through the movements API.
    """

    queryset = StockItem.objects.select_related("product", "warehouse")
    serializer_class = StockItemSerializer
    permission_classes = [IsAuthenticated, IsStaff, _ModAccess_inventory]
    filterset_fields = ["product", "warehouse"]
    search_fields = ["product__name", "product__sku"]
    http_method_names = ["get", "delete", "head", "options"]

    def get_queryset(self):
        """
        Annotate per-row aggregates (incoming qty + earliest PO ETA) as
        subqueries — same N+1 elimination as ProductViewSet: without this the
        stock list ran 2 queries per row and multi-second responses for large
        catalogues pushed the client into its offline fallback.
        """
        from django.db.models import DateField, DecimalField, F, Min, OuterRef, Subquery, Sum, Value
        from django.db.models.functions import Coalesce
        from apps.purchases.models import PurchaseOrder, PurchaseOrderItem

        dec = DecimalField(max_digits=15, decimal_places=2)
        incoming_sq = (
            PurchaseOrderItem.objects.filter(
                product=OuterRef("product_id"),
                purchase_order__status__in=["draft", "sent", "partially_received"],
            )
            .values("product")
            .annotate(t=Sum(F("quantity_ordered") - F("quantity_received")))
            .values("t")[:1]
        )
        eta_sq = (
            PurchaseOrder.objects.filter(
                items__product=OuterRef("product_id"),
                status__in=["draft", "sent", "partially_received"],
                expected_date__isnull=False,
            )
            .values("organisation")
            .annotate(e=Min("expected_date"))
            .values("e")[:1]
        )
        return (
            super()
            .get_queryset()
            .annotate(
                _quantity_incoming=Coalesce(Subquery(incoming_sq, output_field=dec), Value(0, output_field=dec)),
                _incoming_eta=Subquery(eta_sq, output_field=DateField()),
            )
        )
    # Disable pagination — the list() override appends phantom rows after the
    # queryset is fetched, so server-side pagination silently drops real rows on
    # pages 2+.  The stock page always needs the full catalogue in one response.
    pagination_class = None

    def get_permissions(self):
        if self.action == "destroy":
            return [IsAuthenticated(), IsManager()]
        return [IsAuthenticated(), IsStaff()]

    def list(self, request, *args, **kwargs):
        """
        Extend the default list to include products that have never had any
        stock movement (no StockItem row yet).  These show as 0 qty / low stock
        so users can see all imported products immediately after a CSV import.

        Phantom rows are ONLY added for the unfiltered (all-warehouses) view.
        When a specific warehouse is requested the response must reflect only
        that warehouse's actual stock — never phantom-inheriting from others.
        """
        response = super().list(request, *args, **kwargs)

        # A warehouse filter means the caller wants one warehouse's actual stock.
        # Skip phantom rows so newly-created warehouses always appear empty.
        if request.query_params.get("warehouse"):
            return response

        org = self._get_organisation()

        ids_with_stock = StockItem.objects.filter(
            organisation=org
        ).values_list("product_id", flat=True)

        no_movement = Product.objects.filter(
            organisation=org, is_active=True,
        ).exclude(id__in=ids_with_stock).values(
            "id", "name", "sku"
        )

        phantom_rows = [
            {
                "id": None,
                "product": str(p["id"]),
                "product_name": p["name"],
                "product_sku": p["sku"] or "",
                "warehouse": None,
                "warehouse_name": "—",
                "quantity_on_hand": "0.00",
                "quantity_available": "0.00",
                "quantity_incoming": 0,
                "incoming_eta": None,
                "is_low_stock": True,
                "stock_level": "low",
            }
            for p in no_movement
        ]

        if not phantom_rows:
            return response

        if isinstance(response.data, dict) and "results" in response.data:
            response.data["results"] = list(response.data["results"]) + phantom_rows
            response.data["count"] = (response.data.get("count") or 0) + len(phantom_rows)
        else:
            response.data = list(response.data) + phantom_rows

        return response

    def destroy(self, request, *args, **kwargs):
        """
        Remove a stock record for a product-warehouse pair.

        If there is stock on hand, an ADJUSTMENT_OUT ledger entry is created
        to zero it out before the StockItem row is deleted.  This keeps the
        StockMovement ledger consistent: summing movements for this
        product/warehouse pair will still equal zero after deletion.
        """
        from django.db import transaction
        from decimal import Decimal

        instance = self.get_object()
        qty = instance.quantity_on_hand

        with transaction.atomic():
            if qty > Decimal("0"):
                try:
                    InventoryService.adjust_stock(
                        organisation=instance.organisation,
                        product=instance.product,
                        warehouse=instance.warehouse,
                        quantity=-qty,
                        reason="Stock record removed by manager",
                        created_by=request.user,
                    )
                except ValueError as e:
                    return Response({"error": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
            instance.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


class StockMovementViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """
    Ledger of all stock movements.

    Create-only for adjustments; history is read-only.
    """

    queryset = StockMovement.objects.select_related("product", "warehouse", "batch")
    serializer_class = StockMovementSerializer
    permission_classes = [IsAuthenticated, IsStaff, _ModAccess_inventory]
    filterset_fields = ["product", "warehouse", "movement_type"]
    ordering_fields = ["created_at"]

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated, IsManager])
    def adjust(self, request):
        """POST /api/v1/inventory/movements/adjust/ — Manual stock adjustment."""
        serializer = StockAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        org = self._get_organisation()
        try:
            product = Product.objects.get(id=d["product_id"], organisation=org)
            warehouse = Warehouse.objects.get(id=d["warehouse_id"], organisation=org)
        except (Product.DoesNotExist, Warehouse.DoesNotExist):
            return Response({"error": "Product or warehouse not found."}, status=404)

        try:
            movement = InventoryService.adjust_stock(
                organisation=org,
                product=product,
                warehouse=warehouse,
                quantity=d["quantity"],
                reason=d["reason"],
                created_by=request.user,
            )
            return Response(StockMovementSerializer(movement).data, status=201)
        except ValueError as e:
            return Response({"error": str(e)}, status=422)

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated, IsManager])
    def transfer(self, request):
        """
        POST /api/v1/inventory/movements/transfer/

        Move stock between warehouses.
        Body: { product_id, from_warehouse_id, to_warehouse_id, quantity, notes }
        """
        serializer = StockTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        org = self._get_organisation()
        try:
            product = Product.objects.get(id=d["product_id"], organisation=org)
            from_wh = Warehouse.objects.get(id=d["from_warehouse_id"], organisation=org)
            to_wh = Warehouse.objects.get(id=d["to_warehouse_id"], organisation=org)
        except (Product.DoesNotExist, Warehouse.DoesNotExist):
            return Response({"error": "Product or warehouse not found."}, status=404)

        try:
            result = InventoryService.transfer_stock(
                organisation=org,
                product=product,
                from_warehouse=from_wh,
                to_warehouse=to_wh,
                quantity=d["quantity"],
                notes=d.get("notes", ""),
                created_by=request.user,
            )
            return Response({
                "reference": result["reference"],
                "out": StockMovementSerializer(result["out"]).data,
                "in": StockMovementSerializer(result["in"]).data,
            }, status=201)
        except ValueError as e:
            return Response({"error": str(e)}, status=422)
