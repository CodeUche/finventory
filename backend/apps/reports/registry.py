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


def customer_receipts(organisation, date_from: date, date_to: date, **_):
    """Customer Receipts — money received from customers in the period.
    (Half of the old ambiguous 'Payments' report.)"""
    from .services import ReportService
    return ReportService.customer_payments(organisation, date_from, date_to)


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


def _register_defaults() -> None:
    register(ReportDef("purchase-returns", "Purchase Returns", "Accounts Payable",
                       purchase_returns, "Supplier returns / debit notes in the period."))
    register(ReportDef("vat-return", "VAT Return / Liability", "Tax",
                       vat_return, "Output VAT less input VAT (reframes 'Net Tax')."))
    register(ReportDef("customer-receipts", "Customer Receipts", "Accounts Receivable",
                       customer_receipts, "Receipts from customers in the period."))
    register(ReportDef("financial-report-pack", "Financial Report Pack", "Financial Statements",
                       financial_report_pack, "Single-entity P&L + Balance Sheet + Trial Balance pack."))
    register(ReportDef("gl-detail", "General Ledger (Detail)", "General Ledger",
                       gl_detail, "Running-balance ledger detail per account."))
    register(ReportDef("journal-register", "Journal Register", "General Ledger",
                       journal_register, "Every posted journal entry with its lines."))
    register(ReportDef("changes-in-equity", "Statement of Changes in Equity", "Financial Statements",
                       statement_of_changes_in_equity, "Opening → movement → closing per equity account."))
    register(ReportDef("notes", "Notes to the Financial Statements", "Financial Statements",
                       notes_shell, "Scaffold of the standard IFRS-for-SMEs notes."))


_register_defaults()
