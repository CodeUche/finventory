from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import MembershipViewSet, OrganisationViewSet, PartnerViewSet

router = DefaultRouter()
router.register("organisations", OrganisationViewSet, basename="organisation")
router.register("memberships", MembershipViewSet, basename="membership")
router.register("partner", PartnerViewSet, basename="partner")

urlpatterns = [path("", include(router.urls))]
