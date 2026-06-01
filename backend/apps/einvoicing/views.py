"""
FIRS E-Invoicing views.

Phase 3 — webhook
=================
    POST /api/v1/einvoicing/webhook/
    DigiTax calls this when an IRN has been issued (HMAC-SHA256 validated).

Phase 6 — management API
=========================
    GET/PATCH  einvoicing/config/                  → FirsConfigView
    POST       einvoicing/config/test_connection/  → TestConnectionView
    GET        einvoicing/submissions/             → FirsSubmissionListView
    GET        einvoicing/submissions/<id>/        → FirsSubmissionDetailView
    GET        einvoicing/stats/                   → FirsStatsView
    POST       einvoicing/submit/<invoice_id>/     → ManualSubmitView

Phase 7 — sandbox certification & go-live checklist
=====================================================
    GET        einvoicing/sandbox/progress/        → SandboxProgressView
    POST       einvoicing/sandbox/run/             → SandboxRunView
    GET        einvoicing/go_live_checklist/       → GoLiveChecklistView

Permissions matrix:
    FirsConfigView      GET        — any authenticated org member
    FirsConfigView      PATCH      — owner/admin only
    TestConnectionView  POST       — owner/admin only
    FirsSubmissionList  GET        — any authenticated org member
    FirsStatsView       GET        — any authenticated org member
    ManualSubmitView    POST       — owner/admin only
    SandboxProgressView GET        — any authenticated org member
    SandboxRunView      POST       — owner/admin only
    GoLiveChecklistView GET        — owner/admin only
"""

import hashlib
import hmac
import logging
import time

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsOwnerOrAdmin
from apps.einvoicing.models import FirsConfig, FirsSubmission
from apps.einvoicing.serializers import (
    FirsConfigSerializer,
    FirsSubmissionDetailSerializer,
    FirsSubmissionSerializer,
    WebhookPayloadSerializer,
)

logger = logging.getLogger(__name__)

# Maximum age of a webhook request (seconds) before it is rejected as a replay.
_WEBHOOK_TOLERANCE = 300  # 5 minutes


class DigiTaxWebhookView(APIView):
    """
    Receive and dispatch DigiTax IRN clearance callbacks.

    Public endpoint — no authentication required, but HMAC signature must be valid.
    """

    permission_classes = [AllowAny]
    # Disable DRF's CSRF enforcement (webhook callers can't send CSRF tokens)
    authentication_classes = []

    def post(self, request) -> Response:
        """
        Handle a DigiTax IRN callback.

        Expected header: X-DigiTax-Signature: t=<timestamp>,v1=<hmac_hex>
        """
        raw_body = request.body  # bytes — must be read before DRF parses it

        # ── 1. HMAC validation ────────────────────────────────────────────────
        sig_header = request.META.get("HTTP_X_DIGITAX_SIGNATURE", "")
        valid, rejection_reason = _verify_signature(sig_header, raw_body)
        if not valid:
            logger.warning(
                "DigiTax webhook: signature rejected — %s (header=%r)",
                rejection_reason, sig_header[:60] if sig_header else "<missing>",
            )
            return Response(
                {"error": f"Invalid signature: {rejection_reason}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── 2. Payload validation ─────────────────────────────────────────────
        serializer = WebhookPayloadSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(
                "DigiTax webhook: invalid payload — %s", serializer.errors
            )
            return Response(
                {"error": "Invalid payload", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data

        # ── 3. Dispatch to Celery (fast, async) ───────────────────────────────
        try:
            from apps.einvoicing.tasks import handle_irn_callback_task
            handle_irn_callback_task.apply_async(
                kwargs={
                    "submission_ref":    data["submission_ref"],
                    "irn":               data["irn"],
                    "csid":              data.get("csid", ""),
                    "firs_invoice_number": data.get("invoice_number", ""),
                    "qr_code_b64":       data.get("qr_code", ""),
                },
                countdown=0,
            )
            logger.info(
                "DigiTax webhook: dispatched callback for ref=%s irn=%s",
                data["submission_ref"], data["irn"],
            )
        except Exception as exc:
            # Log but still return 200 to avoid DigiTax infinite retry loop.
            # The submission can be retried by the retry_failed_submissions beat task.
            logger.exception(
                "DigiTax webhook: failed to dispatch callback task ref=%s: %s",
                data.get("submission_ref"), exc,
            )

        # ── 4. Always return 200 so DigiTax stops retrying ───────────────────
        return Response({"received": True}, status=status.HTTP_200_OK)


# ─── HMAC helpers ─────────────────────────────────────────────────────────────

def _verify_signature(sig_header: str, raw_body: bytes) -> tuple[bool, str]:
    """
    Validate the DigiTax HMAC-SHA256 webhook signature.

    DigiTax signature format:
        X-DigiTax-Signature: t=<unix_timestamp>,v1=<hmac_sha256_hex>

    The signed string is: "<timestamp>.<raw_body_bytes_decoded_as_utf8>".

    Args:
        sig_header: Raw value of the X-DigiTax-Signature header.
        raw_body:   Raw request body bytes (before JSON parsing).

    Returns:
        (True, "")       — signature valid
        (False, reason)  — invalid; reason is a short description for logging
    """
    secret = getattr(settings, "DIGITAX_WEBHOOK_SECRET", "")

    if not secret:
        # Missing secret is always a configuration error — never skip HMAC validation
        return False, "DIGITAX_WEBHOOK_SECRET not configured"

    if not sig_header:
        return False, "missing X-DigiTax-Signature header"

    # Parse "t=<ts>,v1=<hex>"
    timestamp_str = ""
    received_sig = ""
    for part in sig_header.split(","):
        if part.startswith("t="):
            timestamp_str = part[2:]
        elif part.startswith("v1="):
            received_sig = part[3:]

    if not timestamp_str or not received_sig:
        return False, "malformed signature header"

    # Replay protection: reject requests older than tolerance window
    try:
        ts = int(timestamp_str)
        age = abs(int(time.time()) - ts)
        if age > _WEBHOOK_TOLERANCE:
            return False, f"timestamp too old ({age}s)"
    except ValueError:
        return False, "invalid timestamp in signature"

    # Compute expected HMAC: HMAC-SHA256(secret, f"{ts}.{body}")
    signed_payload = f"{timestamp_str}.{raw_body.decode('utf-8', errors='replace')}"
    expected = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(expected, received_sig):
        return False, "signature mismatch"

    return True, ""


# ─── Phase 6: Management API views ────────────────────────────────────────────

def _get_org(request):
    """
    Return the resolved Organisation from the request (set by TenantMiddleware).
    Falls back to resolve_organisation() for APIView subclasses where the mixin
    is not present. Raises PermissionDenied if org cannot be determined.
    """
    org = getattr(request, "organisation", None)
    if org is None:
        # resolve_organisation lives in tenancy middleware (not core middleware)
        from apps.tenancy.middleware import resolve_organisation
        org = resolve_organisation(request)
    return org


class FirsConfigView(APIView):
    """
    Retrieve or update the FIRS configuration for the authenticated organisation.

    GET  — returns the config (auto-creates a default-off config if none exists)
    PATCH — updates credentials; owner/admin only
    """

    def get_permissions(self):
        """GET is available to all org members; PATCH requires owner/admin."""
        if self.request.method == "PATCH":
            return [IsAuthenticated(), IsOwnerOrAdmin()]
        return [IsAuthenticated()]

    def get(self, request):
        """Return (or auto-create) the org's FirsConfig."""
        org = _get_org(request)
        if org is None:
            return Response({"error": "Organisation not found"}, status=status.HTTP_403_FORBIDDEN)

        # get_or_create means non-enrolled orgs see a clean config object
        # rather than a 404 — the UI needs this to show the enrollment form.
        config, _ = FirsConfig.objects.get_or_create(organisation=org)
        return Response(FirsConfigSerializer(config).data)

    def patch(self, request):
        """Update credentials. Only fields explicitly sent are changed."""
        org = _get_org(request)
        if org is None:
            return Response({"error": "Organisation not found"}, status=status.HTTP_403_FORBIDDEN)

        config, _ = FirsConfig.objects.get_or_create(organisation=org)
        serializer = FirsConfigSerializer(config, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        serializer.save()
        logger.info(
            "FirsConfig updated for org=%s by user=%s",
            org.id, request.user.id,
        )
        return Response(FirsConfigSerializer(config).data)


class TestConnectionView(APIView):
    """
    POST /einvoicing/config/test_connection/

    Calls the DigiTax /resources endpoint using the org's stored credentials.
    Updates FirsConfig.last_test_at and last_test_ok accordingly.
    Owner/admin only — requires a stored API key.
    """

    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def post(self, request):
        org = _get_org(request)
        if org is None:
            return Response({"error": "Organisation not found"}, status=status.HTTP_403_FORBIDDEN)

        try:
            config = org.firs_config
        except FirsConfig.DoesNotExist:
            return Response(
                {"error": "No FIRS configuration found. Please save credentials first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not config.app_api_key:
            return Response(
                {"error": "No API key stored. Please enter your DigiTax API key first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.einvoicing.services import DigiTaxApiClient, DigiTaxError

        client = DigiTaxApiClient.from_config(config)
        try:
            result = client.test_connection()
            ok = True
            detail = {"message": "Connection successful", "data": result}
        except DigiTaxError as exc:
            ok = False
            detail = {"message": str(exc)}

        # Persist test result regardless of outcome
        config.last_test_at = timezone.now()
        config.last_test_ok = ok
        config.save(update_fields=["last_test_at", "last_test_ok"])

        http_status = status.HTTP_200_OK if ok else status.HTTP_502_BAD_GATEWAY
        return Response({
            "ok": ok,
            "tested_at": config.last_test_at.isoformat(),
            **detail,
        }, status=http_status)


class FirsSubmissionListView(APIView):
    """
    GET /einvoicing/submissions/

    Returns a paginated list of FirsSubmission records for the org.
    Supports filtering by:
        ?status=cleared|failed|submitted|pending|bypassed
        ?invoice=<invoice_id>
        ?kind=invoice|credit_note
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_org(request)
        if org is None:
            return Response({"error": "Organisation not found"}, status=status.HTTP_403_FORBIDDEN)

        qs = FirsSubmission.objects.filter(organisation=org).select_related(
            "invoice", "invoice__customer", "sale_return",
        ).order_by("-created_at")

        # Optional filters
        filter_status = request.query_params.get("status")
        if filter_status:
            qs = qs.filter(status=filter_status)

        filter_invoice = request.query_params.get("invoice")
        if filter_invoice:
            qs = qs.filter(invoice_id=filter_invoice)

        filter_kind = request.query_params.get("kind")
        if filter_kind:
            qs = qs.filter(submission_kind=filter_kind)

        # Simple offset pagination (page_size default 20)
        try:
            page_size = min(int(request.query_params.get("page_size", 20)), 100)
            page = max(int(request.query_params.get("page", 1)), 1)
        except (TypeError, ValueError):
            page_size, page = 20, 1

        total = qs.count()
        start = (page - 1) * page_size
        items = qs[start: start + page_size]

        return Response({
            "count": total,
            "page": page,
            "page_size": page_size,
            "results": FirsSubmissionSerializer(items, many=True).data,
        })


class FirsSubmissionDetailView(APIView):
    """
    GET /einvoicing/submissions/<submission_id>/

    Returns the full FirsSubmission including payload_json and response_raw.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, submission_id):
        org = _get_org(request)
        if org is None:
            return Response({"error": "Organisation not found"}, status=status.HTTP_403_FORBIDDEN)

        try:
            submission = FirsSubmission.objects.select_related(
                "invoice", "invoice__customer", "sale_return",
            ).get(pk=submission_id, organisation=org)
        except FirsSubmission.DoesNotExist:
            return Response({"error": "Submission not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(FirsSubmissionDetailSerializer(submission).data)


class FirsStatsView(APIView):
    """
    GET /einvoicing/stats/

    Returns submission counts broken down by status for the org, plus
    a boolean indicating whether the org is currently enrolled.
    Used by the Settings FIRS tab and the Dashboard compliance banner.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_org(request)
        if org is None:
            return Response({"error": "Organisation not found"}, status=status.HTTP_403_FORBIDDEN)

        try:
            config = org.firs_config
            is_enrolled = config.is_enrolled
            has_api_key = bool(config.app_api_key)
            use_sandbox = config.use_sandbox
            last_test_ok = config.last_test_ok
            last_test_at = config.last_test_at.isoformat() if config.last_test_at else None
        except FirsConfig.DoesNotExist:
            is_enrolled = False
            has_api_key = False
            use_sandbox = True
            last_test_ok = None
            last_test_at = None

        # Submission counts for this org
        from django.db.models import Count
        counts = (
            FirsSubmission.objects
            .filter(organisation=org)
            .values("status")
            .annotate(n=Count("id"))
        )
        status_counts = {row["status"]: row["n"] for row in counts}

        return Response({
            "is_enrolled":   is_enrolled,
            "has_api_key":   has_api_key,
            "use_sandbox":   use_sandbox,
            "last_test_ok":  last_test_ok,
            "last_test_at":  last_test_at,
            "total":         sum(status_counts.values()),
            "cleared":       status_counts.get("cleared", 0),
            "submitted":     status_counts.get("submitted", 0),
            "pending":       status_counts.get("pending", 0),
            "failed":        status_counts.get("failed", 0),
            "bypassed":      status_counts.get("bypassed", 0),
            "reported":      status_counts.get("reported", 0),
        })


class ManualSubmitView(APIView):
    """
    POST /einvoicing/submit/<invoice_id>/

    Owner/admin-triggered manual submission for an invoice that failed or
    was skipped. Useful during onboarding or after fixing a bad payload.
    Only works if the invoice firs_status is 'failed' or 'not_enrolled'.
    """

    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def post(self, request, invoice_id):
        org = _get_org(request)
        if org is None:
            return Response({"error": "Organisation not found"}, status=status.HTTP_403_FORBIDDEN)

        from apps.sales.models import Invoice

        try:
            invoice = Invoice.objects.get(pk=invoice_id, organisation=org)
        except Invoice.DoesNotExist:
            return Response({"error": "Invoice not found"}, status=status.HTTP_404_NOT_FOUND)

        # Guard: only submit invoices in a re-submittable state
        resubmittable = {"failed", "not_enrolled"}
        if invoice.firs_status not in resubmittable:
            return Response(
                {
                    "error": (
                        f"Invoice firs_status is '{invoice.firs_status}' — "
                        "only 'failed' or 'not_enrolled' invoices can be manually re-submitted."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.einvoicing.tasks import request_irn
        request_irn.apply_async(args=[str(invoice.pk)], countdown=0)

        logger.info(
            "ManualSubmitView: queued request_irn for invoice %s by user=%s",
            invoice.invoice_number, request.user.id,
        )
        return Response({
            "queued": True,
            "invoice_id": str(invoice.pk),
            "invoice_number": invoice.invoice_number,
        }, status=status.HTTP_202_ACCEPTED)


# ─── Phase 7: Sandbox certification & go-live checklist ───────────────────────

class SandboxProgressView(APIView):
    """
    GET /einvoicing/sandbox/progress/

    Returns the organisation's sandbox certification progress toward the
    FIRS-required 50 pass + 50 fail submissions, plus the last 5 run records.
    Any authenticated org member may view this.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org = _get_org(request)
        if org is None:
            return Response({"error": "Organisation not found"}, status=status.HTTP_403_FORBIDDEN)

        try:
            config = FirsConfig.objects.get(organisation=org)
        except FirsConfig.DoesNotExist:
            # No config yet — return zero progress so the UI renders safely
            return Response({
                "pass_count": 0, "fail_count": 0, "pending_count": 0,
                "required_passes": 50, "required_fails": 50,
                "passes_complete": False, "fails_complete": False,
                "certification_ready": False, "recent_runs": [],
            })

        from apps.einvoicing.sandbox_runner import SandboxTestRunner
        return Response(SandboxTestRunner.get_progress(config))


class SandboxRunView(APIView):
    """
    POST /einvoicing/sandbox/run/

    Triggers an async sandbox certification batch. Owner/admin only.

    Body: {"mode": "pass" | "fail", "count": 50}

    Returns 202 immediately; the Celery worker runs the actual submissions.
    """

    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def post(self, request):
        org = _get_org(request)
        if org is None:
            return Response({"error": "Organisation not found"}, status=status.HTTP_403_FORBIDDEN)

        mode = request.data.get("mode")
        if mode not in ("pass", "fail"):
            return Response(
                {"error": "mode must be 'pass' or 'fail'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            count = int(request.data.get("count", 50))
        except (TypeError, ValueError):
            count = 50
        if count < 1 or count > 100:
            return Response(
                {"error": "count must be between 1 and 100"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            config = FirsConfig.objects.get(organisation=org)
        except FirsConfig.DoesNotExist:
            return Response(
                {"error": "No FIRS configuration found. Set up your credentials first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not config.use_sandbox:
            return Response(
                {"error": "Sandbox tests can only be run when use_sandbox is True."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not config.app_api_key:
            return Response(
                {"error": "No DigiTax API key configured. Add your key in FIRS settings."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.einvoicing.tasks import run_sandbox_batch
        task = run_sandbox_batch.apply_async(args=[str(org.pk), mode, count], countdown=0)

        logger.info(
            "SandboxRunView: queued %s batch (count=%d) for org=%s task=%s",
            mode, count, org.pk, task.id,
        )
        return Response(
            {"queued": True, "mode": mode, "count": count, "task_id": task.id},
            status=status.HTTP_202_ACCEPTED,
        )


class GoLiveChecklistView(APIView):
    """
    GET /einvoicing/go_live_checklist/

    Returns a structured pre-production checklist so admins can verify all
    requirements are met before switching from sandbox to live production.

    Checks:
        is_enrolled              — FirsConfig.is_enrolled = True
        tin_configured           — TIN field non-empty
        business_name_configured — business_name field non-empty
        api_key_configured       — API key stored
        sandbox_passes_complete  — ≥50 sandbox pass submissions
        sandbox_fails_complete   — ≥50 sandbox fail submissions
        no_recent_failures       — no non-sandbox FAILED submissions in the last 7 days
        currently_sandbox        — use_sandbox = True (about to flip to prod)

    Response:
        {"checks": {"<key>": {"pass": bool, "detail": str}},
         "all_passed": bool, "production_ready": bool}
    """

    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get(self, request):
        org = _get_org(request)
        if org is None:
            return Response({"error": "Organisation not found"}, status=status.HTTP_403_FORBIDDEN)

        checks = {}
        config = None
        try:
            config = FirsConfig.objects.get(organisation=org)
        except FirsConfig.DoesNotExist:
            pass

        # 1. Enrollment
        enrolled = bool(config and config.is_enrolled)
        checks["is_enrolled"] = {
            "pass":   enrolled,
            "detail": "Enrolled in FIRS e-invoicing" if enrolled
                      else "Not enrolled — enable enrollment in FIRS settings",
        }

        # 2. TIN
        tin_ok = bool(config and config.tin.strip())
        checks["tin_configured"] = {
            "pass":   tin_ok,
            "detail": f"TIN: {config.tin}" if tin_ok else "TIN not set — required for FIRS",
        }

        # 3. Business name
        bn_ok = bool(config and config.business_name.strip())
        checks["business_name_configured"] = {
            "pass":   bn_ok,
            "detail": config.business_name if bn_ok else "Business name not set",
        }

        # 4. API key
        key_ok = bool(config and config.app_api_key)
        checks["api_key_configured"] = {
            "pass":   key_ok,
            "detail": "DigiTax API key stored" if key_ok else "No API key — add your DigiTax x-api-key",
        }

        # 5 & 6. Sandbox certification counts
        from apps.einvoicing.models import FirsSubmission
        from apps.einvoicing.sandbox_runner import REQUIRED_PASS_COUNT, REQUIRED_FAIL_COUNT

        if config:
            qs = FirsSubmission.objects.filter(organisation=org, is_sandbox_test=True)
            pass_count = qs.filter(
                status__in=["submitted", "cleared", "reported", "bypassed"]
            ).count()
            fail_count = qs.filter(status="failed").count()
        else:
            pass_count = fail_count = 0

        passes_ok = pass_count >= REQUIRED_PASS_COUNT
        checks["sandbox_passes_complete"] = {
            "pass":   passes_ok,
            "detail": (f"{pass_count}/{REQUIRED_PASS_COUNT} pass tests complete"
                       + (" ✓" if passes_ok else " — run pass tests from the Sandbox section")),
        }

        fails_ok = fail_count >= REQUIRED_FAIL_COUNT
        checks["sandbox_fails_complete"] = {
            "pass":   fails_ok,
            "detail": (f"{fail_count}/{REQUIRED_FAIL_COUNT} fail tests complete"
                       + (" ✓" if fails_ok else " — run fail tests from the Sandbox section")),
        }

        # 7. No recent non-sandbox failures (last 7 days)
        from datetime import timedelta
        week_ago = timezone.now() - timedelta(days=7)
        recent_failures = FirsSubmission.objects.filter(
            organisation=org, is_sandbox_test=False,
            status="failed", created_at__gte=week_ago,
        ).count()
        no_failures = recent_failures == 0
        checks["no_recent_failures"] = {
            "pass":   no_failures,
            "detail": "No recent submission failures" if no_failures
                      else f"{recent_failures} failed submission(s) in the last 7 days — resolve before going live",
        }

        # 8. Currently in sandbox mode
        in_sandbox = bool(config and config.use_sandbox)
        checks["currently_sandbox"] = {
            "pass":   in_sandbox,
            "detail": "Currently in sandbox mode — ready to switch to production"
                      if in_sandbox else "Already in production mode",
        }

        all_passed = all(c["pass"] for c in checks.values())
        return Response({
            "checks":           checks,
            "all_passed":       all_passed,
            "production_ready": all_passed,
        })
