"""Paystack driver — hosted checkout (card, USSD, bank) and dedicated accounts."""

from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal

from .base import (
    CheckoutSession, PaymentEvent, PaymentProvider, PaymentProviderError,
    VirtualAccountDetails,
)

API = "https://api.paystack.co"

# Paystack works in kobo; every amount crossing the wire is integer minor units.
MINOR = Decimal("100")


class PaystackProvider(PaymentProvider):
    slug = "paystack"
    label = "Paystack"
    supports_virtual_accounts = True

    def _headers(self):
        if not self.config.secret_key:
            raise PaymentProviderError(
                "Paystack secret key is missing. Add it in Settings → Payment Gateways."
            )
        return {
            "Authorization": f"Bearer {self.config.secret_key}",
            "Content-Type": "application/json",
        }

    # ── Outbound ────────────────────────────────────────────────────────────
    def initialize_checkout(self, *, reference, amount: Decimal, email: str,
                            callback_url: str, metadata: dict) -> CheckoutSession:
        body = self._request("POST", f"{API}/transaction/initialize", headers=self._headers(), json={
            "reference": reference,
            "amount": int((Decimal(str(amount)) * MINOR).to_integral_value()),
            "email": email or "customer@audity.app",
            "callback_url": callback_url,
            "metadata": metadata,
        })
        data = body.get("data") or {}
        url = data.get("authorization_url")
        if not url:
            raise PaymentProviderError("Paystack did not return a payment link.")
        return CheckoutSession(
            reference=data.get("reference") or reference,
            url=url,
            provider_reference=str(data.get("access_code") or ""),
            raw=data,
        )

    def create_virtual_account(self, *, reference, amount: Decimal, customer_name: str,
                               customer_email: str, metadata: dict) -> VirtualAccountDetails:
        """Paystack issues a dedicated account against a customer, not an amount.

        We therefore create (or reuse) the customer, then assign an account. The
        amount is enforced on our side when the transfer notification arrives.
        """
        headers = self._headers()
        names = (customer_name or "Customer").split(" ", 1)
        customer = self._request("POST", f"{API}/customer", headers=headers, json={
            "email": customer_email or f"{reference.lower()}@audity.app",
            "first_name": names[0],
            "last_name": names[1] if len(names) > 1 else "",
        })
        customer_code = (customer.get("data") or {}).get("customer_code")
        if not customer_code:
            raise PaymentProviderError("Paystack did not return a customer record.")

        body = self._request("POST", f"{API}/dedicated_account", headers=headers, json={
            "customer": customer_code,
            "preferred_bank": self.config.preferred_bank or "wema-bank",
        })
        data = (body.get("data") or {})
        number = data.get("account_number")
        if not number:
            raise PaymentProviderError("Paystack did not return an account number.")
        return VirtualAccountDetails(
            account_number=number,
            bank_name=(data.get("bank") or {}).get("name", ""),
            account_name=data.get("account_name") or customer_name,
            reference=reference,
            provider_reference=str(data.get("id") or customer_code),
            raw=data,
        )

    # ── Inbound ─────────────────────────────────────────────────────────────
    def verify_signature(self, raw_body: bytes, headers) -> bool:
        received = (headers.get("HTTP_X_PAYSTACK_SIGNATURE") or "").strip()
        secret = self.config.webhook_secret or self.config.secret_key
        if not received or not secret:
            return False
        expected = hmac.new(secret.encode(), msg=raw_body, digestmod=hashlib.sha512).hexdigest()
        try:
            return hmac.compare_digest(expected, received)
        except (TypeError, ValueError):
            return False

    def parse_event(self, payload: dict) -> PaymentEvent | None:
        event = payload.get("event") or ""
        data = payload.get("data") or {}
        if event not in ("charge.success", "charge.failed"):
            return None

        # Transfers into a dedicated account arrive as charge.success with a
        # dedicated_nuban channel and no reference we issued — fall back to the
        # account number so the virtual account can be matched.
        channel = data.get("channel") or ""
        reference = data.get("reference") or ""
        if channel == "dedicated_nuban":
            account = ((data.get("metadata") or {}).get("receiver_account_number")
                       or (data.get("authorization") or {}).get("receiver_bank_account_number"))
            reference = reference or account or ""

        return PaymentEvent(
            event_id=str(data.get("id") or reference),
            reference=reference,
            amount=(Decimal(str(data.get("amount") or 0)) / MINOR),
            status="success" if event == "charge.success" else "failed",
            channel={"dedicated_nuban": "bank_transfer", "card": "card",
                     "bank": "bank_transfer"}.get(channel, channel),
            currency=data.get("currency") or "NGN",
            provider_reference=str(data.get("id") or ""),
            raw=data,
        )
