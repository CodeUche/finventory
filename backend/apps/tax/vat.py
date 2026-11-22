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
  * Counted at the EARLIEST of: the invoice being issued, money being received (a deposit on a
    proforma is VAT on the day it arrives), or delivery (Nigeria Tax Act 2025, s.146(1)). Every
    invoice raised under the current rule books its VAT when it is raised, so that is its issue
    date (a proforma that is confirmed takes the confirmation date as its issue date). An older
    fulfil-later invoice (raised before the two-step posting, or stamped "delivery") is counted at
    the earliest of its issue date, first receipt and delivery, and flagged as an older invoice.
  * A voided invoice stays in the month it was raised (a return already filed must not change);
    the void is a negative line in the month it was done, the same date the ledger uses.
  * Delivery-charge VAT (Invoice.shipping_tax_amount) is output VAT and is counted with the invoice.
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
  * Bills: approved, paid, partially_paid, overdue. A bill that came from a purchase
    order and is still only 'received' is a goods-received note, not a supplier tax
    invoice: its VAT is shown as a memo line (awaiting supplier invoice) and is NOT
    claimed. Draft, other 'received' and voided bills are out.
  * Counted by bill ``issue_date``.
  * Recoverable only if the business is VAT registered (Organisation.charges_vat),
    the bill is not exempt and not marked "not claimable" by the user, and the supplier
    is VAT registered (Supplier.vat_registered = yes). 'no' is never claimable;
    'unknown' falls back to "a TIN is on record" and is marked unconfirmed.
    Anything else is reported separately as irrecoverable input VAT (a cost).
  * The organisation's "share used for taxable supplies" % is applied to the
    recoverable total; the rest is irrecoverable.
  * Purchase returns reduce input VAT in the period of the return date and follow the
    ORIGINAL bill's verdict (linked through the purchase order); with no linked bill
    the supplier's status decides.
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
from datetime import date
from decimal import Decimal
from typing import Optional

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.core.utils import round_money

ZERO = Decimal("0")

OUTPUT_INVOICE_STATUSES = ["confirmed", "paid", "partially_paid", "credit", "overdue", "returned"]
INPUT_BILL_STATUSES = ["approved", "paid", "partially_paid", "overdue"]
WORKSHEET_NOTE = (
    "This is a working figure prepared by Audity from your sales and bills. It is not a filed "
    "return and not tax advice. Have a licensed tax practitioner review it before you file or pay. "
    "Input VAT is counted only where your business is VAT registered and the supplier is VAT registered, "
    "or, when that is not known, the bill carries the supplier tax ID AND the supplier invoice reference. "
    "Otherwise it is shown as Not counted until checked. It is not counted on exempt purchases."
)
DUE_NOTE = "The legal due date is the 21st of the next month. Confirm with the Service."
BILL_TREATMENT_NOTE = (
    "VAT treatment applies to the whole bill. If a bill mixes standard-rated and exempt items, "
    "record it as separate bills so the claim is right."
)
NEGATIVE_NOTE = (
    "Your input VAT is more than your output VAT for this period. This may be a refund or a "
    "carry-forward. Ask your tax practitioner how to treat it."
)
UNREGISTERED_NOTE = (
    "Your business is not marked as registered for VAT, so no input VAT is counted. Small businesses "
    "under the registration limits may not need to register; confirm with your practitioner."
)
CHARGED_BUT_OFF_NOTE = (
    "Warning: VAT was charged on sales in this period, but your business is marked as not registered "
    "for VAT. Check the VAT setting in Settings with your practitioner."
)
PRE_2026_NOTE = (
    "This period starts before 1 January 2026. Input VAT on services and fixed assets bought before "
    "that date may be treated differently. Confirm with your practitioner."
)
AWAITING_INVOICE_LABEL = "VAT on goods received, awaiting supplier invoice (not claimed yet)"
TURNOVER_LABELS = {
    "taxable_standard": "Taxable sales (standard rate)",
    "zero_rated": "Zero-rated sales",
    "exempt": "Exempt sales",
    "not_taxable": "Not taxable (exempt or out of scope, please classify)",
    "nil_vat_needs_class": "Nil VAT, needs a VAT class",
}
NOT_CLAIMABLE_LABELS = {
    "private_use": "Private or non-business use",
    "entertainment": "Entertainment and hospitality",
    "motor_vehicle": "Passenger motor vehicles",
    "other": "Other",
}


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

def _bucket(rate, tax, treatment, is_taxable) -> Optional[str]:
    """Which turnover bucket a sale line belongs to."""
    if rate > 0 or tax > 0:
        return "taxable_standard"
    if treatment == "zero_rated":
        return "zero_rated"
    if treatment == "exempt":
        return "exempt"
    if is_taxable is False:
        return "not_taxable"
    return "nil_vat_needs_class"


OLDER_INVOICE_NOTE = (
    "Older invoice: it was raised under the old delivery-date rule, so months before delivery may be "
    "understated. Ask your accountant."
)


def _effective_vat_date(inv):
    """(date the output VAT is due, is_older_invoice).

    VAT is due at the EARLIEST of the invoice being issued, money received, or delivery
    (Nigeria Tax Act 2025, s.146(1)). Every invoice raised under the current rule books its
    VAT when it is raised, so its date is the issue date. An older fulfil-later invoice (raised
    before the two-step posting, or stamped "delivery") has ledger entries that booked VAT at
    delivery; those entries are left alone, but the worksheet counts it at the earliest of its
    issue date, first receipt and delivery, and flags it.
    """
    from apps.sales import ledger, rules
    from apps.sales.models import SalePayment

    if not inv.is_deferred:
        return inv.issue_date, False
    if ledger.is_new_style_deferred(inv) and inv.vat_timing != rules.VAT_TIMING_DELIVERY:
        return inv.issue_date, False
    dates = [inv.issue_date]
    if inv.fulfilled_at:
        dates.append(timezone.localtime(inv.fulfilled_at).date())
    first_receipt = SalePayment.objects.filter(invoice=inv, amount__gt=0).order_by("received_at").first()
    if first_receipt is not None:
        dates.append(timezone.localtime(first_receipt.received_at).date())
    return min(dates), True


def _vat_account(organisation):
    from apps.accounting.services import AccountMappingService
    try:
        return AccountMappingService.resolve(organisation, "vat_output_account")
    except Exception:
        return None


def _deposit_lines(organisation, date_from, date_to):
    """Output VAT booked on money received before the invoice exists (a deposit on a
    proforma: ledger entries 'sale_deposit'). The ledger books that VAT on the day the
    money arrives, and later takes it off the invoice's own VAT, so:
      * returns ({invoice_id: deposit VAT already booked}, lines for deposits in the period);
      * the invoice's own line is reduced by the first figure in _output_lines.
    A voided invoice keeps its deposits in their own month; the void shows as a negative
    line in the month it was voided (see _void_lines)."""
    from apps.accounting.models import JournalEntry, JournalLine
    from apps.sales.models import SalePayment

    entries = list(JournalEntry.objects.filter(
        organisation=organisation, source_type="sale_deposit", status=JournalEntry.POSTED,
        is_deleted=False, entry_date__lte=date_to,
    ))
    vat_acct = _vat_account(organisation)
    if not entries or vat_acct is None:
        return {}, []
    pay_by_id = {str(p.id): p for p in SalePayment.objects.filter(
        organisation=organisation, id__in=[e.source_ref for e in entries],
    ).select_related("invoice", "invoice__customer")}
    vat_by_entry = {
        r["journal_entry_id"]: _d(r["v"]) for r in JournalLine.objects.filter(
            journal_entry__in=entries, account=vat_acct,
        ).values("journal_entry_id").annotate(v=Sum("credit"))
    }
    per_invoice, lines = {}, []
    for e in entries:
        pay = pay_by_id.get(e.source_ref)
        vat = vat_by_entry.get(e.id, ZERO)
        if pay is None or vat == ZERO:
            continue
        inv = pay.invoice
        per_invoice[inv.id] = per_invoice.get(inv.id, ZERO) + vat
        if date_from <= e.entry_date <= date_to:
            lines.append(_line(
                kind="sale", direction="output", document_id=str(inv.id),
                source_ref=inv.invoice_number, date=e.entry_date,
                counterparty_name=inv.customer.name if inv.customer else "",
                counterparty_tin=(inv.customer.tin if inv.customer else "") or "",
                net_amount=ZERO, vat_amount=vat,
                reason="VAT on a deposit received before delivery (due when the money arrives)",
            ))
    return per_invoice, lines


def _void_entries(organisation):
    """{invoice_id: (void date, VAT the void took back)} for every voided invoice. The void is ONE mirror entry in the ledger (source_type 'invoice_void'), dated the
    day it was done; the VAT it took back is its debit on the Output VAT account."""
    from apps.accounting.models import JournalEntry, JournalLine

    vat_acct = _vat_account(organisation)
    ents = list(JournalEntry.objects.filter(
        organisation=organisation, source_type="invoice_void", status=JournalEntry.POSTED,
        is_deleted=False))
    if not ents or vat_acct is None:
        return {}
    back = {r["journal_entry_id"]: _d(r["d"]) - _d(r["c"]) for r in JournalLine.objects.filter(
        journal_entry__in=ents, account=vat_acct,
    ).values("journal_entry_id").annotate(d=Sum("debit"), c=Sum("credit"))}
    out = {}
    for e in ents:
        out[e.source_ref] = (e.entry_date, back.get(e.id, ZERO))
    return out


def _was_ever_a_sale(organisation, inv):
    """True when the ledger holds a sale entry for this invoice (a real sale, not a proforma)."""
    from apps.accounting.models import JournalEntry
    from apps.sales import ledger
    return JournalEntry.objects.filter(
        organisation=organisation, source_type__in=ledger.SALE_SOURCES,
        source_ref__startswith=str(inv.id), is_deleted=False).exists()


def _output_lines(organisation, date_from, date_to):
    from apps.sales.models import Invoice, SaleItem, SaleReturnItem

    # Which invoices have their VAT due in this period, and on what date (see
    # _effective_vat_date). A VOIDED invoice stays in the month it was raised (a return already
    # filed must not change); the void is a negative line in the month it was done, the same
    # date the ledger mirror entry carries. A voided invoice that never reached the ledger
    # (no void entry) was never counted at all.
    voids_all = _void_entries(organisation)
    inv_qs = Invoice.objects.filter(
        organisation=organisation, status__in=OUTPUT_INVOICE_STATUSES + ["voided"],
    ).filter(
        Q(is_deferred=False, issue_date__gte=date_from, issue_date__lte=date_to)
        | Q(is_deferred=True)
    )
    vat_date, older = {}, set()
    for inv in inv_qs.only("id", "is_deferred", "issue_date", "fulfilled_at", "vat_timing", "status",
                           "organisation_id"):
        if inv.status == "voided" and not (
                str(inv.id) in voids_all and _was_ever_a_sale(organisation, inv)):
            # never booked (a proforma that only took a deposit, or a sale the ledger never got):
            # its deposits and the void show as their own lines, the invoice itself was never VAT
            continue
        d, is_older = _effective_vat_date(inv)
        if date_from <= d <= date_to:
            vat_date[inv.id] = d
            if is_older:
                older.add(inv.id)
    inv_qs = Invoice.objects.filter(organisation=organisation, id__in=list(vat_date))
    deposit_vat_by_invoice, deposit_lines = _deposit_lines(organisation, date_from, date_to)
    item_rows = SaleItem.objects.filter(
        organisation=organisation, invoice__in=inv_qs,
    ).values(
        "invoice_id", "invoice__invoice_number", "invoice__issue_date", "invoice__tax_amount",
        "invoice__shipping_tax_amount",
        "invoice__status", "invoice__customer__name", "invoice__customer__tin",
        "tax_amount", "tax_rate", "line_total",
        "product__is_taxable", "product__tax_class__treatment",
    )

    per_invoice = {}
    turnover = {k: ZERO for k in TURNOVER_LABELS}
    overdue_vat = ZERO
    for r in item_rows:
        tax = _d(r["tax_amount"])
        net = _d(r["line_total"]) - tax
        rate = _d(r["tax_rate"])
        bucket = _bucket(rate, tax, r["product__tax_class__treatment"], r["product__is_taxable"])
        turnover[bucket] += net
        if r["invoice__status"] == "overdue":
            overdue_vat += tax
        e = per_invoice.setdefault(r["invoice_id"], {
            "number": r["invoice__invoice_number"], "date": vat_date[r["invoice_id"]],
            "header_tax": _d(r["invoice__tax_amount"]),
            # delivery-charge VAT is in the invoice total but on no item line
            "vat": _d(r["invoice__shipping_tax_amount"]),
            "customer": r["invoice__customer__name"] or "", "tin": r["invoice__customer__tin"] or "",
            "net": ZERO, "rates": set(),
        })
        e["net"] += net
        e["vat"] += tax
        e["rates"].add(rate)

    lines, mismatches = [], []
    for inv_id, e in per_invoice.items():
        header_ok = e["vat"] == e["header_tax"]
        already = deposit_vat_by_invoice.get(inv_id, ZERO)   # booked earlier, on the deposit
        if not header_ok:
            mismatches.append({
                "invoice_number": e["number"], "line_vat": e["vat"], "invoice_vat": e["header_tax"],
                "difference": e["vat"] - e["header_tax"],
            })
        rate = next(iter(e["rates"])) if len(e["rates"]) == 1 else None
        reason = ("Line VAT differs from invoice total" if not header_ok
                  else ("Part of the VAT was already counted when the deposit was received" if already else ""))
        if inv_id in older:
            reason = (reason + " " if reason else "") + OLDER_INVOICE_NOTE
        lines.append(_line(
            kind="sale", direction="output", document_id=str(inv_id), source_ref=e["number"],
            date=e["date"], counterparty_name=e["customer"], counterparty_tin=e["tin"],
            net_amount=e["net"], vat_amount=e["vat"] - already, vat_rate=rate,
            reason=reason, older_invoice=inv_id in older,
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
            date=vat_date[inv.id], counterparty_name=inv.customer.name if inv.customer else "",
            counterparty_tin=(inv.customer.tin if inv.customer else "") or "",
            net_amount=_d(inv.total_amount) - tax, vat_amount=tax - deposit_vat_by_invoice.get(inv.id, ZERO),
            reason="Invoice has no lines; invoice total used",
        ))

    lines.extend(deposit_lines)

    # Voids done in this period: a negative line in the month of the void.
    void_in_period = {iid: v for iid, v in voids_all.items() if date_from <= v[0] <= date_to}
    if void_in_period:
        for inv in Invoice.objects.filter(
                organisation=organisation, id__in=list(void_in_period)).select_related("customer"):
            when, back = void_in_period[str(inv.id)]
            if back == ZERO:
                continue
            lines.append(_line(
                kind="sale_void", direction="output", document_id=str(inv.id), source_ref=inv.invoice_number,
                date=when, counterparty_name=inv.customer.name if inv.customer else "",
                counterparty_tin=(inv.customer.tin if inv.customer else "") or "",
                net_amount=ZERO, vat_amount=-back,
                reason="Invoice voided: its VAT is taken back in the month it was voided",
            ))
        # Only invoices that were counted as a sale in the first place give turnover back: a proforma
        # that only took a deposit never added any, so its void must not subtract any.
        counted_ids = [i.id for i in Invoice.objects.filter(
            organisation=organisation, id__in=list(void_in_period)) if _was_ever_a_sale(organisation, i)]
        for r in SaleItem.objects.filter(organisation=organisation, invoice_id__in=counted_ids).values(
                "tax_amount", "tax_rate", "line_total", "product__is_taxable", "product__tax_class__treatment"):
            tax = _d(r["tax_amount"])
            turnover[_bucket(_d(r["tax_rate"]), tax, r["product__tax_class__treatment"],
                             r["product__is_taxable"])] -= _d(r["line_total"]) - tax

    ret_rows = SaleReturnItem.objects.filter(
        organisation=organisation,
        sale_return__return_date__gte=date_from, sale_return__return_date__lte=date_to,
        sale_return__invoice__status__in=OUTPUT_INVOICE_STATUSES,
    ).values(
        "sale_return_id", "sale_return__return_number", "sale_return__return_date",
        "sale_return__invoice__customer__name", "sale_return__invoice__customer__tin",
        "tax_refund", "refund_amount", "original_item__tax_rate",
        "original_item__product__tax_class__treatment", "original_item__product__is_taxable",
    )
    per_return = {}
    for r in ret_rows:
        vat_back = _d(r["tax_refund"])
        net_back = _d(r["refund_amount"]) - vat_back
        # Turnover is net of returns, in the period of the return.
        turnover[_bucket(_d(r["original_item__tax_rate"]), vat_back,
                         r["original_item__product__tax_class__treatment"],
                         r["original_item__product__is_taxable"])] -= net_back
        e = per_return.setdefault(r["sale_return_id"], {
            "number": r["sale_return__return_number"], "date": r["sale_return__return_date"],
            "customer": r["sale_return__invoice__customer__name"] or "",
            "tin": r["sale_return__invoice__customer__tin"] or "", "net": ZERO, "vat": ZERO,
        })
        e["vat"] += vat_back
        e["net"] += net_back
    for rid, e in per_return.items():
        lines.append(_line(
            kind="sale_return", direction="output", document_id=str(rid), source_ref=e["number"],
            date=e["date"], counterparty_name=e["customer"], counterparty_tin=e["tin"],
            net_amount=-e["net"], vat_amount=-e["vat"], reason="Credit note / sales return",
        ))
    return lines, turnover, mismatches, overdue_vat


# ─── Input side ──────────────────────────────────────────────────────────────

def _verdict(registered, supplier, treatment, not_claimable_reason, reference=""):
    """(claimable, reason, confirmation) for one bill or return. Decided per bill."""
    if not registered:
        return False, "Your business is not marked as registered for VAT", "n/a"
    if not_claimable_reason:
        return False, "Not claimable: " + NOT_CLAIMABLE_LABELS.get(not_claimable_reason, not_claimable_reason), "user"
    if treatment == "exempt":
        return False, "Exempt purchase: VAT cannot be claimed back", "n/a"
    status = getattr(supplier, "vat_registered", "unknown") if supplier else "unknown"
    tin = ((supplier.tax_id if supplier else "") or "").strip()
    if status == "no":
        return False, "Supplier is not VAT registered", "confirmed"
    if status == "yes":
        return True, "", "confirmed"
    # Status not known. A TIN does not prove VAT registration; s.152 asks for a VAT invoice that
    # carries the supplier tax ID. So count it only when the bill shows VAT charged (it does, or it
    # would not be here), carries the supplier tax ID AND the supplier invoice reference. Otherwise
    # it is NOT counted until someone checks (it is on the needs-attention list). Marking the supplier
    # "yes" or "no" is the manual override.
    ref = (reference or "").strip()
    if tin and ref:
        return True, "Supplier VAT status not confirmed; counted because the bill shows VAT with the supplier tax ID and invoice reference", "unconfirmed"
    missing = " and ".join(x for x, ok in (("the supplier tax ID", bool(tin)), ("the supplier invoice reference", bool(ref))) if not ok)
    return False, "Not counted until checked: supplier VAT status not known and the bill lacks " + missing, "unconfirmed"


def _original_bill(organisation, purchase_return):
    from apps.bills.models import Bill
    po = purchase_return.purchase_order
    bill = Bill.objects.filter(organisation=organisation, source_purchase_order=po).select_related("supplier").first()
    if bill is None and po is not None:
        bill = Bill.objects.filter(organisation=organisation, reference=po.po_number).select_related("supplier").first()
    return bill


def _input_lines(organisation, date_from, date_to):
    from apps.bills.models import Bill
    from apps.purchases.models import PurchaseReturn

    registered = bool(organisation.charges_vat)
    base = Bill.objects.filter(
        organisation=organisation, issue_date__gte=date_from, issue_date__lte=date_to,
    ).exclude(tax_amount=0).select_related("supplier")
    bills = base.filter(status__in=INPUT_BILL_STATUSES)
    awaiting = base.filter(status=Bill.RECEIVED, source_purchase_order__isnull=False)

    lines, attention = [], []
    for b in bills:
        sup = b.supplier
        ok, why, conf = _verdict(registered, sup, b.vat_treatment, b.vat_not_claimable_reason, b.reference)
        line = _line(
            kind="bill", direction="input", document_id=str(b.id), source_ref=b.bill_number,
            date=b.issue_date, counterparty_name=sup.name if sup else "",
            counterparty_tin=(sup.tax_id if sup else "") or "", net_amount=_d(b.subtotal),
            vat_amount=_d(b.tax_amount), is_claimable=ok, reason=why,
        )
        line["confirmation"] = conf
        line["supplier_id"] = str(sup.id) if sup else ""
        lines.append(line)
        if registered and sup:
            unknown = sup.vat_registered == "unknown"
            no_tin = not (sup.tax_id or "").strip()
            no_ref = not (b.reference or "").strip()
            if (unknown or no_tin) and sup.vat_registered != "no" and (not ok or unknown):
                attention.append({
                    "bill_id": str(b.id), "bill_number": b.bill_number, "date": str(b.issue_date),
                    "supplier_id": str(sup.id), "supplier_name": sup.name,
                    "supplier_tin": sup.tax_id or "", "supplier_vat_registered": sup.vat_registered,
                    "vat_amount": _d(b.tax_amount),
                    "counted": bool(ok),
                    "reason": (("Not counted until checked: " if not ok else "") +
                               ("Supplier VAT status not known" if unknown else "") +
                               (" and " if unknown and no_tin else "") +
                               ("no TIN on record" if no_tin else "") +
                               (("; " if (unknown or no_tin) else "") + "no supplier invoice reference on the bill"
                                if (no_ref and unknown) else "")),
                })
    for b in awaiting:
        sup = b.supplier
        line = _line(
            kind="bill_awaiting_invoice", direction="input", document_id=str(b.id), source_ref=b.bill_number,
            date=b.issue_date, counterparty_name=sup.name if sup else "",
            counterparty_tin=(sup.tax_id if sup else "") or "", net_amount=_d(b.subtotal),
            vat_amount=_d(b.tax_amount), is_claimable=False, reason=AWAITING_INVOICE_LABEL,
        )
        line["confirmation"] = "n/a"
        lines.append(line)

    returns = PurchaseReturn.objects.filter(
        organisation=organisation, return_date__gte=date_from, return_date__lte=date_to,
    ).exclude(tax_amount=0).select_related("supplier", "purchase_order__supplier")
    for r in returns:
        orig = _original_bill(organisation, r)
        if orig is not None:
            sup = orig.supplier
            if orig.status in INPUT_BILL_STATUSES:
                ok, why, conf = _verdict(registered, sup, orig.vat_treatment, orig.vat_not_claimable_reason, orig.reference)
            else:
                ok, why, conf = False, "Original bill VAT was not claimed (bill status: %s)" % orig.status, "n/a"
            note = "Follows original bill %s" % orig.bill_number
        else:
            sup = r.supplier or r.purchase_order.supplier
            ok, why, conf = _verdict(registered, sup, "standard", "")
            note = "No linked bill; supplier status used"
        line = _line(
            kind="purchase_return", direction="input", document_id=str(r.id), source_ref=r.return_number,
            date=r.return_date, counterparty_name=sup.name if sup else "",
            counterparty_tin=(sup.tax_id if sup else "") or "", net_amount=-_d(r.subtotal),
            vat_amount=-_d(r.tax_amount), is_claimable=ok,
            reason=(why + "; " if why else "") + note,
        )
        line["confirmation"] = conf
        lines.append(line)
    return lines, attention


# ─── Manual adjustments ──────────────────────────────────────────────────────

def _manual_adjustments(organisation, date_from, date_to):
    """VATTransaction rows typed in by a person. Snapshots of real documents are
    skipped and listed (so nothing disappears silently)."""
    from django.db.models import Q
    from apps.bills.models import Bill
    from apps.sales.models import Invoice
    from apps.tax.models import VATTransaction

    rows = list(VATTransaction.objects.filter(
        organisation=organisation, period_end__gte=date_from, period_end__lte=date_to,
    ))
    if not rows:
        return [], []
    refs = {r.source_ref for r in rows if r.source_ref}
    known = set()
    if refs:
        known |= set(Invoice.all_objects.filter(organisation=organisation, invoice_number__in=refs)
                     .values_list("invoice_number", flat=True))
        known |= set(Invoice.all_objects.filter(organisation=organisation, firs_irn__in=refs)
                     .values_list("firs_irn", flat=True))
        known |= set(Bill.all_objects.filter(organisation=organisation, bill_number__in=refs)
                     .values_list("bill_number", flat=True))
        # Old sync rows stored the first 12 characters of the bill id: match them in SQL.
        prefixes = {x for x in refs if len(x) == 12 and x[8] == "-"}
        if prefixes:
            q = Q()
            for pf in prefixes:
                q |= Q(id__startswith=pf)
            known |= {str(i)[:12] for i in Bill.all_objects.filter(organisation=organisation).filter(q)
                      .values_list("id", flat=True)}
    out, ignored = [], []
    for r in rows:
        is_dup = bool(r.source_ref and r.source_ref in known)
        is_einv = (r.notes or "").startswith("E-Invoice")
        if is_dup or is_einv:
            ignored.append({
                "id": str(r.id), "direction": r.direction, "date": str(r.period_end),
                "source_ref": r.source_ref, "counterparty_name": r.counterparty_name,
                "vat_amount": _d(r.vat_amount),
                "reason": "Same document as invoice/bill %s, which is already counted live" % r.source_ref
                          if is_dup else "Created automatically for an e-invoice, which is already counted live",
            })
            continue
        out.append(_line(
            kind="manual", direction=r.direction, document_id=str(r.id), source_ref=r.source_ref,
            date=r.period_end, counterparty_name=r.counterparty_name, counterparty_tin=r.counterparty_tin,
            net_amount=_d(r.net_amount), vat_amount=_d(r.vat_amount), vat_rate=_d(r.vat_rate),
            is_claimable=bool(r.is_claimable),
            reason="Manual adjustment" + ("" if r.is_claimable or r.direction == "output" else " (not claimable)"),
            notes=r.notes or "",
        ))
    return out, ignored


# ─── Ledger reconciliation ───────────────────────────────────────────────────

def _ledger_reconciliation(organisation, date_from, date_to, output_vat, booked, recoverable,
                           irrecoverable, awaiting):
    """GL movement on the Output / Input VAT accounts for the same dates. Reported, never fixed."""
    from apps.accounting.models import Account, AccountMapping, JournalEntry, JournalLine
    from apps.accounting.services import AccountMappingService

    mapping = AccountMapping.objects.filter(organisation=organisation).first()
    out_acct = getattr(mapping, "vat_output_account", None) or AccountMappingService.suggest(organisation, "vat_output_account")
    # Every flow now posts Input VAT to the ONE mapped vat_input_account (1400 for new organisations).
    # An older organisation keeps its mapping until the repair_vat_input_account command is run, and
    # bill journals booked before this release went to 1400 whatever the mapping said, so 1400 is still
    # read as the "older" home when the mapping points somewhere else.
    mapped_in = getattr(mapping, "vat_input_account", None)
    if mapped_in is None:
        mapped_in = AccountMappingService.suggest(organisation, "vat_input_account")
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
                               "role": ("mapped vat_input_account (where all bill VAT is posted)" if acct == mapped_in
                                        else "1400 (bill journals booked before the single Input VAT account)")})
        gl_input += mv
    return {
        "gl_output_vat": gl_output,
        "gl_output_account": {"code": out_acct.code, "name": out_acct.name} if out_acct else None,
        "gl_input_vat": gl_input,
        "gl_input_accounts": input_accounts,
        "output_difference": output_vat - gl_output,
        "input_vat_booked_by_documents": booked,
        "input_difference": booked - gl_input,
        "input_vat_mapped_account": {"code": mapped_in.code, "name": mapped_in.name} if mapped_in else None,
        "input_vat_account_needs_repair": bool(mapped_in and by_code and mapped_in.id != by_code.id),
        "input_split": {
            "recoverable": recoverable,
            "irrecoverable": irrecoverable,
            "goods_received_awaiting_supplier_invoice": awaiting,
        },
        "note": (
            "Reported only; the ledger is not changed by this worksheet. Every flow now posts Input VAT to the ONE "
            "mapped Input VAT account (1400 for new organisations; an older organisation stays on its mapping "
            "until the repair_vat_input_account command is run, and while the mapping is not 1400 older bill "
            "journals on 1400 are added in). The ledger still posts ALL bill VAT "
            "to that account (including VAT that is not claimable and should be a cost) and posts VAT on goods "
            "received straight away, before the supplier invoice. So the ledger is compared with the VAT "
            "booked by documents (recoverable + not claimable + goods received awaiting invoice), not with "
            "the claimable figure. Any remaining difference is a real mismatch to investigate. Once "
            "not-claimable VAT is posted to cost, compare the ledger with the claimable figure instead."
        ),
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
    if date_to >= timezone.localdate():
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

    out_lines, turnover, mismatches, overdue_vat = _output_lines(organisation, date_from, date_to)
    in_lines, attention = _input_lines(organisation, date_from, date_to)
    manual, ignored = _manual_adjustments(organisation, date_from, date_to)

    sales_vat = sum((l["vat_amount"] for l in out_lines if l["kind"] in ("sale", "sale_void")), ZERO)
    returns_vat = -sum((l["vat_amount"] for l in out_lines if l["kind"] == "sale_return"), ZERO)
    manual_out = sum((l["vat_amount"] for l in manual if l["direction"] == "output"), ZERO)
    output_vat = sales_vat - returns_vat + manual_out

    bills = [l for l in in_lines if l["kind"] == "bill"]
    bills_vat_all = sum((l["vat_amount"] for l in bills), ZERO)
    bills_claimable = sum((l["vat_amount"] for l in bills if l["is_claimable"]), ZERO)
    rets = [l for l in in_lines if l["kind"] == "purchase_return"]
    rets_claimable = -sum((l["vat_amount"] for l in rets if l["is_claimable"]), ZERO)
    rets_other = -sum((l["vat_amount"] for l in rets if not l["is_claimable"]), ZERO)
    awaiting = sum((l["vat_amount"] for l in in_lines if l["kind"] == "bill_awaiting_invoice"), ZERO)
    manual_in = sum((l["vat_amount"] for l in manual if l["direction"] == "input" and l["is_claimable"]), ZERO)

    # Apportionment for businesses with taxable and exempt activity (100 = all of it).
    share = _d(getattr(organisation, "input_vat_share_percent", 100))
    claimable_before = bills_claimable - rets_claimable
    claimable_after = round_money(claimable_before * share / Decimal("100"))
    not_apportioned = claimable_before - claimable_after
    recoverable_input = claimable_after + manual_in
    irrecoverable = (bills_vat_all - bills_claimable) - rets_other + not_apportioned

    net = output_vat - recoverable_input
    registered = bool(organisation.charges_vat)

    warnings, notes = [], []
    if not registered:
        notes.append(UNREGISTERED_NOTE)
        if any(l["kind"] == "sale" and l["vat_amount"] > 0 for l in out_lines):
            warnings.append(CHARGED_BUT_OFF_NOTE)
    if any(l.get("older_invoice") for l in out_lines):
        warnings.append(OLDER_INVOICE_NOTE)
    if net < 0:
        notes.append(NEGATIVE_NOTE)
    if share != Decimal("100"):
        notes.append("Only %s%% of claimable input VAT is counted (your share used for taxable supplies); "
                     "the rest is in irrecoverable input VAT." % format(share.normalize(), "f"))
    if date_from < date(2026, 1, 1):
        notes.append(PRE_2026_NOTE)
    notes.append(BILL_TREATMENT_NOTE)

    all_lines = sorted(out_lines + in_lines + manual, key=lambda l: (str(l["date"]), l["kind"], l["source_ref"]))
    for l in all_lines:
        l["date"] = str(l["date"]) if l["date"] else None

    result = {
        "period_start": date_from,
        "period_end": date_to,
        "filing_due_date": filing_due_date(date_to),
        "due_note": DUE_NOTE,
        "vat_registered": registered,
        "registration_note": "" if registered else UNREGISTERED_NOTE,
        "warnings": warnings,
        "notes": notes,
        "output_vat_on_sales": sales_vat,
        "output_vat_returns": returns_vat,
        "output_vat_manual_adjustments": manual_out,
        "output_vat_on_overdue_invoices": overdue_vat,
        "output_vat": output_vat,
        "input_vat_recoverable": recoverable_input,
        "input_vat_irrecoverable": irrecoverable,
        "input_vat_manual_adjustments": manual_in,
        "input_vat_not_apportioned": not_apportioned,
        "input_vat_awaiting_supplier_invoice": awaiting,
        "input_vat_awaiting_supplier_invoice_label": AWAITING_INVOICE_LABEL,
        "net_vat_payable": net,
        "position": "payable" if net > 0 else ("refund_or_carry_forward" if net < 0 else "nil"),
        "position_label": ("Estimated VAT to pay for this period" if net > 0 else
                           ("Estimated refund or carry-forward for this period" if net < 0
                            else "Estimated nil for this period")),
        "labels": {
            "net_vat_payable": "Estimated net VAT for this period",
            "input_vat_recoverable": "Input VAT counted by Audity",
            "input_vat_irrecoverable": "Input VAT not counted by Audity",
        },
        "turnover": turnover,
        "turnover_labels": TURNOVER_LABELS,
        "invoice_vat_mismatches": mismatches,
        "superseded_snapshot_rows": len(ignored),
        "ignored_duplicates": ignored,
        "needs_attention": attention,
        "needs_attention_count": len(attention),
        "lines": all_lines,
        "worksheet_note": WORKSHEET_NOTE,
        "bill_treatment_note": BILL_TREATMENT_NOTE,
    }
    if with_reconciliation:
        booked = bills_vat_all - (rets_claimable + rets_other) + awaiting
        result["reconciliation"] = _ledger_reconciliation(
            organisation, date_from, date_to, output_vat, booked, recoverable_input, irrecoverable, awaiting)
    if with_previous_methods:
        result["previous_methods"] = _previous_methods(organisation, date_from, date_to, output_vat, recoverable_input, net)
    return result


def summary_view(vat: dict) -> dict:
    """The compute_vat result without the per-document lines: for report endpoints."""
    return {k: v for k, v in vat.items() if k != "lines"}


def why_it_changed(vat: dict) -> list:
    """Plain reasons the new figure can differ from the old screens, only those that apply."""
    why = []
    if vat["output_vat_on_overdue_invoices"] > 0:
        why.append("Invoices past due are now included.")
    if vat["output_vat_returns"] > 0:
        why.append("Credit notes are deducted in the month they are issued.")
    if vat["input_vat_irrecoverable"] > 0:
        why.append("Some input VAT is not counted: it needs a VAT registered business, a supplier that is VAT "
                   "registered (or a bill with the supplier tax ID and invoice reference), and a purchase that "
                   "is not exempt or marked not claimable.")
    if vat["input_vat_awaiting_supplier_invoice"] > 0:
        why.append("VAT on goods received but not yet invoiced by the supplier is not counted.")
    if vat["net_vat_payable"] < 0:
        why.append("A negative result is shown as a possible refund instead of zero.")
    return why


def comparison_table(organisation, today: Optional[date] = None, months: int = 12) -> list:
    """Closed calendar months of the last `months`: what the two old screens showed
    against the new figure. Words are 'different from', never 'owe' or 'overpaid'."""
    today = today or timezone.localdate()
    y, m = today.year, today.month
    out = []
    for _ in range(months):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        start, end = month_range(y, m)
        vat = compute_vat(organisation, start, end, with_reconciliation=False)
        prev = vat["previous_methods"]
        if prev is None:
            continue
        reports_net, tax_net, now = prev["reports_summary"]["net_vat_payable"], prev["tax_page"]["net_vat_payable"], vat["net_vat_payable"]
        differs = reports_net != now or tax_net != now
        out.append({
            "period_start": start, "period_end": end,
            "reports_page_showed": reports_net, "tax_page_showed": tax_net, "now": now,
            "difference_from_reports_page": now - reports_net, "difference_from_tax_page": now - tax_net,
            "different": differs,
            "why": why_it_changed(vat) if differs else [],
        })
    return out
