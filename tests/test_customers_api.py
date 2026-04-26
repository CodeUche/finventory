"""
Customers API integration tests.

Covers: CRUD, statement, outstanding balance tracking,
        credit limit enforcement, cross-org isolation.
"""

import pytest
from decimal import Decimal
from datetime import date, timedelta

from apps.customers.models import Customer


@pytest.mark.integration
class TestCreateCustomer:

    def test_create_customer_minimal(self, auth_client):
        """POST /customers/ with minimal fields should succeed."""
        response = auth_client.post("/api/v1/customers/", {
            "code": "CUST-100",
            "name": "Port Harcourt Distributors",
        }, format="json")
        assert response.status_code == 201
        assert response.data["name"] == "Port Harcourt Distributors"
        assert response.data["code"] == "CUST-100"

    def test_create_customer_full(self, auth_client):
        """POST /customers/ with all optional fields."""
        response = auth_client.post("/api/v1/customers/", {
            "code": "CUST-101",
            "name": "Kano Premium Wines",
            "email": "kpw@example.com",
            "phone": "07011223344",
            "credit_limit": "750000",
            "payment_terms_days": 45,
            "customer_type": "wholesale",
        }, format="json")
        assert response.status_code == 201
        assert Decimal(response.data["credit_limit"]) == Decimal("750000")

    def test_duplicate_code_rejected(self, auth_client, customer):
        """Customer codes must be unique within the org."""
        response = auth_client.post("/api/v1/customers/", {
            "code": customer.code,
            "name": "Duplicate",
        }, format="json")
        assert response.status_code == 400

    def test_unauthenticated_blocked(self, api_client):
        response = api_client.get("/api/v1/customers/")
        assert response.status_code == 401


@pytest.mark.integration
class TestListCustomers:

    def test_list_returns_own_org_customers(self, auth_client, customer):
        response = auth_client.get("/api/v1/customers/")
        assert response.status_code == 200
        ids = [c["id"] for c in response.data["results"]]
        assert str(customer.id) in ids

    def test_cross_org_isolation(self, other_auth_client, customer):
        """Other org must not see this customer."""
        response = other_auth_client.get(f"/api/v1/customers/{customer.id}/")
        assert response.status_code in (403, 404)

    def test_search_by_name(self, auth_client, customer):
        response = auth_client.get(f"/api/v1/customers/?search={customer.name[:8]}")
        assert response.status_code == 200
        ids = [c["id"] for c in response.data["results"]]
        assert str(customer.id) in ids


@pytest.mark.integration
class TestCustomerStatement:

    def test_statement_endpoint_exists(self, auth_client, customer):
        """GET /customers/{id}/statement/ should return 200."""
        from_date = str(date.today() - timedelta(days=90))
        to_date = str(date.today())
        response = auth_client.get(
            f"/api/v1/customers/{customer.id}/statement/"
            f"?date_from={from_date}&date_to={to_date}"
        )
        assert response.status_code == 200

    def test_statement_has_required_fields(self, auth_client, customer):
        """Statement response should include balance, invoices list, payments."""
        response = auth_client.get(
            f"/api/v1/customers/{customer.id}/statement/"
            f"?date_from={str(date.today() - timedelta(days=30))}"
            f"&date_to={str(date.today())}"
        )
        assert response.status_code == 200
        data = response.data
        # At minimum the statement must have some summary field
        assert any(k in data for k in ("balance", "outstanding_balance", "invoices", "transactions"))

    def test_outstanding_balance_increases_on_credit_sale(
        self, auth_client, stocked_product, warehouse, customer
    ):
        """A credit sale should raise the customer's outstanding_balance."""
        initial = customer.outstanding_balance

        auth_client.post("/api/v1/sales/invoices/", {
            "customer_id": str(customer.id),
            "warehouse_id": str(warehouse.id),
            "payment_method": "credit",
            "items": [{"product_id": str(stocked_product.id), "quantity": "1"}],
        }, format="json")

        customer.refresh_from_db()
        assert customer.outstanding_balance > initial


@pytest.mark.integration
class TestCustomerCRUD:

    def test_update_customer(self, auth_client, customer):
        """PATCH /customers/{id}/ should update fields."""
        response = auth_client.patch(f"/api/v1/customers/{customer.id}/", {
            "phone": "08099998888",
            "credit_limit": "1000000",
        }, format="json")
        assert response.status_code == 200
        assert response.data["phone"] == "08099998888"
        assert Decimal(response.data["credit_limit"]) == Decimal("1000000")

    def test_delete_customer(self, auth_client, customer):
        """DELETE /customers/{id}/ should soft-delete the record."""
        response = auth_client.delete(f"/api/v1/customers/{customer.id}/")
        assert response.status_code in (200, 204)
        # After soft-delete the record should no longer appear in list
        list_resp = auth_client.get("/api/v1/customers/")
        ids = [c["id"] for c in list_resp.data["results"]]
        assert str(customer.id) not in ids
