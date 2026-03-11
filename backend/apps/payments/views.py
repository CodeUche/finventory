"""
Payment gateway views.

Security notes:
- Webhook endpoint uses HMAC-SHA512 signature verification (Paystack standard).
- All authenticated viewsets enforce IsOwnerOrAdmin for config management.
- Secret keys stored in the DB are never echoed in API responses (write_only
  enforcement is in PaymentGatewayConfigSerializer).
"""

import hashlib
import hmac
import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsOwnerOrAdmin
from apps.core.throttles import WebhookRateThrottle
from apps.sales.models import Invoice

from .models import PaymentGatewayConfig, PaymentLink
from .serializers import PaymentGatewayConfigSerializer, PaymentLinkSerializer
from .services import PaystackService

logger = logging.getLogger(__name__)

# Paystack sends the HMAC-SHA512 signature in this HTTP header.
# Django converts it to META key format (HTTP_ prefix + uppercase + underscores).
_PAYSTACK_SIG_HEADER = "HTTP_X_PAYSTACK_SIGNATURE"


def _verify_paystack_signature(raw_body: bytes, secret: str, received_sig: str) -> bool:
    """
    Verify a Paystack webhook HMAC-SHA512 signature.

    Paystack signs the raw JSON body with the webhook_secret using HMAC-SHA512
    and sends the hex-encoded digest in the X-Paystack-Signature header.

    We use hmac.compare_digest (constant-time comparison) to prevent
    timing-oracle attacks.

    Reference: https://paystack.com/docs/payments/webhooks/#verify-event-origin
    """
    expected = hmac.new(
        secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha512,
    ).hexdigest()
    # compare_digest raises TypeError if either arg isn't str — safe default is False
    try:
        return hmac.compare_digest(expected, received_sig)
    except (TypeError, ValueError):
        return False


class PaymentGatewayConfigViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """CRUD for per-org payment gateway configurations (Paystack, etc.)."""

    serializer_class = PaymentGatewayConfigSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        org = self._get_organisation()
        return PaymentGatewayConfig.objects.filter(organisation=org)


class PaymentLinkViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Create and list payment links tied to invoices."""

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
            config = PaymentGatewayConfig.objects.get(
                organisation=org, provider='paystack', is_active=True
            )
        except PaymentGatewayConfig.DoesNotExist:
            return Response(
                {'error': 'No active Paystack configuration found. '
                          'Please configure in Settings → Payment Gateways.'},
                status=400,
            )
        link = PaystackService.create_payment_link(invoice, config)
        return Response(PaymentLinkSerializer(link).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([WebhookRateThrottle])
def paystack_webhook(request):
    """
    POST /api/v1/payments/webhook/paystack/

    Receives Paystack webhook events.

    Security controls applied:
      1. IP-based rate throttling (WebhookRateThrottle: 300/min).
         We return HTTP 200 even when throttled — returning 429 causes
         Paystack to retry aggressively, amplifying the attack.
      2. HMAC-SHA512 signature verification using the org's webhook_secret.
         If no secret is configured the event is accepted but logged as a
         warning — operators must add the secret in Settings → Payment Gateways.
      3. We always return HTTP 200 for invalid/unverified requests to avoid
         disclosing validation logic (Paystack retries on non-2xx; 200 stops it).

    Paystack signature docs:
    https://paystack.com/docs/payments/webhooks/#verify-event-origin
    """
    received_sig = request.META.get(_PAYSTACK_SIG_HEADER, "").strip()

    if not received_sig:
        # No signature → not a Paystack request; log and silently drop.
        logger.warning(
            "Paystack webhook received without X-Paystack-Signature header "
            "from IP %s — dropping",
            request.META.get("REMOTE_ADDR", "unknown"),
        )
        # Return 200 to prevent retry floods from misconfigured senders.
        return Response({"status": "ok"})

    # Look up the first active Paystack config to retrieve the webhook secret.
    # In a multi-org setup you may need to parse the event reference first;
    # for now we use the platform-level first active config.
    config = (
        PaymentGatewayConfig.objects
        .filter(provider=PaymentGatewayConfig.PAYSTACK, is_active=True)
        .first()
    )

    if config and config.webhook_secret:
        # Read raw body for HMAC computation — request.data is already parsed
        # by DRF so we must access request.body (always available before response).
        raw_body = request.body  # bytes
        if not _verify_paystack_signature(raw_body, config.webhook_secret, received_sig):
            logger.warning(
                "Paystack webhook HMAC mismatch from IP %s — possible spoofed event; "
                "dropping silently",
                request.META.get("REMOTE_ADDR", "unknown"),
            )
            return Response({"status": "ok"})
        logger.debug("Paystack webhook signature verified OK")
    else:
        # No secret configured — accept but warn loudly.
        logger.warning(
            "Paystack webhook received but webhook_secret is not set for the active "
            "Paystack gateway config. Event accepted without verification. "
            "Set webhook_secret in Settings → Payment Gateways to enable verification."
        )

    # ── Dispatch event ────────────────────────────────────────────────────────
    event = request.data.get("event", "")
    data = request.data.get("data", {})
    logger.info("Paystack webhook event received: %s", event)

    # TODO: dispatch to domain handlers
    # e.g. if event == "charge.success": handle_charge_success(data)

    return Response({"status": "received"})
