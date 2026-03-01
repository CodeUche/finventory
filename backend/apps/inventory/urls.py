from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BatchViewSet,
    CategoryViewSet,
    ProductViewSet,
    StockItemViewSet,
    StockMovementViewSet,
    WarehouseViewSet,
)

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("warehouses", WarehouseViewSet, basename="warehouse")
router.register("products", ProductViewSet, basename="product")
router.register("batches", BatchViewSet, basename="batch")
router.register("stock", StockItemViewSet, basename="stock-item")
router.register("movements", StockMovementViewSet, basename="stock-movement")

urlpatterns = [path("", include(router.urls))]
