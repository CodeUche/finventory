from django.db import models
from apps.core.models import TenantAwareModel, MoneyField
from apps.suppliers.models import Supplier
from apps.authentication.models import User


class Bill(TenantAwareModel):
    DRAFT = 'draft'; RECEIVED = 'received'; APPROVED = 'approved'
    PAID = 'paid'; PARTIALLY_PAID = 'partially_paid'; OVERDUE = 'overdue'; VOIDED = 'voided'
    STATUS_CHOICES = [(s, s) for s in [DRAFT, RECEIVED, APPROVED, PAID, PARTIALLY_PAID, OVERDUE, VOIDED]]

    bill_number = models.CharField(max_length=20, editable=False)
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
