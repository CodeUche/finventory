from django.db import models
from apps.core.models import TenantAwareModel, MoneyField
from apps.customers.models import Customer
from apps.inventory.models import Warehouse, Product
from apps.authentication.models import User


class Quote(TenantAwareModel):
    DRAFT = 'draft'; SENT = 'sent'; ACCEPTED = 'accepted'
    REJECTED = 'rejected'; EXPIRED = 'expired'; CONVERTED = 'converted'
    STATUS_CHOICES = [(s, s) for s in [DRAFT, SENT, ACCEPTED, REJECTED, EXPIRED, CONVERTED]]

    quote_number = models.CharField(max_length=20, editable=False)
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name='quotes')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='quotes')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    issue_date = models.DateField()
    valid_until = models.DateField()
    subtotal = MoneyField(default=0)
    discount_amount = MoneyField(default=0)
    tax_amount = MoneyField(default=0)
    total_amount = MoneyField(default=0)
    notes = models.TextField(blank=True)
    terms = models.TextField(blank=True)
    converted_invoice = models.OneToOneField('sales.Invoice', null=True, blank=True, on_delete=models.SET_NULL, related_name='quote')
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='quotes_created')

    class Meta:
        ordering = ['-created_at']
        # Live rows only — see Bill. A deleted quote used to hold its number
        # permanently, so the next quote could not reuse it.
        constraints = [
            models.UniqueConstraint(
                fields=['organisation', 'quote_number'],
                condition=models.Q(is_deleted=False),
                name='uniq_quote_org_quote_number',
            ),
        ]

    def __str__(self):
        return f"{self.quote_number}"

    def save(self, *args, **kwargs):
        if not self.quote_number:
            last = Quote.objects.filter(organisation=self.organisation).order_by('-created_at').first()
            n = 1
            if last and last.quote_number:
                try:
                    n = int(last.quote_number.split('-')[1]) + 1
                except (IndexError, ValueError):
                    n = Quote.objects.filter(organisation=self.organisation).count() + 1
            self.quote_number = f"QT-{n:04d}"
        super().save(*args, **kwargs)


class QuoteItem(TenantAwareModel):
    quote = models.ForeignKey(Quote, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    unit_price = MoneyField()
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    line_total = MoneyField(default=0)

    class Meta:
        ordering = ['created_at']

    def compute_total(self):
        from decimal import Decimal
        subtotal = self.quantity * self.unit_price
        discount = subtotal * (self.discount_percent / Decimal('100'))
        return subtotal - discount
