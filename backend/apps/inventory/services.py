"""
Inventory service layer.

All stock mutations MUST go through this service.
Direct model saves that bypass this layer break the ledger.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import F

from .models import Batch, Product, StockCostLayer, StockItem, StockMovement, Warehouse

logger = logging.getLogger(__name__)


class InventoryService:

    @staticmethod
    @transaction.atomic
    def record_movement(
        organisation,
        product: Product,
        warehouse: Warehouse,
        quantity: Decimal,
        movement_type: str,
        unit_cost: Decimal = None,
        reference: str = "",
        notes: str = "",
        batch: Batch = None,
        created_by=None,
        use_costing_engine: bool = False,
    ) -> StockMovement:
        """
        Core stock mutation function.

        Uses select_for_update() to prevent race conditions in concurrent
        sale/purchase recording. Atomically updates StockItem balance.

        Args:
            quantity: Positive for inward movements, negative for outward.
            use_costing_engine: When True and quantity is outward, resolve the
                movement's unit_cost from the product's costing_method (FIFO/
                LIFO layer consumption, running average, or the given `batch`
                for Specific Unit) instead of trusting the caller's unit_cost.
                Every inbound movement builds the FIFO/LIFO layer ledger and
                recomputes the running average REGARDLESS of this flag — it's
                cheap bookkeeping with no behavioural effect until something
                reads it — so a product can switch costing_method later and
                already have real history instead of starting empty.
                Defaults to False so every pre-existing caller (reversals,
                restocks, adjustments, transfers) keeps its exact prior
                behaviour; only a new sale opts in, since that's the one path
                the reviewer's costing-method request is actually about.
        """
        # Lock the stock item row to prevent concurrent modification
        stock_item, _ = StockItem.objects.select_for_update().get_or_create(
            organisation=organisation,
            product=product,
            warehouse=warehouse,
            defaults={"quantity_on_hand": Decimal("0")},
        )

        new_balance = stock_item.quantity_on_hand + quantity

        # Business rule: don't allow negative stock (configurable per product in future)
        if new_balance < 0:
            raise ValueError(
                f"Insufficient stock. Available: {stock_item.quantity_on_hand}, Requested: {abs(quantity)}"
            )

        resolved_unit_cost = unit_cost or product.cost_price

        if quantity > 0:
            InventoryService._create_cost_layer(
                organisation, product, warehouse, quantity, resolved_unit_cost, reference,
            )
            InventoryService._update_average_cost(stock_item, quantity, resolved_unit_cost)
        elif use_costing_engine:
            resolved_unit_cost = InventoryService._resolve_outbound_unit_cost(
                organisation, product, warehouse, stock_item, abs(quantity), batch, resolved_unit_cost,
            )

        # Update denormalised balance
        stock_item.quantity_on_hand = new_balance
        stock_item.save(update_fields=["quantity_on_hand", "updated_at"])

        # Append immutable ledger entry
        movement = StockMovement.objects.create(
            organisation=organisation,
            product=product,
            warehouse=warehouse,
            batch=batch,
            movement_type=movement_type,
            quantity=quantity,
            unit_cost=resolved_unit_cost,
            reference=reference,
            notes=notes,
            created_by=created_by,
            balance_after=new_balance,
        )

        logger.info(
            "StockMovement %s: %s %s × %s × %s @ %s",
            movement.id, movement_type, quantity, product.sku, warehouse.name, resolved_unit_cost,
        )
        return movement

    @staticmethod
    def _create_cost_layer(organisation, product, warehouse, quantity, unit_cost, reference):
        StockCostLayer.objects.create(
            organisation=organisation, product=product, warehouse=warehouse,
            quantity_remaining=quantity, unit_cost=unit_cost, reference=reference,
        )

    @staticmethod
    def _update_average_cost(stock_item, in_quantity, in_unit_cost):
        """Weighted average: (old total value + new total value) / new total qty."""
        prior_qty = stock_item.quantity_on_hand
        prior_value = prior_qty * stock_item.average_cost
        new_qty = prior_qty + in_quantity
        if new_qty <= 0:
            return
        stock_item.average_cost = (prior_value + in_quantity * in_unit_cost) / new_qty
        stock_item.save(update_fields=["average_cost"])

    @staticmethod
    def _resolve_outbound_unit_cost(organisation, product, warehouse, stock_item, quantity_needed, batch, fallback_cost):
        """
        Weighted unit cost for `quantity_needed` leaving this warehouse, per the
        product's costing_method. Falls back to `fallback_cost` (the caller's
        unit_cost or product.cost_price) whenever there isn't enough layer
        history to resolve from — e.g. a fifo/lifo product take-on directly via
        an opening balance rather than a purchase, or a specific-unit sale where
        no batch was actually chosen.
        """
        method = product.costing_method
        if method == Product.CostingMethod.SPECIFIC:
            if batch is not None:
                return batch.unit_cost
            return fallback_cost
        if method == Product.CostingMethod.AVERAGE:
            return stock_item.average_cost if stock_item.average_cost > 0 else fallback_cost
        if method in (Product.CostingMethod.FIFO, Product.CostingMethod.LIFO):
            return InventoryService._consume_layers(
                organisation, product, warehouse, quantity_needed, method, fallback_cost,
            )
        return fallback_cost

    @staticmethod
    def _consume_layers(organisation, product, warehouse, quantity_needed, method, fallback_cost):
        order = "created_at" if method == Product.CostingMethod.FIFO else "-created_at"
        layers = list(
            StockCostLayer.objects.select_for_update().filter(
                organisation=organisation, product=product, warehouse=warehouse,
                quantity_remaining__gt=0,
            ).order_by(order)
        )
        remaining = Decimal(quantity_needed)
        total_cost = Decimal("0")
        for layer in layers:
            if remaining <= 0:
                break
            take = min(layer.quantity_remaining, remaining)
            total_cost += take * layer.unit_cost
            layer.quantity_remaining -= take
            layer.save(update_fields=["quantity_remaining"])
            remaining -= take
        if remaining > 0:
            # Layer history doesn't cover the full quantity (e.g. stock taken on
            # via an opening balance with no layer, or a pre-existing balance
            # from before this engine existed) — value the shortfall at the
            # fallback cost rather than understating COGS.
            total_cost += remaining * fallback_cost
        return total_cost / quantity_needed

    @staticmethod
    def get_low_stock_products(organisation):
        """Return stock items that have fallen below reorder level."""
        return (
            StockItem.objects.filter(organisation=organisation)
            .select_related("product", "warehouse")
            .filter(quantity_on_hand__lte=F("product__reorder_level"))
        )

    @staticmethod
    def get_stock_valuation(organisation, warehouse=None):
        """
        Calculate inventory value.

        Uses each StockItem's real running weighted-average cost once it has
        one (i.e. at least one inbound movement has been recorded since this
        engine shipped); falls back to the product's flat cost_price for stock
        that predates it or has never had a purchase/opening-balance movement.
        This is a valuation snapshot, not a COGS driver — a FIFO/LIFO product
        still consumes its own layers correctly at sale time regardless of what
        this reports.

        Returns list of dicts: {product, quantity, unit_cost, total_value}
        """
        from django.db.models import Case, F, When

        qs = StockItem.objects.filter(organisation=organisation, quantity_on_hand__gt=0)
        if warehouse:
            qs = qs.filter(warehouse=warehouse)

        effective_cost = Case(
            When(average_cost__gt=0, then=F("average_cost")),
            default=F("product__cost_price"),
        )
        return qs.select_related("product", "warehouse").annotate(
            total_value=F("quantity_on_hand") * effective_cost
        )

    @staticmethod
    @transaction.atomic
    def adjust_stock(organisation, product, warehouse, quantity, reason, created_by):
        """Manual stock adjustment (positive or negative)."""
        movement_type = (
            StockMovement.MovementType.ADJUSTMENT_IN
            if quantity > 0
            else StockMovement.MovementType.ADJUSTMENT_OUT
        )
        return InventoryService.record_movement(
            organisation=organisation,
            product=product,
            warehouse=warehouse,
            quantity=quantity,
            movement_type=movement_type,
            notes=reason,
            created_by=created_by,
        )

    @staticmethod
    @transaction.atomic
    def transfer_stock(
        organisation,
        product: Product,
        from_warehouse: Warehouse,
        to_warehouse: Warehouse,
        quantity: Decimal,
        notes: str = "",
        created_by=None,
    ) -> dict:
        """
        Transfer stock between two warehouses atomically.

        Creates paired TRANSFER_OUT + TRANSFER_IN ledger entries with a shared
        reference so the pair can always be traced back together.
        """
        import uuid as _uuid
        if from_warehouse.id == to_warehouse.id:
            raise ValueError("Source and destination warehouses must be different.")
        if quantity <= 0:
            raise ValueError("Transfer quantity must be positive.")

        ref = f"TRF-{str(_uuid.uuid4())[:8].upper()}"

        out_movement = InventoryService.record_movement(
            organisation=organisation,
            product=product,
            warehouse=from_warehouse,
            quantity=-quantity,
            movement_type=StockMovement.MovementType.TRANSFER_OUT,
            reference=ref,
            notes=notes,
            created_by=created_by,
        )
        in_movement = InventoryService.record_movement(
            organisation=organisation,
            product=product,
            warehouse=to_warehouse,
            quantity=quantity,
            movement_type=StockMovement.MovementType.TRANSFER_IN,
            reference=ref,
            notes=notes,
            created_by=created_by,
        )
        logger.info(
            "Stock transfer %s: %s × %s from '%s' → '%s'",
            ref, quantity, product.sku, from_warehouse.name, to_warehouse.name,
        )
        return {"reference": ref, "out": out_movement, "in": in_movement}
