from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsOwnerOrAdmin
from apps.sales.models import Invoice
from .models import PaymentGatewayConfig, PaymentLink
from .serializers import PaymentGatewayConfigSerializer, PaymentLinkSerializer
from .services import PaystackService


class PaymentGatewayConfigViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = PaymentGatewayConfigSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        org = self._get_organisation()
        return PaymentGatewayConfig.objects.filter(organisation=org)


class PaymentLinkViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = PaymentLinkSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        org = self._get_organisation()
        return PaymentLink.objects.filter(organisation=org).select_related('invoice')

    @action(detail=False, methods=['post'])
    def create_link(self, request):
        org = self._get_organisation()
        invoice_id = request.data.get('invoice_id')
        try:
            invoice = Invoice.objects.get(id=invoice_id, organisation=org)
        except Invoice.DoesNotExist:
            return Response({'error': 'Invoice not found'}, status=404)
        try:
            config = PaymentGatewayConfig.objects.get(organisation=org, provider='paystack', is_active=True)
        except PaymentGatewayConfig.DoesNotExist:
            return Response({'error': 'No active Paystack configuration found. Please configure in Settings -> Payment Gateways.'}, status=400)
        link = PaystackService.create_payment_link(invoice, config)
        return Response(PaymentLinkSerializer(link).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def paystack_webhook(request):
    """Public endpoint for Paystack webhooks."""
    payload = request.data
    # TODO: verify webhook signature using config.webhook_secret
    return Response({'status': 'received'})
