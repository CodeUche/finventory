"""
Period resolution utility for report date ranges.

Converts a period shortcut (today/week/month/year/all) or a custom
date_from/date_to pair into a concrete (date_from, date_to) tuple.

Both values are None when period='all' — callers must skip date
filtering entirely in that case.
"""

from datetime import date, datetime, timedelta
from typing import Optional, Tuple

# Canonical period names accepted by all report endpoints
VALID_PERIODS = frozenset({"today", "week", "month", "year", "ytd", "all", "custom"})

_DATE_FMT = "%Y-%m-%d"


def resolve_period(
    period: Optional[str],
    date_from_str: Optional[str] = None,
    date_to_str: Optional[str] = None,
) -> Tuple[Optional[date], Optional[date]]:
    """
    Resolve a period shortcut or custom date strings to a (date_from, date_to) tuple.

    Args:
        period:        'today' | 'week' | 'month' | 'year' | 'all' | 'custom' | None
        date_from_str: ISO date string (YYYY-MM-DD), used when period='custom'
        date_to_str:   ISO date string (YYYY-MM-DD), used when period='custom'

    Returns:
        (date_from, date_to) — both are None only for period='all'.
        Falls back to the current-calendar-month range for invalid input.
    """
    today = date.today()
    canonical = (period or "custom").lower().strip()

    if canonical == "today":
        return today, today

    if canonical == "week":
        # ISO week: Monday → today
        return today - timedelta(days=today.weekday()), today

    if canonical == "month":
        return today.replace(day=1), today

    if canonical in ("year", "ytd", "1y"):
        return today.replace(month=1, day=1), today

    if canonical == "all":
        return None, None

    # custom / unknown / fallback — parse explicit dates
    d_from = _parse_date(date_from_str, default=today.replace(day=1))
    d_to = _parse_date(date_to_str, default=today)
    return d_from, d_to


def period_label(
    period: Optional[str],
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> str:
    """Return a human-readable label for the resolved period (used in export titles)."""
    canonical = (period or "custom").lower().strip()
    labels = {
        "today": "Today",
        "week": "This Week",
        "month": "This Month",
        "year": "This Year",
        "ytd": "Year to Date",
        "1y": "Last 12 Months",
        "all": "All Time",
    }
    if canonical in labels:
        return labels[canonical]
    if date_from and date_to:
        return f"{date_from.strftime('%d %b %Y')} – {date_to.strftime('%d %b %Y')}"
    return "Custom Range"


def _parse_date(value: Optional[str], default: date) -> date:
    """Parse an ISO date string; return *default* on any failure."""
    if not value:
        return default
    try:
        return datetime.strptime(value.strip(), _DATE_FMT).date()
    except (ValueError, AttributeError):
        return default
