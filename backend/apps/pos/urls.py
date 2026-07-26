from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import RestaurantTableViewSet, POSOrderViewSet, KitchenOrderTicketViewSet

router = DefaultRouter()
router.register("tables", RestaurantTableViewSet, basename="pos-table")
router.register("orders", POSOrderViewSet, basename="pos-order")
router.register("kots", KitchenOrderTicketViewSet, basename="pos-kot")
urlpatterns = [path("", include(router.urls))]
