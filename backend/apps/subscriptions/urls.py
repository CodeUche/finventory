from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PlanViewSet, SubscriptionViewSet

router = DefaultRouter()
router.register("plans", PlanViewSet, basename="plan")
router.register("", SubscriptionViewSet, basename="subscription")

urlpatterns = [path("", include(router.urls))]
