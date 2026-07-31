"""Unified report engine.

A single registry maps a report *key* to a resolver function and its display
metadata, so every report shares one dispatch path (JSON + CSV/Excel export) and
the frontend can render one consistent reports menu. New reports are added as a
thin resolver + one register() call rather than a bespoke view + url each.

Resolvers have the signature:
    resolver(organisation, date_from, date_to, **params) -> dict
and return a JSON-serialisable dict.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable, Optional


@dataclass(frozen=True)
class ReportDef:
    key: str
    label: str
    category: str
    resolver: Callable
    description: str = ""
    needs_period: bool = True


_REGISTRY: "dict[str, ReportDef]" = {}


def register(rd: ReportDef) -> None:
    _REGISTRY[rd.key] = rd


def get(key: str) -> Optional[ReportDef]:
    return _REGISTRY.get(key)


def catalog() -> list:
    """Ordered list of report metadata for building the reports menu."""
    return [
        {
            "key": rd.key,
            "label": rd.label,
            "category": rd.category,
            "description": rd.description,
            "needs_period": rd.needs_period,
        }
        for rd in _REGISTRY.values()
    ]


# ── Auditor / GL-derived resolvers ───────────────────────────────────────────

def _zero() -> Decimal:
    return Decimal("0")


def gl_detail(organisation, date_from: date, date_to: date, account_id=None, account_code=None, **_):
    """General Ledger detail with a running balance per account.

    Opening balance = posted movement strictly before date_from; then every posted
    line within the range, each carrying the running balance; closing balance at the end.
    Filter to a single account by `account_id` or `account_code` (used by drill-down).
    """
    from apps.accounting.models import Account, JournalLine
    from apps.accounting.services import AccountingService

    accounts = Account.objects.filter(organisation=organisation, is_active=True)
    if account_id:
        accounts = accounts.filter(id=account_id)
    if account_code:
        accounts = accounts.filter(code=account_code)
    accounts = accounts.order_by("code")

    day_before = date_from - timedelta(days=1) if date_from else None
    sections = []
    for acct in accounts:
        opening = (
            AccountingService._ledger_balance(acct, as_of=day_before)
            if day_before else _zero()
        )
        lines_qs = JournalLine.objects.filter(
            account=acct,
            journal_entry__organisation=organisation,
            journal_entry__status="posted",
        ).select_related("journal_entry")
        if date_from:
            lines_qs = lines_qs.filter(journal_entry__entry_date__gte=date_from)
        if date_to:
            lines_qs = lines_qs.filter(journal_entry__entry_date__lte=date_to)
        lines_qs = lines_qs.order_by("journal_entry__entry_date", "journal_entry__reference", "id")

        debit_normal = acct.effective_normal_balance == "debit"
        running = opening
        rows = []
        for ln in lines_qs:
            d = Decimal(str(ln.debit or 0))
            c = Decimal(str(ln.credit or 0))
            running += (d - c) if debit_normal else (c - d)
            je = ln.journal_entry
            rows.append({
                "date": str(je.entry_date),
                "reference": je.reference,
                "description": ln.description or je.description,
                "debit": d,
                "credit": c,
                "balance": running,
                # Drill-down: link a ledger line back to the document that created it.
                "journal_entry_id": str(je.id),
                "source_type": je.source_type or "",
                "source_ref": je.source_ref or "",
            })
        if not rows and opening == 0:
            continue  # skip dormant accounts
        sections.append({
            "account_code": acct.code,
            "account_name": acct.name,
            "opening_balance": opening,
            "lines": rows,
            "closing_balance": running,
        })
    return {"period_start": str(date_from), "period_end": str(date_to), "accounts": sections}


def journal_register(organisation, date_from: date, date_to: date, **_):
    """Every posted journal entry in the period, with its lines and totals."""
    from apps.accounting.models import JournalEntry

    qs = JournalEntry.objects.filter(
        organisation=organisation, status="posted"
    ).prefetch_related("lines__account")
    if date_from:
        qs = qs.filter(entry_date__gte=date_from)
    if date_to:
        qs = qs.filter(entry_date__lte=date_to)
    qs = qs.order_by("entry_date", "reference")

    entries = []
    total_debit = _zero()
    total_credit = _zero()
    for je in qs:
        lines = []
        for ln in je.lines.all():
            d = Decimal(str(ln.debit or 0))
            c = Decimal(str(ln.credit or 0))
            total_debit += d
            total_credit += c
            lines.append({
                "account_code": ln.account.code if ln.account else "",
                "account_name": ln.account.name if ln.account else "",
                "debit": d, "credit": c,
                "description": ln.description,
            })
        entries.append({
            "date": str(je.entry_date),
            "reference": je.reference,
            "description": je.description,
            "source_type": je.source_type or "",
            "lines": lines,
        })
    return {
        "period_start": str(date_from), "period_end": str(date_to),
        "entries": entries,
        "total_debit": total_debit, "total_credit": total_credit,
    }


def statement_of_changes_in_equity(organisation, date_from: date, date_to: date, **_):
    """Statement of Changes in Equity (IFRS for SMEs §6).

    For each equity account: opening balance (before the period), movement during the
    period, and closing balance. Current-period profit not yet closed to retained
    earnings is shown as a separate movement so the statement ties to the balance sheet.
    """
    from apps.accounting.models import Account, AccountType
    from apps.accounting.services import AccountingService

    day_before = date_from - timedelta(days=1) if date_from else None
    equity_accounts = Account.objects.filter(
        organisation=organisation, is_active=True, account_type=AccountType.EQUITY,
    ).order_by("code")

    rows = []
    total_open = total_move = total_close = _zero()
    for acct in equity_accounts:
        opening = AccountingService._ledger_balance(acct, as_of=day_before) if day_before else _zero()
        closing = AccountingService._ledger_balance(acct, as_of=date_to) if date_to else _zero()
        movement = closing - opening
        if opening == 0 and closing == 0 and movement == 0:
            continue
        rows.append({
            "account_code": acct.code, "account_name": acct.name,
            "opening": opening, "movement": movement, "closing": closing,
        })
        total_open += opening
        total_move += movement
        total_close += closing

    # Unclosed current-period profit (revenue − expenses/COGS over the period) is a
    # movement in equity not yet reflected in a 3xxx account.
    zero = _zero()
    inc = exp = zero
    for acct in Account.objects.filter(organisation=organisation, is_active=True):
        if acct.account_type == AccountType.REVENUE:
            inc += AccountingService._ledger_balance(acct, as_of=date_to) - (
                AccountingService._ledger_balance(acct, as_of=day_before) if day_before else zero)
        elif acct.account_type in (AccountType.EXPENSE, AccountType.COST_OF_GOODS):
            exp += AccountingService._ledger_balance(acct, as_of=date_to) - (
                AccountingService._ledger_balance(acct, as_of=day_before) if day_before else zero)
    unclosed_profit = inc - exp
    if unclosed_profit != 0:
        rows.append({
            "account_code": "", "account_name": "Profit for the period (unclosed)",
            "opening": zero, "movement": unclosed_profit, "closing": unclosed_profit,
            "is_computed": True,
        })
        total_move += unclosed_profit
        total_close += unclosed_profit

    return {
        "period_start": str(date_from), "period_end": str(date_to),
        "rows": rows,
        "total_opening": total_open, "total_movement": total_move, "total_closing": total_close,
    }


def notes_shell(organisation, date_from: date, date_to: date, **_):
    """A scaffold of the standard IFRS-for-SMEs note sections, pre-filled where the
    figure is trivially derivable. Intended as a starting point for the accountant."""
    return {
        "period_start": str(date_from), "period_end": str(date_to),
        "notes": [
            {"number": 1, "title": "General information", "body": organisation.name},
            {"number": 2, "title": "Basis of preparation",
             "body": "Prepared under IFRS for SMEs on the historical cost basis."},
            {"number": 3, "title": "Significant accounting policies", "body": ""},
            {"number": 4, "title": "Property, plant and equipment", "body": "See Fixed Asset Movement schedule."},
            {"number": 5, "title": "Trade and other receivables", "body": "See Aged Receivables."},
            {"number": 6, "title": "Trade and other payables", "body": "See Aged Payables."},
            {"number": 7, "title": "Inventories", "body": "See Stock Valuation."},
            {"number": 8, "title": "Revenue", "body": ""},
            {"number": 9, "title": "Taxation", "body": "See VAT Return / Tax Summary."},
            {"number": 10, "title": "Events after the reporting period", "body": ""},
        ],
    }


def purchase_returns(organisation, date_from: date, date_to: date, **_):
    """Supplier purchase returns (debit notes) in the period."""
    from apps.purchases.models import PurchaseReturn
    qs = PurchaseReturn.objects.filter(organisation=organisation).select_related("supplier")
    if date_from:
        qs = qs.filter(return_date__gte=date_from)
    if date_to:
        qs = qs.filter(return_date__lte=date_to)
    qs = qs.order_by("return_date", "return_number")
    rows = []
    total = _zero()
    for r in qs:
        total += Decimal(str(r.total_amount or 0))
        rows.append({
            "return_number": r.return_number,
            "date": str(r.return_date),
            "supplier": r.supplier.name if r.supplier else "",
            "refund_method": r.refund_method,
            "subtotal": r.subtotal, "tax": r.tax_amount, "total": r.total_amount,
        })
    return {"period_start": str(date_from), "period_end": str(date_to),
            "rows": rows, "total": total}


def vat_return(organisation, date_from: date, date_to: date, **_):
    """VAT Return / Liability — output VAT less input VAT for the period.
    (Reframes the ambiguous 'Net Tax Report'.)"""
    from .services import ReportService
    return ReportService.vat_summary(organisation, date_from, date_to)


def customer_receipts(organisation, date_from: date, date_to: date, customer_id=None, **_):
    """Customer Receipts — money received from customers in the period.
    (Half of the old ambiguous 'Payments' report.)

    Org-wide by default; pass ?customer_id= to scope to one customer.
    """
    from apps.sales.models import SalePayment

    qs = SalePayment.objects.filter(organisation=organisation).select_related(
        "invoice", "invoice__customer")
    if customer_id:
        qs = qs.filter(invoice__customer__id=customer_id)
    if date_from:
        qs = qs.filter(received_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(received_at__date__lte=date_to)

    rows = []
    total = _zero()
    for p in qs.order_by("received_at"):
        total += Decimal(str(p.amount or 0))
        rows.append({
            "date": str(p.received_at.date()),
            "customer": (p.invoice.customer.name
                         if p.invoice and p.invoice.customer else "Walk-in"),
            "invoice_number": p.invoice.invoice_number if p.invoice else "",
            "method": p.method, "reference": p.reference,
            "amount": p.amount,
        })
    return {"period_start": str(date_from), "period_end": str(date_to),
            "rows": rows, "total": total}


def financial_report_pack(organisation, date_from: date, date_to: date, **_):
    """Single-entity Financial Report Pack (P&L + Balance Sheet + Trial Balance).
    This is the reframed 'Consolidated Reports' — a single-entity pack, NOT true
    multi-entity consolidation."""
    from .services import ReportService
    from apps.accounting.services import AccountingService
    return {
        "period_start": str(date_from), "period_end": str(date_to),
        "profit_and_loss": ReportService.profit_and_loss(organisation, date_from, date_to),
        "balance_sheet": AccountingService.balance_sheet(organisation, as_of=date_to),
        "trial_balance": AccountingService.trial_balance(organisation, as_of=date_to),
    }


# ── Financial-statement wrappers ─────────────────────────────────────────────

def profit_and_loss_report(organisation, date_from: date, date_to: date, **_):
    from .services import ReportService
    return ReportService.profit_and_loss(organisation, date_from, date_to)


def cash_flow_report(organisation, date_from: date, date_to: date, **_):
    from .services import ReportService
    return ReportService.cash_flow(organisation, date_from, date_to)


def balance_sheet_report(organisation, date_from: date, date_to: date, **_):
    from apps.accounting.services import AccountingService
    return AccountingService.balance_sheet(organisation, as_of=date_to)


def trial_balance_report(organisation, date_from: date, date_to: date, **_):
    from apps.accounting.services import AccountingService
    return AccountingService.trial_balance(organisation, as_of=date_to)


def tax_summary_report(organisation, date_from: date, date_to: date, **_):
    """All tax positions for the period in one view: VAT (output − input),
    WHT withheld, and PAYE from payroll runs."""
    from django.db.models import Sum
    from apps.payroll.models import PayrollRun
    from apps.tax.models import WHTTransaction
    from .services import ReportService

    vat = ReportService.vat_summary(organisation, date_from, date_to)

    wht_qs = WHTTransaction.objects.filter(organisation=organisation)
    if date_from:
        wht_qs = wht_qs.filter(transaction_date__gte=date_from)
    if date_to:
        wht_qs = wht_qs.filter(transaction_date__lte=date_to)
    wht_total = wht_qs.aggregate(t=Sum("wht_amount"))["t"] or _zero()

    pay_qs = PayrollRun.objects.filter(
        organisation=organisation, status__in=["approved", "paid"])
    if date_from:
        pay_qs = pay_qs.filter(
            period_year__gte=date_from.year).exclude(
            period_year=date_from.year, period_month__lt=date_from.month)
    if date_to:
        pay_qs = pay_qs.filter(
            period_year__lte=date_to.year).exclude(
            period_year=date_to.year, period_month__gt=date_to.month)
    paye_total = pay_qs.aggregate(t=Sum("total_paye"))["t"] or _zero()

    return {
        "period_start": str(date_from), "period_end": str(date_to),
        "vat": vat,
        "wht_withheld": wht_total,
        "paye_payable": paye_total,
    }


# ── General-ledger reports ───────────────────────────────────────────────────

def account_list(organisation, date_from: date, date_to: date, **_):
    """Chart of accounts with current ledger balances.

    Balances are aggregated in ONE grouped query rather than one per account —
    a per-account `_ledger_balance()` call made this O(number of accounts).
    Sign convention matches `_ledger_balance` / the trial balance exactly.
    """
    from django.db.models import Sum
    from apps.accounting.models import Account, AccountType, JournalLine

    lines = JournalLine.objects.filter(
        journal_entry__organisation=organisation,
        journal_entry__status="posted",
    )
    if date_to:
        lines = lines.filter(journal_entry__entry_date__lte=date_to)
    totals = {
        row["account"]: (row["d"] or _zero(), row["c"] or _zero())
        for row in lines.values("account").annotate(d=Sum("debit"), c=Sum("credit"))
    }

    debit_normal = (AccountType.ASSET, AccountType.EXPENSE, AccountType.COST_OF_GOODS)
    rows = []
    for acct in Account.objects.filter(
            organisation=organisation, is_active=True
    ).select_related("sub_type").order_by("code"):
        debits, credits = totals.get(acct.id, (_zero(), _zero()))
        balance = (debits - credits) if acct.account_type in debit_normal else (credits - debits)
        rows.append({
            "code": acct.code, "name": acct.name,
            "type": acct.account_type,
            "sub_type": acct.sub_type.name if acct.sub_type else "",
            "balance": balance,
        })
    return {"as_of": str(date_to), "rows": rows}


def cash_register(organisation, date_from: date, date_to: date, account_id=None, **_):
    """Register (running-balance detail) of cash & bank accounts only."""
    from django.db.models import Q
    from apps.accounting.models import Account, AccountType

    cashish = Account.objects.filter(
        organisation=organisation, is_active=True, account_type=AccountType.ASSET,
    ).filter(Q(name__icontains="cash") | Q(name__icontains="bank"))
    if account_id:
        return gl_detail(organisation, date_from, date_to, account_id=account_id)
    result = {"period_start": str(date_from), "period_end": str(date_to), "accounts": []}
    for acct in cashish.order_by("code"):
        part = gl_detail(organisation, date_from, date_to, account_id=acct.id)
        result["accounts"].extend(part["accounts"])
    return result


def pay_bills_report(organisation, date_from: date, date_to: date, **_):
    """Supplier bill payments made in the period."""
    from apps.bills.models import BillPayment

    qs = BillPayment.objects.filter(organisation=organisation).select_related(
        "bill", "bill__supplier")
    if date_from:
        qs = qs.filter(payment_date__gte=date_from)
    if date_to:
        qs = qs.filter(payment_date__lte=date_to)
    rows = []
    total = _zero()
    for p in qs.order_by("payment_date"):
        total += Decimal(str(p.amount or 0))
        rows.append({
            "date": str(p.payment_date),
            "bill_number": p.bill.bill_number if p.bill else "",
            "supplier": p.bill.supplier.name if p.bill and p.bill.supplier else "",
            "method": p.method, "reference": p.reference,
            "amount": p.amount,
        })
    return {"period_start": str(date_from), "period_end": str(date_to),
            "rows": rows, "total": total}


def deposit_report(organisation, date_from: date, date_to: date, **_):
    """Money received in the period: customer receipts + miscellaneous income."""
    from apps.expenses.models import Expense
    from apps.sales.models import SalePayment

    rows = []
    total = _zero()

    pay_qs = SalePayment.objects.filter(organisation=organisation).select_related(
        "invoice", "invoice__customer")
    if date_from:
        pay_qs = pay_qs.filter(received_at__date__gte=date_from)
    if date_to:
        pay_qs = pay_qs.filter(received_at__date__lte=date_to)
    for p in pay_qs.order_by("received_at"):
        amt = Decimal(str(p.amount or 0))
        total += amt
        rows.append({
            "date": str(p.received_at.date()),
            "source": "Customer receipt",
            "detail": (p.invoice.customer.name if p.invoice and p.invoice.customer
                       else (p.invoice.invoice_number if p.invoice else "")),
            "method": p.method, "reference": p.reference, "amount": amt,
        })

    inc_qs = Expense.objects.filter(organisation=organisation, is_income=True)
    if date_from:
        inc_qs = inc_qs.filter(expense_date__gte=date_from)
    if date_to:
        inc_qs = inc_qs.filter(expense_date__lte=date_to)
    for e in inc_qs.order_by("expense_date"):
        amt = Decimal(str(e.amount or 0))
        total += amt
        rows.append({
            "date": str(e.expense_date), "source": "Other income",
            "detail": e.description[:120], "method": e.payment_method,
            "reference": e.reference, "amount": amt,
        })

    rows.sort(key=lambda r: r["date"])
    return {"period_start": str(date_from), "period_end": str(date_to),
            "rows": rows, "total": total}


def payments_out_report(organisation, date_from: date, date_to: date, **_):
    """All money paid out in the period: bill payments + expenses."""
    from apps.bills.models import BillPayment
    from apps.expenses.models import Expense

    rows = []
    total = _zero()

    bp_qs = BillPayment.objects.filter(organisation=organisation).select_related(
        "bill", "bill__supplier")
    if date_from:
        bp_qs = bp_qs.filter(payment_date__gte=date_from)
    if date_to:
        bp_qs = bp_qs.filter(payment_date__lte=date_to)
    for p in bp_qs.order_by("payment_date"):
        amt = Decimal(str(p.amount or 0))
        total += amt
        rows.append({
            "date": str(p.payment_date), "type": "Bill payment",
            "payee": p.bill.supplier.name if p.bill and p.bill.supplier else "",
            "method": p.method, "reference": p.reference, "amount": amt,
        })

    ex_qs = Expense.objects.filter(organisation=organisation, is_income=False)
    if date_from:
        ex_qs = ex_qs.filter(expense_date__gte=date_from)
    if date_to:
        ex_qs = ex_qs.filter(expense_date__lte=date_to)
    for e in ex_qs.order_by("expense_date"):
        amt = Decimal(str(e.amount or 0))
        total += amt
        rows.append({
            "date": str(e.expense_date), "type": "Expense",
            "payee": e.description[:120], "method": e.payment_method,
            "reference": e.reference, "amount": amt,
        })

    rows.sort(key=lambda r: r["date"])
    return {"period_start": str(date_from), "period_end": str(date_to),
            "rows": rows, "total": total}


# ── Receivables / payables master reports ────────────────────────────────────

def customers_report(organisation, date_from: date, date_to: date, **_):
    from .services import ReportService
    return {"rows": ReportService.customer_details(organisation)}


def sales_by_customer_report(organisation, date_from: date, date_to: date, **_):
    from .services import ReportService
    return {"rows": ReportService.sales_by_customer(organisation, date_from, date_to)}


def purchases_report(organisation, date_from: date, date_to: date, **_):
    """Supplier bills raised in the period."""
    from apps.bills.models import Bill

    qs = Bill.objects.filter(organisation=organisation).exclude(
        status="voided").select_related("supplier")
    if date_from:
        qs = qs.filter(issue_date__gte=date_from)
    if date_to:
        qs = qs.filter(issue_date__lte=date_to)
    rows = []
    total = subtotal = tax = _zero()
    for b in qs.order_by("issue_date"):
        total += Decimal(str(b.total_amount or 0))
        subtotal += Decimal(str(b.subtotal or 0))
        tax += Decimal(str(b.tax_amount or 0))
        rows.append({
            "date": str(b.issue_date), "bill_number": b.bill_number,
            "supplier": b.supplier.name if b.supplier else "",
            "status": b.status,
            "subtotal": b.subtotal, "tax": b.tax_amount,
            "total": b.total_amount, "amount_due": b.amount_due,
        })
    return {"period_start": str(date_from), "period_end": str(date_to),
            "rows": rows, "subtotal": subtotal, "tax": tax, "total": total}


def product_purchases_report(organisation, date_from: date, date_to: date, **_):
    """Purchases grouped by product (from purchase-order lines)."""
    from collections import defaultdict
    from apps.purchases.models import PurchaseOrderItem

    qs = PurchaseOrderItem.objects.filter(
        organisation=organisation,
        purchase_order__status__in=["approved", "partially_received", "received"],
    ).select_related("product", "purchase_order")
    if date_from:
        qs = qs.filter(purchase_order__order_date__gte=date_from)
    if date_to:
        qs = qs.filter(purchase_order__order_date__lte=date_to)

    agg: "dict[str, dict]" = defaultdict(lambda: {
        "quantity_ordered": Decimal("0"), "quantity_received": Decimal("0"),
        "total_cost": _zero(), "orders": 0})
    for it in qs:
        key = it.product.sku if it.product else "(no product)"
        row = agg[key]
        row["product_sku"] = key
        row["product_name"] = it.product.name if it.product else "(no product)"
        row["quantity_ordered"] += Decimal(str(it.quantity_ordered or 0))
        row["quantity_received"] += Decimal(str(it.quantity_received or 0))
        row["total_cost"] += (Decimal(str(it.unit_cost or 0))
                              * Decimal(str(it.quantity_ordered or 0)))
        row["orders"] += 1
    rows = sorted(agg.values(), key=lambda r: r["total_cost"], reverse=True)
    total = sum((r["total_cost"] for r in rows), _zero())
    return {"period_start": str(date_from), "period_end": str(date_to),
            "rows": rows, "total": total}


def suppliers_report(organisation, date_from: date, date_to: date, **_):
    """Supplier master with outstanding balances (open bill amounts + opening balance)."""
    from django.db.models import Sum
    from apps.bills.models import Bill
    from apps.suppliers.models import Supplier

    rows = []
    for s in Supplier.objects.filter(organisation=organisation).order_by("name"):
        due = Bill.objects.filter(
            organisation=organisation, supplier=s,
        ).exclude(status="voided").aggregate(t=Sum("amount_due"))["t"] or _zero()
        rows.append({
            "name": s.name,
            "email": getattr(s, "email", "") or "",
            "phone": getattr(s, "phone", "") or "",
            "opening_balance": s.opening_balance,
            "outstanding": due,
        })
    return {"rows": rows}


# ── Inventory ────────────────────────────────────────────────────────────────

def stock_valuation_report(organisation, date_from: date, date_to: date, **_):
    from .services import ReportService
    return ReportService.inventory_valuation(organisation)


def stock_report(organisation, date_from: date, date_to: date, **_):
    """Current stock levels per product/warehouse."""
    from apps.inventory.models import StockItem

    rows = []
    for si in StockItem.objects.filter(organisation=organisation).select_related(
            "product", "warehouse").order_by("product__name"):
        rows.append({
            "sku": si.product.sku if si.product else "",
            "product": si.product.name if si.product else "",
            "warehouse": si.warehouse.name if si.warehouse else "",
            "quantity": si.quantity_on_hand,
            "reorder_level": getattr(si.product, "reorder_level", None),
        })
    return {"rows": rows}


# ── Fixed assets ─────────────────────────────────────────────────────────────

def asset_register_rpt(organisation, date_from: date, date_to: date, **_):
    from apps.accounting.services import CapitalisationService
    return CapitalisationService.asset_register_report(organisation)


def assets_by_category_rpt(organisation, date_from: date, date_to: date, **_):
    from apps.accounting.services import CapitalisationService
    return CapitalisationService.assets_by_category(organisation)


def assets_by_location_rpt(organisation, date_from: date, date_to: date, **_):
    from apps.accounting.services import CapitalisationService
    return CapitalisationService.assets_by_location(organisation)


def depreciation_report(organisation, date_from: date, date_to: date, **_):
    """Posted depreciation entries in the period."""
    from apps.accounting.models import DepreciationEntry

    qs = DepreciationEntry.objects.filter(
        organisation=organisation).select_related("asset")
    if date_from:
        qs = qs.filter(period_year__gte=date_from.year).exclude(
            period_year=date_from.year, period_month__lt=date_from.month)
    if date_to:
        qs = qs.filter(period_year__lte=date_to.year).exclude(
            period_year=date_to.year, period_month__gt=date_to.month)
    rows = []
    total = _zero()
    for d in qs.order_by("period_year", "period_month", "asset__asset_code"):
        total += Decimal(str(d.depreciation_amount or 0))
        rows.append({
            "period": f"{d.period_year}-{d.period_month:02d}",
            "asset_code": d.asset.asset_code if d.asset else "",
            "asset_name": d.asset.name if d.asset else "",
            "depreciation": d.depreciation_amount,
            "accumulated": d.accumulated_to_date,
            "net_book_value": d.net_book_value,
        })
    return {"period_start": str(date_from), "period_end": str(date_to),
            "rows": rows, "total": total}


def depreciation_method_report(organisation, date_from: date, date_to: date, **_):
    """Assets grouped by depreciation method with cost / accum. dep / NBV totals."""
    from collections import defaultdict
    from apps.accounting.models import FixedAsset

    agg: "dict[str, dict]" = defaultdict(lambda: {
        "assets": 0, "total_cost": _zero(),
        "total_accumulated": _zero(), "total_nbv": _zero()})
    for a in FixedAsset.objects.filter(
            organisation=organisation, is_active=True, disposal_date__isnull=True):
        row = agg[a.depreciation_method]
        row["method"] = a.get_depreciation_method_display()
        row["assets"] += 1
        cost = Decimal(str(a.purchase_cost or 0))
        accum = Decimal(str(a.accumulated_depreciation or 0))
        row["total_cost"] += cost
        row["total_accumulated"] += accum
        row["total_nbv"] += cost - accum
    return {"rows": sorted(agg.values(), key=lambda r: r["method"])}


# ── Payroll & HR ─────────────────────────────────────────────────────────────

def employee_list(organisation, date_from: date, date_to: date, **_):
    from apps.payroll.models import Employee

    rows = []
    for e in Employee.objects.filter(
            organisation=organisation, is_active=True).order_by("last_name", "first_name"):
        rows.append({
            "employee_id": e.employee_id,
            "name": f"{e.first_name} {e.last_name}".strip(),
            "job_title": e.job_title, "department": e.department,
            "employment_type": e.employment_type,
            "hire_date": str(e.hire_date),
            "basic_salary": e.basic_salary,
        })
    return {"rows": rows}


def payroll_report(organisation, date_from: date, date_to: date, **_):
    """Payroll runs falling inside the period, with per-run totals."""
    from apps.payroll.models import PayrollRun

    qs = PayrollRun.objects.filter(organisation=organisation)
    if date_from:
        qs = qs.filter(period_year__gte=date_from.year).exclude(
            period_year=date_from.year, period_month__lt=date_from.month)
    if date_to:
        qs = qs.filter(period_year__lte=date_to.year).exclude(
            period_year=date_to.year, period_month__gt=date_to.month)
    rows = []
    totals = {"gross": _zero(), "deductions": _zero(), "net": _zero(), "paye": _zero()}
    for r in qs.order_by("period_year", "period_month"):
        rows.append({
            "run_number": r.run_number,
            "period": f"{r.period_year}-{r.period_month:02d}",
            "status": r.status,
            "gross": r.total_gross, "deductions": r.total_deductions,
            "net": r.total_net, "paye": r.total_paye,
            "pension_employee": r.total_pension_employee,
            "pension_employer": r.total_pension_employer,
            "nhf": r.total_nhf,
        })
        totals["gross"] += Decimal(str(r.total_gross or 0))
        totals["deductions"] += Decimal(str(r.total_deductions or 0))
        totals["net"] += Decimal(str(r.total_net or 0))
        totals["paye"] += Decimal(str(r.total_paye or 0))
    return {"period_start": str(date_from), "period_end": str(date_to),
            "rows": rows, "totals": totals}


def attendance_summary(organisation, date_from: date, date_to: date, **_):
    """Attendance counts per employee for the period."""
    from collections import defaultdict
    from apps.payroll.models import Attendance

    qs = Attendance.objects.filter(organisation=organisation).select_related("employee")
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    agg: "dict[str, dict]" = defaultdict(lambda: {
        "present": 0, "absent": 0, "half_day": 0, "leave": 0, "holiday": 0,
        "overtime_hours": Decimal("0")})
    for a in qs:
        key = str(a.employee_id)
        row = agg[key]
        row["employee"] = (f"{a.employee.first_name} {a.employee.last_name}".strip()
                           if a.employee else "")
        row[a.status] = row.get(a.status, 0) + 1
        row["overtime_hours"] += Decimal(str(a.overtime_hours or 0))
    return {"period_start": str(date_from), "period_end": str(date_to),
            "rows": sorted(agg.values(), key=lambda r: r.get("employee", ""))}


def _register_defaults() -> None:
    # Registration order = display order within the reports hub.

    # ── Financial Statements ──
    register(ReportDef("profit-loss", "Profit & Loss", "Financial Statements",
                       profit_and_loss_report, "Revenue, cost of sales and expenses for the period."))
    register(ReportDef("cash-flow", "Cash Flow Report", "Financial Statements",
                       cash_flow_report, "Cash in and out over the period."))
    register(ReportDef("balance-sheet", "Balance Sheet", "Financial Statements",
                       balance_sheet_report, "Assets, liabilities and equity as at the period end."))
    register(ReportDef("trial-balance", "Trial Balance", "Financial Statements",
                       trial_balance_report, "Every account's debit/credit balance as at the period end."))
    register(ReportDef("vat-return", "Net Tax Report (VAT Return)", "Financial Statements",
                       vat_return, "Output VAT less input VAT for the period."))
    register(ReportDef("tax-summary", "Tax Summary Report", "Financial Statements",
                       tax_summary_report, "VAT, WHT and PAYE positions for the period."))
    # ── Accountant Reports (auditor / practitioner pack) ──
    register(ReportDef("financial-report-pack", "Financial Report Pack", "Accountant Reports",
                       financial_report_pack, "Single-entity P&L + Balance Sheet + Trial Balance pack."))
    register(ReportDef("changes-in-equity", "Statement of Changes in Equity", "Accountant Reports",
                       statement_of_changes_in_equity, "Opening → movement → closing per equity account."))
    register(ReportDef("notes", "Notes to the Financial Statements", "Accountant Reports",
                       notes_shell, "Scaffold of the standard IFRS-for-SMEs notes."))

    # ── General Ledger ──
    register(ReportDef("account-list", "Account List", "General Ledger",
                       account_list, "Chart of accounts with current balances."))
    register(ReportDef("cash-register", "Cash Register Report", "General Ledger",
                       cash_register, "Running-balance register of cash & bank accounts."))
    register(ReportDef("pay-bills", "Pay Bills Report", "General Ledger",
                       pay_bills_report, "Supplier bill payments made in the period."))
    register(ReportDef("deposits", "Deposit Report", "General Ledger",
                       deposit_report, "Customer receipts and other income received in the period."))
    register(ReportDef("gl-tax-summary", "Tax Summary", "General Ledger",
                       tax_summary_report, "VAT, WHT and PAYE positions for the period."))
    register(ReportDef("gl-detail", "Transaction Report (GL Detail)", "General Ledger",
                       gl_detail, "Running-balance ledger detail per account."))
    register(ReportDef("payments", "Payments", "General Ledger",
                       payments_out_report, "All money paid out: bill payments and expenses."))
    register(ReportDef("journal-register", "Journal Register", "General Ledger",
                       journal_register, "Every posted journal entry with its lines."))

    # ── Accounts Receivable ──
    register(ReportDef("sales-by-customer", "Sales By Customer", "Accounts Receivable",
                       sales_by_customer_report, "Sales totals per customer for the period."))
    register(ReportDef("customers-report", "Customers Report", "Accounts Receivable",
                       customers_report, "Customer master with contact details and balances."))
    register(ReportDef("customer-receipts", "Customer Receipts", "Accounts Receivable",
                       customer_receipts, "Receipts from customers in the period."))

    # ── Accounts Payable ──
    register(ReportDef("purchases-report", "Purchases Report", "Accounts Payable",
                       purchases_report, "Supplier bills raised in the period."))
    register(ReportDef("purchase-returns", "Purchase Return", "Accounts Payable",
                       purchase_returns, "Supplier returns / debit notes in the period."))
    register(ReportDef("product-purchases", "Product Purchases Report", "Accounts Payable",
                       product_purchases_report, "Purchases grouped by product."))
    register(ReportDef("suppliers-report", "Suppliers Report", "Accounts Payable",
                       suppliers_report, "Supplier master with outstanding balances."))

    # ── Inventory ──
    register(ReportDef("stock-report", "Stock Report", "Inventory",
                       stock_report, "Current stock levels per product and warehouse."))
    register(ReportDef("stock-valuation", "Stock Valuation Report", "Inventory",
                       stock_valuation_report, "Inventory quantities valued at cost."))

    # ── Fixed Assets ──
    register(ReportDef("asset-register", "Asset Register", "Fixed Assets",
                       asset_register_rpt, "Every asset with cost, accumulated depreciation and NBV."))
    register(ReportDef("assets-by-category", "Asset By Category", "Fixed Assets",
                       assets_by_category_rpt, "Assets grouped by category."))
    register(ReportDef("assets-by-location", "Asset By Location", "Fixed Assets",
                       assets_by_location_rpt, "Assets grouped by location."))
    register(ReportDef("depreciation-report", "Depreciation Report", "Fixed Assets",
                       depreciation_report, "Posted depreciation entries in the period."))
    register(ReportDef("depreciation-method", "Depreciation Method Report", "Fixed Assets",
                       depreciation_method_report, "Assets grouped by depreciation method."))

    # ── Payroll & HR ──
    register(ReportDef("employee-list", "Employee List", "Payroll & HR",
                       employee_list, "Active employees with role, department and salary."))
    register(ReportDef("payroll-report", "Payroll Report", "Payroll & HR",
                       payroll_report, "Payroll runs in the period with gross/net/PAYE totals."))
    register(ReportDef("attendance-summary", "Attendance Summary", "Payroll & HR",
                       attendance_summary, "Attendance counts per employee for the period."))


_register_defaults()
