"""
Thin client for Nango's server-to-server API (nango.dev).

Nango is an embedded-auth + API-proxy layer, NOT a workflow engine — nothing
here lets Nango make a business decision. It only ever does two things for
Audity:
    1. Hosts the OAuth consent flow and stores/refreshes the resulting
       tokens (Connect Sessions API — see create_connect_session).
    2. Proxies an authenticated HTTP call to the third-party API on our
       behalf, using the tokens it holds (Proxy API — see proxy).

Shapes below are taken from Nango's own docs (fetched during implementation,
Aug 2026):
    - POST https://api.nango.dev/connect/sessions  → { data: { token,
      connect_link, expires_at } }
    - POST https://api.nango.dev/proxy/{path}       → mirrors the target
      API's response verbatim.
    - Outgoing webhooks are signed with header `X-Nango-Hmac-Sha256`:
      hex(hmac_sha256(webhook_signing_key, raw_body)).
Auth is a single NANGO_SECRET_KEY (server-side only) — Nango's current
Connect-Sessions API has no separate client-facing "public key" the way
Paystack does; the frontend instead uses a short-lived session token minted
here via the secret key. Every entry point below fails loudly
(NangoNotConfiguredError) rather than silently no-op-ing when the key is
absent, so a missing key is visible in logs/API responses instead of
masquerading as "it just doesn't work."
"""

from __future__ import annotations

import hashlib
import hmac
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_NANGO_API_BASE = "https://api.nango.dev"
REQUEST_TIMEOUT = (5, 15)  # (connect, read) seconds — mirrors apps.integrations.services

# Maps our internal connector_key -> the Nango "integration id" (a.k.a.
# providerConfigKey) that must be configured in the Nango dashboard for that
# provider. Overridable via env because the product owner controls the
# actual names chosen when they set up the Nango account/integrations.
_INTEGRATION_ID_SETTINGS = {
    "slack": "NANGO_SLACK_INTEGRATION_ID",
    "google_sheets": "NANGO_GOOGLE_SHEETS_INTEGRATION_ID",
    "google_drive": "NANGO_GOOGLE_DRIVE_INTEGRATION_ID",
    "google_calendar": "NANGO_GOOGLE_CALENDAR_INTEGRATION_ID",
    # "telegram" is deliberately absent — Telegram never goes through Nango
    # (no OAuth grant exists to proxy). Calling integration_id_for("telegram")
    # correctly raises ValueError; see apps.connectors.telegram instead.
}
_INTEGRATION_ID_DEFAULTS = {
    "slack": "slack",
    "google_sheets": "google-sheets",
    "google_drive": "google-drive",
    "google_calendar": "google-calendar",
}


class NangoNotConfiguredError(Exception):
    """Raised when NANGO_SECRET_KEY (or another required Nango setting) is unset.

    Deliberately a distinct exception (not a bare ValueError) so callers —
    and tests — can tell "Nango isn't provisioned yet" apart from "Nango
    rejected this request", and so the API layer can return a clear,
    specific error/503 instead of a generic 400.
    """


class NangoAPIError(Exception):
    """Raised when Nango's API itself returns an error response."""


def _secret_key() -> str:
    key = getattr(settings, "NANGO_SECRET_KEY", "")
    if not key:
        raise NangoNotConfiguredError(
            "NANGO_SECRET_KEY is not configured. Connectors cannot be used until a "
            "Nango account is created and NANGO_SECRET_KEY / NANGO_PUBLIC_KEY are set "
            "as environment variables on the backend service."
        )
    return key


def webhook_signing_key() -> str:
    """
    The key Nango uses to HMAC-sign outgoing webhooks. Nango's dashboard
    exposes this as a distinct "webhook signing key" under Environment
    Settings (separate from the secret API key used for outbound calls) —
    NANGO_WEBHOOK_SECRET is provided for that. Falls back to
    NANGO_SECRET_KEY only so a minimal single-key setup still verifies
    something rather than being silently unable to check anything; once a
    real webhook signing key exists it should be set explicitly.
    """
    key = getattr(settings, "NANGO_WEBHOOK_SECRET", "") or getattr(settings, "NANGO_SECRET_KEY", "")
    if not key:
        raise NangoNotConfiguredError(
            "NANGO_WEBHOOK_SECRET / NANGO_SECRET_KEY are not configured — cannot verify "
            "Nango webhook signatures."
        )
    return key


def integration_id_for(connector_key: str) -> str:
    """The Nango providerConfigKey for our internal connector_key."""
    setting_name = _INTEGRATION_ID_SETTINGS.get(connector_key)
    default = _INTEGRATION_ID_DEFAULTS.get(connector_key)
    if setting_name is None:
        raise ValueError(f"Unknown connector_key: {connector_key!r}")
    return getattr(settings, setting_name, default) or default


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_secret_key()}",
        "Content-Type": "application/json",
    }


def create_connect_session(*, organisation_id: str, connector_key: str, user_email: str) -> dict:
    """
    Server-to-server call to mint a short-lived (30 min) Nango Connect
    session for exactly one integration. The returned `connect_link` is a
    plain HTTPS URL — the frontend opens it via openExternal() on desktop /
    a new tab on web, EXACTLY like the Paystack checkout URL, so no Nango
    frontend SDK is needed and the existing Tauri-vs-web OAuth-handoff
    pattern (see IntegrationsPage's openExternal usage) applies unchanged.

    Returns: { "token": str, "connect_link": str, "expires_at": str }
    Raises: NangoNotConfiguredError, NangoAPIError
    """
    integration_id = integration_id_for(connector_key)
    payload = {
        "allowed_integrations": [integration_id],
        "tags": {
            "organization_id": str(organisation_id),
            "end_user_email": user_email,
        },
    }
    try:
        resp = requests.post(
            f"{_NANGO_API_BASE}/connect/sessions",
            json=payload,
            headers=_headers(),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error("Nango create_connect_session request failed: %s", exc)
        raise NangoAPIError("Could not reach Nango. Please try again.") from exc

    if resp.status_code >= 400:
        logger.error("Nango create_connect_session returned %s: %s", resp.status_code, resp.text[:500])
        raise NangoAPIError(f"Nango rejected the connect session request ({resp.status_code}).")

    data = (resp.json() or {}).get("data") or {}
    if not data.get("token") or not data.get("connect_link"):
        raise NangoAPIError("Nango's connect session response was missing token/connect_link.")
    return data


def get_connection(*, nango_connection_id: str, connector_key: str) -> dict:
    """
    GET /connection/{connection_id}?provider_config_key=... — used by the
    restore/check-status endpoint to confirm a connection actually exists on
    Nango's side (mirrors PaymentEngine.activate's "silently ask the
    provider" pattern from apps.subscriptions.payment_engine).
    """
    integration_id = integration_id_for(connector_key)
    try:
        resp = requests.get(
            f"{_NANGO_API_BASE}/connection/{nango_connection_id}",
            params={"provider_config_key": integration_id},
            headers=_headers(),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error("Nango get_connection request failed: %s", exc)
        raise NangoAPIError("Could not reach Nango. Please try again.") from exc

    if resp.status_code == 404:
        raise NangoAPIError("Connection not found on Nango.")
    if resp.status_code >= 400:
        logger.error("Nango get_connection returned %s: %s", resp.status_code, resp.text[:500])
        raise NangoAPIError(f"Nango rejected the connection lookup ({resp.status_code}).")
    return resp.json() or {}


def verify_webhook_signature(raw_body: bytes, received_signature: str) -> bool:
    """
    Verifies the `X-Nango-Hmac-Sha256` header: hex(hmac_sha256(webhook_signing_key,
    raw_body)). Mirrors the exact hmac.compare_digest pattern already used by
    apps.payments.providers.paystack.verify_signature and
    apps.integrations.services.sign_payload — same convention, different key.
    """
    if not received_signature:
        return False
    try:
        key = webhook_signing_key()
    except NangoNotConfiguredError:
        logger.error("Cannot verify Nango webhook signature — Nango is not configured.")
        return False
    expected = hmac.new(key.encode(), msg=raw_body, digestmod=hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(expected, received_signature.strip())
    except (TypeError, ValueError):
        return False


def list_connections_for_org(*, organisation_id: str, connector_key: str) -> list[dict]:
    """
    GET /connections?tags[organization_id]=...  — used by the restore/
    check-status endpoint (services.check_and_restore) to find a connection
    that completed on Nango's side but whose webhook hasn't arrived (or
    can't reach us yet, e.g. local dev with no public URL). This is the
    connectors equivalent of PaystackSubscriptionService.verify_payment's
    "silently ask the provider" fallback.

    Filters client-side on provider_config_key == integration_id_for(connector_key)
    since the list endpoint's tag filter narrows by org but not by provider,
    and returns matches newest-first.
    """
    integration_id = integration_id_for(connector_key)
    try:
        resp = requests.get(
            f"{_NANGO_API_BASE}/connections",
            params={"tags[organization_id]": str(organisation_id)},
            headers=_headers(),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error("Nango list_connections request failed: %s", exc)
        raise NangoAPIError("Could not reach Nango. Please try again.") from exc

    if resp.status_code >= 400:
        logger.error("Nango list_connections returned %s: %s", resp.status_code, resp.text[:500])
        raise NangoAPIError(f"Nango rejected the connections lookup ({resp.status_code}).")

    connections = (resp.json() or {}).get("connections") or []
    matches = [c for c in connections if c.get("provider_config_key") == integration_id]
    matches.sort(key=lambda c: c.get("created") or "", reverse=True)
    return matches


def delete_connection(*, nango_connection_id: str, connector_key: str) -> None:
    """
    DELETE /connection/{id} — best-effort revoke on Nango's side when the
    org disconnects. Failures are logged, never raised: our own
    ConnectorConnection.status=REVOKED is the authoritative gate for
    delivery (see services.deliver_event_to_connection), so a Nango-side
    delete failing must not block the local disconnect from taking effect.
    """
    integration_id = integration_id_for(connector_key)
    try:
        resp = requests.delete(
            f"{_NANGO_API_BASE}/connection/{nango_connection_id}",
            params={"provider_config_key": integration_id},
            headers=_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code >= 400:
            logger.warning(
                "Nango delete_connection returned %s for connection=%s (non-fatal, local "
                "disconnect proceeds regardless): %s",
                resp.status_code, nango_connection_id, resp.text[:300],
            )
    except (requests.RequestException, NangoNotConfiguredError) as exc:
        logger.warning(
            "Nango delete_connection failed for connection=%s (non-fatal): %s",
            nango_connection_id, exc,
        )


def proxy(*, method: str, path: str, nango_connection_id: str, connector_key: str,
          json_body: dict | None = None, params: dict | None = None,
          data: bytes | None = None, content_type: str | None = None) -> requests.Response:
    """
    POST/GET https://api.nango.dev/proxy/{path} — the ONE place Audity makes
    an authenticated call to Slack/Google Sheets/Drive/Calendar on an org's
    behalf. Nango injects the real OAuth token; Audity never sees or stores
    it. `path` is the target API's own endpoint (e.g. "chat.postMessage" for
    Slack, "v4/spreadsheets/{id}/values/{range}:append" for Sheets,
    "upload/drive/v3/files/{id}" for a Drive content upload) — see
    apps.connectors.services / apps.connectors.drive for the actual
    per-connector calls.

    `data`/`content_type` are for raw-bytes bodies (e.g. uploading a PDF's
    actual bytes to Drive, where the body is the file content, not JSON) —
    mutually exclusive with `json_body`. Existing json_body-only callers are
    unaffected (data defaults to None, so the json= branch is used exactly
    as before).
    """
    integration_id = integration_id_for(connector_key)
    headers = {
        **_headers(),
        "Connection-Id": nango_connection_id,
        "Provider-Config-Key": integration_id,
    }
    if content_type:
        headers["Content-Type"] = content_type
    try:
        resp = requests.request(
            method,
            f"{_NANGO_API_BASE}/proxy/{path.lstrip('/')}",
            json=json_body if data is None else None,
            data=data,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error("Nango proxy call failed (%s %s): %s", method, path, exc)
        raise NangoAPIError(f"Could not reach {connector_key} via Nango. Please try again.") from exc
    return resp
