"""
Quotes API integration tests.

Covers: create quote, list, status transitions, convert → invoice,
        edge cases (rejected / expired / already-converted).
"""

import pytest
from decimal import Decimal
from datetime import date, timedelta

from apps.quotes.models import Quote, QuoteItem


@pytest.mark.integration
class TestCreateQuote:

    def test_create_draft_quote(self, auth_client, customer, warehouse, stocked_product):
        """POST /sales/quotes/ should create a draft quote with auto-number."""
        response = auth_client.post("/api/v1/quotes/", {
            "customer": str(customer.id),
            "warehouse": str(warehouse.id),
            "issue_date": str(date.today()),
            "valid_until": str(date.today() + timedelta(days=14)),
            "items": [
                {
                    "product_id": str(stocked_product.id),
                    "quantity": "2",
                    "unit_price": str(stocked_product.selling_price),
                    "discount_percent": "0",
                }
            ],
        }, format="json")

        assert response.status_code == 201
        data = response.data
        assert data["status"] == Quote.DRAFT
        assert data["quote_number"].startswith("QT-")
        assert Decimal(data["total_amount"]) > 0

    def test_create_quote_without_customer(self, auth_client, warehouse, stocked_product):
        """Quotes can be created without a customer (walk-in)."""
        response = auth_client.post("/api/v1/quotes/", {
            "warehouse": str(warehouse.id),
            "issue_date": str(date.today()),
            "valid_until": str(date.today() + timedelta(days=7)),
            "items": [
                {
                    "product_id": str(stocked_product.id),
                    "quantity": "1",
                    "unit_price": str(stocked_product.selling_price),
                }
            ],
        }, format="json")
        assert response.status_code == 201

    def test_create_quote_requires_items(self, auth_client, customer, warehouse):
        """Quote with empty items list should return 400."""
        response = auth_client.post("/api/v1/quotes/", {
            "customer": str(customer.id),
            "warehouse": str(warehouse.id),
            "issue_date": str(date.today()),
            "valid_until": str(date.today() + timedelta(days=7)),
            "items": [],
        }, format="json")
        assert response.status_code == 400

    def test_quote_numbers_are_unique(self, auth_client, warehouse, stocked_product):
        """Each quote should receive a unique sequential number."""
        resp1 = auth_client.post("/api/v1/quotes/", {
            "warehouse": str(warehouse.id),
            "issue_date": str(date.today()),
            "valid_until": str(date.today() + timedelta(days=7)),
            "items": [{"product_id": str(stocked_product.id), "quantity": "1",
                       "unit_price": str(stocked_product.selling_price)}],
        }, format="json")
        resp2 = auth_client.post("/api/v1/quotes/", {
            "warehouse": str(warehouse.id),
            "issue_date": str(date.today()),
            "valid_until": str(date.today() + timedelta(days=7)),
            "items": [{"product_id": str(stocked_product.id), "quantity": "1",
                       "unit_price": str(stocked_product.selling_price)}],
        }, format="json")
        assert resp1.data["quote_number"] != resp2.data["quote_number"]


@pytest.mark.integration
class TestQuoteList:

    def test_list_returns_own_org_quotes(self, auth_client, quote):
        response = auth_client.get("/api/v1/quotes/")
        assert response.status_code == 200
        ids = [q["id"] for q in response.data["results"]]
        assert str(quote.id) in ids

    def test_cross_org_isolation(self, other_auth_client, quote):
        """Other org cannot see this quote."""
        response = other_auth_client.get(f"/api/v1/quotes/{quote.id}/")
        assert response.status_code in (403, 404)

    def test_filter_by_status(self, auth_client, quote):
        response = auth_client.get("/api/v1/quotes/?status=draft")
        assert response.status_code == 200
        for q in response.data["results"]:
            assert q["status"] == Quote.DRAFT


@pytest.mark.integration
class TestQuoteStatusTransitions:

    def test_send_quote(self, auth_client, quote):
        """Mark quote as sent."""
        response = auth_client.patch(f"/api/v1/quotes/{quote.id}/", {
            "status": Quote.SENT,
        }, format="json")
        assert response.status_code == 200
        assert response.data["status"] == Quote.SENT

    def test_accept_quote(self, auth_client, quote):
        """Set status to accepted."""
        response = auth_client.patch(f"/api/v1/quotes/{quote.id}/", {
            "status": Quote.ACCEPTED,
        }, format="json")
        assert response.status_code == 200
        assert response.data["status"] == Quote.ACCEPTED

    def test_reject_quote(self, auth_client, quote):
        """Reject a quote — conversion should then be blocked."""
        auth_client.patch(f"/api/v1/quotes/{quote.id}/", {
            "status": Quote.REJECTED,
        }, format="json")
        response = auth_client.post(f"/api/v1/quotes/{quote.id}/convert/")
        assert response.status_code in (400, 422)

    def test_convert_expired_quote_blocked(self, auth_client, quote):
        """Expired quotes cannot be converted to invoices."""
        quote.status = Quote.EXPIRED
        quote.save()
        response = auth_client.post(f"/api/v1/quotes/{quote.id}/convert/")
        assert response.status_code in (400, 422)


@pytest.mark.integration
class TestQuoteConvert:

    def test_convert_draft_quote_to_invoice(
        self, auth_client, quote, stocked_product, warehouse
    ):
        """A draft quote should convert successfully to a confirmed invoice."""
        response = auth_client.post(f"/api/v1/quotes/{quote.id}/convert/")
        assert response.status_code in (200, 201)

        # Quote should now be converted
        quote.refresh_from_db()
        assert quote.status == Quote.CONVERTED
        assert quote.converted_invoice_id is not None

        # The resulting invoice should be confirmed
        from apps.sales.models import Invoice
        invoice = Invoice.objects.get(id=quote.converted_invoice_id)
        assert invoice.status in (Invoice.Status.CONFIRMED, Invoice.Status.PAID, Invoice.Status.CREDIT)

    def test_cannot_convert_twice(self, auth_client, quote, stocked_product):
        """Once converted, a second conversion attempt should fail."""
        auth_client.post(f"/api/v1/quotes/{quote.id}/convert/")
        response = auth_client.post(f"/api/v1/quotes/{quote.id}/convert/")
        assert response.status_code in (400, 422)
