"""
Views for the integrations marketplace:
    - WebhookSubscriptionViewSet: CRUD + /test/ for the caller's own org
      (session/JWT auth, request.organisation resolved the normal way).
    - APIKeyViewSet: create/list/revoke Zapier-style API keys.
    - Zapier REST Hooks endpoints (subscribe/unsubscribe) + polling-trigger
      fallback: authenticated via APIKeyAuthentication, org resolved from the
      key itself.

Tenant isolation: every queryset below is explicitly filtered on
request.organisation — never a bare `.objects.all()`.
"""

import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsStaff, _get_or_resolve_org
from apps.subscriptions.models import IntegrationProduct, OrganisationIntegrationEntitlement

from .authentication import APIKeyAuthentication
from .models import DomainEvent, OrganisationAPIKey, WebhookDelivery, WebhookSubscription
from .serializers import (
    DomainEventSerializer,
    IntegrationProductSerializer,
    OrganisationAPIKeyCreateResponseSerializer,
    OrganisationAPIKeySerializer,
    WebhookSubscriptionCreateResponseSerializer,
    WebhookSubscriptionSerializer,
)
from .services import IntegrationEventService, SSRFValidationError, _validate_target, deliver_event_to_subscription

logger = logging.getLogger(__name__)


def _check_entitlement(organisation, integration_product_id):
    """
    Returns (product_or_None, error_response_or_None). Gates creation on the
    org having an ACTIVE entitlement for the referenced IntegrationProduct.
    """
    if not integration_product_id:
        return None, None
    try:
        product = IntegrationProduct.objects.get(id=integration_product_id, is_active=True)
    except IntegrationProduct.DoesNotExist:
        return None, Response({"error": "Integration product not found."}, status=400)

    return _check_entitlement_for_product(organisation, product)


def _check_entitlement_for_product(organisation, product):
    """
    Shared by _check_entitlement (lookup by id, dashboard create path) and
    _get_zapier_product_or_error (lookup by key, Zapier REST-Hooks path) so
    both entitlement-gated creation paths enforce identical ACTIVE-status
    semantics. Returns (product_or_None, error_response_or_None).
    """
    is_entitled = OrganisationIntegrationEntitlement.objects.filter(
        organisation=organisation,
        product=product,
        status=OrganisationIntegrationEntitlement.Status.ACTIVE,
    ).exists()
    if not is_entitled:
        return None, Response(
            {
                "error": (
                    f"Your organisation has not purchased the '{product.name}' integration. "
                    f"Purchase it first via POST /subscriptions/integrations/{product.key}/purchase/."
                )
            },
            status=403,
        )
    return product, None


def _get_zapier_product_or_error():
    """
    Fail-CLOSED lookup of the 'zapier' IntegrationProduct catalog row, shared
    by APIKeyViewSet.create and ZapierHooksSubscribeView.post. A missing
    catalog row (e.g. the seed migration's reverse ran, or a fresh
    environment before it applies) is treated as a server misconfiguration —
    NOT as "no gate needed" — because failing open here would let anyone
    mint unlimited free API keys / entitlement-ungated webhook subscriptions.

    Returns (product_or_None, error_response_or_None).
    """
    try:
        product = IntegrationProduct.objects.get(key="zapier", is_active=True)
    except IntegrationProduct.DoesNotExist:
        logger.error(
            "Zapier IntegrationProduct catalog row is missing or inactive — "
            "failing closed on Zapier entitlement checks."
        )
        return None, Response(
            {"error": "Zapier integration is temporarily unavailable. Please contact support."},
            status=500,
        )
    return product, None


class IntegrationProductListView(APIView):
    """
    GET /integrations/products/ — read-only catalog listing for the
    marketplace page, annotated with the caller's org's entitlement status
    per product (pending/active/revoked/None) so the frontend can render
    "Purchase" vs "Purchased" without a second request per row.

    IntegrationProduct itself lives in apps.subscriptions (read-only from
    here) — this is purely a display convenience, not a new write path.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_or_resolve_org(request)
        products = IntegrationProduct.objects.filter(is_active=True).order_by("name")

        statuses = {}
        if org is not None:
            entitlements = OrganisationIntegrationEntitlement.objects.filter(
                organisation=org, product__in=products,
            ).values_list("product_id", "status")
            statuses = dict(entitlements)

        serializer = IntegrationProductSerializer(
            products, many=True, context={"entitlement_statuses": statuses},
        )
        return Response(serializer.data)


class WebhookSubscriptionViewSet(viewsets.ModelViewSet):
    """
    /api/v1/integrations/webhooks/

    GET/POST list-create, DELETE deactivate, POST {id}/test/ send a synthetic
    event synchronously through the same SSRF-validated delivery path used by
    the Celery task.
    """

    permission_classes = [IsAuthenticated, IsStaff]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        org = _get_or_resolve_org(self.request)
        if org is None:
            return WebhookSubscription.objects.none()
        return WebhookSubscription.objects.filter(organisation=org)

    def get_serializer_class(self):
        if self.action == "create":
            return WebhookSubscriptionCreateResponseSerializer
        return WebhookSubscriptionSerializer

    def create(self, request, *args, **kwargs):
        org = _get_or_resolve_org(request)
        if org is None:
            return Response({"error": "Organisation not found."}, status=400)

        integration_product_id = request.data.get("integration_product")
        _, error = _check_entitlement(org, integration_product_id)
        if error is not None:
            return error

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(organisation=org)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        # Soft-delete via TenantAwareModel, plus explicitly deactivate so a
        # concurrent Celery delivery run mid-request stops matching it too.
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        instance.delete()

    @action(detail=True, methods=["post"])
    def test(self, request, pk=None):
        """
        POST /integrations/webhooks/{id}/test/ — sends a synthetic test event
        immediately (synchronous, bypasses Celery), through the SAME
        SSRF-validated delivery path as the real background task.
        """
        subscription = self.get_object()
        org = _get_or_resolve_org(request)

        test_event = IntegrationEventService.emit(
            organisation=org,
            event_type="integration.test",
            payload={"message": "This is a test event from Audity.", "webhook_subscription_id": str(subscription.id)},
        )
        delivery = deliver_event_to_subscription(subscription, test_event)
        return Response(
            {
                "status": delivery.status,
                "last_response_code": delivery.last_response_code,
                "last_error": delivery.last_error,
                "attempt_count": delivery.attempt_count,
            }
        )

    @action(detail=True, methods=["get"])
    def deliveries(self, request, pk=None):
        """GET /integrations/webhooks/{id}/deliveries/ — delivery history for this subscription."""
        subscription = self.get_object()
        qs = WebhookDelivery.objects.filter(subscription=subscription).order_by("-created_at")[:100]
        from .serializers import WebhookDeliverySerializer

        return Response(WebhookDeliverySerializer(qs, many=True).data)


class APIKeyViewSet(viewsets.ModelViewSet):
    """
    /api/v1/integrations/api-keys/

    Create/list/revoke Zapier-style API keys. Gated on the Zapier
    IntegrationProduct entitlement being ACTIVE, same as webhooks.
    """

    permission_classes = [IsAuthenticated, IsStaff]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        org = _get_or_resolve_org(self.request)
        if org is None:
            return OrganisationAPIKey.objects.none()
        return OrganisationAPIKey.objects.filter(organisation=org)

    def get_serializer_class(self):
        if self.action == "create":
            return OrganisationAPIKeyCreateResponseSerializer
        return OrganisationAPIKeySerializer

    def create(self, request, *args, **kwargs):
        org = _get_or_resolve_org(request)
        if org is None:
            return Response({"error": "Organisation not found."}, status=400)

        name = (request.data.get("name") or "").strip() or "API Key"

        zapier_product, error = _get_zapier_product_or_error()
        if error is not None:
            return error

        _, error = _check_entitlement_for_product(org, zapier_product)
        if error is not None:
            return error

        plaintext, prefix, key_hash = OrganisationAPIKey.generate_key()
        api_key = OrganisationAPIKey.objects.create(
            organisation=org, name=name, key_prefix=prefix, key_hash=key_hash,
        )
        serializer = self.get_serializer(api_key)
        data = dict(serializer.data)
        data["key"] = plaintext
        return Response(data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
        instance.delete()


class ZapierHooksSubscribeView(APIView):
    """POST /integrations/zapier/hooks/subscribe/ — Zapier REST Hooks registration."""

    authentication_classes = [APIKeyAuthentication]
    permission_classes = []  # authentication itself is the gate; no session/role check applies to API-key callers

    def post(self, request):
        org = getattr(request, "organisation", None)
        if org is None:
            return Response({"error": "Invalid API key."}, status=401)

        target_url = (request.data.get("target_url") or request.data.get("hookUrl") or "").strip()
        event_type = (request.data.get("event") or request.data.get("event_type") or "").strip()
        if not target_url or not event_type:
            return Response({"error": "target_url and event are required."}, status=400)

        # Same creation-time SSRF check as the dashboard create path
        # (WebhookSubscriptionSerializer.validate_target_url) — this endpoint
        # builds a WebhookSubscription directly rather than through that
        # serializer, so it needs its own call into the same reused
        # _validate_target logic to close the identical gap here.
        try:
            _validate_target(target_url)
        except SSRFValidationError as exc:
            return Response(
                {"error": f"This URL cannot be used as a webhook target: {exc}"}, status=400
            )

        valid_types = {choice[0] for choice in DomainEvent.EVENT_TYPES}
        if event_type not in valid_types:
            return Response({"error": f"Unknown event type '{event_type}'."}, status=400)

        # Same fail-closed lookup + ACTIVE-entitlement gate as the dashboard
        # create path (WebhookSubscriptionViewSet.create) and API-key
        # creation — this endpoint is only reachable with a valid API key,
        # which itself requires an active Zapier entitlement to have been
        # minted (see APIKeyViewSet.create), but subscriptions created here
        # must still be tagged with integration_product so
        # deliver_event_to_subscription's per-delivery entitlement check
        # (services.py) actually applies to them, and so a later-revoked
        # entitlement stops delivery exactly as it would for a dashboard-
        # created subscription.
        zapier_product, error = _get_zapier_product_or_error()
        if error is not None:
            return error

        _, error = _check_entitlement_for_product(org, zapier_product)
        if error is not None:
            return error

        subscription = WebhookSubscription.objects.create(
            organisation=org,
            target_url=target_url,
            event_types=[event_type],
            integration_product=zapier_product,
        )
        return Response({"id": str(subscription.id)}, status=status.HTTP_201_CREATED)


class ZapierHooksUnsubscribeView(APIView):
    """DELETE /integrations/zapier/hooks/unsubscribe/ — Zapier REST Hooks de-registration."""

    authentication_classes = [APIKeyAuthentication]
    permission_classes = []

    def delete(self, request):
        org = getattr(request, "organisation", None)
        if org is None:
            return Response({"error": "Invalid API key."}, status=401)

        subscription_id = request.data.get("id") or request.query_params.get("id")
        if not subscription_id:
            return Response({"error": "id is required."}, status=400)

        deleted = WebhookSubscription.objects.filter(organisation=org, id=subscription_id).first()
        if deleted is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        deleted.is_active = False
        deleted.save(update_fields=["is_active", "updated_at"])
        deleted.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ZapierPollingTriggerView(APIView):
    """
    GET /integrations/zapier/triggers/{event_type}/ — polling-trigger
    fallback for Zapier triggers not using REST Hooks. Returns most recent N
    DomainEvent rows of that type for the authenticated org, newest first —
    each item has a stable unique `id`, matching Zapier's polling contract.
    """

    authentication_classes = [APIKeyAuthentication]
    permission_classes = []

    def get(self, request, event_type=None):
        org = getattr(request, "organisation", None)
        if org is None:
            return Response({"error": "Invalid API key."}, status=401)

        qs = DomainEvent.objects.filter(organisation=org, event_type=event_type).order_by("-occurred_at")[:50]
        return Response(DomainEventSerializer(qs, many=True).data)
