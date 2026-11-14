"""
The one VAT calculation.

Every VAT figure in Audity (Reports Overview card, VAT Return report, Tax
Summary report, the Tax page VAT report, and the VAT ITC worksheet and its PDF)
comes from ``compute_vat``. It works for one organisation and any date range
(a calendar month is the usual case) and returns BOTH the totals and the
document-by-document lines behind them, so a figure can always be traced.

Rules (agreed with the tax expert and the senior accountant, 2026-11-13):

OUTPUT VAT
  * Posted sales invoices (incl. POS): confirmed, paid, partially_paid, credit,
    overdue and returned. Draft, proforma, voided are out.
  * Counted by invoice ``issue_date``, never by payment date.
  * Amount = sum of the line-level SaleItem.tax_amount (already rounded per line
    half-up to the kobo when the sale was made). It is reconciled to
    Invoice.tax_amount and any mismatch is FLAGGED in the result, not changed.
  * Returns / credit notes: SaleReturnItem.tax_refund is subtracted in the period
    of the return date.
  * No floor: a negative result is a refund / carry-forward and is returned as
    a negative number.
  * Zero-rated and exempt sales carry tax 0 but their value is reported in the
    turnover section. Items that are not taxable at all (out of scope) appear
    nowhere.

INPUT VAT
  * Bills: approved, paid, partially_paid, overdue, and 'received' ONLY when the
    bill was created from a purchase order (the ledger holds its input VAT from
    the moment of receipt). Draft, other 'received' and voided bills are out.
  * Counted by bill ``issue_date``.
  * Recoverable only if the business is VAT registered (Organisation.charges_vat),
    the supplier has a TIN recorded, and the bill is not exempt. Anything else is
    reported separately as irrecoverable input VAT (it is a cost).
  * Purchase returns reduce input VAT in the period of the return date.
  * Bills carry one VAT figure and one treatment for the whole bill (no line-level
    VAT data exists on bill lines), so the decision is made per bill.

NET = output after returns - recoverable input after purchase returns
      +/- manual adjustments. Negative is allowed.

Manual adjustments are VATTransaction rows that a person typed in. Rows that the
old "sync" or the e-invoice hook created for a real invoice/bill are stale
snapshots of documents this function already reads live, so they are ignored
(never counted twice, never deleted).
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from django.db.models import Count, Sum

from apps.core.utils import round_money

ZERO = Decimal("0")

OUTPUT_INVOICE_STATUSES = ["confirmed", "paid", "partially_paid", "credit", "overdue", "returned"]
INPUT_BILL_STATUSES = ["approved", "paid", "partially_paid", "overdue"]
WORKSHEET_NOTE = (
    "This is a working figure produced by Audity from your sales and bills. "
    "It must be reviewed by a licensed tax practitioner before anything is filed with FIRS."
)


def _d(value) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


def month_range(year: int, month: int):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def filing_due_date(period_end: date) -> date:
    """VAT is due on the 21st of the month after the period. Reminder only."""
    y, m = (period_end.year + 1, 1) if period_end.month == 12 else (period_end.year, period_end.month + 1)
    return date(y, m, 21)


def _line(**kw) -> dict:
    base = {
        "kind": "", "direction": "", "document_id": "", "source_ref": "", "date": None,
        "counterparty_name": "", "counterparty_tin": "", "net_amount": ZERO, "vat_amount": ZERO,
        "vat_rate": None, "is_claimable": True, "reason": "", "notes": "",
    }
    base.update(kw)
    return base


# ─── Output side ─────────────────────────────────────────────────────────────

def _output_lines(organisation, date_from, date_to):
    from apps.sales.models import Invoice, SaleItem, SaleReturnItem

    inv_qs = Invoice.objects.filter(
        organisation=organisation, status__in=OUTPUT_INVOICE_STATUSES,
        issue_date__gte=date_from, issue_date__lte=date_to,
    )
    item_rows = SaleItem.objects.filter(
        organisation=organisation, invoice__in=inv_qs,
    ).values(
        "invoice_id", "invoice__invoice_number", "invoice__issue_date", "invoice__tax_amount",
        "invoice__customer__name", "invoice__customer__tin",
        "tax_amount", "tax_rate", "line_total",
        "product__is_taxable", "product__tax_class__treatment",
    )

    per_invoice = {}
    turnover = {"standard": ZERO, "zero_rated": ZERO, "exempt": ZERO, "unclassified_nil_rated": ZERO}
    for r in item_rows:
        tax = _d(r["tax_amount"])
        net = _d(r["line_total"]) - tax
        rate = _d(r["tax_rate"])
        if rate > 0 or tax > 0:
            turnover["standard"] += net
        else:
            treatment = r["product__tax_class__treatment"]
            if treatment == "zero_rated":
                turnover["zero_rated"] += net
            elif treatment == "exempt":
                turnover["exempt"] += net
            elif r["product__is_taxable"] is False:
                pass  # out of scope: reported nowhere
            else:
                turnover["unclassified_nil_rated"] += net
        e = per_invoice.setdefault(r["invoice_id"], {
            "number": r["invoice__invoice_number"], "date": r["invoice__issue_date"],
            "header_tax": _d(r["invoice__tax_amount"]),
            "customer": r["invoice__customer__name"] or "", "tin": r["invoice__customer__tin"] or "",
            "net": ZERO, "vat": ZERO, "rates": set(),
        })
        e["net"] += net
        e["vat"] += tax
        e["rates"].add(rate)

    lines, mismatches = [], []
    for inv_id, e in per_invoice.items():
        if e["vat"] != e["header_tax"]:
            mismatches.append({
                "invoice_number": e["number"], "line_vat": e["vat"], "invoice_vat": e["header_tax"],
                "difference": e["vat"] - e["header_tax"],
            })
        rate = next(iter(e["rates"])) if len(e["rates"]) == 1 else None
        lines.append(_line(
            kind="sale", direction="output", document_id=str(inv_id), source_ref=e["number"],
            date=e["date"], counterparty_name=e["customer"], counterparty_tin=e["tin"],
            net_amount=e["net"], vat_amount=e["vat"], vat_rate=rate,
            reason="Line VAT differs from invoice total" if e["vat"] != e["header_tax"] else "",
        ))

    # Invoices that carry VAT but have no lines at all: use the header figure, flagged.
    headerless = inv_qs.annotate(n_items=Count("items")).filter(n_items=0).exclude(tax_amount=0)
    for inv in headerless.select_related("customer"):
        tax = _d(inv.tax_amount)
        mismatches.append({
            "invoice_number": inv.invoice_number, "line_vat": ZERO, "invoice_vat": tax,
            "difference": -tax, "note": "no lines; invoice total used",
        })
        lines.append(_line(
            kind="sale", direction="output", document_id=str(inv.id), source_ref=inv.invoice_number,
            date=inv.issue_date, counterparty_name=inv.customer.name if inv.customer else "",
            counterparty_tin=(inv.customer.tin if inv.customer else "") or "",
            net_amount=_d(inv.total_amount) - tax, vat_amount=tax,
            reason="Invoice has no lines; invoice total used",
        ))

    ret_rows = SaleReturnItem.objects.filter(
        organisation=organisation,
        sale_return__return_date__gte=date_from, sale_return__return_date__lte=date_to,
        sale_return__invoice__status__in=OUTPUT_INVOICE_STATUSES,
    ).values(
        "sale_return_id", "sale_return__return_number", "sale_return__return_date",
        "sale_return__invoice__customer__name", "sale_return__invoice__customer__tin",
        "tax_refund", "refund_amount",
    )
    per_return = {}
    for r in ret_rows:
        e = per_return.setdefault(r["sale_return_id"], {
            "number": r["sale_return__return_number"], "date": r["sale_return__return_date"],
            "customer": r["sale_return__invoice__customer__name"] or "",
            "tin": r["sale_return__invoice__customer__tin"] or "", "net": ZERO, "vat": ZERO,
        })
        e["vat"] += _d(r["tax_refund"])
        e["net"] += _d(r["refund_amount"]) - _d(r["tax_refund"])
    for rid, e in per_return.items():
        lines.append(_line(
            kind="sale_return", direction="output", document_id=str(rid), source_ref=e["number"],
            date=e["date"], counterparty_name=e["customer"], counterparty_tin=e["tin"],
            net_amount=-e["net"], vat_amount=-e["vat"], reason="Credit note / sales return",
        ))
    return lines, turnover, mismatches


# ─── Input side ──────────────────────────────────────────────────────────────

def _input_lines(organisation, date_from, date_to):
    from django.db.models import Q
    from apps.bills.models import Bill
    from apps.purchases.models import PurchaseReturn

    registered = bool(organisation.charges_vat)
    bills = Bill.objects.filter(
        organisation=organisation, issue_date__gte=date_from, issue_date__lte=date_to,
    ).filter(
        Q(status__in=INPUT_BILL_STATUSES) | Q(status=Bill.RECEIVED, source_purchase_order__isnull=False)
    ).exclude(tax_amount=0).select_related("supplier")

    def _verdict(supplier_tin, treatment):
        if not registered:
            return False, "Your business is not marked as registered for VAT"
        if not (supplier_tin or "").strip():
            return False, "Supplier has no TIN recorded"
        if treatment == "exempt":
            return False, "Exempt purchase: VAT cannot be claimed back"
        return True, ""

    lines = []
    for b in bills:
        tin = b.supplier.tax_id if b.supplier else ""
        ok, why = _verdict(tin, b.vat_treatment)
        lines.append(_line(
            kind="bill", direction="input", document_id=str(b.id), source_ref=b.bill_number,
            date=b.issue_date, counterparty_name=b.supplier.name if b.supplier else "",
            counterparty_tin=tin or "", net_amount=_d(b.subtotal), vat_amount=_d(b.tax_amount),
            is_claimable=ok, reason=why,
        ))

    returns = PurchaseReturn.objects.filter(
        organisation=organisation, return_date__gte=date_from, return_date__lte=date_to,
    ).exclude(tax_amount=0).select_related("supplier", "purchase_order__supplier")
    for r in returns:
        sup = r.supplier or r.purchase_order.supplier
        tin = sup.tax_id if sup else ""
        ok, why = _verdict(tin, "standard")
        lines.append(_line(
            kind="purchase_return", direction="input", document_id=str(r.id), source_ref=r.return_number,
            date=r.return_date, counterparty_name=sup.name if sup else "", counterparty_tin=tin or "",
            net_amount=-_d(r.subtotal), vat_amount=-_d(r.tax_amount), is_claimable=ok,
            reason=why or "Supplier debit note / purchase return",
        ))
    return lines


# ─── Manual adjustments ──────────────────────────────────────────────────────

def _manual_adjustments(organisation, date_from, date_to):
    """VATTransaction rows typed in by a person. Snapshots of real documents are skipped."""
    from apps.bills.models import Bill
    from apps.sales.models import Invoice
    from apps.tax.models import VATTransaction

    rows = list(VATTransaction.objects.filter(
        organisation=organisation, period_end__gte=date_from, period_end__lte=date_to,
    ))
    if not rows:
        return [], 0
    refs = {r.source_ref for r in rows if r.source_ref}
    known = set()
    if refs:
        known |= set(Invoice.all_objects.filter(organisation=organisation).filter(
            invoice_number__in=refs).values_list("invoice_number", flat=True))
        known |= set(Invoice.all_objects.filter(organisation=organisation).filter(
            firs_irn__in=refs).values_list("firs_irn", flat=True))
        known |= set(Bill.all_objects.filter(organisation=organisation).filter(
            bill_number__in=refs).values_list("bill_number", flat=True))
        for b in Bill.all_objects.filter(organisation=organisation).values_list("id", flat=True):
            if str(b)[:12] in refs:
                known.add(str(b)[:12])
    out, superseded = [], 0
    for r in rows:
        if (r.source_ref and r.source_ref in known) or (r.notes or "").startswith("E-Invoice"):
            superseded += 1
            continue
        out.append(_line(
            kind="manual", direction=r.direction, document_id=str(r.id), source_ref=r.source_ref,
            date=r.period_end, counterparty_name=r.counterparty_name, counterparty_tin=r.counterparty_tin,
            net_amount=_d(r.net_amount), vat_amount=_d(r.vat_amount), vat_rate=_d(r.vat_rate),
            is_claimable=bool(r.is_claimable),
            reason="Manual adjustment" + ("" if r.is_claimable or r.direction == "output" else " (not claimable)"),
            notes=r.notes or "",
        ))
    return out, superseded


# ─── Ledger reconciliation ───────────────────────────────────────────────────

def _ledger_reconciliation(organisation, date_from, date_to, output_vat, input_vat):
    """GL movement on the Output / Input VAT accounts for the same dates. Reported, never fixed."""
    from apps.accounting.models import Account, AccountMapping, JournalEntry, JournalLine
    from apps.accounting.services import AccountMappingService

    mapping = AccountMapping.objects.filter(organisation=organisation).first()
    out_acct = getattr(mapping, "vat_output_account", None) or AccountMappingService.suggest(organisation, "vat_output_account")
    mapped_in = getattr(mapping, "vat_input_account", None)
    by_code = Account.objects.filter(organisation=organisation, code="1400", is_deleted=False).first()

    def _movement(acct, sign):
        if acct is None:
            return ZERO
        agg = JournalLine.objects.filter(
            journal_entry__organisation=organisation, journal_entry__status=JournalEntry.POSTED,
            journal_entry__is_deleted=False,
            journal_entry__entry_date__gte=date_from, journal_entry__entry_date__lte=date_to,
            account=acct,
        ).aggregate(d=Sum("debit"), c=Sum("credit"))
        return sign * (_d(agg["d"]) - _d(agg["c"]))

    gl_output = _movement(out_acct, -1)
    input_accounts, gl_input = [], ZERO
    seen = set()
    for acct in (by_code, mapped_in):
        if acct is None or acct.id in seen:
            continue
        seen.add(acct.id)
        mv = _movement(acct, 1)
        input_accounts.append({"code": acct.code, "name": acct.name, "movement": mv,
                               "role": "mapped vat_input_account" if acct == mapped_in else "bill journal (1400)"})
        gl_input += mv
    return {
        "gl_output_vat": gl_output,
        "gl_output_account": {"code": out_acct.code, "name": out_acct.name} if out_acct else None,
        "gl_input_vat": gl_input,
        "gl_input_accounts": input_accounts,
        "output_difference": output_vat - gl_output,
        "input_difference": input_vat - gl_input,
        "note": "Reported only. The ledger is not changed by this report.",
    }


# ─── Old methods, kept ONLY to show how the number moved ─────────────────────
# REMOVE AFTER THE COMPARISON WINDOW. Nothing else may call these.

def _legacy_reports_method(organisation, date_from, date_to):
    from apps.bills.models import Bill
    from apps.sales.models import Invoice

    out = Invoice.objects.filter(
        organisation=organisation, status__in=["paid", "confirmed", "partially_paid", "credit", "overdue"],
        issue_date__gte=date_from, issue_date__lte=date_to,
    ).aggregate(t=Sum("tax_amount"))["t"] or ZERO
    inp = Bill.objects.filter(
        organisation=organisation, status__in=["approved", "paid", "partially_paid"],
        issue_date__gte=date_from, issue_date__lte=date_to,
    ).aggregate(t=Sum("tax_amount"))["t"] or ZERO
    return {"output_vat": out, "input_vat": inp, "net_vat_payable": out - inp}


def _legacy_tax_service_method(organisation, date_from, date_to):
    from apps.bills.models import Bill
    from apps.sales.models import SaleItem, SaleReturnItem

    out = SaleItem.objects.filter(
        organisation=organisation, invoice__issue_date__gte=date_from, invoice__issue_date__lte=date_to,
        invoice__status__in=["paid", "confirmed", "partially_paid", "credit"],
    ).aggregate(t=Sum("tax_amount"))["t"] or ZERO
    ret = SaleReturnItem.objects.filter(
        organisation=organisation, sale_return__return_date__gte=date_from,
        sale_return__return_date__lte=date_to, tax_refund__isnull=False,
    ).aggregate(t=Sum("tax_refund"))["t"] or ZERO
    out = max(ZERO, out - ret)
    # The old exempt-bill exclusion queried a field that does not exist, failed
    # silently and fell back to counting every bill. Reproduced as it behaved.
    inp = Bill.objects.filter(
        organisation=organisation, issue_date__gte=date_from, issue_date__lte=date_to,
        status__in=[Bill.APPROVED, Bill.PAID, Bill.PARTIALLY_PAID],
    ).aggregate(t=Sum("tax_amount"))["t"] or ZERO
    return {"output_vat": out, "input_vat": inp, "net_vat_payable": out - inp}


def _previous_methods(organisation, date_from, date_to, new_output, new_input, new_net):
    if date_to >= date.today():
        return None  # only closed periods are compared
    a = _legacy_reports_method(organisation, date_from, date_to)
    b = _legacy_tax_service_method(organisation, date_from, date_to)
    return {
        "reports_summary": a,
        "tax_page": b,
        "new_minus_reports_summary_net": new_net - a["net_vat_payable"],
        "new_minus_tax_page_net": new_net - b["net_vat_payable"],
        "note": "Old methods shown for comparison only; to be removed after the comparison window.",
    }


# ─── The function ────────────────────────────────────────────────────────────

def compute_vat(
    organisation,
    date_from: Optional[date],
    date_to: Optional[date],
    *,
    with_reconciliation: bool = True,
    with_previous_methods: bool = True,
) -> dict:
    """Single VAT calculation for ``organisation`` over [date_from, date_to]."""
    if date_from is None or date_to is None:
        raise ValueError("compute_vat needs both date_from and date_to")

    out_lines, turnover, mismatches = _output_lines(organisation, date_from, date_to)
    in_lines = _input_lines(organisation, date_from, date_to)
    manual, superseded = _manual_adjustments(organisation, date_from, date_to)

    sales_vat = sum((l["vat_amount"] for l in out_lines if l["kind"] == "sale"), ZERO)
    returns_vat = -sum((l["vat_amount"] for l in out_lines if l["kind"] == "sale_return"), ZERO)
    manual_out = sum((l["vat_amount"] for l in manual if l["direction"] == "output"), ZERO)
    output_vat = sales_vat - returns_vat + manual_out

    bills_vat_all = sum((l["vat_amount"] for l in in_lines if l["kind"] == "bill"), ZERO)
    recoverable_bills = sum((l["vat_amount"] for l in in_lines if l["kind"] == "bill" and l["is_claimable"]), ZERO)
    purchase_returns_claimable = -sum(
        (l["vat_amount"] for l in in_lines if l["kind"] == "purchase_return" and l["is_claimable"]), ZERO)
    purchase_returns_other = -sum(
        (l["vat_amount"] for l in in_lines if l["kind"] == "purchase_return" and not l["is_claimable"]), ZERO)
    manual_in = sum((l["vat_amount"] for l in manual if l["direction"] == "input" and l["is_claimable"]), ZERO)
    recoverable_input = recoverable_bills - purchase_returns_claimable + manual_in
    irrecoverable = (bills_vat_all - recoverable_bills) - purchase_returns_other

    net = output_vat - recoverable_input
    registered = bool(organisation.charges_vat)

    all_lines = sorted(out_lines + in_lines + manual, key=lambda l: (str(l["date"]), l["kind"], l["source_ref"]))
    for l in all_lines:
        l["date"] = str(l["date"]) if l["date"] else None

    result = {
        "period_start": date_from,
        "period_end": date_to,
        "filing_due_date": filing_due_date(date_to),
        "vat_registered": registered,
        "registration_note": "" if registered else
            "This business is not marked as registered for VAT, so no input VAT is recoverable.",
        "output_vat_on_sales": sales_vat,
        "output_vat_returns": returns_vat,
        "output_vat_manual_adjustments": manual_out,
        "output_vat": output_vat,
        "input_vat_recoverable": recoverable_input,
        "input_vat_irrecoverable": irrecoverable,
        "input_vat_manual_adjustments": manual_in,
        "net_vat_payable": net,
        "position": "payable" if net > 0 else ("refund_or_carry_forward" if net < 0 else "nil"),
        "turnover": {
            "taxable_standard": turnover["standard"], "zero_rated": turnover["zero_rated"],
            "exempt": turnover["exempt"], "unclassified_nil_rated": turnover["unclassified_nil_rated"],
        },
        "invoice_vat_mismatches": mismatches,
        "superseded_snapshot_rows": superseded,
        "lines": all_lines,
        "worksheet_note": WORKSHEET_NOTE,
    }
    if with_reconciliation:
        result["reconciliation"] = _ledger_reconciliation(
            organisation, date_from, date_to, output_vat, recoverable_input + irrecoverable)
    if with_previous_methods:
        result["previous_methods"] = _previous_methods(organisation, date_from, date_to, output_vat, recoverable_input, net)
    return result


def summary_view(vat: dict) -> dict:
    """The compute_vat result without the per-document lines: for report endpoints."""
    return {k: v for k, v in vat.items() if k != "lines"}
