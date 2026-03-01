from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import TaxClassViewSet, TaxConfigViewSet, TaxReturnViewSet, ExciseDutyViewSet, WHTRateViewSet, WHTTransactionViewSet

router = DefaultRouter()
router.register("classes", TaxClassViewSet, basename="tax-class")
router.register("configs", TaxConfigViewSet, basename="tax-config")
router.register("returns", TaxReturnViewSet, basename="tax-return")
router.register("excise", ExciseDutyViewSet, basename="excise")
router.register("wht-rates", WHTRateViewSet, basename="wht-rate")
router.register("wht-transactions", WHTTransactionViewSet, basename="wht-transaction")

urlpatterns = [path("", include(router.urls))]
