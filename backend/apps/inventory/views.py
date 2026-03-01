"""Inventory ViewSets."""

import django_filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsManager, IsStaff

from .models import Batch, Category, Product, StockItem, StockMovement, Warehouse
from .serializers import (
    BatchSerializer,
    CategorySerializer,
    ProductSerializer,
    StockAdjustmentSerializer,
    StockItemSerializer,
    StockMovementSerializer,
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
    permission_classes = [IsAuthenticated, IsStaff]
    search_fields = ["name"]


class WarehouseViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    queryset = Warehouse.objects.filter(is_active=True)
    serializer_class = WarehouseSerializer
    permission_classes = [IsAuthenticated, IsManager]


class ProductViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """
    Full CRUD for products / SKUs.

    GET /inventory/products/low-stock/ — products below reorder level
    """

    queryset = Product.objects.select_related("category", "tax_class")
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    filterset_class = ProductFilter
    search_fields = ["name", "sku", "barcode", "brand"]
    ordering_fields = ["name", "selling_price", "created_at"]

    @action(detail=False, methods=["get"])
    def low_stock(self, request):
        """GET /api/v1/inventory/products/low-stock/"""
        items = InventoryService.get_low_stock_products(request.organisation)
        return Response(StockItemSerializer(items, many=True).data)

    @action(detail=False, methods=["get"])
    def valuation(self, request):
        """GET /api/v1/inventory/products/valuation/ — Inventory value report."""
        items = InventoryService.get_stock_valuation(request.organisation)
        data = [
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
        return Response(data)


class BatchViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    queryset = Batch.objects.select_related("product", "warehouse")
    serializer_class = BatchSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    filterset_fields = ["product", "warehouse", "is_active"]


class StockItemViewSet(TenantFilterMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only view of current stock levels per product/warehouse."""

    queryset = StockItem.objects.select_related("product", "warehouse")
    serializer_class = StockItemSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    filterset_fields = ["product", "warehouse"]
    search_fields = ["product__name", "product__sku"]


class StockMovementViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """
    Ledger of all stock movements.

    Create-only for adjustments; history is read-only.
    """

    queryset = StockMovement.objects.select_related("product", "warehouse", "batch")
    serializer_class = StockMovementSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    filterset_fields = ["product", "warehouse", "movement_type"]
    ordering_fields = ["created_at"]

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated, IsManager])
    def adjust(self, request):
        """POST /api/v1/inventory/movements/adjust/ — Manual stock adjustment."""
        serializer = StockAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            product = Product.objects.get(id=d["product_id"], organisation=request.organisation)
            warehouse = Warehouse.objects.get(id=d["warehouse_id"], organisation=request.organisation)
        except (Product.DoesNotExist, Warehouse.DoesNotExist):
            return Response({"error": "Product or warehouse not found."}, status=404)

        try:
            movement = InventoryService.adjust_stock(
                organisation=request.organisation,
                product=product,
                warehouse=warehouse,
                quantity=d["quantity"],
                reason=d["reason"],
                created_by=request.user,
            )
            return Response(StockMovementSerializer(movement).data, status=201)
        except ValueError as e:
            return Response({"error": str(e)}, status=422)
