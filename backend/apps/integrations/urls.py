from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    APIKeyViewSet,
    IntegrationProductListView,
    WebhookSubscriptionViewSet,
    ZapierHooksSubscribeView,
    ZapierHooksUnsubscribeView,
    ZapierPollingTriggerView,
)

router = DefaultRouter()
router.register("webhooks", WebhookSubscriptionViewSet, basename="webhook-subscription")
router.register("api-keys", APIKeyViewSet, basename="organisation-api-key")

urlpatterns = [
    path("products/", IntegrationProductListView.as_view(), name="integration-products"),
    path("zapier/hooks/subscribe/", ZapierHooksSubscribeView.as_view(), name="zapier-hooks-subscribe"),
    path("zapier/hooks/unsubscribe/", ZapierHooksUnsubscribeView.as_view(), name="zapier-hooks-unsubscribe"),
    path("zapier/triggers/<str:event_type>/", ZapierPollingTriggerView.as_view(), name="zapier-polling-trigger"),
    path("", include(router.urls)),
]
