import uuid
from decimal import Decimal
from .models import PaymentGatewayConfig, PaymentLink


class PaystackService:
    @staticmethod
    def create_payment_link(invoice, config):
        """Create a Paystack payment link for an invoice."""
        import secrets
        reference = f"INV-{invoice.invoice_number}-{secrets.token_hex(6).upper()}"
        # In production: call Paystack API to initialize transaction
        # For now: create a mock link using Paystack's standard URL pattern
        amount_kobo = int(invoice.amount_due * 100)  # Paystack uses kobo
        link_url = f"https://paystack.com/pay/{reference}"

        link = PaymentLink.objects.create(
            organisation=invoice.organisation,
            invoice=invoice,
            provider='paystack',
            payment_reference=reference,
            amount=invoice.amount_due,
            currency='NGN',
            link_url=link_url,
        )
        return link

    @staticmethod
    def handle_webhook(payload, config):
        """Handle Paystack webhook event."""
        event = payload.get('event')
        data = payload.get('data', {})
        if event == 'charge.success':
            reference = data.get('reference', '')
            try:
                link = PaymentLink.objects.get(payment_reference=reference)
                link.status = PaymentLink.PAID
                link.gateway_response = data
                from django.utils import timezone
                link.paid_at = timezone.now()
                link.save()
                # Auto-mark invoice as paid
                from apps.sales.services import SaleService
                SaleService.record_payment_from_gateway(link.invoice, link.amount, reference)
                return True
            except PaymentLink.DoesNotExist:
                return False
        return False
