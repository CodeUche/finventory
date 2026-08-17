"""
Thin client for Telegram's Bot API (api.telegram.org) — the ONE shared
Audity bot (@AudityNotifyBot per production TELEGRAM_BOT_TOKEN), used to
notify orgs that link their own Telegram chat to Audity.

Architecture note — read before touching this file or apps.connectors.services'
TelegramLinkService: Telegram is deliberately NOT modeled like
Slack/Sheets/Drive/Calendar. Those four are per-org OAuth grants brokered by
Nango. Telegram has no OAuth here at all — there is exactly one bot token
for the whole platform, and a specific org is correlated to a specific
Telegram chat via a short-lived, unguessable linking code:

    1. Org clicks "Connect" -> backend mints a random opaque code (same
       entropy/opaque-token discipline as ConnectorConnection.
       pending_session_token, which this literally reuses as storage) and
       returns a `t.me/<bot_username>?start=<code>` deep link — Telegram's
       own /start deep-link convention.
    2. The org's user taps it in Telegram, which sends "/start <code>" to
       the bot as an ordinary message.
    3. Audity's webhook (apps.connectors.views.telegram_webhook) receives
       that message via Telegram's Bot API webhook mechanism (see
       set_webhook below), looks up which ConnectorConnection the code
       belongs to, and stores the resulting chat_id.
    4. Sending a notification later is a direct call to sendMessage with
       that chat_id — NEVER through Nango's Proxy API. Nango has no OAuth
       token of its own to proxy here; routing through Nango would be
       nonsensical since Nango's entire value (token custody/refresh)
       doesn't apply to a static shared bot token.

Auth is a single TELEGRAM_BOT_TOKEN (server-side only; already provisioned
as a Railway env var on audity-backend). Every entry point fails loudly
(TelegramNotConfiguredError) rather than silently no-op-ing when the token
is absent — same "visible gap, not a silent no-op" discipline as
apps.connectors.nango's NangoNotConfiguredError.
"""

from __future__ import annotations

import hmac
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"
REQUEST_TIMEOUT = (5, 15)  # (connect, read) seconds — mirrors apps.connectors.nango


class TelegramNotConfiguredError(Exception):
    """Raised when TELEGRAM_BOT_TOKEN is unset. Distinct from TelegramAPIError
    for the same reason NangoNotConfiguredError is distinct from
    NangoAPIError: callers (and tests) need to tell "not provisioned yet"
    apart from "the API rejected/couldn't be reached"."""


class TelegramAPIError(Exception):
    """Raised when a Telegram API call could not be completed at the
    transport level (network error) — NOT raised for an ordinary API-level
    failure (e.g. "chat not found"), which callers inspect via the returned
    Response's status_code/body instead, same convention as nango.proxy."""


def _token() -> str:
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise TelegramNotConfiguredError(
            "TELEGRAM_BOT_TOKEN is not configured. The Telegram connector cannot be used "
            "until it is set as an environment variable on the backend service."
        )
    return token


def require_configured() -> None:
    """Cheap, no-network check that TELEGRAM_BOT_TOKEN exists — for callers
    that need to fail loudly before doing anything else (e.g. minting a
    linking code the user would otherwise be handed for a bot that can't
    actually respond). Mirrors nango._secret_key()'s settings-only check."""
    _token()


def bot_username() -> str:
    """Used to build the t.me/<username>?start=<code> deep link. Overridable
    via env in case the bot is ever renamed; defaults to the bot already
    live in production."""
    return getattr(settings, "TELEGRAM_BOT_USERNAME", "") or "AudityNotifyBot"


def webhook_secret() -> str:
    return getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "") or ""


def _call(method: str, payload: dict) -> requests.Response:
    url = f"{_API_BASE}/bot{_token()}/{method}"
    try:
        resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.error("Telegram API call failed (%s): %s", method, exc)
        raise TelegramAPIError(f"Could not reach Telegram ({method}). Please try again.") from exc
    return resp


def send_message(*, chat_id, text: str, parse_mode: str = "Markdown") -> requests.Response:
    """
    POST .../sendMessage — mirrors nango.proxy's contract: returns the raw
    Response, caller inspects `.json()["ok"]` (Telegram's own success field,
    conveniently the same shape as Slack's `ok` field) rather than this
    function raising on an ordinary API-level rejection.
    """
    return _call("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse_mode})


def get_me() -> requests.Response:
    """Read-only diagnostic — confirms the token is valid and returns the
    bot's own identity (username, etc)."""
    return _call("getMe", {})


def set_webhook(*, url: str, secret_token: str | None = None) -> requests.Response:
    """
    One-time setup call — see the `setup_telegram_webhook` management
    command. Registers Audity's webhook endpoint with Telegram so incoming
    /start messages are delivered there instead of requiring us to poll.
    NEVER called from request-serving code — this reconfigures the live
    bot's single global webhook target for every org at once.
    """
    payload = {"url": url, "allowed_updates": ["message"]}
    if secret_token:
        payload["secret_token"] = secret_token
    return _call("setWebhook", payload)


def verify_webhook_secret(received: str) -> bool:
    """
    Optional hardening: if TELEGRAM_WEBHOOK_SECRET is configured, Telegram
    echoes it back on every webhook call in the
    X-Telegram-Bot-Api-Secret-Token header (registered via set_webhook's
    secret_token param). Unlike Nango's HMAC-signed webhooks, this is not
    strictly load-bearing for correctness here: the /start linking code
    itself is an unguessable, single-use, ~30-minute-lived secret (see
    TelegramLinkService in apps.connectors.services), so a forged webhook
    call still cannot activate a connection without already knowing that
    code. This check is defense-in-depth that activates automatically once
    the secret is configured on both sides, and does not block the feature
    before then (returns True — "allow" — when unconfigured).
    """
    configured = webhook_secret()
    if not configured:
        return True
    return hmac.compare_digest(configured, received or "")
