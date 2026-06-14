"""
FIRS E-Invoicing service layer.

Architecture
============
Three distinct responsibilities, each in its own class:

    DigiTaxApiClient
        Pure HTTP wrapper around the DigiTax REST API.
        No Django ORM. No business logic. Just HTTP ↔ dict.
        Raises typed DigiTaxError subclasses on failure so callers
        can decide whether to retry or mark the submission as FAILED.

    InvoiceJsonSerializer
        Pure data transformer: Audity ORM objects → DigiTax JSON dicts.
        No I/O, no network, no DB writes. Fully unit-testable in isolation.
        Transaction-type resolution (B2B / B2G / B2C) lives here.

    EInvoicingService
        Orchestrator. Calls the client, updates the ORM, writes FirsSubmission
        audit rows. This is the only class that touches the database.
        All DigiTax interactions go through this class — never call the client
        or serializer directly from views / tasks.

Usage flow (Phase 3 Celery task will call this)
================================================
    service = EInvoicingService(firs_config)
    submission = service.submit_invoice(invoice)
    # submission.status == 'submitted' → webhook will fire with IRN later
    # submission.status == 'bypassed'  → B2C, will appear in nightly batch

Retry safety
============
All methods are idempotent. Calling submit_invoice() twice on the same invoice
is safe: the second call detects the existing SUBMITTED/CLEARED status and
returns the existing FirsSubmission without re-hitting DigiTax.
"""

import hashlib
import logging
from datetime import date
from decimal import Decimal
from typing import Optional

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


# ─── Exception hierarchy ──────────────────────────────────────────────────────

class DigiTaxError(Exception):
    """
    Base exception for all DigiTax API failures.

    Attributes:
        message    : Human-readable description (shown in FirsSubmission.error_detail).
        status_code: HTTP status from DigiTax (None for network-level failures).
        response   : Raw response dict (None if no HTTP response received).
    """

    def __init__(self, message: str, status_code: int | None = None, response: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response = response or {}


class DigiTaxAuthError(DigiTaxError):
    """
    401 Unauthorized — invalid or missing API key.
    Non-retryable: operator must fix credentials before retrying.
    """


class DigiTaxValidationError(DigiTaxError):
    """
    400 / 422 Bad Request — DigiTax rejected the payload as invalid.
    Non-retryable: payload must be corrected (e.g. missing HSN code, bad TIN).
    """


class DigiTaxServerError(DigiTaxError):
    """
    5xx from DigiTax — temporary server-side failure.
    Retryable: Celery task will retry with exponential backoff.
    """


class DigiTaxNotFoundError(DigiTaxError):
    """
    404 — referenced party or item ID does not exist on DigiTax.
    Non-retryable but recoverable: clear the cached digitax_party_id /
    digitax_item_id and re-register, then resubmit.
    """


# ─── DigiTax API Client ───────────────────────────────────────────────────────

class DigiTaxApiClient:
    """
    Thin HTTP wrapper around the DigiTax REST API (ng/v1).

    Every public method returns a parsed JSON dict on success.
    On failure it raises the appropriate DigiTaxError subclass so the caller
    can decide whether to log-and-retry or mark the submission as permanently FAILED.

    Thread-safety: Each client instance owns its own requests.Session.
    Do not share instances across threads.

    Sandbox vs production is controlled by the FirsConfig.use_sandbox flag,
    which is passed at construction time and reflected in self.base_url.
    """

    # Request timeout (seconds): connect timeout, read timeout
    _TIMEOUT = (10, 30)

    def __init__(self, api_key: str, base_url: str):
        """
        Args:
            api_key : DigiTax x-api-key (decrypted plain string).
            base_url: Full base URL including version prefix, e.g.
                      https://api.digitax.tech/ng/v1
        """
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    @classmethod
    def from_config(cls, firs_config) -> "DigiTaxApiClient":
        """
        Convenience factory that builds a client from a FirsConfig instance.

        Automatically chooses sandbox vs production URL based on the config's
        use_sandbox flag. Falls back to Django settings if the config's base URL
        is blank (defensive for migrated orgs).
        """
        from apps.einvoicing.models import FirsConfig  # avoid circular import

        if firs_config.use_sandbox:
            base_url = getattr(settings, "DIGITAX_SANDBOX_URL", "https://api-dev.digitax.tech/ng/v1")
        else:
            base_url = (
                firs_config.app_base_url
                or getattr(settings, "DIGITAX_BASE_URL", "https://api.digitax.tech/ng/v1")
            )

        # Prefer the per-org key; fall back to platform-level env var.
        api_key = firs_config.app_api_key or getattr(settings, "DIGITAX_APP_API_KEY", "")
        return cls(api_key=api_key, base_url=base_url)

    # ── Public API methods ────────────────────────────────────────────────────

    def create_party(self, payload: dict) -> dict:
        """
        Register a business party (seller or buyer) with DigiTax.

        POST /parties
        Required fields: tax_identification_number, email, name, address
        Returns: {"id": "<digitax_party_id>", ...}

        Idempotent: DigiTax returns the existing record if the TIN is already
        registered (HTTP 200 with the existing party data).
        """
        return self._post("parties", payload)

    def create_item(self, payload: dict) -> dict:
        """
        Register a product/service line item with DigiTax.

        POST /items
        Required fields: tax_category_code, product_category, item_name, description
        Optional fields: hsn_code (physical goods), is_service, unit_price
        Returns: {"id": "<digitax_item_id>", ...}
        """
        return self._post("items", payload)

    def create_invoice(self, payload: dict) -> dict:
        """
        Submit an invoice to DigiTax for IRN clearance.

        POST /invoices
        Returns: {"id": "<submission_ref>", "status": "CREATED", ...}
        The IRN is NOT in this response — it arrives later via webhook callback.

        invoice_kind (B2B / B2G):
            - Async clearance: DigiTax submits to FIRS; webhook fires when IRN issued.
        invoice_kind B2C:
            - Synchronous reporting (no individual clearance required).
        """
        return self._post("invoices", payload)

    def create_credit_note(self, payload: dict) -> dict:
        """
        Submit a credit note against a previously cleared invoice.

        POST /credit-notes
        Used when a SaleReturn is processed against a B2B-cleared invoice.
        Returns: {"id": "<credit_note_ref>", ...}
        """
        return self._post("credit-notes", payload)

    def update_payment_status(self, digitax_invoice_id: str, status: str) -> dict:
        """
        Notify DigiTax that an invoice's payment status has changed.

        PUT /invoices/{id}/payment-status
        status: "PAID" | "REJECTED"

        Called when an Audity invoice transitions to Invoice.Status.PAID.
        """
        endpoint = f"invoices/{digitax_invoice_id}/payment-status"
        return self._put(endpoint, {"status": status})

    def test_connection(self) -> dict:
        """
        Lightweight connectivity check — no side effects.

        Calls GET /resources (DigiTax provides this as a health/reference endpoint).
        Returns the response dict on success.
        Raises DigiTaxAuthError if credentials are wrong.
        Raises DigiTaxServerError for transient failures.
        """
        return self._get("resources")

    # ── Internal HTTP helpers ─────────────────────────────────────────────────

    def _post(self, endpoint: str, payload: dict) -> dict:
        """Execute a POST request and return the parsed JSON response."""
        url = f"{self.base_url}/{endpoint}"
        logger.debug("DigiTax POST %s payload_keys=%s", endpoint, list(payload.keys()))
        try:
            resp = self._session.post(url, json=payload, timeout=self._TIMEOUT)
        except requests.exceptions.ConnectionError as exc:
            raise DigiTaxServerError(f"Connection failed: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            raise DigiTaxServerError(f"Request timed out: {exc}") from exc
        return self._handle_response(resp, endpoint)

    def _put(self, endpoint: str, payload: dict) -> dict:
        """Execute a PUT request and return the parsed JSON response."""
        url = f"{self.base_url}/{endpoint}"
        logger.debug("DigiTax PUT %s", endpoint)
        try:
            resp = self._session.put(url, json=payload, timeout=self._TIMEOUT)
        except requests.exceptions.ConnectionError as exc:
            raise DigiTaxServerError(f"Connection failed: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            raise DigiTaxServerError(f"Request timed out: {exc}") from exc
        return self._handle_response(resp, endpoint)

    def _get(self, endpoint: str) -> dict:
        """Execute a GET request and return the parsed JSON response."""
        url = f"{self.base_url}/{endpoint}"
        logger.debug("DigiTax GET %s", endpoint)
        try:
            resp = self._session.get(url, timeout=self._TIMEOUT)
        except requests.exceptions.ConnectionError as exc:
            raise DigiTaxServerError(f"Connection failed: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            raise DigiTaxServerError(f"Request timed out: {exc}") from exc
        return self._handle_response(resp, endpoint)

    @staticmethod
    def _handle_response(resp: requests.Response, endpoint: str) -> dict:
        """
        Parse the HTTP response and raise the appropriate exception on failure.

        Error taxonomy:
            401       → DigiTaxAuthError     (non-retryable, fix credentials)
            400 / 422 → DigiTaxValidationError (non-retryable, fix payload)
            404       → DigiTaxNotFoundError   (re-register resource)
            5xx       → DigiTaxServerError     (retryable)
        """
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text[:500]}

        if resp.status_code in (200, 201):
            return data

        message = _extract_error_message(data, resp.status_code, endpoint)

        if resp.status_code == 401:
            raise DigiTaxAuthError(message, status_code=401, response=data)
        if resp.status_code == 404:
            raise DigiTaxNotFoundError(message, status_code=404, response=data)
        if resp.status_code in (400, 422):
            raise DigiTaxValidationError(message, status_code=resp.status_code, response=data)
        if resp.status_code >= 500:
            raise DigiTaxServerError(message, status_code=resp.status_code, response=data)

        # Unexpected 2xx variant (e.g. 204 No Content) — treat as success with empty dict
        if 200 <= resp.status_code < 300:
            return data or {}

        raise DigiTaxError(message, status_code=resp.status_code, response=data)


def _extract_error_message(data: dict, status_code: int, endpoint: str) -> str:
    """
    Extract a human-readable error message from DigiTax error responses.

    DigiTax uses a few different error shapes:
        {"message": "..."}
        {"error": "..."}
        {"errors": ["...", "..."]}
        {"detail": "..."}
    """
    if isinstance(data, dict):
        for key in ("message", "error", "detail"):
            if key in data and data[key]:
                return str(data[key])
        if "errors" in data and isinstance(data["errors"], list):
            return "; ".join(str(e) for e in data["errors"])
    return f"DigiTax {endpoint} returned HTTP {status_code}"


# ─── Invoice JSON Serializer ──────────────────────────────────────────────────

class InvoiceJsonSerializer:
    """
    Transforms an Audity Invoice ORM object into the JSON payloads expected
    by the DigiTax API.

    Pure data transformer — no I/O, no DB writes, no network calls.
    All methods are static so they can be called without instantiation.

    Transaction-type resolution
    ===========================
    The DigiTax API needs invoice_kind: B2B | B2G | B2C.

        customer.customer_type == 'government'    → B2G
        customer.tin is non-empty (not government) → B2B
        no customer, or customer with no TIN       → B2C

    Tax category codes (Nigerian context)
    =====================================
        'S' → Standard rate   (taxable, rate > 0, currently 7.5% VAT)
        'Z' → Zero rated       (taxable=True, rate == 0)
        'E' → Exempt           (is_taxable=False)

    Idempotency IDs
    ===============
    Party and item payloads include an idempotency key derived from the
    Audity UUID so that re-calling create_party / create_item never creates
    duplicates on the DigiTax side.
    """

    # DigiTax standard invoice type code (UBL 380 = Commercial Invoice)
    INVOICE_TYPE_CODE = "380"
    # Credit note type code (UBL 381)
    CREDIT_NOTE_TYPE_CODE = "381"

    # ── Transaction-type resolution ───────────────────────────────────────────

    @staticmethod
    def resolve_transaction_type(invoice) -> str:
        """
        Determine B2B / B2G / B2C from the invoice's customer record.

        Returns one of: 'B2B', 'B2G', 'B2C'
        This value is stored on FirsSubmission.transaction_type and
        Invoice.firs_transaction_type when the submission is created.
        """
        customer = invoice.customer
        if not customer:
            return "B2C"  # walk-in / no customer record → always B2C

        if customer.customer_type == "government":
            return "B2G"  # government entity always routes to B2G clearance

        if customer.tin and customer.tin.strip():
            return "B2B"  # registered business with TIN → B2B clearance

        return "B2C"  # consumer with no TIN

    # ── Tax category mapping ──────────────────────────────────────────────────

    @staticmethod
    def map_tax_category(is_taxable: bool, tax_rate: Decimal) -> str:
        """
        Map Audity tax settings to DigiTax / FIRS tax category codes.

            S — Standard rate (VAT applies, rate > 0)
            Z — Zero rated    (VAT applies but at 0%)
            E — Exempt        (outside VAT scope entirely)
        """
        if not is_taxable:
            return "E"
        if tax_rate and tax_rate > 0:
            return "S"
        return "Z"

    # ── Party payload builders ────────────────────────────────────────────────

    @staticmethod
    def build_seller_party_payload(org) -> dict:
        """
        Build the POST /parties payload for the selling organisation.

        Args:
            org: Organisation instance (from tenancy app)
        Returns:
            Dict matching DigiTax /parties schema.
        """
        # Use FirsConfig.tin if set, fall back to Organisation.tax_id
        try:
            tin = org.firs_config.tin or org.tax_id or ""
            business_name = org.firs_config.business_name or org.name
        except Exception:
            tin = org.tax_id or ""
            business_name = org.name

        return {
            "tax_identification_number": tin,
            "email": org.email or "",
            "name": business_name,
            "address": org.address or "",
            # Idempotency: DigiTax deduplicates on TIN; extra field for traceability
            "reference_id": _short_id(str(org.id)),
        }

    @staticmethod
    def build_buyer_party_payload(customer, org) -> dict:
        """
        Build the POST /parties payload for the buying customer.

        For B2C / walk-in (no customer record), we use the org's own details
        as a placeholder buyer — this is acceptable for B2C batch reporting.

        Args:
            customer: Customer instance or None (walk-in)
            org:      Organisation (used as fallback for B2C)
        Returns:
            Dict matching DigiTax /parties schema.
        """
        if customer and customer.tin and customer.tin.strip():
            # Registered B2B buyer — use their actual TIN
            return {
                "tax_identification_number": customer.tin,
                "email": customer.email or "",
                "name": customer.name,
                "address": customer.address or "",
                "reference_id": _short_id(str(customer.id)),
            }

        # B2C / unregistered buyer — use placeholder data
        # FIRS allows aggregate B2C reporting without individual buyer details
        return {
            "tax_identification_number": "",
            "email": "",
            "name": customer.name if customer else "Walk-in Customer",
            "address": customer.address if (customer and customer.address) else org.address or "",
            "reference_id": _short_id(str(customer.id)) if customer else "walkin",
        }

    # ── Item payload builder ──────────────────────────────────────────────────

    @staticmethod
    def build_item_payload(product) -> dict:
        """
        Build the POST /items payload for a single product.

        Args:
            product: Product instance (from inventory app)
        Returns:
            Dict matching DigiTax /items schema.

        Note on hsn_code:
            HSN codes are mandatory for physical goods under FIRS rules.
            Services use isic_code instead. If neither is set, we send an
            empty string — DigiTax will return a ValidationError, which is
            surfaced to the UI so the user can add the code to the product.
        """
        is_service = product.product_type in ("service", "digital")
        return {
            "item_name": product.name,
            "description": product.description or product.name,
            "tax_category_code": InvoiceJsonSerializer.map_tax_category(
                product.is_taxable,
                product.tax_class.rate if (product.tax_class and hasattr(product.tax_class, "rate")) else Decimal("0"),
            ),
            # Product category — DigiTax accepts "GENERAL" as a catch-all
            "product_category": "SERVICES" if is_service else "GOODS",
            "is_service": is_service,
            # HSN code for physical goods; empty string for services is acceptable
            "hsn_code": product.hsn_code or "",
            # Unit price optional — line-level price is sent on the invoice items array
            "unit_price": float(product.selling_price),
            "reference_id": _short_id(str(product.id)),
        }

    # ── Invoice payload builder ───────────────────────────────────────────────

    @classmethod
    def build_invoice_payload(
        cls,
        invoice,
        seller_party_id: str,
        buyer_party_id: str,
        item_id_map: dict,
        callback_url: str = "",
    ) -> dict:
        """
        Build the POST /invoices payload.

        This is the main method — it assembles the full invoice document
        from all the pre-registered party and item IDs.

        Args:
            invoice       : Invoice ORM instance (with .items and .customer prefetched)
            seller_party_id: DigiTax party ID for the selling organisation
            buyer_party_id : DigiTax party ID for the buyer (customer)
            item_id_map    : {product_id_str: digitax_item_id} for each line item
            callback_url   : Webhook URL DigiTax POSTs to when IRN is issued

        Returns:
            Dict matching DigiTax POST /invoices schema.
        """
        tx_type = cls.resolve_transaction_type(invoice)

        # Use tax_point_date if set; fall back to issue_date (most common case)
        tax_point_date = invoice.tax_point_date or invoice.issue_date

        payload = {
            # ── Document metadata ───────────────────────────────────────────
            "invoice_date": str(invoice.issue_date),
            "issue_date": str(invoice.issue_date),
            "invoice_type_code": cls.INVOICE_TYPE_CODE,
            "document_currency_code": invoice.organisation.currency or "NGN",
            # trader_invoice_number = Audity's internal number (our reference)
            "trader_invoice_number": invoice.invoice_number,
            "invoice_kind": tx_type,

            # ── Parties (pre-registered DigiTax IDs) ────────────────────────
            "seller_party_id": seller_party_id,
            "buyer_party_id": buyer_party_id,

            # ── Tax point date (when VAT legally becomes due) ────────────────
            "tax_point_date": str(tax_point_date),

            # ── Line items ───────────────────────────────────────────────────
            "items": cls._build_invoice_items(invoice, item_id_map),

            # ── Financial totals (informational — DigiTax re-calculates) ────
            "tax_exclusive_amount": float(invoice.subtotal),
            "tax_inclusive_amount": float(invoice.total_amount),
            "tax_amount": float(invoice.tax_amount),
            "discount_amount": float(invoice.discount_amount),
        }

        # Optional fields — only include if non-empty to keep payload clean
        if callback_url:
            payload["callback_url"] = callback_url

        if invoice.payment_terms_text:
            payload["payment_terms_note"] = invoice.payment_terms_text

        if invoice.due_date:
            payload["due_date"] = str(invoice.due_date)

        if invoice.delivery_start and invoice.delivery_end:
            payload["invoice_delivery_period"] = {
                "start_date": str(invoice.delivery_start),
                "end_date": str(invoice.delivery_end),
            }

        if invoice.notes:
            payload["note"] = invoice.notes[:500]  # DigiTax caps at 500 chars

        return payload

    @classmethod
    def _build_invoice_items(cls, invoice, item_id_map: dict) -> list:
        """
        Build the items array for the invoice payload.

        Each element represents one SaleItem line. The DigiTax item_id
        is looked up from item_id_map[str(sale_item.product_id)].

        Raises:
            ValueError: if a product has no DigiTax item_id registered yet.
                        EInvoicingService.ensure_items_registered() must be
                        called before build_invoice_payload().
        """
        lines = []
        for sale_item in invoice.items.select_related("product").all():
            product_id_str = str(sale_item.product_id)
            digitax_item_id = item_id_map.get(product_id_str, "")

            if not digitax_item_id:
                raise ValueError(
                    f"Product '{sale_item.product.name}' (id={product_id_str}) has no "
                    f"DigiTax item_id. Call ensure_items_registered() first."
                )

            tax_category = cls.map_tax_category(
                sale_item.product.is_taxable,
                sale_item.tax_rate,
            )

            lines.append({
                "item_id": digitax_item_id,
                "quantity": float(sale_item.quantity),
                "unit_price": float(sale_item.unit_price),
                "discount_amount": float(sale_item.discount_amount),
                "tax_category_code": tax_category,
                "tax_rate": float(sale_item.tax_rate),
                "tax_amount": float(sale_item.tax_amount),
                # line_extension_amount = unit_price × qty − discount
                "line_extension_amount": float(sale_item.line_total),
            })

        return lines

    # ── Credit note payload builder ───────────────────────────────────────────

    @classmethod
    def build_credit_note_payload(
        cls,
        sale_return,
        seller_party_id: str,
        buyer_party_id: str,
        item_id_map: dict,
        original_irn: str,
    ) -> dict:
        """
        Build the POST /credit-notes payload for a SaleReturn.

        Args:
            sale_return    : SaleReturn ORM instance
            seller_party_id: DigiTax party ID of the seller
            buyer_party_id : DigiTax party ID of the buyer
            item_id_map    : {product_id_str: digitax_item_id}
            original_irn   : The IRN of the original invoice being credited
        """
        invoice = sale_return.invoice
        return {
            "invoice_date": str(sale_return.return_date),
            "issue_date": str(sale_return.return_date),
            "invoice_type_code": cls.CREDIT_NOTE_TYPE_CODE,
            "document_currency_code": invoice.organisation.currency or "NGN",
            "trader_invoice_number": sale_return.return_number,
            "original_irn": original_irn,
            "seller_party_id": seller_party_id,
            "buyer_party_id": buyer_party_id,
            "items": [
                {
                    "item_id": item_id_map.get(str(item.product_id), ""),
                    "quantity": float(item.quantity_returned),
                    "unit_price": float(item.unit_price),
                    "line_extension_amount": float(item.refund_amount),
                }
                for item in sale_return.items.select_related("product").all()
            ],
            "tax_exclusive_amount": float(sale_return.total_refund),
            "tax_inclusive_amount": float(sale_return.total_refund),
            "note": f"Return reason: {sale_return.get_reason_display()}",
        }


# ─── E-Invoicing Service (Orchestrator) ──────────────────────────────────────

class EInvoicingService:
    """
    Orchestrates the full DigiTax submission lifecycle for a single organisation.

    Responsibilities:
        1. Ensure seller (org) is registered as a DigiTax party.
        2. Ensure buyer (customer) is registered as a DigiTax party.
        3. Ensure all products on the invoice are registered as DigiTax items.
        4. Build the invoice JSON payload via InvoiceJsonSerializer.
        5. POST the invoice to DigiTax and create a FirsSubmission audit row.
        6. Update Invoice.firs_status, firs_transaction_type.

    Idempotency:
        All "ensure_*" methods cache DigiTax IDs in the ORM (digitax_party_id,
        digitax_item_id). Re-calling is safe and cheap — it checks the cached
        ID and skips the API call if already registered.

    Usage:
        service = EInvoicingService.for_invoice(invoice)
        if service is None:
            return  # org not enrolled — skip silently
        submission = service.submit_invoice(invoice)
    """

    def __init__(self, firs_config, client: Optional[DigiTaxApiClient] = None):
        """
        Args:
            firs_config: FirsConfig ORM instance for the organisation.
            client:      Optional pre-built client (injected in tests for mocking).
        """
        self.config = firs_config
        self.org = firs_config.organisation
        # Allow test injection; build from config in production
        self.client = client or DigiTaxApiClient.from_config(firs_config)
        self.serializer = InvoiceJsonSerializer()

    @classmethod
    def for_invoice(cls, invoice) -> Optional["EInvoicingService"]:
        """
        Build an EInvoicingService for the org that owns this invoice.

        Returns None (no exception) if the org is not enrolled in FIRS
        e-invoicing — this allows callers to skip silently without
        try/except around every call site.

        Returns:
            EInvoicingService instance, or None if not enrolled.
        """
        try:
            config = invoice.organisation.firs_config
        except Exception:
            return None

        if not config.is_enrolled:
            return None

        return cls(config)

    # ── Party registration ────────────────────────────────────────────────────

    def ensure_seller_registered(self) -> str:
        """
        Register the selling organisation as a DigiTax party.

        Returns the DigiTax party ID (from cache or fresh API call).
        Caches the ID in FirsConfig.digitax_party_id for future calls.
        """
        if self.config.digitax_party_id:
            return self.config.digitax_party_id

        payload = InvoiceJsonSerializer.build_seller_party_payload(self.org)
        try:
            resp = self.client.create_party(payload)
        except DigiTaxError:
            raise  # let caller decide retry strategy

        party_id = resp.get("id") or resp.get("party_id") or resp.get("data", {}).get("id", "")
        if not party_id:
            raise DigiTaxError(f"DigiTax /parties response missing 'id' field: {resp}")

        # Cache the party ID so we never need to re-register
        self.config.digitax_party_id = party_id
        self.config.save(update_fields=["digitax_party_id", "updated_at"])
        logger.info("DigiTax: seller party registered org=%s party_id=%s", self.org.id, party_id)
        return party_id

    def ensure_buyer_registered(self, customer) -> str:
        """
        Register the buyer (customer) as a DigiTax party.

        For B2C walk-in customers (no TIN), a stable placeholder party is used.
        Returns the DigiTax party ID.
        Caches the ID in Customer.digitax_party_id.
        """
        if not customer:
            # Walk-in: return a platform-level "B2C aggregate" party if configured,
            # otherwise register the org itself as the placeholder buyer.
            return self.ensure_seller_registered()

        if customer.digitax_party_id:
            return customer.digitax_party_id

        payload = InvoiceJsonSerializer.build_buyer_party_payload(customer, self.org)
        try:
            resp = self.client.create_party(payload)
        except DigiTaxError:
            raise

        party_id = resp.get("id") or resp.get("party_id") or resp.get("data", {}).get("id", "")
        if not party_id:
            raise DigiTaxError(f"DigiTax /parties (buyer) response missing 'id' field: {resp}")

        customer.digitax_party_id = party_id
        customer.save(update_fields=["digitax_party_id"])
        logger.info("DigiTax: buyer party registered customer=%s party_id=%s", customer.id, party_id)
        return party_id

    def ensure_items_registered(self, invoice) -> dict:
        """
        Ensure every product on the invoice is registered as a DigiTax item.

        Returns:
            {product_id_str: digitax_item_id} for all line items.
            This map is passed directly to InvoiceJsonSerializer.build_invoice_payload().
        """
        item_id_map: dict[str, str] = {}

        for sale_item in invoice.items.select_related("product").all():
            product = sale_item.product
            product_id_str = str(product.id)

            if product.digitax_item_id:
                # Already registered — use cached ID
                item_id_map[product_id_str] = product.digitax_item_id
                continue

            # Not yet registered — call DigiTax POST /items
            payload = InvoiceJsonSerializer.build_item_payload(product)
            try:
                resp = self.client.create_item(payload)
            except DigiTaxError:
                raise

            item_id = resp.get("id") or resp.get("item_id") or resp.get("data", {}).get("id", "")
            if not item_id:
                raise DigiTaxError(
                    f"DigiTax /items response missing 'id' for product {product.name}: {resp}"
                )

            # Cache on the Product record to avoid re-registration
            product.digitax_item_id = item_id
            product.save(update_fields=["digitax_item_id"])
            item_id_map[product_id_str] = item_id
            logger.info("DigiTax: item registered product=%s item_id=%s", product.id, item_id)

        return item_id_map

    # ── Invoice submission ────────────────────────────────────────────────────

    def submit_invoice(self, invoice) -> "FirsSubmission":
        """
        Full submission pipeline: register parties + items, then POST invoice.

        Idempotency guard:
            If a SUBMITTED or CLEARED FirsSubmission already exists for this
            invoice, returns it immediately without re-submitting. This makes
            the method safe to call multiple times (e.g. from Celery retries).

        Transaction type routing:
            B2B / B2G → async clearance (webhook delivers IRN in 2–4 hours)
            B2C       → bypassed (queued for nightly batch; no individual IRN)

        Returns:
            FirsSubmission with status SUBMITTED or BYPASSED.

        Raises:
            DigiTaxAuthError     — bad API key (non-retryable)
            DigiTaxValidationError — bad payload (non-retryable; fix data)
            DigiTaxServerError   — transient failure (retryable by Celery)
        """
        from apps.einvoicing.models import FirsSubmission  # avoid circular import at module level

        # ── Idempotency: return existing submission if already in-flight ─────
        existing = (
            FirsSubmission.objects
            .filter(invoice=invoice, status__in=[
                FirsSubmission.Status.SUBMITTED,
                FirsSubmission.Status.CLEARED,
            ])
            .order_by("-created_at")
            .first()
        )
        if existing:
            logger.info(
                "DigiTax: invoice %s already has status=%s — skipping re-submission",
                invoice.invoice_number, existing.status,
            )
            return existing

        # ── Resolve transaction type early (needed for routing decision) ─────
        tx_type = InvoiceJsonSerializer.resolve_transaction_type(invoice)

        # ── B2C shortcut: bypass individual clearance ─────────────────────────
        if tx_type == "B2C":
            return self._bypass_b2c(invoice, tx_type)

        # ── B2B / B2G: full clearance flow ────────────────────────────────────
        seller_id = self.ensure_seller_registered()
        buyer_id = self.ensure_buyer_registered(invoice.customer)
        item_id_map = self.ensure_items_registered(invoice)

        callback_url = _build_callback_url()
        payload = InvoiceJsonSerializer.build_invoice_payload(
            invoice, seller_id, buyer_id, item_id_map, callback_url
        )

        # Create the submission audit row BEFORE the API call so we have a
        # record even if the API call raises an exception mid-flight.
        submission = FirsSubmission.objects.create(
            organisation=invoice.organisation,
            invoice=invoice,
            transaction_type=tx_type,
            payload_json=payload,
            status=FirsSubmission.Status.PENDING,
        )

        try:
            resp = self.client.create_invoice(payload)
            submission_ref = resp.get("id") or resp.get("submission_ref") or resp.get("data", {}).get("id", "")

            submission.submission_ref = submission_ref
            submission.response_raw = resp
            submission.status = FirsSubmission.Status.SUBMITTED
            submission.submitted_at = timezone.now()
            submission.save(update_fields=[
                "submission_ref", "response_raw", "status", "submitted_at", "updated_at"
            ])

            # Update the invoice's FIRS status and transaction type
            invoice.firs_status = "submitted"
            invoice.firs_transaction_type = tx_type
            invoice.save(update_fields=["firs_status", "firs_transaction_type", "updated_at"])

            logger.info(
                "DigiTax: invoice %s submitted ref=%s tx=%s",
                invoice.invoice_number, submission_ref, tx_type,
            )

        except (DigiTaxAuthError, DigiTaxValidationError, DigiTaxNotFoundError) as exc:
            # Non-retryable: mark FAILED immediately
            submission.status = FirsSubmission.Status.FAILED
            submission.error_detail = exc.message
            submission.response_raw = exc.response
            submission.save(update_fields=["status", "error_detail", "response_raw", "updated_at"])

            invoice.firs_status = "failed"
            invoice.firs_transaction_type = tx_type
            invoice.save(update_fields=["firs_status", "firs_transaction_type", "updated_at"])

            logger.error(
                "DigiTax: invoice %s submission FAILED (non-retryable) error=%s",
                invoice.invoice_number, exc.message,
            )
            raise  # re-raise so Celery task records it correctly

        except DigiTaxServerError as exc:
            # Retryable: mark FAILED for now; Celery will retry
            submission.status = FirsSubmission.Status.FAILED
            submission.error_detail = exc.message
            submission.response_raw = exc.response
            submission.save(update_fields=["status", "error_detail", "response_raw", "updated_at"])

            invoice.firs_status = "failed"
            invoice.firs_transaction_type = tx_type
            invoice.save(update_fields=["firs_status", "firs_transaction_type", "updated_at"])

            logger.warning(
                "DigiTax: invoice %s submission FAILED (retryable) error=%s",
                invoice.invoice_number, exc.message,
            )
            raise  # let Celery retry

        return submission

    # ── IRN callback handler ──────────────────────────────────────────────────

    def handle_irn_callback(
        self,
        submission_ref: str,
        irn: str,
        csid: str,
        firs_invoice_number: str,
        qr_code_b64: str = "",
    ) -> None:
        """
        Called by the webhook view when DigiTax POSTs an IRN callback.

        Updates the FirsSubmission and the Invoice with the received IRN,
        CSID, and FIRS invoice number. Generates a QR code if base64 data
        was not provided by DigiTax.

        Args:
            submission_ref    : DigiTax submission reference (FK to FirsSubmission)
            irn               : FIRS Invoice Reference Number
            csid              : Cryptographic Stamp Identifier
            firs_invoice_number: FIRS-assigned invoice number
            qr_code_b64       : Base64 QR code image (optional — DigiTax may include it)
        """
        from apps.einvoicing.models import FirsSubmission

        try:
            submission = FirsSubmission.objects.select_related("invoice").get(
                submission_ref=submission_ref
            )
        except FirsSubmission.DoesNotExist:
            logger.warning(
                "DigiTax webhook: FirsSubmission not found for ref=%s", submission_ref
            )
            return

        submission.irn = irn
        submission.csid = csid
        submission.status = FirsSubmission.Status.CLEARED
        submission.cleared_at = timezone.now()
        submission.save(update_fields=["irn", "csid", "status", "cleared_at", "updated_at"])

        # Stamp the invoice with FIRS identifiers
        invoice = submission.invoice
        invoice.firs_irn = irn
        invoice.firs_csid = csid
        invoice.firs_invoice_number = firs_invoice_number
        invoice.firs_status = "cleared"

        # Generate or store QR code with all FIRS-required fields
        if qr_code_b64:
            invoice.firs_qr_code = qr_code_b64
        elif irn:
            # Build the full QR code with seller TIN and financial totals
            try:
                seller_tin = self.config.tin or self.org.tax_id or ""
            except Exception:
                seller_tin = ""
            invoice.firs_qr_code = _generate_full_qr(
                irn=irn,
                invoice_number=firs_invoice_number or invoice.invoice_number,
                seller_tin=seller_tin,
                issue_date=str(invoice.issue_date) if invoice.issue_date else "",
                tax_amount=str(invoice.tax_amount),
                total_amount=str(invoice.total_amount),
                csid=csid,
            )

        invoice.save(update_fields=[
            "firs_irn", "firs_csid", "firs_invoice_number",
            "firs_status", "firs_qr_code", "updated_at",
        ])

        # Auto-create VATTransaction for this e-invoice VAT (non-blocking)
        try:
            from decimal import Decimal as _D
            from apps.tax.models import VATTransaction
            if invoice.tax_amount and _D(str(invoice.tax_amount)) > _D('0'):
                period_start = invoice.issue_date.replace(day=1)
                import calendar
                last_day = calendar.monthrange(invoice.issue_date.year, invoice.issue_date.month)[1]
                period_end = invoice.issue_date.replace(day=last_day)
                source_ref = invoice.firs_irn or invoice.invoice_number
                if not VATTransaction.objects.filter(
                    organisation=invoice.organisation,
                    source_ref=source_ref,
                    direction=VATTransaction.OUTPUT,
                ).exists():
                    VATTransaction.objects.create(
                        organisation=invoice.organisation,
                        direction=VATTransaction.OUTPUT,
                        period_start=period_start,
                        period_end=period_end,
                        counterparty_name=invoice.customer.name if invoice.customer else '',
                        counterparty_tin=getattr(invoice.customer, 'tax_id', '') or '' if invoice.customer else '',
                        net_amount=_D(str(invoice.total_amount)) - _D(str(invoice.tax_amount or 0)),
                        vat_amount=_D(str(invoice.tax_amount)),
                        vat_rate=_D('7.5'),
                        source_ref=source_ref,
                        notes=f"E-Invoice {irn}",
                    )
        except Exception as _exc:
            logger.error("VATTransaction auto-create from e-invoice failed: %s", _exc)

        logger.info(
            "DigiTax: IRN received invoice=%s irn=%s",
            invoice.invoice_number, irn,
        )

    # ── Credit note submission ────────────────────────────────────────────────────

    def submit_credit_note(self, sale_return) -> "Optional[FirsSubmission]":
        """
        Submit a credit note to DigiTax for a sales return.

        A credit note can only be submitted if the original invoice was already
        cleared by FIRS (has an IRN). If the invoice is not yet cleared, returns
        None silently — the credit note can be re-submitted once the IRN arrives.

        The credit note re-uses the already-registered parties and items from
        the original invoice (cached IDs), so no new DigiTax API registrations
        are required in the typical case.

        Args:
            sale_return: SaleReturn ORM instance

        Returns:
            FirsSubmission with status SUBMITTED, or None if original not cleared.

        Raises:
            DigiTaxAuthError / DigiTaxValidationError / DigiTaxServerError on failure.
        """
        from apps.einvoicing.models import FirsSubmission

        invoice = sale_return.invoice

        # Guard: can only raise a credit note against a cleared invoice
        if not invoice.firs_irn:
            logger.info(
                "submit_credit_note: invoice %s has no IRN yet — skipping credit note for %s",
                invoice.invoice_number, sale_return.return_number,
            )
            return None

        # Idempotency: return existing submission if credit note already in-flight
        existing = (
            FirsSubmission.objects
            .filter(
                sale_return=sale_return,
                submission_kind=FirsSubmission.SubmissionKind.CREDIT_NOTE,
                status__in=[FirsSubmission.Status.SUBMITTED, FirsSubmission.Status.CLEARED],
            )
            .first()
        )
        if existing:
            logger.info(
                "submit_credit_note: credit note for %s already %s — skipping",
                sale_return.return_number, existing.status,
            )
            return existing

        # Resolve parties (cached from the original invoice submission)
        seller_id = self.ensure_seller_registered()
        buyer_id = self.ensure_buyer_registered(invoice.customer)
        item_id_map = self.ensure_items_registered(invoice)

        payload = InvoiceJsonSerializer.build_credit_note_payload(
            sale_return=sale_return,
            seller_party_id=seller_id,
            buyer_party_id=buyer_id,
            item_id_map=item_id_map,
            original_irn=invoice.firs_irn,
        )

        # Inherit transaction type from original invoice
        tx_type = invoice.firs_transaction_type or InvoiceJsonSerializer.resolve_transaction_type(invoice)

        # Create audit row before the API call so we always have a record
        submission = FirsSubmission.objects.create(
            organisation=invoice.organisation,
            invoice=invoice,
            sale_return=sale_return,
            submission_kind=FirsSubmission.SubmissionKind.CREDIT_NOTE,
            transaction_type=tx_type,
            payload_json=payload,
            status=FirsSubmission.Status.PENDING,
        )

        try:
            resp = self.client.create_credit_note(payload)
            submission_ref = (
                resp.get("id") or resp.get("submission_ref")
                or resp.get("data", {}).get("id", "")
            )

            submission.submission_ref = submission_ref
            submission.response_raw = resp
            submission.status = FirsSubmission.Status.SUBMITTED
            submission.submitted_at = timezone.now()
            submission.save(update_fields=[
                "submission_ref", "response_raw", "status", "submitted_at", "updated_at",
            ])

            logger.info(
                "DigiTax: credit note submitted return=%s ref=%s original_irn=%s",
                sale_return.return_number, submission_ref, invoice.firs_irn,
            )

        except (DigiTaxAuthError, DigiTaxValidationError, DigiTaxNotFoundError) as exc:
            submission.status = FirsSubmission.Status.FAILED
            submission.error_detail = exc.message
            submission.response_raw = exc.response
            submission.save(update_fields=["status", "error_detail", "response_raw", "updated_at"])
            logger.error(
                "DigiTax: credit note FAILED (non-retryable) return=%s error=%s",
                sale_return.return_number, exc.message,
            )
            raise

        except DigiTaxServerError as exc:
            submission.status = FirsSubmission.Status.FAILED
            submission.error_detail = exc.message
            submission.response_raw = exc.response
            submission.save(update_fields=["status", "error_detail", "response_raw", "updated_at"])
            logger.warning(
                "DigiTax: credit note FAILED (retryable) return=%s error=%s",
                sale_return.return_number, exc.message,
            )
            raise

        return submission

    # ── B2C bypass helper ─────────────────────────────────────────────────────

    def _bypass_b2c(self, invoice, tx_type: str) -> "FirsSubmission":
        """
        Mark a B2C invoice as BYPASSED for daily batch reporting.
        No individual DigiTax API call is made — the nightly Celery task
        (einvoicing.report_b2c_invoices) will batch-submit these.
        """
        from apps.einvoicing.models import FirsSubmission

        submission = FirsSubmission.objects.create(
            organisation=invoice.organisation,
            invoice=invoice,
            transaction_type=tx_type,
            status=FirsSubmission.Status.BYPASSED,
            payload_json={},  # built at batch-report time
        )

        invoice.firs_status = "bypassed"
        invoice.firs_transaction_type = tx_type
        invoice.save(update_fields=["firs_status", "firs_transaction_type", "updated_at"])

        logger.info(
            "DigiTax: invoice %s bypassed (B2C — queued for nightly batch)",
            invoice.invoice_number,
        )
        return submission


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _short_id(uuid_str: str) -> str:
    """
    Produce an 8-char stable short ID from a UUID string.
    Used as a reference_id in DigiTax party / item payloads for traceability.
    Not used as a primary key — DigiTax assigns its own IDs.
    """
    return hashlib.sha1(uuid_str.encode()).hexdigest()[:8]


def _build_callback_url() -> str:
    """
    Build the webhook callback URL that DigiTax will POST to when an IRN is ready.
    Uses settings.BACKEND_URL so it works across Railway, local, and custom domains.
    """
    backend_url = getattr(settings, "BACKEND_URL", "").rstrip("/")
    if not backend_url:
        return ""
    return f"{backend_url}/api/v1/einvoicing/webhook/"


def _generate_full_qr(
    irn: str,
    invoice_number: str = "",
    seller_tin: str = "",
    issue_date: str = "",
    tax_amount: str = "",
    total_amount: str = "",
    csid: str = "",
) -> str:
    """
    Generate a FIRS-compliant QR code with all required cryptographic fields.

    The QR payload is a structured pipe-delimited string so it is scannable
    by any QR reader and unambiguous for FIRS verification tools.

    FIRS-required fields:
        IRN       — Invoice Reference Number
        SELLER    — Seller's TIN
        DATE      — Invoice issue date (YYYY-MM-DD)
        TAX       — Total VAT amount (currency-formatted)
        TOTAL     — Invoice total (inclusive of VAT)
        INV       — FIRS-assigned invoice number
        CSID      — Cryptographic Stamp Identifier (optional but recommended)

    Returns:
        Base64-encoded PNG string, or "" on failure.

    Raises:
        Never raises — falls back to empty string so invoice PDF generation is
        never blocked by a QR failure.
    """
    try:
        import base64
        import io

        import qrcode
        from qrcode.constants import ERROR_CORRECT_M

        # Build structured pipe-delimited payload
        fields = [f"IRN:{irn}"]
        if seller_tin:
            fields.append(f"SELLER:{seller_tin}")
        if issue_date:
            fields.append(f"DATE:{issue_date}")
        if tax_amount:
            fields.append(f"TAX:{tax_amount}")
        if total_amount:
            fields.append(f"TOTAL:{total_amount}")
        if invoice_number:
            fields.append(f"INV:{invoice_number}")
        if csid:
            fields.append(f"CSID:{csid[:20]}")  # truncate CSID to keep QR scannable

        payload = "|".join(fields)

        # Use ERROR_CORRECT_M (15% redundancy) — good balance for printed invoices
        qr = qrcode.QRCode(
            error_correction=ERROR_CORRECT_M,
            box_size=6,
            border=2,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    except ImportError:
        # qrcode / Pillow not available — graceful fallback
        logger.debug("qrcode/Pillow package not available — skipping QR generation")
        return ""
    except Exception as exc:
        logger.warning("QR code generation failed: %s", exc)
        return ""
