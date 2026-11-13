"""
M5: a sales return refunded "to account" moved the GL's Accounts Receivable
line, but only updated the customer's own CreditTransaction ledger
(outstanding_balance) when the original invoice happened to be a credit
sale. A cash- or bank-paid invoice refunded to account left the GL saying
money was now owed back to the customer while the customer's own balance
record never moved -- invisible to anything that reads
customer.outstanding_balance or their statement directly.
"""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.customers.models import Customer
from apps.inventory.models import Product, Warehouse
from apps.sales.models import Invoice, SalePayment
from apps.tenancy.services import OrganisationService


def _make_user(email="refund_balance@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Refund", last_name="Balance", is_verified=True,
    )


def _make_org(user, name="Refund Balance Org"):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _auth_client(user, org):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return client


class CashInvoiceRefundToAccountTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        self.client = _auth_client(self.user, self.org)
        self.warehouse = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.customer = Customer.objects.create(
            organisation=self.org, code="C-REFUND", name="Regular Customer", customer_type="retail",
        )
        self.product = Product.objects.create(
            organisation=self.org, sku="REFUND-P1", name="Refundable Item",
            product_type="service", cost_price=0, selling_price=5000, unit_of_measure="unit",
        )
        res = self.client.post("/api/v1/sales/invoices/", {
            "customer_id": str(self.customer.id),
            "warehouse_id": str(self.warehouse.id),
            "payment_method": "cash",
            "amount_paid": "5000.00",
            "items": [{"product_id": str(self.product.id), "quantity": 1, "unit_price": "5000.00"}],
        }, format="json")
        self.assertIn(res.status_code, (200, 201), msg=str(res.data))
        self.invoice = Invoice.objects.get(id=res.data["id"])
        self.assertEqual(self.invoice.amount_paid, Decimal("5000.00"))  # really paid, like a till sale
        self.sale_item = self.invoice.items.first()
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, Decimal("0"))

    def _process_return(self, refund_method):
        return self.client.post(
            f"/api/v1/sales/invoices/{self.invoice.id}/process_return/",
            {
                "items": [{"sale_item_id": str(self.sale_item.id), "quantity_returned": 1}],
                "reason": "defective",
                "notes": "",
                "restocked": True,
                "refund_method": refund_method,
            },
            format="json",
        )

    def test_refund_to_account_credits_the_customer_balance_not_cash(self):
        res = self._process_return("account")
        self.assertEqual(res.status_code, 201, msg=str(res.data))

        self.assertFalse(
            SalePayment.objects.filter(organisation=self.org, invoice=self.invoice, amount__lt=0).exists(),
            "refund_method=account must not pay out cash or bank",
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, Decimal("-5000.00"))  # in credit, not owing

        from apps.credits.models import CreditTransaction
        txn = CreditTransaction.objects.filter(organisation=self.org, customer=self.customer).first()
        self.assertIsNotNone(txn, "the customer's own credit ledger must record the refund")
        self.assertEqual(txn.amount, Decimal("5000.00"))
        self.assertEqual(txn.balance_after, Decimal("-5000.00"))

    def test_refund_to_cash_still_pays_out_and_does_not_touch_customer_balance(self):
        res = self._process_return("cash")
        self.assertEqual(res.status_code, 201, msg=str(res.data))

        self.assertTrue(
            SalePayment.objects.filter(organisation=self.org, invoice=self.invoice, amount=Decimal("-5000.00")).exists()
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, Decimal("0"))  # unaffected: paid out, not kept
