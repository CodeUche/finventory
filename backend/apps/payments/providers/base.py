"""
Payment provider interface.

Audity is a software vendor, not a payment aggregator: money never touches an
Audity account. Every provider call is made with the *merchant's own* API keys
held on their PaymentGatewayConfig, and settles into the merchant's own bank
account. That keeps us out of CBN licensing territory entirely.

A provider driver has three jobs:

  1. ``initialize_checkout``      — hand back a URL the payer can open (card, USSD…).
  2. ``create_virtual_account``   — reserve a one-time account number for a transfer.
  3. ``parse_event``              — turn a webhook body into a normalised PaymentEvent.

Anything provider-specific (field names, auth scheme, signature algorithm) stays
inside the driver. Callers only ever see the dataclasses below.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Providers get one shot; a slow gateway must never hold a POS sale open.
HTTP_TIMEOUT = 15


class PaymentProviderError(Exception):
    """A provider rejected the request or could not be reached.

    Carries a message safe to show a merchant — never a raw provider payload,
    which can contain key material.
    """


@dataclass
class CheckoutSession:
    """A hosted payment page the payer opens in a browser."""

    reference: str
    url: str
    provider_reference: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class VirtualAccountDetails:
    """A one-time bank account number issued for a single payment.

    The payer transfers from any bank; the provider notifies us the moment the
    money lands, which is what makes 'fake alert' screenshots useless.
    """

    account_number: str
    bank_name: str
    account_name: str
    reference: str
    provider_reference: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class PaymentEvent:
    """A normalised 'money moved' notification.

    ``event_id`` is what makes replay handling possible — every provider resends
    webhooks, so the same event must be recognisable across deliveries.
    """

    event_id: str
    reference: str
    amount: Decimal
    status: str                # 'success' | 'failed' | 'ignored'
    channel: str = ""          # 'card' | 'bank_transfer' | 'pos' | ''
    currency: str = "NGN"
    provider_reference: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status == "success"


class PaymentProvider:
    """Base driver. Subclasses implement whatever the provider actually supports."""

    #: Registry key and the value stored on PaymentGatewayConfig.provider.
    slug: str = ""
    #: Human name for error messages and the settings screen.
    label: str = ""
    #: Whether this provider can reserve one-time account numbers.
    supports_virtual_accounts: bool = False

    def __init__(self, config):
        self.config = config

    # ── Capabilities ────────────────────────────────────────────────────────
    def initialize_checkout(self, *, reference, amount: Decimal, email: str,
                            callback_url: str, metadata: dict) -> CheckoutSession:
        raise PaymentProviderError(f"{self.label} does not support hosted checkout.")

    def create_virtual_account(self, *, reference, amount: Decimal, customer_name: str,
                               customer_email: str, metadata: dict) -> VirtualAccountDetails:
        raise PaymentProviderError(f"{self.label} does not support one-time account numbers.")

    # ── Inbound ─────────────────────────────────────────────────────────────
    def verify_signature(self, raw_body: bytes, headers) -> bool:
        raise NotImplementedError

    def parse_event(self, payload: dict) -> PaymentEvent | None:
        """Return a PaymentEvent, or None when the event is not about a payment."""
        raise NotImplementedError

    # ── Shared HTTP plumbing ────────────────────────────────────────────────
    def _request(self, method: str, url: str, *, headers=None, json=None) -> dict:
        try:
            response = requests.request(
                method, url, headers=headers, json=json, timeout=HTTP_TIMEOUT,
            )
        except requests.Timeout:
            raise PaymentProviderError(
                f"{self.label} did not respond in time. Please try again."
            )
        except requests.RequestException as exc:
            logger.warning("%s request failed: %s", self.label, exc)
            raise PaymentProviderError(f"Could not reach {self.label}. Please try again.")

        try:
            body: Any = response.json()
        except ValueError:
            body = {}

        if response.status_code >= 400:
            # Provider messages are safe to surface; they describe the merchant's
            # own misconfiguration ("Invalid key", "Account not found").
            detail = ""
            if isinstance(body, dict):
                detail = body.get("message") or body.get("responseMessage") or ""
            logger.warning("%s returned %s: %s", self.label, response.status_code, detail)
            raise PaymentProviderError(detail or f"{self.label} rejected the request.")

        return body if isinstance(body, dict) else {}
