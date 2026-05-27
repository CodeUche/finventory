"""Purchase order service: receive stock from suppliers."""

import logging
from datetime import timedelta
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

        - Triggers stock inward movements via InventoryService.
        - Auto-creates or updates a Bill so the receipt appears in AP aging.
        - Posts the GL journal (DR Inventory / CR Accounts Payable) via AccountingService.
        """
        all_received = True
        batch_subtotal = Decimal("0")

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

            batch_subtotal += qty * Decimal(str(item.unit_cost))

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

        # Auto-create / update Bill so this receipt shows in AP aging
        if po.supplier_id and batch_subtotal > 0:
            _upsert_bill_for_po(po, batch_subtotal, received_by)

        logger.info("PO %s received by %s", po.po_number, received_by)
        return po


def _upsert_bill_for_po(po: PurchaseOrder, batch_subtotal: Decimal, received_by) -> None:
    """
    Create a Bill (or add to the existing one) when a PO is received.
    One Bill per PO — subsequent partial receives increase the existing bill's amounts.
    Posts GL journal (DR Inventory CR AP) after creating/updating.
    """
    from apps.bills.models import Bill, BillItem
    from apps.accounting.services import AccountingService

    today = timezone.now().date()
    due_date = today + timedelta(days=30)

    existing = Bill.objects.filter(
        organisation=po.organisation,
        reference=po.po_number,
    ).first()

    if existing:
        # Add this batch's value to the existing bill
        existing.subtotal = Decimal(str(existing.subtotal)) + batch_subtotal
        existing.total_amount = Decimal(str(existing.total_amount)) + batch_subtotal
        existing.amount_due = Decimal(str(existing.amount_due)) + batch_subtotal
        existing.save(update_fields=["subtotal", "total_amount", "amount_due", "updated_at"])
        bill = existing
    else:
        bill = Bill.objects.create(
            organisation=po.organisation,
            supplier=po.supplier,
            status=Bill.RECEIVED,
            issue_date=today,
            due_date=due_date,
            reference=po.po_number,
            subtotal=batch_subtotal,
            tax_amount=Decimal("0"),
            total_amount=batch_subtotal,
            amount_due=batch_subtotal,
            notes=f"Auto-created from PO {po.po_number}",
            created_by=received_by,
        )
        # Create one summary BillItem for this receipt
        BillItem.objects.create(
            organisation=po.organisation,
            bill=bill,
            description=f"Goods received against {po.po_number}",
            quantity=Decimal("1"),
            unit_cost=batch_subtotal,
            line_total=batch_subtotal,
        )

    # Post GL: DR Inventory 1200 / CR Accounts Payable 2001
    try:
        zero = Decimal("0")
        amount = Decimal(str(batch_subtotal))
        AccountingService.post_journal_entry(
            po.organisation,
            f"Goods received {po.po_number}",
            timezone.now().date(),
            [("1200", amount, zero), ("2001", zero, amount)],
            received_by,
            ref=po.po_number,
        )
    except Exception as exc:
        logger.warning("GL journal for PO receipt %s failed: %s", po.po_number, exc)
