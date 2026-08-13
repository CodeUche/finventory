from django.urls import path

from .views import (
    ConnectorAddonInitiateView,
    ConnectorAddonRestoreView,
    ConnectorAddonVerifyView,
    ConnectorConfigView,
    ConnectorConnectView,
    ConnectorDisconnectView,
    ConnectorGalleryView,
    ConnectorRestoreView,
    GoogleDriveFoldersView,
    SlackChannelsView,
    nango_webhook,
    telegram_webhook,
)

urlpatterns = [
    path("", ConnectorGalleryView.as_view(), name="connector-gallery"),
    path("slack/channels/", SlackChannelsView.as_view(), name="connector-slack-channels"),
    path("google-drive/folders/", GoogleDriveFoldersView.as_view(), name="connector-google-drive-folders"),
    path("addon/verify-payment/", ConnectorAddonVerifyView.as_view(), name="connector-addon-verify"),
    path("webhook/nango/", nango_webhook, name="connector-nango-webhook"),
    path("webhook/telegram/", telegram_webhook, name="connector-telegram-webhook"),
    path("<str:connector_key>/connect/", ConnectorConnectView.as_view(), name="connector-connect"),
    path("<str:connector_key>/restore/", ConnectorRestoreView.as_view(), name="connector-restore"),
    path("<str:connector_key>/disconnect/", ConnectorDisconnectView.as_view(), name="connector-disconnect"),
    path("<str:connector_key>/config/", ConnectorConfigView.as_view(), name="connector-config"),
    path("<str:connector_key>/addon/initiate/", ConnectorAddonInitiateView.as_view(), name="connector-addon-initiate"),
    path("<str:connector_key>/addon/restore/", ConnectorAddonRestoreView.as_view(), name="connector-addon-restore"),
]
