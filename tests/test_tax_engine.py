"""
Unit tests for the Tax Engine.

These tests verify the core calculation logic in isolation.
No database is needed — pure business logic tests.

Covers:
    - Progressive bracket calculation
    - Flat-rate calculation
    - Allowance deductions
    - VAT calculation (exclusive and inclusive)
    - Edge cases: zero income, income below allowance
"""

import pytest
from decimal import Decimal

from apps.tax.engine import TaxEngine, ProgressiveTaxStrategy, FlatRateTaxStrategy


@pytest.mark.unit
class TestProgressiveTaxStrategy:
    """Tests for the progressive/stepped bracket tax strategy."""

    def _make_config(self, personal_allowance=0):
        """Create a mock config object without hitting the DB."""
        from unittest.mock import MagicMock
        config = MagicMock()
        config.is_progressive = True
        config.personal_allowance = Decimal(str(personal_allowance))
        return config

    def _make_brackets(self, brackets_data):
        """Create mock bracket objects from (lower, upper, rate) tuples."""
        from unittest.mock import MagicMock
        brackets = []
        for lower, upper, rate in brackets_data:
            b = MagicMock()
            b.lower_bound = Decimal(str(lower))
            b.upper_bound = Decimal(str(upper)) if upper is not None else None
            b.rate = Decimal(str(rate))
            brackets.append(b)
        return brackets

    def test_zero_income_zero_tax(self):
        """Income of zero should result in zero tax."""
        strategy = ProgressiveTaxStrategy()
        brackets = self._make_brackets([(0, 300000, 7)])
        tax, _ = strategy.calculate(Decimal("0"), self._make_config(), brackets)
        assert tax == Decimal("0")

    def test_single_bracket_basic(self):
        """Income within first bracket: 100,000 * 7% = 7,000."""
        strategy = ProgressiveTaxStrategy()
        brackets = self._make_brackets([(0, 300000, 7)])
        tax, results = strategy.calculate(Decimal("100000"), self._make_config(), brackets)
        assert tax == Decimal("7000.00")
        assert len(results) == 1

    def test_multiple_brackets_nigeria_pit(self):
        """
        Nigeria PIT example:
        Income: 1,000,000
        Brackets:
            0 - 300,000:   7%  → 21,000
            300,000 - 600,000: 11% → 33,000
            600,000 - 1,000,000: 15% → 60,000
        Total: 114,000
        """
        strategy = ProgressiveTaxStrategy()
        brackets = self._make_brackets([
            (0, 300000, 7),
            (300000, 600000, 11),
            (600000, 1100000, 15),
        ])
        tax, results = strategy.calculate(Decimal("1000000"), self._make_config(), brackets)
        assert tax == Decimal("114000.00")
        assert len(results) == 3

    def test_top_bracket_no_upper_bound(self):
        """Income above all defined brackets should use the top bracket."""
        strategy = ProgressiveTaxStrategy()
        brackets = self._make_brackets([
            (0, 300000, 7),
            (300000, None, 11),  # No upper bound
        ])
        # 300k taxed at 7% = 21000, then 200k at 11% = 22000 → total 43000
        tax, results = strategy.calculate(Decimal("500000"), self._make_config(), brackets)
        assert tax == Decimal("43000.00")


@pytest.mark.unit
class TestTaxEngine:
    """Tests for the TaxEngine orchestrator."""

    def _make_mock_config(self, personal_allowance=200000, is_progressive=True):
        from unittest.mock import MagicMock, patch
        config = MagicMock()
        config.is_progressive = is_progressive
        config.personal_allowance = Decimal(str(personal_allowance))
        config.flat_rate = Decimal("10")
        return config

    def test_allowance_deducted_before_calculation(self):
        """Personal allowance should be deducted from gross income first."""
        from unittest.mock import MagicMock
        config = self._make_mock_config(personal_allowance=200000)
        config.brackets.order_by.return_value = []  # No brackets = zero tax

        result = TaxEngine.calculate(income=Decimal("200000"), config=config)
        assert result.net_taxable_income == Decimal("0")
        assert result.tax_payable == Decimal("0")

    def test_income_below_allowance_zero_tax(self):
        """If income ≤ allowance, no tax is payable."""
        from unittest.mock import MagicMock
        config = self._make_mock_config(personal_allowance=500000)
        config.brackets.order_by.return_value = []

        result = TaxEngine.calculate(income=Decimal("300000"), config=config)
        assert result.net_taxable_income == Decimal("0")
        assert result.tax_payable == Decimal("0")

    def test_effective_rate_calculated(self):
        """Effective rate = tax_payable / gross_income × 100."""
        from unittest.mock import MagicMock
        config = self._make_mock_config(personal_allowance=0, is_progressive=False)
        config.brackets.order_by.return_value = []

        result = TaxEngine.calculate(income=Decimal("1000000"), config=config)
        # Flat rate 10% → tax = 100,000
        assert result.tax_payable == Decimal("100000.00")
        assert result.effective_rate == Decimal("10.00")


@pytest.mark.unit
class TestVATCalculation:
    """Tests for VAT calculations."""

    def test_vat_exclusive_basic(self):
        """100 * 7.5% = 7.5 VAT, 107.5 gross."""
        result = TaxEngine.calculate_vat(amount=Decimal("100"), rate=Decimal("7.5"))
        assert result["vat_amount"] == Decimal("7.50")
        assert result["gross_amount"] == Decimal("107.50")

    def test_vat_exclusive_zero_rate(self):
        """Zero-rated item: VAT = 0."""
        result = TaxEngine.calculate_vat(amount=Decimal("500"), rate=Decimal("0"))
        assert result["vat_amount"] == Decimal("0.00")
        assert result["gross_amount"] == Decimal("500.00")

    def test_vat_inclusive_extraction(self):
        """
        Extract VAT from inclusive price.
        Gross = 107.50, rate = 7.5%
        Net = 107.50 / 1.075 = 100.00
        VAT = 7.50
        """
        result = TaxEngine.calculate_vat_inclusive(
            gross_amount=Decimal("107.50"), rate=Decimal("7.5")
        )
        assert result["net_amount"] == Decimal("100.00")
        assert result["vat_amount"] == Decimal("7.50")

    def test_vat_large_amount(self):
        """Ensure no precision loss on large amounts."""
        result = TaxEngine.calculate_vat(amount=Decimal("10000000"), rate=Decimal("7.5"))
        assert result["vat_amount"] == Decimal("750000.00")


@pytest.mark.integration
class TestTaxEngineWithDB:
    """Integration tests using real TaxConfig and TaxBracket records."""

    def test_nigeria_pit_calculation(self, nigeria_pit_config):
        """
        Full Nigeria PIT with DB-backed config.
        Income: 5,000,000
        Allowance: 200,000
        Net taxable: 4,800,000
        Expected tax (approximate): 965,000
        """
        from apps.tax.services import TaxService

        result = TaxService.calculate_income_tax(
            organisation=nigeria_pit_config.organisation,
            income=Decimal("5000000"),
            tax_year=2024,
        )
        assert result["net_taxable_income"] == Decimal("4800000")
        assert result["tax_payable"] > Decimal("0")
        assert len(result["brackets"]) > 0
        assert "effective_rate" in result
