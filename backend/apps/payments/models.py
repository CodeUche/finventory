from django.db import models
from django.utils import timezone

from apps.core.models import MoneyField, TenantAwareModel
from apps.sales.models import Invoice


class PaymentGatewayConfig(TenantAwareModel):
    """A merchant's own gateway credentials.

    Audity never holds merchant funds — these keys belong to the merchant and
    settle into the merchant's own bank account, which is what keeps Audity a
    software vendor rather than a payment aggregator.
    """

    PAYSTACK = 'paystack'
    FLUTTERWAVE = 'flutterwave'
    MONNIFY = 'monnify'
    PROVIDER_CHOICES = [
        (PAYSTACK, 'Paystack'),
        (MONNIFY, 'Monnify / Moniepoint'),
        (FLUTTERWAVE, 'Flutterwave'),
    ]

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    public_key = models.CharField(
        max_length=200, blank=True,
        help_text="Public/API key. For Monnify this is the API key.",
    )
    secret_key = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=False)
    webhook_secret = models.CharField(max_length=200, blank=True)

    # Monnify requires a contract code alongside the key pair.
    contract_code = models.CharField(max_length=100, blank=True)
    # Bank the one-time account is issued against — a Paystack slug
    # ("wema-bank") or a Monnify bank code ("035").
    preferred_bank = models.CharField(max_length=50, blank=True)
    use_sandbox = models.BooleanField(default=False)

    # Which collection methods this merchant offers at checkout.
    allow_card = models.BooleanField(default=True)
    allow_transfer = models.BooleanField(default=True)
    # How long a one-time account stays valid before it is abandoned.
    virtual_account_minutes = models.PositiveSmallIntegerField(default=30)

    class Meta:
        unique_together = [('organisation', 'provider')]

    def __str__(self):
        return f"{self.get_provider_display()} ({'active' if self.is_active else 'inactive'})"


class PaymentLink(TenantAwareModel):
    """A hosted checkout session — card, USSD or the provider's own page."""

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


class VirtualAccount(TenantAwareModel):
    """A one-time account number issued for a single sale.

    The payer transfers from any bank and the provider notifies us within
    seconds, so a doctored transfer screenshot proves nothing — the money either
    arrived against this account or it did not.
    """

    PENDING = 'pending'; PAID = 'paid'; EXPIRED = 'expired'; CANCELLED = 'cancelled'
    STATUS_CHOICES = [(s, s) for s in [PENDING, PAID, EXPIRED, CANCELLED]]

    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name='virtual_accounts',
    )
    provider = models.CharField(max_length=20)
    reference = models.CharField(max_length=200, unique=True)
    account_number = models.CharField(max_length=20, db_index=True)
    bank_name = models.CharField(max_length=120, blank=True)
    account_name = models.CharField(max_length=200, blank=True)
    amount = MoneyField()
    currency = models.CharField(max_length=10, default='NGN')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    expires_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    provider_reference = models.CharField(max_length=200, blank=True)
    gateway_response = models.JSONField(default=dict)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['organisation', 'status'])]

    @property
    def is_expired(self) -> bool:
        return bool(
            self.status == self.PENDING
            and self.expires_at
            and timezone.now() > self.expires_at
        )

    def __str__(self):
        return f"{self.account_number} → {self.invoice.invoice_number}"


class MerchantBankAccount(TenantAwareModel):
    """A bank account the merchant owns and wants customers to pay into.

    This is the option for merchants with no payment provider at all — the
    majority of small Nigerian traders, who simply tell a customer "send it to
    my GTB account". Money goes straight to the merchant; Audity never touches
    it and never sees a webhook, so a transfer here is confirmed by a person,
    not automatically. That trade-off is stated plainly at checkout.
    """

    bank_name = models.CharField(max_length=120)
    account_number = models.CharField(max_length=20)
    account_name = models.CharField(max_length=200)
    is_default = models.BooleanField(
        default=False, help_text="Offered first at checkout and printed on invoices.",
    )
    is_active = models.BooleanField(default=True)
    show_on_invoice = models.BooleanField(default=True)
    show_on_storefront = models.BooleanField(default=True)
    instructions = models.CharField(
        max_length=300, blank=True,
        help_text="Shown under the account, e.g. 'Use your order number as the narration'.",
    )

    class Meta:
        ordering = ['-is_default', 'bank_name']
        unique_together = [('organisation', 'bank_name', 'account_number')]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Exactly one default per organisation.
        if self.is_default:
            MerchantBankAccount.objects.filter(
                organisation=self.organisation, is_default=True,
            ).exclude(pk=self.pk).update(is_default=False)

    def __str__(self):
        return f"{self.bank_name} — {self.account_number}"


class BankTransferClaim(TenantAwareModel):
    """A customer says they have transferred into the merchant's own account.

    Nothing is posted until a member of staff confirms it against their bank —
    the whole point of the one-time account number is to avoid this manual step,
    but a merchant without a provider still needs a way to take the order.
    """

    AWAITING = 'awaiting'; CONFIRMED = 'confirmed'; REJECTED = 'rejected'
    STATUS_CHOICES = [
        (AWAITING, 'Awaiting confirmation'),
        (CONFIRMED, 'Confirmed'),
        (REJECTED, 'Rejected'),
    ]

    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name='transfer_claims',
    )
    bank_account = models.ForeignKey(
        MerchantBankAccount, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='claims',
    )
    amount = MoneyField()
    payer_name = models.CharField(max_length=200, blank=True)
    narration = models.CharField(max_length=200, blank=True)
    proof = models.ImageField(upload_to='transfer_proofs/', null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=AWAITING)
    reviewed_by = models.ForeignKey(
        'authentication.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='reviewed_transfer_claims',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['organisation', 'status'])]

    def __str__(self):
        return f"{self.invoice.invoice_number} — {self.get_status_display()}"


class PaymentEventLog(TenantAwareModel):
    """Every webhook we have already acted on.

    Providers resend notifications on any non-2xx reply and sometimes just
    because. Without this table a retry would record the same payment twice,
    which is the worst possible bug in a payments path.
    """

    provider = models.CharField(max_length=20)
    event_id = models.CharField(max_length=200)
    reference = models.CharField(max_length=200, blank=True, db_index=True)
    status = models.CharField(max_length=20, blank=True)
    amount = MoneyField(default=0)
    payload = models.JSONField(default=dict)
    processed_at = models.DateTimeField(auto_now_add=True)
    # Set when the event was accepted but deliberately not acted on (duplicate
    # amount already settled, unknown reference, etc.) — useful for support.
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['-processed_at']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'event_id'], name='unique_payment_event',
            )
        ]

    def __str__(self):
        return f"{self.provider}:{self.event_id}"

# Card terminal settlement lives in its own module for clarity; re-exported so
# Django discovers the models and existing imports keep working.
from .settlement_models import SettlementBatch, SettlementLine  # noqa: E402,F401
