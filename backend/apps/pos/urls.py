from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .till_views import TillSessionViewSet
from .views import RestaurantTableViewSet, POSOrderViewSet, KitchenOrderTicketViewSet

router = DefaultRouter()
router.register("tables", RestaurantTableViewSet, basename="pos-table")
router.register("orders", POSOrderViewSet, basename="pos-order")
router.register("kots", KitchenOrderTicketViewSet, basename="pos-kot")
router.register("till-sessions", TillSessionViewSet, basename="till-session")
urlpatterns = [path("", include(router.urls))]
