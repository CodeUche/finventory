from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PaymentGatewayConfigViewSet, PaymentLinkViewSet, paystack_webhook

router = DefaultRouter()
router.register('gateways', PaymentGatewayConfigViewSet, basename='gateway')
router.register('links', PaymentLinkViewSet, basename='payment-link')

urlpatterns = [
    path('', include(router.urls)),
    path('webhook/paystack/', paystack_webhook, name='paystack-webhook'),
]
