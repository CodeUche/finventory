from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import PurchaseOrderViewSet, PurchaseReturnViewSet

router = DefaultRouter()
router.register("orders", PurchaseOrderViewSet, basename="purchase-order")
router.register("returns", PurchaseReturnViewSet, basename="purchase-return")
urlpatterns = [path("", include(router.urls))]
