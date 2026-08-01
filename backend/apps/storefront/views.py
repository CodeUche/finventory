"""
Storefront endpoints.

Two clearly separated halves:

  * Public  — no authentication at all. The tenant comes from the slug, every
    response is an allowlist, and everything is rate limited by IP.
  * Merchant — the normal authenticated, tenant-scoped views for configuring
    the shop and working the orders that arrive.
"""

import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsOwnerOrAdmin, IsStaff

from .models import Storefront, StorefrontOrder
from .serializers import (
    MerchantOrderSerializer, PlaceOrderSerializer, PublicOrderSerializer,
    PublicProductSerializer, PublicStorefrontSerializer, StorefrontSerializer,
)
from .services import StorefrontError, StorefrontService

logger = logging.getLogger(__name__)


class StorefrontBrowseThrottle(AnonRateThrottle):
    """Generous — browsing a shop is normal traffic."""
    scope = "storefront_browse"


class StorefrontOrderThrottle(AnonRateThrottle):
    """Tight — placing an order writes to the database."""
    scope = "storefront_order"


def _not_found():
    # Never distinguish "no such shop" from "shop unpublished": that difference
    # lets anyone enumerate which merchants exist.
    return Response({"error": "This shop is not available."}, status=404)


# ── Public ───────────────────────────────────────────────────────────────────
@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([StorefrontBrowseThrottle])
def public_storefront(request, slug):
    """GET /storefront/<slug>/ — the shop and what it can be paid with."""
    try:
        shop = StorefrontService.resolve(slug)
    except StorefrontError:
        return _not_found()

    data = PublicStorefrontSerializer(shop).data
    # Only which methods exist — never keys, and never the merchant's own
    # account numbers unless they chose to show them publicly.
    from apps.payments.services import PaymentService
    options = PaymentService.payment_options(shop.organisation)
    data["payment"] = {
        "card": options["card"],
        "virtual_account": options["virtual_account"],
        "bank_transfer": options["bank_transfer"],
        "bank_accounts": [
            {
                "bank_name": a.bank_name,
                "account_number": a.account_number,
                "account_name": a.account_name,
                "instructions": a.instructions,
            }
            for a in options["bank_accounts"] if a.show_on_storefront
        ],
    }
    return Response(data)


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([StorefrontBrowseThrottle])
def public_products(request, slug):
    """GET /storefront/<slug>/products/ — the published catalogue."""
    try:
        shop = StorefrontService.resolve(slug)
    except StorefrontError:
        return _not_found()
    products = StorefrontService.published_products(shop)
    return Response({"results": PublicProductSerializer(products, many=True).data})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([StorefrontOrderThrottle])
def public_place_order(request, slug):
    """POST /storefront/<slug>/orders/ — place an order."""
    try:
        shop = StorefrontService.resolve(slug)
    except StorefrontError:
        return _not_found()

    serializer = PlaceOrderSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        order = StorefrontService.place_order(shop, serializer.validated_data)
    except StorefrontError as exc:
        return Response({"error": str(exc)}, status=422)

    logger.info("Storefront order %s placed for %s", order.reference, shop.slug)
    return Response(PublicOrderSerializer(order).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([StorefrontBrowseThrottle])
def public_order_status(request, slug, reference):
    """GET /storefront/<slug>/orders/<reference>/ — track an order.

    The reference is the only credential, so it is long and unguessable and the
    response carries nothing beyond what the customer already typed in.
    """
    try:
        shop = StorefrontService.resolve(slug)
    except StorefrontError:
        return _not_found()
    order = StorefrontOrder.objects.filter(
        storefront=shop, reference=(reference or "").upper(),
    ).prefetch_related("items").first()
    if order is None:
        return Response({"error": "Order not found."}, status=404)
    return Response(PublicOrderSerializer(order).data)


# ── Merchant ─────────────────────────────────────────────────────────────────
class StorefrontViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Configure the shop page."""

    serializer_class = StorefrontSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        return Storefront.objects.filter(organisation=self._get_organisation())

    @action(detail=False, methods=["get"])
    def mine(self, request):
        """The org's storefront, created on first visit so the settings screen
        always has something to edit."""
        org = self._get_organisation()
        shop = Storefront.objects.filter(organisation=org).first()
        if shop is None:
            from django.utils.text import slugify
            base = slugify(org.name)[:40] or "shop"
            slug, n = base, 1
            while Storefront.objects.filter(slug=slug).exists():
                n += 1
                slug = f"{base}-{n}"
            shop = Storefront.objects.create(organisation=org, slug=slug)
        return Response(StorefrontSerializer(shop).data)


class StorefrontOrderViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Orders that arrived from the public page."""

    serializer_class = MerchantOrderSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["status", "fulfilment"]

    def get_queryset(self):
        return (
            StorefrontOrder.objects
            .filter(organisation=self._get_organisation())
            .select_related("invoice", "table")
            .prefetch_related("items")
        )

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        """Turn the order into a real sale."""
        try:
            order = StorefrontService.accept_order(self.get_object(), request.user)
        except StorefrontError as exc:
            return Response({"error": str(exc)}, status=422)
        return Response(MerchantOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def set_status(self, request, pk=None):
        try:
            order = StorefrontService.set_status(
                self.get_object(), request.data.get("status", ""),
            )
        except StorefrontError as exc:
            return Response({"error": str(exc)}, status=422)
        return Response(MerchantOrderSerializer(order).data)
