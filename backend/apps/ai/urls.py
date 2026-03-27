from django.urls import path
from .views import AIChatView, AIStatusView, AIModelsView

urlpatterns = [
    path("chat/", AIChatView.as_view(), name="ai-chat"),
    path("status/", AIStatusView.as_view(), name="ai-status"),
    path("models/", AIModelsView.as_view(), name="ai-models"),
]
