"""
Inventory service layer.

All stock mutations MUST go through this service.
Direct model saves that bypass this layer break the ledger.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import F

from .models import Batch, Product, StockItem, StockMovement, Warehouse

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
    ) -> StockMovement:
        """
        Core stock mutation function.

        Uses select_for_update() to prevent race conditions in concurrent
        sale/purchase recording. Atomically updates StockItem balance.

        Args:
            quantity: Positive for inward movements, negative for outward.
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
            unit_cost=unit_cost or product.cost_price,
            reference=reference,
            notes=notes,
            created_by=created_by,
            balance_after=new_balance,
        )

        logger.info(
            "StockMovement %s: %s %s × %s @ %s",
            movement.id, movement_type, quantity, product.sku, warehouse.name
        )
        return movement

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
        Calculate inventory value using weighted average cost.

        Returns list of dicts: {product, quantity, unit_cost, total_value}
        """
        from django.db.models import F, Sum

        qs = StockItem.objects.filter(organisation=organisation, quantity_on_hand__gt=0)
        if warehouse:
            qs = qs.filter(warehouse=warehouse)

        return qs.select_related("product", "warehouse").annotate(
            total_value=F("quantity_on_hand") * F("product__cost_price")
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
