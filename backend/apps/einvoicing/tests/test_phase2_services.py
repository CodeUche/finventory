"""
Phase 2 tests — DigiTax API client, InvoiceJsonSerializer, EInvoicingService.

All network calls are mocked via unittest.mock — no real requests are made.

Coverage:
    Unit (marker: unit)
        DigiTaxApiClient
            - correct x-api-key header is set
            - correct Content-Type header is set
            - _handle_response raises DigiTaxAuthError on 401
            - _handle_response raises DigiTaxValidationError on 400 / 422
            - _handle_response raises DigiTaxServerError on 500+
            - _handle_response raises DigiTaxNotFoundError on 404
            - _handle_response returns dict on 200 / 201
            - ConnectionError maps to DigiTaxServerError
            - Timeout maps to DigiTaxServerError
            - from_config uses sandbox URL when use_sandbox=True
            - from_config uses production URL when use_sandbox=False

        InvoiceJsonSerializer
            - resolve_transaction_type: no customer → B2C
            - resolve_transaction_type: govt customer → B2G
            - resolve_transaction_type: customer with TIN → B2B
            - resolve_transaction_type: customer without TIN → B2C
            - map_tax_category: non-taxable → E
            - map_tax_category: taxable, rate > 0 → S
            - map_tax_category: taxable, rate == 0 → Z
            - build_seller_party_payload: correct field mapping
            - build_buyer_party_payload: B2B (has TIN) includes TIN
            - build_buyer_party_payload: B2C (no TIN) uses placeholder
            - build_buyer_party_payload: walk-in (no customer) uses org fallback
            - build_item_payload: physical goods (hsn_code, GOODS category)
            - build_item_payload: service item (is_service=True, SERVICES)
            - build_invoice_payload: includes all required fields
            - build_invoice_payload: omits empty optional fields
            - build_invoice_payload: tax_point_date falls back to issue_date
            - build_invoice_payload: delivery period included when set
            - _build_invoice_items: raises ValueError when item has no digitax_item_id

    Integration (marker: integration)
        EInvoicingService
            - for_invoice returns None when org has no FirsConfig
            - for_invoice returns None when is_enrolled=False
            - for_invoice returns service when is_enrolled=True
            - ensure_seller_registered caches party_id on FirsConfig
            - ensure_seller_registered skips API call when party_id cached
            - ensure_buyer_registered caches party_id on Customer
            - ensure_buyer_registered skips API call when party_id cached
            - ensure_items_registered caches digitax_item_id on Product
            - ensure_items_registered skips API call when item_id cached
            - submit_invoice: B2C → BYPASSED (no API call to /invoices)
            - submit_invoice: B2B → SUBMITTED + FirsSubmission created
            - submit_invoice: idempotency — second call returns existing submission
            - submit_invoice: DigiTaxAuthError → submission FAILED, invoice firs_status=failed
            - submit_invoice: DigiTaxServerError → submission FAILED, re-raised
            - handle_irn_callback: updates submission + invoice with IRN
            - handle_irn_callback: noop when submission_ref not found
"""

import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch, PropertyMock

from django.test import TestCase

from apps.authentication.models import User
from apps.customers.models import Customer
from apps.einvoicing.models import FirsConfig, FirsSubmission
from apps.einvoicing.services import (
    DigiTaxApiClient,
    DigiTaxAuthError,
    DigiTaxError,
    DigiTaxNotFoundError,
    DigiTaxServerError,
    DigiTaxValidationError,
    EInvoicingService,
    InvoiceJsonSerializer,
    _extract_error_message,
    _short_id,
)
from apps.inventory.models import Product, Warehouse
from apps.sales.models import Invoice, SaleItem
from apps.tenancy.services import OrganisationService


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _make_user(email="phase2@test.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="P2", last_name="Test", is_verified=True,
    )


def _make_org(user, name="Phase2 Org"):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _make_warehouse(org):
    return Warehouse.objects.create(organisation=org, name="Main", is_default=True)


def _make_customer(org, tin="", customer_type="retail", code="C001"):
    return Customer.objects.create(
        organisation=org, code=code, name="Test Customer",
        customer_type=customer_type, tin=tin,
    )


def _make_product(org, sku="P001", hsn_code="", is_taxable=True, product_type="service"):
    return Product.objects.create(
        organisation=org, sku=sku, name="Test Product",
        product_type=product_type,
        cost_price=500, selling_price=1000,
        unit_of_measure="unit",
        is_taxable=is_taxable,
        hsn_code=hsn_code,
    )


def _make_invoice(org, user, warehouse, customer=None):
    """Create a minimal confirmed invoice directly via ORM."""
    invoice = Invoice.objects.create(
        organisation=org,
        customer=customer,
        warehouse=warehouse,
        invoice_number=Invoice.generate_number(org),
        status=Invoice.Status.CONFIRMED,
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
    return invoice


def _make_sale_item(invoice, product, quantity=1, unit_price=Decimal("1000")):
    """Add a SaleItem line to an invoice."""
    return SaleItem.objects.create(
        organisation=invoice.organisation,
        invoice=invoice,
        product=product,
        quantity=quantity,
        unit_price=unit_price,
        discount_percent=Decimal("0"),
        discount_amount=Decimal("0"),
        tax_rate=Decimal("7.5"),
        tax_amount=Decimal("75"),
        line_total=unit_price * quantity,
        cost_of_goods=Decimal("500"),
    )


def _make_firs_config(org, enrolled=True, party_id=""):
    return FirsConfig.objects.create(
        organisation=org,
        tin=org.tax_id or "12345678-0001",
        business_name=org.name,
        app_api_key="test-api-key",
        is_enrolled=enrolled,
        use_sandbox=True,
        digitax_party_id=party_id,
    )


def _mock_response(status_code: int, json_data: dict):
    """Build a mock requests.Response object."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.text = str(json_data)
    return mock


# ─── Unit tests: DigiTaxApiClient ─────────────────────────────────────────────

@pytest.mark.unit
class DigiTaxApiClientHeaderTests(TestCase):
    """Verify that the client sets the correct HTTP headers on every request."""

    def setUp(self):
        self.client = DigiTaxApiClient(
            api_key="test-key-abc",
            base_url="https://api-dev.digitax.tech/ng/v1",
        )

    def test_x_api_key_header_set(self):
        self.assertEqual(self.client._session.headers.get("x-api-key"), "test-key-abc")

    def test_content_type_header_set(self):
        self.assertEqual(self.client._session.headers.get("Content-Type"), "application/json")

    def test_accept_header_set(self):
        self.assertEqual(self.client._session.headers.get("Accept"), "application/json")


@pytest.mark.unit
class DigiTaxHandleResponseTests(TestCase):
    """Unit tests for the _handle_response static method."""

    def test_200_returns_dict(self):
        resp = _mock_response(200, {"id": "abc123"})
        result = DigiTaxApiClient._handle_response(resp, "parties")
        self.assertEqual(result, {"id": "abc123"})

    def test_201_returns_dict(self):
        resp = _mock_response(201, {"id": "new-item"})
        result = DigiTaxApiClient._handle_response(resp, "items")
        self.assertEqual(result, {"id": "new-item"})

    def test_401_raises_auth_error(self):
        resp = _mock_response(401, {"message": "Invalid API key"})
        with self.assertRaises(DigiTaxAuthError) as ctx:
            DigiTaxApiClient._handle_response(resp, "parties")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Invalid API key", ctx.exception.message)

    def test_400_raises_validation_error(self):
        resp = _mock_response(400, {"message": "Missing required field: name"})
        with self.assertRaises(DigiTaxValidationError) as ctx:
            DigiTaxApiClient._handle_response(resp, "invoices")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_422_raises_validation_error(self):
        resp = _mock_response(422, {"errors": ["TIN format invalid", "Missing HSN code"]})
        with self.assertRaises(DigiTaxValidationError) as ctx:
            DigiTaxApiClient._handle_response(resp, "invoices")
        # The errors list should be joined
        self.assertIn("TIN format invalid", ctx.exception.message)

    def test_404_raises_not_found_error(self):
        resp = _mock_response(404, {"message": "Party not found"})
        with self.assertRaises(DigiTaxNotFoundError) as ctx:
            DigiTaxApiClient._handle_response(resp, "invoices")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_500_raises_server_error(self):
        resp = _mock_response(500, {"message": "Internal server error"})
        with self.assertRaises(DigiTaxServerError) as ctx:
            DigiTaxApiClient._handle_response(resp, "invoices")
        self.assertEqual(ctx.exception.status_code, 500)

    def test_503_raises_server_error(self):
        resp = _mock_response(503, {"detail": "Service unavailable"})
        with self.assertRaises(DigiTaxServerError):
            DigiTaxApiClient._handle_response(resp, "invoices")

    def test_error_response_stores_raw_json(self):
        """The raw response dict must be attached to the exception for logging."""
        raw = {"code": "INVALID_TIN", "message": "TIN not found"}
        resp = _mock_response(400, raw)
        with self.assertRaises(DigiTaxValidationError) as ctx:
            DigiTaxApiClient._handle_response(resp, "parties")
        self.assertEqual(ctx.exception.response, raw)


@pytest.mark.unit
class DigiTaxApiClientNetworkTests(TestCase):
    """Verify that network-level errors are translated to DigiTaxServerError."""

    def setUp(self):
        self.client = DigiTaxApiClient(
            api_key="key",
            base_url="https://api-dev.digitax.tech/ng/v1",
        )

    def test_connection_error_raises_server_error(self):
        import requests as req
        with patch.object(self.client._session, "post",
                          side_effect=req.exceptions.ConnectionError("refused")):
            with self.assertRaises(DigiTaxServerError) as ctx:
                self.client.create_party({"name": "Test"})
            self.assertIn("Connection failed", ctx.exception.message)

    def test_timeout_raises_server_error(self):
        import requests as req
        with patch.object(self.client._session, "post",
                          side_effect=req.exceptions.Timeout("timed out")):
            with self.assertRaises(DigiTaxServerError) as ctx:
                self.client.create_party({"name": "Test"})
            self.assertIn("timed out", ctx.exception.message)

    def test_create_party_posts_to_correct_endpoint(self):
        """POST /parties must be called with the correct URL."""
        with patch.object(self.client._session, "post",
                          return_value=_mock_response(201, {"id": "p-123"})) as mock_post:
            self.client.create_party({"name": "Acme"})
            called_url = mock_post.call_args[0][0]
            self.assertIn("/parties", called_url)

    def test_create_item_posts_to_correct_endpoint(self):
        with patch.object(self.client._session, "post",
                          return_value=_mock_response(201, {"id": "i-456"})) as mock_post:
            self.client.create_item({"item_name": "Widget"})
            called_url = mock_post.call_args[0][0]
            self.assertIn("/items", called_url)

    def test_create_invoice_posts_to_correct_endpoint(self):
        with patch.object(self.client._session, "post",
                          return_value=_mock_response(201, {"id": "sub-789"})) as mock_post:
            self.client.create_invoice({"trader_invoice_number": "INV-001"})
            called_url = mock_post.call_args[0][0]
            self.assertIn("/invoices", called_url)

    def test_update_payment_status_uses_put(self):
        with patch.object(self.client._session, "put",
                          return_value=_mock_response(200, {"status": "PAID"})) as mock_put:
            self.client.update_payment_status("inv-abc", "PAID")
            called_url = mock_put.call_args[0][0]
            self.assertIn("inv-abc", called_url)
            self.assertIn("payment-status", called_url)


@pytest.mark.unit
class DigiTaxFromConfigTests(TestCase):
    """Test the from_config() factory method."""

    def setUp(self):
        self.user = _make_user("from_config@test.com")
        self.org = _make_org(self.user)

    def test_from_config_uses_sandbox_url_when_use_sandbox_true(self):
        cfg = _make_firs_config(self.org)
        cfg.use_sandbox = True
        cfg.save()

        with self.settings(DIGITAX_SANDBOX_URL="https://sandbox.example.com/v1"):
            client = DigiTaxApiClient.from_config(cfg)
            self.assertIn("sandbox.example.com", client.base_url)

    def test_from_config_uses_production_url_when_use_sandbox_false(self):
        cfg = _make_firs_config(self.org)
        cfg.use_sandbox = False
        cfg.app_base_url = "https://api.digitax.tech/ng/v1"
        cfg.save()

        client = DigiTaxApiClient.from_config(cfg)
        self.assertIn("api.digitax.tech", client.base_url)

    def test_from_config_uses_org_api_key(self):
        cfg = _make_firs_config(self.org)
        cfg.app_api_key = "org-specific-key"
        cfg.save()

        client = DigiTaxApiClient.from_config(cfg)
        self.assertEqual(client._session.headers.get("x-api-key"), "org-specific-key")


# ─── Unit tests: InvoiceJsonSerializer ───────────────────────────────────────

@pytest.mark.unit
class TransactionTypeResolutionTests(TestCase):
    """Verify B2B / B2G / B2C resolution logic."""

    def setUp(self):
        self.user = _make_user("txtype@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)

    def _make_inv(self, customer=None):
        return _make_invoice(self.org, self.user, self.warehouse, customer=customer)

    def test_no_customer_is_b2c(self):
        invoice = self._make_inv(customer=None)
        self.assertEqual(InvoiceJsonSerializer.resolve_transaction_type(invoice), "B2C")

    def test_government_customer_is_b2g(self):
        customer = _make_customer(self.org, customer_type="government")
        invoice = self._make_inv(customer=customer)
        self.assertEqual(InvoiceJsonSerializer.resolve_transaction_type(invoice), "B2G")

    def test_customer_with_tin_is_b2b(self):
        customer = _make_customer(self.org, tin="26224023-8761")
        invoice = self._make_inv(customer=customer)
        self.assertEqual(InvoiceJsonSerializer.resolve_transaction_type(invoice), "B2B")

    def test_customer_without_tin_is_b2c(self):
        customer = _make_customer(self.org, tin="")
        invoice = self._make_inv(customer=customer)
        self.assertEqual(InvoiceJsonSerializer.resolve_transaction_type(invoice), "B2C")

    def test_government_customer_with_tin_is_still_b2g(self):
        """
        Government type takes priority over TIN presence for transaction type.
        """
        customer = _make_customer(
            self.org, tin="12345678-GOVT", customer_type="government"
        )
        invoice = self._make_inv(customer=customer)
        self.assertEqual(InvoiceJsonSerializer.resolve_transaction_type(invoice), "B2G")

    def test_tin_whitespace_only_is_b2c(self):
        """TIN containing only whitespace must not trigger B2B."""
        customer = _make_customer(self.org, tin="   ")
        invoice = self._make_inv(customer=customer)
        self.assertEqual(InvoiceJsonSerializer.resolve_transaction_type(invoice), "B2C")


@pytest.mark.unit
class TaxCategoryMappingTests(TestCase):
    """Verify tax category code mapping (S / Z / E)."""

    def test_non_taxable_maps_to_exempt(self):
        self.assertEqual(
            InvoiceJsonSerializer.map_tax_category(is_taxable=False, tax_rate=Decimal("0")), "E"
        )

    def test_taxable_with_rate_maps_to_standard(self):
        self.assertEqual(
            InvoiceJsonSerializer.map_tax_category(is_taxable=True, tax_rate=Decimal("7.5")), "S"
        )

    def test_taxable_zero_rate_maps_to_zero_rated(self):
        self.assertEqual(
            InvoiceJsonSerializer.map_tax_category(is_taxable=True, tax_rate=Decimal("0")), "Z"
        )

    def test_non_taxable_ignores_rate(self):
        """Even if rate is set, non-taxable always gives E."""
        self.assertEqual(
            InvoiceJsonSerializer.map_tax_category(is_taxable=False, tax_rate=Decimal("7.5")), "E"
        )


@pytest.mark.unit
class PartyPayloadBuilderTests(TestCase):
    """Verify seller and buyer party payload construction."""

    def setUp(self):
        self.user = _make_user("party_payload@test.com")
        self.org = _make_org(self.user)
        self.org.email = "billing@acme.com"
        self.org.address = "10 Acme Street, Lagos"
        self.org.tax_id = "ACME-TIN-001"
        self.org.save()

    def test_seller_payload_contains_name(self):
        payload = InvoiceJsonSerializer.build_seller_party_payload(self.org)
        self.assertIn("name", payload)
        self.assertTrue(len(payload["name"]) > 0)

    def test_seller_payload_contains_email(self):
        payload = InvoiceJsonSerializer.build_seller_party_payload(self.org)
        self.assertIn("email", payload)

    def test_seller_payload_contains_address(self):
        payload = InvoiceJsonSerializer.build_seller_party_payload(self.org)
        self.assertIn("address", payload)
        self.assertEqual(payload["address"], "10 Acme Street, Lagos")

    def test_seller_payload_contains_tin(self):
        payload = InvoiceJsonSerializer.build_seller_party_payload(self.org)
        self.assertIn("tax_identification_number", payload)

    def test_buyer_payload_b2b_includes_tin(self):
        customer = _make_customer(self.org, tin="BUYER-TIN-001")
        payload = InvoiceJsonSerializer.build_buyer_party_payload(customer, self.org)
        self.assertEqual(payload["tax_identification_number"], "BUYER-TIN-001")

    def test_buyer_payload_b2c_no_tin(self):
        customer = _make_customer(self.org, tin="")
        payload = InvoiceJsonSerializer.build_buyer_party_payload(customer, self.org)
        # TIN field present but empty for B2C
        self.assertEqual(payload.get("tax_identification_number", ""), "")

    def test_buyer_payload_walkin_uses_org_address(self):
        """Walk-in (no customer) must fall back to org address."""
        payload = InvoiceJsonSerializer.build_buyer_party_payload(None, self.org)
        self.assertIn("address", payload)

    def test_seller_payload_reference_id_is_stable(self):
        """Same org always produces the same reference_id (deterministic)."""
        p1 = InvoiceJsonSerializer.build_seller_party_payload(self.org)
        p2 = InvoiceJsonSerializer.build_seller_party_payload(self.org)
        self.assertEqual(p1["reference_id"], p2["reference_id"])


@pytest.mark.unit
class ItemPayloadBuilderTests(TestCase):
    """Verify product item payload construction."""

    def setUp(self):
        self.user = _make_user("item_payload@test.com")
        self.org = _make_org(self.user)

    def test_physical_product_payload_has_goods_category(self):
        product = _make_product(self.org, product_type="physical", hsn_code="22042190")
        payload = InvoiceJsonSerializer.build_item_payload(product)
        self.assertEqual(payload["product_category"], "GOODS")

    def test_service_product_payload_has_services_category(self):
        product = _make_product(self.org, product_type="service")
        payload = InvoiceJsonSerializer.build_item_payload(product)
        self.assertEqual(payload["product_category"], "SERVICES")
        self.assertTrue(payload["is_service"])

    def test_digital_product_treated_as_service(self):
        product = _make_product(self.org, product_type="digital")
        payload = InvoiceJsonSerializer.build_item_payload(product)
        self.assertTrue(payload["is_service"])

    def test_hsn_code_included_for_physical(self):
        product = _make_product(self.org, product_type="physical", hsn_code="22042190")
        payload = InvoiceJsonSerializer.build_item_payload(product)
        self.assertEqual(payload["hsn_code"], "22042190")

    def test_item_payload_contains_required_fields(self):
        product = _make_product(self.org)
        payload = InvoiceJsonSerializer.build_item_payload(product)
        for field in ("item_name", "description", "tax_category_code", "product_category"):
            self.assertIn(field, payload, msg=f"Missing field: {field}")

    def test_non_taxable_product_maps_to_exempt(self):
        product = _make_product(self.org, is_taxable=False)
        payload = InvoiceJsonSerializer.build_item_payload(product)
        self.assertEqual(payload["tax_category_code"], "E")

    def test_item_unit_price_is_float(self):
        product = _make_product(self.org)
        payload = InvoiceJsonSerializer.build_item_payload(product)
        self.assertIsInstance(payload["unit_price"], float)


@pytest.mark.unit
class InvoicePayloadBuilderTests(TestCase):
    """Verify the invoice-level JSON payload construction."""

    def setUp(self):
        self.user = _make_user("inv_payload@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)
        self.customer = _make_customer(self.org, tin="TIN-001")
        self.product = _make_product(self.org, sku="IPROD")
        self.invoice = _make_invoice(
            self.org, self.user, self.warehouse, customer=self.customer
        )
        self.sale_item = _make_sale_item(self.invoice, self.product)
        # Pre-populate DigiTax item_id (normally done by ensure_items_registered)
        self.product.digitax_item_id = "dtx-item-001"
        self.product.save()

    def test_invoice_payload_has_trader_invoice_number(self):
        payload = InvoiceJsonSerializer.build_invoice_payload(
            self.invoice, "seller-1", "buyer-1",
            {str(self.product.id): "dtx-item-001"},
        )
        self.assertEqual(payload["trader_invoice_number"], self.invoice.invoice_number)

    def test_invoice_payload_has_invoice_date(self):
        payload = InvoiceJsonSerializer.build_invoice_payload(
            self.invoice, "seller-1", "buyer-1",
            {str(self.product.id): "dtx-item-001"},
        )
        self.assertEqual(payload["invoice_date"], str(self.invoice.issue_date))

    def test_invoice_payload_includes_items_array(self):
        payload = InvoiceJsonSerializer.build_invoice_payload(
            self.invoice, "seller-1", "buyer-1",
            {str(self.product.id): "dtx-item-001"},
        )
        self.assertIn("items", payload)
        self.assertEqual(len(payload["items"]), 1)

    def test_invoice_payload_has_correct_currency(self):
        payload = InvoiceJsonSerializer.build_invoice_payload(
            self.invoice, "seller-1", "buyer-1",
            {str(self.product.id): "dtx-item-001"},
        )
        self.assertEqual(payload["document_currency_code"], "NGN")

    def test_invoice_payload_tax_point_date_falls_back_to_issue_date(self):
        """When tax_point_date is None, issue_date is used."""
        self.invoice.tax_point_date = None
        self.invoice.save()
        payload = InvoiceJsonSerializer.build_invoice_payload(
            self.invoice, "seller-1", "buyer-1",
            {str(self.product.id): "dtx-item-001"},
        )
        self.assertEqual(payload["tax_point_date"], str(self.invoice.issue_date))

    def test_invoice_payload_callback_url_omitted_when_empty(self):
        payload = InvoiceJsonSerializer.build_invoice_payload(
            self.invoice, "seller-1", "buyer-1",
            {str(self.product.id): "dtx-item-001"},
            callback_url="",
        )
        self.assertNotIn("callback_url", payload)

    def test_invoice_payload_includes_callback_url_when_set(self):
        payload = InvoiceJsonSerializer.build_invoice_payload(
            self.invoice, "seller-1", "buyer-1",
            {str(self.product.id): "dtx-item-001"},
            callback_url="https://api.example.com/webhook/",
        )
        self.assertEqual(payload["callback_url"], "https://api.example.com/webhook/")

    def test_invoice_payload_delivery_period_included_when_set(self):
        self.invoice.delivery_start = date(2026, 5, 1)
        self.invoice.delivery_end = date(2026, 5, 31)
        self.invoice.save()
        payload = InvoiceJsonSerializer.build_invoice_payload(
            self.invoice, "seller-1", "buyer-1",
            {str(self.product.id): "dtx-item-001"},
        )
        self.assertIn("invoice_delivery_period", payload)
        self.assertEqual(payload["invoice_delivery_period"]["start_date"], "2026-05-01")

    def test_invoice_payload_raises_when_item_has_no_digitax_id(self):
        """ValueError when item_id_map is missing a product — programmer error."""
        with self.assertRaises(ValueError) as ctx:
            InvoiceJsonSerializer.build_invoice_payload(
                self.invoice, "seller-1", "buyer-1",
                item_id_map={},  # empty — product not registered
            )
        self.assertIn("no DigiTax item_id", str(ctx.exception))

    def test_invoice_items_have_correct_quantity(self):
        payload = InvoiceJsonSerializer.build_invoice_payload(
            self.invoice, "seller-1", "buyer-1",
            {str(self.product.id): "dtx-item-001"},
        )
        self.assertEqual(payload["items"][0]["quantity"], float(self.sale_item.quantity))


# ─── Integration tests: EInvoicingService ────────────────────────────────────

@pytest.mark.integration
class EInvoicingServiceFactoryTests(TestCase):
    """Test the for_invoice() factory method."""

    def setUp(self):
        self.user = _make_user("svc_factory@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)

    def test_returns_none_when_no_firs_config(self):
        invoice = _make_invoice(self.org, self.user, self.warehouse)
        svc = EInvoicingService.for_invoice(invoice)
        self.assertIsNone(svc)

    def test_returns_none_when_not_enrolled(self):
        _make_firs_config(self.org, enrolled=False)
        invoice = _make_invoice(self.org, self.user, self.warehouse)
        svc = EInvoicingService.for_invoice(invoice)
        self.assertIsNone(svc)

    def test_returns_service_when_enrolled(self):
        _make_firs_config(self.org, enrolled=True)
        invoice = _make_invoice(self.org, self.user, self.warehouse)
        svc = EInvoicingService.for_invoice(invoice)
        self.assertIsNotNone(svc)
        self.assertIsInstance(svc, EInvoicingService)


@pytest.mark.integration
class EInvoicingServicePartyRegistrationTests(TestCase):
    """Test party registration with mocked DigiTax API."""

    def setUp(self):
        self.user = _make_user("party_reg@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)
        self.config = _make_firs_config(self.org, enrolled=True)
        # Inject a mock client to avoid real HTTP
        self.mock_client = MagicMock(spec=DigiTaxApiClient)
        self.svc = EInvoicingService(self.config, client=self.mock_client)

    def test_ensure_seller_registered_calls_create_party(self):
        self.mock_client.create_party.return_value = {"id": "seller-party-001"}
        party_id = self.svc.ensure_seller_registered()
        self.mock_client.create_party.assert_called_once()
        self.assertEqual(party_id, "seller-party-001")

    def test_ensure_seller_registered_caches_party_id(self):
        self.mock_client.create_party.return_value = {"id": "seller-party-001"}
        self.svc.ensure_seller_registered()
        # Reload config from DB to verify persistence
        self.config.refresh_from_db()
        self.assertEqual(self.config.digitax_party_id, "seller-party-001")

    def test_ensure_seller_registered_skips_api_when_cached(self):
        """If party_id is already set, DigiTax must not be called again."""
        self.config.digitax_party_id = "cached-party-id"
        self.config.save()
        party_id = self.svc.ensure_seller_registered()
        self.mock_client.create_party.assert_not_called()
        self.assertEqual(party_id, "cached-party-id")

    def test_ensure_buyer_registered_caches_on_customer(self):
        customer = _make_customer(self.org, tin="BUYER-TIN")
        self.mock_client.create_party.return_value = {"id": "buyer-party-007"}
        party_id = self.svc.ensure_buyer_registered(customer)
        customer.refresh_from_db()
        self.assertEqual(customer.digitax_party_id, "buyer-party-007")
        self.assertEqual(party_id, "buyer-party-007")

    def test_ensure_buyer_registered_skips_api_when_cached(self):
        customer = _make_customer(self.org)
        customer.digitax_party_id = "cached-buyer-id"
        customer.save()
        party_id = self.svc.ensure_buyer_registered(customer)
        self.mock_client.create_party.assert_not_called()
        self.assertEqual(party_id, "cached-buyer-id")


@pytest.mark.integration
class EInvoicingServiceItemRegistrationTests(TestCase):
    """Test item registration with mocked DigiTax API."""

    def setUp(self):
        self.user = _make_user("item_reg@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)
        self.config = _make_firs_config(self.org, enrolled=True)
        self.mock_client = MagicMock(spec=DigiTaxApiClient)
        self.svc = EInvoicingService(self.config, client=self.mock_client)

    def test_ensure_items_registered_caches_item_id(self):
        product = _make_product(self.org, sku="ITEMREG")
        invoice = _make_invoice(self.org, self.user, self.warehouse)
        _make_sale_item(invoice, product)

        self.mock_client.create_item.return_value = {"id": "dtx-item-999"}
        item_map = self.svc.ensure_items_registered(invoice)

        product.refresh_from_db()
        self.assertEqual(product.digitax_item_id, "dtx-item-999")
        self.assertIn(str(product.id), item_map)

    def test_ensure_items_registered_skips_api_when_cached(self):
        product = _make_product(self.org, sku="CACHED")
        product.digitax_item_id = "already-registered"
        product.save()
        invoice = _make_invoice(self.org, self.user, self.warehouse)
        _make_sale_item(invoice, product)

        item_map = self.svc.ensure_items_registered(invoice)
        self.mock_client.create_item.assert_not_called()
        self.assertEqual(item_map[str(product.id)], "already-registered")

    def test_ensure_items_registered_handles_multiple_products(self):
        p1 = _make_product(self.org, sku="MULTI1")
        p2 = _make_product(self.org, sku="MULTI2")
        invoice = _make_invoice(self.org, self.user, self.warehouse)
        _make_sale_item(invoice, p1)
        _make_sale_item(invoice, p2)

        self.mock_client.create_item.side_effect = [
            {"id": "dtx-001"},
            {"id": "dtx-002"},
        ]
        item_map = self.svc.ensure_items_registered(invoice)
        self.assertEqual(len(item_map), 2)
        self.assertEqual(self.mock_client.create_item.call_count, 2)


@pytest.mark.integration
class EInvoicingServiceSubmitTests(TestCase):
    """Test the full submit_invoice flow with mocked network."""

    def setUp(self):
        self.user = _make_user("submit@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)
        self.config = _make_firs_config(self.org, enrolled=True, party_id="seller-001")
        self.mock_client = MagicMock(spec=DigiTaxApiClient)
        self.svc = EInvoicingService(self.config, client=self.mock_client)

    def _make_b2b_invoice(self):
        customer = _make_customer(self.org, tin="B2B-TIN-001")
        customer.digitax_party_id = "buyer-001"
        customer.save()
        product = _make_product(self.org, sku="SUBMITP")
        product.digitax_item_id = "item-001"
        product.save()
        invoice = _make_invoice(self.org, self.user, self.warehouse, customer=customer)
        _make_sale_item(invoice, product)
        return invoice

    def _make_b2c_invoice(self):
        product = _make_product(self.org, sku="B2CPROD")
        product.digitax_item_id = "item-b2c"
        product.save()
        invoice = _make_invoice(self.org, self.user, self.warehouse, customer=None)
        _make_sale_item(invoice, product)
        return invoice

    # ── B2C bypass ────────────────────────────────────────────────────────────

    def test_b2c_invoice_bypassed_no_api_call(self):
        """B2C invoices must be bypassed (no POST /invoices) — queued for batch."""
        invoice = self._make_b2c_invoice()
        submission = self.svc.submit_invoice(invoice)
        self.mock_client.create_invoice.assert_not_called()
        self.assertEqual(submission.status, FirsSubmission.Status.BYPASSED)
        self.assertEqual(submission.transaction_type, "B2C")

    def test_b2c_invoice_firs_status_set_to_bypassed(self):
        invoice = self._make_b2c_invoice()
        self.svc.submit_invoice(invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice.firs_status, "bypassed")
        self.assertEqual(invoice.firs_transaction_type, "B2C")

    # ── B2B submission ────────────────────────────────────────────────────────

    def test_b2b_invoice_calls_create_invoice(self):
        invoice = self._make_b2b_invoice()
        self.mock_client.create_invoice.return_value = {"id": "sub-ref-001"}
        self.svc.submit_invoice(invoice)
        self.mock_client.create_invoice.assert_called_once()

    def test_b2b_submission_creates_firs_submission_row(self):
        invoice = self._make_b2b_invoice()
        self.mock_client.create_invoice.return_value = {"id": "sub-ref-002"}
        submission = self.svc.submit_invoice(invoice)
        self.assertEqual(submission.status, FirsSubmission.Status.SUBMITTED)
        self.assertEqual(submission.submission_ref, "sub-ref-002")
        self.assertEqual(submission.transaction_type, "B2B")

    def test_b2b_invoice_firs_status_set_to_submitted(self):
        invoice = self._make_b2b_invoice()
        self.mock_client.create_invoice.return_value = {"id": "sub-ref-003"}
        self.svc.submit_invoice(invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice.firs_status, "submitted")
        self.assertEqual(invoice.firs_transaction_type, "B2B")

    def test_b2b_submission_payload_stored_in_audit_row(self):
        """Full payload JSON must be persisted on the FirsSubmission row."""
        invoice = self._make_b2b_invoice()
        self.mock_client.create_invoice.return_value = {"id": "sub-ref-004"}
        submission = self.svc.submit_invoice(invoice)
        self.assertIn("trader_invoice_number", submission.payload_json)

    # ── Idempotency ────────────────────────────────────────────────────────────

    def test_second_submit_returns_existing_submission(self):
        """Calling submit_invoice twice must not double-submit."""
        invoice = self._make_b2b_invoice()
        self.mock_client.create_invoice.return_value = {"id": "sub-ref-idem"}
        sub1 = self.svc.submit_invoice(invoice)
        sub2 = self.svc.submit_invoice(invoice)
        # Only one API call — second call found existing SUBMITTED row
        self.mock_client.create_invoice.assert_called_once()
        self.assertEqual(sub1.id, sub2.id)

    # ── Error handling ────────────────────────────────────────────────────────

    def test_auth_error_marks_submission_failed(self):
        invoice = self._make_b2b_invoice()
        self.mock_client.create_invoice.side_effect = DigiTaxAuthError(
            "Invalid API key", status_code=401
        )
        with self.assertRaises(DigiTaxAuthError):
            self.svc.submit_invoice(invoice)

        submission = FirsSubmission.objects.filter(invoice=invoice).first()
        self.assertIsNotNone(submission)
        self.assertEqual(submission.status, FirsSubmission.Status.FAILED)
        self.assertIn("Invalid API key", submission.error_detail)

    def test_validation_error_marks_submission_failed_non_retryable(self):
        invoice = self._make_b2b_invoice()
        self.mock_client.create_invoice.side_effect = DigiTaxValidationError(
            "Missing HSN code", status_code=422
        )
        with self.assertRaises(DigiTaxValidationError):
            self.svc.submit_invoice(invoice)

        invoice.refresh_from_db()
        self.assertEqual(invoice.firs_status, "failed")

    def test_server_error_marks_submission_failed_and_reraises(self):
        """DigiTaxServerError is retryable — must be re-raised so Celery can retry."""
        invoice = self._make_b2b_invoice()
        self.mock_client.create_invoice.side_effect = DigiTaxServerError(
            "Service temporarily unavailable", status_code=503
        )
        with self.assertRaises(DigiTaxServerError):
            self.svc.submit_invoice(invoice)

        submission = FirsSubmission.objects.filter(invoice=invoice).first()
        self.assertEqual(submission.status, FirsSubmission.Status.FAILED)


@pytest.mark.integration
class EInvoicingServiceIrnCallbackTests(TestCase):
    """Test handle_irn_callback: updating submission + invoice with IRN data."""

    def setUp(self):
        self.user = _make_user("irn_cb@test.com")
        self.org = _make_org(self.user)
        self.warehouse = _make_warehouse(self.org)
        self.config = _make_firs_config(self.org, enrolled=True, party_id="seller-001")
        self.mock_client = MagicMock(spec=DigiTaxApiClient)
        self.svc = EInvoicingService(self.config, client=self.mock_client)

    def test_handle_irn_callback_updates_submission_to_cleared(self):
        invoice = _make_invoice(self.org, self.user, self.warehouse)
        submission = FirsSubmission.objects.create(
            organisation=self.org,
            invoice=invoice,
            submission_ref="sub-ref-irn",
            status=FirsSubmission.Status.SUBMITTED,
            transaction_type="B2B",
        )
        self.svc.handle_irn_callback(
            submission_ref="sub-ref-irn",
            irn="2013528595NNVPE-E3A89069-20260515",
            csid="csid-abc123",
            firs_invoice_number="FRS-2026-000042",
        )
        submission.refresh_from_db()
        self.assertEqual(submission.status, FirsSubmission.Status.CLEARED)
        self.assertEqual(submission.irn, "2013528595NNVPE-E3A89069-20260515")
        self.assertEqual(submission.csid, "csid-abc123")
        self.assertIsNotNone(submission.cleared_at)

    def test_handle_irn_callback_updates_invoice_firs_fields(self):
        invoice = _make_invoice(self.org, self.user, self.warehouse)
        FirsSubmission.objects.create(
            organisation=self.org,
            invoice=invoice,
            submission_ref="sub-ref-inv-update",
            status=FirsSubmission.Status.SUBMITTED,
            transaction_type="B2B",
        )
        self.svc.handle_irn_callback(
            submission_ref="sub-ref-inv-update",
            irn="TEST-IRN-001",
            csid="CSID-001",
            firs_invoice_number="FRS-2026-001",
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.firs_status, "cleared")
        self.assertEqual(invoice.firs_irn, "TEST-IRN-001")
        self.assertEqual(invoice.firs_invoice_number, "FRS-2026-001")
        self.assertEqual(invoice.firs_csid, "CSID-001")

    def test_handle_irn_callback_noop_on_unknown_ref(self):
        """Unknown submission_ref must not raise — log warning and return."""
        # Should not raise; just logs a warning
        self.svc.handle_irn_callback(
            submission_ref="nonexistent-ref",
            irn="SOME-IRN",
            csid="SOME-CSID",
            firs_invoice_number="FRS-NONE",
        )
        # Verify no FirsSubmission was created
        self.assertEqual(FirsSubmission.objects.filter(submission_ref="nonexistent-ref").count(), 0)


# ─── Unit tests: helper functions ────────────────────────────────────────────

@pytest.mark.unit
class HelperFunctionTests(TestCase):
    """Test internal helper functions."""

    def test_short_id_is_8_chars(self):
        result = _short_id("550e8400-e29b-41d4-a716-446655440000")
        self.assertEqual(len(result), 8)

    def test_short_id_is_stable(self):
        """Same input always produces same output (deterministic)."""
        uid = "550e8400-e29b-41d4-a716-446655440000"
        self.assertEqual(_short_id(uid), _short_id(uid))

    def test_short_id_differs_for_different_uuids(self):
        id1 = _short_id("550e8400-e29b-41d4-a716-446655440000")
        id2 = _short_id("660f9500-f30c-52e5-b827-557766551111")
        self.assertNotEqual(id1, id2)

    def test_extract_error_message_from_message_key(self):
        result = _extract_error_message({"message": "Bad TIN"}, 400, "parties")
        self.assertEqual(result, "Bad TIN")

    def test_extract_error_message_from_error_key(self):
        result = _extract_error_message({"error": "Unauthorized"}, 401, "invoices")
        self.assertEqual(result, "Unauthorized")

    def test_extract_error_message_from_errors_list(self):
        result = _extract_error_message({"errors": ["Field A missing", "Field B invalid"]}, 422, "items")
        self.assertIn("Field A missing", result)
        self.assertIn("Field B invalid", result)

    def test_extract_error_message_fallback(self):
        result = _extract_error_message({}, 500, "invoices")
        self.assertIn("500", result)
        self.assertIn("invoices", result)
