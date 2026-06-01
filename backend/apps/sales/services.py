"""
Sales service layer.

Orchestrates the complex multi-step sale process:
    1. Validate stock availability
    2. Calculate line totals (discount + tax)
    3. Record stock movements (ledger)
    4. Create invoice
    5. Handle credit if applicable
    6. Update customer outstanding balance

All wrapped in a DB transaction for atomicity.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.utils import round_money
from apps.inventory.models import Product, Warehouse
from apps.inventory.services import InventoryService

from .models import Invoice, SaleItem, SalePayment, SaleReturn, SaleReturnItem

logger = logging.getLogger(__name__)


class SaleService:

    @staticmethod
    @transaction.atomic
    def create_sale(
        organisation,
        created_by,
        customer,
        warehouse: Warehouse,
        items: list[dict],
        payment_method: str,
        notes: str = "",
        sold_by: str = "",
        issue_date=None,
        due_date=None,
        is_proforma: bool = False,
        amount_paid: Decimal = None,
        amount_tendered: Decimal = None,
        credit_applied: Decimal = None,
        location=None,
    ) -> Invoice:
        """
        Create a confirmed sale invoice with stock deductions.

        Args:
            items: List of dicts:
                {
                    product_id, quantity, unit_price,
                    discount_percent (opt), batch_id (opt)
                }

        Returns:
            Confirmed Invoice with all related records created.
        """
        from django.utils import timezone as tz
        from apps.accounting.services import AccountingService

        issue_date = issue_date or tz.now().date()

        if AccountingService.is_period_locked(organisation, issue_date):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied(f"The period {issue_date.year}-{issue_date.month:02d} is locked. Unlock it before creating new transactions.")

        # Validate and normalise credit_applied
        credit_to_apply = Decimal("0")
        if credit_applied and credit_applied > Decimal("0") and not is_proforma:
            if not customer:
                raise ValueError("A customer must be selected to apply store credit.")
            if credit_applied > customer.store_credit:
                raise ValueError(
                    f"Cannot apply {credit_applied} — customer only has {customer.store_credit} store credit."
                )
            credit_to_apply = credit_applied

        # Resolve sold_by: use provided name or fall back to creating user's full name
        resolved_sold_by = (
            sold_by.strip()
            if sold_by and sold_by.strip()
            else f"{created_by.first_name} {created_by.last_name}".strip() or created_by.email
        )

        invoice = Invoice.objects.create(
            organisation=organisation,
            invoice_number=Invoice.generate_number(organisation),
            customer=customer,
            status=Invoice.Status.DRAFT,
            payment_method=payment_method,
            issue_date=issue_date,
            due_date=due_date,
            warehouse=warehouse,
            location=location,
            notes=notes,
            sold_by=resolved_sold_by,
            created_by=created_by,
            subtotal=Decimal("0"),
            discount_amount=Decimal("0"),
            tax_amount=Decimal("0"),
            total_amount=Decimal("0"),
            credit_applied=Decimal("0"),
            amount_paid=Decimal("0"),
            amount_due=Decimal("0"),
        )

        subtotal = Decimal("0")
        total_discount = Decimal("0")
        total_tax = Decimal("0")

        for item_data in items:
            line = SaleService._process_line_item(
                organisation=organisation,
                invoice=invoice,
                warehouse=warehouse,
                item_data=item_data,
                created_by=created_by,
                skip_stock=is_proforma,
            )
            subtotal += line["subtotal"]
            total_discount += line["discount_amount"]
            total_tax += line["tax_amount"]

        total = subtotal - total_discount + total_tax

        # Clamp credit to total (can't apply more credit than the invoice total)
        credit_to_apply = min(credit_to_apply, total)

        # Update invoice totals
        invoice.subtotal = subtotal
        invoice.discount_amount = total_discount
        invoice.tax_amount = total_tax
        invoice.total_amount = total
        invoice.credit_applied = credit_to_apply
        invoice.amount_due = total - credit_to_apply

        # Effective balance after applying store credit
        effective_due = total - credit_to_apply

        # Handle payment method / proforma
        if is_proforma:
            invoice.status = Invoice.Status.PROFORMA
        elif payment_method == Invoice.PaymentMethod.CREDIT:
            SaleService._handle_credit_sale(invoice, customer, effective_due, created_by)
        elif credit_to_apply >= total:
            # Credit covers the entire invoice — mark as paid immediately
            invoice.status = Invoice.Status.PAID
        else:
            invoice.status = Invoice.Status.CONFIRMED

        invoice.save()
        logger.info("Invoice %s created by %s for org %s", invoice.invoice_number, created_by, organisation.id)

        # Deduct store credit from customer balance (atomic with the transaction)
        if credit_to_apply > Decimal("0") and customer:
            from apps.customers.models import Customer as CustomerModel
            CustomerModel.objects.filter(pk=customer.pk).update(
                store_credit=customer.store_credit - credit_to_apply
            )

        # Auto-record cash payment for non-credit, non-proforma sales
        if not is_proforma and payment_method != Invoice.PaymentMethod.CREDIT and credit_to_apply < total:
            paid = amount_paid if amount_paid is not None else effective_due
            paid = min(paid, effective_due)  # Never record more than remaining balance
            if paid > Decimal("0"):
                payment = SalePayment.objects.create(
                    organisation=organisation,
                    invoice=invoice,
                    amount=paid,
                    method=payment_method,
                    reference="",
                    received_by=created_by,
                )
                invoice.amount_paid = paid
                invoice.amount_due = effective_due - paid
                if paid >= effective_due:
                    invoice.status = Invoice.Status.PAID
                elif paid > Decimal("0"):
                    invoice.status = Invoice.Status.PARTIALLY_PAID
                if amount_tendered and amount_tendered > paid:
                    payment.notes = f"Tendered: {amount_tendered}, Change: {amount_tendered - paid}"
                    payment.save(update_fields=["notes"])
                invoice.save(update_fields=["amount_paid", "amount_due", "status"])

        # Auto-post journal entry (non-blocking)
        from apps.accounting.services import safe_post_gl
        safe_post_gl(
            AccountingService.post_sale_journal, organisation, invoice, created_by,
            model_instance=invoice,
        )

        return invoice

    @staticmethod
    def _process_line_item(organisation, invoice, warehouse, item_data, created_by, skip_stock: bool = False) -> dict:
        """Process one line item: validate, create record, deduct stock."""
        product = Product.objects.select_for_update().get(
            id=item_data["product_id"], organisation=organisation
        )
        quantity = Decimal(str(item_data["quantity"]))
        unit_price = Decimal(str(item_data.get("unit_price", product.selling_price)))
        discount_pct = Decimal(str(item_data.get("discount_percent", 0)))

        subtotal = round_money(quantity * unit_price)
        discount_amount = round_money(subtotal * discount_pct / Decimal("100"))
        after_discount = subtotal - discount_amount

        # Apply product tax rate
        tax_rate = Decimal("0")
        if product.is_taxable and product.tax_class:
            tax_rate = product.tax_class.rate
        tax_amount = round_money(after_discount * tax_rate / Decimal("100"))

        line_total = after_discount + tax_amount

        # Deduct stock only for physical/digital products (services have no inventory)
        # skip_stock=True for proforma invoices (stock not reserved yet)
        if product.product_type != "service" and not skip_stock:
            InventoryService.record_movement(
                organisation=organisation,
                product=product,
                warehouse=warehouse,
                quantity=-quantity,
                movement_type="sale_out",
                unit_cost=product.cost_price,
                reference=invoice.invoice_number,
                created_by=created_by,
            )

        SaleItem.objects.create(
            organisation=organisation,
            invoice=invoice,
            product=product,
            quantity=quantity,
            unit_price=unit_price,
            discount_percent=discount_pct,
            discount_amount=discount_amount,
            tax_rate=tax_rate,
            tax_amount=tax_amount,
            line_total=line_total,
            cost_of_goods=round_money(quantity * product.cost_price),
        )

        return {
            "subtotal": subtotal,
            "discount_amount": discount_amount,
            "tax_amount": tax_amount,
            "line_total": line_total,
        }

    @staticmethod
    @transaction.atomic
    def update_sale(
        invoice: Invoice,
        updated_by,
        *,
        customer=None,
        warehouse=None,
        items: list[dict],
        notes: str = "",
        issue_date=None,
        due_date=None,
        payment_method: str = None,
    ) -> Invoice:
        """
        Full update of invoice line items and metadata.

        Allowed statuses: draft, proforma, confirmed, credit, partially_paid, overdue.
        Paid and voided invoices cannot be edited.

        For non-draft/proforma invoices, old physical-product sale_out stock movements
        are reversed via adjustment_in before new items are applied.

        Note: GL journal entries are NOT automatically reversed/re-posted here to avoid
        complex accounting state; owners should create a manual correcting entry if needed.
        """
        from apps.accounting.services import AccountingService

        EDITABLE_STATUSES = {
            Invoice.Status.DRAFT, Invoice.Status.PROFORMA,
            Invoice.Status.CONFIRMED, Invoice.Status.CREDIT,
            Invoice.Status.PARTIALLY_PAID, Invoice.Status.OVERDUE,
        }
        if invoice.status not in EDITABLE_STATUSES:
            raise ValueError(
                f"Invoices with status '{invoice.status}' cannot be edited."
            )

        effective_warehouse = warehouse or invoice.warehouse

        # Reverse old stock movements for physical products (not for draft/proforma)
        skip_stock_was = invoice.status in {Invoice.Status.DRAFT, Invoice.Status.PROFORMA}
        if not skip_stock_was:
            for old_item in invoice.items.select_related("product").all():
                if old_item.product.product_type != "service":
                    InventoryService.record_movement(
                        organisation=invoice.organisation,
                        product=old_item.product,
                        warehouse=invoice.warehouse,
                        quantity=old_item.quantity,   # positive = restore
                        movement_type="adjustment_in",
                        unit_cost=old_item.product.cost_price,
                        reference=f"EDIT:{invoice.invoice_number}",
                        created_by=updated_by,
                    )

        # Delete old line items
        invoice.items.all().delete()

        # Apply metadata updates
        if customer is not None:
            invoice.customer = customer
        if warehouse is not None:
            invoice.warehouse = warehouse
        if notes is not None:
            invoice.notes = notes
        if issue_date is not None:
            invoice.issue_date = issue_date
        if due_date is not None:
            invoice.due_date = due_date
        if payment_method is not None:
            invoice.payment_method = payment_method

        # Create new line items
        skip_stock_new = invoice.status in {Invoice.Status.DRAFT, Invoice.Status.PROFORMA}
        subtotal = Decimal("0")
        total_discount = Decimal("0")
        total_tax = Decimal("0")

        for item_data in items:
            line = SaleService._process_line_item(
                organisation=invoice.organisation,
                invoice=invoice,
                warehouse=effective_warehouse,
                item_data=item_data,
                created_by=updated_by,
                skip_stock=skip_stock_new,
            )
            subtotal += line["subtotal"]
            total_discount += line["discount_amount"]
            total_tax += line["tax_amount"]

        total = subtotal - total_discount + total_tax

        # Recalculate financials; preserve existing payments
        invoice.subtotal = subtotal
        invoice.discount_amount = total_discount
        invoice.tax_amount = total_tax
        invoice.total_amount = total
        amount_paid = invoice.amount_paid or Decimal("0")
        invoice.amount_due = max(total - amount_paid, Decimal("0"))

        invoice.save()
        logger.info(
            "Invoice %s updated by %s for org %s",
            invoice.invoice_number, updated_by, invoice.organisation.id,
        )
        return invoice

    @staticmethod
    def _handle_credit_sale(invoice: Invoice, customer, total: Decimal, recorded_by=None):
        """Mark as credit sale, create credit ledger entry, and update customer balance."""
        if customer is None:
            raise ValueError("Customer is required for credit sales.")
        if customer.is_credit_blocked:
            raise ValueError(
                f"Customer {customer.name} has exceeded their credit limit of {customer.credit_limit}."
            )
        invoice.status = Invoice.Status.CREDIT

        # Record in credits ledger (also updates customer.outstanding_balance)
        from apps.credits.services import CreditService
        CreditService.record_credit_debit(
            organisation=invoice.organisation,
            customer=customer,
            amount=total,
            invoice=invoice,
            due_date=invoice.due_date,
            recorded_by=recorded_by,
            description=f"Credit sale – {invoice.invoice_number}",
        )

    @staticmethod
    @transaction.atomic
    def record_payment(invoice: Invoice, amount: Decimal, method: str, received_by, reference="") -> SalePayment:
        """
        Record a payment against an invoice.

        Updates invoice status:
            amount_paid >= total_amount → PAID
            0 < amount_paid < total_amount → PARTIALLY_PAID
        """
        from django.db import transaction as _tx
        with _tx.atomic():
            # Re-read with row lock to prevent concurrent payment races
            invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)

            if invoice.status == Invoice.Status.PAID:
                raise ValueError("This invoice has already been fully paid.")
            if amount > invoice.amount_due:
                raise ValueError(
                    f"Payment of {amount} exceeds the outstanding balance of {invoice.amount_due}."
                )

            payment = SalePayment.objects.create(
                organisation=invoice.organisation,
                invoice=invoice,
                amount=amount,
                method=method,
                reference=reference,
                received_by=received_by,
            )

            invoice.amount_paid += amount
            invoice.amount_due = invoice.total_amount - invoice.amount_paid

            if invoice.amount_paid >= invoice.total_amount:
                invoice.status = Invoice.Status.PAID
                # Reduce customer outstanding balance
                if invoice.customer and invoice.payment_method == Invoice.PaymentMethod.CREDIT:
                    invoice.customer.outstanding_balance = max(
                        invoice.customer.outstanding_balance - invoice.total_amount, Decimal("0")
                    )
                    invoice.customer.save(update_fields=["outstanding_balance"])
            elif invoice.amount_paid > 0:
                invoice.status = Invoice.Status.PARTIALLY_PAID

            invoice.save(update_fields=["amount_paid", "amount_due", "status", "updated_at"])

        # Auto-post credit payment journal (non-blocking)
        if invoice.payment_method == Invoice.PaymentMethod.CREDIT:
            from apps.accounting.services import AccountingService, safe_post_gl
            safe_post_gl(
                AccountingService.post_credit_payment_journal,
                invoice.organisation, invoice.customer, amount, received_by,
                description=f"Credit payment – {invoice.invoice_number}",
                invoice=invoice,
                model_instance=invoice,
            )
        return payment

    @staticmethod
    def void_invoice(invoice: Invoice, voided_by) -> Invoice:
        """Void an invoice and reverse stock movements."""
        if invoice.status == Invoice.Status.PAID:
            raise ValueError("Paid invoices cannot be voided without a return process.")

        # Reverse all stock deductions (skip service items)
        for item in invoice.items.all():
            if item.product.product_type == "service":
                continue
            InventoryService.record_movement(
                organisation=invoice.organisation,
                product=item.product,
                warehouse=invoice.warehouse,
                quantity=item.quantity,  # positive = restocking
                movement_type="return_in",
                unit_cost=item.cost_of_goods / item.quantity,
                reference=f"VOID-{invoice.invoice_number}",
                created_by=voided_by,
            )

        invoice.status = Invoice.Status.VOIDED
        invoice.save(update_fields=["status", "updated_at"])
        return invoice

    @staticmethod
    @transaction.atomic
    def process_return(
        organisation,
        invoice: Invoice,
        items: list[dict],
        reason: str,
        notes: str,
        processed_by,
        restocked: bool = True,
        return_date=None,
    ) -> SaleReturn:
        """
        Process a sales return / credit note.

        Args:
            items: List of {sale_item_id, quantity_returned}
        """
        from django.utils import timezone as tz

        return_date = return_date or tz.now().date()

        total_refund = Decimal("0")
        return_items_to_create = []

        for item_data in items:
            sale_item = SaleItem.objects.select_for_update().get(
                id=item_data["sale_item_id"], invoice=invoice
            )
            qty = Decimal(str(item_data["quantity_returned"]))
            already_returned = sale_item.quantity_returned or Decimal("0")
            remaining_returnable = sale_item.quantity - already_returned
            if qty <= 0 or qty > remaining_returnable:
                raise ValueError(
                    f"Invalid return quantity {qty} for {sale_item.product.sku} "
                    f"(sold: {sale_item.quantity}, already returned: {already_returned}, "
                    f"remaining returnable: {remaining_returnable})"
                )

            # Proportional refund based on the remaining line value
            remaining_line_value = sale_item.line_total * remaining_returnable / sale_item.quantity
            refund = round_money(remaining_line_value * qty / remaining_returnable)
            total_refund += refund
            return_items_to_create.append((sale_item, qty, refund))

        sale_return = SaleReturn.objects.create(
            organisation=organisation,
            return_number=SaleReturn.generate_number(organisation),
            invoice=invoice,
            reason=reason,
            notes=notes,
            return_date=return_date,
            total_refund=total_refund,
            restocked=restocked,
            processed_by=processed_by,
        )

        for sale_item, qty, refund in return_items_to_create:
            SaleReturnItem.objects.create(
                organisation=organisation,
                sale_return=sale_return,
                original_item=sale_item,
                product=sale_item.product,
                quantity_returned=qty,
                unit_price=sale_item.unit_price,
                refund_amount=refund,
            )
            # Track cumulative returned quantity on the line item
            SaleItem.objects.filter(pk=sale_item.pk).update(
                quantity_returned=sale_item.quantity_returned + qty
            )
            # Restock physical products if requested
            if restocked and sale_item.product.product_type != "service":
                unit_cost = (
                    sale_item.cost_of_goods / sale_item.quantity
                    if sale_item.quantity
                    else sale_item.product.cost_price
                )
                InventoryService.record_movement(
                    organisation=organisation,
                    product=sale_item.product,
                    warehouse=invoice.warehouse,
                    quantity=qty,
                    movement_type="return_in",
                    unit_cost=unit_cost,
                    reference=sale_return.return_number,
                    created_by=processed_by,
                )

        # Update invoice status only when ALL items are fully returned (full reversal).
        # A partial return is a credit note against the original invoice — best accounting
        # practice (Xero / QuickBooks behaviour) leaves the invoice at its current status
        # (paid, confirmed, etc.) and lets the SaleReturn credit note carry the partial value.
        all_items = list(invoice.items.all())
        total_sold     = sum(Decimal(str(i.quantity))                         for i in all_items)
        total_returned = sum(Decimal(str(i.quantity_returned or 0))           for i in all_items)
        if total_sold > 0 and total_returned >= total_sold:
            Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.Status.RETURNED)

        # Update customer outstanding balance if credit sale and record in ledger
        if invoice.customer and invoice.payment_method == Invoice.PaymentMethod.CREDIT:
            from apps.credits.services import CreditService
            CreditService.record_payment(
                organisation=organisation,
                customer=invoice.customer,
                amount=total_refund,
                recorded_by=processed_by,
                description=f"Sales return – {sale_return.return_number}",
            )

        logger.info(
            "Return %s processed for invoice %s — refund %s",
            sale_return.return_number, invoice.invoice_number, total_refund,
        )
        return sale_return
