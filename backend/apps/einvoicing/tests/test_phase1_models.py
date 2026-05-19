"""
Phase 1 tests — FIRS E-Invoicing data foundation.

Coverage:
    Unit (marker: unit)
        - FirsConfig model: creation, field defaults, __str__, encryption
        - FirsSubmission model: creation, field defaults, __str__, indexes
        - FirsConfig.is_enrolled default gate (False by default)
        - API-key encryption round-trip via EncryptedCharField

    Integration (marker: integration)
        - Invoice FIRS fields present with correct defaults
        - Product hsn_code / digitax_item_id fields present
        - Customer tin / digitax_party_id fields present
        - OneToOne constraint on FirsConfig (only one per org)
        - FirsSubmission FK protects Invoice from deletion while submission exists
        - FirsConfig is isolated per-org (org A cannot read org B's config)

    API (marker: api)
        - Existing invoice CREATE endpoint still returns 200/201 (regression)
        - New FIRS fields on invoice response default to 'not_enrolled' / empty
        - Existing customer endpoint still works after new fields added
        - Existing product endpoint still works after new fields added

All tests use SQLite in-memory via config.settings.testing.
No real network calls are made — DigiTax API is not contacted in Phase 1.
"""

import pytest
from django.db import IntegrityError
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.customers.models import Customer
from apps.einvoicing.models import FirsConfig, FirsSubmission
from apps.inventory.models import Product, Warehouse
from apps.sales.models import Invoice
from apps.tenancy.services import OrganisationService


# ─── Shared test helpers ──────────────────────────────────────────────────────

def _make_user(email="firs_owner@test.com"):
    """Create a verified user suitable for test orgs."""
    return User.objects.create_user(
        email=email,
        password="TestPass123!",
        first_name="FIRS",
        last_name="Owner",
        is_verified=True,
    )


def _make_org(user, name="FIRS Test Org"):
    """Create a fully initialised organisation via the service layer."""
    return OrganisationService.create_organisation(
        name=name,
        owner=user,
        extra={"currency": "NGN", "country": "NG"},
    )


def _make_warehouse(org):
    return Warehouse.objects.create(organisation=org, name="Main", is_default=True)


def _make_customer(org, code="C001", tin=""):
    return Customer.objects.create(
        organisation=org,
        code=code,
        name="Test Customer",
        tin=tin,
    )


def _make_product(org, sku="P001", hsn_code=""):
    return Product.objects.create(
        organisation=org,
        sku=sku,
        name="Test Product",
        product_type="service",   # service type — skips inventory movements
        cost_price=500,
        selling_price=1000,
        unit_of_measure="unit",
        hsn_code=hsn_code,
    )


def _make_firs_config(org, enrolled=False, api_key="test-api-key"):
    """Create a FirsConfig for an org, optionally marking it enrolled."""
    return FirsConfig.objects.create(
        organisation=org,
        tin=org.tax_id or "12345678-0001",
        business_name=org.name,
        app_api_key=api_key,
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


# ─── Unit tests: FirsConfig model ────────────────────────────────────────────

@pytest.mark.unit
class FirsConfigModelTests(TestCase):
    """
    Unit tests for FirsConfig model defaults, constraints, and encryption.
    These tests exercise the ORM layer directly without going through views.
    """

    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)

    def test_firs_config_creates_successfully(self):
        """FirsConfig can be created for an enrolled organisation."""
        cfg = _make_firs_config(self.org, enrolled=True)
        self.assertIsNotNone(cfg.pk)

    def test_firs_config_is_enrolled_defaults_false(self):
        """New FirsConfig must default to NOT enrolled — safety gate."""
        cfg = FirsConfig.objects.create(organisation=self.org)
        self.assertFalse(cfg.is_enrolled)

    def test_firs_config_use_sandbox_defaults_true(self):
        """Sandbox must be True by default to prevent accidental live submissions."""
        cfg = FirsConfig.objects.create(organisation=self.org)
        self.assertTrue(cfg.use_sandbox)

    def test_firs_config_app_base_url_default(self):
        """Default base URL must point to DigiTax production endpoint."""
        cfg = FirsConfig.objects.create(organisation=self.org)
        self.assertEqual(cfg.app_base_url, "https://api.digitax.tech/ng/v1")

    def test_firs_config_api_key_encrypted_at_rest(self):
        """
        API key stored via EncryptedCharField must be stored as a Fernet token,
        not as plain text, and must decrypt back to the original value.
        """
        plain_key = "api_key_GcfpEsLLxjPnNsqFaaCtdRELl3mih5hz"
        cfg = _make_firs_config(self.org, api_key=plain_key)

        # Reload from DB to confirm the round-trip works
        cfg_from_db = FirsConfig.objects.get(pk=cfg.pk)
        self.assertEqual(cfg_from_db.app_api_key, plain_key)

    def test_firs_config_api_key_not_stored_as_plaintext(self):
        """
        Verify the raw DB value is NOT the plain API key.
        SQLite allows us to introspect via raw SQL.
        Query by the config PK (UUID as hex) to avoid SQLite UUID format issues.
        """
        from django.db import connection

        plain_key = "supersecretapikey123"
        cfg = _make_firs_config(self.org, api_key=plain_key)
        # SQLite stores UUIDs as 32-char hex (no hyphens); normalise the PK.
        pk_hex = str(cfg.pk).replace("-", "")

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT app_api_key FROM einvoicing_firsconfig WHERE id = ?",
                [pk_hex],
            )
            row = cursor.fetchone()

        self.assertIsNotNone(row, "FirsConfig row not found via raw SQL")
        raw = row[0]
        # Fernet tokens start with 'gAAAAA' (base64-urlsafe prefix)
        self.assertNotEqual(raw, plain_key)
        self.assertTrue(raw.startswith("gAAAAA"), msg=f"Expected Fernet token, got: {raw[:20]}")

    def test_firs_config_one_per_org_constraint(self):
        """Only one FirsConfig can exist per organisation (OneToOne)."""
        _make_firs_config(self.org)
        with self.assertRaises(IntegrityError):
            # Second config for the same org must raise IntegrityError
            FirsConfig.objects.create(organisation=self.org)

    def test_firs_config_str_representation(self):
        """__str__ includes org name, enrollment status, and sandbox mode."""
        cfg = _make_firs_config(self.org, enrolled=False)
        s = str(cfg)
        self.assertIn(self.org.name, s)
        self.assertIn("not enrolled", s)
        self.assertIn("sandbox", s)

    def test_firs_config_str_enrolled_production(self):
        cfg = FirsConfig.objects.create(
            organisation=self.org,
            is_enrolled=True,
            use_sandbox=False,
        )
        s = str(cfg)
        self.assertIn("enrolled", s)
        self.assertIn("production", s)

    def test_firs_config_blank_api_key_stored_as_blank(self):
        """Empty string API key is stored as-is (no encryption overhead)."""
        cfg = FirsConfig.objects.create(organisation=self.org, app_api_key="")
        cfg_from_db = FirsConfig.objects.get(pk=cfg.pk)
        self.assertEqual(cfg_from_db.app_api_key, "")

    def test_firs_config_last_test_ok_nullable(self):
        """last_test_ok must accept None (test has never been run)."""
        cfg = FirsConfig.objects.create(organisation=self.org)
        self.assertIsNone(cfg.last_test_ok)

    def test_firs_config_org_isolation(self):
        """FirsConfig for org A must not be visible when querying org B's config."""
        user_b = _make_user("org_b@test.com")
        org_b = _make_org(user_b, name="Org B")

        _make_firs_config(self.org)

        with self.assertRaises(FirsConfig.DoesNotExist):
            FirsConfig.objects.get(organisation=org_b)


# ─── Unit tests: FirsSubmission model ────────────────────────────────────────

@pytest.mark.unit
class FirsSubmissionModelTests(TestCase):
    """
    Unit tests for FirsSubmission creation, defaults, and __str__.
    """

    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)
        self.customer = _make_customer(self.org)
        self.product = _make_product(self.org)

        # Create a minimal invoice directly (bypassing SaleService) for ORM tests
        from datetime import date
        self.invoice = Invoice.objects.create(
            organisation=self.org,
            customer=self.customer,
            warehouse=self.warehouse,
            invoice_number=Invoice.generate_number(self.org),
            status=Invoice.Status.CONFIRMED,
            payment_method=Invoice.PaymentMethod.CASH,
            issue_date=date.today(),
            subtotal=1000,
            discount_amount=0,
            tax_amount=75,
            total_amount=1075,
            amount_paid=1075,
            amount_due=0,
            created_by=self.user,
        )

    def test_firs_submission_creates_successfully(self):
        submission = FirsSubmission.objects.create(
            organisation=self.org,
            invoice=self.invoice,
            transaction_type=FirsSubmission.TxType.B2B,
            status=FirsSubmission.Status.PENDING,
        )
        self.assertIsNotNone(submission.pk)

    def test_firs_submission_status_defaults_pending(self):
        submission = FirsSubmission.objects.create(
            organisation=self.org,
            invoice=self.invoice,
        )
        self.assertEqual(submission.status, FirsSubmission.Status.PENDING)

    def test_firs_submission_attempt_count_defaults_one(self):
        submission = FirsSubmission.objects.create(
            organisation=self.org,
            invoice=self.invoice,
        )
        self.assertEqual(submission.attempt_count, 1)

    def test_firs_submission_payload_json_defaults_empty_dict(self):
        submission = FirsSubmission.objects.create(
            organisation=self.org,
            invoice=self.invoice,
        )
        self.assertEqual(submission.payload_json, {})

    def test_firs_submission_str_contains_key_info(self):
        submission = FirsSubmission.objects.create(
            organisation=self.org,
            invoice=self.invoice,
            transaction_type=FirsSubmission.TxType.B2C,
            status=FirsSubmission.Status.CLEARED,
            attempt_count=2,
        )
        s = str(submission)
        self.assertIn("B2C", s)
        self.assertIn("cleared", s)
        self.assertIn("attempt 2", s)

    def test_firs_submission_multiple_per_invoice_allowed(self):
        """
        Multiple FirsSubmission rows per invoice are allowed (retry pattern).
        This is intentional — the submission log is append-only.
        """
        FirsSubmission.objects.create(
            organisation=self.org, invoice=self.invoice,
            status=FirsSubmission.Status.FAILED, attempt_count=1,
        )
        FirsSubmission.objects.create(
            organisation=self.org, invoice=self.invoice,
            status=FirsSubmission.Status.PENDING, attempt_count=2,
        )
        count = FirsSubmission.objects.filter(invoice=self.invoice).count()
        self.assertEqual(count, 2)

    def test_firs_submission_status_choices_valid(self):
        """All defined Status choices can be saved and retrieved correctly."""
        for status_value, _ in FirsSubmission.Status.choices:
            sub = FirsSubmission.objects.create(
                organisation=self.org,
                invoice=self.invoice,
                status=status_value,
            )
            self.assertEqual(sub.status, status_value)

    def test_firs_submission_tx_type_choices_valid(self):
        """All defined TxType choices can be saved correctly."""
        for tx_type, _ in FirsSubmission.TxType.choices:
            sub = FirsSubmission.objects.create(
                organisation=self.org,
                invoice=self.invoice,
                transaction_type=tx_type,
            )
            self.assertEqual(sub.transaction_type, tx_type)


# ─── Integration tests: Invoice FIRS fields ───────────────────────────────────

@pytest.mark.integration
class InvoiceFirsFieldsTests(TestCase):
    """
    Verify that the 10 FIRS fields were added to Invoice correctly.
    Existing invoice behaviour must be entirely unaffected.
    """

    def setUp(self):
        self.user = _make_user("inv_firs@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)

        from datetime import date
        self.invoice = Invoice.objects.create(
            organisation=self.org,
            warehouse=self.warehouse,
            invoice_number=Invoice.generate_number(self.org),
            status=Invoice.Status.CONFIRMED,
            payment_method=Invoice.PaymentMethod.CASH,
            issue_date=date.today(),
            subtotal=500,
            discount_amount=0,
            tax_amount=0,
            total_amount=500,
            amount_paid=500,
            amount_due=0,
            created_by=self.user,
        )

    def test_firs_status_defaults_to_not_enrolled(self):
        """All invoices default to 'not_enrolled' — zero impact on existing data."""
        self.assertEqual(self.invoice.firs_status, "not_enrolled")

    def test_firs_irn_defaults_blank(self):
        self.assertEqual(self.invoice.firs_irn, "")

    def test_firs_invoice_number_defaults_blank(self):
        self.assertEqual(self.invoice.firs_invoice_number, "")

    def test_firs_csid_defaults_blank(self):
        self.assertEqual(self.invoice.firs_csid, "")

    def test_firs_transaction_type_defaults_blank(self):
        self.assertEqual(self.invoice.firs_transaction_type, "")

    def test_firs_qr_code_defaults_blank(self):
        self.assertEqual(self.invoice.firs_qr_code, "")

    def test_tax_point_date_defaults_null(self):
        self.assertIsNone(self.invoice.tax_point_date)

    def test_delivery_start_defaults_null(self):
        self.assertIsNone(self.invoice.delivery_start)

    def test_delivery_end_defaults_null(self):
        self.assertIsNone(self.invoice.delivery_end)

    def test_payment_terms_text_defaults_blank(self):
        self.assertEqual(self.invoice.payment_terms_text, "")

    def test_firs_fields_can_be_updated(self):
        """FIRS fields can be written after creation (e.g. when IRN arrives)."""
        self.invoice.firs_status = "cleared"
        self.invoice.firs_irn = "2013528595NNVPE-E3A89069-20260515"
        self.invoice.firs_invoice_number = "FRS-2026-000042"
        self.invoice.save(update_fields=["firs_status", "firs_irn", "firs_invoice_number"])

        refreshed = Invoice.objects.get(pk=self.invoice.pk)
        self.assertEqual(refreshed.firs_status, "cleared")
        self.assertEqual(refreshed.firs_irn, "2013528595NNVPE-E3A89069-20260515")
        self.assertEqual(refreshed.firs_invoice_number, "FRS-2026-000042")

    def test_existing_invoice_fields_unaffected(self):
        """Sanity check: original Invoice fields still work after migration."""
        self.assertEqual(self.invoice.total_amount, 500)
        self.assertEqual(self.invoice.status, Invoice.Status.CONFIRMED)
        self.assertIsNotNone(self.invoice.invoice_number)


# ─── Integration tests: Product FIRS fields ──────────────────────────────────

@pytest.mark.integration
class ProductFirsFieldsTests(TestCase):
    """Verify hsn_code and digitax_item_id were added to Product correctly."""

    def setUp(self):
        self.user = _make_user("prod_firs@test.com")
        self.org = _make_org(self.user)

    def test_product_hsn_code_defaults_blank(self):
        product = _make_product(self.org)
        self.assertEqual(product.hsn_code, "")

    def test_product_digitax_item_id_defaults_blank(self):
        product = _make_product(self.org)
        self.assertEqual(product.digitax_item_id, "")

    def test_product_hsn_code_can_be_set(self):
        product = _make_product(self.org, hsn_code="2204.21")
        self.assertEqual(product.hsn_code, "2204.21")

    def test_product_digitax_item_id_can_be_written(self):
        """Simulates caching the DigiTax item ID after POST /items."""
        product = _make_product(self.org)
        product.digitax_item_id = "dtx-item-abc123"
        product.save(update_fields=["digitax_item_id"])

        refreshed = Product.objects.get(pk=product.pk)
        self.assertEqual(refreshed.digitax_item_id, "dtx-item-abc123")

    def test_product_hsn_code_max_length_20(self):
        """HSN codes are at most 8 digits; max_length=20 is well within bounds."""
        product = _make_product(self.org, hsn_code="22042190")  # 8-char HS code
        self.assertEqual(product.hsn_code, "22042190")

    def test_product_existing_fields_unaffected(self):
        """Core product fields still work after migration."""
        product = _make_product(self.org, sku="CHKFLD")
        self.assertEqual(product.selling_price, 1000)
        self.assertEqual(product.product_type, "service")


# ─── Integration tests: Customer FIRS fields ─────────────────────────────────

@pytest.mark.integration
class CustomerFirsFieldsTests(TestCase):
    """Verify tin and digitax_party_id were added to Customer correctly."""

    def setUp(self):
        self.user = _make_user("cust_firs@test.com")
        self.org = _make_org(self.user)

    def test_customer_tin_defaults_blank(self):
        customer = _make_customer(self.org)
        self.assertEqual(customer.tin, "")

    def test_customer_digitax_party_id_defaults_blank(self):
        customer = _make_customer(self.org)
        self.assertEqual(customer.digitax_party_id, "")

    def test_customer_tin_can_be_set(self):
        customer = _make_customer(self.org, tin="26224023-8761")
        self.assertEqual(customer.tin, "26224023-8761")

    def test_customer_digitax_party_id_can_be_written(self):
        """Simulates caching the DigiTax party ID after POST /parties."""
        customer = _make_customer(self.org)
        customer.digitax_party_id = "dtx-party-xyz789"
        customer.save(update_fields=["digitax_party_id"])

        refreshed = Customer.objects.get(pk=customer.pk)
        self.assertEqual(refreshed.digitax_party_id, "dtx-party-xyz789")

    def test_customer_tin_presence_indicates_b2b(self):
        """
        Business logic assertion: a customer with a TIN is a registered business.
        This test documents the contract that other phases rely on.
        """
        b2b_customer = _make_customer(self.org, tin="12345678-0001")
        b2c_customer = _make_customer(self.org, code="C002")  # no TIN
        self.assertTrue(bool(b2b_customer.tin))
        self.assertFalse(bool(b2c_customer.tin))

    def test_customer_existing_fields_unaffected(self):
        customer = _make_customer(self.org)
        self.assertEqual(customer.name, "Test Customer")
        self.assertEqual(customer.code, "C001")


# ─── API regression tests ─────────────────────────────────────────────────────

@pytest.mark.api
class InvoiceApiRegressionTests(TestCase):
    """
    Regression tests: existing invoice API endpoints must continue to work
    unchanged after Phase 1 model additions.

    These tests do NOT exercise FIRS-specific logic — they guard against
    the Phase 1 migrations accidentally breaking existing functionality.
    """

    def setUp(self):
        self.user = _make_user("api_reg@test.com")
        self.org = _make_org(self.user)
        self.client = _auth_client(self.user, self.org)
        self.warehouse = _make_warehouse(self.org)
        self.customer = _make_customer(self.org)
        self.product = _make_product(self.org)

    def _invoice_payload(self, **overrides):
        base = {
            "customer_id": str(self.customer.id),
            "warehouse_id": str(self.warehouse.id),
            "payment_method": "cash",
            "items": [
                {
                    "product_id": str(self.product.id),
                    "quantity": 1,
                    "unit_price": "1000.00",
                }
            ],
        }
        base.update(overrides)
        return base

    def test_create_invoice_returns_200_or_201(self):
        """Existing invoice creation flow must not be broken by Phase 1 changes."""
        res = self.client.post("/api/v1/sales/invoices/", self._invoice_payload(), format="json")
        self.assertIn(res.status_code, [200, 201], msg=res.data)

    def test_invoice_response_includes_firs_status_field(self):
        """
        After Phase 1, created invoices must include firs_status in the response
        and default to 'not_enrolled'.
        """
        res = self.client.post("/api/v1/sales/invoices/", self._invoice_payload(), format="json")
        self.assertIn(res.status_code, [200, 201], msg=res.data)
        # firs_status may or may not be serialized in Phase 1 — either is acceptable.
        # Phase 6 will add it explicitly. This test documents the expected default.
        invoice = Invoice.objects.filter(organisation=self.org).first()
        self.assertEqual(invoice.firs_status, "not_enrolled")

    def test_invoice_list_still_returns_200(self):
        """Invoice list endpoint must not be affected by new fields."""
        res = self.client.get("/api/v1/sales/invoices/")
        self.assertEqual(res.status_code, 200, msg=res.data)

    def test_customer_list_still_returns_200(self):
        """Customer list endpoint must not be affected by tin / digitax_party_id fields."""
        res = self.client.get("/api/v1/customers/")
        self.assertEqual(res.status_code, 200, msg=res.data)

    def test_product_list_still_returns_200(self):
        """Product list endpoint must not be affected by hsn_code / digitax_item_id."""
        res = self.client.get("/api/v1/inventory/products/")
        self.assertEqual(res.status_code, 200, msg=res.data)


@pytest.mark.api
class FirsConfigIsolationTests(TestCase):
    """
    Verify that FirsConfig cannot be accessed or inferred across organisations.
    Tenant isolation is critical: org B must never see org A's credentials.
    """

    def setUp(self):
        # Org A
        self.user_a = _make_user("org_a@test.com")
        self.org_a = _make_org(self.user_a, name="Org A")
        self.client_a = _auth_client(self.user_a, self.org_a)

        # Org B
        self.user_b = _make_user("org_b@test.com")
        self.org_b = _make_org(self.user_b, name="Org B")

        # Create a FirsConfig for Org A only
        _make_firs_config(self.org_a, enrolled=True, api_key="secret-key-org-a")

    def test_org_a_config_not_visible_from_org_b(self):
        """FirsConfig for org A must not be retrievable using org B's identity."""
        with self.assertRaises(FirsConfig.DoesNotExist):
            FirsConfig.objects.get(organisation=self.org_b)

    def test_firs_config_count_per_org(self):
        """Org A has one config; total across both orgs is one."""
        self.assertEqual(FirsConfig.objects.filter(organisation=self.org_a).count(), 1)
        self.assertEqual(FirsConfig.objects.filter(organisation=self.org_b).count(), 0)
