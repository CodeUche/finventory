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

    def test_approving_own_bill_is_refused_with_reason_when_someone_else_can_approve(self):
        """The rule raised ValueError past the view: a 500 and "An unexpected
        error occurred" instead of the actual reason."""
        from apps.payroll.test_track_a import _make_user as mk_user
        from apps.tenancy.models import Membership
        Membership.objects.create(user=mk_user("second_admin@example.com"), organisation=self.org,
                                  role="admin", is_active=True)
        res = self.client.post(f"/api/v1/bills/{self.bill.id}/approve/")
        self.assertEqual(res.status_code, 400, res.content[:300])
        self.assertIn("another person can approve", res.json()["error"])
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.RECEIVED)

    def test_a_sole_owner_can_approve_their_own_bill(self):
        """Nobody else can approve, so refusing would strand the business."""
        res = self.client.post(f"/api/v1/bills/{self.bill.id}/approve/")
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.status, Bill.APPROVED)

    def test_a_bill_cannot_be_paid_before_it_is_approved(self):
        for status in (Bill.DRAFT, Bill.RECEIVED):
            Bill.objects.filter(pk=self.bill.pk).update(status=status)
            res = self._pay("100")
            self.assertEqual(res.status_code, 400, (status, res.content[:200]))
            self.assertIn("Approve this bill", res.json()["error"])

    def _pay(self, amount):
        return self.client.post(
            f"/api/v1/bills/{self.bill.id}/pay/",
            {"amount": amount, "payment_date": str(date.today()), "method": "cash"},
            format="json",
        )

    def test_payment_above_amount_due_is_refused(self):
        Bill.objects.filter(pk=self.bill.pk).update(status=Bill.APPROVED)
        res = self._pay("1000.01")
        self.assertEqual(res.status_code, 400, res.content[:300])
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.amount_paid, Decimal("0"))
        self.assertEqual(self.bill.payments.count(), 0)

    def test_paid_bill_cannot_be_paid_again(self):
        Bill.objects.filter(pk=self.bill.pk).update(status=Bill.APPROVED)
        self.assertEqual(self._pay("1000").status_code, 200)
        res = self._pay("1")
        self.assertEqual(res.status_code, 400, res.content[:300])
        self.bill.refresh_from_db()
        self.assertEqual(self.bill.amount_paid, Decimal("1000"))
        self.assertEqual(self.bill.status, Bill.PAID)

    def test_payment_response_reflects_the_new_balance(self):
        Bill.objects.filter(pk=self.bill.pk).update(status=Bill.APPROVED)
        res = self._pay("400")
        self.assertEqual(res.status_code, 200, res.content[:300])
        self.assertEqual(Decimal(res.json()["amount_due"]), Decimal("600"))
        self.assertEqual(res.json()["status"], Bill.PARTIALLY_PAID)

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


class ApprovePoBillTests(TestCase):
    """Approving a bill that came from a PO delivery posted it a second time
    under a key the duplicate check could not see: AP doubled, the cost hit
    General Expense as well as Inventory, input VAT was claimed twice."""

    def test_approving_a_po_bill_posts_nothing_new(self):
        from apps.accounting.models import Account, JournalEntry
        from apps.accounting.services import AccountingService
        from apps.bills.services import BillService
        from apps.inventory.models import Product, Warehouse
        from apps.purchases.models import PurchaseOrder, PurchaseOrderItem
        from apps.purchases.services import PurchaseService
        from apps.tenancy.models import Membership
        from apps.payroll.test_track_a import _make_user as mk_user

        owner = _make_user("po_bill_owner@example.com")
        org = _make_org(owner, "PO Bill Org")
        _upgrade_to_business(org)
        approver = mk_user("po_bill_approver@example.com")
        Membership.objects.create(user=approver, organisation=org, role="admin", is_active=True)
        supplier = Supplier.objects.create(organisation=org, name="Supplier Z")
        wh = Warehouse.objects.create(organisation=org, name="Main", is_default=True)
        product = Product.objects.create(organisation=org, sku="POB", name="Goods",
                                         cost_price=Decimal("1000"), selling_price=Decimal("1500"))
        po = PurchaseOrder.objects.create(
            organisation=org, supplier=supplier, warehouse=wh, po_number=PurchaseOrder.generate_number(org),
            order_date=date.today(), subtotal=Decimal("10000"), tax_amount=Decimal("750"),
            total_amount=Decimal("10750"), created_by=owner,
        )
        item = PurchaseOrderItem.objects.create(
            organisation=org, purchase_order=po, product=product, quantity_ordered=Decimal("10"),
            unit_cost=Decimal("1000"), line_total=Decimal("10000"), tax_rate=Decimal("7.5"),
        )
        PurchaseService.receive_purchase_order(po, [{"item_id": str(item.id), "quantity_received": "10"}], owner)
        bill = Bill.objects.get(organisation=org, source_purchase_order=po)
        ap = Account.objects.get(organisation=org, code="2001")
        before = AccountingService._ledger_balance(ap)
        entries = JournalEntry.objects.filter(organisation=org).count()

        BillService.approve_bill(bill, approver)

        bill.refresh_from_db()
        self.assertEqual(bill.status, Bill.APPROVED)
        self.assertEqual(AccountingService._ledger_balance(ap), before)
        self.assertEqual(JournalEntry.objects.filter(organisation=org).count(), entries)
