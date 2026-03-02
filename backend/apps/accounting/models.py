from django.db import models
from django.core.exceptions import ValidationError
from apps.core.models import TenantAwareModel, TimeStampedModel, MoneyField
from apps.authentication.models import User


class AccountType(models.TextChoices):
    ASSET = 'asset', 'Asset'
    LIABILITY = 'liability', 'Liability'
    EQUITY = 'equity', 'Equity'
    REVENUE = 'revenue', 'Revenue'
    EXPENSE = 'expense', 'Expense'
    COST_OF_GOODS = 'cogs', 'Cost of Goods Sold'


class Account(TenantAwareModel):
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=200)
    account_type = models.CharField(max_length=20, choices=AccountType.choices)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='children')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)  # system accounts cannot be deleted

    class Meta:
        ordering = ['code']
        unique_together = [('organisation', 'code')]

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def balance(self):
        from django.db.models import Sum
        lines = JournalLine.objects.filter(journal_entry__organisation=self.organisation, account=self, journal_entry__status='posted')
        debits = lines.aggregate(t=Sum('debit'))['t'] or 0
        credits = lines.aggregate(t=Sum('credit'))['t'] or 0
        if self.account_type in [AccountType.ASSET, AccountType.EXPENSE, AccountType.COST_OF_GOODS]:
            return debits - credits
        return credits - debits


class JournalEntry(TenantAwareModel):
    DRAFT = 'draft'; POSTED = 'posted'
    STATUS_CHOICES = [(DRAFT, 'Draft'), (POSTED, 'Posted')]

    reference = models.CharField(max_length=20, editable=False)
    description = models.CharField(max_length=500)
    entry_date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='journal_entries_created')
    posted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='journal_entries_posted')

    class Meta:
        ordering = ['-entry_date', '-created_at']
        unique_together = [('organisation', 'reference')]

    def __str__(self):
        return f"{self.reference} - {self.description}"

    def save(self, *args, **kwargs):
        if not self.reference:
            count = JournalEntry.objects.filter(organisation=self.organisation).count()
            self.reference = f"JE-{count + 1:05d}"
        super().save(*args, **kwargs)

    def clean(self):
        if self.pk:
            lines = self.lines.all()
            total_debit = sum(l.debit for l in lines)
            total_credit = sum(l.credit for l in lines)
            if total_debit != total_credit:
                raise ValidationError("Journal entry is not balanced: debits must equal credits")


class JournalLine(TimeStampedModel):
    journal_entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name='lines')
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='journal_lines')
    debit = MoneyField(default=0)
    credit = MoneyField(default=0)
    description = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['created_at']

    def clean(self):
        from decimal import Decimal
        if self.debit > 0 and self.credit > 0:
            raise ValidationError("A journal line cannot have both debit and credit")
        if self.debit == 0 and self.credit == 0:
            raise ValidationError("A journal line must have either a debit or credit amount")


class FixedAsset(TenantAwareModel):
    LAND = 'land'; BUILDING = 'building'; VEHICLE = 'vehicle'
    EQUIPMENT = 'equipment'; FURNITURE = 'furniture'; OTHER = 'other'
    CATEGORY_CHOICES = [(c, c) for c in [LAND, BUILDING, VEHICLE, EQUIPMENT, FURNITURE, OTHER]]

    SL = 'straight_line'; RB = 'reducing_balance'
    DEPRECIATION_CHOICES = [(SL, 'Straight Line'), (RB, 'Reducing Balance')]

    name = models.CharField(max_length=200)
    asset_code = models.CharField(max_length=20)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=OTHER)
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL)
    purchase_date = models.DateField()
    purchase_cost = MoneyField()
    depreciation_method = models.CharField(max_length=20, choices=DEPRECIATION_CHOICES, default=SL)
    useful_life_years = models.PositiveIntegerField(default=5)
    residual_value = MoneyField(default=0)
    disposal_date = models.DateField(null=True, blank=True)
    disposal_amount = MoneyField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-purchase_date']
        unique_together = [('organisation', 'asset_code')]

    def __str__(self):
        return f"{self.asset_code} - {self.name}"

    @property
    def annual_depreciation(self):
        from decimal import Decimal
        if self.useful_life_years <= 0:
            return Decimal('0')
        if self.depreciation_method == self.SL:
            depreciable = self.purchase_cost - self.residual_value
            return max(Decimal('0'), depreciable) / self.useful_life_years
        # Reducing balance: current NBV × (1 / useful_life)
        current_nbv = self.net_book_value
        depreciable_remaining = current_nbv - self.residual_value
        if depreciable_remaining <= Decimal('0'):
            return Decimal('0')
        return depreciable_remaining * (Decimal('1') / self.useful_life_years)

    @property
    def accumulated_depreciation(self):
        from django.db.models import Sum
        return self.depreciation_entries.aggregate(t=Sum('depreciation_amount'))['t'] or 0

    @property
    def net_book_value(self):
        return self.purchase_cost - self.accumulated_depreciation


class DepreciationEntry(TenantAwareModel):
    asset = models.ForeignKey(FixedAsset, on_delete=models.CASCADE, related_name='depreciation_entries')
    period_year = models.PositiveIntegerField()
    period_month = models.PositiveIntegerField()
    depreciation_amount = MoneyField()
    accumulated_to_date = MoneyField()
    net_book_value = MoneyField()

    class Meta:
        ordering = ['period_year', 'period_month']
        unique_together = [('asset', 'period_year', 'period_month')]
