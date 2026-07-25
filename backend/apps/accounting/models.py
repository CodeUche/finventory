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


DEBIT_NORMAL_TYPES = (AccountType.ASSET, AccountType.EXPENSE, AccountType.COST_OF_GOODS)


def normal_balance_for_type(account_type) -> str:
    """Debit-normal for assets/expenses/COGS, credit-normal for the rest."""
    return 'debit' if account_type in DEBIT_NORMAL_TYPES else 'credit'


# ── Account classification taxonomy (client COA spec) ────────────────────────
# Groups are the user-facing "Account Type" headers under two statements. Each
# group maps to one of the six base AccountType values (which drives all
# debit/credit-normal and statement logic) and carries a default sub-type list.
# statement: 'pl' = Profit & Loss, 'bs' = Balance Sheet.
ACCOUNT_GROUP_SPEC = {
    # Profit & Loss
    'Income':                 ('revenue',   'pl', ['Sales Income', 'Other Income']),
    'Cost of Sales':          ('cogs',      'pl', ['Cost Of Production', 'Cost of Distribution', 'Damage & Waste']),
    'Indirect Cost':          ('expense',   'pl', ['Sales & Marketing', 'Distribution Cost', 'Salaries & Wages']),
    'Expenses':               ('expense',   'pl', ['Office Expenses', 'Admin Expenses', 'Finance Expenses',
                                                   'Overhead Expenses', 'Depreciation Expenses', 'Tax Expenses']),
    # Balance Sheet
    'Asset':                  ('asset',     'bs', ['Accum. Depreciation', 'Current Asset', 'Other Asset', 'Fixed Asset',
                                                   'Other Current Asset', 'Inventory', 'Receivables', 'Receivable Retainage']),
    'Cash & Cash Equivalent': ('asset',     'bs', ['Bank', 'Cash', 'Credit Card', 'Loan', 'Mobile Money']),
    'Liabilities':            ('liability', 'bs', ['Short Term Liabilities', 'Long Term Liabilities', 'Other Liabilities',
                                                   'Payables', 'Payable Retainage']),
    'Equity':                 ('equity',    'bs', ['Retained Earnings', "Equity Doesn't Close", 'Equity Get Close',
                                                   'Take-On Suspense/Beginning Balance']),
}

ACCOUNT_GROUP_CHOICES = [(g, g) for g in ACCOUNT_GROUP_SPEC]

# Reverse lookup: base account_type -> default display group (used for backfill/UI).
DEFAULT_GROUP_FOR_TYPE = {
    'revenue': 'Income', 'cogs': 'Cost of Sales', 'expense': 'Expenses',
    'asset': 'Asset', 'liability': 'Liabilities', 'equity': 'Equity',
}


class AccountSubType(TenantAwareModel):
    """User-manageable account sub-types (the 'Add Sub Account Type' screen).

    Each sub-type belongs to a group header (e.g. 'Cash & Cash Equivalent') and
    resolves to one of the six base AccountType values used by all ledger logic.
    Seeded with the client's default taxonomy on org creation; users may add,
    rename, deactivate their own.
    """
    name = models.CharField(max_length=100)
    account_group = models.CharField(max_length=40, choices=ACCOUNT_GROUP_CHOICES)
    base_account_type = models.CharField(max_length=20, choices=AccountType.choices)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)

    class Meta:
        ordering = ['account_group', 'name']
        unique_together = [('organisation', 'account_group', 'name')]

    def __str__(self):
        return f"{self.account_group} · {self.name}"


class Account(TenantAwareModel):
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=200)
    account_type = models.CharField(max_length=20, choices=AccountType.choices)
    # Richer classification (client COA spec). account_type stays the base
    # source-of-truth for ledger math; group + sub_type are presentation/grouping.
    account_group = models.CharField(max_length=40, choices=ACCOUNT_GROUP_CHOICES, blank=True)
    sub_type = models.ForeignKey('AccountSubType', null=True, blank=True, on_delete=models.SET_NULL, related_name='accounts')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='children')
    description = models.TextField(blank=True)
    normal_balance = models.CharField(max_length=6, choices=[('debit', 'Debit'), ('credit', 'Credit')], blank=True)
    is_active = models.BooleanField(default=True)
    # Control accounts (AR/AP/Inventory) accumulate from subledgers; disallow
    # direct manual journal posting to them. Auto-posting is always exempt.
    allow_posting = models.BooleanField(default=True)
    is_control_account = models.BooleanField(default=False)
    # Opening / take-on balance captured at migration into Audity.
    opening_balance = MoneyField(null=True, blank=True)
    opening_balance_date = models.DateField(null=True, blank=True)
    # Supporting document attached to the account (e.g. bank statement, agreement).
    attachment = models.FileField(upload_to='account_attachments/', null=True, blank=True)
    is_system = models.BooleanField(default=False)  # system accounts cannot be deleted

    class Meta:
        ordering = ['code']
        unique_together = [('organisation', 'code')]

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def effective_normal_balance(self) -> str:
        return self.normal_balance or normal_balance_for_type(self.account_type)

    def clean(self):
        # Prevent an account being its own parent / trivial cycles.
        if self.parent_id and self.parent_id == self.pk:
            raise ValidationError("An account cannot be its own parent.")

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
    # Nullable: system/automated postings (depreciation runs, scheduled tasks) have
    # no human author. User-initiated entries always set this.
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name='journal_entries_created')
    posted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='journal_entries_posted')
    # Idempotency: uniquely identifies the business event that triggered this entry
    source_type = models.CharField(max_length=40, blank=True, default='')
    source_ref = models.CharField(max_length=100, blank=True, default='')
    # Workflow approval (manual journals): draft → pending → approved/rejected.
    PENDING = 'pending'; APPROVED = 'approved'; REJECTED = 'rejected'
    APPROVAL_CHOICES = [
        ('none', 'Not Required'), (PENDING, 'Pending Approval'),
        (APPROVED, 'Approved'), (REJECTED, 'Rejected'),
    ]
    approval_status = models.CharField(max_length=10, choices=APPROVAL_CHOICES, default='none')
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='journal_entries_approved')
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_note = models.CharField(max_length=500, blank=True, default='')
    # E-sign / manual document upload supporting the entry.
    attachment = models.FileField(upload_to='journal_attachments/', null=True, blank=True)
    signature = models.TextField(blank=True, default='')  # typed name or data-URI signature
    signed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='journal_entries_signed')
    signed_at = models.DateTimeField(null=True, blank=True)

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
                ALLOWED_FIELDS = {
                    'gl_post_status', 'gl_post_error', 'reconciled_at', 'updated_at',
                    'approval_status', 'approved_by', 'approved_at', 'approval_note',
                    'attachment', 'signature', 'signed_by', 'signed_at', 'posted_by', 'status',
                }
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
    IMMEDIATE = 'immediate'; ZERO = 'zero'; UNITS = 'units'
    DEPRECIATION_CHOICES = [
        (SL, 'Straight Line'), (RB, 'Reducing Balance'),
        (IMMEDIATE, 'Immediate Write-Off'), (ZERO, 'No Depreciation (0%)'),
        (UNITS, 'Units of Production'),
    ]

    # Depreciation convention for the FIRST period an asset is depreciated.
    CONV_FULL = 'full_month'; CONV_PRORATA = 'pro_rata'; CONV_NEW_MONTH = 'new_month'
    CONVENTION_CHOICES = [
        (CONV_FULL, 'Full month'), (CONV_PRORATA, 'Pro-rata (by days)'),
        (CONV_NEW_MONTH, 'New month (start the month after purchase)'),
    ]

    # How the acquisition was funded — drives the credit leg of the acquisition
    # journal (DR 1500 Fixed Assets / CR funding). 'none' means the asset is being
    # brought on via the opening-balance / take-on flow, which posts its own entry,
    # so the acquisition journal is NOT posted here.
    FUND_BANK = 'bank'; FUND_CASH = 'cash'; FUND_PAYABLE = 'payable'
    FUND_EQUITY = 'equity'; FUND_NONE = 'none'
    FUNDING_CHOICES = [
        (FUND_BANK, 'Bank'), (FUND_CASH, 'Cash'), (FUND_PAYABLE, 'Accounts Payable'),
        (FUND_EQUITY, 'Owner / Capital Introduced'), (FUND_NONE, 'Already on books (opening balance)'),
    ]

    # Where the capitalisation originated (audit / double-post guard).
    CAP_DIRECT = 'direct'; CAP_BILL = 'bill'; CAP_OPENING = 'opening_balance'
    CAP_SOURCE_CHOICES = [
        (CAP_DIRECT, 'Direct purchase'), (CAP_BILL, 'Capitalised from bill'),
        (CAP_OPENING, 'Opening balance / take-on'),
    ]

    name = models.CharField(max_length=200)
    asset_code = models.CharField(max_length=20)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=OTHER)
    asset_type = models.ForeignKey(
        'AssetType', null=True, blank=True, on_delete=models.SET_NULL, related_name='assets'
    )
    # Asset master file: serial/barcode for reconciliation, and master/sub linking
    # (a sub-asset — e.g. an add-on — points to its master asset).
    serial_number = models.CharField(max_length=100, blank=True, default='')
    barcode = models.CharField(max_length=100, blank=True, default='')
    master_asset = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='sub_assets'
    )
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL)
    purchase_date = models.DateField()
    purchase_cost = MoneyField()
    depreciation_method = models.CharField(max_length=20, choices=DEPRECIATION_CHOICES, default=SL)
    useful_life_years = models.PositiveIntegerField(default=5)
    residual_value = MoneyField(default=0)
    # Configurable reducing-balance rate (annual %, e.g. 25 for 25%). When null the
    # rate is derived from useful life (1/life). Only used for the RB method.
    reducing_balance_rate = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    depreciation_convention = models.CharField(max_length=12, choices=CONVENTION_CHOICES, default=CONV_FULL)
    # Units-of-production: total expected lifetime output (only used for UNITS method).
    total_units = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    disposal_date = models.DateField(null=True, blank=True)
    disposal_amount = MoneyField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    # Location / cost-centre (for Asset-by-Location reporting and transfers).
    location = models.ForeignKey(
        'inventory.Warehouse', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='fixed_assets',
    )
    cost_centre = models.CharField(max_length=100, blank=True, default='')

    # ── Acquisition posting (Phase 1) ─────────────────────────────────────────
    funding_source = models.CharField(max_length=12, choices=FUNDING_CHOICES, default=FUND_BANK)
    capitalisation_source = models.CharField(max_length=20, choices=CAP_SOURCE_CHOICES, default=CAP_DIRECT)
    # Idempotency stamp for the double-post guard (e.g. 'bill_line:<uuid>').
    source_document_ref = models.CharField(max_length=100, blank=True, default='')
    acquisition_posted = models.BooleanField(default=False)
    acquisition_error = models.CharField(max_length=500, blank=True, default='')

    # ── Tax channel (captured at capitalisation; consumed by the gated CA engine) ──
    # qualifying_cost is the capital-allowance cost base (may differ from purchase_cost
    # once §27(2) VAT/levy exclusions apply); input_tax_* records §27(2) evidence.
    qualifying_cost = MoneyField(null=True, blank=True)
    input_tax_paid = models.BooleanField(default=False)
    input_tax_amount = MoneyField(null=True, blank=True)

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
    # Units consumed in the period (Units-of-Production method only).
    units = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['period_year', 'period_month']
        unique_together = [('asset', 'period_year', 'period_month')]


class AssetType(TenantAwareModel):
    """A class of asset (e.g. 'Motor Vehicles') carrying default depreciation settings
    and GL account mapping. Assets may link to an asset type; the type then supplies
    the book method + depreciation-expense / accumulated-depreciation accounts for the
    ledger posting (reviewer's 'methods linked to asset types' requirement)."""
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=FixedAsset.CATEGORY_CHOICES, default=FixedAsset.OTHER)
    depreciation_method = models.CharField(
        max_length=20, choices=FixedAsset.DEPRECIATION_CHOICES, default=FixedAsset.SL
    )
    useful_life_years = models.PositiveIntegerField(default=5)
    reducing_balance_rate = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    fixed_asset_account = models.ForeignKey(
        Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='asset_type_fa'
    )
    depreciation_expense_account = models.ForeignKey(
        Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='asset_type_dep_exp'
    )
    accumulated_depreciation_account = models.ForeignKey(
        Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='asset_type_acc_dep'
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']
        unique_together = [('organisation', 'code')]

    def __str__(self):
        return f"{self.code} - {self.name}"


class AssetTransfer(TenantAwareModel):
    """Record of a fixed asset moving between locations / cost-centres. A pure
    sub-ledger reclassification — it does NOT change GL cost or accumulated
    depreciation (IFRS: a transfer has no depreciation/valuation effect)."""
    asset = models.ForeignKey(FixedAsset, on_delete=models.CASCADE, related_name='transfers')
    transfer_date = models.DateField()
    from_location = models.ForeignKey(
        'inventory.Warehouse', null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    to_location = models.ForeignKey(
        'inventory.Warehouse', null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    from_cost_centre = models.CharField(max_length=100, blank=True, default='')
    to_cost_centre = models.CharField(max_length=100, blank=True, default='')
    # Asset-type change as a dated transfer (rules for depreciation may change).
    from_asset_type = models.ForeignKey(
        AssetType, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    to_asset_type = models.ForeignKey(
        AssetType, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    reference = models.CharField(max_length=100, blank=True, default='')
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-transfer_date', '-created_at']


class AssetRevaluation(TenantAwareModel):
    """IAS 16 revaluation of a fixed asset. Gated behind the org's
    fixed_asset_revaluation_enabled flag; upward surplus → equity (Revaluation
    Surplus), downward deficit → P&L. Optional; SME default is the cost model."""
    asset = models.ForeignKey(FixedAsset, on_delete=models.CASCADE, related_name='revaluations')
    revaluation_date = models.DateField()
    previous_carrying_amount = MoneyField()
    new_carrying_amount = MoneyField()
    surplus = MoneyField(default=0)  # positive = surplus (equity), negative = deficit (P&L)
    reference = models.CharField(max_length=100, blank=True, default='')
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-revaluation_date', '-created_at']


class FinancialPeriod(TenantAwareModel):
    """A financial month that can be locked to prevent back-dated postings."""
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()
    is_locked = models.BooleanField(default=False)
    locked_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='locked_periods'
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    # Audit-safe unlock: keep the lock evidence AND record who unlocked, when, and why.
    # (Previously unlock() nulled locked_by/locked_at, destroying the audit trail.)
    unlocked_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name='unlocked_periods'
    )
    unlocked_at = models.DateTimeField(null=True, blank=True)
    unlock_reason = models.TextField(blank=True)

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
    nhf_account             = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_nhf')
    wht_account             = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_wht')
    # Expenses
    salary_expense_account  = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_salary')
    general_expense_account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_general_expense')
    bank_charges_account    = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name='mapping_bank_charges')

    class Meta:
        verbose_name = 'Account Mapping'

    def clean(self):
        """Validate each mapped account: same org, active, and a real posting leaf.

        NOTE: control accounts (AR/AP/Inventory/Fixed Assets) legitimately map here and
        are posting-locked (allow_posting=False) for MANUAL journals only — auto-posting
        is exempt — so we deliberately do NOT enforce allow_posting. We DO reject inactive
        accounts and header/summary accounts (accounts that have children), which must
        never be a posting target.
        """
        fk_fields = [
            'revenue_account', 'cogs_account', 'inventory_account', 'accounts_receivable',
            'cash_account', 'bank_account', 'accounts_payable', 'vat_output_account',
            'vat_input_account', 'paye_account', 'pension_account', 'nhf_account', 'wht_account',
            'salary_expense_account', 'general_expense_account', 'bank_charges_account',
        ]
        for field_name in fk_fields:
            account = getattr(self, field_name, None)
            if account is None:
                continue
            if account.organisation_id != self.organisation_id:
                raise ValidationError(
                    f"Account '{account}' for role '{field_name}' does not belong to this organisation."
                )
            if not account.is_active:
                raise ValidationError(
                    f"Account '{account}' for role '{field_name}' is inactive and cannot be mapped."
                )
            if account.children.exists():
                raise ValidationError(
                    f"Account '{account}' for role '{field_name}' is a header/summary account; "
                    f"map a specific posting account instead."
                )
