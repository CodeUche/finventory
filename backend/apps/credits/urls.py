from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import CreditTransactionViewSet

router = DefaultRouter()
router.register("", CreditTransactionViewSet, basename="credit")
urlpatterns = [path("", include(router.urls))]
