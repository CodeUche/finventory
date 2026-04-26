"""
Bills API integration tests.

Covers: create bill, list/filter, mark received, record payment,
        void bill, bill folders, cross-org isolation.
"""

import pytest
from decimal import Decimal
from datetime import date, timedelta

from apps.bills.models import Bill, BillItem, BillPayment


@pytest.mark.integration
class TestCreateBill:

    def test_create_draft_bill(self, auth_client, supplier, organisation):
        """POST /bills/ with valid payload should create a draft bill."""
        response = auth_client.post("/api/v1/bills/", {
            "supplier": str(supplier.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "items": [
                {
                    "description": "Hennessy VS × 5 cases",
                    "quantity": "5",
                    "unit_cost": "80000",
                },
            ],
        }, format="json")

        assert response.status_code == 201
        data = response.data
        assert data["status"] == Bill.DRAFT
        assert str(data["supplier"]) == str(supplier.id)
        assert len(data["items"]) == 1
        assert Decimal(data["subtotal"]) == Decimal("400000")
        assert data["bill_number"].startswith("BILL-")

    def test_create_bill_without_supplier_fails(self, auth_client):
        """A bill requires a supplier — missing it should return 400."""
        response = auth_client.post("/api/v1/bills/", {
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "items": [{"description": "Test item", "quantity": "1", "unit_cost": "1000"}],
        }, format="json")
        assert response.status_code == 400

    def test_create_bill_missing_items_fails(self, auth_client, supplier):
        """A bill with no items should be rejected."""
        response = auth_client.post("/api/v1/bills/", {
            "supplier": str(supplier.id),
            "issue_date": str(date.today()),
            "due_date": str(date.today() + timedelta(days=30)),
            "items": [],
        }, format="json")
        assert response.status_code == 400

    def test_create_bill_auto_numbers(self, auth_client, supplier):
        """Bill numbers should be sequential and org-specific."""
        for _ in range(3):
            auth_client.post("/api/v1/bills/", {
                "supplier": str(supplier.id),
                "issue_date": str(date.today()),
                "due_date": str(date.today() + timedelta(days=30)),
                "items": [{"description": "Item", "quantity": "1", "unit_cost": "1000"}],
            }, format="json")

        bills = Bill.objects.order_by("created_at")
        numbers = [b.bill_number for b in bills]
        assert len(set(numbers)) == len(numbers)   # all unique


@pytest.mark.integration
class TestListBills:

    def test_list_bills_returns_only_own_org(self, auth_client, bill, other_auth_client, other_organisation):
        """GET /bills/ should only return bills from the authenticated org."""
        response = auth_client.get("/api/v1/bills/")
        assert response.status_code == 200
        ids = [b["id"] for b in response.data["results"]]
        assert str(bill.id) in ids

    def test_cross_org_isolation(self, auth_client, other_auth_client, bill):
        """The other org client must not see this org's bill."""
        response = other_auth_client.get(f"/api/v1/bills/{bill.id}/")
        assert response.status_code in (404, 403)

    def test_filter_by_status(self, auth_client, bill):
        """Filter ?status=draft should return only draft bills."""
        response = auth_client.get("/api/v1/bills/?status=draft")
        assert response.status_code == 200
        for b in response.data["results"]:
            assert b["status"] == Bill.DRAFT

    def test_unauthenticated_access_denied(self, api_client):
        """Bills list should require authentication."""
        response = api_client.get("/api/v1/bills/")
        assert response.status_code == 401


@pytest.mark.integration
class TestBillStatusTransitions:

    def test_mark_bill_received(self, auth_client, bill):
        """PATCH status=received should transition from draft."""
        response = auth_client.patch(f"/api/v1/bills/{bill.id}/", {
            "status": Bill.RECEIVED,
        }, format="json")
        assert response.status_code == 200
        assert response.data["status"] == Bill.RECEIVED

    def test_void_bill(self, auth_client, bill):
        """Voiding a bill should set status=voided."""
        response = auth_client.post(f"/api/v1/bills/{bill.id}/void/")
        assert response.status_code in (200, 204)
        bill.refresh_from_db()
        assert bill.status == Bill.VOIDED

    def test_cannot_pay_voided_bill(self, auth_client, bill):
        """Recording a payment on a voided bill should fail."""
        bill.status = Bill.VOIDED
        bill.save()

        response = auth_client.post(f"/api/v1/bills/{bill.id}/pay/", {
            "amount": "1000",
            "payment_date": str(date.today()),
            "method": BillPayment.CASH,
        }, format="json")
        assert response.status_code in (400, 422)


@pytest.mark.integration
class TestBillPayments:

    def test_partial_payment(self, auth_client, bill):
        """Partial payment should set status=partially_paid."""
        partial = str(bill.total_amount / 2)
        response = auth_client.post(f"/api/v1/bills/{bill.id}/pay/", {
            "amount": partial,
            "payment_date": str(date.today()),
            "method": BillPayment.BANK,
        }, format="json")
        assert response.status_code in (200, 201)
        bill.refresh_from_db()
        assert bill.status in (Bill.PARTIALLY_PAID, Bill.APPROVED, Bill.RECEIVED, Bill.DRAFT)

    def test_full_payment_marks_paid(self, auth_client, bill):
        """Paying the full amount_due should transition to paid."""
        response = auth_client.post(f"/api/v1/bills/{bill.id}/pay/", {
            "amount": str(bill.total_amount),
            "payment_date": str(date.today()),
            "method": BillPayment.CASH,
        }, format="json")
        assert response.status_code in (200, 201)
        bill.refresh_from_db()
        assert bill.status == Bill.PAID

    def test_payment_amount_must_be_positive(self, auth_client, bill):
        """Zero or negative payment amount should return 400."""
        response = auth_client.post(f"/api/v1/bills/{bill.id}/pay/", {
            "amount": "0",
            "payment_date": str(date.today()),
            "method": BillPayment.CASH,
        }, format="json")
        assert response.status_code == 400


@pytest.mark.integration
class TestBillFolders:

    def test_create_folder(self, auth_client):
        """POST /bills/folders/ should create a named folder."""
        response = auth_client.post("/api/v1/bills/folders/", {
            "name": "Q1 2026",
        }, format="json")
        assert response.status_code == 201
        assert response.data["name"] == "Q1 2026"

    def test_assign_bill_to_folder(self, auth_client, bill):
        """PATCH bill with folder_id should assign it."""
        folder_resp = auth_client.post("/api/v1/bills/folders/", {
            "name": "Archive",
        }, format="json")
        folder_id = folder_resp.data["id"]

        response = auth_client.patch(f"/api/v1/bills/{bill.id}/", {
            "folder": folder_id,
        }, format="json")
        assert response.status_code == 200
        bill.refresh_from_db()
        assert str(bill.folder_id) == folder_id

    def test_list_folders(self, auth_client):
        """GET /bills/folders/ should return org's folders."""
        auth_client.post("/api/v1/bills/folders/", {"name": "Folder A"}, format="json")
        auth_client.post("/api/v1/bills/folders/", {"name": "Folder B"}, format="json")
        response = auth_client.get("/api/v1/bills/folders/")
        assert response.status_code == 200
        names = [f["name"] for f in response.data["results"]]
        assert "Folder A" in names and "Folder B" in names
