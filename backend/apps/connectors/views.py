"""
Views for Connectors.

Tenant isolation: every queryset/service call below is explicitly scoped to
request.organisation via _get_or_resolve_org — never a bare `.objects.all()`
(same discipline as apps.integrations.views).

Permission split:
    - Connection lifecycle (connect/disconnect/config/channels/restore) uses
      IsStaff, matching apps.integrations.views.WebhookSubscriptionViewSet /
      APIKeyViewSet — this is a settings-area action, not a billing action.
    - Add-on billing (initiate/verify — real recurring money) uses
      IsOwnerOrAdmin, matching apps.subscriptions.views.SubscriptionViewSet's
      purchase/initiate-payment actions.
"""

import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsOwnerOrAdmin, IsStaff, _get_or_resolve_org
from apps.core.throttles import WebhookRateThrottle
from apps.subscriptions.models import PaymentHistory

from . import nango
from .models import Connector, ConnectorAddonSubscription, ConnectorConnection
from .pricing import price_for_interval
from .serializers import ConnectorAddonSubscriptionSerializer, ConnectorConnectionSerializer
from .services import (
    AlreadyConnectedError,
    ConnectorConnectionService,
    ConnectorQuotaService,
    QuotaExceededError,
)

logger = logging.getLogger(__name__)

# Static catalog metadata for the gallery — deliberately NOT a DB table (only
# two connectors exist in v1 and both are hardcoded product decisions, same
# spirit as EVENT_TYPES in apps.integrations.services being a Python tuple
# rather than a table). Extending to a 3rd connector post-v1 means adding a
# row here + a Connector.TextChoices member + a deliverer in services.py.
CONNECTOR_CATALOG = [
    {
        "connector_key": Connector.SLACK,
        "name": "Slack",
        "description": "Get notified when invoices are created, payments land, or stock runs low.",
    },
    {
        "connector_key": Connector.GOOGLE_SHEETS,
        "name": "Google Sheets",
        "description": "Every sale and invoice appended live to a spreadsheet you pick.",
    },
]


def _err(message: str, code: int = 400):
    return Response({"error": message}, status=code)


class ConnectorGalleryView(APIView):
    """GET /connectors/ — everything the gallery page needs in one call."""

    permission_classes = [IsAuthenticated, IsStaff]

    def get(self, request):
        org = _get_or_resolve_org(request)
        if org is None:
            return _err("Organisation not found.")

        connections = {
            c.connector_key: c
            for c in ConnectorConnection.objects.filter(organisation=org)
        }
        addons = {
            a.connector_key: a
            for a in ConnectorAddonSubscription.objects.filter(organisation=org)
        }

        catalog = []
        for entry in CONNECTOR_CATALOG:
            key = entry["connector_key"]
            connection = connections.get(key)
            addon = addons.get(key)
            catalog.append({
                **entry,
                "connection": ConnectorConnectionSerializer(connection).data if connection else None,
                "addon_subscription": ConnectorAddonSubscriptionSerializer(addon).data if addon else None,
            })

        return Response({
            "quota": ConnectorQuotaService.quota_summary(org),
            "connectors": catalog,
            "addon_price": {
                "monthly": str(price_for_interval(ConnectorAddonSubscription.Interval.MONTHLY)),
                "annual": str(price_for_interval(ConnectorAddonSubscription.Interval.ANNUAL)),
            },
        })


class ConnectorConnectView(APIView):
    """POST /connectors/{connector_key}/connect/ — mint a Nango Connect session."""

    permission_classes = [IsAuthenticated, IsStaff]

    def post(self, request, connector_key=None):
        org = _get_or_resolve_org(request)
        if org is None:
            return _err("Organisation not found.")

        try:
            result = ConnectorConnectionService.start_connect_session(org, connector_key, request.user)
        except AlreadyConnectedError as exc:
            return _err(str(exc), 409)
        except QuotaExceededError as exc:
            return _err(str(exc), 402)
        except ValueError as exc:
            return _err(str(exc), 400)
        except nango.NangoNotConfiguredError as exc:
            logger.error("Connector connect blocked — Nango not configured: %s", exc)
            return _err(str(exc), 503)
        except nango.NangoAPIError as exc:
            logger.error("Connector connect failed calling Nango: %s", exc)
            return _err(str(exc), 502)

        return Response(result, status=status.HTTP_200_OK)


class ConnectorRestoreView(APIView):
    """
    POST /connectors/{connector_key}/restore/ — the poll / silent-check /
    manual-"Restore access" trio's server side, mirroring
    SubscriptionViewSet.restore_integration_payment exactly (see that
    view's docstring for why this exists at all: the Nango Connect UI opens
    in the system browser on desktop and there's no OS-level deep-link back
    into the app).
    """

    permission_classes = [IsAuthenticated, IsStaff]

    def post(self, request, connector_key=None):
        org = _get_or_resolve_org(request)
        if org is None:
            return _err("Organisation not found.")

        try:
            conn = ConnectorConnectionService.check_and_restore(org, connector_key)
        except ValueError as exc:
            return _err(str(exc), 404)
        except nango.NangoNotConfiguredError as exc:
            return _err(str(exc), 503)
        except nango.NangoAPIError as exc:
            return _err(str(exc), 502)

        return Response(ConnectorConnectionSerializer(conn).data)


class ConnectorDisconnectView(APIView):
    """POST /connectors/{connector_key}/disconnect/"""

    permission_classes = [IsAuthenticated, IsStaff]

    def post(self, request, connector_key=None):
        org = _get_or_resolve_org(request)
        if org is None:
            return _err("Organisation not found.")

        try:
            conn = ConnectorConnectionService.disconnect(org, connector_key)
        except ValueError as exc:
            return _err(str(exc), 404)

        return Response(ConnectorConnectionSerializer(conn).data)


class ConnectorConfigView(APIView):
    """
    PATCH /connectors/{connector_key}/config/ — set connector-specific
    settings (Slack channel_id, Google Sheets spreadsheet_id/sheet_range).
    Only meaningful on an ACTIVE connection.
    """

    permission_classes = [IsAuthenticated, IsStaff]

    ALLOWED_KEYS = {
        Connector.SLACK: {"channel_id"},
        Connector.GOOGLE_SHEETS: {"spreadsheet_id", "sheet_range"},
    }

    def patch(self, request, connector_key=None):
        org = _get_or_resolve_org(request)
        if org is None:
            return _err("Organisation not found.")

        if connector_key not in Connector.values:
            return _err("Unknown connector.")

        conn = ConnectorConnection.objects.filter(organisation=org, connector_key=connector_key).first()
        if conn is None or conn.status != ConnectorConnection.Status.ACTIVE:
            return _err("Connect this connector before configuring it.", 400)

        allowed = self.ALLOWED_KEYS.get(connector_key, set())
        incoming = {k: v for k, v in (request.data or {}).items() if k in allowed}
        if not incoming:
            return _err(f"No valid config keys provided. Allowed: {sorted(allowed)}")

        conn.config = {**(conn.config or {}), **incoming}
        conn.save(update_fields=["config", "updated_at"])
        return Response(ConnectorConnectionSerializer(conn).data)


class SlackChannelsView(APIView):
    """
    GET /connectors/slack/channels/ — best-effort channel list for the
    config picker, proxied through Nango's conversations.list. Returns an
    empty list (never an error the UI must special-case) if Slack isn't
    connected yet or the call fails, so the frontend can always fall back to
    manual channel-ID entry.
    """

    permission_classes = [IsAuthenticated, IsStaff]

    def get(self, request):
        org = _get_or_resolve_org(request)
        if org is None:
            return _err("Organisation not found.")

        conn = ConnectorConnection.objects.filter(
            organisation=org, connector_key=Connector.SLACK, status=ConnectorConnection.Status.ACTIVE,
        ).first()
        if conn is None:
            return Response({"channels": []})

        try:
            resp = nango.proxy(
                method="GET",
                path="conversations.list",
                nango_connection_id=conn.nango_connection_id,
                connector_key=Connector.SLACK,
                params={"types": "public_channel,private_channel", "limit": 200},
            )
            data = resp.json() if resp.status_code == 200 else {}
            channels = [
                {"id": c.get("id"), "name": c.get("name")}
                for c in (data.get("channels") or [])
            ]
        except (nango.NangoNotConfiguredError, nango.NangoAPIError) as exc:
            logger.warning("SlackChannelsView: could not list channels for org %s: %s", org.id, exc)
            channels = []

        return Response({"channels": channels})


class ConnectorAddonInitiateView(APIView):
    """
    POST /connectors/{connector_key}/addon/initiate/
    Body: { "interval": "monthly" | "annual" }

    Mirrors SubscriptionViewSet.initiate_payment / purchase_integration's
    request/response shape exactly (authorization_url, reference, access_code,
    public_key, amount_kobo, email) so the frontend can reuse the SAME
    Paystack-inline / openExternal handling already built for those flows —
    only the kind passed to PaymentEngine differs.
    """

    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def post(self, request, connector_key=None):
        from apps.subscriptions.payment_engine import PaymentEngine

        org = _get_or_resolve_org(request)
        if org is None:
            return _err("Organisation not found.")

        interval = (request.data.get("interval") or ConnectorAddonSubscription.Interval.MONTHLY).strip()

        try:
            result = PaymentEngine.initiate(
                org, PaymentHistory.Kind.CONNECTOR_ADDON, (connector_key, interval), request.user.email,
            )
        except ValueError as exc:
            return _err(str(exc), 400)
        except Exception:
            logger.exception("Unexpected error initiating connector add-on for org %s connector %s", org.id, connector_key)
            return _err("Payment initialization failed. Please try again.", 500)

        return Response(result, status=status.HTTP_200_OK)


class ConnectorAddonVerifyView(APIView):
    """
    POST /connectors/addon/verify-payment/
    Body: { "reference": "ADDON-XXXXXXXX" }

    Mirrors verify_integration_payment's cross-org ownership check exactly
    (see that view's docstring for why: PaymentEngine.activate() genuinely
    verifies with Paystack regardless of caller, so an authenticated caller
    who merely observed another org's reference must not be able to
    force-settle it).
    """

    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def post(self, request):
        from apps.subscriptions.payment_engine import PaymentEngine
        from apps.subscriptions.serializers import PaymentHistorySerializer

        org = _get_or_resolve_org(request)
        reference = (request.data.get("reference") or "").strip()
        if not reference:
            return _err("reference is required.")

        try:
            payment = PaymentEngine.activate(reference)
        except ValueError as exc:
            return _err(str(exc), 400)

        if org is None or payment.organisation_id != org.id:
            return Response({"detail": "Not found."}, status=404)

        return Response(PaymentHistorySerializer(payment).data)


class ConnectorAddonRestoreView(APIView):
    """
    POST /connectors/{connector_key}/addon/restore/

    Re-verifies the CALLING ORG's own most recent pending ₦4,500/mo add-on
    payment for this connector — no reference required from the client.
    Exists for the exact same reason SubscriptionViewSet.
    restore_integration_payment does: on desktop the Paystack checkout opens
    in the system browser and there's no deep-link back into the app, so a
    completed payment there never reaches ConnectorAddonVerifyView on its
    own if the reference was lost (e.g. the app was closed mid-flow). Lets
    the frontend recover automatically (background poll) or the user
    recover manually ("Restore" fallback) without ever handling the raw
    reference.
    """

    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def post(self, request, connector_key=None):
        from apps.subscriptions.payment_engine import PaymentEngine
        from apps.subscriptions.serializers import PaymentHistorySerializer

        org = _get_or_resolve_org(request)
        if org is None:
            return _err("Organisation not found.")

        payment = PaymentHistory.objects.filter(
            kind=PaymentHistory.Kind.CONNECTOR_ADDON,
            organisation=org,
            connector_addon_subscription__connector_key=connector_key,
            status=PaymentHistory.Status.PENDING,
        ).order_by("-created_at").first()

        if payment is None:
            return _err("No pending add-on purchase found for this connector.", 404)

        try:
            payment = PaymentEngine.activate(payment.provider_payment_id)
        except ValueError as exc:
            return _err(str(exc), 400)

        return Response(PaymentHistorySerializer(payment).data)


# ── Nango webhook (server-to-server, no user session) ───────────────────────

@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([WebhookRateThrottle])
def nango_webhook(request):
    """
    POST /connectors/webhook/nango/

    Verifies X-Nango-Hmac-Sha256 against the raw body before touching
    anything (same signature-first discipline as
    apps.payments.views.paystack_webhook). Always answers 200 for a
    well-formed-but-unverifiable/unrecognised payload — providers retry
    aggressively on non-2xx, and retry-storming a spoofed or malformed event
    helps nobody. Only returns non-200 for a signature that fails to verify
    at all.
    """
    raw_body = request.body
    signature = request.META.get("HTTP_X_NANGO_HMAC_SHA256", "")

    if not nango.verify_webhook_signature(raw_body, signature):
        logger.warning("Nango webhook signature verification failed.")
        return Response({"status": "invalid_signature"}, status=401)

    try:
        payload = request.data if isinstance(request.data, dict) else {}
        ConnectorConnectionService.apply_webhook(payload)
    except Exception:
        logger.exception("Unexpected error handling Nango webhook.")
        return Response({"status": "error_logged"})

    return Response({"status": "ok"})
