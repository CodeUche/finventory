"""
Google Drive upload — auto-saving generated PDFs (invoice, payslip, report
export) into the folder an org picked when connecting. Everything here goes
through nango.proxy(), same as Slack/Sheets — Drive is a normal Nango OAuth
connector, unlike Telegram (see apps.connectors.telegram's module docstring
for that exception).

Two-call pattern (Drive's own documented approach, avoids hand-building a
multipart/related body over Nango's proxy):
    1. POST drive/v3/files — create the file's metadata (name + parent
       folder), get back a file id.
    2. PATCH upload/drive/v3/files/{id}?uploadType=media — upload the raw
       PDF bytes as the file's content.
A failure between step 1 and 2 can leave a zero-byte orphan file in the
org's Drive folder — acceptable for a best-effort auto-save convenience
feature (never blocks or fails the PDF's primary purpose — see
apps.connectors.services.maybe_save_pdf_to_drive, the only caller), not
acceptable if this were the record of truth for anything.
"""

from __future__ import annotations

import logging

from . import nango
from .models import Connector, ConnectorConnection

logger = logging.getLogger(__name__)


class GoogleDriveService:

    @staticmethod
    def upload_pdf(connection: ConnectorConnection, filename: str, pdf_bytes: bytes) -> tuple[bool, str]:
        """
        Uploads `pdf_bytes` as `filename` into the connection's configured
        Drive folder. Returns (ok, error) — never raises (mirrors every
        other connector deliverer's contract in apps.connectors.services),
        so a Drive outage never propagates into whatever generated the PDF
        in the first place.
        """
        folder_id = (connection.config or {}).get("folder_id")
        if not folder_id:
            return False, "No Google Drive folder configured for this connection."

        try:
            metadata_resp = nango.proxy(
                method="POST",
                path="drive/v3/files",
                nango_connection_id=connection.nango_connection_id,
                connector_key=Connector.GOOGLE_DRIVE,
                json_body={"name": filename, "parents": [folder_id], "mimeType": "application/pdf"},
            )
        except (nango.NangoNotConfiguredError, nango.NangoAPIError) as exc:
            return False, str(exc)

        if not (200 <= metadata_resp.status_code < 300):
            error = metadata_resp.text[:500] if metadata_resp.text else f"HTTP {metadata_resp.status_code}"
            return False, f"Drive file creation failed: {error}"

        file_id = (metadata_resp.json() or {}).get("id")
        if not file_id:
            return False, "Drive did not return a file id after creation."

        try:
            content_resp = nango.proxy(
                method="PATCH",
                path=f"upload/drive/v3/files/{file_id}",
                params={"uploadType": "media"},
                nango_connection_id=connection.nango_connection_id,
                connector_key=Connector.GOOGLE_DRIVE,
                data=pdf_bytes,
                content_type="application/pdf",
            )
        except (nango.NangoNotConfiguredError, nango.NangoAPIError) as exc:
            return False, str(exc)

        if not (200 <= content_resp.status_code < 300):
            error = content_resp.text[:500] if content_resp.text else f"HTTP {content_resp.status_code}"
            return False, f"Drive content upload failed: {error}"

        return True, ""

    @staticmethod
    def list_folders(connection: ConnectorConnection) -> list[dict]:
        """
        Best-effort folder list for the config picker (mirrors
        SlackChannelsView's "always fall back to manual entry" contract —
        returns [] rather than raising on any failure).
        """
        try:
            resp = nango.proxy(
                method="GET",
                path="drive/v3/files",
                nango_connection_id=connection.nango_connection_id,
                connector_key=Connector.GOOGLE_DRIVE,
                params={
                    "q": "mimeType='application/vnd.google-apps.folder' and trashed=false",
                    "fields": "files(id,name)",
                    "pageSize": 200,
                },
            )
            data = resp.json() if resp.status_code == 200 else {}
            return [{"id": f.get("id"), "name": f.get("name")} for f in (data.get("files") or [])]
        except (nango.NangoNotConfiguredError, nango.NangoAPIError) as exc:
            logger.warning("GoogleDriveService.list_folders failed: %s", exc)
            return []
