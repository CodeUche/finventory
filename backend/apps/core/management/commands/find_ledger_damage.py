"""
Read-only report of records damaged by the defects fixed on 2026-10-02.

The fixes stop new damage; they do not correct what is already stored. This
command finds, per organisation, every record the old code got wrong and says
what a repair would do. It writes nothing: every query is a read, and the whole
run sits inside a transaction that is rolled back.

    python manage.py find_ledger_damage                 # every active organisation
    python manage.py find_ledger_damage --org <uuid>    # one organisation
    python manage.py find_ledger_damage --json out.json # full detail as JSON

What it looks for (QA report reference in brackets):

  missed_credit_payments  [BUG-001] Customer payments recorded but never posted
                          (DR Cash/Bank, CR Accounts Receivable missing).
  missed_po_receipts      [BUG-004] Bills grown by later partial receipts whose
                          ledger entry (DR Inventory/Input VAT, CR AP) never posted.
  vat_left_unpaid         [BUG-010/028] Counter, Register or restaurant sales whose
                          only "amount due" is exactly their VAT: the customer paid
                          the VAT-free price the screen showed.
  vat_charged_twice       [BUG-011] Invoices whose total exceeds the sum of their
                          lines + shipping: VAT-inclusive lines taxed again.
  quote_billed_above_quote[BUG-012] Invoices converted from a quote for more than
                          the quoted total.
  till_missed_takings     [BUG-020] Closed tills whose cash sales were never linked,
                          so the posted over/short variance is wrong by that amount.
  depreciation_fractions  [BUG-029] Depreciation charges with fractions of a kobo.
"""

import json
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q, Sum

CENT = Decimal("0.01")


def _d(v):
    return Decimal(str(v or 0))


def _money(v):
    return str(_d(v).quantize(CENT))


class Command(BaseCommand):
    help = "Read-only report of ledger/invoice damage left by the defects fixed on 2026-10-02."

    def add_arguments(self, parser):
        parser.add_argument("--org", help="Only this organisation id.")
        parser.add_argument("--json", dest="json_path", help="Write full detail to this JSON file.")

    def handle(self, *args, **opts):
        from apps.core.tenant_context import organisation_context
        from apps.tenancy.models import Organisation

        orgs = Organisation.objects.filter(is_active=True)
        if opts.get("org"):
            orgs = orgs.filter(id=opts["org"])
        orgs = list(orgs.order_by("name"))

        report = []
        with transaction.atomic():
            for org in orgs:
                with organisation_context(org.id):
                    findings = self._scan(org)
                if any(f["items"] for f in findings.values()):
                    report.append({"organisation": str(org.id), "name": org.name, "findings": findings})
            transaction.set_rollback(True)  # belt and braces: nothing here writes

        self._print(report, len(orgs))
        if opts.get("json_path"):
            with open(opts["json_path"], "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=1, default=str)
            self.stdout.write(f"\nDetail written to {opts['json_path']}")

    # ── scans ────────────────────────────────────────────────────────────────
    def _scan(self, org):
        twice = self._vat_charged_twice(org)
        # An invoice charged VAT twice and part-paid at the shelf price also
        # "owes" its VAT; that is one problem with one repair, so list it once.
        unpaid = self._vat_left_unpaid(org, skip={i["invoice"] for i in twice["items"]})
        payments = self._missed_credit_payments(org)
        return {
            "missed_credit_payments": payments,
            "overpaid_payments": self._overpaid_payments(org),
            "missed_po_receipts": self._missed_po_receipts(org),
            "vat_left_unpaid": unpaid,
            "vat_charged_twice": twice,
            "quote_billed_above_quote": self._quote_billed_above_quote(org),
            "till_missed_takings": self._till_missed_takings(org),
            "depreciation_fractions": self._depreciation_fractions(org),
        }

    @staticmethod
    def _entry_amount(entry):
        return sum((_d(l.debit) for l in entry.lines.all()), Decimal("0"))

    def _missed_credit_payments(self, org):
        """A payment is posted if a credit_payment journal carries its own key
        (CRPAY-<txn id>, the fixed code) or, under the old customer-keyed
        CRPAY-<customer id>, the one entry that key ever held (the customer's
        first payment, matched on description and amount)."""
        from apps.accounting.models import JournalEntry
        from apps.credits.models import CreditTransaction

        entries = list(JournalEntry.objects.filter(organisation=org, source_type="credit_payment")
                       .prefetch_related("lines"))
        by_ref = {e.source_ref: e for e in entries}
        legacy_used = set()
        out = []
        # What each customer owed just before each transaction. The old code cut a
        # balance off at zero, so a payment larger than the debt was stored as if
        # only the debt had been paid. Only the part that was owed is evident from
        # the books; the excess may be a typing slip, so it is left to a person.
        owed_before = {}
        running = {}
        for t in (CreditTransaction.objects.filter(organisation=org).order_by("created_at", "id")
                  .only("id", "customer_id", "balance_after")):
            owed_before[t.id] = running.get(t.customer_id, Decimal("0"))
            running[t.customer_id] = _d(t.balance_after)

        payments = (CreditTransaction.objects
                    .filter(organisation=org, transaction_type=CreditTransaction.TransactionType.CREDIT)
                    .filter(Q(description__startswith="Credit payment") | Q(description__startswith="Payment received"))
                    .select_related("customer").order_by("created_at"))
        excess = []
        for txn in payments:
            if f"CRPAY-{txn.id}" in by_ref:
                continue
            legacy = by_ref.get(f"CRPAY-{txn.customer_id}")
            if (legacy and legacy.id not in legacy_used and legacy.description == txn.description
                    and self._entry_amount(legacy).quantize(CENT) == _d(txn.amount).quantize(CENT)):
                legacy_used.add(legacy.id)
                continue
            recorded = _d(txn.amount)
            fixable = min(recorded, max(owed_before.get(txn.id, Decimal("0")), Decimal("0")))
            name = txn.customer.name if txn.customer else ""
            if recorded - fixable > CENT:
                excess.append({"payment": str(txn.id), "customer": name,
                               "date": txn.created_at.date().isoformat(), "recorded": _money(recorded),
                               "owed_at_the_time": _money(fixable), "not_owed": _money(recorded - fixable),
                               "decision": "The payment was larger than the customer owed. Confirm whether the "
                                           "extra money really arrived before anything is posted for it."})
            if fixable > CENT:
                out.append({"payment": str(txn.id), "customer": name,
                            "date": txn.created_at.date().isoformat(), "amount": _money(fixable),
                            "recorded_amount": _money(recorded), "description": txn.description,
                            "repair": "post DR Cash/Bank, CR Accounts Receivable for the part that was owed"})
        self._payment_excess = excess
        return {"items": out, "total": _money(sum((_d(i["amount"]) for i in out), Decimal("0")))}

    def _overpaid_payments(self, org):
        """Payments larger than the debt they were recorded against (see above).
        Run after _missed_credit_payments, which collects them."""
        items = getattr(self, "_payment_excess", [])
        return {"items": items, "total": _money(sum((_d(i["not_owed"]) for i in items), Decimal("0")))}

    def _missed_po_receipts(self, org):
        from apps.accounting.models import JournalEntry
        from apps.bills.models import Bill

        out = []
        bills = (Bill.objects.filter(organisation=org, source_purchase_order__isnull=False)
                 .select_related("source_purchase_order", "supplier"))
        for bill in bills:
            po = bill.source_purchase_order
            if getattr(po, "billed_before_receipt", False):
                continue  # pre-billed POs post the bill at conversion; receipts only clear transit
            receipts = (JournalEntry.objects.filter(organisation=org, source_type="po_receipt")
                        .filter(Q(source_ref=str(po.id)) | Q(source_ref__startswith=f"{po.id}:"))
                        .prefetch_related("lines"))
            posted = sum((sum((_d(l.credit) for l in e.lines.all()), Decimal("0")) for e in receipts), Decimal("0"))
            # A bill approved on its own already booked its payable; counting only
            # receipts would book it a second time.
            approvals = (JournalEntry.objects.filter(organisation=org, source_type="bill_approved", source_ref=str(bill.id))
                         .prefetch_related("lines"))
            posted += sum((sum((_d(l.credit) for l in e.lines.all()), Decimal("0")) for e in approvals), Decimal("0"))
            missing = _d(bill.total_amount) - posted
            if missing > CENT:
                out.append({"bill": bill.bill_number, "purchase_order": po.po_number,
                            "supplier": bill.supplier.name if bill.supplier else "",
                            "bill_total": _money(bill.total_amount), "posted_to_ledger": _money(posted),
                            "missing": _money(missing),
                            "repair": "post DR Inventory + Input VAT, CR Accounts Payable for the unposted receipts"})
        return {"items": out, "total": _money(sum((_d(i["missing"]) for i in out), Decimal("0")))}

    def _vat_left_unpaid(self, org, skip=frozenset()):
        from apps.sales.models import Invoice

        out = []
        qs = Invoice.objects.filter(organisation=org, status=Invoice.Status.PARTIALLY_PAID).exclude(
            payment_method=Invoice.PaymentMethod.CREDIT)
        for inv in qs:
            if inv.invoice_number in skip:
                continue
            due, tax = _d(inv.amount_due), _d(inv.tax_amount)
            if tax > 0 and abs(due - tax) <= CENT:
                out.append({"invoice": inv.invoice_number, "date": str(inv.issue_date),
                            "customer": inv.customer.name if inv.customer_id else "Walk-in",
                            "total": _money(inv.total_amount), "paid": _money(inv.amount_paid),
                            "vat_shown_as_owed": _money(due),
                            "repair": "decision needed: write off the VAT 'owed' (treat price as VAT-inclusive) or collect it"})
        return {"items": out, "total": _money(sum((_d(i["vat_shown_as_owed"]) for i in out), Decimal("0")))}

    def _vat_charged_twice(self, org):
        from apps.sales.models import Invoice

        out = []
        for inv in Invoice.objects.filter(organisation=org).prefetch_related("items"):
            lines = sum((_d(i.line_total) for i in inv.items.all()), Decimal("0"))
            extra = _d(inv.total_amount) - lines - _d(inv.shipping_amount)
            if extra > CENT:
                out.append({"invoice": inv.invoice_number, "date": str(inv.issue_date), "status": inv.status,
                            "customer": inv.customer.name if inv.customer_id else "Walk-in",
                            "billed": _money(inv.total_amount), "should_be": _money(_d(inv.total_amount) - extra),
                            "overcharge": _money(extra),
                            "repair": "credit the overcharge (credit note or invoice correction) and reverse the overstated revenue"})
        return {"items": out, "total": _money(sum((_d(i["overcharge"]) for i in out), Decimal("0")))}

    def _quote_billed_above_quote(self, org):
        from apps.quotes.models import Quote

        out = []
        for q in Quote.objects.filter(organisation=org, converted_invoice__isnull=False).select_related("converted_invoice"):
            diff = _d(q.converted_invoice.total_amount) - _d(q.total_amount)
            if diff > CENT:
                out.append({"quote_id": str(q.id), "invoice": q.converted_invoice.invoice_number,
                            "quoted": _money(q.total_amount), "invoiced": _money(q.converted_invoice.total_amount),
                            "difference": _money(diff),
                            "repair": "decision needed: honour the quote (credit the difference) or keep the invoice"})
        return {"items": out, "total": _money(sum((_d(i["difference"]) for i in out), Decimal("0")))}

    def _till_missed_takings(self, org):
        from apps.pos.models import TillSession
        from apps.sales.models import SalePayment

        out = []
        for s in TillSession.objects.filter(organisation=org, status=TillSession.Status.CLOSED).exclude(closed_at=None):
            missed = (SalePayment.objects.filter(organisation=org, till_session__isnull=True, method="cash",
                                                 received_by=s.opened_by,
                                                 received_at__gte=s.opened_at, received_at__lte=s.closed_at)
                      .aggregate(t=Sum("amount"))["t"] or Decimal("0"))
            if missed > CENT:
                out.append({"till_session": str(s.id), "cashier": str(s.opened_by), "closed": s.closed_at.isoformat(),
                            "posted_variance": _money(s.cash_variance), "cash_sales_not_counted": _money(missed),
                            "true_variance": _money(_d(s.cash_variance) - missed),
                            "repair": "reverse the posted over/short entry and post the true variance"})
        return {"items": out, "total": _money(sum((_d(i["cash_sales_not_counted"]) for i in out), Decimal("0")))}

    def _depreciation_fractions(self, org):
        from apps.accounting.models import DepreciationEntry

        out = []
        for e in DepreciationEntry.objects.filter(asset__organisation=org).select_related("asset"):
            amt = _d(e.depreciation_amount)
            if amt != amt.quantize(CENT):
                out.append({"asset": e.asset.name, "period": f"{e.period_year}-{e.period_month:02d}",
                            "amount": str(amt), "fraction": str(amt - amt.quantize(CENT)),
                            "repair": "one rounding journal per asset (sub-kobo; cosmetic)"})
        return {"items": out, "total": str(sum((_d(i["fraction"]) for i in out), Decimal("0")))}

    # ── output ───────────────────────────────────────────────────────────────
    def _print(self, report, scanned):
        w = self.stdout.write
        w(f"Read-only scan of {scanned} organisation(s). Nothing was changed.\n")
        if not report:
            w("No damaged records found.")
            return
        for org in report:
            w(f"\n== {org['name']} ({org['organisation']})")
            for kind, f in org["findings"].items():
                if f["items"]:
                    w(f"  {kind:26} {len(f['items']):4} record(s)   total {f['total']}")
                    for item in f["items"][:5]:
                        w("     - " + ", ".join(f"{k}={v}" for k, v in item.items() if k != "repair"))
                    if len(f["items"]) > 5:
                        w(f"     … {len(f['items']) - 5} more (use --json for all)")
