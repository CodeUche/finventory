"""
FIRS E-Invoicing models.

Architecture:
    - FirsConfig       : Per-organisation DigiTax credentials + enrollment state.
                         OneToOne with Organisation. API key encrypted at rest.
    - FirsSubmission   : Append-only audit log of every submission attempt.
                         One row per attempt; new row on retry (never update).
                         invoice may be NULL for sandbox certification test rows
                         (is_sandbox_test=True).
    - SandboxTestRun   : Tracks a single batch of sandbox certification submissions.
                         FIRS requires 50 pass + 50 fail before production access.

Feature flag: All FIRS submission logic is gated on FirsConfig.is_enrolled = True.
Organisations without a FirsConfig — or with is_enrolled = False — are completely
unaffected by this app.
"""

from django.db import models

from apps.core.fields import EncryptedCharField
from apps.core.models import TenantAwareModel, TimeStampedModel


class FirsConfig(TimeStampedModel):
    """
    Per-organisation DigiTax / FIRS enrollment configuration.

    Created once when an organisation enrolls in FIRS e-invoicing.
    use_sandbox = True  → requests go to DigiTax sandbox endpoint (safe for testing).
    use_sandbox = False → live production submissions (irreversible).
    """

    organisation = models.OneToOneField(
        "tenancy.Organisation",
        on_delete=models.CASCADE,
        related_name="firs_config",
    )
    is_enrolled = models.BooleanField(
        default=False,
        help_text="Master switch — no FIRS submissions until this is True.",
    )
    # Business identity sent to FIRS (mirrors Organisation.tax_id / name but editable)
    tin = models.CharField(
        max_length=20,
        blank=True,
        help_text="Organisation Tax Identification Number for FIRS.",
    )
    business_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Legal business name as registered with FIRS.",
    )
    # DigiTax API credentials (API key encrypted at rest via EncryptedCharField)
    app_api_key = EncryptedCharField(
        max_length=300,
        blank=True,
        help_text="DigiTax x-api-key — encrypted at rest, never exposed in API responses.",
    )
    # Base URL — allows per-org override if DigiTax changes endpoints
    app_base_url = models.CharField(
        max_length=500,
        default="https://api.digitax.tech/ng/v1",
    )
    use_sandbox = models.BooleanField(
        default=True,
        help_text="Route submissions to DigiTax sandbox. Set False only for production go-live.",
    )
    # DigiTax party ID assigned after POST /parties for the seller (this organisation)
    digitax_party_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="DigiTax-assigned party ID for this organisation (seller). Cached after first registration.",
    )
    # Enrollment audit
    enrolled_at = models.DateTimeField(null=True, blank=True)
    # Test-connection results (set by Settings UI "Test Connection" button)
    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(
        null=True,
        help_text="Result of the most recent test-connection attempt.",
    )

    class Meta(TimeStampedModel.Meta):
        verbose_name = "FIRS Config"
        verbose_name_plural = "FIRS Configs"

    def __str__(self):
        status = "enrolled" if self.is_enrolled else "not enrolled"
        mode = "sandbox" if self.use_sandbox else "production"
        return f"FirsConfig({self.organisation.name} — {status}, {mode})"


class FirsSubmission(TenantAwareModel):
    """
    Append-only audit log of every FIRS invoice submission attempt.

    One row is created per submission attempt. On retry, a new row is inserted
    (attempt_count incremented) — existing rows are never mutated.

    Status lifecycle:
        PENDING    → submission task picked up but not yet sent
        SUBMITTED  → POST /invoices sent to DigiTax; awaiting IRN via webhook
        CLEARED    → IRN received; invoice is fully compliant
        REPORTED   → B2C invoice reported in daily batch
        FAILED     → non-retryable error (bad payload, 4xx); needs human fix
        BYPASSED   → B2C invoice queued for daily batch report (skips async clearance)
    """

    class Status(models.TextChoices):
        PENDING    = "pending",    "Pending"
        SUBMITTED  = "submitted",  "Submitted to DigiTax"
        CLEARED    = "cleared",    "IRN Issued (Cleared)"
        REPORTED   = "reported",   "B2C Batch Reported"
        FAILED     = "failed",     "Submission Failed"
        BYPASSED   = "bypassed",   "Bypassed (B2C daily batch)"

    class TxType(models.TextChoices):
        B2B = "B2B", "Business to Business"
        B2G = "B2G", "Business to Government"
        B2C = "B2C", "Business to Consumer"

    invoice = models.ForeignKey(
        "sales.Invoice",
        on_delete=models.PROTECT,
        related_name="firs_submissions",
        null=True,
        blank=True,
        help_text="Null only for sandbox certification test rows (is_sandbox_test=True).",
    )
    # Phase 7: sandbox certification flag
    is_sandbox_test = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            "True for synthetic submissions created by the sandbox test runner. "
            "FIRS requires 50 pass + 50 fail sandbox tests before production access."
        ),
    )
    submission_ref = models.CharField(
        max_length=200,
        blank=True,
        db_index=True,
        help_text="DigiTax-assigned submission reference returned after POST /invoices.",
    )
    transaction_type = models.CharField(
        max_length=3,
        choices=TxType.choices,
        blank=True,
        help_text="B2B | B2G | B2C — resolved from customer data at submission time.",
    )
    # Full audit trail of the round-trip
    payload_json = models.JSONField(
        default=dict,
        help_text="Exact JSON payload sent to DigiTax POST /invoices.",
    )
    response_raw = models.JSONField(
        default=dict,
        help_text="Raw JSON response body from DigiTax.",
    )
    # FIRS-issued identifiers (populated when status → CLEARED)
    irn = models.CharField(
        max_length=200,
        blank=True,
        help_text="FIRS Invoice Reference Number — format: XXXXXXXXXX-XXXXXXXX-YYYYMMDD",
    )
    csid = models.CharField(
        max_length=500,
        blank=True,
        help_text="Cryptographic Stamp Identifier returned by DigiTax.",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    attempt_count = models.PositiveSmallIntegerField(
        default=1,
        help_text="Incremented each time this submission row is retried.",
    )
    last_attempted_at = models.DateTimeField(auto_now=True)
    error_detail = models.TextField(
        blank=True,
        help_text="Human-readable error from DigiTax or internal exception.",
    )
    class SubmissionKind(models.TextChoices):
        INVOICE     = "invoice",     "Invoice Submission"
        CREDIT_NOTE = "credit_note", "Credit Note"

    # Discriminator: is this a regular invoice submission or a credit note?
    submission_kind = models.CharField(
        max_length=20,
        choices=SubmissionKind.choices,
        default=SubmissionKind.INVOICE,
        db_index=True,
    )
    # Set when submission_kind == 'credit_note' — links back to the SaleReturn
    sale_return = models.ForeignKey(
        "sales.SaleReturn",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="firs_submissions",
        help_text="Populated for credit-note submissions; null for regular invoice submissions.",
    )

    # Timestamps for key state transitions
    submitted_at = models.DateTimeField(null=True, blank=True)
    cleared_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantAwareModel.Meta):
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["invoice", "status"]),
            models.Index(fields=["organisation", "status", "created_at"]),
            models.Index(fields=["submission_ref"]),
            models.Index(fields=["organisation", "is_sandbox_test", "status"]),
        ]
        verbose_name = "FIRS Submission"
        verbose_name_plural = "FIRS Submissions"

    def __str__(self):
        inv_ref = self.invoice_id or "sandbox-test"
        return (
            f"FirsSubmission({inv_ref} | {self.transaction_type} | "
            f"{self.status} | attempt {self.attempt_count})"
        )


class SandboxTestRun(TenantAwareModel):
    """
    Tracks a single batch of FIRS sandbox certification submissions.

    FIRS / DigiTax requires every organisation to complete at least:
        50 pass tests — valid invoices that DigiTax accepts
        50 fail tests — invalid payloads that DigiTax rejects

    before production credentials are issued.

    One SandboxTestRun is created per batch trigger (via the API or management
    command). The related FirsSubmission rows have is_sandbox_test=True.
    """

    class Mode(models.TextChoices):
        PASS = "pass", "Pass Batch (valid invoices)"
        FAIL = "fail", "Fail Batch (invalid payloads)"

    class Outcome(models.TextChoices):
        RUNNING  = "running",  "Running"
        COMPLETE = "complete", "Complete"
        ERROR    = "error",    "Error"

    mode = models.CharField(
        max_length=10,
        choices=Mode.choices,
        help_text="Whether this batch targets pass or fail certification.",
    )
    target_count = models.PositiveSmallIntegerField(
        default=50,
        help_text="How many submissions this batch aimed to make.",
    )
    completed_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="How many submissions completed (pass + fail outcomes combined).",
    )
    outcome = models.CharField(
        max_length=10,
        choices=Outcome.choices,
        default=Outcome.RUNNING,
        db_index=True,
    )
    error_detail = models.TextField(
        blank=True,
        help_text="Top-level error if the batch failed before completing.",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantAwareModel.Meta):
        ordering = ["-created_at"]
        verbose_name = "Sandbox Test Run"
        verbose_name_plural = "Sandbox Test Runs"

    def __str__(self):
        return (
            f"SandboxTestRun({self.mode} | {self.outcome} | "
            f"{self.completed_count}/{self.target_count})"
        )
