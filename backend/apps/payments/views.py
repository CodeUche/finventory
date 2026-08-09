"""
Payment endpoints.

Webhook security, in order:
  1. IP throttling — a flood must not become a database write.
  2. Organisation resolution from the payload, so an event is only ever verified
     against the key of the org it claims to belong to.
  3. Provider signature verification with the merchant's own secret.
  4. Replay protection in PaymentService.settle.

We answer 200 to anything we deliberately drop. Providers retry aggressively on
non-2xx, and a retry storm against a spoofed event helps nobody.
"""

import hashlib
import hmac
import json
import logging

from django.conf import settings
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsOwnerOrAdmin, IsStaff
from apps.core.throttles import WebhookRateThrottle
from apps.sales.models import Invoice

from .models import (
    BankTransferClaim, MerchantBankAccount, PaymentGatewayConfig, PaymentLink,
    VirtualAccount,
)
from .providers import PaymentProviderError, get_provider
from .serializers import (
    BankTransferClaimSerializer, MerchantBankAccountSerializer,
    PaymentGatewayConfigSerializer, PaymentLinkSerializer, VirtualAccountSerializer,
)
from .services import PaymentService

logger = logging.getLogger(__name__)


def _fail(exc, code=422):
    return Response({'error': str(exc)}, status=code)


class PaymentGatewayConfigViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """A merchant's own gateway keys. Secrets are never echoed back."""

    serializer_class = PaymentGatewayConfigSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        return PaymentGatewayConfig.objects.filter(organisation=self._get_organisation())


class MerchantBankAccountViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Bank accounts the merchant wants customers to transfer into."""

    serializer_class = MerchantBankAccountSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        return MerchantBankAccount.objects.filter(organisation=self._get_organisation())


class PaymentLinkViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = PaymentLinkSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return PaymentLink.objects.filter(
            organisation=self._get_organisation()
        ).select_related('invoice')

    @action(detail=False, methods=['post'])
    def create_link(self, request):
        org = self._get_organisation()
        invoice = Invoice.objects.filter(
            id=request.data.get('invoice_id'), organisation=org,
        ).first()
        if invoice is None:
            return Response({'error': 'Invoice not found'}, status=404)
        try:
            link = PaymentService.create_payment_link(
                invoice, callback_url=request.data.get('callback_url', ''),
            )
        except PaymentProviderError as exc:
            return _fail(exc)
        return Response(PaymentLinkSerializer(link).data, status=status.HTTP_201_CREATED)


class VirtualAccountViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """One-time account numbers issued per sale."""

    serializer_class = VirtualAccountSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return VirtualAccount.objects.filter(
            organisation=self._get_organisation()
        ).select_related('invoice')

    @action(detail=False, methods=['post'])
    def issue(self, request):
        org = self._get_organisation()
        invoice = Invoice.objects.filter(
            id=request.data.get('invoice_id'), organisation=org,
        ).first()
        if invoice is None:
            return Response({'error': 'Invoice not found'}, status=404)
        try:
            account = PaymentService.create_virtual_account(invoice)
        except PaymentProviderError as exc:
            return _fail(exc)
        return Response(VirtualAccountSerializer(account).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def status(self, request, pk=None):
        """Polled by the checkout screen while the payer transfers."""
        account = self.get_object()
        return Response({
            'status': 'expired' if account.is_expired else account.status,
            'paid_at': account.paid_at,
            'invoice_status': account.invoice.status,
            'amount_due': account.invoice.amount_due,
        })


class BankTransferClaimViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Transfers into the merchant's own account, pending human confirmation."""

    serializer_class = BankTransferClaimSerializer
    permission_classes = [IsAuthenticated, IsStaff]

    def get_queryset(self):
        return BankTransferClaim.objects.filter(
            organisation=self._get_organisation()
        ).select_related('invoice', 'bank_account')

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        try:
            claim = PaymentService.confirm_bank_transfer(
                self.get_object(), request.user, request.data.get('note', ''),
            )
        except PaymentProviderError as exc:
            return _fail(exc)
        return Response(BankTransferClaimSerializer(claim).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        try:
            claim = PaymentService.reject_bank_transfer(
                self.get_object(), request.user, request.data.get('note', ''),
            )
        except PaymentProviderError as exc:
            return _fail(exc)
        return Response(BankTransferClaimSerializer(claim).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def payment_options(request):
    """What this merchant can currently collect with."""
    org = getattr(request, 'organisation', None)
    if org is None:
        from apps.tenancy.middleware import resolve_organisation
        org = resolve_organisation(request)
    options = PaymentService.payment_options(org)
    options['bank_accounts'] = MerchantBankAccountSerializer(
        options['bank_accounts'], many=True,
    ).data
    return Response(options)


# ── Webhooks ────────────────────────────────────────────────────────────────
def _org_id_from_payload(provider_slug, payload):
    """Pull the organisation out of whatever shape this provider sends."""
    if provider_slug == 'paystack':
        return ((payload.get('data') or {}).get('metadata') or {}).get('org_id')
    if provider_slug == 'monnify':
        data = payload.get('eventData') or {}
        meta = data.get('metaData') or data.get('metadata') or {}
        return meta.get('org_id')
    return None


def _verify_platform_signature(raw_body: bytes, headers) -> bool:
    """
    Verify a webhook against Audity's OWN Paystack secret (platform-level
    billing — subscriptions and integration purchases), as opposed to a
    merchant's own PaymentGatewayConfig secret (their customer sales).

    There is deliberately no PaymentGatewayConfig row for Audity's own
    account (that table is for merchants' keys), so platform-signed events
    could never verify via the per-merchant loop below — that was the bug:
    activate_from_webhook was unreachable from the real webhook route.
    """
    secret = getattr(settings, "PAYSTACK_SECRET_KEY", "")
    received = (headers.get("HTTP_X_PAYSTACK_SIGNATURE") or "").strip()
    if not secret or not received:
        return False
    expected = hmac.new(secret.encode(), msg=raw_body, digestmod=hashlib.sha512).hexdigest()
    try:
        return hmac.compare_digest(expected, received)
    except (TypeError, ValueError):
        return False


def _handle_webhook(request, provider_slug):
    raw_body = request.body
    try:
        payload = json.loads(raw_body or b'{}')
    except ValueError:
        return Response({'status': 'ignored'})

    # Platform trust-domain check FIRST — cheap (one HMAC compute) and, when
    # it verifies, completely bypasses the per-merchant-config loop below
    # since a platform-billing event has nothing to do with any merchant.
    if provider_slug == 'paystack' and _verify_platform_signature(raw_body, request.META):
        try:
            from apps.subscriptions.payment_engine import PaymentEngine

            event = payload.get('event') or ''
            data = payload.get('data') or {}

            if event.startswith('refund.'):
                PaymentEngine.handle_refund_webhook(data)
                return Response({'status': 'refund_processed'})

            payment_kind = (data.get('metadata') or {}).get('payment_kind')
            if payment_kind in ('subscription', 'integration', 'connector_addon'):
                reference = data.get('reference', '')
                PaymentEngine.activate(reference)
                return Response({'status': payment_kind})

            logger.info("Platform paystack webhook event=%s ignored (no matching handler)", event)
            return Response({'status': 'ignored'})
        except Exception:
            logger.exception("Platform webhook handling failed for provider=%s", provider_slug)
            return Response({'status': 'error_logged'})

    org_id = _org_id_from_payload(provider_slug, payload)
    configs = PaymentGatewayConfig.objects.filter(provider=provider_slug, is_active=True)
    if org_id:
        configs = configs.filter(organisation_id=org_id)

    # Without an org hint we must try each merchant's secret — only the one that
    # actually signed this event can verify it, so nothing is trusted blindly.
    for config in configs.select_related('organisation')[:50]:
        provider = get_provider(config)
        if not provider.verify_signature(raw_body, request.META):
            continue
        event = provider.parse_event(payload)
        if event is None:
            return Response({'status': 'ignored'})

        # A subscription payment is Audity's own billing, not a merchant sale.
        metadata = (payload.get('data') or {}).get('metadata') or {}
        if metadata.get('plan_id'):
            from apps.subscriptions.services import PaystackSubscriptionService
            PaystackSubscriptionService.activate_from_webhook(payload.get('data') or {})
            return Response({'status': 'subscription'})

        outcome = PaymentService.settle(config.organisation, provider_slug, event)
        logger.info("%s webhook %s → %s", provider_slug, event.event_id, outcome)
        return Response({'status': outcome})

    logger.warning(
        "%s webhook could not be verified against any active configuration (ip=%s)",
        provider_slug, request.META.get('REMOTE_ADDR', 'unknown'),
    )
    return Response({'status': 'unverified'}, status=400)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([WebhookRateThrottle])
def paystack_webhook(request):
    """POST /api/v1/payments/webhook/paystack/"""
    return _handle_webhook(request, 'paystack')


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([WebhookRateThrottle])
def monnify_webhook(request):
    """POST /api/v1/payments/webhook/monnify/"""
    return _handle_webhook(request, 'monnify')
