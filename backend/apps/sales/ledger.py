"""
Ledger postings for sales invoices.

One place that decides what a sale does to the books. Every function here
RAISES when the journal cannot be posted (locked period, missing account,
imbalance): the callers run inside a database transaction, so a failed journal
rolls the whole sale / payment / fulfilment back instead of leaving stock or
money moved with nothing in the ledger.

The entries an invoice can own (source_type, source_ref):

  sale           invoice.id    The sale itself. Fulfil-now: DR Cash/Bank (paid
                               at the till) + DR AR (rest) + DR Customer
                               Deposits (store credit used); CR Revenue, CR VAT,
                               DR COGS / CR Inventory. Fulfil-later: posted at
                               delivery (dated the delivery day): DR Customer
                               Deposits, CR Revenue (+ VAT if VAT is due on
                               delivery), COGS / Inventory.
  sale_deferred  invoice.id    Fulfil-later invoice at the moment it is raised:
                               DR Cash/Bank/AR/store credit as above, CR
                               Customer Deposits (the undelivered sale), CR VAT.
  sale_receipt   payment.id    A later payment on an invoice: DR Cash/Bank, CR AR.
  sale_deposit   payment.id    A payment on a PROFORMA (a deposit): DR Cash/Bank,
                               CR Customer Deposits (net) and CR VAT output.

Cash is therefore debited exactly once per payment, and Accounts Receivable
always equals what customers still owe.
"""

import logging
from decimal import Decimal

from apps.core.utils import round_money

from . import rules

logger = logging.getLogger(__name__)
Z = Decimal("0")

SALE_SOURCES = ("sale", "sale_deferred")
PAYMENT_SOURCES = ("sale_receipt", "sale_deposit", "sale_refund", "credit_payment")


# ── accounts ────────────────────────────────────────────────────────────────

def deposits_account(organisation):
    """Customer Deposits (2050): money held for goods not yet delivered, plus
    customers' store credit. Created if an older organisation lacks it."""
    from apps.accounting.models import Account, AccountType, normal_balance_for_type

    acct = Account.objects.filter(organisation=organisation, code="2050").first()
    if acct:
        return acct
    return Account.objects.create(
        organisation=organisation, code="2050", name="Customer Deposits",
        account_type=AccountType.LIABILITY, account_group="Liability",
        normal_balance=normal_balance_for_type(AccountType.LIABILITY), is_system=True,
    )


def _ar(organisation, invoice):
    from apps.accounting.services import AccountingService
    return AccountingService._resolve_party_account(
        organisation, invoice.customer, "receivable_account", "accounts_receivable", "1100")


def _post(organisation, description, entry_date, lines, user, ref, source_type, source_ref):
    from apps.accounting.services import AccountingService
    return AccountingService.post_journal_entry(
        organisation, description, entry_date, lines, user,
        ref=ref, source_type=source_type, source_ref=source_ref,
    )


# ── what an invoice already owns ────────────────────────────────────────────

def _payment_ids(invoice):
    from .models import SalePayment
    return [str(pk) for pk in SalePayment.objects.filter(invoice=invoice).values_list("id", flat=True)]


def invoice_entries(invoice):
    """Every journal entry that belongs to this invoice."""
    from django.db.models import Q
    from apps.accounting.models import JournalEntry

    return list(JournalEntry.objects.filter(
        Q(source_type__in=SALE_SOURCES, source_ref=str(invoice.id))
        | Q(source_type__in=PAYMENT_SOURCES, source_ref__in=_payment_ids(invoice)),
        organisation=invoice.organisation,
    ).order_by("created_at"))


def has_entry(invoice, source_type):
    from apps.accounting.models import JournalEntry
    return JournalEntry.objects.filter(
        organisation=invoice.organisation, source_type=source_type, source_ref=str(invoice.id),
    ).exists()


def is_new_style_deferred(invoice):
    """A fulfil-later invoice whose raising was already booked (sale_deferred)."""
    return bool(invoice.is_deferred) and has_entry(invoice, "sale_deferred")


def prior_deposits(invoice):
    """(gross, net, vat) of deposits already received against this invoice while
    it was still a proforma."""
    from apps.accounting.models import JournalEntry, JournalLine
    from apps.accounting.services import AccountMappingService

    ids = _payment_ids(invoice)
    entries = JournalEntry.objects.filter(
        organisation=invoice.organisation, source_type="sale_deposit", source_ref__in=ids)
    if not entries.exists():
        return Z, Z, Z
    dep = deposits_account(invoice.organisation)
    try:
        vat = AccountMappingService.resolve(invoice.organisation, "vat_output_account")
    except Exception:
        vat = None
    net = vat_amt = gross = Z
    for ln in JournalLine.objects.filter(journal_entry__in=entries):
        gross += ln.debit
        if ln.account_id == dep.id:
            net += ln.credit
        elif vat is not None and ln.account_id == vat.id:
            vat_amt += ln.credit
    return gross, net, vat_amt


def _payments_in_sale_entry(invoice):
    """Payments whose cash belongs in the sale entry itself: those folded in
    when the sale was created, plus any payment nobody has journalled yet (an
    invoice raised before these rules, or a sale entry being re-posted after a
    failure). A payment that already has its own receipt entry, or that the
    restaurant till journalled itself, is never counted twice. Credit-method
    invoices never fold payments in: their receipts always post separately."""
    from apps.accounting.models import JournalEntry
    from .models import SalePayment

    if invoice.payment_method == "credit":
        return []
    pays = list(SalePayment.objects.filter(invoice=invoice, amount__gt=0))
    posted = set(JournalEntry.objects.filter(
        organisation=invoice.organisation, source_type__in=PAYMENT_SOURCES,
        source_ref__in=[str(p.id) for p in pays],
    ).values_list("source_ref", flat=True))
    return [
        p for p in pays
        if p.in_sale_journal
        or (str(p.id) not in posted and not (p.reference or "").startswith("POS "))
    ]


# ── building blocks ─────────────────────────────────────────────────────────

def _credit_side(organisation, invoice, items, with_vat, vat_amount):
    """Revenue (+ shipping income, + VAT) credit lines, exactly as before: one
    revenue line by default, per-account buckets when a product overrides its
    Sales account."""
    from apps.accounting.services import AccountMappingService

    total = Decimal(str(invoice.total_amount))
    tax = Decimal(str(invoice.tax_amount or 0))
    shipping = Decimal(str(invoice.shipping_amount or 0))
    revenue_default = AccountMappingService.resolve(organisation, "revenue_account")
    shipping_acct = AccountMappingService.get_or_create_mapping(organisation).shipping_income_account \
        or revenue_default
    item_class_defaults = AccountMappingService.get_item_class_defaults(organisation)

    def class_default(product, role):
        row = item_class_defaults.get(product.product_type)
        return getattr(row, role, None) if row else None

    has_override = any(
        i.product.sales_account_id or i.product.cogs_account_id or i.product.wages_account_id
        or class_default(i.product, "sales_account") or class_default(i.product, "cogs_account")
        or class_default(i.product, "wages_account")
        for i in items
    )
    lines = []
    if not has_override:
        revenue = total - tax
        if shipping != Z and shipping_acct.id != revenue_default.id:
            lines.append((revenue_default, Z, revenue - shipping))
            lines.append((shipping_acct, Z, shipping))
        else:
            lines.append((revenue_default, Z, revenue))
    else:
        buckets = {}
        if shipping != Z:
            buckets[shipping_acct.id] = [shipping_acct, shipping]
        for i in items:
            amt = Decimal(str(i.line_total or 0)) - Decimal(str(i.tax_amount or 0))
            if amt == 0:
                continue
            acct = i.product.sales_account or class_default(i.product, "sales_account") or revenue_default
            slot = buckets.setdefault(acct.id, [acct, Z])
            slot[1] += amt
        for acct, amt in buckets.values():
            if amt != 0:
                lines.append((acct, Z, amt))
    if with_vat and vat_amount > Z:
        lines.append((AccountMappingService.resolve(organisation, "vat_output_account"), Z, vat_amount))
    return lines


def _cogs_lines(organisation, items):
    """COGS / Inventory lines. A missing account raises -- COGS used to be
    silently dropped, leaving profit overstated with no warning."""
    from apps.accounting.services import AccountMappingService

    lines = []
    cogs_total = sum((Decimal(str(i.cost_of_goods or 0)) for i in items), Z)
    if cogs_total <= Z:
        return lines
    item_class_defaults = AccountMappingService.get_item_class_defaults(organisation)

    def class_default(product, role):
        row = item_class_defaults.get(product.product_type)
        return getattr(row, role, None) if row else None

    has_override = any(
        i.product.sales_account_id or i.product.cogs_account_id or i.product.wages_account_id
        or class_default(i.product, "sales_account") or class_default(i.product, "cogs_account")
        or class_default(i.product, "wages_account")
        for i in items
    )
    cogs_default = AccountMappingService.resolve(organisation, "cogs_account")
    inv_default = AccountMappingService.resolve(organisation, "inventory_account")
    if not has_override:
        lines.append((cogs_default, cogs_total, Z))
        lines.append((inv_default, Z, cogs_total))
        return lines
    debit_buckets, credit_buckets = {}, {}
    for i in items:
        amt = Decimal(str(i.cost_of_goods or 0))
        if amt == 0:
            continue
        product = i.product
        if product.product_type == "service" and (
            product.wages_account_id or class_default(product, "wages_account")
        ):
            debit_acct = product.wages_account or class_default(product, "wages_account")
        else:
            debit_acct = product.cogs_account or class_default(product, "cogs_account") or cogs_default
        credit_acct = product.inventory_account or class_default(product, "inventory_account") or inv_default
        debit_buckets.setdefault(debit_acct.id, [debit_acct, Z])[1] += amt
        credit_buckets.setdefault(credit_acct.id, [credit_acct, Z])[1] += amt
    for acct, amt in debit_buckets.values():
        if amt != 0:
            lines.append((acct, amt, Z))
    for acct, amt in credit_buckets.values():
        if amt != 0:
            lines.append((acct, Z, amt))
    return lines


def _items(invoice):
    return list(invoice.items.select_related(
        "product__sales_account", "product__cogs_account", "product__wages_account",
    ).all())


# ── postings ────────────────────────────────────────────────────────────────

def post_sale_entry(organisation, invoice, user=None, mode="full", entry_date=None):
    """
    mode "full"        the sale is delivered now (or an old fulfil-later invoice
                       being delivered): the whole sale in one entry.
    mode "deferred"    a fulfil-later invoice being raised: nothing is earned yet.
    mode "fulfilment"  delivery of an invoice raised in "deferred" mode.
    """
    from apps.accounting.services import AccountingService

    total = Decimal(str(invoice.total_amount))
    tax = Decimal(str(invoice.tax_amount or 0))
    credit_used = Decimal(str(invoice.credit_applied or 0))
    items = _items(invoice)
    vat_now = rules.vat_due_at_invoice()
    deposits = deposits_account(organisation)
    lines = []

    if mode == "fulfilment":
        lines.append((deposits, total - (tax if vat_now else Z), Z))
        lines += _credit_side(organisation, invoice, items, with_vat=not vat_now, vat_amount=tax)
        lines += _cogs_lines(organisation, items)
        date = entry_date or invoice.issue_date
        return _post(organisation, f"Delivery {invoice.invoice_number}", date, lines, user,
                     invoice.invoice_number, "sale", str(invoice.id))

    prior_gross, prior_net, prior_vat = prior_deposits(invoice)

    # debit side: what was paid at the till, what is owed, store credit used
    paid_by_account = {}
    paid_total = Z
    for p in _payments_in_sale_entry(invoice):
        acct = AccountingService.tender_asset_account(organisation, p.method)
        slot = paid_by_account.setdefault(acct.id, [acct, Z])
        slot[1] += Decimal(str(p.amount))
        paid_total += Decimal(str(p.amount))
    for acct, amt in paid_by_account.values():
        lines.append((acct, amt, Z))
    if credit_used > Z:
        lines.append((deposits, credit_used, Z))
    ar_amount = total - credit_used - paid_total - prior_gross
    if ar_amount > Z:
        lines.append((_ar(organisation, invoice), ar_amount, Z))

    if mode == "deferred":
        held = total - (tax if vat_now else Z) - prior_net
        lines.append((deposits, Z, held))
        if vat_now and tax - prior_vat > Z:
            from apps.accounting.services import AccountMappingService
            lines.append((AccountMappingService.resolve(organisation, "vat_output_account"),
                          Z, tax - prior_vat))
        return _post(organisation, f"Sale (to be delivered) {invoice.invoice_number}",
                     entry_date or invoice.issue_date, lines, user,
                     invoice.invoice_number, "sale_deferred", str(invoice.id))

    # mode == "full"
    if prior_net > Z:
        lines.append((deposits, prior_net, Z))          # deposit becomes revenue
    lines += _credit_side(organisation, invoice, items, with_vat=True, vat_amount=tax - prior_vat)
    lines += _cogs_lines(organisation, items)
    return _post(organisation, f"Sale {invoice.invoice_number}", entry_date or invoice.issue_date,
                 lines, user, invoice.invoice_number, "sale", str(invoice.id))


def post_receipt_entry(organisation, invoice, payment, user=None, entry_date=None):
    """A payment received after the sale was raised (or a deposit on a proforma)."""
    from apps.accounting.services import AccountingService, AccountMappingService
    from .models import Invoice

    amount = Decimal(str(payment.amount))
    tender = AccountingService.tender_asset_account(organisation, payment.method)
    date = entry_date or invoice.issue_date
    if invoice.status == Invoice.Status.PROFORMA:
        total = Decimal(str(invoice.total_amount))
        tax = Decimal(str(invoice.tax_amount or 0))
        vat_part = round_money(amount * tax / total) if (rules.vat_due_at_invoice() and total > Z) else Z
        lines = [(tender, amount, Z), (deposits_account(organisation), Z, amount - vat_part)]
        if vat_part > Z:
            lines.append((AccountMappingService.resolve(organisation, "vat_output_account"), Z, vat_part))
        return _post(organisation, f"Deposit {invoice.invoice_number}", date, lines, user,
                     invoice.invoice_number, "sale_deposit", str(payment.id))
    lines = [(tender, amount, Z), (_ar(organisation, invoice), Z, amount)]
    # Credit-method invoices keep the entry type the credit ledger has always
    # used for a credit customer paying; every other invoice uses sale_receipt.
    source_type = "credit_payment" if invoice.payment_method == "credit" else "sale_receipt"
    return _post(organisation, f"Payment {invoice.invoice_number}", date, lines, user,
                 invoice.invoice_number, source_type, str(payment.id))


def reverse_invoice_entries(invoice, actor):
    """Reverse every entry the invoice owns (once each). Returns how many."""
    from apps.accounting.models import JournalEntry
    from apps.accounting.services import AccountingService

    count = 0
    for entry in invoice_entries(invoice):
        if JournalEntry.objects.filter(
            organisation=invoice.organisation, source_type="reversal", source_ref=str(entry.id),
        ).exists():
            continue
        AccountingService.reverse_journal_entry(entry, actor)
        count += 1
    return count


def void_invoice_entry(invoice, actor):
    """Undo everything the invoice posted with ONE mirror entry (source_type
    'invoice_void'): every line of every entry the invoice owns, debit and
    credit swapped, so a discount, VAT-inclusive price, delivery charge, store
    credit or deposit reverses exactly -- nothing is recomputed. Idempotent."""
    from django.utils import timezone

    lines = []
    for entry in invoice_entries(invoice):
        for ln in entry.lines.select_related("account").all():
            lines.append((ln.account, Decimal(str(ln.credit)), Decimal(str(ln.debit))))
    if not lines:
        return None
    return _post(
        invoice.organisation, f"Void invoice {invoice.invoice_number}", timezone.now().date(),
        lines, actor, f"VOID-{invoice.invoice_number}", "invoice_void", str(invoice.id),
    )
