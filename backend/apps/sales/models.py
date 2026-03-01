"""
Sales models: Invoice, SaleItem, Payment.

Architecture:
    - Invoice is the central document. Each invoice has line items (SaleItem).
    - Payments are linked to invoices (partial payments supported).
    - Payment method tracking enables cash-flow analysis.
    - Tax amounts are stored denormalised for historical accuracy
      (tax rates can change; stored amounts reflect the rate at time of sale).
"""

from django.conf import settings
from django.db import models

from apps.core.models import MoneyField, TenantAwareModel
from apps.core.utils import generate_reference


class Invoice(TenantAwareModel):
    """
    Sales invoice / POS receipt.

    A single invoice can have multiple line items, partial payments,
    and different payment methods.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"
        PAID = "paid", "Paid"
        PARTIALLY_PAID = "partially_paid", "Partially Paid"
        OVERDUE = "overdue", "Overdue"
        VOIDED = "voided", "Voided"
        CREDIT = "credit", "Credit"   # Sold on credit

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        POS = "pos", "POS Terminal"
        CHEQUE = "cheque", "Cheque"
        CREDIT = "credit", "Credit"
        MIXED = "mixed", "Mixed"

    invoice_number = models.CharField(max_length=50, unique=True, db_index=True)
    customer = models.ForeignKey(
        "customers.Customer",
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    payment_method = models.CharField(
        max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )
    issue_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.PROTECT,
        related_name="invoices",
    )

    # Financials (all denormalised from line items for performance)
    subtotal = MoneyField()
    discount_amount = MoneyField()
    tax_amount = MoneyField()
    total_amount = MoneyField()
    amount_paid = MoneyField()
    amount_due = MoneyField()

    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invoices",
    )

    class Meta(TenantAwareModel.Meta):
        indexes = [
            models.Index(fields=["organisation", "status", "issue_date"]),
            models.Index(fields=["customer", "status"]),
        ]

    def __str__(self):
        return self.invoice_number

    @classmethod
    def generate_number(cls, organisation):
        """Generate sequential invoice number per organisation."""
        prefix = "INV"
        count = cls.objects.filter(organisation=organisation).count() + 1
        return f"{prefix}-{count:06d}"


class SaleItem(TenantAwareModel):
    """One line on an invoice."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "inventory.Product", on_delete=models.PROTECT, related_name="sale_items"
    )
    batch = models.ForeignKey(
        "inventory.Batch", null=True, blank=True, on_delete=models.SET_NULL
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = MoneyField()
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = MoneyField()
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_amount = MoneyField()
    line_total = MoneyField(help_text="After discount and tax")
    cost_of_goods = MoneyField(help_text="Cost at time of sale for COGS tracking")

    class Meta(TenantAwareModel.Meta):
        pass

    def __str__(self):
        return f"{self.product.sku} × {self.quantity}"


class SalePayment(TenantAwareModel):
    """A payment against an invoice (supports partial/installment payments)."""

    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        POS = "pos", "POS"
        CHEQUE = "cheque", "Cheque"
        CREDIT_APPLIED = "credit_applied", "Credit Applied"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    amount = MoneyField()
    method = models.CharField(max_length=20, choices=Method.choices)
    reference = models.CharField(max_length=100, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_payments",
    )
    notes = models.TextField(blank=True)

    class Meta(TenantAwareModel.Meta):
        pass


class RecurringInvoice(TenantAwareModel):
    DAILY = 'daily'; WEEKLY = 'weekly'; MONTHLY = 'monthly'; QUARTERLY = 'quarterly'; ANNUAL = 'annual'
    FREQ_CHOICES = [(f, f) for f in [DAILY, WEEKLY, MONTHLY, QUARTERLY, ANNUAL]]

    template_name = models.CharField(max_length=200)
    customer = models.ForeignKey('customers.Customer', null=True, blank=True, on_delete=models.SET_NULL)
    warehouse = models.ForeignKey('inventory.Warehouse', on_delete=models.PROTECT)
    frequency = models.CharField(max_length=20, choices=FREQ_CHOICES, default=MONTHLY)
    interval = models.PositiveIntegerField(default=1)
    next_run_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    max_occurrences = models.PositiveIntegerField(null=True, blank=True)
    occurrences_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    items = models.JSONField(default=list)  # [{product_id, quantity, unit_price, discount_percent}]
    notes = models.TextField(blank=True)
    payment_method = models.CharField(max_length=30, default='credit')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='recurring_invoices')

    class Meta:
        ordering = ['next_run_date']

    def __str__(self):
        return self.template_name


class RecurringInvoiceLog(TenantAwareModel):
    SUCCESS = 'success'; FAILED = 'failed'
    STATUS_CHOICES = [(s, s) for s in [SUCCESS, FAILED]]

    recurring_invoice = models.ForeignKey(RecurringInvoice, on_delete=models.CASCADE, related_name='logs')
    invoice = models.ForeignKey(Invoice, null=True, blank=True, on_delete=models.SET_NULL)
    generated_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-generated_at']
