from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    MembershipViewSet, OrganisationViewSet, PartnerViewSet,
    PartnerInvoiceViewSet, WhiteLabelViewSet, PublicBrandingView,
)

router = DefaultRouter()
router.register("organisations", OrganisationViewSet, basename="organisation")
router.register("memberships", MembershipViewSet, basename="membership")
router.register("partner", PartnerViewSet, basename="partner")
router.register("partner-invoices", PartnerInvoiceViewSet, basename="partner-invoice")
router.register("partner/white-label-mgmt", WhiteLabelViewSet, basename="white-label-mgmt")

urlpatterns = [
    path("", include(router.urls)),
    # Public — no auth required; used by frontend on initial load
    path("white-label/", PublicBrandingView.as_view(), name="public-branding"),
]
