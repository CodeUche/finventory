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


class Location(TenantAwareModel):
    """
    A sales location / branch / store where transactions happen.

    Distinct from Warehouse (storage only). Locations are where sales are
    recorded — e.g. Main Branch, Victoria Island Showroom, Online Store.
    """

    name = models.CharField(max_length=200)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_locations",
    )
    is_active = models.BooleanField(default=True)

    class Meta(TenantAwareModel.Meta):
        unique_together = [["organisation", "name"]]

    def __str__(self):
        return self.name


class InvoiceFolder(TenantAwareModel):
    """
    A named folder for organising sales invoices.
    Supports unlimited nesting for hierarchical organisation.
    Example: "2026" → "Q1" → "January Sales"
    """
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    folder_date = models.DateField(null=True, blank=True)
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='children'
    )

    class Meta(TenantAwareModel.Meta):
        ordering = ['-folder_date', 'name']

    def __str__(self):
        return self.name

    def get_ancestors(self):
        ancestors = []
        current = self.parent
        while current:
            ancestors.insert(0, {'id': str(current.id), 'name': current.name})
            current = current.parent
        return ancestors


class Invoice(TenantAwareModel):
    """
    Sales invoice / POS receipt.

    A single invoice can have multiple line items, partial payments,
    and different payment methods.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PROFORMA = "proforma", "Proforma"   # Estimate / pro-forma invoice
        CONFIRMED = "confirmed", "Confirmed"
        PAID = "paid", "Paid"
        PARTIALLY_PAID = "partially_paid", "Partially Paid"
        OVERDUE = "overdue", "Overdue"
        VOIDED = "voided", "Voided"
        CREDIT = "credit", "Credit"   # Sold on credit
        RETURNED = "returned", "Returned"          # All items fully returned via credit note(s)

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        POS = "pos", "POS Terminal"
        CHEQUE = "cheque", "Cheque"
        CREDIT = "credit", "Credit"
        MIXED = "mixed", "Mixed"

    invoice_number = models.CharField(max_length=50, unique=True, db_index=True)
    folder = models.ForeignKey(
        InvoiceFolder, null=True, blank=True, on_delete=models.SET_NULL, related_name='invoices'
    )
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
    location = models.ForeignKey(
        Location,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="invoices",
    )

    # Financials (all denormalised from line items for performance)
    subtotal = MoneyField()
    discount_amount = MoneyField()
    tax_amount = MoneyField()
    # Optional delivery/shipping charge — folded into total_amount and, for GL
    # purposes, into the revenue credit line of post_sale_journal (not split out
    # to a dedicated shipping-income account yet).
    shipping_amount = MoneyField(default=0)
    total_amount = MoneyField()
    credit_applied = MoneyField(default=0)  # Store credit redeemed on this invoice
    amount_paid = MoneyField()
    amount_due = MoneyField()

    notes = models.TextField(blank=True)
    sold_by = models.CharField(max_length=200, blank=True, db_index=True)

    # ── FIRS e-invoicing fields ───────────────────────────────────────────────
    # All fields are nullable / blank so existing invoices are unaffected.
    # Populated only when the organisation has an active FirsConfig (is_enrolled=True).
    firs_status = models.CharField(
        max_length=30, default="not_enrolled", db_index=True,
        help_text="not_enrolled | pending | submitted | cleared | failed | bypassed",
    )
    firs_irn = models.CharField(
        max_length=200, blank=True,
        help_text="FIRS Invoice Reference Number — assigned after clearance.",
    )
    firs_invoice_number = models.CharField(
        max_length=200, blank=True,
        help_text="FIRS-assigned invoice number (different from internal invoice_number).",
    )
    firs_csid = models.CharField(
        max_length=500, blank=True,
        help_text="Cryptographic Stamp Identifier from DigiTax.",
    )
    firs_transaction_type = models.CharField(
        max_length=3, blank=True,
        help_text="B2B | B2G | B2C — resolved at submission time.",
    )
    firs_qr_code = models.TextField(
        blank=True,
        help_text="Base64-encoded QR code PNG for embedding in invoice PDF.",
    )
    tax_point_date = models.DateField(
        null=True, blank=True,
        help_text="Date VAT becomes legally due. Defaults to issue_date if not set.",
    )
    delivery_start = models.DateField(null=True, blank=True)
    delivery_end = models.DateField(null=True, blank=True)
    payment_terms_text = models.CharField(
        max_length=500, blank=True,
        help_text="Free-text payment terms sent to FIRS (e.g. 'Net 30').",
    )
    transmitted_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Timestamp when invoice was transmitted to FIRS for clearance.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_invoices",
    )

    # ── Deferred fulfillment ───────────────────────────────────────────────
    # A "manual" invoice can be billed/paid today while stock deduction +
    # GL posting are deferred until the goods/services are actually
    # fulfilled. Status (Invoice.Status) still reflects the customer-facing
    # billing state (confirmed/paid/credit etc.) as normal — these two
    # fields track fulfillment independently.
    is_deferred = models.BooleanField(
        default=False,
        help_text="True if stock deduction + GL posting were deferred at creation time.",
    )
    fulfilled_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When stock/GL were posted for a deferred invoice. Null = not yet fulfilled.",
    )

    # GL auto-post tracking
    GL_STATUS = [
        ('pending', 'Pending'), ('posted', 'Posted'),
        ('failed', 'Failed'), ('not_configured', 'Not Configured'),
    ]
    gl_post_status = models.CharField(max_length=20, choices=GL_STATUS, default='pending')
    gl_post_error  = models.TextField(blank=True, default='')

    class Meta(TenantAwareModel.Meta):
        indexes = [
            models.Index(fields=["organisation", "status", "issue_date"]),
            models.Index(fields=["customer", "status"]),
        ]

    def __str__(self):
        return self.invoice_number

    @classmethod
    def generate_number(cls, organisation):
        """
        Generate a sequential invoice number per organisation.

        Uses MAX(invoice_number) scan within the org to find the next sequence
        value, which is safe against concurrent cross-org requests (different
        org prefixes never collide because each org uses its own 4-char hex
        prefix derived from its UUID).
        """
        from django.db.models import Max
        # 4-char hex prefix from org UUID — unique per org, collision-proof
        org_prefix = str(organisation.id).replace('-', '')[:4].upper()
        prefix = f"INV-{org_prefix}"
        # Use all_objects so voided/deleted invoices don't reset the counter
        last = cls.all_objects.filter(
            organisation=organisation,
            invoice_number__startswith=prefix,
        ).aggregate(last=Max('invoice_number'))['last']
        if last:
            try:
                seq = int(last.split('-')[-1]) + 1
            except (ValueError, IndexError):
                seq = cls.all_objects.filter(organisation=organisation).count() + 1
        else:
            seq = 1
        return f"{prefix}-{seq:06d}"


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
    quantity_returned = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Cumulative quantity returned so far for this line item"
    )
    unit_price = MoneyField()
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = MoneyField()
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_amount = MoneyField()
    line_total = MoneyField(help_text="After discount and tax")
    cost_of_goods = MoneyField(help_text="Cost at time of sale for COGS tracking")

    # Chosen modifier options, snapshotted at sale time — see POSOrderItem.
    modifiers = models.JSONField(default=list, blank=True)

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
    # Nullable: a payment confirmed by a gateway webhook or a storefront order
    # has no signed-in user behind it. Staff-recorded payments always set it.
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name="received_payments",
    )
    # Which till shift took this money. Set when a payment is recorded while the
    # cashier has a session open, so the end-of-day count is an exact figure
    # rather than a guess from timestamps. Gateway and storefront payments have
    # no session — correctly, since they never touch the drawer.
    till_session = models.ForeignKey(
        "pos.TillSession", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="payments",
    )
    notes = models.TextField(blank=True)

    class Meta(TenantAwareModel.Meta):
        pass


class RecurringInvoice(TenantAwareModel):
    DAILY = 'daily'; WEEKLY = 'weekly'; MONTHLY = 'monthly'; QUARTERLY = 'quarterly'; ANNUAL = 'annual'
    FREQ_CHOICES = [(f, f) for f in [DAILY, WEEKLY, MONTHLY, QUARTERLY, ANNUAL]]

    template_name = models.CharField(max_length=200)
    customer = models.ForeignKey('customers.Customer', null=True, blank=True, on_delete=models.SET_NULL)
    custom_customer_name = models.CharField(max_length=255, blank=True, help_text="Free-text customer/vendor name when not in the customer list")
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


class SaleReturn(TenantAwareModel):
    """
    A credit note / sales return against an original invoice.

    Restocks inventory and creates a credit for the customer.
    """

    class Reason(models.TextChoices):
        DEFECTIVE = "defective", "Defective / Damaged"
        WRONG_ITEM = "wrong_item", "Wrong Item Delivered"
        CUSTOMER_CHANGE = "customer_change", "Customer Changed Mind"
        OVERCHARGE = "overcharge", "Overcharge / Price Error"
        OTHER = "other", "Other"

    return_number = models.CharField(max_length=50, unique=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="returns")
    reason = models.CharField(max_length=30, choices=Reason.choices, default=Reason.OTHER)
    notes = models.TextField(blank=True)
    return_date = models.DateField()
    total_refund = MoneyField(default=0)
    restocked = models.BooleanField(default=True, help_text="Whether items were physically returned to stock")
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="processed_returns"
    )

    class Meta(TenantAwareModel.Meta):
        ordering = ["-return_date"]

    def __str__(self):
        return self.return_number

    @classmethod
    def generate_number(cls, organisation):
        from django.db.models import Max
        org_prefix = str(organisation.id).replace('-', '')[:4].upper()
        prefix = f"RTN-{org_prefix}"
        last = cls.all_objects.filter(
            organisation=organisation, return_number__startswith=prefix
        ).aggregate(last=Max('return_number'))['last']
        if last:
            try:
                seq = int(last.split('-')[-1]) + 1
            except (ValueError, IndexError):
                seq = cls.all_objects.filter(organisation=organisation).count() + 1
        else:
            seq = 1
        return f"{prefix}-{seq:06d}"


class SaleReturnItem(TenantAwareModel):
    """One line item in a sales return / credit note."""

    sale_return = models.ForeignKey(SaleReturn, on_delete=models.CASCADE, related_name="items")
    original_item = models.ForeignKey(SaleItem, on_delete=models.PROTECT, related_name="return_items")
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    quantity_returned = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = MoneyField()
    refund_amount = MoneyField()          # VAT-inclusive refund to the customer
    tax_refund = MoneyField(default=0)    # VAT portion of refund_amount (reverses output VAT)

    class Meta(TenantAwareModel.Meta):
        pass

    def __str__(self):
        return f"{self.product.sku} × {self.quantity_returned} (return)"
