"""
Tests for reports.period_utils.

Covers every period shortcut, custom date parsing, invalid input fallback,
edge cases (Monday, Jan 1, leap year), and period_label output.
"""

from datetime import date, timedelta
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.reports.period_utils import VALID_PERIODS, period_label, resolve_period


class TestResolvePeriodToday(SimpleTestCase):
    """period='today' → (today, today)."""

    def _today(self):
        return date(2025, 6, 15)  # fixed anchor

    def test_today_returns_same_date_both_sides(self):
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = self._today()
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("today")
        self.assertEqual(d_from, self._today())
        self.assertEqual(d_to, self._today())

    def test_today_case_insensitive(self):
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = self._today()
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("TODAY")
        self.assertEqual(d_from, self._today())
        self.assertEqual(d_to, self._today())

    def test_today_ignores_date_params(self):
        """Explicit date_from/date_to params must be ignored for 'today'."""
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = self._today()
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("today", "2020-01-01", "2020-12-31")
        self.assertEqual(d_from, self._today())
        self.assertEqual(d_to, self._today())


class TestResolvePeriodWeek(SimpleTestCase):
    """period='week' → Monday of current ISO week to today."""

    def test_week_on_wednesday(self):
        # 2025-06-18 is a Wednesday; Monday = 2025-06-16
        anchor = date(2025, 6, 18)
        expected_monday = date(2025, 6, 16)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = anchor
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("week")
        self.assertEqual(d_from, expected_monday)
        self.assertEqual(d_to, anchor)

    def test_week_on_monday(self):
        # When today IS Monday, date_from == today
        monday = date(2025, 6, 16)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = monday
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("week")
        self.assertEqual(d_from, monday)
        self.assertEqual(d_to, monday)

    def test_week_on_sunday(self):
        # 2025-06-22 is Sunday; Monday = 2025-06-16
        sunday = date(2025, 6, 22)
        monday = date(2025, 6, 16)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = sunday
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("week")
        self.assertEqual(d_from, monday)
        self.assertEqual(d_to, sunday)

    def test_week_spans_month_boundary(self):
        # 2025-07-02 is Wednesday; Monday = 2025-06-30
        anchor = date(2025, 7, 2)
        monday = date(2025, 6, 30)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = anchor
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("week")
        self.assertEqual(d_from, monday)
        self.assertEqual(d_to, anchor)


class TestResolvePeriodMonth(SimpleTestCase):
    """period='month' → first of current month to today."""

    def test_month_mid_month(self):
        anchor = date(2025, 6, 15)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = anchor
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("month")
        self.assertEqual(d_from, date(2025, 6, 1))
        self.assertEqual(d_to, anchor)

    def test_month_on_first(self):
        first = date(2025, 6, 1)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = first
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("month")
        self.assertEqual(d_from, first)
        self.assertEqual(d_to, first)

    def test_month_january(self):
        anchor = date(2025, 1, 20)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = anchor
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("month")
        self.assertEqual(d_from, date(2025, 1, 1))
        self.assertEqual(d_to, anchor)


class TestResolvePeriodYear(SimpleTestCase):
    """period='year' → Jan 1 of current year to today."""

    def test_year_mid_year(self):
        anchor = date(2025, 6, 15)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = anchor
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("year")
        self.assertEqual(d_from, date(2025, 1, 1))
        self.assertEqual(d_to, anchor)

    def test_year_on_jan_first(self):
        jan1 = date(2025, 1, 1)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = jan1
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("year")
        self.assertEqual(d_from, jan1)
        self.assertEqual(d_to, jan1)

    def test_year_on_dec_31(self):
        dec31 = date(2025, 12, 31)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = dec31
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("year")
        self.assertEqual(d_from, date(2025, 1, 1))
        self.assertEqual(d_to, dec31)


class TestResolvePeriodAll(SimpleTestCase):
    """period='all' → (None, None)."""

    def test_all_returns_none_none(self):
        d_from, d_to = resolve_period("all")
        self.assertIsNone(d_from)
        self.assertIsNone(d_to)

    def test_all_ignores_date_params(self):
        d_from, d_to = resolve_period("all", "2020-01-01", "2020-12-31")
        self.assertIsNone(d_from)
        self.assertIsNone(d_to)

    def test_all_case_insensitive(self):
        d_from, d_to = resolve_period("ALL")
        self.assertIsNone(d_from)
        self.assertIsNone(d_to)


class TestResolvePeriodCustom(SimpleTestCase):
    """period='custom' → parses date_from/date_to strings."""

    def test_custom_valid_dates(self):
        d_from, d_to = resolve_period("custom", "2025-01-01", "2025-03-31")
        self.assertEqual(d_from, date(2025, 1, 1))
        self.assertEqual(d_to, date(2025, 3, 31))

    def test_custom_only_from(self):
        anchor = date(2025, 6, 15)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = anchor
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("custom", "2025-01-01", None)
        self.assertEqual(d_from, date(2025, 1, 1))
        self.assertEqual(d_to, anchor)

    def test_custom_only_to(self):
        anchor = date(2025, 6, 15)
        first_of_month = date(2025, 6, 1)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = anchor
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("custom", None, "2025-06-30")
        self.assertEqual(d_from, first_of_month)
        self.assertEqual(d_to, date(2025, 6, 30))

    def test_custom_invalid_from_falls_back(self):
        anchor = date(2025, 6, 15)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = anchor
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("custom", "not-a-date", "2025-06-30")
        self.assertEqual(d_from, date(2025, 6, 1))  # fallback = first of month
        self.assertEqual(d_to, date(2025, 6, 30))

    def test_custom_invalid_to_falls_back(self):
        anchor = date(2025, 6, 15)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = anchor
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("custom", "2025-06-01", "bad")
        self.assertEqual(d_from, date(2025, 6, 1))
        self.assertEqual(d_to, anchor)  # fallback = today

    def test_custom_both_none_fallback_to_current_month(self):
        anchor = date(2025, 6, 15)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = anchor
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("custom", None, None)
        self.assertEqual(d_from, date(2025, 6, 1))
        self.assertEqual(d_to, anchor)


class TestResolvePeriodNoneAndUnknown(SimpleTestCase):
    """None period and unknown strings behave like 'custom'."""

    def test_none_period_treats_as_custom(self):
        anchor = date(2025, 6, 15)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = anchor
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period(None, "2025-06-01", "2025-06-15")
        self.assertEqual(d_from, date(2025, 6, 1))
        self.assertEqual(d_to, date(2025, 6, 15))

    def test_unknown_period_treats_as_custom(self):
        anchor = date(2025, 6, 15)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = anchor
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("quarterly", "2025-04-01", "2025-06-30")
        self.assertEqual(d_from, date(2025, 4, 1))
        self.assertEqual(d_to, date(2025, 6, 30))

    def test_empty_string_period_treats_as_custom(self):
        anchor = date(2025, 6, 15)
        with patch("apps.reports.period_utils.date") as mock_date:
            mock_date.today.return_value = anchor
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            d_from, d_to = resolve_period("", None, None)
        self.assertEqual(d_from, date(2025, 6, 1))
        self.assertEqual(d_to, anchor)


class TestValidPeriodsConstant(SimpleTestCase):
    def test_all_canonical_periods_in_set(self):
        for p in ("today", "week", "month", "year", "all", "custom"):
            self.assertIn(p, VALID_PERIODS)

    def test_valid_periods_is_frozenset(self):
        self.assertIsInstance(VALID_PERIODS, frozenset)


class TestPeriodLabel(SimpleTestCase):
    """period_label() returns correct human-readable strings."""

    def test_today_label(self):
        self.assertEqual(period_label("today"), "Today")

    def test_week_label(self):
        self.assertEqual(period_label("week"), "This Week")

    def test_month_label(self):
        self.assertEqual(period_label("month"), "This Month")

    def test_year_label(self):
        self.assertEqual(period_label("year"), "This Year")

    def test_all_label(self):
        self.assertEqual(period_label("all"), "All Time")

    def test_custom_with_dates(self):
        d_from = date(2025, 1, 1)
        d_to = date(2025, 3, 31)
        label = period_label("custom", d_from, d_to)
        self.assertIn("01 Jan 2025", label)
        self.assertIn("31 Mar 2025", label)

    def test_custom_without_dates(self):
        self.assertEqual(period_label("custom"), "Custom Range")

    def test_none_period_returns_custom_range(self):
        self.assertEqual(period_label(None), "Custom Range")

    def test_unknown_period_returns_custom_range(self):
        self.assertEqual(period_label("quarterly"), "Custom Range")

    def test_label_case_insensitive(self):
        self.assertEqual(period_label("TODAY"), "Today")
        self.assertEqual(period_label("Month"), "This Month")
