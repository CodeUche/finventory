"""
Bill status-transition tests (finding H-4).

BillViewSet.partial_update accepted `status` in its allowed-field set and wrote
it with setattr + save() and no transition validation, so
PATCH /bills/{id}/ {"status": "paid"} marked a supplier liability settled while
amount_paid stayed at 0 and no BillPayment row existed.

That corrupts AP aging in both directions: it can hide a real unpaid liability,
or fabricate a settled one. The dedicated approve / pay / void actions are the
paths that keep amount_paid, the payment records and the GL consistent.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounting.tests import _make_user, _make_org, _upgrade_to_business, _auth_client
from apps.bills.models import Bill
from apps.suppliers.models import Supplier


class BillStatusBypassTests(TestCase):
    def setUp(self):
        self.user = _make_user("billstatus_owner@example.com")
        self.org = _make_org(self.user, "Bill Status Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        self.supplier = Supplier.objects.create(organisation=self.org, name="Supplier Y")
        self.bill = Bill.objects.create(
            organisation=self.org,
            supplier=self.supplier,
            bill_number="BILL-STATUS-1",
            status=Bill.RECEIVED,
            issue_date=date.today(),
            due_date=date.today(),
            subtotal=Decimal("1000"),
            total_amount=Decimal("1000"),
            amount_due=Decimal("1000"),
            created_by=self.user,
        )

    def _patch(self, payload):
        return self.client.patch(
            f"/api/v1/bills/{self.bill.id}/", payload, format="json",
        )

    # --- the bypass itself -------------------------------------------------

    def test_cannot_mark_paid_via_patch(self):
        res = self._patch({"status": Bill.PAID})
        self.assertIn(
            res.status_code, (400, 422),
            "PATCH marked the bill paid with amount_paid still 0 and no "
            "BillPayment recorded (H-4)",
        )
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.RECEIVED)
        self.assertEqual(self.bill.amount_paid, Decimal("0"))

    def test_cannot_mark_partially_paid_via_patch(self):
        res = self._patch({"status": Bill.PARTIALLY_PAID})
        self.assertIn(res.status_code, (400, 422))
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.RECEIVED)

    def test_cannot_approve_via_patch(self):
        """Approval is a control step; it must not be reachable by field write."""
        res = self._patch({"status": Bill.APPROVED})
        self.assertIn(res.status_code, (400, 422))
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.RECEIVED)

    def test_cannot_void_via_patch(self):
        res = self._patch({"status": Bill.VOIDED})
        self.assertIn(res.status_code, (400, 422))
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.RECEIVED)

    def test_paid_status_does_not_leave_amount_paid_inconsistent(self):
        """The reason this matters: status and amount_paid must not diverge."""
        self._patch({"status": Bill.PAID})
        self.bill.refresh_from_db()
        self.assertFalse(
            self.bill.status == Bill.PAID and self.bill.amount_paid == Decimal("0"),
            "bill reads as paid while amount_paid is 0 — AP aging is now wrong",
        )

    # --- what must keep working -------------------------------------------

    def test_can_still_edit_administrative_fields(self):
        res = self._patch({"notes": "Awaiting supplier credit note", "reference": "REF-9"})
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.notes, "Awaiting supplier credit note")
        self.assertEqual(self.bill.reference, "REF-9")

    def test_can_still_set_non_financial_status(self):
        res = self._patch({"status": Bill.DRAFT})
        self.assertEqual(
            res.status_code, 200,
            "blocking non-financial statuses would over-restrict the edit path",
        )
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.DRAFT)

    def test_pay_action_is_still_the_way_to_settle_a_bill(self):
        """The legitimate path must remain open and must move amount_paid."""
        self.bill.status = Bill.APPROVED
        self.bill.save(update_fields=["status"])
        res = self.client.post(
            f"/api/v1/bills/{self.bill.id}/pay/",
            {"amount": "1000", "payment_date": str(date.today())},
            format="json",
        )
        self.assertIn(res.status_code, (200, 201), res.content[:300])
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.amount_paid, Decimal("1000"))
        self.assertEqual(self.bill.status, Bill.PAID)
