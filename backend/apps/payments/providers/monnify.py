"""
Monnify driver — reserved (one-time) account numbers and hosted checkout.

Monnify is the collections rail behind Moniepoint, so a merchant already banking
with Moniepoint can use their existing keys here. Its reserved accounts are the
closest thing available to "a fresh account number per sale, confirmed the second
the money lands, from any bank" without a terminal partnership.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from decimal import Decimal

from .base import (
    CheckoutSession, PaymentEvent, PaymentProvider, PaymentProviderError,
    VirtualAccountDetails,
)

LIVE = "https://api.monnify.com"
SANDBOX = "https://sandbox.monnify.com"


class MonnifyProvider(PaymentProvider):
    slug = "monnify"
    label = "Monnify / Moniepoint"
    supports_virtual_accounts = True

    def __init__(self, config):
        super().__init__(config)
        self._token = None
        self._token_expires = 0.0

    @property
    def base(self):
        return SANDBOX if self.config.use_sandbox else LIVE

    def _login(self) -> str:
        """Monnify uses short-lived bearer tokens obtained with Basic auth."""
        if self._token and time.time() < self._token_expires:
            return self._token
        if not (self.config.public_key and self.config.secret_key):
            raise PaymentProviderError(
                "Monnify API key and secret are missing. Add them in "
                "Settings → Payments."
            )
        basic = base64.b64encode(
            f"{self.config.public_key}:{self.config.secret_key}".encode()
        ).decode()
        body = self._request(
            "POST", f"{self.base}/api/v1/auth/login",
            headers={"Authorization": f"Basic {basic}"},
        )
        data = body.get("responseBody") or {}
        token = data.get("accessToken")
        if not token:
            raise PaymentProviderError("Monnify did not return an access token.")
        self._token = token
        # Refresh a minute early so a long request can't run past expiry.
        self._token_expires = time.time() + max(int(data.get("expiresIn") or 3600) - 60, 60)
        return token

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self._login()}", "Content-Type": "application/json"}

    # ── Outbound ────────────────────────────────────────────────────────────
    def initialize_checkout(self, *, reference, amount: Decimal, email: str,
                            callback_url: str, metadata: dict) -> CheckoutSession:
        if not self.config.contract_code:
            raise PaymentProviderError(
                "Monnify contract code is missing. Add it in Settings → Payments."
            )
        body = self._request(
            "POST", f"{self.base}/api/v1/merchant/transactions/init-transaction",
            headers=self._auth_headers(),
            json={
                "amount": float(Decimal(str(amount))),
                "customerName": metadata.get("customer_name") or "Customer",
                "customerEmail": email or "customer@audity.app",
                "paymentReference": reference,
                "paymentDescription": metadata.get("description") or reference,
                "currencyCode": "NGN",
                "contractCode": self.config.contract_code,
                "redirectUrl": callback_url,
                "metaData": metadata,
            },
        )
        data = body.get("responseBody") or {}
        url = data.get("checkoutUrl")
        if not url:
            raise PaymentProviderError("Monnify did not return a payment link.")
        return CheckoutSession(
            reference=data.get("paymentReference") or reference,
            url=url,
            provider_reference=str(data.get("transactionReference") or ""),
            raw=data,
        )

    def create_virtual_account(self, *, reference, amount: Decimal, customer_name: str,
                               customer_email: str, metadata: dict) -> VirtualAccountDetails:
        if not self.config.contract_code:
            raise PaymentProviderError(
                "Monnify contract code is missing. Add it in Settings → Payments."
            )
        body = self._request(
            "POST", f"{self.base}/api/v1/bank-transfer/reserved-accounts",
            headers=self._auth_headers(),
            json={
                "accountReference": reference,
                "accountName": (customer_name or "Customer")[:50],
                "currencyCode": "NGN",
                "contractCode": self.config.contract_code,
                "customerEmail": customer_email or f"{reference.lower()}@audity.app",
                "customerName": (customer_name or "Customer")[:50],
                # One account, one sale: locking the amount lets Monnify reject
                # an underpayment instead of us discovering it afterwards.
                "restrictPaymentToMatchingAmount": True,
                "reservedAccountType": "INVOICE",
                "getAllAvailableBanks": False,
                "preferredBanks": [self.config.preferred_bank or "035"],
            },
        )
        data = body.get("responseBody") or {}
        accounts = data.get("accounts") or []
        if not accounts:
            raise PaymentProviderError("Monnify did not return an account number.")
        first = accounts[0]
        return VirtualAccountDetails(
            account_number=first.get("accountNumber", ""),
            bank_name=first.get("bankName", ""),
            account_name=data.get("accountName") or customer_name,
            reference=reference,
            provider_reference=str(data.get("accountReference") or reference),
            raw=data,
        )

    # ── Inbound ─────────────────────────────────────────────────────────────
    def verify_signature(self, raw_body: bytes, headers) -> bool:
        received = (headers.get("HTTP_MONNIFY_SIGNATURE") or "").strip()
        secret = self.config.webhook_secret or self.config.secret_key
        if not received or not secret:
            return False
        expected = hmac.new(secret.encode(), msg=raw_body, digestmod=hashlib.sha512).hexdigest()
        try:
            return hmac.compare_digest(expected, received)
        except (TypeError, ValueError):
            return False

    def parse_event(self, payload: dict) -> PaymentEvent | None:
        event = payload.get("eventType") or ""
        data = payload.get("eventData") or {}
        if event not in ("SUCCESSFUL_TRANSACTION", "FAILED_TRANSACTION"):
            return None

        method = (data.get("paymentMethod") or "").upper()
        return PaymentEvent(
            event_id=str(data.get("transactionReference") or data.get("paymentReference") or ""),
            reference=str(data.get("paymentReference") or ""),
            amount=Decimal(str(data.get("amountPaid") or 0)),
            status="success" if event == "SUCCESSFUL_TRANSACTION" else "failed",
            channel={"ACCOUNT_TRANSFER": "bank_transfer", "CARD": "card",
                     "USSD": "bank_transfer"}.get(method, method.lower()),
            currency=data.get("currency") or "NGN",
            provider_reference=str(data.get("transactionReference") or ""),
            raw=data,
        )
