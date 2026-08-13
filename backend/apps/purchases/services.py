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
        # A closed order cannot take delivery. Without this, receiving could be
        # replayed against an already-received PO and add the stock again, each
        # call also re-running _upsert_bill_for_po and inflating AP with it.
        # quick_receive() checked this; the plain receive() path did not, so the
        # guard lives here where both share it (NEW-12).
        closed = {
            PurchaseOrder.Status.RECEIVED,
            PurchaseOrder.Status.CLOSED,
            PurchaseOrder.Status.CANCELED,
        }
        if po.status in closed:
            raise ValueError(
                f"This purchase order is already {po.status} and cannot receive "
                f"more goods."
            )

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

            # Cap at what is actually outstanding. quantity_received was
            # previously incremented by whatever the caller sent, so a single
            # request could book 9,999 units against an order of 10 — inflating
            # both stock and the supplier bill, with no upper bound and no error.
            outstanding = Decimal(str(item.quantity_ordered)) - Decimal(str(item.quantity_received))
            if qty > outstanding:
                raise ValueError(
                    f"Cannot receive {qty} of {item.product.name}: only "
                    f"{outstanding} outstanding on this order."
                )

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


class PurchaseReturnService:
    """Process returns of received goods to a supplier."""

    @staticmethod
    @transaction.atomic
    def process_return(organisation, purchase_order, items, return_date=None,
                       refund_method="ap", reason="", created_by=None):
        """Create a PurchaseReturn, reduce inventory, and post the reversing journal.

        items: [{product_id, quantity, unit_cost?}]  (unit_cost defaults to the PO line cost)
        GL:  DR Accounts Payable / Cash / Bank (total incl VAT)
             CR Inventory        (net cost)
             CR VAT Input        (recoverable VAT reversed)
        """
        from datetime import date as _date
        from apps.accounting.services import AccountingService, AccountMappingService, safe_post_gl
        from apps.inventory.models import Product
        from .models import PurchaseReturn, PurchaseReturnItem, PurchaseOrderItem

        return_date = AccountingService._coerce_date(return_date) if return_date else _date.today()
        if not items:
            raise ValueError("A purchase return must have at least one line.")

        # PO VAT rate (proportional) for reversing input VAT.
        subtotal = Decimal(str(purchase_order.subtotal or 0))
        vat_rate = (Decimal(str(purchase_order.tax_amount or 0)) / subtotal) if subtotal else Decimal("0")

        pret = PurchaseReturn.objects.create(
            organisation=organisation,
            purchase_order=purchase_order,
            supplier=purchase_order.supplier,
            warehouse=purchase_order.warehouse,
            return_number=PurchaseReturn.generate_number(organisation),
            return_date=return_date,
            reason=reason,
            refund_method=refund_method,
            created_by=created_by,
        )

        net_total = Decimal("0")
        for row in items:
            product = Product.objects.get(id=row["product_id"], organisation=organisation)
            qty = Decimal(str(row["quantity"]))
            if qty <= 0:
                continue
            po_item = PurchaseOrderItem.objects.filter(
                purchase_order=purchase_order, product=product
            ).first()
            unit_cost = Decimal(str(row.get("unit_cost") or (po_item.unit_cost if po_item else 0)))
            line_total = qty * unit_cost
            net_total += line_total

            PurchaseReturnItem.objects.create(
                organisation=organisation, purchase_return=pret, po_item=po_item,
                product=product, quantity_returned=qty, unit_cost=unit_cost, line_total=line_total,
            )
            # Reduce stock (goods leave our warehouse back to the supplier).
            if product.product_type == "physical":
                InventoryService.record_movement(
                    organisation=organisation, product=product, warehouse=purchase_order.warehouse,
                    quantity=-qty, movement_type="adjustment_out", unit_cost=unit_cost,
                    reference=pret.return_number, created_by=created_by,
                )
            # Roll back the received quantity on the PO line.
            if po_item:
                po_item.quantity_received = max(Decimal("0"), po_item.quantity_received - qty)
                po_item.save(update_fields=["quantity_received"])

        vat_total = (net_total * vat_rate).quantize(Decimal("0.01"))
        grand_total = net_total + vat_total
        pret.subtotal = net_total
        pret.tax_amount = vat_total
        pret.total_amount = grand_total
        pret.save(update_fields=["subtotal", "tax_amount", "total_amount"])

        def _post():
            zero = Decimal("0")
            if refund_method == "cash":
                debit_acct = AccountMappingService.resolve(organisation, "cash_account")
            elif refund_method == "bank":
                debit_acct = AccountMappingService.resolve(organisation, "bank_account")
            else:
                debit_acct = AccountMappingService.resolve(organisation, "accounts_payable")
            inv_acct = AccountMappingService.resolve(organisation, "inventory_account")
            lines = [
                (debit_acct, grand_total, zero),   # DR AP / Cash / Bank
                (inv_acct, zero, net_total),        # CR Inventory
            ]
            if vat_total > 0:
                vat_acct = AccountMappingService.resolve(organisation, "vat_input_account")
                lines.append((vat_acct, zero, vat_total))  # CR VAT Input (reverse recoverable)
            AccountingService.post_journal_entry(
                organisation, f"Purchase return {pret.return_number}", return_date,
                lines, created_by, ref=pret.return_number,
                source_type="purchase_return", source_ref=str(pret.id),
            )

        safe_post_gl(_post, model_instance=pret)
        return pret
