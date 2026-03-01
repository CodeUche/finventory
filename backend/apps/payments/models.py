from django.db import models
from apps.core.models import TenantAwareModel, MoneyField
from apps.sales.models import Invoice


class PaymentGatewayConfig(TenantAwareModel):
    PAYSTACK = 'paystack'; FLUTTERWAVE = 'flutterwave'
    PROVIDER_CHOICES = [(p, p) for p in [PAYSTACK, FLUTTERWAVE]]

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    public_key = models.CharField(max_length=200, blank=True)
    secret_key = models.CharField(max_length=200, blank=True)  # In production: encrypt this
    is_active = models.BooleanField(default=False)
    webhook_secret = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = [('organisation', 'provider')]


class PaymentLink(TenantAwareModel):
    PENDING = 'pending'; PAID = 'paid'; FAILED = 'failed'; CANCELLED = 'cancelled'
    STATUS_CHOICES = [(s, s) for s in [PENDING, PAID, FAILED, CANCELLED]]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payment_links')
    provider = models.CharField(max_length=20)
    payment_reference = models.CharField(max_length=200, unique=True)
    amount = MoneyField()
    currency = models.CharField(max_length=10, default='NGN')
    link_url = models.URLField(max_length=500)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    paid_at = models.DateTimeField(null=True, blank=True)
    gateway_response = models.JSONField(default=dict)

    class Meta:
        ordering = ['-created_at']
