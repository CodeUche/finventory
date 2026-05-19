"""
Phase 6 tests — FIRS management API views.

Coverage:
    Unit (marker: unit)
        - FirsConfigView GET auto-creates config when none exists
        - FirsConfigView PATCH updates allowed fields
        - FirsConfigView PATCH by non-owner returns 403
        - TestConnectionView POST returns 400 when no API key stored
        - ManualSubmitView POST rejects invoices not in re-submittable state

    Integration (marker: integration)
        - FirsSubmissionListView returns paginated submissions for org
        - FirsSubmissionListView ?status filter works
        - FirsSubmissionDetailView returns 404 for wrong org
        - FirsStatsView returns correct counts
        - FirsStatsView returns is_enrolled=False for unenrolled org
        - ManualSubmitView queues task for failed invoice

    API (marker: api)
        - GET /einvoicing/config/ returns 200 with correct fields
        - PATCH /einvoicing/config/ by owner updates tin
        - PATCH /einvoicing/config/ by viewer returns 403
        - GET /einvoicing/submissions/ returns 200 with results key
        - GET /einvoicing/stats/ returns 200 with enrollment fields
        - POST /einvoicing/submit/<id>/ returns 202 for failed invoice
        - POST /einvoicing/submit/<id>/ returns 400 for cleared invoice
        - Unauthenticated requests return 401

All tests use SQLite in-memory via config.settings.testing.
No real network calls are made — DigiTax API is not contacted.
"""

import pytest
from datetime import date
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.customers.models import Customer
from apps.einvoicing.models import FirsConfig, FirsSubmission
from apps.inventory.models import Product, Warehouse
from apps.sales.models import Invoice
from apps.tenancy.services import OrganisationService


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _make_user(email="p6owner@test.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="P6", last_name="Owner", is_verified=True,
    )


def _make_org(user, name="Phase6 Org"):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _make_warehouse(org):
    return Warehouse.objects.create(organisation=org, name="Main", is_default=True)


def _make_customer(org):
    return Customer.objects.create(organisation=org, code="C001", name="Test Customer")


def _make_invoice(org, warehouse, user, firs_status="not_enrolled"):
    return Invoice.objects.create(
        organisation=org, warehouse=warehouse, customer=None,
        invoice_number=Invoice.generate_number(org),
        status="confirmed", payment_method="cash",
        issue_date=date.today(),
        subtotal=1000, discount_amount=0, tax_amount=0,
        total_amount=1000, amount_paid=0, amount_due=1000,
        created_by=user, firs_status=firs_status,
    )


def _make_firs_config(org, enrolled=False, api_key="test-key"):
    return FirsConfig.objects.create(
        organisation=org, tin="12345678-0001",
        business_name=org.name, app_api_key=api_key,
        is_enrolled=enrolled, use_sandbox=True,
    )


def _make_submission(org, invoice, sub_status="submitted"):
    return FirsSubmission.objects.create(
        organisation=org, invoice=invoice,
        submission_ref=f"REF-{invoice.invoice_number}",
        transaction_type="B2B",
        status=sub_status,
    )


def _auth_client(user, org):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return client


def _viewer_client(org):
    """Create a viewer user and return an authenticated client."""
    viewer = User.objects.create_user(
        email=f"viewer-{org.id}@test.com", password="TestPass123!",
        first_name="Viewer", last_name="User", is_verified=True,
    )
    from apps.tenancy.models import Membership
    Membership.objects.create(organisation=org, user=viewer, role="viewer", is_active=True)
    client = APIClient()
    refresh = RefreshToken.for_user(viewer)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return client


# ─── Unit tests: view logic ───────────────────────────────────────────────────

@pytest.mark.unit
class FirsConfigViewUnitTests(TestCase):
    """Validate FirsConfigView field handling and permission gating."""

    def setUp(self):
        self.user = _make_user("p6_cfgunit@test.com")
        self.org = _make_org(self.user)
        self.client = _auth_client(self.user, self.org)

    def test_get_config_auto_creates(self):
        """GET /einvoicing/config/ must return 200 and create a config if none exists."""
        self.assertFalse(FirsConfig.objects.filter(organisation=self.org).exists())
        resp = self.client.get("/api/v1/einvoicing/config/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(FirsConfig.objects.filter(organisation=self.org).exists())

    def test_get_config_returns_is_enrolled_false_by_default(self):
        """A freshly auto-created config must default to not enrolled."""
        resp = self.client.get("/api/v1/einvoicing/config/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["is_enrolled"])

    def test_get_config_has_api_key_false_initially(self):
        """has_api_key must be False before any key is stored."""
        resp = self.client.get("/api/v1/einvoicing/config/")
        self.assertFalse(resp.data["has_api_key"])

    def test_patch_config_updates_tin(self):
        """PATCH with tin must update and return the new value."""
        _make_firs_config(self.org)
        resp = self.client.patch(
            "/api/v1/einvoicing/config/",
            {"tin": "99887766-0001"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["tin"], "99887766-0001")

    def test_patch_config_api_key_stored_but_not_returned(self):
        """PATCH with app_api_key must set has_api_key=True but not return the key."""
        _make_firs_config(self.org)
        resp = self.client.patch(
            "/api/v1/einvoicing/config/",
            {"app_api_key": "api_key_test123"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["has_api_key"])
        self.assertNotIn("app_api_key", resp.data)

    def test_patch_config_by_viewer_returns_403(self):
        """Viewer role must not be able to PATCH FIRS credentials."""
        _make_firs_config(self.org)
        viewer_client = _viewer_client(self.org)
        resp = viewer_client.patch(
            "/api/v1/einvoicing/config/",
            {"tin": "00000000-0001"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_test_connection_without_api_key_returns_400(self):
        """POST /einvoicing/config/test_connection/ without a stored key must return 400."""
        _make_firs_config(self.org, api_key="")
        resp = self.client.post("/api/v1/einvoicing/config/test_connection/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.data)

    def test_test_connection_no_config_returns_400(self):
        """POST test_connection/ before any config is saved must return 400."""
        resp = self.client.post("/api/v1/einvoicing/config/test_connection/")
        self.assertEqual(resp.status_code, 400)


@pytest.mark.unit
class ManualSubmitViewUnitTests(TestCase):
    """Validate ManualSubmitView state guards."""

    def setUp(self):
        self.user = _make_user("p6_msunit@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_manual_submit_cleared_invoice_returns_400(self):
        """Cannot re-submit an already-cleared invoice."""
        invoice = _make_invoice(self.org, self.warehouse, self.user, firs_status="cleared")
        with patch("apps.einvoicing.tasks.request_irn.apply_async"):
            resp = self.client.post(f"/api/v1/einvoicing/submit/{invoice.pk}/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.data)

    def test_manual_submit_submitted_invoice_returns_400(self):
        """Cannot re-submit an in-flight (already submitted) invoice."""
        invoice = _make_invoice(self.org, self.warehouse, self.user, firs_status="submitted")
        with patch("apps.einvoicing.tasks.request_irn.apply_async"):
            resp = self.client.post(f"/api/v1/einvoicing/submit/{invoice.pk}/")
        self.assertEqual(resp.status_code, 400)

    def test_manual_submit_nonexistent_invoice_returns_404(self):
        """POST with a random UUID must return 404."""
        import uuid
        resp = self.client.post(f"/api/v1/einvoicing/submit/{uuid.uuid4()}/")
        self.assertEqual(resp.status_code, 404)

    def test_manual_submit_viewer_returns_403(self):
        """Viewer must not be able to trigger manual submission."""
        invoice = _make_invoice(self.org, self.warehouse, self.user, firs_status="failed")
        viewer_client = _viewer_client(self.org)
        with patch("apps.einvoicing.tasks.request_irn.apply_async"):
            resp = viewer_client.post(f"/api/v1/einvoicing/submit/{invoice.pk}/")
        self.assertEqual(resp.status_code, 403)


# ─── Integration tests: view + DB ─────────────────────────────────────────────

@pytest.mark.integration
class FirsSubmissionListViewTests(TestCase):
    """FirsSubmissionListView returns correctly filtered, paginated results."""

    def setUp(self):
        self.user = _make_user("p6_sublist@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)
        self.client = _auth_client(self.user, self.org)
        # Create 3 submissions: 2 cleared, 1 failed
        inv1 = _make_invoice(self.org, self.warehouse, self.user)
        inv2 = _make_invoice(self.org, self.warehouse, self.user)
        inv3 = _make_invoice(self.org, self.warehouse, self.user)
        with patch("apps.einvoicing.tasks.request_irn.apply_async"):
            pass  # invoices already created without triggering tasks
        self.sub1 = _make_submission(self.org, inv1, "cleared")
        self.sub2 = _make_submission(self.org, inv2, "cleared")
        self.sub3 = _make_submission(self.org, inv3, "failed")

    def test_list_returns_all_submissions(self):
        """GET /submissions/ without filter must return all 3 submissions."""
        resp = self.client.get("/api/v1/einvoicing/submissions/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 3)

    def test_list_status_filter(self):
        """?status=cleared must return only the 2 cleared submissions."""
        resp = self.client.get("/api/v1/einvoicing/submissions/?status=cleared")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 2)

    def test_list_failed_filter(self):
        """?status=failed must return only the 1 failed submission."""
        resp = self.client.get("/api/v1/einvoicing/submissions/?status=failed")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)

    def test_list_invoice_filter(self):
        """?invoice=<id> must return only submissions for that invoice."""
        resp = self.client.get(f"/api/v1/einvoicing/submissions/?invoice={self.sub1.invoice_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)

    def test_list_org_isolation(self):
        """Submissions from a different org must not appear in the list."""
        other_user = _make_user("p6_other@test.com")
        other_org = _make_org(other_user, "Other Org")
        other_wh = _make_warehouse(other_org)
        other_inv = _make_invoice(other_org, other_wh, other_user)
        _make_submission(other_org, other_inv, "cleared")
        # Our org still has 3 submissions (not 4)
        resp = self.client.get("/api/v1/einvoicing/submissions/")
        self.assertEqual(resp.data["count"], 3)


@pytest.mark.integration
class FirsSubmissionDetailViewTests(TestCase):
    """FirsSubmissionDetailView enforces org isolation."""

    def setUp(self):
        self.user = _make_user("p6_subdet@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)
        self.client = _auth_client(self.user, self.org)
        inv = _make_invoice(self.org, self.warehouse, self.user)
        self.sub = _make_submission(self.org, inv, "cleared")

    def test_detail_returns_200_for_own_org(self):
        resp = self.client.get(f"/api/v1/einvoicing/submissions/{self.sub.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(str(resp.data["id"]), str(self.sub.pk))

    def test_detail_returns_404_for_other_org(self):
        """A submission belonging to another org must return 404."""
        other_user = _make_user("p6_det_other@test.com")
        other_org = _make_org(other_user, "Other Org DT")
        other_client = _auth_client(other_user, other_org)
        resp = other_client.get(f"/api/v1/einvoicing/submissions/{self.sub.pk}/")
        self.assertEqual(resp.status_code, 404)


@pytest.mark.integration
class FirsStatsViewTests(TestCase):
    """FirsStatsView returns correct aggregated counts and enrollment state."""

    def setUp(self):
        self.user = _make_user("p6_stats@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_stats_no_config(self):
        """Stats for an org with no FirsConfig must show is_enrolled=False and zeros."""
        resp = self.client.get("/api/v1/einvoicing/stats/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["is_enrolled"])
        self.assertEqual(resp.data["total"], 0)

    def test_stats_enrolled_counts(self):
        """Stats must reflect the actual submission counts per status.

        Invoices are created before enrolling so the on_invoice_save signal
        finds no enrolled config and skips submission creation.  We then enroll
        and add the specific FirsSubmission rows we want to count.
        """
        # Create invoices BEFORE enrolling — signal finds org not enrolled, skips
        inv1 = _make_invoice(self.org, self.warehouse, self.user)
        inv2 = _make_invoice(self.org, self.warehouse, self.user)
        inv3 = _make_invoice(self.org, self.warehouse, self.user)
        # Now mark org as enrolled so stats endpoint returns is_enrolled=True
        _make_firs_config(self.org, enrolled=True)
        _make_submission(self.org, inv1, "cleared")
        _make_submission(self.org, inv2, "cleared")
        _make_submission(self.org, inv3, "failed")

        resp = self.client.get("/api/v1/einvoicing/stats/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["is_enrolled"])
        self.assertEqual(resp.data["total"], 3)
        self.assertEqual(resp.data["cleared"], 2)
        self.assertEqual(resp.data["failed"], 1)
        self.assertEqual(resp.data["submitted"], 0)

    def test_stats_sandbox_flag(self):
        """use_sandbox must reflect the FirsConfig setting."""
        cfg = _make_firs_config(self.org, enrolled=True)
        cfg.use_sandbox = False
        cfg.save()
        resp = self.client.get("/api/v1/einvoicing/stats/")
        self.assertFalse(resp.data["use_sandbox"])


# ─── API tests: HTTP layer ─────────────────────────────────────────────────────

@pytest.mark.api
class Phase6ApiTests(TestCase):
    """End-to-end API tests for all Phase 6 endpoints."""

    def setUp(self):
        self.user = _make_user("p6_api@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)
        self.client = _auth_client(self.user, self.org)

    # ── Config endpoint ───────────────────────────────────────────────────────

    def test_get_config_returns_200(self):
        resp = self.client.get("/api/v1/einvoicing/config/")
        self.assertEqual(resp.status_code, 200)
        for field in ("id", "is_enrolled", "tin", "has_api_key", "use_sandbox"):
            self.assertIn(field, resp.data, f"Missing field: {field}")

    def test_patch_config_updates_tin(self):
        resp = self.client.patch(
            "/api/v1/einvoicing/config/",
            {"tin": "11223344-0001"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["tin"], "11223344-0001")

    def test_patch_config_by_viewer_is_forbidden(self):
        viewer_client = _viewer_client(self.org)
        resp = viewer_client.patch("/api/v1/einvoicing/config/", {"tin": "x"}, format="json")
        self.assertEqual(resp.status_code, 403)

    # ── Submissions endpoint ──────────────────────────────────────────────────

    def test_get_submissions_returns_200_with_results(self):
        resp = self.client.get("/api/v1/einvoicing/submissions/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("results", resp.data)
        self.assertIn("count", resp.data)

    def test_get_submissions_unauthenticated_returns_401(self):
        unauth = APIClient()
        resp = unauth.get("/api/v1/einvoicing/submissions/")
        self.assertEqual(resp.status_code, 401)

    # ── Stats endpoint ────────────────────────────────────────────────────────

    def test_get_stats_returns_200(self):
        resp = self.client.get("/api/v1/einvoicing/stats/")
        self.assertEqual(resp.status_code, 200)
        for field in ("is_enrolled", "has_api_key", "total", "cleared", "failed"):
            self.assertIn(field, resp.data, f"Missing stats field: {field}")

    def test_get_stats_unauthenticated_returns_401(self):
        unauth = APIClient()
        resp = unauth.get("/api/v1/einvoicing/stats/")
        self.assertEqual(resp.status_code, 401)

    # ── Manual submit endpoint ────────────────────────────────────────────────

    def test_manual_submit_failed_invoice_returns_202(self):
        """POST /einvoicing/submit/<id>/ for a failed invoice queues the task."""
        invoice = _make_invoice(self.org, self.warehouse, self.user, firs_status="failed")
        _make_firs_config(self.org, enrolled=True)
        with patch("apps.einvoicing.tasks.request_irn.apply_async") as mock_task:
            resp = self.client.post(f"/api/v1/einvoicing/submit/{invoice.pk}/")
        self.assertEqual(resp.status_code, 202)
        self.assertTrue(resp.data["queued"])
        mock_task.assert_called_once()

    def test_manual_submit_not_enrolled_invoice_returns_202(self):
        """not_enrolled status is also re-submittable (org may have just enrolled)."""
        invoice = _make_invoice(self.org, self.warehouse, self.user, firs_status="not_enrolled")
        _make_firs_config(self.org, enrolled=True)
        with patch("apps.einvoicing.tasks.request_irn.apply_async"):
            resp = self.client.post(f"/api/v1/einvoicing/submit/{invoice.pk}/")
        self.assertEqual(resp.status_code, 202)

    def test_manual_submit_cleared_invoice_returns_400(self):
        invoice = _make_invoice(self.org, self.warehouse, self.user, firs_status="cleared")
        with patch("apps.einvoicing.tasks.request_irn.apply_async"):
            resp = self.client.post(f"/api/v1/einvoicing/submit/{invoice.pk}/")
        self.assertEqual(resp.status_code, 400)

    # ── Test connection endpoint ──────────────────────────────────────────────

    def test_test_connection_no_config_returns_400(self):
        """No FirsConfig → 400 with a meaningful error."""
        resp = self.client.post("/api/v1/einvoicing/config/test_connection/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.data)

    def test_test_connection_with_key_calls_digitax(self):
        """With a stored key, the view calls DigiTaxApiClient.test_connection."""
        _make_firs_config(self.org, api_key="api_key_test123")
        from apps.einvoicing.services import DigiTaxApiClient
        with patch.object(DigiTaxApiClient, "test_connection", return_value={"status": "ok"}):
            resp = self.client.post("/api/v1/einvoicing/config/test_connection/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["ok"])
        # last_test_ok must be persisted
        cfg = FirsConfig.objects.get(organisation=self.org)
        self.assertTrue(cfg.last_test_ok)
        self.assertIsNotNone(cfg.last_test_at)

    def test_test_connection_failure_returns_502(self):
        """When DigiTax rejects the key, the view returns 502 with ok=False."""
        from apps.einvoicing.services import DigiTaxApiClient, DigiTaxAuthError
        _make_firs_config(self.org, api_key="api_key_bad")
        with patch.object(DigiTaxApiClient, "test_connection", side_effect=DigiTaxAuthError("Unauthorized")):
            resp = self.client.post("/api/v1/einvoicing/config/test_connection/")
        self.assertEqual(resp.status_code, 502)
        self.assertFalse(resp.data["ok"])
        cfg = FirsConfig.objects.get(organisation=self.org)
        self.assertFalse(cfg.last_test_ok)
