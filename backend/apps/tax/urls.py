from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (
    CapitalAllowanceClaimViewSet, DeferredTaxItemViewSet, ExciseDutyViewSet,
    RelatedPartyTransactionViewSet, TaxClassViewSet, TaxConfigViewSet,
    TaxObligationViewSet, TaxReturnViewSet, VATTransactionViewSet,
    WHTCertificateViewSet, WHTRateViewSet, WHTTransactionViewSet,
)

router = DefaultRouter()
router.register("classes", TaxClassViewSet, basename="tax-class")
router.register("configs", TaxConfigViewSet, basename="tax-config")
router.register("returns", TaxReturnViewSet, basename="tax-return")
router.register("excise", ExciseDutyViewSet, basename="excise")
router.register("wht-rates", WHTRateViewSet, basename="wht-rate")
router.register("wht-transactions", WHTTransactionViewSet, basename="wht-transaction")
router.register("wht-certificates", WHTCertificateViewSet, basename="wht-certificate")
router.register("vat-transactions", VATTransactionViewSet, basename="vat-transaction")
router.register("obligations", TaxObligationViewSet, basename="tax-obligation")
router.register("capital-allowances", CapitalAllowanceClaimViewSet, basename="capital-allowance")
router.register("deferred-tax", DeferredTaxItemViewSet, basename="deferred-tax")
router.register("transfer-pricing", RelatedPartyTransactionViewSet, basename="transfer-pricing")

urlpatterns = [path("", include(router.urls))]
