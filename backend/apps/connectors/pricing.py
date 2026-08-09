"""
Connector add-on pricing — single source of truth for the ₦4,500/connector/
month figure, imported by both apps.connectors.views (to display it) and
apps.subscriptions.payment_engine (to charge it), so the number can never
drift between the two call sites.
"""

from decimal import Decimal

CONNECTOR_ADDON_MONTHLY_PRICE = Decimal("4500.00")
# No discount applied for annual billing unless/until product decides
# otherwise — flat 12x the monthly price.
CONNECTOR_ADDON_ANNUAL_PRICE = CONNECTOR_ADDON_MONTHLY_PRICE * 12


def price_for_interval(interval: str) -> Decimal:
    from .models import ConnectorAddonSubscription

    if interval == ConnectorAddonSubscription.Interval.ANNUAL:
        return CONNECTOR_ADDON_ANNUAL_PRICE
    return CONNECTOR_ADDON_MONTHLY_PRICE
