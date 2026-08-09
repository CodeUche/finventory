from django.urls import path

from .views import (
    ConnectorAddonInitiateView,
    ConnectorAddonVerifyView,
    ConnectorConfigView,
    ConnectorConnectView,
    ConnectorDisconnectView,
    ConnectorGalleryView,
    ConnectorRestoreView,
    SlackChannelsView,
    nango_webhook,
)

urlpatterns = [
    path("", ConnectorGalleryView.as_view(), name="connector-gallery"),
    path("slack/channels/", SlackChannelsView.as_view(), name="connector-slack-channels"),
    path("addon/verify-payment/", ConnectorAddonVerifyView.as_view(), name="connector-addon-verify"),
    path("webhook/nango/", nango_webhook, name="connector-nango-webhook"),
    path("<str:connector_key>/connect/", ConnectorConnectView.as_view(), name="connector-connect"),
    path("<str:connector_key>/restore/", ConnectorRestoreView.as_view(), name="connector-restore"),
    path("<str:connector_key>/disconnect/", ConnectorDisconnectView.as_view(), name="connector-disconnect"),
    path("<str:connector_key>/config/", ConnectorConfigView.as_view(), name="connector-config"),
    path("<str:connector_key>/addon/initiate/", ConnectorAddonInitiateView.as_view(), name="connector-addon-initiate"),
]
