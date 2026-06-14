"""
Tax Engine Models.

Architecture:
    TaxClass      — Product-level VAT/sales tax rates (e.g., Standard, Zero-rated, Exempt)
    TaxConfig     — Country/org-level configuration for income tax regime
    TaxBracket    — Progressive income tax brackets (configurable per TaxConfig)
    TaxReturn     — Filed/calculated tax return for a period
    TaxEntry      — Line item in a tax return

Design principles:
    - ZERO hardcoded values. All rates live in the database.
    - Country-configurable: Nigeria (FIRS), Ghana (GRA), UK (HMRC) etc.
    - VAT/sales tax (indirect) and income tax (direct) are separated.
    - TaxBracket supports stepped/progressive calculations.
    - Easy to extend: add new TaxConfig rows for new jurisdictions.

Example TaxBracket (Nigeria PIT 2024):
    lower_bound=0         upper_bound=300000   rate=7    min_tax=0
    lower_bound=300000    upper_bound=600000   rate=11   min_tax=21000
    lower_bound=600000    upper_bound=1100000  rate=15   ...
    ...
"""

from decimal import Decimal

from django.db import models
from apps.core.models import MoneyField, TenantAwareModel, TimeStampedModel


class TaxClass(TenantAwareModel):
    """
    Product-level VAT / sales tax rate.

    Assigned to products; rate applied at point of sale.
    Examples:
        Standard Rate (7.5% VAT in Nigeria)
        Zero Rated (0%)
        Exempt
    """

    name = models.CharField(max_length=100)
    rate = models.DecimalField(
        max_digits=5, decimal_places=2,
        help_text="Tax rate as percentage (e.g., 7.5 for 7.5%)"
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(TenantAwareModel.Meta):
        unique_together = [["organisation", "name"]]
        verbose_name_plural = "Tax Classes"

    def __str__(self):
        return f"{self.name} ({self.rate}%)"


class TaxConfig(TenantAwareModel):
    """
    Country/organisation-level tax configuration.

    Separates VAT/GST settings from income tax settings.
    One TaxConfig per jurisdiction per organisation.
    """

    class TaxType(models.TextChoices):
        INCOME = "income", "Income Tax"
        CORPORATE = "corporate", "Corporate Tax"
        VAT = "vat", "VAT / Sales Tax"
        WITHHOLDING = "withholding", "Withholding Tax"
        EXCISE = "excise", "Excise Duty"

    name = models.CharField(max_length=200, help_text="e.g., Nigeria Personal Income Tax 2024")
    tax_type = models.CharField(max_length=20, choices=TaxType.choices)
    country = models.CharField(max_length=2, help_text="ISO 3166-1 alpha-2 country code")
    tax_year = models.PositiveSmallIntegerField(help_text="Applicable tax year")
    is_progressive = models.BooleanField(
        default=True,
        help_text="True = tiered brackets. False = flat rate."
    )
    flat_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Used only if is_progressive=False"
    )
    # Reliefs and allowances
    personal_allowance = MoneyField(
        help_text="Tax-free allowance before bracket calculation begins"
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta(TenantAwareModel.Meta):
        unique_together = [["organisation", "name", "tax_year"]]
        verbose_name = "Tax Configuration"

    def __str__(self):
        return f"{self.name} ({self.tax_year})"


class TaxBracket(TimeStampedModel):
    """
    A single bracket in a progressive tax schedule.

    Brackets must be contiguous and non-overlapping.
    upper_bound=None means "and above" (highest bracket).

    Example (Nigeria PIT):
        lower=0       upper=300000   rate=7%   cumulative_tax_below=0
        lower=300000  upper=600000   rate=11%  cumulative_tax_below=21000
        ...
    """

    config = models.ForeignKey(TaxConfig, on_delete=models.CASCADE, related_name="brackets")
    lower_bound = MoneyField(help_text="Income at which this bracket starts")
    upper_bound = MoneyField(
        null=True, blank=True, help_text="Income at which this bracket ends (null = no upper limit)"
    )
    rate = models.DecimalField(max_digits=5, decimal_places=2, help_text="Rate for income in this bracket")
    cumulative_tax_below = MoneyField(
        default=0,
        help_text="Total tax owed on all income below lower_bound (pre-computed for speed)"
    )

    class Meta(TimeStampedModel.Meta):
        ordering = ["lower_bound"]
        verbose_name = "Tax Bracket"

    def __str__(self):
        upper = f"{self.upper_bound:,.0f}" if self.upper_bound else "∞"
        return f"{self.config.name}: {self.lower_bound:,.0f}–{upper} @ {self.rate}%"


class TaxReturn(TenantAwareModel):
    """
    A filed or calculated tax return for a given period.

    Covers one tax type (VAT, Income Tax, etc.) for one period.
    """

    class PeriodType(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"
        ANNUAL = "annual", "Annual"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        FILED = "filed", "Filed"
        PAID = "paid", "Paid"
        AMENDED = "amended", "Amended"

    config = models.ForeignKey(TaxConfig, on_delete=models.PROTECT, related_name="returns")
    period_type = models.CharField(max_length=15, choices=PeriodType.choices)
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)

    # Calculated amounts
    total_taxable_income = MoneyField()
    total_allowances = MoneyField()
    net_taxable_income = MoneyField()
    tax_payable = MoneyField()
    tax_paid = MoneyField()
    tax_due = MoneyField()

    filed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta(TenantAwareModel.Meta):
        unique_together = [["organisation", "config", "period_start", "period_end"]]
        verbose_name = "Tax Return"

    def __str__(self):
        return f"{self.config.name} | {self.period_start} → {self.period_end}"


class ExciseDuty(TenantAwareModel):
    SPIRITS = 'spirits'; WINE = 'wine'; BEER = 'beer'; TOBACCO = 'tobacco'; OTHER = 'other'
    CATEGORY_CHOICES = [(c, c) for c in [SPIRITS, WINE, BEER, TOBACCO, OTHER]]
    SPECIFIC = 'specific'; AD_VALOREM = 'ad_valorem'
    DUTY_TYPE_CHOICES = [(SPECIFIC, 'Specific (per LPA)'), (AD_VALOREM, 'Ad Valorem (%)')]

    name = models.CharField(max_length=200)
    product_category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=SPIRITS)
    duty_type = models.CharField(max_length=20, choices=DUTY_TYPE_CHOICES, default=SPECIFIC)
    rate = models.DecimalField(max_digits=10, decimal_places=4)  # e.g. 158.7 for 158.70/LPA
    effective_date = models.DateField()
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-effective_date']

    def __str__(self):
        return f"{self.name} ({self.rate})"

    def calculate(self, product, quantity):
        from decimal import Decimal
        if self.duty_type == self.SPECIFIC:
            # Specific: rate per litre of pure alcohol (LPA)
            abv = Decimal(str(product.alcohol_percentage or '0'))
            vol_ml = Decimal(str(product.volume_ml or '0'))
            lpa_per_unit = abv / 100 * vol_ml / 1000
            return lpa_per_unit * Decimal(str(quantity)) * self.rate
        else:
            # Ad valorem: percentage of selling price
            return product.selling_price * Decimal(str(quantity)) * (self.rate / 100)


class WHTRate(TenantAwareModel):
    transaction_type = models.CharField(max_length=200)  # e.g. "Rent", "Consultancy"
    company_rate = models.DecimalField(max_digits=5, decimal_places=2, default=5)  # %
    individual_rate = models.DecimalField(max_digits=5, decimal_places=2, default=5)  # %
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['transaction_type']
        unique_together = [('organisation', 'transaction_type')]


class WHTTransaction(TenantAwareModel):
    SALE = 'sale'; PURCHASE = 'purchase'
    TYPE_CHOICES = [(SALE, 'Sale'), (PURCHASE, 'Purchase')]
    WITHHELD = 'withheld'; REMITTED = 'remitted'
    STATUS_CHOICES = [(WITHHELD, 'Withheld'), (REMITTED, 'Remitted')]

    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    wht_rate = models.ForeignKey(WHTRate, on_delete=models.PROTECT)
    counterparty_name = models.CharField(max_length=200)
    tin = models.CharField(max_length=50, blank=True)
    gross_amount = MoneyField()
    wht_rate_percent = models.DecimalField(max_digits=5, decimal_places=2)
    wht_amount = MoneyField()
    net_amount = MoneyField()
    transaction_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=WITHHELD)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-transaction_date']


class WHTCertificate(TenantAwareModel):
    """
    WHT Credit Note (Form WHT 03) issued to a payee after remittance.
    Allows the payee to offset WHT against their own income tax liability.
    """
    wht_transaction = models.OneToOneField(WHTTransaction, on_delete=models.CASCADE, related_name='certificate')
    certificate_number = models.CharField(max_length=50, unique=True)
    issued_date = models.DateField()
    remittance_reference = models.CharField(max_length=200, blank=True, help_text="FIRS receipt / TaxPro MAX payment reference")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-issued_date']

    def __str__(self):
        return f"WHT Cert {self.certificate_number}"

    def save(self, *args, **kwargs):
        if not self.certificate_number:
            import uuid
            prefix = str(self.organisation_id)[:4].upper()
            self.certificate_number = f"WHT-{prefix}-{str(uuid.uuid4())[:8].upper()}"
        super().save(*args, **kwargs)


class VATTransaction(TenantAwareModel):
    """
    Per-transaction VAT tracking for full ITC (Input Tax Credit) reconciliation.
    Output transactions are VAT collected on sales.
    Input transactions are VAT paid on purchases (claimable against output VAT).
    """
    OUTPUT = 'output'; INPUT = 'input'
    DIRECTION_CHOICES = [(OUTPUT, 'Output (collected)'), (INPUT, 'Input (paid)')]

    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    period_start = models.DateField(help_text="VAT return period this transaction belongs to")
    period_end = models.DateField()
    counterparty_name = models.CharField(max_length=200, blank=True, help_text="Customer or supplier name")
    counterparty_tin = models.CharField(max_length=50, blank=True, help_text="TIN for ITC verification")
    net_amount = MoneyField(help_text="Net amount before VAT")
    vat_amount = MoneyField(help_text="VAT amount charged or paid")
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=7.5)
    is_claimable = models.BooleanField(default=True, help_text="Input VAT is claimable only if for business use with valid tax invoice")
    source_ref = models.CharField(max_length=200, blank=True, help_text="Invoice number or bill reference")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-period_end', 'direction']

    def __str__(self):
        return f"{self.direction} VAT {self.vat_amount} — {self.period_start} to {self.period_end}"


class TaxObligation(TenantAwareModel):
    """
    Compliance calendar entry: one tax obligation per period.
    Auto-generated by Celery Beat (VAT monthly, PAYE monthly, CIT annually).
    Can also be created manually for custom obligations.
    """
    VAT = 'vat'; PAYE = 'paye'; CIT = 'cit'; PIT = 'pit'; WHT = 'wht'; PENSION = 'pension'; CUSTOM = 'custom'
    TYPE_CHOICES = [
        (VAT, 'VAT Return'), (PAYE, 'PAYE Remittance'), (CIT, 'Companies Income Tax'),
        (PIT, 'Personal Income Tax'), (WHT, 'WHT Remittance'), (PENSION, 'Pension Contribution'),
        (CUSTOM, 'Custom'),
    ]

    PENDING = 'pending'; FILED = 'filed'; PAID = 'paid'; OVERDUE = 'overdue'
    STATUS_CHOICES = [(PENDING, 'Pending'), (FILED, 'Filed'), (PAID, 'Paid'), (OVERDUE, 'Overdue')]

    obligation_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    label = models.CharField(max_length=200, help_text="e.g. 'VAT Return — January 2025'")
    period_year = models.PositiveIntegerField()
    period_month = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Null for annual obligations")
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    amount_due = MoneyField(default=0)
    filed_date = models.DateField(null=True, blank=True)
    payment_reference = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    is_auto_generated = models.BooleanField(default=False)

    class Meta:
        ordering = ['due_date']
        unique_together = [('organisation', 'obligation_type', 'period_year', 'period_month')]

    def __str__(self):
        return self.label


class CapitalAllowanceClaim(TenantAwareModel):
    """
    Capital allowance claim per fixed asset per tax year (Schedule 2 CITA).

    Initial Allowance (IA) is granted in the year of acquisition.
    Annual Allowance (AA) is granted each subsequent year on the reducing balance.
    """
    # Asset classes per CITA Schedule 2
    INDUSTRIAL_BUILDING = 'industrial_building'
    NON_INDUSTRIAL_BUILDING = 'non_industrial_building'
    PLANT_MACHINERY = 'plant_machinery'
    MOTOR_VEHICLE = 'motor_vehicle'
    FURNITURE = 'furniture'
    COMPUTER = 'computer'
    OTHER = 'other'
    ASSET_CLASS_CHOICES = [
        (INDUSTRIAL_BUILDING, 'Industrial Building'),
        (NON_INDUSTRIAL_BUILDING, 'Non-Industrial Building'),
        (PLANT_MACHINERY, 'Plant & Machinery'),
        (MOTOR_VEHICLE, 'Motor Vehicle'),
        (FURNITURE, 'Furniture & Fittings'),
        (COMPUTER, 'Computer & IT Equipment'),
        (OTHER, 'Other'),
    ]

    # CITA Schedule 2 rates: (initial_allowance%, annual_allowance%)
    ASSET_CLASS_RATES = {
        INDUSTRIAL_BUILDING: (Decimal('15'), Decimal('10')),
        NON_INDUSTRIAL_BUILDING: (Decimal('15'), Decimal('10')),
        PLANT_MACHINERY: (Decimal('50'), Decimal('25')),
        MOTOR_VEHICLE: (Decimal('25'), Decimal('20')),
        FURNITURE: (Decimal('25'), Decimal('20')),
        COMPUTER: (Decimal('50'), Decimal('25')),
        OTHER: (Decimal('25'), Decimal('20')),
    }

    asset_name = models.CharField(max_length=300)
    asset_class = models.CharField(max_length=30, choices=ASSET_CLASS_CHOICES, default=PLANT_MACHINERY)
    tax_year = models.PositiveIntegerField()
    cost = MoneyField(help_text="Original acquisition cost")
    opening_tax_written_down_value = MoneyField(default=0, help_text="Tax WDV at start of this tax year")
    initial_allowance_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0,
        help_text="IA rate % (only in year of acquisition)")
    annual_allowance_rate = models.DecimalField(max_digits=5, decimal_places=2, default=20)
    initial_allowance = MoneyField(default=0)
    annual_allowance = MoneyField(default=0)
    total_allowance = MoneyField(default=0)
    closing_tax_written_down_value = MoneyField(default=0)
    is_acquisition_year = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-tax_year', 'asset_name']
        unique_together = [('organisation', 'asset_name', 'tax_year')]

    def __str__(self):
        return f"{self.asset_name} — CA {self.tax_year}"

    def save(self, *args, **kwargs):
        ia_rate, aa_rate = self.ASSET_CLASS_RATES.get(
            self.asset_class, (Decimal('25'), Decimal('20'))
        )
        if self.is_acquisition_year:
            self.initial_allowance_rate = ia_rate
            self.initial_allowance = (Decimal(str(self.cost)) * ia_rate / 100).quantize(Decimal('0.01'))
        else:
            self.initial_allowance_rate = Decimal('0')
            self.initial_allowance = Decimal('0')

        self.annual_allowance_rate = aa_rate
        base = Decimal(str(self.opening_tax_written_down_value)) - self.initial_allowance
        self.annual_allowance = (base * aa_rate / 100).quantize(Decimal('0.01'))
        self.total_allowance = self.initial_allowance + self.annual_allowance
        self.closing_tax_written_down_value = max(
            Decimal('0'),
            Decimal(str(self.opening_tax_written_down_value)) - self.total_allowance
        )
        super().save(*args, **kwargs)


class DeferredTaxItem(TenantAwareModel):
    """
    Deferred tax asset (DTA) or liability (DTL) per IAS 12.

    Arises from temporary differences between accounting profit and taxable profit.
    Examples:
      - Accelerated tax depreciation vs. straight-line accounting depreciation (→ DTL)
      - Provisions not yet deductible for tax (→ DTA)
      - Revenue recognised in accounts but not yet taxable (→ DTL)
    """
    DTA = 'dta'; DTL = 'dtl'
    TYPE_CHOICES = [(DTA, 'Deferred Tax Asset'), (DTL, 'Deferred Tax Liability')]

    DEPRECIATION = 'depreciation'
    PROVISION = 'provision'
    REVENUE = 'revenue'
    EXPENSE = 'expense'
    OTHER = 'other'
    CATEGORY_CHOICES = [
        (DEPRECIATION, 'Accelerated Depreciation'),
        (PROVISION, 'Provision / Accrual'),
        (REVENUE, 'Revenue Recognition Timing'),
        (EXPENSE, 'Disallowed / Deferred Expense'),
        (OTHER, 'Other'),
    ]

    deferred_type = models.CharField(max_length=3, choices=TYPE_CHOICES)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=DEPRECIATION)
    description = models.CharField(max_length=300)
    tax_year = models.PositiveIntegerField()
    timing_difference = MoneyField(help_text="Carrying amount minus tax base (positive = DTL, negative = DTA)")
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=30,
        help_text="Applicable corporate tax rate % for computing the deferred tax amount")
    deferred_tax_amount = MoneyField(default=0, help_text="timing_difference × tax_rate / 100")
    is_recognised = models.BooleanField(default=True, help_text="Unrecognised DTAs may not meet recoverability criteria")
    reversal_year = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-tax_year', 'deferred_type', 'description']

    def __str__(self):
        return f"{self.get_deferred_type_display()} — {self.description} ({self.tax_year})"

    def save(self, *args, **kwargs):
        diff = Decimal(str(self.timing_difference))
        rate = Decimal(str(self.tax_rate))
        self.deferred_tax_amount = (abs(diff) * rate / 100).quantize(Decimal('0.01'))
        # Determine type from the sign of timing difference if not explicitly set
        if diff > 0:
            self.deferred_type = self.DTL
        elif diff < 0:
            self.deferred_type = self.DTA
        super().save(*args, **kwargs)


class RelatedPartyTransaction(TenantAwareModel):
    """
    Transfer Pricing — related party transactions disclosure (FIRS TP Regulations 2018).

    Nigerian entities with related-party transactions > ₦300M must file TP disclosures.
    """
    SALE_OF_GOODS = 'sale_goods'; PURCHASE_OF_GOODS = 'purchase_goods'
    SERVICES_RENDERED = 'services_rendered'; SERVICES_RECEIVED = 'services_received'
    LOAN_ADVANCED = 'loan_advanced'; LOAN_RECEIVED = 'loan_received'
    ROYALTIES_PAID = 'royalties_paid'; ROYALTIES_RECEIVED = 'royalties_received'
    MANAGEMENT_FEE_PAID = 'mgmt_fee_paid'; MANAGEMENT_FEE_RECEIVED = 'mgmt_fee_received'
    DIVIDEND = 'dividend'; OTHER = 'other'
    TRANSACTION_TYPE_CHOICES = [
        (SALE_OF_GOODS, 'Sale of Goods'), (PURCHASE_OF_GOODS, 'Purchase of Goods'),
        (SERVICES_RENDERED, 'Services Rendered'), (SERVICES_RECEIVED, 'Services Received'),
        (LOAN_ADVANCED, 'Loan Advanced'), (LOAN_RECEIVED, 'Loan Received'),
        (ROYALTIES_PAID, 'Royalties Paid'), (ROYALTIES_RECEIVED, 'Royalties Received'),
        (MANAGEMENT_FEE_PAID, 'Management Fee Paid'), (MANAGEMENT_FEE_RECEIVED, 'Management Fee Received'),
        (DIVIDEND, 'Dividend'), (OTHER, 'Other'),
    ]

    CUP = 'cup'; RPM = 'rpm'; CPM = 'cpm'; TNMM = 'tnmm'; PSM = 'psm'; NONE = 'none'
    TP_METHOD_CHOICES = [
        (CUP, 'Comparable Uncontrolled Price (CUP)'),
        (RPM, 'Resale Price Method (RPM)'),
        (CPM, 'Cost Plus Method (CPM)'),
        (TNMM, 'Transactional Net Margin Method (TNMM)'),
        (PSM, 'Profit Split Method (PSM)'),
        (NONE, 'Not yet determined'),
    ]

    related_party_name = models.CharField(max_length=300, help_text="Name of related party (subsidiary, parent, affiliate)")
    relationship = models.CharField(max_length=200, help_text="e.g. Parent Company, Subsidiary, Sister Company")
    country = models.CharField(max_length=2, help_text="ISO country code of related party")
    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPE_CHOICES)
    tax_year = models.PositiveIntegerField()
    amount = MoneyField(help_text="Total value of this transaction type for the year")
    currency = models.CharField(max_length=3, default='NGN')
    tp_method = models.CharField(max_length=10, choices=TP_METHOD_CHOICES, default=NONE)
    arm_length_price = MoneyField(default=0, help_text="Arm's length price / benchmark value")
    adjustment_required = models.BooleanField(default=False, help_text="True if actual price deviates from arm's length")
    adjustment_amount = MoneyField(default=0)
    documentation_status = models.CharField(max_length=50, default='not_prepared',
        choices=[
            ('not_prepared', 'Not Prepared'), ('in_progress', 'In Progress'),
            ('completed', 'Completed'), ('filed', 'Filed with FIRS'),
        ])
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-tax_year', 'related_party_name']

    def __str__(self):
        return f"TP: {self.related_party_name} — {self.get_transaction_type_display()} ({self.tax_year})"

    @property
    def exceeds_threshold(self):
        """Nigerian TP disclosure threshold: ₦300M aggregate per related party."""
        return Decimal(str(self.amount)) > Decimal('300000000')
