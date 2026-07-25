from django.db import models
from apps.core.models import TenantAwareModel, MoneyField
from apps.suppliers.models import Supplier
from apps.authentication.models import User


class BillFolder(TenantAwareModel):
    """
    A named folder/group for organising bills.
    Supports unlimited nesting (parent → children) for hierarchical organisation.
    Example: "2026 Q1" → "January" → individual bills
    """
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    folder_date = models.DateField(null=True, blank=True, help_text="Date for this folder (optional)")
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


class Bill(TenantAwareModel):
    DRAFT = 'draft'; RECEIVED = 'received'; APPROVED = 'approved'
    PAID = 'paid'; PARTIALLY_PAID = 'partially_paid'; OVERDUE = 'overdue'; VOIDED = 'voided'
    STATUS_CHOICES = [(s, s) for s in [DRAFT, RECEIVED, APPROVED, PAID, PARTIALLY_PAID, OVERDUE, VOIDED]]

    bill_number = models.CharField(max_length=20, editable=False)
    folder = models.ForeignKey(
        BillFolder, null=True, blank=True, on_delete=models.SET_NULL, related_name='bills'
    )
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='bills')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=DRAFT)
    issue_date = models.DateField()
    due_date = models.DateField()
    reference = models.CharField(max_length=100, blank=True)
    subtotal = MoneyField(default=0)
    tax_amount = MoneyField(default=0)
    total_amount = MoneyField(default=0)
    amount_paid = MoneyField(default=0)
    amount_due = MoneyField(default=0)
    notes = models.TextField(blank=True)
    attachment = models.FileField(upload_to='bill_attachments/', null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='bills_created')
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='bills_approved')

    # GL auto-post tracking
    GL_STATUS = [
        ('pending', 'Pending'), ('posted', 'Posted'),
        ('failed', 'Failed'), ('not_configured', 'Not Configured'),
    ]
    gl_post_status = models.CharField(max_length=20, choices=GL_STATUS, default='pending')
    gl_post_error  = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-created_at']
        unique_together = [('organisation', 'bill_number')]

    def __str__(self):
        return f"{self.bill_number}"

    def save(self, *args, **kwargs):
        if not self.bill_number:
            count = Bill.objects.filter(organisation=self.organisation).count()
            self.bill_number = f"BILL-{count + 1:04d}"
        super().save(*args, **kwargs)


class BillItem(TenantAwareModel):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name='items')
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=15, decimal_places=4, default=1)
    unit_cost = MoneyField()
    line_total = MoneyField(default=0)
    expense_category = models.ForeignKey(
        'expenses.ExpenseCategory', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='bill_items'
    )
    account = models.ForeignKey(
        'accounting.Account', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='bill_items'
    )
    # Capitalisation: when set, this line's VAT-exclusive cost is debited to Fixed
    # Assets (1500) instead of an expense account, and a FixedAsset register record is
    # created on bill approval (Phase 1 — bill-line capitalisation).
    capitalise = models.BooleanField(default=False)
    asset_category = models.CharField(max_length=20, blank=True, default='')
    useful_life_years = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']


class BillPayment(TenantAwareModel):
    CASH = 'cash'; BANK = 'bank_transfer'; CHEQUE = 'cheque'; POS = 'pos'
    METHOD_CHOICES = [(m, m) for m in [CASH, BANK, CHEQUE, POS]]

    bill = models.ForeignKey(Bill, on_delete=models.PROTECT, related_name='payments')
    amount = MoneyField()
    payment_date = models.DateField()
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default=CASH)
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='bill_payments_recorded')

    class Meta:
        ordering = ['-created_at']
