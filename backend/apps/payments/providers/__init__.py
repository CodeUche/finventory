"""Provider registry.

Adding a gateway means writing a driver and listing it here; nothing else in the
codebase names a provider directly.
"""

from .base import (  # noqa: F401
    CheckoutSession, PaymentEvent, PaymentProvider, PaymentProviderError,
    VirtualAccountDetails,
)
from .monnify import MonnifyProvider
from .paystack import PaystackProvider

_DRIVERS = {p.slug: p for p in (PaystackProvider, MonnifyProvider)}

PROVIDER_CHOICES = [(slug, cls.label) for slug, cls in _DRIVERS.items()]


def get_provider(config) -> PaymentProvider:
    """Build the driver for a merchant's gateway configuration."""
    driver = _DRIVERS.get(config.provider)
    if driver is None:
        raise PaymentProviderError(f"'{config.provider}' is not a supported payment provider.")
    return driver(config)


def supports_virtual_accounts(provider_slug: str) -> bool:
    driver = _DRIVERS.get(provider_slug)
    return bool(driver and driver.supports_virtual_accounts)
