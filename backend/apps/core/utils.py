"""
Shared utility functions used across multiple apps.
"""

import hashlib
import secrets
import string
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def generate_reference(prefix: str = "", length: int = 10) -> str:
    """
    Generate a cryptographically-random alphanumeric reference code.

    Example: generate_reference("INV") → "INV-A3F9K2M7P1"
    """
    alphabet = string.ascii_uppercase + string.digits
    code = "".join(secrets.choice(alphabet) for _ in range(length))
    return f"{prefix}-{code}" if prefix else code


def round_money(amount: Decimal, places: int = 2) -> Decimal:
    """Round a Decimal to the given number of decimal places using ROUND_HALF_UP."""
    quantize_str = Decimal("0." + "0" * places)
    return amount.quantize(quantize_str, rounding=ROUND_HALF_UP)


def calculate_percentage(value: Decimal, percentage: Decimal) -> Decimal:
    """Calculate `percentage`% of `value`. Returns Decimal."""
    return round_money((value * percentage) / Decimal("100"))


def mask_sensitive(value: str, visible_chars: int = 4) -> str:
    """
    Mask sensitive strings (e.g., card numbers, account IDs).
    Example: "1234567890" → "******7890"
    """
    if len(value) <= visible_chars:
        return "*" * len(value)
    return "*" * (len(value) - visible_chars) + value[-visible_chars:]


def safe_divide(numerator: Any, denominator: Any, default: Any = Decimal("0")) -> Decimal:
    """Division that returns `default` instead of raising ZeroDivisionError."""
    try:
        if denominator == 0:
            return default
        return Decimal(str(numerator)) / Decimal(str(denominator))
    except Exception:
        return default


def get_client_ip(request) -> str:
    """Extract the real client IP, respecting X-Forwarded-For (behind proxies)."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        # Take the first IP (client IP), ignore proxy chain
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")
