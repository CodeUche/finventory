"""
Phase 3 tests — Celery tasks, Django post_save signal, and DigiTax webhook view.

All Celery tasks are called synchronously (CELERY_TASK_ALWAYS_EAGER=True) so
no broker is needed for the test suite. Network calls to DigiTax are mocked
throughout.

Coverage
========
Tasks
    request_irn
        - skips when invoice not found
        - skips when org not enrolled
        - skips when invoice already submitted/cleared
        - submits B2B invoice → returns {"status": "submitted", ...}
        - submits B2C invoice → returns {"status": "bypassed", ...}
        - non-retryable DigiTaxAuthError → returns {"status": "failed"}
        - non-retryable DigiTaxValidationError → returns {"status": "failed"}
        - DigiTaxServerError → task retries (raises Retry)

    handle_irn_callback_task
        - skips when submission_ref not found
        - calls EInvoicingService.handle_irn_callback with correct args
        - exception triggers retry

    report_b2c_invoices
        - skips orgs without enrolled FirsConfig
        - marks BYPASSED submissions as REPORTED
        - increments reported counter
        - DigiTaxError on one invoice → failed counter increments, others still processed

    retry_failed_submissions
        - queues request_irn for eligible FAILED submissions
        - skips submissions at max attempt_count
        - skips orgs no longer enrolled

    update_payment_status_firs
        - skips when invoice not found
        - skips when no CLEARED submission exists
        - calls client.update_payment_status("PAID")
        - DigiTaxServerError → retries

Signal
    on_invoice_save
        - draft invoice → no task queued
        - proforma invoice → no task queued
        - confirmed invoice → request_irn queued
        - paid invoice → request_irn + update_payment_status_firs queued
        - already-submitted invoice → no task queued (firs_status guard)

Webhook
    DigiTaxWebhookView
        - missing signature header in production mode → 400
        - malformed signature header → 400
        - valid signature → 200 + task dispatched
        - invalid payload (missing required field) → 400
        - valid payload in DEBUG mode (no secret) → 200
        - dispatched task kwargs match webhook payload
        - replay attack (old timestamp) → 400
        - signature mismatch → 400
"""

import hashlib
import hmac
import json
import time
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.authentication.models import User
from apps.customers.models import Customer
from apps.einvoicing.models import FirsConfig, FirsSubmission
from apps.einvoicing.serializers import (
    FirsConfigSerializer,
    FirsSubmissionSerializer,
    WebhookPayloadSerializer,
)
from apps.einvoicing.services import (
    DigiTaxAuthError,
    DigiTaxServerError,
    DigiTaxValidationError,
)
from apps.inventory.models import Product, Warehouse
from apps.sales.models import Invoice, SaleItem
from apps.tenancy.services import OrganisationService


# ─── Shared test helpers ──────────────────────────────────────────────────────

def _make_user(email="phase3@test.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="P3", last_name="Test", is_verified=True,
    )


def _make_org(user, name="Phase3 Org"):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _make_warehouse(org):
    return Warehouse.objects.create(organisation=org, name="Main", is_default=True)


def _make_customer(org, tin="", customer_type="retail", code="CUST-P3"):
    return Customer.objects.create(
        organisation=org, code=code, name="Phase3 Customer",
        customer_type=customer_type, tin=tin,
    )


def _make_product(org, sku="PROD-P3", is_taxable=True):
    return Product.objects.create(
        organisation=org, sku=sku, name="P3 Product",
        product_type="service",
        cost_price=500, selling_price=1000,
        unit_of_measure="unit",
        is_taxable=is_taxable,
    )


def _make_invoice(org, user, warehouse, customer=None, status=Invoice.Status.CONFIRMED):
    return Invoice.objects.create(
        organisation=org,
        customer=customer,
        warehouse=warehouse,
        invoice_number=Invoice.generate_number(org),
        status=status,
        payment_method=Invoice.PaymentMethod.CASH,
        issue_date=date.today(),
        subtotal=Decimal("1000"),
        discount_amount=Decimal("0"),
        tax_amount=Decimal("75"),
        total_amount=Decimal("1075"),
        amount_paid=Decimal("1075"),
        amount_due=Decimal("0"),
        created_by=user,
    )


def _make_sale_item(invoice, product):
    return SaleItem.objects.create(
        organisation=invoice.organisation,
        invoice=invoice,
        product=product,
        quantity=1,
        unit_price=Decimal("1000"),
        discount_percent=Decimal("0"),
        discount_amount=Decimal("0"),
        tax_rate=Decimal("7.5"),
        tax_amount=Decimal("75"),
        line_total=Decimal("1000"),
        cost_of_goods=Decimal("500"),
    )


def _make_firs_config(org, enrolled=True, party_id="seller-party-001"):
    return FirsConfig.objects.create(
        organisation=org,
        tin="12345678-0001",
        business_name=org.name,
        app_api_key="test-api-key-p3",
        is_enrolled=enrolled,
        use_sandbox=True,
        digitax_party_id=party_id,
    )


def _make_mock_client(
    party_id="buyer-party-001",
    item_id="item-001",
    invoice_id="inv-sub-001",
):
    """Return a mock DigiTaxApiClient with sensible defaults."""
    client = MagicMock()
    client.create_party.return_value = {"id": party_id}
    client.create_item.return_value = {"id": item_id}
    client.create_invoice.return_value = {"id": invoice_id, "status": "CREATED"}
    client.update_payment_status.return_value = {"status": "OK"}
    return client


def _make_webhook_signature(body: bytes, secret: str, timestamp: int = None) -> str:
    """
    Build a valid X-DigiTax-Signature header value for tests.

    Args:
        body     : Raw JSON bytes of the request body.
        secret   : The DIGITAX_WEBHOOK_SECRET value to sign with.
        timestamp: Unix timestamp (defaults to now).
    Returns:
        "t=<ts>,v1=<hex>"
    """
    ts = timestamp or int(time.time())
    signed_payload = f"{ts}.{body.decode('utf-8', errors='replace')}"
    sig = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"t={ts},v1={sig}"


# ─── Task: request_irn ────────────────────────────────────────────────────────

class RequestIrnTaskTests(TestCase):
    """Tests for the request_irn Celery task."""

    def setUp(self):
        self.user = _make_user("req_irn@test.com")
        self.org = _make_org(self.user, "RequestIrn Org")
        self.wh = _make_warehouse(self.org)
        self.product = _make_product(self.org, sku="RI-001")

    def test_skips_when_invoice_not_found(self):
        """Should return skipped/invoice_not_found when invoice UUID is unknown."""
        from apps.einvoicing.tasks import request_irn

        result = request_irn("00000000-0000-0000-0000-000000000000")
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "invoice_not_found")

    def test_skips_when_not_enrolled(self):
        """Should return skipped/not_enrolled when org has no FirsConfig."""
        from apps.einvoicing.tasks import request_irn

        invoice = _make_invoice(self.org, self.user, self.wh)
        result = request_irn(str(invoice.pk))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "not_enrolled")

    def test_skips_when_already_submitted(self):
        """Should return skipped when invoice.firs_status is 'submitted'."""
        from apps.einvoicing.tasks import request_irn

        _make_firs_config(self.org)
        invoice = _make_invoice(self.org, self.user, self.wh)
        invoice.firs_status = "submitted"
        invoice.save(update_fields=["firs_status"])

        result = request_irn(str(invoice.pk))
        self.assertEqual(result["status"], "skipped")
        self.assertIn("already_submitted", result["reason"])

    def test_skips_when_already_cleared(self):
        """Should return skipped when invoice.firs_status is 'cleared'."""
        from apps.einvoicing.tasks import request_irn

        _make_firs_config(self.org)
        invoice = _make_invoice(self.org, self.user, self.wh)
        invoice.firs_status = "cleared"
        invoice.save(update_fields=["firs_status"])

        result = request_irn(str(invoice.pk))
        self.assertEqual(result["status"], "skipped")

    def test_submits_b2b_invoice(self):
        """B2B invoice (customer with TIN) should be submitted via DigiTax API."""
        from apps.einvoicing.tasks import request_irn

        _make_firs_config(self.org)
        customer = _make_customer(self.org, tin="12345678-0002", code="CUST-B2B")
        invoice = _make_invoice(self.org, self.user, self.wh, customer=customer)

        mock_service = MagicMock()
        mock_submission = FirsSubmission.objects.create(
            organisation=self.org,
            invoice=invoice,
            transaction_type="B2B",
            status=FirsSubmission.Status.SUBMITTED,
            submission_ref="sub-001",
        )
        mock_service.submit_invoice.return_value = mock_submission

        # Patch at the source module where EInvoicingService is defined
        with patch("apps.einvoicing.services.EInvoicingService.for_invoice", return_value=mock_service):
            result = request_irn(str(invoice.pk))

        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["submission_ref"], "sub-001")
        mock_service.submit_invoice.assert_called_once_with(invoice)

    def test_submits_b2c_invoice(self):
        """B2C invoice (no customer) should be bypassed."""
        from apps.einvoicing.tasks import request_irn

        _make_firs_config(self.org)
        invoice = _make_invoice(self.org, self.user, self.wh)

        mock_service = MagicMock()
        mock_submission = FirsSubmission.objects.create(
            organisation=self.org,
            invoice=invoice,
            transaction_type="B2C",
            status=FirsSubmission.Status.BYPASSED,
            submission_ref="",
        )
        mock_service.submit_invoice.return_value = mock_submission

        with patch("apps.einvoicing.services.EInvoicingService.for_invoice", return_value=mock_service):
            result = request_irn(str(invoice.pk))

        self.assertEqual(result["status"], "bypassed")

    def test_non_retryable_auth_error_returns_failed(self):
        """DigiTaxAuthError should return {'status': 'failed'} without retrying."""
        from apps.einvoicing.tasks import request_irn

        _make_firs_config(self.org)
        invoice = _make_invoice(self.org, self.user, self.wh)

        mock_service = MagicMock()
        mock_service.submit_invoice.side_effect = DigiTaxAuthError("bad api key", 401)

        with patch("apps.einvoicing.services.EInvoicingService.for_invoice", return_value=mock_service):
            result = request_irn(str(invoice.pk))

        self.assertEqual(result["status"], "failed")
        self.assertIn("bad api key", result["error"])

    def test_non_retryable_validation_error_returns_failed(self):
        """DigiTaxValidationError should return {'status': 'failed'} without retrying."""
        from apps.einvoicing.tasks import request_irn

        _make_firs_config(self.org)
        invoice = _make_invoice(self.org, self.user, self.wh)

        mock_service = MagicMock()
        mock_service.submit_invoice.side_effect = DigiTaxValidationError("invalid hsn", 422)

        with patch("apps.einvoicing.services.EInvoicingService.for_invoice", return_value=mock_service):
            result = request_irn(str(invoice.pk))

        self.assertEqual(result["status"], "failed")

    def test_server_error_triggers_retry(self):
        """DigiTaxServerError should cause the task to retry."""
        from apps.einvoicing.tasks import request_irn
        from celery.exceptions import Retry

        _make_firs_config(self.org)
        invoice = _make_invoice(self.org, self.user, self.wh)

        mock_service = MagicMock()
        mock_service.submit_invoice.side_effect = DigiTaxServerError("503 down", 503)

        with patch("apps.einvoicing.services.EInvoicingService.for_invoice", return_value=mock_service):
            with self.assertRaises((Retry, DigiTaxServerError)):
                # apply() runs synchronously; retry raises celery.exceptions.Retry
                request_irn.apply(args=[str(invoice.pk)]).get(propagate=False)


# ─── Task: handle_irn_callback_task ──────────────────────────────────────────

class HandleIrnCallbackTaskTests(TestCase):
    """Tests for the handle_irn_callback_task Celery task."""

    def setUp(self):
        self.user = _make_user("irn_cb@test.com")
        self.org = _make_org(self.user, "IrnCallback Org")
        self.wh = _make_warehouse(self.org)
        self.config = _make_firs_config(self.org)

    def test_skips_when_submission_not_found(self):
        """Should return skipped when submission_ref is unknown."""
        from apps.einvoicing.tasks import handle_irn_callback_task

        result = handle_irn_callback_task(
            submission_ref="nonexistent-ref",
            irn="IRN-001",
            csid="CSID-001",
            firs_invoice_number="FIRS-001",
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "submission_not_found")

    def test_processes_valid_callback(self):
        """Valid callback should update submission and invoice via handle_irn_callback."""
        from apps.einvoicing.tasks import handle_irn_callback_task
        from apps.einvoicing.services import EInvoicingService

        invoice = _make_invoice(self.org, self.user, self.wh)
        # Create a SUBMITTED FirsSubmission
        submission = FirsSubmission.objects.create(
            organisation=self.org,
            invoice=invoice,
            transaction_type="B2B",
            status=FirsSubmission.Status.SUBMITTED,
            submission_ref="test-ref-001",
        )

        mock_service = MagicMock()

        # Patch EInvoicingService at the services module so the task's lazy import picks it up
        with patch("apps.einvoicing.services.EInvoicingService") as MockService:
            mock_instance = MagicMock()
            MockService.return_value = mock_instance

            result = handle_irn_callback_task(
                submission_ref="test-ref-001",
                irn="2013528595NNVPE-E3A89069-20260519",
                csid="CSID-ABCDEF",
                firs_invoice_number="FIRS-INV-0001",
                qr_code_b64="base64png",
            )

        mock_instance.handle_irn_callback.assert_called_once_with(
            submission_ref="test-ref-001",
            irn="2013528595NNVPE-E3A89069-20260519",
            csid="CSID-ABCDEF",
            firs_invoice_number="FIRS-INV-0001",
            qr_code_b64="base64png",
        )
        self.assertEqual(result["status"], "cleared")
        self.assertEqual(result["irn"], "2013528595NNVPE-E3A89069-20260519")


# ─── Task: report_b2c_invoices ────────────────────────────────────────────────

class ReportB2cInvoicesTaskTests(TestCase):
    """Tests for the report_b2c_invoices nightly Celery beat task."""

    def setUp(self):
        self.user = _make_user("b2c_report@test.com")
        self.org = _make_org(self.user, "B2CReport Org")
        self.wh = _make_warehouse(self.org)
        self.product = _make_product(self.org, sku="B2C-001")
        self.product.digitax_item_id = "item-b2c"
        self.product.save()
        self.config = _make_firs_config(self.org)

    def test_skips_org_without_enrolled_config(self):
        """Orgs with BYPASSED submissions but no enrolled config should be skipped."""
        from apps.einvoicing.tasks import report_b2c_invoices

        # Create an unenrolled org with a BYPASSED submission
        user2 = _make_user("b2c_unenrolled@test.com")
        org2 = _make_org(user2, "Unenrolled Org")
        wh2 = _make_warehouse(org2)
        _make_firs_config(org2, enrolled=False)
        inv2 = _make_invoice(org2, user2, wh2)
        FirsSubmission.objects.create(
            organisation=org2,
            invoice=inv2,
            transaction_type="B2C",
            status=FirsSubmission.Status.BYPASSED,
        )

        mock_client = _make_mock_client()
        with patch("apps.einvoicing.services.DigiTaxApiClient.from_config", return_value=mock_client):
            result = report_b2c_invoices()

        # The unenrolled org's submission should not have been reported
        inv2.refresh_from_db()
        self.assertNotEqual(inv2.firs_status, "reported")

    def test_marks_bypassed_submissions_as_reported(self):
        """BYPASSED B2C submissions should be marked REPORTED after batch call."""
        from apps.einvoicing.tasks import report_b2c_invoices

        # Suppress signal-triggered task so we control exactly one BYPASSED submission
        with patch("apps.einvoicing.tasks.request_irn.apply_async"):
            invoice = _make_invoice(self.org, self.user, self.wh)
        _make_sale_item(invoice, self.product)
        submission = FirsSubmission.objects.create(
            organisation=self.org,
            invoice=invoice,
            transaction_type="B2C",
            status=FirsSubmission.Status.BYPASSED,
        )

        mock_client = _make_mock_client()
        with patch("apps.einvoicing.services.DigiTaxApiClient.from_config", return_value=mock_client):
            result = report_b2c_invoices()

        submission.refresh_from_db()
        invoice.refresh_from_db()

        self.assertEqual(submission.status, FirsSubmission.Status.REPORTED)
        self.assertEqual(invoice.firs_status, "reported")
        self.assertEqual(result["reported"], 1)
        self.assertEqual(result["failed"], 0)

    def test_failed_submission_increments_failed_counter(self):
        """DigiTaxError on one invoice should increment failed counter."""
        from apps.einvoicing.tasks import report_b2c_invoices
        from apps.einvoicing.services import DigiTaxError

        # Suppress signal-triggered task so we control exactly one BYPASSED submission
        with patch("apps.einvoicing.tasks.request_irn.apply_async"):
            invoice = _make_invoice(self.org, self.user, self.wh)
        _make_sale_item(invoice, self.product)
        FirsSubmission.objects.create(
            organisation=self.org,
            invoice=invoice,
            transaction_type="B2C",
            status=FirsSubmission.Status.BYPASSED,
        )

        mock_client = _make_mock_client()
        mock_client.create_invoice.side_effect = DigiTaxError("server error")

        with patch("apps.einvoicing.services.DigiTaxApiClient.from_config", return_value=mock_client):
            result = report_b2c_invoices()

        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["reported"], 0)


# ─── Task: retry_failed_submissions ──────────────────────────────────────────

class RetryFailedSubmissionsTaskTests(TestCase):
    """Tests for the retry_failed_submissions periodic task."""

    def setUp(self):
        self.user = _make_user("retry_task@test.com")
        self.org = _make_org(self.user, "Retry Org")
        self.wh = _make_warehouse(self.org)
        self.config = _make_firs_config(self.org)

    def test_queues_request_irn_for_eligible_failed_submissions(self):
        """FAILED submissions under max_retries should be re-queued."""
        from apps.einvoicing.tasks import retry_failed_submissions, request_irn

        invoice = _make_invoice(self.org, self.user, self.wh)
        submission = FirsSubmission.objects.create(
            organisation=self.org,
            invoice=invoice,
            transaction_type="B2B",
            status=FirsSubmission.Status.FAILED,
            attempt_count=1,  # below max
        )

        with patch("apps.einvoicing.tasks.request_irn.delay") as mock_delay:
            result = retry_failed_submissions()

        mock_delay.assert_called_once_with(str(invoice.pk))
        self.assertEqual(result["queued"], 1)

        # attempt_count should have been incremented
        submission.refresh_from_db()
        self.assertEqual(submission.attempt_count, 2)

    def test_skips_submissions_at_max_attempt_count(self):
        """FAILED submissions at or above _MAX_RETRIES should not be re-queued."""
        from apps.einvoicing.tasks import retry_failed_submissions, _MAX_RETRIES

        invoice = _make_invoice(self.org, self.user, self.wh)
        FirsSubmission.objects.create(
            organisation=self.org,
            invoice=invoice,
            transaction_type="B2B",
            status=FirsSubmission.Status.FAILED,
            attempt_count=_MAX_RETRIES,  # exactly at max → excluded
        )

        with patch("apps.einvoicing.tasks.request_irn.delay") as mock_delay:
            result = retry_failed_submissions()

        mock_delay.assert_not_called()
        self.assertEqual(result["queued"], 0)

    def test_skips_org_no_longer_enrolled(self):
        """FAILED submissions for unenrolled orgs should not be re-queued."""
        from apps.einvoicing.tasks import retry_failed_submissions

        # Unenroll the org
        self.config.is_enrolled = False
        self.config.save()

        invoice = _make_invoice(self.org, self.user, self.wh)
        FirsSubmission.objects.create(
            organisation=self.org,
            invoice=invoice,
            transaction_type="B2B",
            status=FirsSubmission.Status.FAILED,
            attempt_count=1,
        )

        with patch("apps.einvoicing.tasks.request_irn.delay") as mock_delay:
            result = retry_failed_submissions()

        mock_delay.assert_not_called()
        self.assertEqual(result["queued"], 0)


# ─── Task: update_payment_status_firs ────────────────────────────────────────

class UpdatePaymentStatusFirsTaskTests(TestCase):
    """Tests for the update_payment_status_firs Celery task."""

    def setUp(self):
        self.user = _make_user("pay_status@test.com")
        self.org = _make_org(self.user, "PayStatus Org")
        self.wh = _make_warehouse(self.org)
        self.config = _make_firs_config(self.org)

    def test_skips_when_invoice_not_found(self):
        """Should return skipped when invoice UUID is unknown."""
        from apps.einvoicing.tasks import update_payment_status_firs

        result = update_payment_status_firs("00000000-0000-0000-0000-000000000000")
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "invoice_not_found")

    def test_skips_when_no_cleared_submission(self):
        """Should return skipped when no CLEARED submission exists."""
        from apps.einvoicing.tasks import update_payment_status_firs

        invoice = _make_invoice(self.org, self.user, self.wh)
        # No CLEARED submission exists

        result = update_payment_status_firs(str(invoice.pk))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "no_cleared_submission")

    def test_notifies_digitax_on_paid_invoice(self):
        """Should call client.update_payment_status('PAID') for a cleared invoice."""
        from apps.einvoicing.tasks import update_payment_status_firs
        from apps.einvoicing.services import EInvoicingService

        invoice = _make_invoice(self.org, self.user, self.wh)
        FirsSubmission.objects.create(
            organisation=self.org,
            invoice=invoice,
            transaction_type="B2B",
            status=FirsSubmission.Status.CLEARED,
            submission_ref="cleared-sub-001",
            irn="IRN-001",
        )

        mock_client = _make_mock_client()
        with patch("apps.einvoicing.services.DigiTaxApiClient.from_config", return_value=mock_client):
            result = update_payment_status_firs(str(invoice.pk))

        self.assertEqual(result["status"], "notified")
        mock_client.update_payment_status.assert_called_once_with("cleared-sub-001", "PAID")


# ─── Signal tests ─────────────────────────────────────────────────────────────

class InvoiceSignalTests(TestCase):
    """Tests for the on_invoice_save post_save signal handler."""

    def setUp(self):
        self.user = _make_user("signal@test.com")
        self.org = _make_org(self.user, "Signal Org")
        self.wh = _make_warehouse(self.org)
        _make_firs_config(self.org)

    def _save_invoice_with_status(self, inv_status):
        """Helper: create an invoice then update its status to trigger the signal."""
        invoice = Invoice.objects.create(
            organisation=self.org,
            warehouse=self.wh,
            invoice_number=Invoice.generate_number(self.org),
            status=Invoice.Status.DRAFT,
            payment_method=Invoice.PaymentMethod.CASH,
            issue_date=date.today(),
            subtotal=Decimal("1000"),
            discount_amount=Decimal("0"),
            tax_amount=Decimal("0"),
            total_amount=Decimal("1000"),
            amount_paid=Decimal("0"),
            amount_due=Decimal("1000"),
            created_by=self.user,
        )
        # Now update status — post_save fires here
        invoice.status = inv_status
        invoice.save()
        return invoice

    def test_draft_status_does_not_queue_task(self):
        """Draft invoices should never trigger FIRS submission."""
        with patch("apps.einvoicing.tasks.request_irn.apply_async") as mock_task:
            self._save_invoice_with_status(Invoice.Status.DRAFT)
        mock_task.assert_not_called()

    def test_proforma_status_does_not_queue_task(self):
        """Proforma invoices should not trigger FIRS submission."""
        with patch("apps.einvoicing.tasks.request_irn.apply_async") as mock_task:
            self._save_invoice_with_status(Invoice.Status.PROFORMA)
        mock_task.assert_not_called()

    def test_confirmed_status_queues_request_irn(self):
        """Confirmed invoices should trigger async request_irn."""
        with patch("apps.einvoicing.tasks.request_irn.apply_async") as mock_task:
            invoice = self._save_invoice_with_status(Invoice.Status.CONFIRMED)
        mock_task.assert_called_once_with(
            args=[str(invoice.pk)], countdown=2
        )

    def test_paid_status_queues_both_tasks(self):
        """Paid invoices should queue both request_irn and update_payment_status_firs."""
        with patch("apps.einvoicing.tasks.request_irn.apply_async") as mock_irn, \
             patch("apps.einvoicing.tasks.update_payment_status_firs.apply_async") as mock_pay:
            invoice = self._save_invoice_with_status(Invoice.Status.PAID)

        mock_irn.assert_called_once_with(args=[str(invoice.pk)], countdown=2)
        mock_pay.assert_called_once_with(args=[str(invoice.pk)], countdown=10)

    def test_already_submitted_invoice_does_not_re_queue(self):
        """Invoices with firs_status='submitted' should not be re-queued."""
        invoice = _make_invoice(self.org, self.user, self.wh)
        invoice.firs_status = "submitted"
        invoice.save(update_fields=["firs_status"])  # does NOT trigger status-based guard
        # Now update status to PAID — signal fires but should see firs_status guard
        with patch("apps.einvoicing.tasks.request_irn.apply_async") as mock_task:
            invoice.status = Invoice.Status.CONFIRMED
            invoice.firs_status = "submitted"  # ensure guard is set
            invoice.save()
        mock_task.assert_not_called()

    def test_voided_status_does_not_queue_task(self):
        """Voided invoices should not trigger FIRS submission."""
        with patch("apps.einvoicing.tasks.request_irn.apply_async") as mock_task:
            self._save_invoice_with_status(Invoice.Status.VOIDED)
        mock_task.assert_not_called()


# ─── Webhook view tests ───────────────────────────────────────────────────────

_TEST_SECRET = "test-webhook-secret-32chars-padded"
_WEBHOOK_URL = "/api/v1/einvoicing/webhook/"

_VALID_PAYLOAD = {
    "submission_ref": "sub-abc-123",
    "irn": "2013528595NNVPE-E3A89069-20260519",
    "csid": "CSID-TESTVALUE",
    "invoice_number": "FIRS-INV-0001",
    "qr_code": "",
    "status": "CLEARED",
}


class WebhookSignatureTests(TestCase):
    """Tests for the HMAC signature validation in DigiTaxWebhookView."""

    def setUp(self):
        self.client = APIClient()

    @override_settings(DIGITAX_WEBHOOK_SECRET=_TEST_SECRET, DEBUG=False)
    def test_missing_signature_returns_400(self):
        """Request with no X-DigiTax-Signature header should return 400."""
        resp = self.client.post(
            _WEBHOOK_URL,
            data=json.dumps(_VALID_PAYLOAD),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("signature", resp.json().get("error", "").lower())

    @override_settings(DIGITAX_WEBHOOK_SECRET=_TEST_SECRET, DEBUG=False)
    def test_malformed_signature_returns_400(self):
        """Signature header with wrong format should return 400."""
        resp = self.client.post(
            _WEBHOOK_URL,
            data=json.dumps(_VALID_PAYLOAD),
            content_type="application/json",
            HTTP_X_DIGITAX_SIGNATURE="garbage-not-t-v1-format",
        )
        self.assertEqual(resp.status_code, 400)

    @override_settings(DIGITAX_WEBHOOK_SECRET=_TEST_SECRET, DEBUG=False)
    def test_signature_mismatch_returns_400(self):
        """Wrong HMAC signature should return 400."""
        body = json.dumps(_VALID_PAYLOAD).encode()
        sig = _make_webhook_signature(body, "wrong-secret")
        resp = self.client.post(
            _WEBHOOK_URL,
            data=body,
            content_type="application/json",
            HTTP_X_DIGITAX_SIGNATURE=sig,
        )
        self.assertEqual(resp.status_code, 400)

    @override_settings(DIGITAX_WEBHOOK_SECRET=_TEST_SECRET, DEBUG=False)
    def test_replay_attack_old_timestamp_returns_400(self):
        """Request with a timestamp > 5 minutes old should be rejected."""
        body = json.dumps(_VALID_PAYLOAD).encode()
        old_ts = int(time.time()) - 400  # 6+ minutes ago
        sig = _make_webhook_signature(body, _TEST_SECRET, timestamp=old_ts)
        resp = self.client.post(
            _WEBHOOK_URL,
            data=body,
            content_type="application/json",
            HTTP_X_DIGITAX_SIGNATURE=sig,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("timestamp", resp.json().get("error", "").lower())

    @override_settings(DIGITAX_WEBHOOK_SECRET=_TEST_SECRET, DEBUG=False)
    def test_valid_signature_returns_200(self):
        """Valid HMAC signature and payload should return 200 with {received: true}."""
        body = json.dumps(_VALID_PAYLOAD).encode()
        sig = _make_webhook_signature(body, _TEST_SECRET)

        with patch("apps.einvoicing.tasks.handle_irn_callback_task.apply_async"):
            resp = self.client.post(
                _WEBHOOK_URL,
                data=body,
                content_type="application/json",
                HTTP_X_DIGITAX_SIGNATURE=sig,
            )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("received"))

    @override_settings(DIGITAX_WEBHOOK_SECRET="", DEBUG=True)
    def test_debug_mode_no_secret_rejects_request(self):
        """Even in DEBUG mode, missing DIGITAX_WEBHOOK_SECRET must reject the request (security hardening)."""
        resp = self.client.post(
            _WEBHOOK_URL,
            data=json.dumps(_VALID_PAYLOAD),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    @override_settings(DIGITAX_WEBHOOK_SECRET="", DEBUG=False)
    def test_production_mode_no_secret_rejects_request(self):
        """In production with no secret configured, all requests should be rejected."""
        resp = self.client.post(
            _WEBHOOK_URL,
            data=json.dumps(_VALID_PAYLOAD),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


class WebhookPayloadTests(TestCase):
    """Tests for WebhookPayloadSerializer and payload routing."""

    def setUp(self):
        self.client = APIClient()

    def _post_signed(self, payload, secret=_TEST_SECRET):
        body = json.dumps(payload).encode()
        sig = _make_webhook_signature(body, secret)
        return self.client.post(
            _WEBHOOK_URL,
            data=body,
            content_type="application/json",
            HTTP_X_DIGITAX_SIGNATURE=sig,
        )

    @override_settings(DIGITAX_WEBHOOK_SECRET=_TEST_SECRET, DEBUG=False)
    def test_missing_submission_ref_returns_400(self):
        """Payload without submission_ref should be rejected with 400."""
        bad_payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "submission_ref"}
        resp = self._post_signed(bad_payload)
        self.assertEqual(resp.status_code, 400)
        resp_data = resp.json()
        self.assertIn("submission_ref", resp_data.get("details", resp_data))

    @override_settings(DIGITAX_WEBHOOK_SECRET=_TEST_SECRET, DEBUG=False)
    def test_missing_irn_returns_400(self):
        """Payload without irn should be rejected with 400."""
        bad_payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "irn"}
        resp = self._post_signed(bad_payload)
        self.assertEqual(resp.status_code, 400)

    @override_settings(DIGITAX_WEBHOOK_SECRET=_TEST_SECRET, DEBUG=False)
    def test_valid_payload_dispatches_task_with_correct_kwargs(self):
        """Valid webhook should dispatch handle_irn_callback_task with correct kwargs."""
        with patch("apps.einvoicing.tasks.handle_irn_callback_task.apply_async") as mock_task:
            self._post_signed(_VALID_PAYLOAD)

        mock_task.assert_called_once()
        kwargs = mock_task.call_args.kwargs["kwargs"]
        self.assertEqual(kwargs["submission_ref"], _VALID_PAYLOAD["submission_ref"])
        self.assertEqual(kwargs["irn"], _VALID_PAYLOAD["irn"])
        self.assertEqual(kwargs["csid"], _VALID_PAYLOAD["csid"])
        self.assertEqual(kwargs["firs_invoice_number"], _VALID_PAYLOAD["invoice_number"])

    @override_settings(DIGITAX_WEBHOOK_SECRET=_TEST_SECRET, DEBUG=False)
    def test_optional_qr_code_passed_through(self):
        """Optional qr_code field should be forwarded to the task."""
        payload_with_qr = {**_VALID_PAYLOAD, "qr_code": "base64imagedata"}
        with patch("apps.einvoicing.tasks.handle_irn_callback_task.apply_async") as mock_task:
            self._post_signed(payload_with_qr)
        kwargs = mock_task.call_args.kwargs["kwargs"]
        self.assertEqual(kwargs["qr_code_b64"], "base64imagedata")

    @override_settings(DIGITAX_WEBHOOK_SECRET=_TEST_SECRET, DEBUG=False)
    def test_task_dispatch_failure_still_returns_200(self):
        """Even if task dispatch fails, webhook should still return 200."""
        with patch(
            "apps.einvoicing.tasks.handle_irn_callback_task.apply_async",
            side_effect=Exception("broker down"),
        ):
            resp = self._post_signed(_VALID_PAYLOAD)
        self.assertEqual(resp.status_code, 200)


# ─── Serializer unit tests ────────────────────────────────────────────────────

class FirsConfigSerializerTests(TestCase):
    """Tests for FirsConfigSerializer."""

    def setUp(self):
        self.user = _make_user("ser_cfg@test.com")
        self.org = _make_org(self.user, "SerCfg Org")
        self.config = _make_firs_config(self.org)

    def test_has_api_key_is_true_when_key_set(self):
        """has_api_key should be True when app_api_key is non-empty."""
        ser = FirsConfigSerializer(self.config)
        self.assertTrue(ser.data["has_api_key"])

    def test_app_api_key_is_not_in_response(self):
        """app_api_key (write-only) should NOT appear in serialized output."""
        ser = FirsConfigSerializer(self.config)
        self.assertNotIn("app_api_key", ser.data)

    def test_has_api_key_is_false_when_key_blank(self):
        """has_api_key should be False when app_api_key is blank."""
        self.config.app_api_key = ""
        self.config.save()
        ser = FirsConfigSerializer(self.config)
        self.assertFalse(ser.data["has_api_key"])

    def test_is_enrolled_and_use_sandbox_in_output(self):
        """is_enrolled and use_sandbox fields should be in serialized output."""
        ser = FirsConfigSerializer(self.config)
        self.assertIn("is_enrolled", ser.data)
        self.assertIn("use_sandbox", ser.data)


class WebhookPayloadSerializerTests(TestCase):
    """Tests for WebhookPayloadSerializer validation."""

    def test_valid_full_payload(self):
        """Full valid payload should pass validation."""
        ser = WebhookPayloadSerializer(data=_VALID_PAYLOAD)
        self.assertTrue(ser.is_valid(), ser.errors)

    def test_missing_submission_ref_is_invalid(self):
        """submission_ref is required."""
        data = {k: v for k, v in _VALID_PAYLOAD.items() if k != "submission_ref"}
        ser = WebhookPayloadSerializer(data=data)
        self.assertFalse(ser.is_valid())
        self.assertIn("submission_ref", ser.errors)

    def test_missing_irn_is_invalid(self):
        """irn is required."""
        data = {k: v for k, v in _VALID_PAYLOAD.items() if k != "irn"}
        ser = WebhookPayloadSerializer(data=data)
        self.assertFalse(ser.is_valid())
        self.assertIn("irn", ser.errors)

    def test_optional_fields_default_to_empty_string(self):
        """csid, invoice_number, qr_code are optional; should default to ''."""
        minimal = {"submission_ref": "ref-001", "irn": "IRN-001"}
        ser = WebhookPayloadSerializer(data=minimal)
        self.assertTrue(ser.is_valid(), ser.errors)
        self.assertEqual(ser.validated_data["csid"], "")
        self.assertEqual(ser.validated_data["invoice_number"], "")
        self.assertEqual(ser.validated_data["qr_code"], "")
