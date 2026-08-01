from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    StorefrontOrderViewSet, StorefrontViewSet, public_order_status,
    public_place_order, public_products, public_storefront,
)

router = DefaultRouter()
router.register("settings", StorefrontViewSet, basename="storefront-settings")
router.register("orders", StorefrontOrderViewSet, basename="storefront-order")

urlpatterns = [
    path("", include(router.urls)),
]

# Public, unauthenticated. Mounted separately in config/urls.py so it is
# obvious at a glance which routes answer to the open internet.
public_urlpatterns = [
    path("<slug:slug>/", public_storefront, name="public-storefront"),
    path("<slug:slug>/products/", public_products, name="public-storefront-products"),
    path("<slug:slug>/orders/", public_place_order, name="public-storefront-order"),
    path("<slug:slug>/orders/<str:reference>/", public_order_status, name="public-storefront-order-status"),
]
