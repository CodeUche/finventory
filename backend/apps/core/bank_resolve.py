"""
Shared Nigerian NUBAN account-name resolution.

Tries Paystack first, then automatically falls back to Flutterwave if
Paystack fails (wrong key, KYC/live-mode restrictions, rate limit, network
error, etc.) or isn't configured. Both providers resolve against the same
underlying NIBSS NIP rails and accept the same numeric bank codes, so a
single (account_number, bank_code) pair works against either without any
provider-specific mapping.

This makes account-name auto-resolution resilient instead of depending on
a single provider's account status — used everywhere a bank account name
needs to resolve (Settings, Employees/payroll, Payment Information/Credits).
"""

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)


class BankResolveError(Exception):
    """Raised when no configured provider could resolve the account."""


def _resolve_via_paystack(account_number: str, bank_code: str) -> str:
    secret_key = getattr(settings, "PAYSTACK_SECRET_KEY", "").strip()
    if not secret_key:
        raise BankResolveError("Paystack not configured")

    url = (
        f"https://api.paystack.co/bank/resolve"
        f"?account_number={account_number}&bank_code={bank_code}"
    )
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {secret_key}",
        # Paystack's API sits behind Cloudflare, which blocks requests with no
        # User-Agent (or a non-browser-looking one) as bots — without this,
        # every call from a datacenter IP (e.g. Railway) gets a Cloudflare
        # error page (HTTP 403, "error code: 1010") instead of reaching Paystack.
        "User-Agent": "Mozilla/5.0 (compatible; AudityBackend/1.0)",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
        account_name = body.get("data", {}).get("account_name")
        if not account_name:
            raise BankResolveError(body.get("message") or "Paystack returned no account name")
        return account_name
    except urllib.error.HTTPError as e:
        msg = "Paystack lookup failed"
        try:
            msg = json.loads(e.read().decode()).get("message", msg)
        except Exception:
            pass
        logger.info("Paystack bank resolve failed (%s): %s", e.code, msg)
        raise BankResolveError(msg) from e
    except BankResolveError:
        raise
    except Exception as e:
        logger.info("Paystack bank resolve error: %s", e)
        raise BankResolveError(str(e)) from e


def _resolve_via_flutterwave(account_number: str, bank_code: str) -> str:
    secret_key = getattr(settings, "FLUTTERWAVE_SECRET_KEY", "").strip()
    if not secret_key:
        raise BankResolveError("Flutterwave not configured")

    payload = json.dumps({"account_number": account_number, "account_bank": bank_code}).encode()
    req = urllib.request.Request(
        "https://api.flutterwave.com/v3/accounts/resolve",
        data=payload,
        headers={
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; AudityBackend/1.0)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
        account_name = body.get("data", {}).get("account_name")
        if not account_name:
            raise BankResolveError(body.get("message") or "Flutterwave returned no account name")
        return account_name
    except urllib.error.HTTPError as e:
        msg = "Flutterwave lookup failed"
        try:
            msg = json.loads(e.read().decode()).get("message", msg)
        except Exception:
            pass
        logger.info("Flutterwave bank resolve failed (%s): %s", e.code, msg)
        raise BankResolveError(msg) from e
    except BankResolveError:
        raise
    except Exception as e:
        logger.info("Flutterwave bank resolve error: %s", e)
        raise BankResolveError(str(e)) from e


def resolve_account_name(account_number: str, bank_code: str) -> str:
    """
    Returns the resolved account holder name, trying Paystack then
    Flutterwave. Raises BankResolveError with a combined message if both
    providers fail or neither is configured.
    """
    errors = []
    for resolver in (_resolve_via_paystack, _resolve_via_flutterwave):
        try:
            return resolver(account_number, bank_code)
        except BankResolveError as exc:
            errors.append(str(exc))

    raise BankResolveError(
        "Could not resolve account name. " + " / ".join(errors) if errors
        else "No bank resolution provider is configured."
    )
