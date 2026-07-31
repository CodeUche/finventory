from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BankTransferClaimViewSet, MerchantBankAccountViewSet, PaymentGatewayConfigViewSet,
    PaymentLinkViewSet, VirtualAccountViewSet, monnify_webhook, payment_options,
    paystack_webhook,
)

router = DefaultRouter()
router.register('gateways', PaymentGatewayConfigViewSet, basename='gateway')
router.register('bank-accounts', MerchantBankAccountViewSet, basename='merchant-bank-account')
router.register('links', PaymentLinkViewSet, basename='payment-link')
router.register('virtual-accounts', VirtualAccountViewSet, basename='virtual-account')
router.register('transfer-claims', BankTransferClaimViewSet, basename='transfer-claim')

urlpatterns = [
    path('options/', payment_options, name='payment-options'),
    path('', include(router.urls)),
    path('webhook/paystack/', paystack_webhook, name='paystack-webhook'),
    path('webhook/monnify/', monnify_webhook, name='monnify-webhook'),
]
