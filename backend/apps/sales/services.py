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
from django.db.models import F, Sum
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
        wht_rate_id=None,
        defer_fulfillment: bool = False,
        shipping_amount: Decimal = None,
        adjustment_amount: Decimal = None,
        strict_walk_in: bool = False,
        put_balance_on_customer: bool = False,
        charge_delivery_vat: bool = False,
    ) -> Invoice:
        """
        Create a confirmed sale invoice with stock deductions.

        Args:
            items: List of dicts:
                {
                    product_id, quantity, unit_price,
                    discount_percent (opt), batch_id (opt)
                }
            defer_fulfillment: When True, this is a "manual"/billed-ahead invoice --
                the invoice is raised and payments are taken now, but no stock
                leaves and no revenue/COGS is booked until fulfill_invoice().
                What IS booked now (see apps.sales.ledger): the money received,
                what the customer still owes, the undelivered sale held in
                Customer Deposits, and VAT (VAT is due on invoice/receipt, not
                delivery -- apps.sales.rules.VAT_TIMING).
            adjustment_amount: signed whole-invoice adjustment (negative =
                discount, positive = surcharge). Spread across the lines in
                proportion to their value BEFORE VAT, so a discount shrinks
                revenue and VAT together.
            strict_walk_in: API sales only -- with no customer the sale must be
                paid in full (there is nobody to chase for a balance). Internal
                callers (restaurant till, storefront) settle separately.
            charge_delivery_vat: API sales only -- VAT on the delivery charge at
                the goods' rate (still subject to
                rules.DELIVERY_VAT_FOLLOWS_GOODS). Other callers (storefront,
                quotes, recurring) compute their own totals without it, so they
                stay as they were until they are changed together.
            put_balance_on_customer: API sales only -- a balance left unpaid by a
                named customer is added to their account (and every later payment
                comes off it). Internal callers that settle by their own journal
                (restaurant till) keep the old behaviour.

        Returns:
            Confirmed Invoice with all related records created.

        Every ledger posting inside this call raises on failure and the whole
        sale rolls back with it.
        """
        from django.utils import timezone as tz
        from apps.accounting.services import AccountingService, check_strict_gl_mode
        from . import ledger, rules

        if payment_method == Invoice.PaymentMethod.MIXED:
            raise ValueError(
                "Mixed is not a payment method on its own. Record each part as a separate payment "
                "(cash, transfer or card)."
            )

        issue_date = issue_date or tz.localdate()
        shipping = round_money(Decimal(str(shipping_amount))) if shipping_amount else Decimal("0")
        if shipping < 0:
            raise ValueError("Shipping amount cannot be negative.")

        check_strict_gl_mode(organisation)

        if AccountingService.is_period_locked(organisation, issue_date, user=created_by):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied(f"The period {issue_date.year}-{issue_date.month:02d} is locked. Unlock it before creating new transactions.")

        # Validate and normalise credit_applied
        credit_to_apply = Decimal("0")
        if credit_applied and credit_applied > Decimal("0") and not is_proforma:
            if not customer:
                raise ValueError("A customer must be selected to apply store credit.")
            # Lock the customer row and read the balance AFTER the lock: the
            # copy the caller holds may be stale, and two sales spending the same
            # credit at once must queue up, not both pass the check.
            from apps.customers.models import Customer as CustomerModel
            locked = CustomerModel.objects.select_for_update().get(
                pk=customer.pk, organisation=organisation)
            if credit_applied > locked.store_credit:
                raise ValueError(
                    f"Cannot apply {credit_applied} — customer only has {locked.store_credit} store credit."
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
            shipping_amount=shipping,
            total_amount=Decimal("0"),
            credit_applied=Decimal("0"),
            amount_paid=Decimal("0"),
            amount_due=Decimal("0"),
            is_deferred=defer_fulfillment,
            wht_rate_id=wht_rate_id,
            vat_timing=rules.vat_timing(),
        )

        totals = SaleService._build_lines(
            organisation=organisation, invoice=invoice, warehouse=warehouse, items=items,
            created_by=created_by, skip_stock=is_proforma or defer_fulfillment,
            shipping=shipping, adjustment=adjustment_amount, charge_delivery_vat=charge_delivery_vat,
        )
        total = totals["total"]

        # Clamp credit to total (can't apply more credit than the invoice total)
        credit_to_apply = min(credit_to_apply, total)

        # Update invoice totals
        invoice.subtotal = totals["subtotal"]
        invoice.discount_amount = totals["discount"]
        invoice.tax_amount = totals["tax"]
        invoice.shipping_tax_amount = totals["shipping_tax"]
        invoice.adjustment_amount = totals["adjustment"]
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

        if strict_walk_in and customer is None and not is_proforma:
            intended = amount_paid if amount_paid is not None else effective_due
            if intended + Decimal("0.01") < effective_due:
                raise ValueError(
                    "A walk-in sale must be paid in full. Pick a customer to leave a balance "
                    "unpaid or to sell on credit."
                )

        invoice.save()
        logger.info("Invoice %s created by %s for org %s", invoice.invoice_number, created_by, organisation.id)

        # Outbox event for the paid integrations marketplace (Track C) — same
        # transaction as the invoice write above, so a rolled-back sale never
        # leaves a dangling "invoice.created" event.
        from apps.integrations.services import IntegrationEventService
        IntegrationEventService.emit(
            organisation, "invoice.created",
            {
                "invoice_id": str(invoice.id),
                "invoice_number": invoice.invoice_number,
                "total_amount": str(invoice.total_amount),
                "customer_id": str(customer.id) if customer else None,
                "status": invoice.status,
                # Consumed by the Google Calendar connector deliverer
                # (apps.connectors.services._deliver_to_calendar) to create
                # a due-date event — None/absent for invoices with no due
                # date (e.g. proforma), which that deliverer treats as
                # "nothing to schedule", not a failure.
                "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            },
        )

        # Deduct store credit from customer balance (atomic with the transaction)
        if credit_to_apply > Decimal("0") and customer:
            from apps.customers.models import Customer as CustomerModel
            CustomerModel.objects.filter(pk=customer.pk, organisation=organisation).update(
                store_credit=F("store_credit") - credit_to_apply
            )

        # Auto-record cash payment for non-credit, non-proforma sales
        paid = Decimal("0")
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
                    # Counter and Register sales are paid here, at the moment of
                    # sale. Without the till link (record_payment already set it)
                    # the till saw none of its own takings: the Z-report showed
                    # zero sales and the whole drawer was posted as an "overage".
                    till_session=SaleService._open_till_for(organisation, created_by),
                    # This cash is folded into the sale's own journal entry.
                    in_sale_journal=True,
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

        # A balance left unpaid by a named customer is owed by that customer:
        # put it on their account so the customer record, AR and every later
        # payment agree. (Credit sales already did this above.)
        if (
            put_balance_on_customer and not is_proforma and customer
            and payment_method != Invoice.PaymentMethod.CREDIT
            and invoice.amount_due > Decimal("0")
        ):
            from apps.credits.services import CreditService
            CreditService.record_credit_debit(
                organisation=organisation, customer=customer, amount=invoice.amount_due,
                invoice=invoice, due_date=invoice.due_date, recorded_by=created_by,
                description=f"Unpaid balance – {invoice.invoice_number}",
            )

        # Journal entry. Raises on failure: the sale, its stock movements and
        # its payment all roll back together (a failed journal used to be
        # logged and swallowed, leaving a sale that never reached the books).
        if not is_proforma:
            SaleService._post_sale_entry(
                invoice, created_by,
                mode="deferred" if defer_fulfillment else "full", entry_date=issue_date,
            )

        # WHT is deducted when each PAYMENT is made, not on the invoice total.
        if wht_rate_id and not is_proforma and paid > Decimal("0"):
            SaleService._record_wht(invoice, paid, issue_date)

        return invoice

    @staticmethod
    def _money_signature(invoice):
        """Everything about an invoice that moves money: its lines (product,
        quantity, price, discount, VAT, adjustment) and its totals. Two equal
        signatures mean an edit changed nothing the ledger cares about."""
        lines = sorted(
            (str(i.product_id), Decimal(str(i.quantity)), Decimal(str(i.unit_price)),
             Decimal(str(i.discount_percent)), Decimal(str(i.tax_rate)),
             Decimal(str(i.adjustment_amount)), Decimal(str(i.line_total)))
            for i in invoice.items.all()
        )
        return (
            lines, Decimal(str(invoice.shipping_amount or 0)), Decimal(str(invoice.adjustment_amount or 0)),
            Decimal(str(invoice.total_amount or 0)), Decimal(str(invoice.tax_amount or 0)),
        )

    @staticmethod
    def _post_sale_entry(invoice, actor, **kwargs):
        """Post the sale entry. Every failure raises (and the surrounding
        transaction rolls the sale back) EXCEPT one that is already a visible,
        retryable state in this product: an account the organisation has not
        mapped yet (and has not demanded via strict GL mode). That sale stands,
        the invoice is flagged gl_post_status='not_configured' with the missing
        role in gl_post_error, and "retry GL post" posts it once mapped."""
        from apps.accounting.exceptions import GLAccountNotConfigured
        from . import ledger
        try:
            entry = ledger.post_sale_entry(invoice.organisation, invoice, actor, **kwargs)
        except GLAccountNotConfigured as exc:
            invoice.gl_post_status = "not_configured"
            invoice.gl_post_error = f"GL account not configured: {exc.role}"
            invoice.save(update_fields=["gl_post_status", "gl_post_error"])
            logger.warning("Sale entry for %s not posted: %s", invoice.invoice_number, invoice.gl_post_error)
            return None
        invoice.gl_post_status = "posted"
        invoice.gl_post_error = ""
        invoice.save(update_fields=["gl_post_status", "gl_post_error"])
        return entry

    @staticmethod
    def _record_wht(invoice, amount, transaction_date):
        """One WHT record for one payment received. No-op unless the customer
        deducts WHT on this invoice (invoice.wht_rate_id). Rate and base are
        TaxService's own rules, unchanged."""
        if not invoice.wht_rate_id or not amount or amount <= 0:
            return
        customer = invoice.customer
        from apps.tax.services import TaxService
        TaxService.auto_create_wht_transaction(
            organisation=invoice.organisation,
            wht_rate_id=invoice.wht_rate_id,
            transaction_type='sale',
            gross_amount=Decimal(str(amount)),
            counterparty_name=customer.name if customer else "Walk-in",
            transaction_date=transaction_date,
            tin=(getattr(customer, 'tax_id', '') or '') if customer else '',
            source_ref=invoice.invoice_number,
        )

    @staticmethod
    def _reverse_wht(invoice):
        """Withdraw the WHT records _record_wht made for this invoice (void /
        delete): tax records must not keep a withholding credit for a sale that no
        longer stands. Records already remitted are left and logged for a person."""
        from django.db.models import Q
        from apps.tax.models import WHTTransaction
        base = f"Auto-created from sale {invoice.invoice_number}"
        qs = WHTTransaction.objects.filter(
            organisation=invoice.organisation, transaction_type=WHTTransaction.SALE,
        ).filter(Q(notes=base) | Q(notes__startswith=base + ". "))
        for rec in qs:
            if rec.status == WHTTransaction.WITHHELD:
                rec.delete()          # soft delete: drops out of every WHT report
            else:
                logger.warning("WHT record %s for %s is already remitted; not withdrawn",
                               rec.id, invoice.invoice_number)

    @staticmethod
    def _close_payment_requests(invoice):
        """A voided / deleted invoice must not stay payable: cancel its open
        checkout links and one-time transfer accounts."""
        from apps.payments.models import PaymentLink, VirtualAccount
        PaymentLink.objects.filter(
            organisation=invoice.organisation, invoice=invoice, status=PaymentLink.PENDING,
        ).update(status=PaymentLink.CANCELLED)
        VirtualAccount.objects.filter(
            organisation=invoice.organisation, invoice=invoice, status=VirtualAccount.PENDING,
        ).update(status=VirtualAccount.CANCELLED)

    @staticmethod
    def _allocate_adjustment(priced: list, adjustment) -> list:
        """Spread a signed whole-invoice adjustment across the lines in
        proportion to their (after-discount) value. The last line takes the
        rounding remainder so the shares add up to the adjustment exactly."""
        from . import rules
        adjustment = round_money(Decimal(str(adjustment or 0)))
        zero = Decimal("0")
        if adjustment == 0:
            return [zero] * len(priced)
        if adjustment > 0 and not rules.surcharge_taxed_like_discount():
            raise ValueError("A surcharge adjustment is not enabled. Use a negative adjustment (a discount).")
        base = sum((p["after_discount"] for p in priced), zero)
        if base <= 0:
            raise ValueError("An adjustment needs invoice lines with a value to spread it across.")
        if adjustment < 0 and -adjustment > base:
            raise ValueError(
                f"The adjustment of {adjustment} is larger than the invoice value of {base}."
            )
        shares, running = [], zero
        for i, p in enumerate(priced):
            if i == len(priced) - 1:
                share = adjustment - running
            else:
                share = round_money(adjustment * p["after_discount"] / base)
            running += share
            shares.append(share)
        for p, share in zip(priced, shares):
            if p["after_discount"] + share < 0:
                raise ValueError("The adjustment would take a line below zero. Reduce the adjustment.")
        return shares

    @staticmethod
    def _delivery_tax(shipping: Decimal, tax_basis: list) -> Decimal:
        """VAT on the delivery charge: it follows the goods. tax_basis is
        [(line value after discount + adjustment, line VAT rate %)]; a mixed
        basket splits the charge between its lines by value."""
        from . import rules
        zero = Decimal("0")
        if shipping <= 0 or not rules.delivery_vat_follows_goods():
            return zero
        base = sum((v for v, _ in tax_basis), zero)
        if base <= 0:
            return zero
        return round_money(sum((shipping * v * r / (base * Decimal("100")) for v, r in tax_basis), zero))

    @staticmethod
    def _build_lines(*, organisation, invoice, warehouse, items, created_by, skip_stock,
                     shipping: Decimal, adjustment, charge_delivery_vat: bool = False) -> dict:
        """Price every line, spread the adjustment, charge VAT, create the
        SaleItems (and stock movements). Shared by create_sale and update_sale."""
        zero = Decimal("0")
        priced = [SaleService._price_line(organisation, item) for item in items]
        shares = SaleService._allocate_adjustment(priced, adjustment)

        subtotal = total_discount = total_tax = lines_total = zero
        tax_basis = []
        for p, share in zip(priced, shares):
            line = SaleService._commit_line(
                organisation=organisation, invoice=invoice, warehouse=warehouse, priced=p,
                adjustment=share, created_by=created_by, skip_stock=skip_stock,
            )
            subtotal += line["subtotal"]
            total_discount += line["discount_amount"]
            total_tax += line["tax_amount"]
            lines_total += line["line_total"]
            tax_basis.append((p["after_discount"] + share, p["tax_rate"]))

        shipping_tax = SaleService._delivery_tax(shipping, tax_basis) if charge_delivery_vat else Decimal("0")
        if lines_total + shipping + shipping_tax < 0:
            raise ValueError("The invoice total cannot be negative.")
        # Sum the lines, not subtotal − discount + tax: a VAT-inclusive line's
        # tax is already inside its price (line_total == after-discount), so
        # adding total_tax on top charged that VAT twice — a 1,075 shelf price
        # billed 1,150 and posted 1,075 as revenue with a phantom 75 owed.
        # For exclusive lines line_total is after-discount + tax: same figure.
        return {
            "subtotal": subtotal,
            "discount": total_discount,
            "tax": total_tax + shipping_tax,
            "shipping_tax": shipping_tax,
            "adjustment": round_money(Decimal(str(adjustment or 0))),
            "total": lines_total + shipping + shipping_tax,
        }

    @staticmethod
    def default_tax_rate(product) -> Decimal:
        """The VAT rate a product carries by default: its tax class's, when taxable
        and the business charges VAT at all."""
        if not product.organisation.charges_vat:
            return Decimal("0")
        if product.is_taxable and product.tax_class:
            return Decimal(str(product.tax_class.rate))
        return Decimal("0")

    @staticmethod
    def apply_tax(product, after_discount: Decimal, tax_rate: Decimal):
        """(tax_amount, line_total) for one line. Exclusive adds the tax on top;
        inclusive backs it out of a price that already contains it. Shared with
        the restaurant order screen's totals so a split bill adds up to the
        invoice it becomes."""
        if product.tax_type == Product.TaxType.INCLUSIVE and tax_rate > 0:
            return round_money(after_discount * tax_rate / (Decimal("100") + tax_rate)), after_discount
        tax_amount = round_money(after_discount * tax_rate / Decimal("100"))
        return tax_amount, after_discount + tax_amount

    @staticmethod
    def _price_line(organisation, item_data) -> dict:
        """Resolve one line's product, price, discount, VAT rate and batch.
        Nothing is written; the adjustment and VAT are applied afterwards."""
        product = Product.objects.select_for_update().get(
            id=item_data["product_id"], organisation=organisation
        )
        if product.product_type == Product.ProductType.VARIABLE:
            raise ValueError(
                f"'{product.name}' is a Variable Product template — sell one of its variants instead."
            )
        quantity = Decimal(str(item_data["quantity"]))
        base_price = Decimal(str(item_data.get("unit_price", product.selling_price)))
        discount_pct = Decimal(str(item_data.get("discount_percent", 0)))

        # Modifier prices are resolved here, never taken from the caller — the
        # same rule as the POS order path (see POSOrderService.create_order).
        modifiers = []
        modifier_ids = item_data.get("modifiers") or item_data.get("modifier_options")
        if modifier_ids:
            from apps.inventory.modifier_services import ModifierService
            unit_price, modifiers = ModifierService.unit_price(
                product, modifier_ids, base_price=base_price,
            )
        else:
            unit_price = base_price

        subtotal = round_money(quantity * unit_price)
        discount_amount = round_money(subtotal * discount_pct / Decimal("100"))
        after_discount = subtotal - discount_amount

        # Per-line VAT override: an explicit rate wins, then a chosen TaxClass,
        # then the product's own default — lets a line be taxed differently
        # from what the product is normally configured for (e.g. a one-off
        # rate, or a class the product wasn't assigned).
        tax_rate = Decimal("0")
        rate_override = item_data.get("tax_rate")
        class_override_id = item_data.get("tax_class_id")
        resolved_override = False
        if rate_override is not None:
            tax_rate = Decimal(str(rate_override))
            resolved_override = True
        elif class_override_id:
            from apps.tax.models import TaxClass
            override_class = TaxClass.objects.filter(
                id=class_override_id, organisation=organisation, is_active=True
            ).first()
            if override_class:
                tax_rate = override_class.rate
                resolved_override = True
        if not resolved_override:
            tax_rate = SaleService.default_tax_rate(product)
        if not organisation.charges_vat:
            tax_rate = Decimal("0")   # not registered for VAT: nothing to add, whatever the line says

        # Specific Unit costing sells FROM a chosen lot, so the batch has to be
        # resolved before the movement.
        batch = None
        batch_id = item_data.get("batch_id")
        if batch_id:
            from apps.inventory.models import Batch
            batch = Batch.objects.filter(
                id=batch_id, organisation=organisation, product=product,
            ).first()

        return {
            "product": product, "quantity": quantity, "unit_price": unit_price,
            "discount_pct": discount_pct, "subtotal": subtotal,
            "discount_amount": discount_amount, "after_discount": after_discount,
            "tax_rate": tax_rate, "modifiers": modifiers, "batch": batch,
        }

    @staticmethod
    def _commit_line(organisation, invoice, warehouse, priced, adjustment, created_by,
                     skip_stock: bool = False) -> dict:
        """Apply the line's share of the adjustment, charge VAT on the adjusted
        amount, deduct stock, and create the SaleItem."""
        product = priced["product"]
        quantity = priced["quantity"]
        batch = priced["batch"]
        after_adjustment = priced["after_discount"] + adjustment
        if priced["unit_price"] < 0 or after_adjustment < 0:
            raise ValueError(f"'{product.name}' would have a negative amount. Prices and discounts cannot go below zero.")
        tax_amount, line_total = SaleService.apply_tax(product, after_adjustment, priced["tax_rate"])
        if line_total < 0:
            raise ValueError(f"'{product.name}' would have a negative total.")

        # Deduct stock only for physical/digital products (services have no inventory)
        # skip_stock=True for proforma / fulfil-later invoices (stock not leaving yet)
        cost_per_unit = product.cost_price
        if product.product_type == Product.ProductType.COMBO and not skip_stock:
            # A combo has no stock of its own — selling it deducts each of its
            # bill-of-materials components from their own stock instead.
            cost_per_unit = InventoryService.consume_combo_components(
                organisation=organisation,
                combo_product=product,
                warehouse=warehouse,
                quantity=quantity,
                reference=invoice.invoice_number,
                created_by=created_by,
            )
        elif product.product_type != "service" and not skip_stock:
            movement = InventoryService.record_movement(
                organisation=organisation,
                product=product,
                warehouse=warehouse,
                quantity=-quantity,
                movement_type="sale_out",
                unit_cost=product.cost_price,
                reference=invoice.invoice_number,
                created_by=created_by,
                batch=batch,
                # The one path the reviewer's costing-method request is about:
                # value this sale per the product's FIFO/LIFO/Average/Specific
                # method instead of the flat product.cost_price.
                use_costing_engine=True,
            )
            # COGS must agree with the cost the ledger actually consumed —
            # the journal reads cost_of_goods, so taking product.cost_price
            # here would post a different figure to the GL than the stock ledger
            # recorded, and the two would drift apart permanently.
            cost_per_unit = movement.unit_cost

        SaleItem.objects.create(
            organisation=organisation,
            invoice=invoice,
            product=product,
            batch=batch,
            quantity=quantity,
            unit_price=priced["unit_price"],
            discount_percent=priced["discount_pct"],
            discount_amount=priced["discount_amount"],
            adjustment_amount=adjustment,
            tax_rate=priced["tax_rate"],
            tax_amount=tax_amount,
            line_total=line_total,
            cost_of_goods=round_money(quantity * cost_per_unit),
            modifiers=priced["modifiers"],
        )

        return {
            "subtotal": priced["subtotal"],
            "discount_amount": priced["discount_amount"],
            "tax_amount": tax_amount,
            "line_total": line_total,
        }

    @staticmethod
    def _process_line_item(organisation, invoice, warehouse, item_data, created_by, skip_stock: bool = False) -> dict:
        """Price and commit one line with no adjustment (kept for callers that
        build an invoice line by line)."""
        priced = SaleService._price_line(organisation, item_data)
        return SaleService._commit_line(
            organisation, invoice, warehouse, priced, Decimal("0"), created_by, skip_stock=skip_stock,
        )

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
        shipping_amount=None,
        adjustment_amount=None,
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
        from . import ledger

        # Lock the row and work from what is stored NOW: the caller's copy may be
        # from before a payment landed or a void happened, and saving it would
        # overwrite them. Status is judged after the lock.
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk, organisation=invoice.organisation)

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

        # An invoice that already has its sale in the ledger: what can be edited
        # safely is limited, and an edit of its money re-posts the entry below.
        posted = any(e.source_type in ledger.SALE_SOURCES for e in ledger.invoice_entries(invoice, live_only=True))
        if posted:
            if invoice.is_deferred and invoice.fulfilled_at is not None:
                raise ValueError(ledger.EDIT_REFUSAL)
            if customer is not None and customer.pk != invoice.customer_id:
                raise ValueError(
                    "The customer cannot be changed once the invoice is posted. "
                    "Void this invoice and issue a new one."
                )
            if payment_method is not None and payment_method != invoice.payment_method:
                raise ValueError(
                    "The payment method cannot be changed once the invoice is posted. "
                    "Void this invoice and issue a new one."
                )
        old_signature = SaleService._money_signature(invoice)
        old_due = Decimal(str(invoice.amount_due or 0))

        # Reverse old stock movements for physical products (not for draft/proforma)
        # (a fulfil-later invoice not yet delivered never moved any stock either)
        skip_stock_was = (
            invoice.status in {Invoice.Status.DRAFT, Invoice.Status.PROFORMA}
            or (invoice.is_deferred and invoice.fulfilled_at is None)
        )
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
        skip_stock_new = skip_stock_was

        # None means "leave it alone" (the caller didn't touch shipping) —
        # distinct from an explicit 0, which clears it. Only the edit-invoice
        # UI passes a value here; every other caller of update_sale omits it
        # and keeps today's behaviour of carrying the old amount forward.
        shipping = round_money(Decimal(str(shipping_amount))) if shipping_amount is not None else Decimal(str(invoice.shipping_amount or 0))
        if shipping < 0:
            raise ValueError("Shipping amount cannot be negative.")
        adjustment = Decimal(str(adjustment_amount)) if adjustment_amount is not None else Decimal(str(invoice.adjustment_amount or 0))

        totals = SaleService._build_lines(
            organisation=invoice.organisation, invoice=invoice, warehouse=effective_warehouse,
            items=items, created_by=updated_by, skip_stock=skip_stock_new,
            shipping=shipping, adjustment=adjustment,
            # an invoice raised with VAT on its delivery keeps it when edited
            charge_delivery_vat=Decimal(str(invoice.shipping_tax_amount or 0)) > 0,
        )
        total = totals["total"]

        # Recalculate financials; preserve existing payments
        invoice.subtotal = totals["subtotal"]
        invoice.discount_amount = totals["discount"]
        invoice.tax_amount = totals["tax"]
        invoice.shipping_amount = shipping
        invoice.shipping_tax_amount = totals["shipping_tax"]
        invoice.adjustment_amount = totals["adjustment"]
        invoice.total_amount = total
        amount_paid = invoice.amount_paid or Decimal("0")
        credit_used = Decimal(str(invoice.credit_applied or 0))
        raw_due = total - credit_used - amount_paid
        invoice.amount_due = max(raw_due, Decimal("0"))

        if posted and SaleService._money_signature(invoice) != old_signature:
            # The edit changed money on an invoice already in the ledger: undo its
            # entry and post it again at the new figures, fix the customer's
            # balance, all in this one transaction (any failure rolls the edit back).
            if raw_due < 0:
                raise ValueError(
                    f"The new total is lower than the {amount_paid + credit_used} already paid or credited. "
                    "Refund the payment first, or void this invoice and issue a new one."
                )
            if invoice.amount_due == 0 and invoice.status in (
                Invoice.Status.CONFIRMED, Invoice.Status.PARTIALLY_PAID,
                Invoice.Status.CREDIT, Invoice.Status.OVERDUE,
            ):
                invoice.status = Invoice.Status.PAID
            invoice.save()
            ledger.repost_sale_entry(invoice, updated_by)
            delta = invoice.amount_due - old_due
            if invoice.customer_id and delta != 0 and SaleService._debt_on_customer_account(invoice):
                from apps.credits.services import CreditService
                if delta > 0:
                    CreditService.record_credit_debit(
                        organisation=invoice.organisation, customer=invoice.customer, amount=delta,
                        invoice=invoice, due_date=invoice.due_date, recorded_by=updated_by,
                        description=f"Invoice edited – {invoice.invoice_number}",
                    )
                else:
                    CreditService.record_payment(
                        organisation=invoice.organisation, customer=invoice.customer, amount=-delta,
                        recorded_by=updated_by, description=f"Invoice edited – {invoice.invoice_number}",
                        post_gl=False,
                    )

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
    def _open_till_for(organisation, user):
        """The cashier's open till session, if they have one."""
        if user is None:
            return None
        try:
            from apps.pos.till_services import TillService
            return TillService.current_session(organisation, user)
        except Exception:  # pragma: no cover — a till lookup must never fail a sale
            return None

    @staticmethod
    @transaction.atomic
    def record_payment(invoice: Invoice, amount: Decimal, method: str, received_by, reference="") -> SalePayment:
        """
        Record a payment against an invoice.

        Updates invoice status:
            amount_paid >= total_amount → PAID
            0 < amount_paid < total_amount → PARTIALLY_PAID
        (a proforma stays a proforma: the money is a deposit.)

        Every payment gets its own journal entry (DR Cash/Bank, CR Accounts
        Receivable -- or CR Customer Deposits + VAT for a proforma deposit), its
        own WHT record when the customer deducts WHT, and moves the customer's
        balance when the invoice's debt sits on their account. A failed journal
        rolls the whole payment back.
        """
        from django.db import transaction as _tx
        from . import ledger
        with _tx.atomic():
            # Re-read with row lock to prevent concurrent payment races
            invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)

            if invoice.status == Invoice.Status.PAID:
                raise ValueError("This invoice has already been fully paid.")
            if invoice.status == Invoice.Status.VOIDED:
                raise ValueError("A voided invoice cannot take payments.")
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
                # Attach to the cashier's open till so the end-of-day count is
                # exact. None for gateway/storefront payments, which is right —
                # that money never reaches the drawer.
                till_session=SaleService._open_till_for(invoice.organisation, received_by),
            )

            credit_used = Decimal(str(invoice.credit_applied or 0))
            invoice.amount_paid += amount
            invoice.amount_due = invoice.total_amount - credit_used - invoice.amount_paid

            if invoice.status != Invoice.Status.PROFORMA:
                if invoice.amount_paid + credit_used >= invoice.total_amount:
                    invoice.status = Invoice.Status.PAID
                elif invoice.amount_paid > 0:
                    invoice.status = Invoice.Status.PARTIALLY_PAID

            invoice.save(update_fields=["amount_paid", "amount_due", "status", "updated_at"])

            # The books: raises, rolling this payment back with it.
            ledger.post_receipt_entry(
                invoice.organisation, invoice, payment, received_by,
                entry_date=timezone.localdate(),
            )

            # Outbox event for the paid integrations marketplace (Track C) —
            # same transaction as the payment + invoice update above.
            from apps.integrations.services import IntegrationEventService
            IntegrationEventService.emit(
                invoice.organisation, "payment.received",
                {
                    "invoice_id": str(invoice.id),
                    "invoice_number": invoice.invoice_number,
                    "payment_id": str(payment.id),
                    "amount": str(amount),
                    "method": method,
                    "invoice_status": invoice.status,
                },
            )

            # Customer sub-ledger: only when this invoice's debt was put on the
            # customer's account (every credit sale, and any named-customer sale
            # left partly unpaid). The receipt journal above already moved AR,
            # so the credit service must not post a second one.
            if invoice.customer_id and SaleService._debt_on_customer_account(invoice):
                from apps.credits.services import CreditService
                CreditService.record_payment(
                    organisation=invoice.organisation,
                    customer=invoice.customer,
                    amount=amount,
                    recorded_by=received_by or invoice.created_by,   # webhooks have no user
                    description=f"Payment – {invoice.invoice_number}",
                    method=method,
                    post_gl=False,
                )

            # WHT is deducted when each payment is made.
            SaleService._record_wht(invoice, amount, timezone.localdate())

        return payment

    @staticmethod
    def _debt_on_customer_account(invoice) -> bool:
        from apps.credits.models import CreditTransaction
        return CreditTransaction.objects.filter(
            invoice=invoice, transaction_type=CreditTransaction.TransactionType.DEBIT,
        ).exists()

    @staticmethod
    def record_payment_from_gateway(invoice: Invoice, amount: Decimal, reference: str,
                                    channel: str = "bank_transfer", provider: str = "") -> "SalePayment":
        """Record a payment confirmed by a payment provider.

        There is no signed-in user behind a webhook, so ``received_by`` is None.
        `channel` is the provider's own wording normalised to a tender we
        already understand ('card' / 'bank_transfer' / 'pos'), which is what
        decides whether the money lands in cash or bank in the ledger.

        Callers must have already guarded against replays — see
        PaymentService.settle.
        """
        method = channel if channel in {"cash", "card", "bank_transfer", "pos"} else "bank_transfer"
        payment = SaleService.record_payment(
            invoice=invoice,
            amount=Decimal(str(amount)),
            method=method,
            received_by=None,
            reference=reference or "",
        )

        # record_payment already posted this payment's journal entry.
        return payment

    @staticmethod
    def record_split_payment(invoice: Invoice, tenders, received_by):
        """Record multiple tenders (a split payment) against an invoice in one call.

        tenders: [{amount, method, reference?}]. Each tender is recorded via
        record_payment, so status transitions and GL/credit wiring are identical to a
        single payment — this is the additive 'split payment' capability (cash + transfer
        + card, etc.) the POS needs, without changing the sale-posting hot path.
        """
        if not tenders:
            raise ValueError("At least one payment line is required.")
        payments = []
        for t in tenders:
            amt = Decimal(str(t.get("amount") or 0))
            if amt <= 0:
                continue
            payments.append(SaleService.record_payment(
                invoice=invoice,
                amount=amt,
                method=t.get("method", "cash"),
                reference=t.get("reference", ""),
                received_by=received_by,
            ))
        if not payments:
            raise ValueError("No valid payment lines (amounts must be greater than zero).")
        return payments

    @staticmethod
    @transaction.atomic
    def fulfill_invoice(invoice: Invoice, actor) -> Invoice:
        """
        Fulfill a deferred-fulfillment invoice: deduct stock for each line item
        and post the sale that was held back at creation time.

        Only valid for invoices created with defer_fulfillment=True that have
        not already been fulfilled. The ledger entry is dated the DELIVERY day
        (today), not the day the invoice was raised. The whole call is one
        transaction and the locked-period check runs BEFORE any stock moves, so
        a locked period fails loudly and nothing is lost.
        """
        from apps.accounting.services import AccountingService
        from . import ledger

        # Re-read with row lock to prevent concurrent double-fulfillment
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)

        if not invoice.is_deferred:
            raise ValueError("This invoice was not created with deferred fulfillment.")
        if invoice.fulfilled_at is not None:
            raise ValueError("This invoice has already been fulfilled.")
        if invoice.status in (Invoice.Status.VOIDED, Invoice.Status.PROFORMA, Invoice.Status.DRAFT):
            raise ValueError(f"A {invoice.status} invoice cannot be fulfilled.")

        delivery_date = timezone.localdate()
        AccountingService.assert_period_open(
            invoice.organisation, delivery_date, actor,
            ref=invoice.invoice_number, source=f"sale/{invoice.id}",
        )

        for item in invoice.items.select_related("product", "batch").all():
            if item.product.product_type == "service":
                continue
            if item.product.product_type == Product.ProductType.COMBO:
                cost_per_unit = InventoryService.consume_combo_components(
                    organisation=invoice.organisation,
                    combo_product=item.product,
                    warehouse=invoice.warehouse,
                    quantity=item.quantity,
                    reference=invoice.invoice_number,
                    created_by=actor,
                )
            else:
                movement = InventoryService.record_movement(
                    organisation=invoice.organisation,
                    product=item.product,
                    warehouse=invoice.warehouse,
                    quantity=-item.quantity,
                    movement_type="sale_out",
                    unit_cost=item.product.cost_price,
                    reference=invoice.invoice_number,
                    created_by=actor,
                    batch=item.batch,
                    use_costing_engine=True,
                )
                cost_per_unit = movement.unit_cost
            # Deferred fulfilment is where the stock actually leaves, so this is
            # where its real cost is known. The line was costed provisionally at
            # creation time (skip_stock=True, nothing consumed yet); restate it
            # from what the ledger consumed before the GL posts just below,
            # otherwise the journal and the stock ledger disagree.
            item.cost_of_goods = round_money(item.quantity * cost_per_unit)
            item.save(update_fields=["cost_of_goods", "updated_at"])

        # Raises on failure -- stock and journal commit together or not at all.
        SaleService._post_sale_entry(
            invoice, actor,
            mode="fulfilment" if ledger.is_new_style_deferred(invoice) else "full",
            entry_date=delivery_date,
        )

        invoice.fulfilled_at = timezone.now()
        invoice.save(update_fields=["fulfilled_at", "updated_at"])

        try:
            from apps.core.models import AuditLog
            AuditLog.log(
                action=AuditLog.UPDATE,
                user=actor,
                organisation=invoice.organisation,
                model_name='Invoice',
                object_id=str(invoice.id),
                object_repr=str(invoice),
                changes={'fulfilled_at': {'old': None, 'new': str(invoice.fulfilled_at)}},
            )
        except Exception:
            pass

        logger.info("Invoice %s fulfilled by %s", invoice.invoice_number, actor)
        return invoice

    @staticmethod
    @transaction.atomic
    def confirm_proforma(invoice: Invoice, actor, allow_unpaid_walk_in: bool = False) -> Invoice:
        """
        Turn a proforma into a real invoice, posting exactly what create_sale
        would have: stock out (unless fulfilment is deferred), the sale entry,
        and the customer's debt when a balance is left. Deposits already taken
        against the proforma are settled in that entry (VAT is never booked twice).
        """
        from apps.accounting.services import AccountingService

        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status != Invoice.Status.PROFORMA:
            raise ValueError("Only proforma invoices can be confirmed this way")

        # A walk-in has nobody to carry a balance: it must be fully paid (by deposit)
        # to be confirmed, unless a manager says otherwise with the explicit flag.
        still_owed = (invoice.total_amount - Decimal(str(invoice.credit_applied or 0))
                      - (invoice.amount_paid or Decimal("0")))
        if invoice.customer_id is None and still_owed > Decimal("0.01") and not allow_unpaid_walk_in:
            raise ValueError(
                "A walk-in sale must be paid in full. Take the payment first, pick a customer "
                "to leave a balance unpaid, or have a manager confirm it as unpaid."
            )

        # The sale happens today: stock moves and the entry is dated now, not on
        # the proforma's date. A locked period fails here, before any stock moves.
        issue_date = timezone.localdate()
        AccountingService.assert_period_open(
            invoice.organisation, issue_date, actor,
            ref=invoice.invoice_number, source=f"sale/{invoice.id}",
        )
        if not invoice.is_deferred:
            for item in invoice.items.select_related("product", "batch").all():
                if item.product.product_type == "combo":
                    cost_per_unit = InventoryService.consume_combo_components(
                        organisation=invoice.organisation,
                        combo_product=item.product,
                        warehouse=invoice.warehouse,
                        quantity=item.quantity,
                        reference=invoice.invoice_number,
                        created_by=actor,
                    )
                elif item.product.product_type != "service":
                    movement = InventoryService.record_movement(
                        organisation=invoice.organisation,
                        product=item.product,
                        warehouse=invoice.warehouse,
                        movement_type="sale_out",
                        quantity=-item.quantity,
                        unit_cost=item.cost_of_goods / item.quantity if item.quantity else item.product.cost_price,
                        reference=invoice.invoice_number,
                        created_by=actor,
                        batch=item.batch,
                        use_costing_engine=True,
                    )
                    cost_per_unit = movement.unit_cost
                else:
                    continue
                # Confirming is where a proforma's stock actually leaves, so
                # restate the provisional cost from what the ledger consumed.
                if item.quantity:
                    item.cost_of_goods = round_money(item.quantity * cost_per_unit)
                    item.save(update_fields=["cost_of_goods", "updated_at"])

        credit_used = Decimal(str(invoice.credit_applied or 0))
        owed = invoice.total_amount - credit_used - invoice.amount_paid
        if invoice.payment_method == Invoice.PaymentMethod.CREDIT:
            if invoice.customer is None:
                raise ValueError("Customer is required for credit sales.")
            invoice.status = Invoice.Status.CREDIT
        elif invoice.amount_paid + credit_used >= invoice.total_amount:
            invoice.status = Invoice.Status.PAID
        elif invoice.amount_paid > 0:
            invoice.status = Invoice.Status.PARTIALLY_PAID
        else:
            invoice.status = Invoice.Status.CONFIRMED
        invoice.amount_due = max(owed, Decimal("0"))

        if invoice.customer_id and owed > 0:
            from apps.credits.services import CreditService
            CreditService.record_credit_debit(
                organisation=invoice.organisation, customer=invoice.customer, amount=owed,
                invoice=invoice, due_date=invoice.due_date, recorded_by=actor,
                description=f"Credit sale – {invoice.invoice_number}"
                if invoice.payment_method == Invoice.PaymentMethod.CREDIT
                else f"Unpaid balance – {invoice.invoice_number}",
            )

        invoice.save(update_fields=["status", "amount_due", "updated_at"])
        SaleService._post_sale_entry(
            invoice, actor,
            mode="deferred" if invoice.is_deferred else "full", entry_date=issue_date,
        )
        return invoice

    @staticmethod
    @transaction.atomic
    def void_invoice(invoice: Invoice, voided_by) -> Invoice:
        """
        Void an invoice. Everything it did is undone together, or none of it:

        * every journal entry it owns is reversed line for line (so discount,
          VAT-inclusive prices, shipping, store credit and deposits all mirror
          exactly -- nothing is recomputed);
        * stock goes back only if stock actually left (a fulfil-later invoice
          that was never delivered, and a proforma, never moved any);
        * payments taken are paid back (negative payment rows; the receipt
          entries are reversed with the rest);
        * what the customer owed on this invoice comes off their balance, and
          store credit they used is given back.
        A paid, delivered invoice still needs a return (Process return).
        """
        from . import ledger

        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status == Invoice.Status.VOIDED:
            raise ValueError("This invoice has already been voided.")
        undelivered = bool(invoice.is_deferred) and invoice.fulfilled_at is None
        if invoice.status == Invoice.Status.PAID and not undelivered:
            raise ValueError("Paid invoices cannot be voided without a return process.")
        if SaleReturn.objects.filter(invoice=invoice).exists():
            raise ValueError("This invoice has returns against it and cannot be voided.")

        previous_status = invoice.status
        stock_left = (
            invoice.status not in (Invoice.Status.DRAFT, Invoice.Status.PROFORMA) and not undelivered
        )

        # Same lock order as create_sale: the customer row first, then stock
        if invoice.customer_id:
            from apps.customers.models import Customer as _Cust
            _Cust.objects.select_for_update().get(pk=invoice.customer_id, organisation=invoice.organisation)

        # Reverse stock deductions (skip service items) -- only if stock left
        if stock_left:
            for item in invoice.items.all():
                if item.product.product_type == "service":
                    continue
                InventoryService.record_movement(
                    organisation=invoice.organisation,
                    product=item.product,
                    warehouse=invoice.warehouse,
                    quantity=item.quantity,
                    movement_type="return_in",
                    unit_cost=item.cost_of_goods / item.quantity if item.quantity else Decimal("0"),
                    reference=f"VOID-{invoice.invoice_number}",
                    created_by=voided_by,
                )

        # Reverse every journal entry the invoice owns. Raises on failure --
        # the void then rolls back as a whole instead of committing half.
        ledger.void_invoice_entry(invoice, voided_by)
        SaleService._reverse_wht(invoice)
        SaleService._close_payment_requests(invoice)

        # Pay back what was taken.
        for p in list(invoice.payments.filter(amount__gt=0)):
            SalePayment.objects.create(
                organisation=invoice.organisation, invoice=invoice, amount=-p.amount,
                method=p.method, reference=f"VOID-{invoice.invoice_number}",
                notes=f"Refund on void of {invoice.invoice_number}", received_by=voided_by,
                till_session=SaleService._open_till_for(invoice.organisation, voided_by)
                if p.method == "cash" else None,
            )

        # The customer's own balance for this invoice goes to zero.
        if invoice.customer_id:
            owed = Decimal(str(invoice.amount_due or 0)) if SaleService._debt_on_customer_account(invoice) else Decimal("0")
            if owed > 0:
                from apps.credits.services import CreditService
                CreditService.record_payment(
                    organisation=invoice.organisation, customer=invoice.customer, amount=owed,
                    recorded_by=voided_by, description=f"Invoice voided – {invoice.invoice_number}",
                    post_gl=False,
                )
            credit_used = Decimal(str(invoice.credit_applied or 0))
            if credit_used > 0:
                from apps.customers.models import Customer as CustomerModel
                # lock, then add to the row's own value (never a Python-held copy)
                CustomerModel.objects.select_for_update().get(
                    pk=invoice.customer_id, organisation=invoice.organisation)
                CustomerModel.objects.filter(
                    pk=invoice.customer_id, organisation=invoice.organisation,
                ).update(store_credit=F("store_credit") + credit_used)

        invoice.status = Invoice.Status.VOIDED
        invoice.save(update_fields=["status", "updated_at"])

        try:
            from apps.core.models import AuditLog
            AuditLog.log(
                action=AuditLog.UPDATE, user=voided_by,
                organisation=invoice.organisation, model_name='Invoice',
                object_id=str(invoice.id), object_repr=str(invoice),
                changes={'status': {'old': previous_status, 'new': invoice.status}},
            )
        except Exception:
            pass

        return invoice

    @staticmethod
    @transaction.atomic
    def delete_invoice(invoice: Invoice, actor) -> None:
        """
        Permanently (soft-)delete an invoice, reversing its accounting and stock
        effects so nothing is left dangling.

        Caller is responsible for authorization — this method assumes the caller
        has already verified the actor is allowed to do this (owner/superuser).

        Effects, in order:
            1. Snapshot everything (for the audit log) before mutating anything.
            2. Reverse the GL journal entry, if one was posted for this invoice.
            3. Restore stock, if stock was actually deducted for this invoice.
            4. Reset the customer's outstanding balance contribution, if any.
            5. Soft-delete the Invoice + its SaleItems + its SalePayments.
            6. Write one audit log entry capturing the full snapshot.
        """
        from apps.accounting.services import AccountingService
        from apps.accounting.models import JournalEntry
        from apps.core.models import AuditLog

        if invoice.is_deleted:
            raise ValueError("This invoice has already been deleted.")

        # ── 1. Build a full json-safe snapshot BEFORE making any changes ──────
        def _jsonsafe(v):
            if isinstance(v, Decimal):
                return str(v)
            if hasattr(v, "isoformat"):
                return v.isoformat()
            if v is None:
                return None
            return str(v) if not isinstance(v, (int, float, str, bool)) else v

        items_snapshot = [
            {
                "product_id": _jsonsafe(item.product_id),
                "quantity": _jsonsafe(item.quantity),
                "unit_price": _jsonsafe(item.unit_price),
            }
            for item in invoice.items.all()
        ]
        payments_snapshot = [
            {
                "amount": _jsonsafe(p.amount),
                "method": p.method,
                "received_at": _jsonsafe(p.received_at),
            }
            for p in invoice.payments.all()
        ]
        linked_journal_entry = JournalEntry.objects.filter(
            organisation=invoice.organisation,
            source_type='sale',
            source_ref=str(invoice.id),
        ).first()

        snapshot = {
            "invoice_number": invoice.invoice_number,
            "customer_id": _jsonsafe(invoice.customer_id),
            "total_amount": _jsonsafe(invoice.total_amount),
            "amount_paid": _jsonsafe(invoice.amount_paid),
            "status": invoice.status,
            "is_deferred": invoice.is_deferred,
            "fulfilled_at": _jsonsafe(invoice.fulfilled_at),
            "items": items_snapshot,
            "payments": payments_snapshot,
            "journal_entry_id": str(linked_journal_entry.id) if linked_journal_entry else None,
            "journal_entry_reference": linked_journal_entry.reference if linked_journal_entry else None,
        }

        # Was GL actually posted for this invoice? (not deferred, not a still-open
        # proforma, and an entry actually exists for it)
        gl_was_posted = (not invoice.is_deferred) and linked_journal_entry is not None

        # Was stock actually deducted for this invoice? Mirrors void_invoice's
        # assumption (non-service items were deducted at creation/fulfillment time),
        # but excludes deferred-and-not-yet-fulfilled invoices (nothing was deducted)
        # and already-voided invoices (stock was already restored by void_invoice).
        stock_was_deducted = (
            invoice.status not in (Invoice.Status.VOIDED, Invoice.Status.DRAFT, Invoice.Status.PROFORMA)
            and (not invoice.is_deferred or invoice.fulfilled_at is not None)
        )

        # ── 2. Reverse the GL journal entry ────────────────────────────────────
        from . import ledger
        ledger.reverse_invoice_entries(invoice, actor)
        SaleService._reverse_wht(invoice)
        SaleService._close_payment_requests(invoice)

        # ── 3. Restore stock ────────────────────────────────────────────────────
        if stock_was_deducted:
            for item in invoice.items.select_related("product").all():
                if item.product.product_type == "service":
                    continue
                InventoryService.record_movement(
                    organisation=invoice.organisation,
                    product=item.product,
                    warehouse=invoice.warehouse,
                    quantity=item.quantity,  # positive = restocking
                    movement_type="return_in",
                    unit_cost=item.cost_of_goods / item.quantity if item.quantity else item.product.cost_price,
                    reference=f"DELETE-{invoice.invoice_number}",
                    created_by=actor,
                )

        # ── 4. Reset customer outstanding balance contribution ─────────────────
        if invoice.customer and invoice.status != Invoice.Status.VOIDED and SaleService._debt_on_customer_account(invoice):
            outstanding_contribution = invoice.amount_due
            if outstanding_contribution and outstanding_contribution > Decimal("0"):
                from apps.credits.services import CreditService
                CreditService.record_payment(
                    organisation=invoice.organisation,
                    customer=invoice.customer,
                    amount=outstanding_contribution,
                    recorded_by=actor,
                    description=f"Invoice deleted – {invoice.invoice_number}",
                    post_gl=False,   # the reversal above already cleared AR
                )

        # ── 5. Soft-delete everything ───────────────────────────────────────────
        for item in invoice.items.all():
            item.delete()
        for payment in invoice.payments.all():
            payment.delete()
        invoice.delete()

        # ── 6. Audit log ─────────────────────────────────────────────────────────
        try:
            AuditLog.log(
                action=AuditLog.DELETE,
                user=actor,
                organisation=invoice.organisation,
                model_name='Invoice',
                object_id=str(invoice.id),
                object_repr=invoice.invoice_number,
                changes=snapshot,
            )
        except Exception:
            pass

        logger.info("Invoice %s deleted by %s for org %s", invoice.invoice_number, actor, invoice.organisation.id)

    @staticmethod
    def _refund_payout(invoice, total_refund, refund_method):
        """(amount paid out, tender) for a return. Never more than what the
        customer actually paid on this invoice and has not already had back."""
        original = invoice.payment_method
        if refund_method not in ("cash", "bank", "account"):
            refund_method = "account" if original == Invoice.PaymentMethod.CREDIT else (
                "cash" if original == Invoice.PaymentMethod.CASH else "bank")
        if refund_method == "account" and not invoice.customer_id and original != Invoice.PaymentMethod.CREDIT:
            # A walk-in has no account to credit: pay back the way they paid.
            refund_method = "cash" if original == Invoice.PaymentMethod.CASH else "bank"
        if refund_method == "account":
            return Decimal("0"), None
        refunded = -(invoice.payments.filter(amount__lt=0).aggregate(t=Sum("amount"))["t"] or Decimal("0"))
        paid_net = max(Decimal(str(invoice.amount_paid or 0)) - Decimal(str(refunded)), Decimal("0"))
        return min(Decimal(str(total_refund)), paid_net), ("cash" if refund_method == "cash" else "bank_transfer")

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
        refund_method: str = None,
    ) -> SaleReturn:
        """
        Process a sales return / credit note.

        Args:
            items: List of {sale_item_id, quantity_returned}
            refund_method: "cash" (paid out of the till), "bank" (transfer back),
                or "account" (off what the customer owes). Defaults to how the
                invoice was originally paid. A cash/bank refund pays out at most
                what was actually paid; any rest reduces what is owed.
        """
        from django.utils import timezone as tz

        # lock + re-read so a void or another return that just happened is seen
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk, organisation=organisation)
        if invoice.status in (
            Invoice.Status.VOIDED, Invoice.Status.DRAFT, Invoice.Status.PROFORMA, Invoice.Status.RETURNED,
        ):
            raise ValueError(f"A {invoice.get_status_display().lower()} invoice cannot have a return.")
        if invoice.is_deferred and invoice.fulfilled_at is None:
            raise ValueError(
                "This invoice has not been delivered yet, so there is nothing to return. "
                "Void it instead; any payment taken is refunded."
            )
        return_date = return_date or tz.localdate()

        total_refund = Decimal("0")
        total_tax_refund = Decimal("0")
        total_cogs_refund = Decimal("0")
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

            # Proportional refund (VAT-inclusive) based on remaining line value
            remaining_line_value = sale_item.line_total * remaining_returnable / sale_item.quantity
            refund = round_money(remaining_line_value * qty / remaining_returnable)

            # Split out the VAT portion to reverse output VAT in the GL and VAT report
            if sale_item.line_total > 0:
                tax_ratio = (sale_item.tax_amount or Decimal("0")) / sale_item.line_total
            else:
                tax_ratio = Decimal("0")
            tax_refund = round_money(refund * tax_ratio)

            total_refund += refund
            total_tax_refund += tax_refund
            return_items_to_create.append((sale_item, qty, refund, tax_refund))

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

        for sale_item, qty, refund, tax_refund in return_items_to_create:
            SaleReturnItem.objects.create(
                organisation=organisation,
                sale_return=sale_return,
                original_item=sale_item,
                product=sale_item.product,
                quantity_returned=qty,
                unit_price=sale_item.unit_price,
                refund_amount=refund,
                tax_refund=tax_refund,
            )
            SaleItem.objects.filter(pk=sale_item.pk).update(
                quantity_returned=sale_item.quantity_returned + qty
            )
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
                total_cogs_refund += round_money(unit_cost * qty)

        # fresh rows, not invoice.items: the view prefetches the lines, and that cached copy
        # still shows quantity_returned as it was BEFORE this return, so a full return never
        # flipped the invoice to 'returned'
        all_items = list(SaleItem.objects.filter(invoice=invoice))
        total_sold     = sum(Decimal(str(i.quantity))           for i in all_items)
        total_returned = sum(Decimal(str(i.quantity_returned or 0)) for i in all_items)
        if total_sold > 0 and total_returned >= total_sold:
            Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.Status.RETURNED)

        # How the customer is made whole. Every return used to credit Accounts
        # Receivable, even for a walk-in cash sale: an AR credit with no customer
        # behind it, Cash in the ledger above the drawer, and the till reading a
        # shortage equal to the refund.
        payout, payout_tender = SaleService._refund_payout(invoice, total_refund, refund_method)
        ar_part = total_refund - payout
        if payout > 0:
            from apps.sales.models import SalePayment
            SalePayment.objects.create(
                organisation=organisation, invoice=invoice, amount=-payout, method=payout_tender,
                reference=sale_return.return_number, notes=f"Refund for {sale_return.return_number}",
                received_by=processed_by,
                till_session=SaleService._open_till_for(organisation, processed_by) if payout_tender == "cash" else None,
            )

        # Update the customer's own balance whenever money is kept "on account"
        # rather than paid out -- not just for an originally-credit sale. A cash
        # or bank-paid invoice refunded to account leaves the customer in credit
        # (CreditService.record_payment already supports going negative, M5): the
        # GL's AR line and the customer's CreditTransaction ledger must move
        # together, or the customer's own balance never reflects money the
        # business now owes them back, even though the books show it.
        if ar_part > 0 and invoice.customer:
            from apps.credits.services import CreditService
            CreditService.record_payment(
                organisation=organisation,
                customer=invoice.customer,
                amount=ar_part,
                recorded_by=processed_by,
                description=f"Sales return – {sale_return.return_number}",
                post_gl=False,   # the return's own journal below credits AR
            )

        # Post reversing GL journal: DR Revenue (net), DR VAT Payable, CR AR/Cash
        try:
            from apps.accounting.services import AccountingService, AccountMappingService
            zero = Decimal("0")
            net_refund = total_refund - total_tax_refund
            revenue_acct = AccountMappingService.resolve(organisation, 'revenue_account')
            vat_acct     = AccountMappingService.resolve(organisation, 'vat_output_account')
            ar_acct      = AccountingService._resolve_party_account(
                organisation, invoice.customer, 'receivable_account', 'accounts_receivable', '1100')
            lines = [
                (revenue_acct, net_refund,       zero),           # DR Revenue (reversal)
                (vat_acct,     total_tax_refund,  zero),          # DR VAT Payable (reversal)
            ]
            if ar_part > zero:
                lines.append((ar_acct, zero, ar_part))            # CR AR / customer
            if payout > zero:                                     # CR Cash / Bank actually paid out
                lines.append((AccountingService.tender_asset_account(organisation, payout_tender), zero, payout))
            # Reverse COGS/Inventory for the restocked portion, so the GL Inventory
            # balance stays in step with the physical stock InventoryService already restored
            if total_cogs_refund > zero:
                cogs_acct = AccountMappingService.resolve(organisation, 'cogs_account')
                inv_acct  = AccountMappingService.resolve(organisation, 'inventory_account')
                lines.append((inv_acct,  total_cogs_refund, zero))  # DR Inventory (restore)
                lines.append((cogs_acct, zero,              total_cogs_refund))  # CR COGS (reverse)
            AccountingService.post_journal_entry(
                organisation,
                f"Credit note {sale_return.return_number}",
                return_date,
                lines,
                processed_by,
                ref=sale_return.return_number,
                source_type='sale_return',
                source_ref=str(sale_return.id),
            )
        except Exception as exc:
            # Previously swallowed: the return record, restocked stock and any
            # refund payout would commit while the GL silently never recorded
            # the credit note, with nothing to tell the user. process_return
            # runs inside @transaction.atomic, so letting this propagate rolls
            # the whole return back together — it either all commits or none
            # of it does, and the caller sees why.
            logger.error("Credit note GL journal failed for %s: %s", sale_return.return_number, exc)
            raise

        logger.info(
            "Return %s processed for invoice %s — refund %s (VAT %s)",
            sale_return.return_number, invoice.invoice_number, total_refund, total_tax_refund,
        )
        return sale_return
