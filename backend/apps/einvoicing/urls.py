"""
URL configuration for the einvoicing app.

Phase 3 routes
--------------
    POST  einvoicing/webhook/                → DigiTaxWebhookView (AllowAny, HMAC-validated)

Phase 6 routes
--------------
    GET/PATCH  einvoicing/config/                  → FirsConfigView
    POST       einvoicing/config/test_connection/  → TestConnectionView
    GET        einvoicing/submissions/             → FirsSubmissionListView
    GET        einvoicing/submissions/<id>/        → FirsSubmissionDetailView
    GET        einvoicing/stats/                   → FirsStatsView
    POST       einvoicing/submit/<invoice_id>/     → ManualSubmitView

Phase 7 routes
--------------
    GET   einvoicing/sandbox/progress/   → SandboxProgressView (50+50 certification counts)
    POST  einvoicing/sandbox/run/        → SandboxRunView (trigger async batch; owner/admin)
    GET   einvoicing/go_live_checklist/  → GoLiveChecklistView (pre-production readiness check)
"""

from django.urls import path

from apps.einvoicing.views import (
    DigiTaxWebhookView,
    FirsConfigView,
    FirsStatsView,
    FirsSubmissionDetailView,
    FirsSubmissionListView,
    GoLiveChecklistView,
    ManualSubmitView,
    SandboxProgressView,
    SandboxRunView,
    TestConnectionView,
)

urlpatterns = [
    # ── Phase 3: Webhook ─────────────────────────────────────────────────────
    path("webhook/", DigiTaxWebhookView.as_view(), name="einvoicing-webhook"),

    # ── Phase 6: Config management ────────────────────────────────────────────
    path("config/", FirsConfigView.as_view(), name="einvoicing-config"),
    path("config/test_connection/", TestConnectionView.as_view(), name="einvoicing-test-connection"),

    # ── Phase 6: Submission audit log ─────────────────────────────────────────
    path("submissions/", FirsSubmissionListView.as_view(), name="einvoicing-submissions"),
    path("submissions/<uuid:submission_id>/", FirsSubmissionDetailView.as_view(), name="einvoicing-submission-detail"),

    # ── Phase 6: Stats & manual re-submit ────────────────────────────────────
    path("stats/", FirsStatsView.as_view(), name="einvoicing-stats"),
    path("submit/<uuid:invoice_id>/", ManualSubmitView.as_view(), name="einvoicing-manual-submit"),

    # ── Phase 7: Sandbox certification ───────────────────────────────────────
    # GET: cumulative pass/fail counts toward 50+50 FIRS requirement
    path("sandbox/progress/", SandboxProgressView.as_view(), name="einvoicing-sandbox-progress"),
    # POST: trigger an async pass or fail batch; owner/admin only
    path("sandbox/run/", SandboxRunView.as_view(), name="einvoicing-sandbox-run"),

    # ── Phase 7: Go-live checklist ────────────────────────────────────────────
    # GET: structured pre-production readiness checklist; owner/admin only
    path("go_live_checklist/", GoLiveChecklistView.as_view(), name="einvoicing-go-live-checklist"),
]
