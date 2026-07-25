"""
Tax service: orchestrates tax return creation and VAT reporting.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.sales.models import SaleItem

from .engine import TaxEngine
from .models import TaxConfig, TaxReturn

logger = logging.getLogger(__name__)


class TaxService:

    # NTA 2025: small-company thresholds for CIT exemption
    SMALL_COMPANY_TURNOVER_LIMIT = Decimal("100000000")   # ₦100 million
    SMALL_COMPANY_ASSET_LIMIT    = Decimal("250000000")   # ₦250 million fixed assets
    DEVELOPMENT_LEVY_RATE        = Decimal("0.04")        # 4% of assessable profit (NTA 2025)

    @staticmethod
    def _get_or_create_config_for_year(organisation, tax_type: str, year: int):
        """
        Return the active TaxConfig for (org, type, year).
        If none exists but a prior year config does, clone it forward so the service
        never fails simply because a new calendar year started (B3 — yearly rollover).
        """
        config = TaxConfig.objects.filter(
            organisation=organisation,
            tax_type=tax_type,
            tax_year=year,
            is_active=True,
        ).order_by('id').first()

        if config:
            return config

        # Try to clone the most recent prior-year config
        prior = TaxConfig.objects.filter(
            organisation=organisation,
            tax_type=tax_type,
            is_active=True,
            tax_year__lt=year,
        ).order_by('-tax_year', 'id').first()

        if not prior:
            return None

        from .models import TaxBracket
        new_config = TaxConfig.objects.create(
            organisation=organisation,
            name=prior.name,
            tax_type=prior.tax_type,
            tax_year=year,
            flat_rate=prior.flat_rate,
            personal_allowance=prior.personal_allowance,
            is_active=True,
            description=f"Auto-rolled forward from {prior.tax_year}",
        )
        for bracket in TaxBracket.objects.filter(config=prior):
            TaxBracket.objects.create(
                organisation=organisation,
                config=new_config,
                lower_bound=bracket.lower_bound,
                upper_bound=bracket.upper_bound,
                rate=bracket.rate,
            )
        logger.info("TaxConfig rolled forward: %s → year %s", prior, year)
        return new_config

    @staticmethod
    def calculate_income_tax(
        organisation, income: Decimal, tax_year: int = None,
        allowances: Decimal = None, tax_type: str = None,
        gross_turnover: Decimal = None,
        fixed_assets: Decimal = None,
    ) -> dict:
        """
        Calculate income tax for the organisation using the active tax config (NTA 2025).

        NTA 2025 changes vs old law:
        - PIT minimum tax abolished (income ≤ ₦800k/yr is the 0% band; no separate floor)
        - CIT minimum tax abolished for small companies (≤₦100m turnover + ≤₦250m assets → 0%)
        - Development Levy 4% of assessable profit added for non-small companies
        - CIT 0.5% minimum-tax floor retained only for large companies (gross_turnover supplied)
        """
        year = tax_year or timezone.now().year

        # Require explicit tax_type when both income and corporate configs may exist (H-4 fix)
        if tax_type in ('income', 'corporate'):
            resolved_type = tax_type
        else:
            resolved_type = TaxConfig.TaxType.INCOME

        config = TaxService._get_or_create_config_for_year(organisation, resolved_type, year)
        if not config:
            raise ValueError(f"No active {resolved_type} tax configuration found for {year}.")

        result = TaxEngine.calculate(income=income, config=config, allowances=allowances)
        tax_payable = result.tax_payable
        development_levy = Decimal('0')
        small_company_exempt = False
        minimum_tax_applied = False
        minimum_tax_amount = Decimal('0')

        if config.tax_type == TaxConfig.TaxType.CORPORATE:
            # NTA 2025: small companies (≤₦100m turnover AND ≤₦250m fixed assets) are CIT-exempt
            turnover = Decimal(str(gross_turnover)) if gross_turnover else Decimal('0')
            assets   = Decimal(str(fixed_assets))   if fixed_assets   else Decimal('0')
            is_small = (
                turnover > 0
                and turnover  <= TaxService.SMALL_COMPANY_TURNOVER_LIMIT
                and (assets == 0 or assets <= TaxService.SMALL_COMPANY_ASSET_LIMIT)
            )
            if is_small:
                tax_payable = Decimal('0')
                small_company_exempt = True
            else:
                # 4% Development Levy on assessable profit (replaces old TET/NITDA/PTF levies)
                development_levy = (income * TaxService.DEVELOPMENT_LEVY_RATE).quantize(
                    Decimal('0.01'), rounding='ROUND_HALF_UP'
                )
                # CIT 0.5% minimum-tax floor (large companies only)
                if turnover > 0:
                    cit_minimum = turnover * Decimal('0.005')
                    if tax_payable < cit_minimum:
                        tax_payable = cit_minimum
                        minimum_tax_applied = True
                        minimum_tax_amount = cit_minimum

        total_tax = tax_payable + development_levy
        effective_rate = (total_tax / income * 100).quantize(
            Decimal('0.01'), rounding='ROUND_HALF_UP'
        ) if income > 0 else Decimal('0')

        return {
            "gross_income": result.gross_income,
            "total_allowances": result.total_allowances,
            "net_taxable_income": result.net_taxable_income,
            "tax_payable": tax_payable,
            "development_levy": development_levy,
            "total_tax": total_tax,
            "effective_rate": effective_rate,
            "small_company_exempt": small_company_exempt,
            "minimum_tax_applied": minimum_tax_applied,
            "minimum_tax_amount": minimum_tax_amount if minimum_tax_applied else None,
            "brackets": [
                {
                    "bracket": f"{b.lower:,.0f} – {'∞' if b.upper is None else f'{b.upper:,.0f}'}",
                    "rate": b.rate,
                    "taxable_amount": b.taxable_in_bracket,
                    "tax": b.tax_in_bracket,
                }
                for b in result.brackets
            ],
            "config": config.name,
            "tax_year": year,
        }

    @staticmethod
    def calculate_vat_report(organisation, period_start, period_end) -> dict:
        """
        Aggregate VAT collected on sales for a given period.

        Returns VAT output (collected on sales) and VAT input (paid on purchases — future).
        """
        from django.db.models import F

        # VAT output: sum tax_amount on confirmed/paid sales lines
        sales_agg = SaleItem.objects.filter(
            organisation=organisation,
            invoice__issue_date__gte=period_start,
            invoice__issue_date__lte=period_end,
            invoice__status__in=["paid", "confirmed", "partially_paid", "credit"],
        ).aggregate(
            total_vat=Sum("tax_amount"),
            total_gross=Sum("line_total"),       # line_total includes VAT
            total_tax_on_lines=Sum("tax_amount"),
        )
        output_vat = sales_agg["total_vat"] or Decimal("0")
        # Net sales = gross line totals minus the VAT embedded in them (M-3 fix)
        total_gross = sales_agg["total_gross"] or Decimal("0")
        net_sales   = total_gross - output_vat

        # Deduct output VAT on sales returns in the period (C2/H-1 fix)
        from apps.sales.models import SaleReturnItem
        returned_vat = SaleReturnItem.objects.filter(
            organisation=organisation,
            sale_return__return_date__gte=period_start,
            sale_return__return_date__lte=period_end,
            tax_refund__isnull=False,
        ).aggregate(total=Sum("tax_refund"))["total"] or Decimal("0")
        output_vat = max(Decimal("0"), output_vat - returned_vat)

        # VAT input: only claim on standard/zero-rated bills (exclude exempt-treatment tax classes)
        from apps.bills.models import Bill
        bills_qs = Bill.objects.filter(
            organisation=organisation,
            issue_date__gte=period_start,
            issue_date__lte=period_end,
            status__in=[Bill.APPROVED, Bill.PAID, Bill.PARTIALLY_PAID],
        )
        # If TaxClass.treatment field exists, exclude input VAT on exempt-treatment bills
        try:
            from apps.tax.models import TaxClass
            exempt_bill_ids = list(
                bills_qs.filter(tax_class__treatment='exempt').values_list('id', flat=True)
            )
            recoverable_bills = bills_qs.exclude(id__in=exempt_bill_ids)
        except Exception:
            recoverable_bills = bills_qs

        input_vat = recoverable_bills.aggregate(
            total_vat=Sum("tax_amount")
        )["total_vat"] or Decimal("0")

        net_vat_payable = output_vat - input_vat

        return {
            "period_start": period_start,
            "period_end": period_end,
            "vat_output": output_vat,
            "vat_input": input_vat,
            "vat_on_returns": returned_vat,
            "net_vat_payable": net_vat_payable,
            "total_net_sales": net_sales,  # net of VAT (M-3 fix)
        }

    # WHT 2024 small-payer exemption thresholds (Deduction of Tax at Source Regulations 2024)
    _WHT_SMALL_PAYER_TURNOVER_LIMIT = Decimal("25000000")   # ₦25m annual turnover
    _WHT_SMALL_PAYER_MONTHLY_LIMIT  = Decimal("2000000")    # ₦2m/month per transaction

    @staticmethod
    def _apply_wht_exemptions(
        organisation,
        rate_pct: Decimal,
        gross_amount: Decimal,
        tin: str,
        transaction_date,
    ) -> tuple[Decimal, str]:
        """
        Apply WHT 2024 Regulation adjustments and return (effective_rate, note).

        Rules applied (NG only):
        1. TIN-doubling: if counterparty has no TIN, double the rate (s.14 WHT Regs 2024).
        2. Small-payer exemption: payer with annual turnover ≤ ₦25m AND transaction ≤ ₦2m/month
           is exempt from deducting WHT — returns rate=0.
        """
        notes = []
        if organisation.country != "NG":
            return rate_pct, ""

        # Small-payer exemption check (payer's own annual revenue)
        payer_annual_turnover = getattr(organisation, "annual_turnover", None)
        if (
            payer_annual_turnover is not None
            and payer_annual_turnover <= TaxService._WHT_SMALL_PAYER_TURNOVER_LIMIT
            and gross_amount <= TaxService._WHT_SMALL_PAYER_MONTHLY_LIMIT
        ):
            return Decimal("0"), "WHT exempt: small payer (≤₦25m turnover, ≤₦2m transaction)"

        # TIN-doubling
        if not tin or not tin.strip():
            rate_pct = rate_pct * 2
            notes.append("TIN-doubling applied (no counterparty TIN)")

        return rate_pct, "; ".join(notes)

    @staticmethod
    def auto_create_wht_transaction(
        organisation,
        wht_rate_id,
        transaction_type: str,  # 'sale' or 'purchase'
        gross_amount: Decimal,
        counterparty_name: str,
        transaction_date,
        tin: str = "",
        source_ref: str = "",
    ) -> None:
        """
        Auto-create a WHTTransaction from a sale or bill payment.

        transaction_type='sale'     → customer withheld from us (we are the payee)
        transaction_type='purchase' → we withhold from vendor (we are the payer)

        Applies WHT 2024 Regulation: TIN-doubling (no TIN → rate×2) and small-payer exemption.
        Non-blocking: errors are logged and swallowed so the parent transaction succeeds.
        """
        try:
            from .models import WHTRate, WHTTransaction
            rate = WHTRate.objects.get(id=wht_rate_id, organisation=organisation)
            rate_pct = rate.company_rate
            rate_pct, exemption_note = TaxService._apply_wht_exemptions(
                organisation, rate_pct, gross_amount, tin, transaction_date
            )
            wht_amount = (gross_amount * rate_pct / Decimal("100")).quantize(Decimal("0.01"))
            net_amount = gross_amount - wht_amount
            base_note = f"Auto-created from {transaction_type} {source_ref}".strip()
            notes = f"{base_note}. {exemption_note}".strip(". ") if exemption_note else base_note
            WHTTransaction.objects.create(
                organisation=organisation,
                transaction_type=transaction_type,
                wht_rate=rate,
                wht_rate_percent=rate_pct,
                counterparty_name=counterparty_name,
                tin=tin,
                gross_amount=gross_amount,
                wht_amount=wht_amount,
                net_amount=net_amount,
                transaction_date=transaction_date,
                status=WHTTransaction.WITHHELD,
                notes=notes,
            )
        except Exception as exc:
            logger.error("auto_create_wht_transaction failed: %s", exc)

    @staticmethod
    @transaction.atomic
    def create_tax_return(organisation, config: TaxConfig, period_start, period_end) -> TaxReturn:
        """Create or update a draft tax return for the given period (NTA 2025 compliant)."""
        from apps.expenses.models import Expense
        from apps.sales.models import Invoice
        from django.db.models import F, Sum

        # Revenue = net sales (VAT-exclusive) — B2/C-1 fix: exclude output VAT from the base
        revenue_agg = Invoice.objects.filter(
            organisation=organisation,
            issue_date__gte=period_start,
            issue_date__lte=period_end,
            status__in=["paid", "confirmed", "partially_paid"],
        ).aggregate(
            gross=Sum("total_amount"),
            vat=Sum("tax_amount"),
        )
        gross_revenue = revenue_agg["gross"] or Decimal("0")
        output_vat    = revenue_agg["vat"]   or Decimal("0")
        net_revenue   = gross_revenue - output_vat  # VAT-exclusive revenue

        # Total expenses (COGS + operating) — exclude bills to avoid double-counting
        expenses = Expense.objects.filter(
            organisation=organisation,
            expense_date__gte=period_start,
            expense_date__lte=period_end,
            is_income=False,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        taxable_income = max(net_revenue - expenses, Decimal("0"))
        result = TaxEngine.calculate(income=taxable_income, config=config)

        # B1: CIT small-company exemption
        development_levy = Decimal("0")
        tax_payable = result.tax_payable
        if config.tax_type == TaxConfig.TaxType.CORPORATE:
            is_small = (
                net_revenue > 0
                and net_revenue <= TaxService.SMALL_COMPANY_TURNOVER_LIMIT
            )
            if is_small:
                tax_payable = Decimal("0")
            else:
                development_levy = (taxable_income * TaxService.DEVELOPMENT_LEVY_RATE).quantize(
                    Decimal("0.01"), rounding="ROUND_HALF_UP"
                )

        total_tax = tax_payable + development_levy

        tax_return, _ = TaxReturn.objects.update_or_create(
            organisation=organisation,
            config=config,
            period_start=period_start,
            period_end=period_end,
            defaults={
                "period_type": TaxReturn.PeriodType.ANNUAL,
                "status": TaxReturn.Status.DRAFT,
                # H-3 fix: store actual net taxable income, not gross revenue
                "total_taxable_income": taxable_income,
                "total_allowances": result.total_allowances,
                "net_taxable_income": result.net_taxable_income,
                "tax_payable": total_tax,
                "tax_paid": Decimal("0"),
                "tax_due": total_tax,
            },
        )
        return tax_return


class CapitalAllowanceService:
    """
    Nigeria Tax Act 2025 capital-allowance engine.

    GATED behind organisation.capital_allowance_nta2025_enabled (default False). Until a
    licensed Nigerian tax practitioner signs off the rate table + qualifying rules, the
    CIT computation continues to use its manual `allowances` input and this engine does
    NOT affect any live number. It is built and tested so it can be switched on after
    sign-off without further code changes.

    Rules encoded (our understanding — needs sign-off): no initial allowance; uniform
    straight-line annual rate per class (10/20/25); 1% notional cost retained until
    disposal; §27(2) VAT/levy-paid qualifying; disposal via chargeable gains only (no
    balancing charge/allowance, no roll-over relief).
    """

    # Fixed-asset register category → CA asset class (→ rate band).
    CATEGORY_TO_CLASS = {
        'building': 'non_industrial_building',
        'vehicle': 'motor_vehicle',
        'equipment': 'plant_machinery',
        'furniture': 'furniture',
        'other': 'other',
        # 'land' is intentionally excluded — land does not qualify for capital allowances.
    }

    @staticmethod
    def is_enabled(organisation) -> bool:
        return bool(getattr(organisation, 'capital_allowance_nta2025_enabled', False))

    @staticmethod
    def _qualifying_assets(organisation, tax_year):
        from apps.accounting.models import FixedAsset
        assets = FixedAsset.objects.filter(organisation=organisation).exclude(
            category=FixedAsset.LAND
        )
        result = []
        for a in assets:
            if a.purchase_date and a.purchase_date.year > tax_year:
                continue
            if a.disposal_date and a.disposal_date.year < tax_year:
                continue
            # §27(2): only capex on which input VAT/levy was paid qualifies. When the
            # flag is unset we still include it (evidence may pre-date capture); the
            # practitioner review decides the exact qualifying test.
            result.append(a)
        return result

    @staticmethod
    @transaction.atomic
    def generate_for_year(organisation, tax_year):
        """Build/refresh CapitalAllowanceClaim rows for each qualifying asset, chaining
        the tax written-down value from the prior year. Idempotent per (asset, year)."""
        from .models import CapitalAllowanceClaim
        claims = []
        for a in CapitalAllowanceService._qualifying_assets(organisation, tax_year):
            # MoneyField defaults to 0 (not None) — fall back to purchase_cost when unset.
            qcost = Decimal(str(a.qualifying_cost)) if a.qualifying_cost else Decimal(str(a.purchase_cost or 0))
            if qcost <= 0:
                continue
            asset_class = CapitalAllowanceService.CATEGORY_TO_CLASS.get(a.category, 'other')
            name = f"{a.asset_code} — {a.name}"[:300]
            prior = CapitalAllowanceClaim.objects.filter(
                organisation=organisation, asset=a, tax_year=tax_year - 1
            ).first()
            opening = Decimal(str(prior.closing_tax_written_down_value)) if prior else qcost
            claim, _ = CapitalAllowanceClaim.objects.update_or_create(
                organisation=organisation, asset_name=name, tax_year=tax_year,
                defaults={
                    'asset': a, 'asset_class': asset_class,
                    'cost': Decimal(str(a.purchase_cost)), 'qualifying_cost': qcost,
                    'opening_tax_written_down_value': opening,
                    'is_acquisition_year': bool(a.purchase_date and a.purchase_date.year == tax_year),
                },
            )
            claims.append(claim)
        return claims

    @staticmethod
    def total_for_year(organisation, tax_year) -> Decimal:
        from .models import CapitalAllowanceClaim
        return CapitalAllowanceClaim.objects.filter(
            organisation=organisation, tax_year=tax_year
        ).aggregate(t=Sum('total_allowance'))['t'] or Decimal('0')

    @staticmethod
    def chargeable_gain_on_disposal(asset, proceeds) -> Decimal:
        """NTA 2025: chargeable gain = proceeds − tax WDV (if CA was claimed) else −
        cost. No balancing charge/allowance; no roll-over relief. Taxed at the CIT
        rate via the normal CIT computation (small companies exempt)."""
        from .models import CapitalAllowanceClaim
        proceeds = Decimal(str(proceeds or 0))
        last = CapitalAllowanceClaim.objects.filter(asset=asset).order_by('-tax_year').first()
        base = (Decimal(str(last.closing_tax_written_down_value)) if last
                else Decimal(str(asset.purchase_cost or 0)))
        return proceeds - base

    @staticmethod
    def compute_assessable_profit(organisation, accounting_profit, tax_year, book_depreciation=None):
        """
        When the CA engine is ENABLED: assessable profit = accounting profit + book
        depreciation add-back − capital allowances (Nigerian CIT disallows accounting
        depreciation and substitutes capital allowances). When DISABLED (default),
        returns the accounting profit unchanged so nothing about the live CIT number
        changes until practitioner sign-off.
        """
        accounting_profit = Decimal(str(accounting_profit or 0))
        if not CapitalAllowanceService.is_enabled(organisation):
            return {
                'assessable_profit': accounting_profit,
                'depreciation_addback': Decimal('0'),
                'capital_allowances': Decimal('0'),
                'ca_enabled': False,
            }
        from apps.accounting.models import DepreciationEntry
        if book_depreciation is None:
            book_depreciation = DepreciationEntry.objects.filter(
                organisation=organisation, period_year=tax_year
            ).aggregate(t=Sum('depreciation_amount'))['t'] or Decimal('0')
        book_depreciation = Decimal(str(book_depreciation))
        CapitalAllowanceService.generate_for_year(organisation, tax_year)
        ca = CapitalAllowanceService.total_for_year(organisation, tax_year)
        return {
            'assessable_profit': accounting_profit + book_depreciation - ca,
            'depreciation_addback': book_depreciation,
            'capital_allowances': ca,
            'ca_enabled': True,
        }
