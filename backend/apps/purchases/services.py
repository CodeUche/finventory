"""Purchase order service: receive stock from suppliers."""

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.inventory.models import Batch
from apps.inventory.services import InventoryService

from .models import PurchaseOrder, PurchaseOrderItem

logger = logging.getLogger(__name__)


class PurchaseService:

    @staticmethod
    @transaction.atomic
    def receive_purchase_order(po: PurchaseOrder, received_items: list[dict], received_by) -> PurchaseOrder:
        """
        Record receipt of goods for a purchase order.

        Args:
            received_items: List of {item_id, quantity_received, batch_number, expiry_date}

        Triggers stock inward movements via InventoryService.
        """
        all_received = True

        for item_data in received_items:
            try:
                item = PurchaseOrderItem.objects.select_for_update().get(
                    id=item_data["item_id"], purchase_order=po
                )
            except PurchaseOrderItem.DoesNotExist:
                continue

            qty = Decimal(str(item_data["quantity_received"]))
            item.quantity_received += qty
            item.save(update_fields=["quantity_received", "updated_at"])

            # Create/update batch record
            batch = None
            if item_data.get("batch_number"):
                batch, _ = Batch.objects.get_or_create(
                    organisation=po.organisation,
                    product=item.product,
                    warehouse=po.warehouse,
                    batch_number=item_data["batch_number"],
                    defaults={
                        "quantity": qty,
                        "unit_cost": item.unit_cost,
                        "expiry_date": item_data.get("expiry_date"),
                    },
                )
                if not _:
                    batch.quantity += qty
                    batch.save(update_fields=["quantity", "updated_at"])

            # Record stock movement
            InventoryService.record_movement(
                organisation=po.organisation,
                product=item.product,
                warehouse=po.warehouse,
                quantity=qty,
                movement_type="purchase_in",
                unit_cost=item.unit_cost,
                reference=po.po_number,
                batch=batch,
                created_by=received_by,
            )

            if not item.is_fully_received:
                all_received = False

        po.status = (
            PurchaseOrder.Status.RECEIVED if all_received
            else PurchaseOrder.Status.PARTIALLY_RECEIVED
        )
        po.received_date = timezone.now().date() if all_received else po.received_date
        po.save(update_fields=["status", "received_date", "updated_at"])

        logger.info("PO %s received by %s", po.po_number, received_by)
        return po
