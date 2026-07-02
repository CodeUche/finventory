"""
Tax Calculation Engine.

The engine is the heart of the tax system. It:
    1. Accepts income/amount and a TaxConfig
    2. Applies the correct calculation strategy (progressive or flat)
    3. Returns a structured TaxCalculationResult

Design:
    - Strategy pattern: ProgressiveTaxStrategy and FlatRateTaxStrategy
    - No hardcoded values anywhere
    - Fully unit-testable in isolation (no DB queries in calculation)
    - Supports future extensions (deductions, credits, min-tax, PAYE rounding)

Usage:
    result = TaxEngine.calculate(
        income=Decimal("5000000"),
        config=nigeria_pit_config,
    )
    print(result.tax_payable)  # → 965000.00
"""

import logging
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class BracketResult:
    """Tax calculated for one bracket."""

    lower: Decimal
    upper: Decimal | None
    rate: Decimal
    taxable_in_bracket: Decimal
    tax_in_bracket: Decimal


@dataclass
class TaxCalculationResult:
    """Full result of a tax calculation."""

    gross_income: Decimal
    total_allowances: Decimal
    net_taxable_income: Decimal
    tax_payable: Decimal
    effective_rate: Decimal             # actual rate as percentage
    brackets: list[BracketResult] = field(default_factory=list)
    notes: str = ""


class TaxStrategy(Protocol):
    """Strategy interface for tax calculation."""

    def calculate(
        self,
        net_income: Decimal,
        config,
        brackets: list,
    ) -> tuple[Decimal, list[BracketResult]]:
        ...


class ProgressiveTaxStrategy:
    """
    Calculates tax using a stepped/tiered bracket system.

    Algorithm:
        For each bracket (sorted by lower_bound):
            1. Determine income falling within this bracket
            2. Apply the bracket rate to that portion
            3. Sum across all brackets

    This is O(n) in the number of brackets — efficient for any realistic schedule.
    """

    def calculate(
        self,
        net_income: Decimal,
        config,
        brackets: list,
    ) -> tuple[Decimal, list[BracketResult]]:
        raw_total = Decimal("0")
        bracket_results = []

        for bracket in brackets:
            lower = Decimal(str(bracket.lower_bound))
            upper = Decimal(str(bracket.upper_bound)) if bracket.upper_bound else None
            rate = Decimal(str(bracket.rate)) / Decimal("100")

            if net_income <= lower:
                break

            if upper is not None:
                taxable_in_bracket = min(net_income, upper) - lower
            else:
                taxable_in_bracket = net_income - lower

            # Keep raw (unrounded) per-bracket; round once at the total (M-1 fix)
            tax_in_bracket_raw = taxable_in_bracket * rate
            raw_total += tax_in_bracket_raw

            bracket_results.append(
                BracketResult(
                    lower=lower,
                    upper=upper,
                    rate=bracket.rate,
                    taxable_in_bracket=taxable_in_bracket,
                    tax_in_bracket=tax_in_bracket_raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                )
            )

        total_tax = raw_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return total_tax, bracket_results


class FlatRateTaxStrategy:
    """Simple flat-rate tax calculation."""

    def calculate(
        self,
        net_income: Decimal,
        config,
        brackets: list,
    ) -> tuple[Decimal, list[BracketResult]]:
        rate = Decimal(str(config.flat_rate)) / Decimal("100")
        total_tax = (net_income * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        bracket_results = [
            BracketResult(
                lower=Decimal("0"),
                upper=None,
                rate=config.flat_rate,
                taxable_in_bracket=net_income,
                tax_in_bracket=total_tax,
            )
        ]
        return total_tax, bracket_results


class TaxEngine:
    """
    Main tax calculation orchestrator.

    Selects the appropriate strategy based on TaxConfig and delegates.
    """

    @staticmethod
    def calculate(
        income: Decimal,
        config,
        allowances: Decimal = None,
        additional_deductions: Decimal = None,
    ) -> TaxCalculationResult:
        """
        Calculate tax for the given income and TaxConfig.

        Args:
            income: Gross taxable income (Decimal).
            config: TaxConfig model instance.
            allowances: Override personal allowance (uses config default if None).
            additional_deductions: Extra deductions (pension, NHF, etc.).

        Returns:
            TaxCalculationResult with full breakdown.
        """
        income = Decimal(str(income))
        personal_allowance = allowances if allowances is not None else Decimal(str(config.personal_allowance))
        extra_deductions = Decimal(str(additional_deductions or 0))

        total_allowances = personal_allowance + extra_deductions
        net_income = max(income - total_allowances, Decimal("0"))

        # Select strategy
        if config.is_progressive:
            brackets = list(config.brackets.order_by("lower_bound"))
            strategy = ProgressiveTaxStrategy()
        else:
            brackets = []
            strategy = FlatRateTaxStrategy()

        tax_payable, bracket_results = strategy.calculate(net_income, config, brackets)

        effective_rate = (
            (tax_payable / income * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if income > 0
            else Decimal("0")
        )

        result = TaxCalculationResult(
            gross_income=income,
            total_allowances=total_allowances,
            net_taxable_income=net_income,
            tax_payable=tax_payable,
            effective_rate=effective_rate,
            brackets=bracket_results,
        )

        logger.debug(
            "Tax calculated: income=%s, allowances=%s, net=%s, tax=%s, eff_rate=%s%%",
            income, total_allowances, net_income, tax_payable, effective_rate,
        )

        return result

    @staticmethod
    def calculate_vat(amount: Decimal, rate: Decimal) -> dict:
        """
        Calculate VAT/sales tax on a given amount.

        Args:
            amount: Pre-tax amount.
            rate: VAT rate as percentage (e.g., 7.5).

        Returns:
            dict with keys: net_amount, vat_amount, gross_amount.
        """
        amount = Decimal(str(amount))
        rate = Decimal(str(rate))
        vat = (amount * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return {
            "net_amount": amount,
            "vat_rate": rate,
            "vat_amount": vat,
            "gross_amount": amount + vat,
        }

    @staticmethod
    def calculate_vat_inclusive(gross_amount: Decimal, rate: Decimal) -> dict:
        """
        Extract VAT from a VAT-inclusive price.

        Formula: VAT = gross - (gross / (1 + rate/100))
        """
        gross_amount = Decimal(str(gross_amount))
        rate = Decimal(str(rate))
        net = (gross_amount / (1 + rate / Decimal("100"))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        vat = gross_amount - net
        return {
            "gross_amount": gross_amount,
            "vat_rate": rate,
            "vat_amount": vat,
            "net_amount": net,
        }
