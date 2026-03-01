"""
Inventory service tests: stock movements, low stock, valuation.
"""

import pytest
from decimal import Decimal

from apps.inventory.services import InventoryService
from apps.inventory.models import StockItem, StockMovement


@pytest.mark.integration
class TestStockMovements:

    def test_opening_stock_creates_stock_item(self, organisation, product, warehouse, user):
        """Recording an opening movement should create a StockItem."""
        InventoryService.record_movement(
            organisation=organisation,
            product=product,
            warehouse=warehouse,
            quantity=Decimal("50"),
            movement_type="opening",
            unit_cost=product.cost_price,
            created_by=user,
        )
        item = StockItem.objects.get(product=product, warehouse=warehouse)
        assert item.quantity_on_hand == Decimal("50")

    def test_sale_deducts_stock(self, organisation, stocked_product, warehouse, user):
        """A sale movement should reduce stock on hand."""
        initial = StockItem.objects.get(product=stocked_product, warehouse=warehouse)
        initial_qty = initial.quantity_on_hand

        InventoryService.record_movement(
            organisation=organisation,
            product=stocked_product,
            warehouse=warehouse,
            quantity=Decimal("-10"),
            movement_type="sale_out",
            unit_cost=stocked_product.cost_price,
            reference="INV-000001",
            created_by=user,
        )

        item = StockItem.objects.get(product=stocked_product, warehouse=warehouse)
        assert item.quantity_on_hand == initial_qty - Decimal("10")

    def test_insufficient_stock_raises_error(self, organisation, product, warehouse, user):
        """Trying to sell more than available should raise ValueError."""
        InventoryService.record_movement(
            organisation=organisation,
            product=product,
            warehouse=warehouse,
            quantity=Decimal("5"),
            movement_type="opening",
            unit_cost=product.cost_price,
            created_by=user,
        )

        with pytest.raises(ValueError, match="Insufficient stock"):
            InventoryService.record_movement(
                organisation=organisation,
                product=product,
                warehouse=warehouse,
                quantity=Decimal("-10"),  # More than available
                movement_type="sale_out",
                unit_cost=product.cost_price,
                created_by=user,
            )

    def test_movement_balance_recorded(self, organisation, product, warehouse, user):
        """Each movement should record the balance_after correctly."""
        InventoryService.record_movement(
            organisation=organisation,
            product=product,
            warehouse=warehouse,
            quantity=Decimal("100"),
            movement_type="opening",
            unit_cost=product.cost_price,
            created_by=user,
        )
        InventoryService.record_movement(
            organisation=organisation,
            product=product,
            warehouse=warehouse,
            quantity=Decimal("-30"),
            movement_type="sale_out",
            unit_cost=product.cost_price,
            created_by=user,
        )

        movements = StockMovement.objects.filter(product=product).order_by("created_at")
        assert movements[0].balance_after == Decimal("100")
        assert movements[1].balance_after == Decimal("70")
