"""
FIRS E-Invoicing Celery tasks.

Task map
========
    request_irn               — Submit a single invoice to DigiTax async.
                                 Triggered by the post_save signal on Invoice.
    handle_irn_callback_task  — Process a webhook IRN callback asynchronously
                                 so the HTTP response to DigiTax is fast.
    report_b2c_invoices       — Nightly batch: report all BYPASSED B2C invoices.
    retry_failed_submissions  — Every 30 min: re-submit non-retryable-excluded
                                 FAILED submissions.
    update_payment_status_firs— Notify DigiTax when an invoice is paid.
    run_sandbox_batch         — Phase 7: run a pass or fail sandbox certification
                                 batch for a given organisation asynchronously.

Retry policy
============
    DigiTaxServerError (5xx, network)  → exponential backoff, max 5 retries.
    DigiTaxAuthError / ValidationError → do NOT retry (operator must fix data).
    All other exceptions               → log + mark FAILED, do NOT swallow.

Naming convention
=================
    All task names are prefixed "einvoicing." so they appear together in
    Celery monitoring tools (Flower, etc.).
"""

import logging

from celery import shared_task
from django.utils import timezone

from apps.core.tenant_context import for_each_organisation

logger = logging.getLogger(__name__)

# Exponential back-off: 1 min, 2 min, 4 min, 8 min, 16 min
_RETRY_DELAYS = [60, 120, 240, 480, 960]
_MAX_RETRIES = len(_RETRY_DELAYS)


# ─── Primary submission task ──────────────────────────────────────────────────

@shared_task(
    name="einvoicing.request_irn",
    bind=True,
    max_retries=_MAX_RETRIES,
    acks_late=True,           # only ACK after task completes — prevents lost tasks on worker crash
    reject_on_worker_lost=True,
)
def request_irn(self, invoice_id: str) -> dict:
    """
    Submit an invoice to DigiTax for FIRS IRN clearance.

    Called by the post_save signal on Invoice when the invoice transitions
    to a finalised status (confirmed, paid, credit). Runs the full
    EInvoicingService.submit_invoice() pipeline.

    Args:
        invoice_id: UUID string of the Invoice to submit.

    Returns:
        Dict with {"status": ..., "submission_ref": ...} on success.
        Celery retry on DigiTaxServerError; marks FAILED on auth/validation errors.
    """
    from apps.sales.models import Invoice
    from apps.einvoicing.services import (
        EInvoicingService,
        DigiTaxAuthError,
        DigiTaxValidationError,
        DigiTaxNotFoundError,
        DigiTaxServerError,
    )

    # Fetch invoice — if it's been deleted since the task was queued, log and exit
    try:
        invoice = Invoice.objects.select_related(
            "organisation", "customer"
        ).get(pk=invoice_id)
    except Invoice.DoesNotExist:
        logger.warning("request_irn: Invoice %s not found — task dropped", invoice_id)
        return {"status": "skipped", "reason": "invoice_not_found"}

    # Guard: only submit if the org is enrolled
    service = EInvoicingService.for_invoice(invoice)
    if service is None:
        logger.debug(
            "request_irn: org not enrolled for invoice %s — skipping",
            invoice.invoice_number,
        )
        return {"status": "skipped", "reason": "not_enrolled"}

    # Guard: skip if already submitted or cleared (idempotency double-check)
    if invoice.firs_status in ("submitted", "cleared", "reported"):
        logger.info(
            "request_irn: invoice %s already firs_status=%s — skipping",
            invoice.invoice_number, invoice.firs_status,
        )
        return {"status": "skipped", "reason": f"already_{invoice.firs_status}"}

    try:
        submission = service.submit_invoice(invoice)
        logger.info(
            "request_irn: invoice %s submission status=%s ref=%s",
            invoice.invoice_number, submission.status, submission.submission_ref,
        )
        return {
            "status": submission.status,
            "submission_ref": submission.submission_ref,
        }

    except (DigiTaxAuthError, DigiTaxValidationError, DigiTaxNotFoundError) as exc:
        # Non-retryable: submission already marked FAILED inside submit_invoice()
        logger.error(
            "request_irn: non-retryable failure for invoice %s: %s",
            invoice_id, exc.message,
        )
        return {"status": "failed", "error": exc.message}

    except DigiTaxServerError as exc:
        # Retryable: schedule next attempt with exponential back-off
        retry_num = self.request.retries  # 0-based attempt counter
        delay = _RETRY_DELAYS[min(retry_num, len(_RETRY_DELAYS) - 1)]
        logger.warning(
            "request_irn: server error for invoice %s (attempt %d/%d), retrying in %ds: %s",
            invoice_id, retry_num + 1, _MAX_RETRIES, delay, exc.message,
        )
        raise self.retry(exc=exc, countdown=delay)

    except Exception as exc:
        # Unexpected error — log fully, do not retry to avoid infinite loops
        logger.exception(
            "request_irn: unexpected error for invoice %s: %s", invoice_id, exc
        )
        raise


# ─── IRN callback handler task ────────────────────────────────────────────────

@shared_task(
    name="einvoicing.handle_irn_callback",
    bind=True,
    max_retries=3,
    acks_late=True,
)
def handle_irn_callback_task(
    self,
    submission_ref: str,
    irn: str,
    csid: str,
    firs_invoice_number: str,
    qr_code_b64: str = "",
) -> dict:
    """
    Process a DigiTax IRN webhook callback asynchronously.

    The WebhookView dispatches this task immediately after HMAC validation so
    that the HTTP response to DigiTax is fast (< 1s). All DB work happens here.

    Args:
        submission_ref    : DigiTax submission reference from webhook payload.
        irn               : FIRS Invoice Reference Number.
        csid              : Cryptographic Stamp Identifier.
        firs_invoice_number: FIRS-assigned invoice number.
        qr_code_b64       : Base64-encoded QR code image (may be empty).
    """
    from apps.einvoicing.models import FirsSubmission
    from apps.einvoicing.services import EInvoicingService

    # Resolve the submission to find which org's service to use
    try:
        submission = FirsSubmission.objects.select_related(
            "invoice__organisation__firs_config"
        ).get(submission_ref=submission_ref)
    except FirsSubmission.DoesNotExist:
        logger.warning(
            "handle_irn_callback: no FirsSubmission for ref=%s — skipped", submission_ref
        )
        return {"status": "skipped", "reason": "submission_not_found"}

    try:
        config = submission.invoice.organisation.firs_config
        service = EInvoicingService(config)
        service.handle_irn_callback(
            submission_ref=submission_ref,
            irn=irn,
            csid=csid,
            firs_invoice_number=firs_invoice_number,
            qr_code_b64=qr_code_b64,
        )
        return {"status": "cleared", "irn": irn}

    except Exception as exc:
        logger.exception(
            "handle_irn_callback: error processing ref=%s irn=%s: %s",
            submission_ref, irn, exc,
        )
        raise self.retry(exc=exc, countdown=30)


# ─── Nightly B2C batch reporter ───────────────────────────────────────────────

@shared_task(
    name="einvoicing.report_b2c_invoices",
    bind=True,
    max_retries=3,
)
def report_b2c_invoices(self) -> dict:
    """
    Nightly Celery beat task: batch-report all BYPASSED B2C invoices to DigiTax.

    FIRS allows B2C invoices to be reported in aggregate rather than cleared
    individually. This task collects all BYPASSED FirsSubmission rows from the
    last 24 hours and submits them via DigiTax POST /invoices (B2C mode).

    Runs at 23:00 daily (configured in CELERY_BEAT_SCHEDULE).
    Each org's submissions are reported independently so one org's API key
    failure doesn't block others.
    """
    from apps.einvoicing.models import FirsSubmission, FirsConfig
    from apps.einvoicing.services import EInvoicingService, DigiTaxError

    from apps.tenancy.models import Organisation

    stats = {"reported": 0, "failed": 0}

    # Get distinct orgs that have BYPASSED submissions
    org_ids = list(
        FirsSubmission.objects
        .filter(status=FirsSubmission.Status.BYPASSED)
        .values_list("organisation_id", flat=True)
        .distinct()
    )

    # Per-org RLS context (NEW-7): the submission queries below select_related
    # into sales_invoice, which is RLS-protected — under the SENTINEL that
    # INNER JOIN eliminates every row, so nothing was ever reported to FIRS.
    def _report_for_org(org):
        org_id = org.id
        try:
            config = FirsConfig.objects.select_related("organisation").get(
                organisation_id=org_id, is_enrolled=True
            )
        except FirsConfig.DoesNotExist:
            logger.warning(
                "report_b2c_invoices: org %s has BYPASSED submissions but no enrolled config",
                org_id,
            )
            return 0

        service = EInvoicingService(config)

        # Fetch all BYPASSED submissions for this org
        pending = FirsSubmission.objects.filter(
            organisation_id=org_id,
            status=FirsSubmission.Status.BYPASSED,
        ).select_related("invoice__customer", "invoice__organisation")

        for submission in pending:
            invoice = submission.invoice
            try:
                # Register parties and items (cached after first call)
                seller_id = service.ensure_seller_registered()
                buyer_id = service.ensure_buyer_registered(invoice.customer)
                item_id_map = service.ensure_items_registered(invoice)

                from apps.einvoicing.services import InvoiceJsonSerializer, _build_callback_url
                payload = InvoiceJsonSerializer.build_invoice_payload(
                    invoice, seller_id, buyer_id, item_id_map, _build_callback_url()
                )

                resp = service.client.create_invoice(payload)
                submission_ref = (
                    resp.get("id") or resp.get("submission_ref")
                    or resp.get("data", {}).get("id", "")
                )

                submission.status = FirsSubmission.Status.REPORTED
                submission.submission_ref = submission_ref
                submission.payload_json = payload
                submission.response_raw = resp
                submission.submitted_at = timezone.now()
                submission.save(update_fields=[
                    "status", "submission_ref", "payload_json",
                    "response_raw", "submitted_at", "updated_at",
                ])

                invoice.firs_status = "reported"
                invoice.save(update_fields=["firs_status", "updated_at"])
                stats["reported"] += 1

            except DigiTaxError as exc:
                logger.warning(
                    "report_b2c_invoices: failed for invoice %s: %s",
                    invoice.invoice_number, exc.message,
                )
                stats["failed"] += 1
            except Exception as exc:
                logger.exception(
                    "report_b2c_invoices: unexpected error for invoice %s: %s",
                    invoice.invoice_number, exc,
                )
                stats["failed"] += 1

        return stats["reported"]

    for_each_organisation(
        _report_for_org,
        task_name="einvoicing.report_b2c_invoices",
        queryset=Organisation.objects.filter(id__in=org_ids, is_active=True),
    )

    logger.info(
        "report_b2c_invoices: reported=%d failed=%d", stats["reported"], stats["failed"]
    )
    return {"reported": stats["reported"], "failed": stats["failed"]}


# ─── Retry failed submissions ─────────────────────────────────────────────────

@shared_task(
    name="einvoicing.retry_failed_submissions",
    bind=True,
    max_retries=1,  # this beat task itself shouldn't loop
)
def retry_failed_submissions(self) -> dict:
    """
    Every-30-min Celery beat task: re-queue FAILED submissions for retry.

    Only submissions with a DigiTaxServerError (HTTP 5xx) are retryable.
    Auth/validation failures (non-retryable) are excluded by checking
    attempt_count < MAX_RETRIES.

    Submits each eligible invoice as a new request_irn task so the existing
    retry back-off logic applies.
    """
    from apps.einvoicing.models import FirsSubmission

    # Per-org RLS context (NEW-7): select_related("invoice__…") INNER JOINs
    # sales_invoice, which is RLS-protected. Under the SENTINEL that join
    # eliminated every row, so no failed submission was ever retried.
    def _retry_for_org(org):
        # Only retry submissions that have failed fewer than MAX_RETRIES times
        eligible = FirsSubmission.objects.filter(
            organisation=org,
            status=FirsSubmission.Status.FAILED,
            attempt_count__lt=_MAX_RETRIES,
        ).select_related("invoice__organisation__firs_config")

        queued = 0
        for submission in eligible:
            invoice = submission.invoice

            # Skip if the org is no longer enrolled
            try:
                config = invoice.organisation.firs_config
                if not config.is_enrolled:
                    continue
            except Exception:
                continue

            # Increment attempt_count before re-queuing to prevent tight retry loops
            submission.attempt_count += 1
            submission.save(update_fields=["attempt_count", "updated_at"])

            # Queue the standard submission task
            request_irn.delay(str(invoice.pk))
            queued += 1

        return queued

    queued = for_each_organisation(
        _retry_for_org, task_name="einvoicing.retry_failed_submissions",
    )["processed"]

    logger.info("retry_failed_submissions: queued %d submissions for retry", queued)
    return {"queued": queued}


# ─── Payment status update ────────────────────────────────────────────────────

@shared_task(
    name="einvoicing.update_payment_status_firs",
    bind=True,
    max_retries=3,
    acks_late=True,
)
def update_payment_status_firs(self, invoice_id: str) -> dict:
    """
    Notify DigiTax that an invoice has been paid.

    Called by the Invoice post_save signal when status transitions to PAID.
    Only acts if the invoice has a cleared DigiTax submission with a submission_ref.

    Args:
        invoice_id: UUID string of the paid Invoice.
    """
    from apps.sales.models import Invoice
    from apps.einvoicing.models import FirsSubmission
    from apps.einvoicing.services import EInvoicingService, DigiTaxServerError

    try:
        invoice = Invoice.objects.select_related(
            "organisation__firs_config"
        ).get(pk=invoice_id)
    except Invoice.DoesNotExist:
        logger.warning(
            "update_payment_status_firs: Invoice %s not found", invoice_id
        )
        return {"status": "skipped", "reason": "invoice_not_found"}

    # Only notify if there is a cleared submission with a DigiTax reference
    submission = (
        FirsSubmission.objects
        .filter(
            invoice=invoice,
            status=FirsSubmission.Status.CLEARED,
        )
        .exclude(submission_ref="")
        .order_by("-cleared_at")
        .first()
    )

    if not submission:
        return {"status": "skipped", "reason": "no_cleared_submission"}

    service = EInvoicingService.for_invoice(invoice)
    if service is None:
        return {"status": "skipped", "reason": "not_enrolled"}

    try:
        service.client.update_payment_status(submission.submission_ref, "PAID")
        logger.info(
            "update_payment_status_firs: notified DigiTax for invoice %s",
            invoice.invoice_number,
        )
        return {"status": "notified", "submission_ref": submission.submission_ref}

    except DigiTaxServerError as exc:
        retry_num = self.request.retries
        delay = _RETRY_DELAYS[min(retry_num, len(_RETRY_DELAYS) - 1)]
        raise self.retry(exc=exc, countdown=delay)

    except Exception as exc:
        logger.exception(
            "update_payment_status_firs: error for invoice %s: %s", invoice_id, exc
        )
        raise


# ─── Credit note submission task ──────────────────────────────────────────────

@shared_task(
    name="einvoicing.submit_credit_note",
    bind=True,
    max_retries=_MAX_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
)
def submit_credit_note_task(self, sale_return_id: str) -> dict:
    """
    Submit a credit note to DigiTax for a SaleReturn.

    Triggered by the SaleReturn post_save signal (from signals.py).
    Only fires when the original invoice is already cleared (has an IRN).
    If the invoice is not yet cleared (IRN pending), this task skips — the
    signal/task will fire again if the IRN arrives later via webhook.

    Args:
        sale_return_id: UUID string of the SaleReturn to submit as a credit note.

    Returns:
        Dict with {"status": ..., "submission_ref": ...} on success.
    """
    from apps.sales.models import SaleReturn
    from apps.einvoicing.services import (
        EInvoicingService,
        DigiTaxAuthError,
        DigiTaxValidationError,
        DigiTaxNotFoundError,
        DigiTaxServerError,
    )

    # Fetch SaleReturn — if deleted since task was queued, exit cleanly
    try:
        sale_return = SaleReturn.objects.select_related(
            "invoice__organisation__firs_config",
            "invoice__customer",
        ).get(pk=sale_return_id)
    except SaleReturn.DoesNotExist:
        logger.warning("submit_credit_note: SaleReturn %s not found — task dropped", sale_return_id)
        return {"status": "skipped", "reason": "sale_return_not_found"}

    invoice = sale_return.invoice

    # Build service — returns None if org is not enrolled
    service = EInvoicingService.for_invoice(invoice)
    if service is None:
        logger.debug(
            "submit_credit_note: org not enrolled for invoice %s — skipping",
            invoice.invoice_number,
        )
        return {"status": "skipped", "reason": "not_enrolled"}

    try:
        submission = service.submit_credit_note(sale_return)
        if submission is None:
            # Original invoice not yet cleared — IRN not available
            return {"status": "skipped", "reason": "original_invoice_not_cleared"}

        logger.info(
            "submit_credit_note: return=%s submission status=%s ref=%s",
            sale_return.return_number, submission.status, submission.submission_ref,
        )
        return {
            "status": submission.status,
            "submission_ref": submission.submission_ref,
        }

    except (DigiTaxAuthError, DigiTaxValidationError, DigiTaxNotFoundError) as exc:
        # Non-retryable — submission already marked FAILED inside submit_credit_note()
        logger.error(
            "submit_credit_note: non-retryable failure for return %s: %s",
            sale_return_id, exc.message,
        )
        return {"status": "failed", "error": exc.message}

    except DigiTaxServerError as exc:
        retry_num = self.request.retries
        delay = _RETRY_DELAYS[min(retry_num, len(_RETRY_DELAYS) - 1)]
        logger.warning(
            "submit_credit_note: server error for return %s (attempt %d/%d), retrying in %ds: %s",
            sale_return_id, retry_num + 1, _MAX_RETRIES, delay, exc.message,
        )
        raise self.retry(exc=exc, countdown=delay)

    except Exception as exc:
        logger.exception(
            "submit_credit_note: unexpected error for return %s: %s", sale_return_id, exc
        )
        raise


# ─── Phase 7: Sandbox certification batch task ────────────────────────────────

@shared_task(
    name="einvoicing.run_sandbox_batch",
    bind=True,
    max_retries=0,  # sandbox batches are not automatically retried
    acks_late=True,
)
def run_sandbox_batch(self, org_id: str, mode: str, count: int = 50) -> dict:
    """
    Run a FIRS sandbox certification batch for the given organisation.

    Called asynchronously by SandboxRunView (POST /einvoicing/sandbox/run/).
    Can also be invoked directly from the management command.

    Args:
        org_id : UUID string of the Organisation.
        mode   : "pass" to submit valid invoices, "fail" to submit invalid ones.
        count  : Number of submissions to attempt (default 50).

    Returns:
        Dict with batch results from SandboxTestRunner.run_pass_batch() or
        run_fail_batch().
    """
    from apps.einvoicing.models import FirsConfig, SandboxTestRun
    from apps.einvoicing.sandbox_runner import SandboxTestRunner

    try:
        config = FirsConfig.objects.get(organisation_id=org_id)
    except FirsConfig.DoesNotExist:
        logger.error("run_sandbox_batch: no FirsConfig for org %s", org_id)
        return {"status": "error", "reason": "no_config"}

    if not config.use_sandbox:
        logger.error(
            "run_sandbox_batch: org %s is not in sandbox mode — refusing to run", org_id
        )
        return {"status": "error", "reason": "not_sandbox_mode"}

    runner = SandboxTestRunner(config)

    try:
        if mode == "pass":
            result = runner.run_pass_batch(count=count)
        elif mode == "fail":
            result = runner.run_fail_batch(count=count)
        else:
            return {"status": "error", "reason": f"unknown_mode: {mode}"}
    except Exception as exc:
        logger.exception("run_sandbox_batch: unexpected error for org %s: %s", org_id, exc)
        # Mark the most recent running SandboxTestRun for this org as errored
        SandboxTestRun.objects.filter(
            organisation_id=org_id,
            outcome=SandboxTestRun.Outcome.RUNNING,
        ).update(
            outcome=SandboxTestRun.Outcome.ERROR,
            error_detail=str(exc),
            finished_at=timezone.now(),
        )
        return {"status": "error", "reason": str(exc)}

    result["status"] = "complete"
    return result
