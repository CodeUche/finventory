"""
Phase 5 tests — Invoice serializer FIRS fields + PDF data contract.

Coverage:
    Unit (marker: unit)
        - InvoiceSerializer.Meta.fields includes all five FIRS fields
        - InvoiceSerializer.Meta.read_only_fields includes all five FIRS fields

    Integration (marker: integration)
        - Invoice API list response includes FIRS fields with default values
        - Invoice API detail response includes FIRS fields
        - FIRS fields reflect updated model values after IRN is set
        - FIRS fields are read-only: PATCH with firs_irn is silently ignored

    API (marker: api)
        - POST /sales/invoices/ response body contains firs_status = 'not_enrolled'
        - firs_qr_code is present in response (empty string by default)
        - After programmatic IRN update, GET returns the cleared IRN + QR data
        - Attempting to PATCH firs_status via the API does not alter the value
        - Unauthenticated requests to invoice endpoints return 401

All tests use SQLite in-memory via config.settings.testing.
No real network calls are made — DigiTax API is not contacted in Phase 5.
"""

import json
import pytest
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.customers.models import Customer
from apps.einvoicing.models import FirsConfig
from apps.inventory.models import Product, Warehouse
from apps.sales.models import Invoice
from apps.sales.serializers import InvoiceSerializer
from apps.tenancy.services import OrganisationService


# ─── Shared test helpers ──────────────────────────────────────────────────────

def _make_user(email="phase5_owner@test.com"):
    """Create a verified user for test organisations."""
    return User.objects.create_user(
        email=email,
        password="TestPass123!",
        first_name="Phase5",
        last_name="Owner",
        is_verified=True,
    )


def _make_org(user, name="Phase5 Test Org"):
    """Create a fully initialised organisation via the service layer."""
    return OrganisationService.create_organisation(
        name=name,
        owner=user,
        extra={"currency": "NGN", "country": "NG"},
    )


def _make_warehouse(org):
    return Warehouse.objects.create(organisation=org, name="Main", is_default=True)


def _make_customer(org):
    return Customer.objects.create(
        organisation=org,
        code="C001",
        name="Test Customer",
    )


def _make_product(org):
    return Product.objects.create(
        organisation=org,
        sku="PROD001",
        name="Test Service",
        product_type="service",
        cost_price=500,
        selling_price=1000,
        unit_of_measure="unit",
    )


def _make_firs_config(org, enrolled=False):
    """Create a FirsConfig for an org, optionally marking it enrolled."""
    return FirsConfig.objects.create(
        organisation=org,
        tin="12345678-0001",
        business_name=org.name,
        app_api_key="test-api-key",
        is_enrolled=enrolled,
        use_sandbox=True,
    )


def _auth_client(user, org):
    """Return an APIClient authenticated as the given user + org."""
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return client


# ─── FIRS fields we expect to be present ─────────────────────────────────────

_FIRS_FIELDS = {"firs_status", "firs_irn", "firs_invoice_number", "firs_csid", "firs_qr_code"}


# ─── Unit tests: InvoiceSerializer meta ──────────────────────────────────────

@pytest.mark.unit
class InvoiceSerializerMetaTests(TestCase):
    """
    Pure unit tests that verify the serializer's declared field and
    read_only_field lists without touching the database or HTTP layer.
    """

    def test_all_firs_fields_in_serializer_fields(self):
        """All five FIRS fields must appear in InvoiceSerializer.Meta.fields."""
        declared = set(InvoiceSerializer.Meta.fields)
        missing = _FIRS_FIELDS - declared
        self.assertEqual(
            missing, set(),
            f"InvoiceSerializer.Meta.fields is missing FIRS fields: {missing}",
        )

    def test_all_firs_fields_are_read_only(self):
        """All five FIRS fields must be in read_only_fields so the API cannot write them."""
        read_only = set(InvoiceSerializer.Meta.read_only_fields)
        not_read_only = _FIRS_FIELDS - read_only
        self.assertEqual(
            not_read_only, set(),
            f"FIRS fields are NOT read-only: {not_read_only}. "
            "Clients must not be able to overwrite FIRS state.",
        )

    def test_serializer_instantiates_without_errors(self):
        """InvoiceSerializer() should be importable and instantiable."""
        s = InvoiceSerializer()
        self.assertIsNotNone(s)


# ─── Integration tests: Invoice model + serializer ───────────────────────────

@pytest.mark.integration
class InvoiceSerializerIntegrationTests(TestCase):
    """
    Integration tests that instantiate an Invoice in the DB and verify that
    InvoiceSerializer produces the expected FIRS field values.
    """

    def setUp(self):
        self.user = _make_user("p5_int@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)
        self.customer = _make_customer(self.org)
        self.product = _make_product(self.org)

    def _make_invoice(self, **overrides):
        """Create a minimal Invoice record directly in the database."""
        from datetime import date
        defaults = dict(
            organisation=self.org,
            customer=self.customer,
            warehouse=self.warehouse,
            invoice_number=Invoice.generate_number(self.org),
            status="confirmed",
            payment_method="cash",
            issue_date=date.today(),
            subtotal=1000,
            discount_amount=0,
            tax_amount=0,
            total_amount=1000,
            amount_paid=0,
            amount_due=1000,
            created_by=self.user,
            firs_status="not_enrolled",
        )
        defaults.update(overrides)
        return Invoice.objects.create(**defaults)

    def test_default_firs_status_is_not_enrolled(self):
        """A newly created invoice serializes with firs_status='not_enrolled'."""
        invoice = self._make_invoice()
        data = InvoiceSerializer(invoice).data
        self.assertEqual(data["firs_status"], "not_enrolled")

    def test_default_firs_irn_is_empty(self):
        """firs_irn defaults to an empty string before FIRS clearance."""
        invoice = self._make_invoice()
        data = InvoiceSerializer(invoice).data
        self.assertEqual(data["firs_irn"], "")

    def test_default_firs_qr_code_is_empty(self):
        """firs_qr_code defaults to an empty string before QR generation."""
        invoice = self._make_invoice()
        data = InvoiceSerializer(invoice).data
        self.assertEqual(data["firs_qr_code"], "")

    def test_cleared_invoice_serializes_firs_fields(self):
        """After programmatic update, serializer reflects the new IRN and QR values."""
        invoice = self._make_invoice()
        # Simulate what EInvoicingService.handle_irn_callback writes
        invoice.firs_status = "cleared"
        invoice.firs_irn = "IRN-2025-0001"
        invoice.firs_invoice_number = "FIRS-INV-0001"
        invoice.firs_csid = "CSID-TEST-0001"
        invoice.firs_qr_code = "base64encodedpng=="
        invoice.save()

        data = InvoiceSerializer(invoice).data
        self.assertEqual(data["firs_status"], "cleared")
        self.assertEqual(data["firs_irn"], "IRN-2025-0001")
        self.assertEqual(data["firs_invoice_number"], "FIRS-INV-0001")
        self.assertEqual(data["firs_csid"], "CSID-TEST-0001")
        self.assertEqual(data["firs_qr_code"], "base64encodedpng==")

    def test_all_firs_fields_present_in_serialized_output(self):
        """Every FIRS key must appear in the serialized dict."""
        invoice = self._make_invoice()
        data = InvoiceSerializer(invoice).data
        for field in _FIRS_FIELDS:
            self.assertIn(field, data, f"Missing FIRS field in serialized output: {field}")

    def test_firs_fields_read_only_at_model_level(self):
        """
        Creating an InvoiceSerializer with write data for FIRS fields must not
        raise an error but must silently exclude the read-only inputs.
        """
        invoice = self._make_invoice()
        # Supply read-only FIRS fields as if they came from a PATCH body
        s = InvoiceSerializer(
            invoice,
            data={"firs_irn": "INJECTED-IRN", "notes": "ok"},
            partial=True,
        )
        self.assertTrue(s.is_valid(), s.errors)
        # firs_irn must not appear in validated_data (stripped by read_only)
        self.assertNotIn("firs_irn", s.validated_data)


# ─── API tests: HTTP layer ─────────────────────────────────────────────────────

@pytest.mark.api
class InvoiceFirsFieldsApiTests(TestCase):
    """
    End-to-end API tests that drive the Invoice endpoints through APIClient
    and verify the FIRS fields surface correctly in HTTP responses.
    """

    def setUp(self):
        from unittest.mock import patch
        self.user = _make_user("p5_api@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)
        self.customer = _make_customer(self.org)
        self.product = _make_product(self.org)
        self.client = _auth_client(self.user, self.org)

    def _create_invoice_via_api(self):
        """
        POST a minimal invoice through the API and return the response data.
        The signal is suppressed to keep these tests focused on serializer output.
        """
        from unittest.mock import patch
        payload = {
            "customer_id": str(self.customer.id),
            "warehouse_id": str(self.warehouse.id),
            "status": "confirmed",
            "payment_method": "cash",
            "issue_date": "2025-05-01",
            "items": [
                {
                    "product_id": str(self.product.id),
                    "quantity": "1",
                    "unit_price": "1000.00",
                }
            ],
        }
        # Suppress Celery task queuing from the post_save signal so these tests
        # focus purely on the serializer output, not the task/submission layer.
        with patch("apps.einvoicing.tasks.request_irn.apply_async"):
            resp = self.client.post("/api/v1/sales/invoices/", payload, format="json")
        return resp

    def test_create_invoice_response_contains_firs_status(self):
        """POST /sales/invoices/ response must include firs_status='not_enrolled'."""
        resp = self._create_invoice_via_api()
        self.assertIn(resp.status_code, [200, 201], resp.data)
        self.assertIn("firs_status", resp.data)
        self.assertEqual(resp.data["firs_status"], "not_enrolled")

    def test_create_invoice_response_contains_firs_irn_empty(self):
        """firs_irn must be an empty string in a freshly-created invoice."""
        resp = self._create_invoice_via_api()
        self.assertIn(resp.status_code, [200, 201], resp.data)
        self.assertEqual(resp.data.get("firs_irn"), "")

    def test_create_invoice_response_contains_firs_qr_code_empty(self):
        """firs_qr_code must be empty before DigiTax sends the webhook."""
        resp = self._create_invoice_via_api()
        self.assertIn(resp.status_code, [200, 201], resp.data)
        self.assertEqual(resp.data.get("firs_qr_code"), "")

    def test_invoice_detail_reflects_programmatic_firs_update(self):
        """
        After EInvoicingService updates the FIRS fields (simulated here via ORM),
        GET /sales/invoices/<id>/ must return the updated values.
        """
        from unittest.mock import patch
        # Create invoice
        resp = self._create_invoice_via_api()
        self.assertIn(resp.status_code, [200, 201])
        invoice_id = resp.data["id"]

        # Simulate DigiTax webhook updating the invoice
        Invoice.objects.filter(pk=invoice_id).update(
            firs_status="cleared",
            firs_irn="IRN-API-TEST-001",
            firs_invoice_number="FIRS-0001",
            firs_csid="CSID-API-001",
            firs_qr_code="dGVzdHFy",  # base64 "testqr"
        )

        # GET the detail view
        detail_resp = self.client.get(f"/api/v1/sales/invoices/{invoice_id}/")
        self.assertEqual(detail_resp.status_code, 200)
        data = detail_resp.data
        self.assertEqual(data["firs_status"], "cleared")
        self.assertEqual(data["firs_irn"], "IRN-API-TEST-001")
        self.assertEqual(data["firs_invoice_number"], "FIRS-0001")
        self.assertEqual(data["firs_csid"], "CSID-API-001")
        self.assertEqual(data["firs_qr_code"], "dGVzdHFy")

    def test_patch_firs_irn_is_silently_ignored(self):
        """
        PATCH /sales/invoices/<id>/ with firs_irn must not alter the stored value.
        Read-only fields are stripped by DRF before validation.
        """
        resp = self._create_invoice_via_api()
        self.assertIn(resp.status_code, [200, 201])
        invoice_id = resp.data["id"]

        # Attempt to overwrite the read-only field via PATCH
        patch_resp = self.client.patch(
            f"/api/v1/sales/invoices/{invoice_id}/",
            {"firs_irn": "INJECTED-IRN"},
            format="json",
        )
        # Must succeed (not 400) — DRF just ignores the read-only field
        self.assertIn(patch_resp.status_code, [200, 201])
        # The value must remain unmodified (still empty string)
        self.assertEqual(patch_resp.data.get("firs_irn"), "")

    def test_patch_firs_status_is_silently_ignored(self):
        """PATCH with firs_status must not overwrite the backend-managed value."""
        resp = self._create_invoice_via_api()
        self.assertIn(resp.status_code, [200, 201])
        invoice_id = resp.data["id"]

        patch_resp = self.client.patch(
            f"/api/v1/sales/invoices/{invoice_id}/",
            {"firs_status": "cleared"},
            format="json",
        )
        self.assertIn(patch_resp.status_code, [200, 201])
        # Status must still be not_enrolled — cannot be client-written
        self.assertEqual(patch_resp.data.get("firs_status"), "not_enrolled")

    def test_invoice_list_includes_firs_fields(self):
        """GET /sales/invoices/ list response must include FIRS fields per invoice."""
        self._create_invoice_via_api()
        list_resp = self.client.get("/api/v1/sales/invoices/")
        self.assertEqual(list_resp.status_code, 200)

        results = list_resp.data
        # Handle both paginated and non-paginated responses
        if isinstance(results, dict) and "results" in results:
            results = results["results"]

        self.assertGreater(len(results), 0, "Expected at least one invoice in the list")
        first = results[0]
        for field in _FIRS_FIELDS:
            self.assertIn(field, first, f"List response missing FIRS field: {field}")

    def test_unauthenticated_request_returns_401(self):
        """Invoice endpoints must require authentication."""
        unauth_client = APIClient()
        resp = unauth_client.get("/api/v1/sales/invoices/")
        self.assertEqual(resp.status_code, 401)


# ─── Integration test: enrolled org FIRS field lifecycle ─────────────────────

@pytest.mark.integration
class FirsFieldLifecycleTests(TestCase):
    """
    Tests the complete lifecycle of FIRS fields on an invoice:
    not_enrolled → submitted → cleared, mirroring what the backend tasks do.
    These run against the real ORM without mocking the serializer.
    """

    def setUp(self):
        self.user = _make_user("p5_lifecycle@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)
        self.customer = _make_customer(self.org)
        self.client = _auth_client(self.user, self.org)

    def _invoice(self):
        """Create an invoice directly in the ORM."""
        from datetime import date
        return Invoice.objects.create(
            organisation=self.org,
            customer=self.customer,
            warehouse=self.warehouse,
            invoice_number=Invoice.generate_number(self.org),
            status="confirmed",
            payment_method="cash",
            issue_date=date.today(),
            subtotal=1000,
            discount_amount=0,
            tax_amount=0,
            total_amount=1000,
            amount_paid=0,
            amount_due=1000,
            created_by=self.user,
            firs_status="not_enrolled",
        )

    def test_not_enrolled_then_cleared_transition(self):
        """
        Verify the serializer correctly reflects each stage of the FIRS lifecycle
        as the backend updates the model fields.
        """
        invoice = self._invoice()

        # Stage 1: not_enrolled (default)
        data = InvoiceSerializer(invoice).data
        self.assertEqual(data["firs_status"], "not_enrolled")
        self.assertEqual(data["firs_irn"], "")

        # Stage 2: submitted — task has called DigiTax but IRN not yet received
        invoice.firs_status = "submitted"
        invoice.save()
        data = InvoiceSerializer(invoice).data
        self.assertEqual(data["firs_status"], "submitted")
        self.assertEqual(data["firs_irn"], "")  # still empty until callback

        # Stage 3: cleared — webhook callback has populated IRN + QR
        invoice.firs_status = "cleared"
        invoice.firs_irn = "IRN-LIFECYCLE-001"
        invoice.firs_qr_code = "cXJkYXRh"  # base64 "qrdata"
        invoice.save()
        data = InvoiceSerializer(invoice).data
        self.assertEqual(data["firs_status"], "cleared")
        self.assertEqual(data["firs_irn"], "IRN-LIFECYCLE-001")
        self.assertEqual(data["firs_qr_code"], "cXJkYXRh")

    def test_failed_status_lifecycle(self):
        """A FAILED submission must surface correctly via the serializer."""
        invoice = self._invoice()
        invoice.firs_status = "failed"
        invoice.save()
        data = InvoiceSerializer(invoice).data
        self.assertEqual(data["firs_status"], "failed")

    def test_bypassed_status_lifecycle(self):
        """A BYPASSED (B2C) invoice must surface correctly via the serializer."""
        invoice = self._invoice()
        invoice.firs_status = "bypassed"
        invoice.save()
        data = InvoiceSerializer(invoice).data
        self.assertEqual(data["firs_status"], "bypassed")
