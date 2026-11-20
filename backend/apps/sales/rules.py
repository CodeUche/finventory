"""
Named switches for the sales tax / posting rules that still need a licensed
tax adviser's sign-off. Each one defaults to the rule the tax-domain expert
recommended (Nigeria Tax Act 2025, s.146, 148, 152) and can be flipped from
Django settings (SALES_* names below) without a code change.

Plain-words list:

VAT_TIMING
    "invoice"  (default) VAT is owed when the invoice is issued or money is
               received, whichever is first -- NOT when the goods are
               delivered. A fulfil-later invoice therefore books its VAT the
               day it is raised.
    "delivery" VAT is booked only when the goods are handed over.

DELIVERY_VAT_FOLLOWS_GOODS (default False -- recommended value is True)
    The delivery charge carries the same VAT rate as the goods it travels
    with: 7.5% on taxable lines, 0% on zero-rated or exempt lines, and a
    mixed basket is split between its lines in proportion to their value.
    False = delivery carries no VAT (the old behaviour). Ships OFF because
    turning it on changes the total the customer is quoted for every sale that
    has a delivery charge, which the page, the edit-invoice screen and the online
    store must all show identically; flip it once they do.

SURCHARGE_TAXED_LIKE_DISCOUNT (default True)
    A positive whole-invoice adjustment (surcharge) is spread across the
    lines BEFORE VAT, exactly like a discount in reverse, so it carries VAT.
    False = a surcharge is rejected (only discounts accepted).

NOT BUILT (no control on the page for them yet, listed so nobody assumes):
    * refundable security deposit held outside VAT until applied
    * discount after supply as a credit note referencing the original invoice
      (the existing sales-return credit note already covers returns)
"""

from django.conf import settings

VAT_TIMING_INVOICE = "invoice"
VAT_TIMING_DELIVERY = "delivery"


def vat_timing() -> str:
    value = getattr(settings, "SALES_VAT_TIMING", VAT_TIMING_INVOICE)
    return value if value in (VAT_TIMING_INVOICE, VAT_TIMING_DELIVERY) else VAT_TIMING_INVOICE


def vat_due_at_invoice() -> bool:
    return vat_timing() == VAT_TIMING_INVOICE


def delivery_vat_follows_goods() -> bool:
    return bool(getattr(settings, "SALES_DELIVERY_VAT_FOLLOWS_GOODS", False))


def surcharge_taxed_like_discount() -> bool:
    return bool(getattr(settings, "SALES_SURCHARGE_TAXED_LIKE_DISCOUNT", True))
