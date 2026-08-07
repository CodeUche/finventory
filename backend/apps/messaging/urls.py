from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ConversationViewSet,
    MessageAttachmentDownloadView,
    MessageSearchView,
    PartnerInboxView,
    UnreadCountView,
)

router = DefaultRouter()
router.register("conversations", ConversationViewSet, basename="conversation")

urlpatterns = [
    path("unread_count/", UnreadCountView.as_view(), name="messaging-unread-count"),
    path("partner_inbox/", PartnerInboxView.as_view(), name="messaging-partner-inbox"),
    path("search/", MessageSearchView.as_view(), name="messaging-search"),
    path(
        "attachments/<uuid:pk>/download/",
        MessageAttachmentDownloadView.as_view(),
        name="messaging-attachment-download",
    ),
    path("", include(router.urls)),
]
