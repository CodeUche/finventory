"""
Gmail send — dispatches a short notification email via the ORG'S OWN
connected Gmail account when invoice.created / payment.received fires (see
apps.connectors.services' _deliver_to_gmail, the only caller). Gmail is a
notification channel in the same category as Slack/Telegram — this module
is completely separate from, and must never touch, Audity's existing
invoice/payslip email-sending pathway (SMTP/Brevo — see apps.payroll.tasks'
EmailMultiAlternatives usage and apps.notifications). That pathway sends
FROM Audity's own transactional sender; this one sends FROM the business's
own Gmail account, to an address the org configured (config["notify_email"]
on the ConnectorConnection — see apps.connectors.views.ConnectorConfigView).

Everything here goes through nango.proxy(), same as Slack/Sheets/Drive/
Calendar — Gmail is a normal Nango OAuth connector reusing the SAME Google
OAuth client already live for Sheets/Drive/Calendar (Nango unique_key
"google-mail"), unlike Telegram (see apps.connectors.telegram's module
docstring for that exception).

Gmail's send API (POST gmail/v1/users/me/messages/send) does not take a
simple JSON body the way Slack's chat.postMessage does — it expects a `raw`
field containing a base64url-encoded (NOT standard base64: Gmail requires
the URL-safe alphabet, "-"/"_" instead of "+"/"/", no padding) full RFC 2822
MIME message (headers + body). build_raw_message() below builds that
message with the stdlib's email.mime classes (a single-part plain-text
message needs nothing heavier) and encodes it; GmailService.send_email() is
the only network call.
"""

from __future__ import annotations

import base64
from email.mime.text import MIMEText

from . import nango
from .models import Connector, ConnectorConnection


def build_raw_message(*, to_email: str, subject: str, body_text: str) -> str:
    """
    Builds a minimal single-part RFC 2822 MIME message (To/Subject/
    Content-Type/body) and returns it base64url-encoded with padding
    stripped — exactly the shape Gmail's users.messages.send `raw` field
    requires. There is no `from_email` parameter: Gmail always sends as the
    authenticated account regardless of any From header supplied, so there
    is nothing meaningful to set there.
    """
    message = MIMEText(body_text, "plain", "utf-8")
    message["To"] = to_email
    message["Subject"] = subject
    raw_bytes = message.as_bytes()
    # urlsafe_b64encode swaps +/ for -_ but still pads with "="; Gmail's API
    # accepts padded input, but stripping it matches Google's own examples
    # and keeps the encoded value a few bytes shorter.
    return base64.urlsafe_b64encode(raw_bytes).decode("ascii").rstrip("=")


class GmailService:

    @staticmethod
    def send_email(
        connection: ConnectorConnection, *, to_email: str, subject: str, body_text: str,
    ) -> tuple[bool, int | None, str]:
        """
        Sends `body_text` as a plain-text email to `to_email` via the org's
        connected Gmail account. Returns (ok, status_code, error) — the
        SAME three-tuple shape every other deliverer in
        apps.connectors.services returns (_deliver_to_slack,
        _deliver_to_sheets, _deliver_to_calendar), since this is called
        directly from _deliver_to_gmail as that deliverer's implementation
        rather than wrapping nango's exceptions itself: NangoNotConfiguredError
        / NangoAPIError propagate uncaught to
        ConnectorDeliveryService.deliver_event_to_connection, which already
        catches both for every connector.
        """
        raw = build_raw_message(to_email=to_email, subject=subject, body_text=body_text)
        resp = nango.proxy(
            method="POST",
            path="gmail/v1/users/me/messages/send",
            nango_connection_id=connection.nango_connection_id,
            connector_key=Connector.GMAIL,
            json_body={"raw": raw},
        )
        ok = 200 <= resp.status_code < 300
        error = "" if ok else (resp.text[:500] if resp.text else f"HTTP {resp.status_code}")
        return ok, resp.status_code, error
