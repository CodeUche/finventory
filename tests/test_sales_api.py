"""
Sales API integration tests.

Covers: creating a sale, recording payment, voiding invoice,
deferred fulfillment, and reversal-based invoice deletion.
"""

import pytest
from decimal import Decimal
from apps.accounting.models import JournalEntry
from apps.inventory.models import StockItem, StockMovement
from apps.sales.models import Invoice, SaleItem, SalePayment
from apps.sales.services import SaleService


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


@pytest.mark.integration
class TestDeferredFulfillment:

    def test_defer_fulfillment_then_fulfill(self, auth_client, user, organisation, stocked_product, warehouse):
        """
        Creating a sale with defer_fulfillment=True must NOT touch stock or post a
        GL journal. Calling fulfill_invoice() afterwards must deduct stock (one
        movement per line) and post exactly one JournalEntry, and stamp fulfilled_at.
        """
        initial_stock = StockItem.objects.get(
            product=stocked_product, warehouse=warehouse
        ).quantity_on_hand

        response = auth_client.post("/api/v1/sales/invoices/", {
            "warehouse_id": str(warehouse.id),
            "payment_method": "cash",
            "defer_fulfillment": True,
            "items": [
                {"product_id": str(stocked_product.id), "quantity": "5"},
            ],
        }, format="json")

        assert response.status_code == 201
        invoice_id = response.data["id"]
        assert response.data["is_deferred"] is True
        assert response.data["fulfilled_at"] is None

        invoice = Invoice.objects.get(id=invoice_id)

        # No stock movement / deduction at creation time
        stock_after_create = StockItem.objects.get(
            product=stocked_product, warehouse=warehouse
        ).quantity_on_hand
        assert stock_after_create == initial_stock
        movement_count_before = StockMovement.objects.filter(
            product=stocked_product, reference=invoice.invoice_number
        ).count()
        assert movement_count_before == 0

        # No GL journal posted at creation time
        assert not JournalEntry.objects.filter(
            organisation=organisation, source_type="sale", source_ref=str(invoice.id)
        ).exists()

        # Now fulfill it
        fulfilled = SaleService.fulfill_invoice(invoice, actor=user)

        assert fulfilled.fulfilled_at is not None

        # Exactly one stock movement per line item
        movements_after = StockMovement.objects.filter(
            product=stocked_product, reference=invoice.invoice_number
        )
        assert movements_after.count() == 1

        stock_after_fulfill = StockItem.objects.get(
            product=stocked_product, warehouse=warehouse
        ).quantity_on_hand
        assert stock_after_fulfill == initial_stock - Decimal("5")

        # Exactly one JournalEntry posted
        journal_entries = JournalEntry.objects.filter(
            organisation=organisation, source_type="sale", source_ref=str(invoice.id)
        )
        assert journal_entries.count() == 1

        # Fulfilling again must raise
        with pytest.raises(ValueError):
            SaleService.fulfill_invoice(fulfilled, actor=user)


@pytest.mark.integration
class TestDeleteInvoice:

    def test_delete_invoice_reverses_gl_and_stock_and_balance(
        self, auth_client, user, organisation, stocked_product, warehouse, customer
    ):
        """
        Deleting a normal (non-deferred) paid invoice must:
          - create a reversing JournalEntry whose lines net every account back to zero
            against the original entry (debits/credits swapped, same amounts)
          - restore stock to pre-sale levels
          - reset customer outstanding_balance
          - soft-delete Invoice/SaleItems/SalePayments (invisible to default manager,
            still visible via all_objects)
        """
        initial_stock = StockItem.objects.get(
            product=stocked_product, warehouse=warehouse
        ).quantity_on_hand
        initial_balance = customer.outstanding_balance

        response = auth_client.post("/api/v1/sales/invoices/", {
            "customer_id": str(customer.id),
            "warehouse_id": str(warehouse.id),
            "payment_method": "bank_transfer",
            # amount_paid is clamped to the invoice's effective due amount, so
            # sending a large value guarantees a full payment regardless of tax.
            "amount_paid": "999999999",
            "items": [
                {"product_id": str(stocked_product.id), "quantity": "3"},
            ],
        }, format="json")
        assert response.status_code == 201
        invoice_id = response.data["id"]

        invoice = Invoice.objects.get(id=invoice_id)
        assert invoice.status == Invoice.Status.PAID
        assert SalePayment.objects.filter(invoice_id=invoice_id).exists()

        original_entry = JournalEntry.objects.get(
            organisation=organisation, source_type="sale", source_ref=str(invoice.id)
        )
        original_lines = {
            (str(l.account_id),): (l.debit, l.credit) for l in original_entry.lines.all()
        }

        delete_resp = auth_client.post(f"/api/v1/sales/invoices/{invoice_id}/delete_invoice/")
        assert delete_resp.status_code == 204

        # Reversing journal entry exists and nets every account back to zero
        reversing_entry = JournalEntry.objects.get(
            organisation=organisation, source_type="reversal", source_ref=str(original_entry.id)
        )
        reversing_lines = {
            (str(l.account_id),): (l.debit, l.credit) for l in reversing_entry.lines.all()
        }
        assert set(reversing_lines.keys()) == set(original_lines.keys())
        for key, (orig_debit, orig_credit) in original_lines.items():
            rev_debit, rev_credit = reversing_lines[key]
            # Swapped: original debit becomes reversal credit, and vice versa
            assert rev_debit == orig_credit
            assert rev_credit == orig_debit
            # Net effect per account across both entries is zero
            assert (orig_debit - orig_credit) + (rev_debit - rev_credit) == Decimal("0")

        total_orig_debit = sum(d for d, c in original_lines.values())
        total_orig_credit = sum(c for d, c in original_lines.values())
        total_rev_debit = sum(d for d, c in reversing_lines.values())
        total_rev_credit = sum(c for d, c in reversing_lines.values())
        assert total_orig_debit == total_orig_credit  # original entry was balanced
        assert total_rev_debit == total_rev_credit     # reversal is balanced too
        assert total_rev_debit == total_orig_credit
        assert total_rev_credit == total_orig_debit

        # Stock restored to pre-sale level
        stock_after_delete = StockItem.objects.get(
            product=stocked_product, warehouse=warehouse
        ).quantity_on_hand
        assert stock_after_delete == initial_stock

        # Customer balance reset (bank_transfer isn't a credit sale, so balance
        # should be unaffected throughout — verifies no stray mutation either)
        customer.refresh_from_db()
        assert customer.outstanding_balance == initial_balance

        # Soft-deleted: invisible to default manager...
        assert not Invoice.objects.filter(id=invoice_id).exists()
        assert not SaleItem.objects.filter(invoice_id=invoice_id).exists()
        assert not SalePayment.objects.filter(invoice_id=invoice_id).exists()

        # ...but still visible via all_objects (soft-delete, not hard-delete)
        deleted_invoice = Invoice.all_objects.get(id=invoice_id)
        assert deleted_invoice.is_deleted is True
        assert SaleItem.all_objects.filter(invoice_id=invoice_id).exists()
        assert SalePayment.all_objects.filter(invoice_id=invoice_id).exists()

    def test_delete_invoice_resets_credit_customer_balance(
        self, auth_client, organisation, stocked_product, warehouse, customer
    ):
        """A credit-sale invoice's outstanding balance contribution must be reversed on delete."""
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
        invoice_id = response.data["id"]

        customer.refresh_from_db()
        balance_after_sale = customer.outstanding_balance
        assert balance_after_sale > initial_balance

        delete_resp = auth_client.post(f"/api/v1/sales/invoices/{invoice_id}/delete_invoice/")
        assert delete_resp.status_code == 204

        customer.refresh_from_db()
        assert customer.outstanding_balance == initial_balance
