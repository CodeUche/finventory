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
