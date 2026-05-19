"""
Phase 7 tests: Sandbox certification & go-live checklist.

Test coverage:
    SandboxRunnerUnitTests        — SandboxTestRunner unit tests (mocked DigiTaxApiClient)
    SandboxProgressViewTests      — GET /einvoicing/sandbox/progress/
    SandboxRunViewTests           — POST /einvoicing/sandbox/run/
    GoLiveChecklistViewTests      — GET /einvoicing/go_live_checklist/
    SandboxSubmissionModelTests   — FirsSubmission.is_sandbox_test + nullable invoice
    Phase7IntegrationTests        — End-to-end API HTTP layer
"""

import pytest
from datetime import date
from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.tenancy.models import Organisation, Membership
from apps.authentication.models import User
from apps.einvoicing.models import FirsConfig, FirsSubmission, SandboxTestRun
from apps.einvoicing.sandbox_runner import (
    SandboxTestRunner,
    REQUIRED_PASS_COUNT,
    REQUIRED_FAIL_COUNT,
    _pass_payload,
    _fail_payload,
)


# ─── Fixture helpers ──────────────────────────────────────────────────────────

def _make_user(email: str) -> User:
    """Create a test user."""
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="P7", last_name="Tester", is_verified=True,
    )


def _make_org(owner: User) -> Organisation:
    """Create an org with the given owner (triggers COA + tax seeding)."""
    from apps.tenancy.services import OrganisationService
    return OrganisationService.create_organisation(
        name=f"P7 Org {owner.email[:20]}",
        owner=owner,
        extra={"currency": "NGN", "country": "NG"},
    )


def _make_firs_config(org: Organisation, enrolled: bool = True, sandbox: bool = True,
                      with_key: bool = True, tin: str = "12345678-0001",
                      business_name: str = "Test Co") -> FirsConfig:
    """Create or update a FirsConfig for the given org."""
    cfg, _ = FirsConfig.objects.get_or_create(organisation=org)
    cfg.is_enrolled = enrolled
    cfg.use_sandbox = sandbox
    cfg.tin = tin
    cfg.business_name = business_name
    if with_key:
        cfg.app_api_key = "test_api_key_xxxxxxxx"
    cfg.save()
    return cfg


def _auth_client(user: User, org: Organisation) -> APIClient:
    """Return an authenticated APIClient with the org header set."""
    from rest_framework_simplejwt.tokens import RefreshToken
    token = RefreshToken.for_user(user)
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(token.access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.pk),
    )
    return client


def _make_sandbox_submissions(org: Organisation, mode: str, count: int) -> list:
    """
    Directly create FirsSubmission rows with is_sandbox_test=True.
    mode='pass'  → status=submitted
    mode='fail'  → status=failed
    """
    status = FirsSubmission.Status.SUBMITTED if mode == "pass" else FirsSubmission.Status.FAILED
    subs = []
    for i in range(count):
        sub = FirsSubmission.objects.create(
            organisation=org,
            invoice=None,
            is_sandbox_test=True,
            status=status,
            payload_json={"_test": True, "_index": i},
        )
        subs.append(sub)
    return subs


# ─── Sandbox runner unit tests ────────────────────────────────────────────────

class SandboxRunnerUnitTests(TestCase):
    """Unit tests for SandboxTestRunner with mocked DigiTaxApiClient."""

    def setUp(self):
        self.user = _make_user("p7_runner@test.com")
        self.org = _make_org(self.user)
        self.config = _make_firs_config(self.org)

    def test_init_raises_if_not_sandbox(self):
        """Runner must raise ValueError if use_sandbox is False."""
        self.config.use_sandbox = False
        self.config.save()
        with self.assertRaises(ValueError, msg="Expected ValueError for non-sandbox config"):
            SandboxTestRunner(self.config)

    def test_init_raises_if_no_api_key(self):
        """Runner must raise ValueError if no API key is configured."""
        self.config.app_api_key = ""
        self.config.save()
        with self.assertRaises(ValueError):
            SandboxTestRunner(self.config)

    @patch("apps.einvoicing.sandbox_runner.DigiTaxApiClient")
    def test_run_pass_batch_creates_submitted_submissions(self, MockClient):
        """run_pass_batch() must create FirsSubmission rows with status=submitted."""
        mock_client = MagicMock()
        mock_client.create_invoice.return_value = {"id": "ref-pass-001", "status": "accepted"}
        MockClient.return_value = mock_client

        runner = SandboxTestRunner(self.config)
        runner.client = mock_client
        result = runner.run_pass_batch(count=3)

        self.assertEqual(result["submitted"], 3)
        self.assertEqual(result["errors"], 0)
        self.assertIn("run_id", result)

        # All 3 FirsSubmission rows should be in submitted status with is_sandbox_test=True
        subs = FirsSubmission.objects.filter(
            organisation=self.org, is_sandbox_test=True,
            status=FirsSubmission.Status.SUBMITTED,
        )
        self.assertEqual(subs.count(), 3)

    @patch("apps.einvoicing.sandbox_runner.DigiTaxApiClient")
    def test_run_fail_batch_creates_failed_submissions(self, MockClient):
        """run_fail_batch() must create FirsSubmission rows with status=failed."""
        from apps.einvoicing.services import DigiTaxValidationError
        mock_client = MagicMock()
        # Simulate DigiTax rejecting every bad payload
        mock_client.create_invoice.side_effect = DigiTaxValidationError(
            "Invalid TIN", status_code=400, response={}
        )
        MockClient.return_value = mock_client

        runner = SandboxTestRunner(self.config)
        runner.client = mock_client
        result = runner.run_fail_batch(count=5)

        self.assertEqual(result["triggered_errors"], 5)
        self.assertEqual(result["unexpected_passes"], 0)

        failed = FirsSubmission.objects.filter(
            organisation=self.org, is_sandbox_test=True,
            status=FirsSubmission.Status.FAILED,
        )
        self.assertEqual(failed.count(), 5)

    @patch("apps.einvoicing.sandbox_runner.DigiTaxApiClient")
    def test_run_pass_batch_creates_sandboxtestrun_record(self, MockClient):
        """run_pass_batch() must create a SandboxTestRun with outcome=complete."""
        mock_client = MagicMock()
        mock_client.create_invoice.return_value = {"id": "ref-abc"}
        MockClient.return_value = mock_client

        runner = SandboxTestRunner(self.config)
        runner.client = mock_client
        result = runner.run_pass_batch(count=2)

        run = SandboxTestRun.objects.get(pk=result["run_id"])
        self.assertEqual(run.mode, SandboxTestRun.Mode.PASS)
        self.assertEqual(run.outcome, SandboxTestRun.Outcome.COMPLETE)
        self.assertEqual(run.completed_count, 2)

    def test_get_progress_returns_zero_for_fresh_org(self):
        """get_progress() must return zeros when no sandbox submissions exist."""
        progress = SandboxTestRunner.get_progress(self.config)
        self.assertEqual(progress["pass_count"], 0)
        self.assertEqual(progress["fail_count"], 0)
        self.assertFalse(progress["passes_complete"])
        self.assertFalse(progress["certification_ready"])

    def test_get_progress_reflects_existing_submissions(self):
        """get_progress() counts existing sandbox submissions correctly."""
        _make_sandbox_submissions(self.org, "pass", 30)
        _make_sandbox_submissions(self.org, "fail", 15)

        progress = SandboxTestRunner.get_progress(self.config)
        self.assertEqual(progress["pass_count"], 30)
        self.assertEqual(progress["fail_count"], 15)
        self.assertFalse(progress["passes_complete"])
        self.assertFalse(progress["fails_complete"])
        self.assertFalse(progress["certification_ready"])

    def test_get_progress_certification_ready_at_50_50(self):
        """certification_ready must be True when both pass and fail counts >= 50."""
        _make_sandbox_submissions(self.org, "pass", REQUIRED_PASS_COUNT)
        _make_sandbox_submissions(self.org, "fail", REQUIRED_FAIL_COUNT)

        progress = SandboxTestRunner.get_progress(self.config)
        self.assertTrue(progress["passes_complete"])
        self.assertTrue(progress["fails_complete"])
        self.assertTrue(progress["certification_ready"])


# ─── Payload generator tests ──────────────────────────────────────────────────

class PayloadGeneratorTests(TestCase):
    """Unit tests for the synthetic payload generators."""

    def setUp(self):
        self.user = _make_user("p7_payload@test.com")
        self.org = _make_org(self.user)
        self.config = _make_firs_config(self.org)

    def test_pass_payload_has_required_fields(self):
        """_pass_payload must include all required DigiTax fields."""
        payload = _pass_payload(self.config, 1)
        for field in ("trader_invoice_number", "seller", "buyer", "line_items",
                      "grand_total", "supply_type", "currency"):
            self.assertIn(field, payload, f"Missing field: {field}")

    def test_pass_payload_uses_config_tin(self):
        """_pass_payload must use the org's TIN as the seller TIN."""
        payload = _pass_payload(self.config, 1)
        self.assertEqual(payload["seller"]["tin"], self.config.tin)

    def test_fail_payload_rotates_five_modes(self):
        """_fail_payload must produce 5 distinct failure modes (index % 5)."""
        modes_seen = set()
        for i in range(10):
            payload = _fail_payload(i + 1)
            modes_seen.add(payload.get("_fail_mode"))
        self.assertEqual(modes_seen, {0, 1, 2, 3, 4})

    def test_fail_payload_mode_0_has_empty_tin(self):
        """Fail mode 0 must have an empty seller TIN."""
        payload = _fail_payload(0)  # index 0 → mode 0 (0 % 5 == 0)
        self.assertEqual(payload["seller"]["tin"], "")

    def test_fail_payload_mode_1_has_zero_total(self):
        """Fail mode 1 must have grand_total = 0."""
        payload = _fail_payload(1)  # index 1 → mode 1
        self.assertEqual(payload["grand_total"], 0)


# ─── Sandbox submission model tests ──────────────────────────────────────────

class SandboxSubmissionModelTests(TestCase):
    """Tests for the new model fields: is_sandbox_test and nullable invoice."""

    def setUp(self):
        self.user = _make_user("p7_model@test.com")
        self.org = _make_org(self.user)

    def test_can_create_submission_with_null_invoice(self):
        """FirsSubmission.invoice can be NULL for sandbox test rows."""
        sub = FirsSubmission.objects.create(
            organisation=self.org,
            invoice=None,
            is_sandbox_test=True,
            status=FirsSubmission.Status.FAILED,
        )
        self.assertIsNone(sub.invoice)
        self.assertTrue(sub.is_sandbox_test)

    def test_is_sandbox_test_defaults_to_false(self):
        """FirsSubmission.is_sandbox_test must default to False for normal rows."""
        from apps.sales.models import Invoice
        from apps.inventory.models import Warehouse

        warehouse = Warehouse.objects.create(
            organisation=self.org,
            name="Test WH",
        )
        invoice = Invoice.objects.create(
            organisation=self.org,
            warehouse=warehouse,
            invoice_number=Invoice.generate_number(self.org),
            status="confirmed",
            payment_method="cash",
            issue_date=date.today(),
            subtotal=100, discount_amount=0, tax_amount=0,
            total_amount=100, amount_paid=0, amount_due=100,
            created_by=self.user,
        )
        sub = FirsSubmission.objects.create(
            organisation=self.org,
            invoice=invoice,
            is_sandbox_test=False,
            status=FirsSubmission.Status.PENDING,
        )
        self.assertFalse(sub.is_sandbox_test)
        self.assertIsNotNone(sub.invoice)


# ─── SandboxProgressView tests ────────────────────────────────────────────────

class SandboxProgressViewTests(TestCase):
    """Tests for GET /einvoicing/sandbox/progress/."""

    def setUp(self):
        self.user = _make_user("p7_progress@test.com")
        self.org = _make_org(self.user)
        self.client = _auth_client(self.user, self.org)

    def test_progress_with_no_config_returns_zeros(self):
        """With no FirsConfig, progress should return zeros and 200."""
        resp = self.client.get("/api/v1/einvoicing/sandbox/progress/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["pass_count"], 0)
        self.assertEqual(resp.data["fail_count"], 0)
        self.assertFalse(resp.data["certification_ready"])

    def test_progress_reflects_existing_sandbox_submissions(self):
        """Progress counts must match existing is_sandbox_test submissions."""
        _make_firs_config(self.org)
        _make_sandbox_submissions(self.org, "pass", 20)
        _make_sandbox_submissions(self.org, "fail", 10)

        resp = self.client.get("/api/v1/einvoicing/sandbox/progress/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["pass_count"], 20)
        self.assertEqual(resp.data["fail_count"], 10)
        self.assertFalse(resp.data["certification_ready"])

    def test_progress_unauthenticated_returns_401(self):
        """Unauthenticated requests must be rejected."""
        anon = APIClient()
        resp = anon.get("/api/v1/einvoicing/sandbox/progress/")
        self.assertEqual(resp.status_code, 401)

    def test_progress_certification_ready_when_50_50(self):
        """certification_ready must be True when pass >= 50 and fail >= 50."""
        _make_firs_config(self.org)
        _make_sandbox_submissions(self.org, "pass", REQUIRED_PASS_COUNT)
        _make_sandbox_submissions(self.org, "fail", REQUIRED_FAIL_COUNT)

        resp = self.client.get("/api/v1/einvoicing/sandbox/progress/")
        self.assertTrue(resp.data["certification_ready"])
        self.assertTrue(resp.data["passes_complete"])
        self.assertTrue(resp.data["fails_complete"])


# ─── SandboxRunView tests ─────────────────────────────────────────────────────

class SandboxRunViewTests(TestCase):
    """Tests for POST /einvoicing/sandbox/run/."""

    def setUp(self):
        self.user = _make_user("p7_run@test.com")
        self.org = _make_org(self.user)
        self.config = _make_firs_config(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_run_invalid_mode_returns_400(self):
        """mode must be 'pass' or 'fail'; anything else returns 400."""
        resp = self.client.post("/api/v1/einvoicing/sandbox/run/", {"mode": "both"})
        self.assertEqual(resp.status_code, 400)

    def test_run_no_config_returns_400(self):
        """With no FirsConfig, run must return 400."""
        # Create a fresh org without a config
        user2 = _make_user("p7_run_noconfig@test.com")
        org2 = _make_org(user2)
        client2 = _auth_client(user2, org2)
        resp = client2.post("/api/v1/einvoicing/sandbox/run/", {"mode": "pass"})
        self.assertEqual(resp.status_code, 400)

    def test_run_production_mode_returns_400(self):
        """Cannot run sandbox tests when use_sandbox is False."""
        self.config.use_sandbox = False
        self.config.save()
        resp = self.client.post("/api/v1/einvoicing/sandbox/run/", {"mode": "pass"})
        self.assertEqual(resp.status_code, 400)

    def test_run_no_api_key_returns_400(self):
        """Cannot run sandbox tests without an API key."""
        self.config.app_api_key = ""
        self.config.save()
        resp = self.client.post("/api/v1/einvoicing/sandbox/run/", {"mode": "pass"})
        self.assertEqual(resp.status_code, 400)

    def test_run_valid_pass_returns_202(self):
        """Valid pass batch request must return 202 with task_id."""
        resp = self.client.post(
            "/api/v1/einvoicing/sandbox/run/", {"mode": "pass", "count": 5}
        )
        self.assertEqual(resp.status_code, 202)
        self.assertTrue(resp.data["queued"])
        self.assertEqual(resp.data["mode"], "pass")
        self.assertIn("task_id", resp.data)

    def test_run_valid_fail_returns_202(self):
        """Valid fail batch request must return 202."""
        resp = self.client.post(
            "/api/v1/einvoicing/sandbox/run/", {"mode": "fail", "count": 3}
        )
        self.assertEqual(resp.status_code, 202)

    def test_run_viewer_returns_403(self):
        """A viewer-level user must not be able to trigger sandbox runs."""
        viewer = _make_user("p7_run_viewer@test.com")
        Membership.objects.create(
            user=viewer, organisation=self.org, role="viewer", is_active=True
        )
        viewer_client = _auth_client(viewer, self.org)
        resp = viewer_client.post("/api/v1/einvoicing/sandbox/run/", {"mode": "pass"})
        self.assertEqual(resp.status_code, 403)

    def test_run_count_out_of_range_returns_400(self):
        """count > 100 or < 1 must return 400."""
        resp = self.client.post(
            "/api/v1/einvoicing/sandbox/run/", {"mode": "pass", "count": 200}
        )
        self.assertEqual(resp.status_code, 400)

    def test_run_unauthenticated_returns_401(self):
        """Unauthenticated request must return 401."""
        anon = APIClient()
        resp = anon.post("/api/v1/einvoicing/sandbox/run/", {"mode": "pass"})
        self.assertEqual(resp.status_code, 401)


# ─── GoLiveChecklistView tests ────────────────────────────────────────────────

class GoLiveChecklistViewTests(TestCase):
    """Tests for GET /einvoicing/go_live_checklist/."""

    def setUp(self):
        self.user = _make_user("p7_checklist@test.com")
        self.org = _make_org(self.user)
        self.client = _auth_client(self.user, self.org)

    def test_checklist_with_no_config_all_fail(self):
        """Without FirsConfig, config-dependent checks must fail and all_passed=False."""
        resp = self.client.get("/api/v1/einvoicing/go_live_checklist/")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["all_passed"])
        self.assertFalse(resp.data["production_ready"])
        # Config-dependent checks must all fail
        config_checks = [
            "is_enrolled", "tin_configured", "business_name_configured",
            "api_key_configured", "sandbox_passes_complete", "sandbox_fails_complete",
            "currently_sandbox",
        ]
        for key in config_checks:
            self.assertFalse(
                resp.data["checks"][key]["pass"],
                f"Expected check '{key}' to fail with no config",
            )
        # no_recent_failures passes correctly when there are truly no failures
        self.assertTrue(resp.data["checks"]["no_recent_failures"]["pass"])

    def test_checklist_has_required_check_keys(self):
        """Checklist must include all 8 required check keys."""
        resp = self.client.get("/api/v1/einvoicing/go_live_checklist/")
        required_keys = {
            "is_enrolled", "tin_configured", "business_name_configured",
            "api_key_configured", "sandbox_passes_complete", "sandbox_fails_complete",
            "no_recent_failures", "currently_sandbox",
        }
        self.assertEqual(set(resp.data["checks"].keys()), required_keys)

    def test_checklist_passes_with_complete_config_and_50_50(self):
        """All checks pass when org is fully configured and has 50+50 sandbox tests."""
        _make_firs_config(self.org, enrolled=True, sandbox=True, tin="12345678-0001",
                          business_name="Test Co", with_key=True)
        _make_sandbox_submissions(self.org, "pass", REQUIRED_PASS_COUNT)
        _make_sandbox_submissions(self.org, "fail", REQUIRED_FAIL_COUNT)

        resp = self.client.get("/api/v1/einvoicing/go_live_checklist/")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data["all_passed"])
        self.assertTrue(resp.data["production_ready"])

    def test_checklist_sandbox_passes_shows_count(self):
        """sandbox_passes_complete detail must include current/required count."""
        _make_firs_config(self.org)
        _make_sandbox_submissions(self.org, "pass", 25)

        resp = self.client.get("/api/v1/einvoicing/go_live_checklist/")
        detail = resp.data["checks"]["sandbox_passes_complete"]["detail"]
        self.assertIn("25", detail)
        self.assertIn(str(REQUIRED_PASS_COUNT), detail)

    def test_checklist_unauthenticated_returns_401(self):
        anon = APIClient()
        resp = anon.get("/api/v1/einvoicing/go_live_checklist/")
        self.assertEqual(resp.status_code, 401)

    def test_checklist_viewer_returns_403(self):
        """Viewer-level user must not see the checklist."""
        viewer = _make_user("p7_checklist_viewer@test.com")
        Membership.objects.create(
            user=viewer, organisation=self.org, role="viewer", is_active=True
        )
        viewer_client = _auth_client(viewer, self.org)
        resp = viewer_client.get("/api/v1/einvoicing/go_live_checklist/")
        self.assertEqual(resp.status_code, 403)

    def test_checklist_enrolled_false_fails_is_enrolled(self):
        """is_enrolled check must fail when FirsConfig.is_enrolled = False."""
        _make_firs_config(self.org, enrolled=False)
        resp = self.client.get("/api/v1/einvoicing/go_live_checklist/")
        self.assertFalse(resp.data["checks"]["is_enrolled"]["pass"])

    def test_checklist_missing_tin_fails_tin_check(self):
        """tin_configured check must fail when TIN is empty."""
        _make_firs_config(self.org, tin="")
        resp = self.client.get("/api/v1/einvoicing/go_live_checklist/")
        self.assertFalse(resp.data["checks"]["tin_configured"]["pass"])


# ─── Phase 7 integration tests ────────────────────────────────────────────────

@pytest.mark.api
class Phase7IntegrationTests(TestCase):
    """End-to-end HTTP-layer tests for Phase 7 endpoints."""

    def setUp(self):
        self.user = _make_user("p7_integration@test.com")
        self.org = _make_org(self.user)
        self.config = _make_firs_config(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_progress_endpoint_returns_200(self):
        resp = self.client.get("/api/v1/einvoicing/sandbox/progress/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("pass_count", resp.data)
        self.assertIn("fail_count", resp.data)
        self.assertIn("certification_ready", resp.data)
        self.assertIn("recent_runs", resp.data)

    def test_checklist_endpoint_returns_200(self):
        resp = self.client.get("/api/v1/einvoicing/go_live_checklist/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("checks", resp.data)
        self.assertIn("all_passed", resp.data)
        self.assertIn("production_ready", resp.data)

    def test_sandbox_run_pass_endpoint_returns_202(self):
        resp = self.client.post(
            "/api/v1/einvoicing/sandbox/run/", {"mode": "pass", "count": 2}
        )
        self.assertEqual(resp.status_code, 202)

    def test_sandbox_run_fail_endpoint_returns_202(self):
        resp = self.client.post(
            "/api/v1/einvoicing/sandbox/run/", {"mode": "fail", "count": 2}
        )
        self.assertEqual(resp.status_code, 202)

    def test_sandbox_submissions_show_is_sandbox_test_flag(self):
        """FirsSubmission API must return is_sandbox_test field."""
        _make_sandbox_submissions(self.org, "pass", 2)
        resp = self.client.get("/api/v1/einvoicing/submissions/")
        self.assertEqual(resp.status_code, 200)
        results = resp.data if isinstance(resp.data, list) else resp.data.get("results", [])
        # All sandbox submissions should have is_sandbox_test=True
        sandbox_subs = [r for r in results if r.get("is_sandbox_test")]
        self.assertGreater(len(sandbox_subs), 0)

    def test_sandbox_submissions_have_test_badge_in_invoice_number(self):
        """Sandbox submissions must return empty invoice_number (not crash)."""
        _make_sandbox_submissions(self.org, "fail", 1)
        resp = self.client.get("/api/v1/einvoicing/submissions/")
        results = resp.data if isinstance(resp.data, list) else resp.data.get("results", [])
        sandbox_subs = [r for r in results if r.get("is_sandbox_test")]
        for sub in sandbox_subs:
            # invoice_number should be an empty string, not raise an AttributeError
            self.assertIn("invoice_number", sub)
            self.assertEqual(sub["invoice_number"], "")
            self.assertEqual(sub["customer_name"], "Sandbox Test")

    def test_checklist_not_enrolled_shows_correct_detail(self):
        """When not enrolled, is_enrolled check detail should guide the user."""
        self.config.is_enrolled = False
        self.config.save()
        resp = self.client.get("/api/v1/einvoicing/go_live_checklist/")
        detail = resp.data["checks"]["is_enrolled"]["detail"]
        self.assertIn("Not enrolled", detail)
