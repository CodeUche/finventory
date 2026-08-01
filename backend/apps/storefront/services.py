"""
Storefront ordering.

An order from the public internet is untrusted input that ends in the ledger,
so the rules are strict: the organisation comes from the slug, the catalogue is
re-read server-side, and money is recomputed from our own prices.
"""

from __future__ import annotations

import logging
import secrets
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from .models import Storefront, StorefrontOrder, StorefrontOrderItem

logger = logging.getLogger(__name__)
ZERO = Decimal("0")

# No I, O, 0 or 1 — a customer reads this out over the phone.
_REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class StorefrontError(Exception):
    """A problem the customer should see, phrased for them."""


class StorefrontService:
    @staticmethod
    def resolve(slug: str) -> Storefront:
        """The only way a public request picks a tenant."""
        shop = (
            Storefront.objects
            .select_related("organisation")
            .filter(slug=(slug or "").lower(), is_published=True)
            .first()
        )
        if shop is None:
            raise StorefrontError("This shop is not available.")
        return shop

    @staticmethod
    def published_products(shop: Storefront):
        """Published, active products with a stock flag attached.

        Annotates availability rather than exposing quantities — a customer
        needs to know whether they can buy it, not how much the shop holds.
        """
        from apps.inventory.models import Product, StockItem

        products = (
            Product.objects
            .filter(organisation=shop.organisation, is_active=True, is_published=True)
            .select_related("category")
            .order_by("name")
        )
        stock = {
            row["product_id"]: row["qty"] or ZERO
            for row in StockItem.objects
            .filter(organisation=shop.organisation)
            .values("product_id").annotate(qty=Sum("quantity_on_hand"))
        }
        out = []
        for product in products:
            available = stock.get(product.id, ZERO)
            # A service has nothing to count, so it is always orderable.
            if getattr(product, "product_type", "physical") != "physical":
                available = Decimal("1")
            product._available = available
            if shop.hide_out_of_stock and available <= 0:
                continue
            out.append(product)
        return out

    @staticmethod
    def _reference() -> str:
        for _ in range(10):
            ref = "".join(secrets.choice(_REF_ALPHABET) for _ in range(8))
            if not StorefrontOrder.objects.filter(reference=ref).exists():
                return ref
        raise StorefrontError("Could not start your order. Please try again.")

    @staticmethod
    @transaction.atomic
    def place_order(shop: Storefront, data: dict) -> StorefrontOrder:
        """Turn a validated public payload into an order.

        Prices come from our catalogue, never from the request — otherwise
        anyone could post their own price and we would honour it.
        """
        from apps.inventory.models import Product

        if not shop.accepts_orders:
            raise StorefrontError("This shop is not taking orders right now.")

        wanted = {line["product_id"]: line["quantity"] for line in data["items"]}
        products = {
            str(p.id): p for p in Product.objects.filter(
                organisation=shop.organisation, id__in=list(wanted), is_active=True,
                is_published=True,
            )
        }
        # Anything not in the published catalogue is refused outright rather
        # than silently dropped, so the customer's total is never a surprise.
        missing = [pid for pid in wanted if pid not in products]
        if missing:
            raise StorefrontError("Some items are no longer available. Please refresh and try again.")

        table = None
        if data.get("table_code"):
            from apps.pos.models import RestaurantTable
            table = RestaurantTable.objects.filter(
                organisation=shop.organisation, name__iexact=data["table_code"].strip(),
                is_active=True,
            ).first()
            if table is None:
                raise StorefrontError("That table code is not recognised.")

        order = StorefrontOrder.objects.create(
            organisation=shop.organisation,
            storefront=shop,
            reference=StorefrontService._reference(),
            fulfilment=(StorefrontOrder.Fulfilment.TABLE if table
                        else data.get("fulfilment", StorefrontOrder.Fulfilment.PICKUP)),
            customer_name=data["customer_name"].strip(),
            customer_phone=data["customer_phone"].strip(),
            customer_email=(data.get("customer_email") or "").strip(),
            delivery_address=(data.get("delivery_address") or "").strip(),
            note=(data.get("note") or "").strip(),
            table=table,
        )

        subtotal = ZERO
        for product_id, quantity in wanted.items():
            product = products[product_id]
            price = Decimal(str(product.selling_price or 0))
            line_total = (price * quantity).quantize(Decimal("0.01"))
            StorefrontOrderItem.objects.create(
                organisation=shop.organisation, order=order, product=product,
                product_name=product.name, quantity=quantity,
                unit_price=price, line_total=line_total,
            )
            subtotal += line_total

        if shop.minimum_order and subtotal < Decimal(str(shop.minimum_order)):
            raise StorefrontError(
                f"Orders start at {shop.minimum_order}. Please add a little more."
            )

        order.subtotal = subtotal
        order.total = subtotal
        order.save(update_fields=["subtotal", "total", "updated_at"])
        return order

    # ── Merchant side ───────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def accept_order(order: StorefrontOrder, user=None) -> StorefrontOrder:
        """Accept an order: it becomes a real sale.

        A table order becomes a POS order so it reaches the kitchen; everything
        else becomes an invoice. Either way it lands in the same ledger the
        counter uses — no second accounting path.
        """
        order = StorefrontOrder.objects.select_for_update().get(pk=order.pk)
        if order.status != StorefrontOrder.Status.PLACED:
            raise StorefrontError("This order has already been dealt with.")
        if order.invoice_id or order.pos_order_id:
            raise StorefrontError("This order has already been turned into a sale.")

        if order.table_id:
            order.pos_order = StorefrontService._to_pos_order(order, user)
        else:
            order.invoice = StorefrontService._to_invoice(order, user)

        order.status = StorefrontOrder.Status.CONFIRMED
        order.save(update_fields=["status", "invoice", "pos_order", "updated_at"])
        return order

    @staticmethod
    def _lines(order: StorefrontOrder) -> list[dict]:
        return [
            {
                "product_id": str(item.product_id),
                "quantity": item.quantity,
                "unit_price": item.unit_price,
            }
            for item in order.items.all() if item.product_id
        ]

    @staticmethod
    def _to_invoice(order: StorefrontOrder, user=None):
        """Raised as an unpaid credit sale — the goods are promised, the money
        has not arrived. Payment then settles it through the normal path."""
        from apps.inventory.models import Warehouse
        from apps.sales.services import SaleService

        warehouse = (
            Warehouse.objects.filter(organisation=order.organisation, is_default=True).first()
            or Warehouse.objects.filter(organisation=order.organisation).first()
        )
        return SaleService.create_sale(
            organisation=order.organisation,
            created_by=user,
            customer=StorefrontService._customer_for(order),
            warehouse=warehouse,
            items=StorefrontService._lines(order),
            payment_method="credit",
            notes=f"Storefront order {order.reference}",
            sold_by="Storefront",
        )

    @staticmethod
    def _to_pos_order(order: StorefrontOrder, user=None):
        from apps.pos.services import POSOrderService
        return POSOrderService.create_order(
            organisation=order.organisation,
            created_by=user,
            order_type="dine_in",
            items=StorefrontService._lines(order),
            table_id=str(order.table_id),
            notes=f"QR order {order.reference} — {order.customer_name}",
        )

    @staticmethod
    def _customer_for(order: StorefrontOrder):
        """Reuse a customer on the phone number, otherwise create one.

        Matching on phone keeps a repeat buyer as one customer rather than a
        new record per order, which is what makes a statement meaningful.
        """
        from apps.customers.models import Customer

        phone = (order.customer_phone or "").strip()
        if phone:
            existing = Customer.objects.filter(
                organisation=order.organisation, phone=phone,
            ).first()
            if existing:
                return existing
        return Customer.objects.create(
            organisation=order.organisation,
            code=f"WEB-{order.reference}",
            name=order.customer_name or "Storefront customer",
            phone=phone,
            email=order.customer_email or "",
            address=order.delivery_address or "",
        )

    @staticmethod
    def set_status(order: StorefrontOrder, status: str) -> StorefrontOrder:
        valid = dict(StorefrontOrder.Status.choices)
        if status not in valid:
            raise StorefrontError("Unknown status.")
        order.status = status
        order.save(update_fields=["status", "updated_at"])
        return order
