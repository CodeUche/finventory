from rest_framework.routers import DefaultRouter

from .views import NotificationPreferenceViewSet, NotificationViewSet

router = DefaultRouter()
router.register("preferences", NotificationPreferenceViewSet, basename="notification-preference")
router.register("", NotificationViewSet, basename="notification")

urlpatterns = router.urls
