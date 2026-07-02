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
    # Idempotency: uniquely identifies the business event that triggered this entry
    source_type = models.CharField(max_length=40, blank=True, default='')
    source_ref = models.CharField(max_length=100, blank=True, default='')

    class Meta:
        ordering = ['-entry_date', '-created_at']
        unique_together = [('organisation', 'reference')]
        constraints = [
            models.UniqueConstraint(
                fields=['organisation', 'source_type', 'source_ref'],
                condition=models.Q(source_type__gt='', source_ref__gt=''),
                name='unique_journal_source',
            )
        ]

    def __str__(self):
        return f"{self.reference} - {self.description}"

    def save(self, *args, **kwargs):
        if not self.reference:
            import re
            from django.db.models import Max
            last = (
                JournalEntry.all_objects
                .filter(organisation=self.organisation)
                .exclude(reference='')
                .aggregate(m=Max('reference'))['m']
            )
            if last:
                match = re.search(r'(\d+)$', last)
                num = int(match.group(1)) + 1 if match else 1
            else:
                num = 1
            self.reference = f"JE-{num:05d}"
        # Immutability: posted entries cannot be modified (E2 fix)
        if self.pk:
            original = JournalEntry.objects.filter(pk=self.pk).values('status').first()
            if original and original['status'] == 'posted':
                update_fields = kwargs.get('update_fields')
                ALLOWED_FIELDS = {'gl_post_status', 'gl_post_error', 'reconciled_at', 'updated_at'}
                if update_fields:
                    forbidden = set(update_fields) - ALLOWED_FIELDS
                    if forbidden:
                        raise PermissionError(
                            f"Cannot modify posted journal entry: {forbidden}. Use a reversing entry."
                        )
                else:
                    # Full save on a posted entry — only allow if only status itself is being set
                    # (the initial create path). Any subsequent full save is blocked.
                    raise PermissionError(
                        "Cannot overwrite a posted journal entry. Use a reversing entry instead."
                    )
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

    def save(self, *args, **kwargs):
        # Only block modifications (not inserts) on posted entries.
        # _state.adding is True when Django is about to INSERT (new object), False for UPDATE.
        if not self._state.adding and self.journal_entry_id:
            status = JournalEntry.objects.filter(pk=self.journal_entry_id).values_list('status', flat=True).first()
            if status == JournalEntry.POSTED:
                raise PermissionError("Cannot modify a line on a posted journal entry. Use a reversing entry.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.journal_entry_id:
            status = JournalEntry.objects.filter(pk=self.journal_entry_id).values_list('status', flat=True).first()
            if status == JournalEntry.POSTED:
                raise PermissionError("Cannot delete a line from a posted journal entry. Use a reversing entry.")
        super().delete(*args, **kwargs)


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

    @property
    def ordered_entries(self):
        return self.depreciation_entries.order_by('period_year', 'period_month')


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


class FinancialPeriod(TenantAwareModel):
    """A financial month that can be locked to prevent back-dated postings."""
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()
    is_locked = models.BooleanField(default=False)
    locked_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='locked_periods'
    )
    locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-year', '-month']
        unique_together = [('organisation', 'year', 'month')]

    def __str__(self):
        return f"{self.year}-{self.month:02d} ({'locked' if self.is_locked else 'open'})"


class BankReconciliation(TenantAwareModel):
    """A bank reconciliation for a specific account and period."""
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='reconciliations')
    period_start = models.DateField()
    period_end = models.DateField()
    statement_closing_balance = MoneyField()
    book_balance = MoneyField(default=0)
    is_reconciled = models.BooleanField(default=False)
    reconciled_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='reconciliations_done'
    )
    reconciled_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-period_end']
        unique_together = [('organisation', 'account', 'period_start', 'period_end')]

    def __str__(self):
        return f"Recon {self.account.code} {self.period_start}–{self.period_end}"


class BankReconciliationLine(TenantAwareModel):
    """An individual line item in a bank reconciliation (from journal lines or manual entry)."""
    reconciliation = models.ForeignKey(
        BankReconciliation, on_delete=models.CASCADE, related_name='lines'
    )
    journal_line = models.ForeignKey(
        JournalLine, null=True, blank=True, on_delete=models.SET_NULL, related_name='recon_lines'
    )
    description = models.CharField(max_length=500)
    transaction_date = models.DateField()
    amount = MoneyField()
    is_cleared = models.BooleanField(default=False)
    reference = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['transaction_date']


class AIReconMatch(TenantAwareModel):
    """AI-proposed match between a bank statement line and a book journal line."""
    MATCH_TYPES = [
        ('exact', 'Exact Match'),
        ('fuzzy', 'Fuzzy Match'),
        ('uncertain', 'Uncertain'),
    ]
    STATUS = [
        ('proposed', 'Proposed'),
        ('confirmed', 'Confirmed'),
        ('rejected', 'Rejected'),
    ]
    reconciliation = models.ForeignKey(BankReconciliation, on_delete=models.CASCADE, related_name='ai_matches')
    bank_line = models.ForeignKey(BankReconciliationLine, on_delete=models.CASCADE, related_name='ai_matches')
    book_line = models.ForeignKey(JournalLine, null=True, blank=True, on_delete=models.SET_NULL, related_name='ai_matches')
    confidence = models.FloatField(default=0.0)  # 0.0 - 1.0
    match_type = models.CharField(max_length=20, choices=MATCH_TYPES, default='uncertain')
    status = models.CharField(max_length=20, choices=STATUS, default='proposed')
    ai_reasoning = models.TextField(blank=True)  # AI explanation
    ai_advice = models.TextField(blank=True)  # For unmatched lines — advice on how to fix
    matched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-confidence']


class AccountMapping(TenantAwareModel):
    """
    Maps semantic GL roles to the org's actual Account records.
    Created automatically on org setup; user can remap via Settings.
    """

    # Revenue & COGS
    revenue_account         = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_revenue')
    cogs_account            = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_cogs')
    # Assets
    inventory_account       = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_inventory')
    accounts_receivable     = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_ar')
    cash_account            = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_cash')
    bank_account            = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_bank')
    # Liabilities
    accounts_payable        = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_ap')
    vat_output_account      = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_vat_output')
    vat_input_account       = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_vat_input')
    paye_account            = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_paye')
    pension_account         = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_pension')
    wht_account             = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_wht')
    # Expenses
    salary_expense_account  = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_salary')
    general_expense_account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_general_expense')
    bank_charges_account    = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_bank_charges')

    class Meta:
        verbose_name = 'Account Mapping'

    def clean(self):
        """Validate that all FK accounts belong to the same organisation."""
        fk_fields = [
            'revenue_account', 'cogs_account', 'inventory_account', 'accounts_receivable',
            'cash_account', 'bank_account', 'accounts_payable', 'vat_output_account',
            'vat_input_account', 'paye_account', 'pension_account', 'wht_account',
            'salary_expense_account', 'general_expense_account', 'bank_charges_account',
        ]
        for field_name in fk_fields:
            account = getattr(self, field_name, None)
            if account is not None and account.organisation_id != self.organisation_id:
                raise ValidationError(
                    f"Account '{account}' for role '{field_name}' does not belong to this organisation."
                )
