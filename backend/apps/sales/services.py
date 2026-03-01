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

from .models import Invoice, SaleItem, SalePayment

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
        issue_date=None,
        due_date=None,
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

        issue_date = issue_date or tz.now().date()

        invoice = Invoice.objects.create(
            organisation=organisation,
            invoice_number=Invoice.generate_number(organisation),
            customer=customer,
            status=Invoice.Status.DRAFT,
            payment_method=payment_method,
            issue_date=issue_date,
            due_date=due_date,
            warehouse=warehouse,
            notes=notes,
            created_by=created_by,
            subtotal=Decimal("0"),
            discount_amount=Decimal("0"),
            tax_amount=Decimal("0"),
            total_amount=Decimal("0"),
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
            )
            subtotal += line["subtotal"]
            total_discount += line["discount_amount"]
            total_tax += line["tax_amount"]

        total = subtotal - total_discount + total_tax

        # Update invoice totals
        invoice.subtotal = subtotal
        invoice.discount_amount = total_discount
        invoice.tax_amount = total_tax
        invoice.total_amount = total
        invoice.amount_due = total

        # Handle payment method
        if payment_method == Invoice.PaymentMethod.CREDIT:
            SaleService._handle_credit_sale(invoice, customer, total)
        else:
            invoice.status = Invoice.Status.CONFIRMED

        invoice.save()
        logger.info("Invoice %s created by %s for org %s", invoice.invoice_number, created_by, organisation.id)
        return invoice

    @staticmethod
    def _process_line_item(organisation, invoice, warehouse, item_data, created_by) -> dict:
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

        # Deduct stock (raises ValueError if insufficient)
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
    def _handle_credit_sale(invoice: Invoice, customer, total: Decimal):
        """Mark as credit sale and update customer balance."""
        if customer is None:
            raise ValueError("Customer is required for credit sales.")
        if customer.is_credit_blocked:
            raise ValueError(
                f"Customer {customer.name} has exceeded their credit limit of {customer.credit_limit}."
            )
        invoice.status = Invoice.Status.CREDIT

        # Update outstanding balance
        customer.outstanding_balance += total
        customer.save(update_fields=["outstanding_balance", "updated_at"])

    @staticmethod
    @transaction.atomic
    def record_payment(invoice: Invoice, amount: Decimal, method: str, received_by, reference="") -> SalePayment:
        """
        Record a payment against an invoice.

        Updates invoice status:
            amount_paid >= total_amount → PAID
            0 < amount_paid < total_amount → PARTIALLY_PAID
        """
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
        return payment

    @staticmethod
    def void_invoice(invoice: Invoice, voided_by) -> Invoice:
        """Void an invoice and reverse stock movements."""
        if invoice.status == Invoice.Status.PAID:
            raise ValueError("Paid invoices cannot be voided without a return process.")

        # Reverse all stock deductions
        for item in invoice.items.all():
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
