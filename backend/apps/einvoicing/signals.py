"""
FIRS e-invoicing signals.

Wires the Invoice post_save signal to the request_irn Celery task.

Trigger conditions
==================
A FIRS submission is triggered when:
    1. The invoice status transitions TO a finalised state:
           confirmed, paid, partially_paid, credit, overdue
    2. The invoice is NOT a draft, proforma, voided, or returned.
    3. The org has a FirsConfig with is_enrolled = True (checked inside the task).
    4. The invoice does not already have firs_status = submitted/cleared/reported
       (idempotency double-check — also enforced inside EInvoicingService).

Payment status update
=====================
When an invoice transitions to PAID, update_payment_status_firs is also queued
to notify DigiTax so the payment record stays in sync.

Why separate tasks?
===================
Keeping submission and payment-status update as separate tasks means:
    - Payment update doesn't block the submission flow.
    - A payment-update failure doesn't roll back submission state.
"""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

# Invoice statuses that should trigger a FIRS submission
_SUBMIT_ON_STATUSES = frozenset(["confirmed", "paid", "partially_paid", "credit", "overdue"])

# Invoice firs_status values that mean we should NOT re-submit
# "bypassed" and "failed" are also terminal states for the signal guard
_ALREADY_SUBMITTED = frozenset(["submitted", "cleared", "reported", "bypassed", "failed"])


@receiver(post_save, sender="sales.SaleReturn")
def on_sale_return_save(sender, instance, created, **kwargs):
    """
    Trigger async credit note submission when a SaleReturn is created.

    Only fires on creation (not updates) and only when the original invoice
    has already been cleared by FIRS. The submit_credit_note_task itself
    handles the "not yet cleared" case gracefully.
    """
    if not created:
        return  # only trigger on new returns, not subsequent edits

    try:
        from apps.einvoicing.tasks import submit_credit_note_task

        submit_credit_note_task.apply_async(
            args=[str(instance.pk)],
            countdown=2,  # small delay so the outer transaction commits first
        )
        logger.debug(
            "on_sale_return_save: queued submit_credit_note for return %s",
            instance.return_number,
        )
    except Exception as exc:
        # Never let signal errors surface to the caller — the return was already
        # created; FIRS credit note can be retried later.
        logger.error(
            "on_sale_return_save: failed to queue credit note task for return %s: %s",
            getattr(instance, "return_number", instance.pk), exc,
        )


@receiver(post_save, sender="sales.Invoice")
def on_invoice_save(sender, instance, created, **kwargs):
    """
    Trigger async FIRS submission when an invoice reaches a finalised state.

    Uses .apply_async() (not .delay()) so we can pass the correct queue
    if the project later adds separate Celery queues per priority.

    The guard `_already_submitted` prevents double-submission when the
    invoice is updated for unrelated reasons (e.g. payment method change).
    """
    # Avoid triggering on proforma / draft / voided
    if instance.status not in _SUBMIT_ON_STATUSES:
        return

    # Skip if this invoice is already in-flight or completed with FIRS
    if instance.firs_status in _ALREADY_SUBMITTED:
        return

    # Import tasks here (inside the handler) to avoid import-time circular
    # dependencies between signals ↔ tasks ↔ services ↔ models.
    try:
        from apps.einvoicing.tasks import request_irn, update_payment_status_firs

        # Queue the IRN request (submission → DigiTax)
        request_irn.apply_async(
            args=[str(instance.pk)],
            # Small delay lets the outer transaction commit first so the task
            # finds the invoice with all relationships fully written.
            countdown=2,
        )
        logger.debug(
            "on_invoice_save: queued request_irn for invoice %s (status=%s)",
            instance.invoice_number, instance.status,
        )

        # Also notify DigiTax of the payment if the invoice is already paid
        if instance.status == "paid":
            update_payment_status_firs.apply_async(
                args=[str(instance.pk)],
                countdown=10,  # wait until IRN may have arrived (best-effort)
            )

    except Exception as exc:
        # Never let signal errors bubble up to the caller — the sale was already
        # created successfully; FIRS submission can be retried later.
        logger.error(
            "on_invoice_save: failed to queue FIRS task for invoice %s: %s",
            getattr(instance, "invoice_number", instance.pk), exc,
        )
