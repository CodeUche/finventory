from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import MembershipViewSet, OrganisationViewSet

router = DefaultRouter()
router.register("organisations", OrganisationViewSet, basename="organisation")
router.register("memberships", MembershipViewSet, basename="membership")

urlpatterns = [path("", include(router.urls))]
