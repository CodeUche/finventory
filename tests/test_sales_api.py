"""
Sales API integration tests.

Covers: creating a sale, recording payment, voiding invoice.
"""

import pytest
from decimal import Decimal
from apps.inventory.models import StockItem
from apps.sales.models import Invoice


@pytest.mark.integration
class TestCreateSale:

    def test_create_cash_sale(self, auth_client, stocked_product, warehouse, organisation):
        """A cash sale should create an invoice and deduct stock."""
        initial_stock = StockItem.objects.get(
            product=stocked_product, warehouse=warehouse
        ).quantity_on_hand

        response = auth_client.post("/api/v1/sales/invoices/", {
            "warehouse_id": str(warehouse.id),
            "payment_method": "cash",
            "items": [
                {
                    "product_id": str(stocked_product.id),
                    "quantity": "5",
                    "discount_percent": "0",
                }
            ],
        }, format="json")

        assert response.status_code == 201
        assert response.data["status"] == "confirmed"

        # Verify stock deducted
        stock_after = StockItem.objects.get(
            product=stocked_product, warehouse=warehouse
        ).quantity_on_hand
        assert stock_after == initial_stock - Decimal("5")

    def test_create_sale_insufficient_stock(self, auth_client, product, warehouse):
        """Selling more than available should return 422."""
        response = auth_client.post("/api/v1/sales/invoices/", {
            "warehouse_id": str(warehouse.id),
            "payment_method": "cash",
            "items": [
                {"product_id": str(product.id), "quantity": "9999"},
            ],
        }, format="json")
        assert response.status_code == 422

    def test_create_credit_sale(self, auth_client, stocked_product, warehouse, customer):
        """A credit sale should update the customer's outstanding balance."""
        initial_balance = customer.outstanding_balance

        response = auth_client.post("/api/v1/sales/invoices/", {
            "customer_id": str(customer.id),
            "warehouse_id": str(warehouse.id),
            "payment_method": "credit",
            "items": [
                {"product_id": str(stocked_product.id), "quantity": "2"},
            ],
        }, format="json")

        assert response.status_code == 201
        assert response.data["status"] == "credit"

        customer.refresh_from_db()
        assert customer.outstanding_balance > initial_balance

    def test_record_payment_marks_paid(self, auth_client, stocked_product, warehouse):
        """Recording full payment should mark invoice as PAID."""
        # Create a sale first
        sale_resp = auth_client.post("/api/v1/sales/invoices/", {
            "warehouse_id": str(warehouse.id),
            "payment_method": "bank_transfer",
            "items": [{"product_id": str(stocked_product.id), "quantity": "1"}],
        }, format="json")
        assert sale_resp.status_code == 201

        invoice_id = sale_resp.data["id"]
        total = sale_resp.data["total_amount"]

        # Record full payment
        pay_resp = auth_client.post(
            f"/api/v1/sales/invoices/{invoice_id}/pay/",
            {"amount": str(total), "method": "cash"},
            format="json",
        )
        assert pay_resp.status_code == 201

        # Check invoice status
        invoice = Invoice.objects.get(id=invoice_id)
        assert invoice.status == Invoice.Status.PAID
