"""
FIRS Sandbox Certification Test Runner.

FIRS / DigiTax requires every organisation to complete at least:
    50 pass tests — valid invoices that DigiTax sandbox accepts
    50 fail tests — invalid payloads that DigiTax sandbox rejects

before production credentials are granted.

This module provides SandboxTestRunner, which:
  - Generates synthetic invoice payloads (no real Invoice records needed)
  - Submits them directly via DigiTaxApiClient against the sandbox endpoint
  - Records each attempt as a FirsSubmission with is_sandbox_test=True
  - Creates a SandboxTestRun record to track the batch

Usage
=====
    from apps.einvoicing.sandbox_runner import SandboxTestRunner

    runner = SandboxTestRunner(firs_config)
    result = runner.run_pass_batch(count=50)
    # {"submitted": 48, "errors": 2, "run_id": "<uuid>"}

    result = runner.run_fail_batch(count=50)
    # {"triggered_errors": 50, "unexpected_passes": 0, "run_id": "<uuid>"}

Safety
======
    - Will raise ValueError if use_sandbox is False (guards against accidentally
      running certification submissions against the live production endpoint).
    - All FirsSubmission rows created here have is_sandbox_test=True and
      invoice=None — they will never appear in real invoice reporting.
"""

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.einvoicing.models import FirsConfig, FirsSubmission, SandboxTestRun
from apps.einvoicing.services import DigiTaxApiClient, DigiTaxError

logger = logging.getLogger(__name__)

# FIRS-required certification thresholds
REQUIRED_PASS_COUNT = 50
REQUIRED_FAIL_COUNT = 50


# ─── Synthetic payload generators ─────────────────────────────────────────────

def _pass_payload(config: FirsConfig, index: int) -> dict:
    """
    Build a valid invoice payload that DigiTax sandbox should accept.

    Uses the org's TIN and business_name.  HSN code 998314 (IT consulting) is
    accepted universally by DigiTax sandbox.  Each payload gets a unique
    trader_invoice_number so duplicate-submission checks don't trigger.
    """
    ref = f"SANDBOX-PASS-{index:04d}-{uuid.uuid4().hex[:6].upper()}"
    today = date.today()
    # Vary amount so each submission looks distinct to DigiTax
    amount = Decimal("1000.00") + Decimal(str(index * 10))
    tax_amount = (amount * Decimal("0.075")).quantize(Decimal("0.01"))
    grand_total = (amount + tax_amount).quantize(Decimal("0.01"))

    return {
        "trader_invoice_number": ref,
        "invoice_date": today.isoformat(),
        "invoice_due_date": (today + timedelta(days=30)).isoformat(),
        "supply_type": "B2B",
        "currency": "NGN",
        "exchange_rate": 1.0,
        "seller": {
            "tin":           config.tin or "12345678-0001",
            "business_name": config.business_name or "Test Organisation",
            "address":       "1 Test Street, Lagos",
            "phone":         "+2340000000000",
        },
        "buyer": {
            "tin":           "98765432-0001",
            "business_name": "FIRS Sandbox Test Buyer",
            "address":       "2 Buyer Avenue, Abuja",
        },
        "line_items": [
            {
                "item_id":     f"ITEM-{ref}",
                "description": f"Sandbox Test Service #{index}",
                "hsn_code":    "998314",   # IT consulting — universally accepted
                "quantity":    1,
                "unit_price":  float(amount),
                "discount":    0,
                "tax_rate":    7.5,
                "total":       float(grand_total),
            }
        ],
        "subtotal":       float(amount),
        "discount_total": 0,
        "tax_total":      float(tax_amount),
        "grand_total":    float(grand_total),
        "payment_method": "cash",
        "callback_url":   "https://audity.app/api/v1/einvoicing/webhook/",
        # Marker fields (informational; not part of FIRS spec)
        "_is_sandbox_test": True,
        "_test_type":       "pass",
        "_test_index":      index,
    }


def _fail_payload(index: int) -> dict:
    """
    Build an intentionally invalid payload that DigiTax sandbox should reject.

    Rotates through 5 distinct failure modes so the 50-fail batch exercises
    multiple validation paths rather than repeating one error type.

    Failure modes (by index % 5):
        0 — Empty seller TIN (required field)
        1 — Zero grand total (FIRS rejects zero-value invoices)
        2 — Invalid HSN code (non-existent code)
        3 — Invoice date far in the future (outside allowed window)
        4 — Empty line_items list (at least one item required)
    """
    ref = f"SANDBOX-FAIL-{index:04d}-{uuid.uuid4().hex[:6].upper()}"
    today = date.today()
    mode = index % 5

    base = {
        "trader_invoice_number": ref,
        "invoice_date": today.isoformat(),
        "supply_type": "B2B",
        "currency": "NGN",
        "exchange_rate": 1.0,
        "callback_url": "https://audity.app/api/v1/einvoicing/webhook/",
        "_is_sandbox_test": True,
        "_test_type":   "fail",
        "_test_index":  index,
        "_fail_mode":   mode,
    }

    if mode == 0:
        # Missing / empty seller TIN
        base.update({
            "seller": {"tin": "", "business_name": "Missing TIN Co", "address": "Lagos"},
            "buyer":  {"tin": "98765432-0001", "business_name": "Buyer"},
            "line_items": [{"item_id": "X", "description": "Test", "hsn_code": "998314",
                            "quantity": 1, "unit_price": 100, "tax_rate": 7.5, "total": 107.5}],
            "subtotal": 100, "tax_total": 7.5, "grand_total": 107.5,
        })
    elif mode == 1:
        # Zero-value invoice
        base.update({
            "seller": {"tin": "12345678-0001", "business_name": "Test Co", "address": "Lagos"},
            "buyer":  {"tin": "98765432-0001", "business_name": "Buyer"},
            "line_items": [{"item_id": "X", "description": "Free", "hsn_code": "998314",
                            "quantity": 0, "unit_price": 0, "tax_rate": 7.5, "total": 0}],
            "subtotal": 0, "tax_total": 0, "grand_total": 0,
        })
    elif mode == 2:
        # Invalid HSN code
        base.update({
            "seller": {"tin": "12345678-0001", "business_name": "Test Co", "address": "Lagos"},
            "buyer":  {"tin": "98765432-0001", "business_name": "Buyer"},
            "line_items": [{"item_id": "X", "description": "Test", "hsn_code": "INVALID_HSN_XXXXX",
                            "quantity": 1, "unit_price": 100, "tax_rate": 7.5, "total": 107.5}],
            "subtotal": 100, "tax_total": 7.5, "grand_total": 107.5,
        })
    elif mode == 3:
        # Far-future invoice date (outside the allowed submission window)
        base.update({
            "invoice_date": (today + timedelta(days=365)).isoformat(),
            "seller": {"tin": "12345678-0001", "business_name": "Test Co", "address": "Lagos"},
            "buyer":  {"tin": "98765432-0001", "business_name": "Buyer"},
            "line_items": [{"item_id": "X", "description": "Test", "hsn_code": "998314",
                            "quantity": 1, "unit_price": 100, "tax_rate": 7.5, "total": 107.5}],
            "subtotal": 100, "tax_total": 7.5, "grand_total": 107.5,
        })
    else:
        # Empty line_items
        base.update({
            "seller": {"tin": "12345678-0001", "business_name": "Test Co", "address": "Lagos"},
            "buyer":  {"tin": "98765432-0001", "business_name": "Buyer"},
            "line_items": [],
            "subtotal": 0, "tax_total": 0, "grand_total": 0,
        })

    return base


# ─── Runner ───────────────────────────────────────────────────────────────────

class SandboxTestRunner:
    """
    Runs FIRS sandbox certification batches for an organisation.

    Instantiate with an enrolled FirsConfig that has use_sandbox=True.
    Call run_pass_batch() and run_fail_batch() to generate the required 50+50
    test submissions against the DigiTax sandbox endpoint.
    """

    def __init__(self, config: FirsConfig):
        if not config.use_sandbox:
            raise ValueError(
                "SandboxTestRunner must only run in sandbox mode. "
                "Set FirsConfig.use_sandbox = True before running certification tests."
            )
        if not config.app_api_key:
            raise ValueError(
                "No DigiTax API key configured. "
                "Set FirsConfig.app_api_key before running sandbox tests."
            )
        self.config = config
        self.client = DigiTaxApiClient(
            api_key=config.app_api_key,
            base_url=config.app_base_url,
        )

    # ── Progress helpers ──────────────────────────────────────────────────────

    @classmethod
    def get_progress(cls, config: FirsConfig) -> dict:
        """
        Return current sandbox certification progress for an org.

        Pass count: sandbox FirsSubmissions with status submitted/cleared/reported/bypassed
        Fail count: sandbox FirsSubmissions with status failed

        Returns a dict ready to serialise to the frontend.
        """
        from django.db.models import Count, Q

        org = config.organisation
        qs = FirsSubmission.objects.filter(
            organisation=org,
            is_sandbox_test=True,
        )
        pass_count = qs.filter(
            status__in=[
                FirsSubmission.Status.SUBMITTED,
                FirsSubmission.Status.CLEARED,
                FirsSubmission.Status.REPORTED,
                FirsSubmission.Status.BYPASSED,
            ]
        ).count()
        fail_count = qs.filter(status=FirsSubmission.Status.FAILED).count()
        pending_count = qs.filter(status=FirsSubmission.Status.PENDING).count()

        recent_runs = SandboxTestRun.objects.filter(
            organisation=org
        ).order_by("-created_at")[:5].values(
            "id", "mode", "outcome", "completed_count", "target_count", "started_at"
        )

        return {
            "pass_count":      pass_count,
            "fail_count":      fail_count,
            "pending_count":   pending_count,
            "required_passes": REQUIRED_PASS_COUNT,
            "required_fails":  REQUIRED_FAIL_COUNT,
            "passes_complete": pass_count >= REQUIRED_PASS_COUNT,
            "fails_complete":  fail_count >= REQUIRED_FAIL_COUNT,
            "certification_ready": (
                pass_count >= REQUIRED_PASS_COUNT and fail_count >= REQUIRED_FAIL_COUNT
            ),
            "recent_runs": list(recent_runs),
        }

    # ── Pass batch ────────────────────────────────────────────────────────────

    def run_pass_batch(self, count: int = REQUIRED_PASS_COUNT) -> dict:
        """
        Submit `count` valid invoices to the DigiTax sandbox.

        Each submission is stored as a FirsSubmission with is_sandbox_test=True.
        Submissions that DigiTax accepts get status SUBMITTED; unexpected
        rejections are stored as FAILED.

        Returns:
            {"submitted": N, "errors": N, "run_id": "<uuid>"}
        """
        run = SandboxTestRun.objects.create(
            organisation=self.config.organisation,
            mode=SandboxTestRun.Mode.PASS,
            target_count=count,
        )
        # Offset index so each invoice_number in this batch is unique even across
        # multiple batch runs for the same org
        start_offset = FirsSubmission.objects.filter(
            organisation=self.config.organisation,
            is_sandbox_test=True,
        ).count()

        submitted = errors = 0

        for i in range(count):
            payload = _pass_payload(self.config, start_offset + i + 1)
            sub = FirsSubmission(
                organisation=self.config.organisation,
                invoice=None,          # no real invoice — sandbox test only
                is_sandbox_test=True,
                payload_json=payload,
                status=FirsSubmission.Status.PENDING,
            )
            try:
                resp = self.client.create_invoice(payload)
                sub_ref = (
                    resp.get("id") or resp.get("submission_ref")
                    or resp.get("data", {}).get("id", "")
                )
                sub.submission_ref = sub_ref or ""
                sub.response_raw = resp
                sub.status = FirsSubmission.Status.SUBMITTED
                sub.submitted_at = timezone.now()
                submitted += 1

            except DigiTaxError as exc:
                # Unexpected rejection of a valid payload — record and continue
                sub.status = FirsSubmission.Status.FAILED
                sub.error_detail = exc.message
                sub.response_raw = getattr(exc, "response", {}) or {}
                errors += 1
                logger.warning(
                    "sandbox pass test #%d/%d failed unexpectedly: %s",
                    i + 1, count, exc.message,
                )
            sub.save()

        run.completed_count = submitted + errors
        run.outcome = SandboxTestRun.Outcome.COMPLETE
        run.finished_at = timezone.now()
        run.save(update_fields=["completed_count", "outcome", "finished_at", "updated_at"])

        logger.info(
            "sandbox pass batch complete: submitted=%d errors=%d (run=%s)",
            submitted, errors, run.pk,
        )
        return {
            "submitted": submitted,
            "errors":    errors,
            "run_id":    str(run.pk),
        }

    # ── Fail batch ────────────────────────────────────────────────────────────

    def run_fail_batch(self, count: int = REQUIRED_FAIL_COUNT) -> dict:
        """
        Submit `count` intentionally invalid payloads to trigger DigiTax rejections.

        Each rejection (DigiTaxError raised) counts toward the 50-fail requirement.
        Unexpected passes are logged as warnings but still recorded.

        Returns:
            {"triggered_errors": N, "unexpected_passes": N, "run_id": "<uuid>"}
        """
        run = SandboxTestRun.objects.create(
            organisation=self.config.organisation,
            mode=SandboxTestRun.Mode.FAIL,
            target_count=count,
        )
        start_offset = FirsSubmission.objects.filter(
            organisation=self.config.organisation,
            is_sandbox_test=True,
        ).count()

        triggered_errors = unexpected_passes = 0

        for i in range(count):
            payload = _fail_payload(start_offset + i + 1)
            sub = FirsSubmission(
                organisation=self.config.organisation,
                invoice=None,
                is_sandbox_test=True,
                payload_json=payload,
                status=FirsSubmission.Status.PENDING,
            )
            try:
                # This SHOULD raise a DigiTaxError — if it doesn't, log as unexpected
                resp = self.client.create_invoice(payload)
                sub.submission_ref = resp.get("id", "")
                sub.response_raw = resp
                sub.status = FirsSubmission.Status.SUBMITTED
                sub.submitted_at = timezone.now()
                unexpected_passes += 1
                logger.warning(
                    "sandbox fail test #%d/%d unexpectedly accepted by DigiTax: %s",
                    i + 1, count, resp,
                )

            except DigiTaxError as exc:
                # Expected: DigiTax correctly rejected the invalid payload
                sub.status = FirsSubmission.Status.FAILED
                sub.error_detail = exc.message
                sub.response_raw = getattr(exc, "response", {}) or {}
                triggered_errors += 1

            sub.save()

        run.completed_count = triggered_errors + unexpected_passes
        run.outcome = SandboxTestRun.Outcome.COMPLETE
        run.finished_at = timezone.now()
        run.save(update_fields=["completed_count", "outcome", "finished_at", "updated_at"])

        logger.info(
            "sandbox fail batch complete: triggered_errors=%d unexpected_passes=%d (run=%s)",
            triggered_errors, unexpected_passes, run.pk,
        )
        return {
            "triggered_errors": triggered_errors,
            "unexpected_passes": unexpected_passes,
            "run_id":            str(run.pk),
        }
