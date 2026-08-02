"""Hospitality POS order service."""
import logging
from decimal import Decimal

from django.db import transaction

from .models import POSOrder, POSOrderItem, KitchenOrderTicket, RestaurantTable

logger = logging.getLogger(__name__)
ZERO = Decimal("0")


class POSOrderService:

    @staticmethod
    def _default_warehouse(organisation):
        from apps.inventory.models import Warehouse
        return (Warehouse.objects.filter(organisation=organisation, is_default=True).first()
                or Warehouse.objects.filter(organisation=organisation, is_active=True).first()
                or Warehouse.objects.filter(organisation=organisation).first())

    @staticmethod
    @transaction.atomic
    def create_order(organisation, created_by, order_type="dine_in", items=None, table_id=None,
                     waiter_id=None, customer_id=None, room_number="", notes="",
                     service_charge=ZERO, tip_amount=ZERO, warehouse_id=None):
        from apps.inventory.models import Product, Warehouse

        table = RestaurantTable.objects.filter(organisation=organisation, id=table_id).first() if table_id else None
        warehouse = None
        if warehouse_id:
            warehouse = Warehouse.objects.filter(organisation=organisation, id=warehouse_id).first()
        warehouse = warehouse or POSOrderService._default_warehouse(organisation)

        order = POSOrder.objects.create(
            organisation=organisation,
            order_number=POSOrder.generate_number(organisation),
            order_type=order_type,
            table=table,
            room_number=room_number or "",
            waiter_id=waiter_id or None,
            customer_id=customer_id or None,
            notes=notes or "",
            service_charge=Decimal(str(service_charge or 0)),
            tip_amount=Decimal(str(tip_amount or 0)),
            warehouse=warehouse,
            created_by=created_by,
        )
        from apps.inventory.modifier_services import ModifierService
        for it in (items or []):
            product = Product.objects.get(id=it["product_id"], organisation=organisation)
            qty = Decimal(str(it.get("quantity") or 1))
            base = Decimal(str(
                it.get("unit_price") if it.get("unit_price") is not None else product.selling_price
            ))
            # Modifier prices are resolved here, never taken from the caller —
            # otherwise "extra chicken" could be sent through as free.
            unit_price, modifiers = ModifierService.unit_price(
                product, it.get("modifiers") or it.get("modifier_options"), base_price=base,
            )
            POSOrderItem.objects.create(
                organisation=organisation, order=order, product=product,
                quantity=qty, unit_price=unit_price, notes=it.get("notes", ""),
                modifiers=modifiers,
            )
        if table:
            table.status = RestaurantTable.Status.OCCUPIED
            table.save(update_fields=["status", "updated_at"])
        return order

    @staticmethod
    @transaction.atomic
    def add_items(organisation, order, items):
        from apps.inventory.models import Product
        if order.status in (POSOrder.Status.COMPLETED, POSOrder.Status.CANCELLED):
            raise ValueError("Cannot add items to a completed or cancelled order.")
        for it in items:
            product = Product.objects.get(id=it["product_id"], organisation=organisation)
            qty = Decimal(str(it.get("quantity") or 1))
            unit_price = Decimal(str(it.get("unit_price") if it.get("unit_price") is not None else product.selling_price))
            POSOrderItem.objects.create(
                organisation=organisation, order=order, product=product,
                quantity=qty, unit_price=unit_price, notes=it.get("notes", ""),
            )
        return order

    @staticmethod
    def set_status(order, status):
        valid = [s[0] for s in POSOrder.Status.choices]
        if status not in valid:
            raise ValueError("Invalid order status.")
        order.status = status
        order.save(update_fields=["status", "updated_at"])
        if status in (POSOrder.Status.COMPLETED, POSOrder.Status.CANCELLED) and order.table:
            order.table.status = RestaurantTable.Status.AVAILABLE
            order.table.save(update_fields=["status", "updated_at"])
        return order

    @staticmethod
    @transaction.atomic
    def generate_kot(organisation, order, section=""):
        """Create a Kitchen Order Ticket for the order (send-to-kitchen)."""
        from django.db.models import Max
        import re
        prefix = str(organisation.id).replace("-", "")[:4].upper()
        pat = f"KOT-{prefix}-"
        last = KitchenOrderTicket.objects.filter(
            organisation=organisation, kot_number__startswith=pat).aggregate(m=Max("kot_number"))["m"]
        seq = 1
        if last:
            m = re.search(r"-(\d+)$", last)
            seq = (int(m.group(1)) + 1) if m else 1
        kot = KitchenOrderTicket.objects.create(
            organisation=organisation, order=order, kot_number=f"{pat}{seq:05d}", section=section or "")
        if order.status == POSOrder.Status.OPEN:
            order.status = POSOrder.Status.PREPARING
            order.save(update_fields=["status", "updated_at"])
        return kot

    @staticmethod
    def split_bill(order, mode="equal", n=2, splits=None):
        """Compute a bill split. Returns a list of amounts (does not post anything).
        mode: 'equal' (n ways), 'custom' (explicit amounts), 'by_items' (list of item-id groups)."""
        total = Decimal(str(order.items_subtotal)) + Decimal(str(order.service_charge or 0)) + Decimal(str(order.tip_amount or 0))
        if mode == "equal":
            n = max(1, int(n or 2))
            base = (total / n).quantize(Decimal("0.01"))
            parts = [base] * n
            parts[-1] = total - base * (n - 1)   # absorb rounding on the last split
            return {"mode": mode, "total": total, "splits": [{"amount": p} for p in parts]}
        if mode == "custom":
            amounts = [Decimal(str(s.get("amount") or 0)) for s in (splits or [])]
            return {"mode": mode, "total": total, "splits": [{"amount": a} for a in amounts],
                    "balanced": abs(sum(amounts, ZERO) - total) < Decimal("0.01")}
        if mode == "by_items":
            item_map = {str(i.id): i for i in order.items.all()}
            groups = []
            for grp in (splits or []):
                amt = sum((item_map[str(iid)].line_total for iid in grp.get("item_ids", []) if str(iid) in item_map), ZERO)
                groups.append({"amount": amt, "item_ids": grp.get("item_ids", [])})
            return {"mode": mode, "total": total, "splits": groups}
        raise ValueError("Invalid split mode.")

    # tender method → invoice payment method
    _METHOD_MAP = {
        "cash": "cash", "transfer": "bank_transfer", "bank": "bank_transfer",
        "bank_transfer": "bank_transfer", "card": "pos", "pos": "pos",
        "credit": "credit", "cheque": "bank_transfer",
    }

    @staticmethod
    @transaction.atomic
    def finalize_order(organisation, order, tenders=None, created_by=None):
        """Finalise: create a fully-paid Invoice from the order items (standard sale →
        GL/inventory/receipt via the existing engine), post service-charge/tip, and close
        the order + free the table. Multiple tenders are summed; the sale posts a single
        receipt to the primary tender's cash/bank account (correct + always balanced —
        credit isn't used because walk-in orders have no customer)."""
        from apps.sales.services import SaleService, SalePayment
        from apps.accounting.services import AccountingService, AccountMappingService, safe_post_gl

        if order.status == POSOrder.Status.COMPLETED:
            raise ValueError("Order is already completed.")
        order_items = list(order.items.all())
        if not order_items:
            raise ValueError("Cannot finalise an empty order.")

        warehouse = order.warehouse or POSOrderService._default_warehouse(organisation)
        if warehouse is None:
            raise ValueError("No warehouse available to fulfil this order.")

        sale_items = [{
            "product_id": str(i.product_id),
            "quantity": i.quantity,
            "unit_price": str(i.unit_price),
        } for i in order_items]

        # Create the sale UNPAID so the sale journal posts DR Accounts Receivable →
        # CR Revenue + VAT (post_sale_journal debits AR when there is no payment). The
        # receipt is then posted separately, splitting the debit across each tender's own
        # cash/bank account — true per-tender GL, always balanced, AR fully relieved.
        invoice = SaleService.create_sale(
            organisation=organisation,
            created_by=created_by,
            customer=order.customer,
            warehouse=warehouse,
            items=sale_items,
            payment_method="cash",   # label only — amount_paid=0 records no payment
            amount_paid=ZERO,
            notes=f"POS order {order.order_number}",
        )

        total_due = Decimal(str(invoice.total_amount))
        # Default to a single cash tender for the full amount when none supplied.
        if not tenders:
            tenders = [{"method": "cash", "amount": str(total_due)}]

        POSOrderService._settle_invoice(organisation, invoice, tenders, order, created_by)

        # Service charge (income) + tip (liability owed to staff), posted only if present.
        svc = Decimal(str(order.service_charge or 0))
        tip = Decimal(str(order.tip_amount or 0))
        if svc > 0 or tip > 0:
            def _post_extras():
                cash = AccountMappingService.resolve(organisation, "cash_account")
                lines = [(cash, svc + tip, ZERO)]
                if svc > 0:
                    revenue = AccountMappingService.resolve(organisation, "revenue_account")
                    lines.append((revenue, ZERO, svc))
                if tip > 0:
                    tips_payable = POSOrderService._tips_payable_account(organisation)
                    lines.append((tips_payable, ZERO, tip))
                AccountingService.post_journal_entry(
                    organisation, f"POS service/tip {order.order_number}", invoice.issue_date,
                    lines, created_by, ref=order.order_number,
                    source_type="pos_service_tip", source_ref=str(order.id))
            safe_post_gl(_post_extras)

        order.invoice = invoice
        order.save(update_fields=["invoice", "updated_at"])
        POSOrderService.set_status(order, POSOrder.Status.COMPLETED)
        return {"order": order, "invoice": invoice}

    @staticmethod
    def _settle_invoice(organisation, invoice, tenders, order, created_by):
        """Post a per-tender receipt — DR each tender's own cash/bank account, CR AR —
        and record the payments, relieving AR exactly (change on overpayment is not
        posted). Always balanced: Σ tender debits == AR credit == amount applied."""
        from apps.sales.models import SalePayment, Invoice as _Invoice
        from apps.accounting.services import AccountingService, AccountMappingService, safe_post_gl

        total_due = Decimal(str(invoice.total_amount))
        total_tendered = sum((Decimal(str(t.get("amount") or 0)) for t in tenders), ZERO)
        applied = min(total_tendered, total_due)
        if applied <= 0:
            return

        ar = AccountMappingService.resolve(organisation, "accounts_receivable")
        cash = AccountMappingService.resolve(organisation, "cash_account")
        bank = AccountMappingService.resolve(organisation, "bank_account")

        remaining = applied
        receipt_lines = []
        payment_rows = []
        for t in tenders:
            if remaining <= 0:
                break
            amt = min(Decimal(str(t.get("amount") or 0)), remaining)
            if amt <= 0:
                continue
            inv_method = POSOrderService._METHOD_MAP.get(t.get("method", "cash"), "cash")
            acct = cash if inv_method == "cash" else bank
            receipt_lines.append((acct, amt, ZERO))          # DR this tender's cash/bank
            payment_rows.append((t.get("method", "cash"), inv_method, amt))
            remaining -= amt
        receipt_lines.append((ar, ZERO, applied))            # CR Accounts Receivable

        def _post_receipt():
            AccountingService.post_journal_entry(
                organisation, f"POS receipt {order.order_number}", invoice.issue_date,
                receipt_lines, created_by, ref=order.order_number,
                source_type="pos_receipt", source_ref=str(order.id))
        safe_post_gl(_post_receipt)

        for (method, inv_method, amt) in payment_rows:
            SalePayment.objects.create(
                organisation=organisation, invoice=invoice, amount=amt,
                method=inv_method, reference=f"POS {method}", received_by=created_by)
        invoice.amount_paid = applied
        invoice.amount_due = total_due - applied
        invoice.status = _Invoice.Status.PAID if applied >= total_due else _Invoice.Status.PARTIALLY_PAID
        invoice.save(update_fields=["amount_paid", "amount_due", "status"])

    @staticmethod
    def _tips_payable_account(organisation):
        """Get or create the Tips Payable (2900) liability account."""
        from apps.accounting.models import Account, AccountType, normal_balance_for_type
        acct = Account.objects.filter(organisation=organisation, code="2900").first()
        if acct:
            return acct
        return Account.objects.create(
            organisation=organisation, code="2900", name="Tips Payable",
            account_type=AccountType.LIABILITY, account_group="Liability",
            normal_balance=normal_balance_for_type(AccountType.LIABILITY), is_system=True)
