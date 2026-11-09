"""
process_return used to swallow a GL journal-posting failure: the return
record, restocked stock and any refund payout would all commit while the
credit note silently never reached the ledger, with nothing to tell the
user. process_return runs inside @transaction.atomic, so letting the
journal failure propagate instead rolls the whole return back together —
it either all commits or none of it does, and the caller sees an error.
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.inventory.models import Product, Warehouse
from apps.sales.models import Invoice, SaleReturn
from apps.tenancy.services import OrganisationService


def _make_user(email="return_atomic@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Return", last_name="Atomic", is_verified=True,
    )


def _make_org(user, name="Return Atomicity Org"):
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


class ReturnGLAtomicityTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        self.client = _auth_client(self.user, self.org)
        self.warehouse = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.product = Product.objects.create(
            organisation=self.org, sku="RET-ATOMIC-1", name="Returnable Item",
            product_type="service", cost_price=0, selling_price=5000, unit_of_measure="unit",
        )
        res = self.client.post("/api/v1/sales/invoices/", {
            "customer_id": None,
            "warehouse_id": str(self.warehouse.id),
            "payment_method": "cash",
            "items": [{"product_id": str(self.product.id), "quantity": 1, "unit_price": "5000.00"}],
        }, format="json")
        self.assertIn(res.status_code, (200, 201), msg=str(res.data))
        self.invoice = Invoice.objects.get(id=res.data["id"])
        self.sale_item = self.invoice.items.first()

    def _process_return(self):
        return self.client.post(
            f"/api/v1/sales/invoices/{self.invoice.id}/process_return/",
            {
                "items": [{"sale_item_id": str(self.sale_item.id), "quantity_returned": 1}],
                "reason": "defective",
                "notes": "",
                "restocked": True,
            },
            format="json",
        )

    def test_a_gl_posting_failure_rolls_back_the_whole_return(self):
        with patch(
            "apps.accounting.services.AccountingService.post_journal_entry",
            side_effect=Exception("GL account not configured"),
        ):
            res = self._process_return()

        self.assertEqual(res.status_code, 422, msg=str(res.data))
        self.assertEqual(SaleReturn.objects.filter(organisation=self.org).count(), 0)
        self.sale_item.refresh_from_db()
        self.assertEqual(self.sale_item.quantity_returned or Decimal("0"), Decimal("0"))
        self.invoice.refresh_from_db()
        self.assertNotEqual(self.invoice.status, Invoice.Status.RETURNED)

    def test_a_clean_return_still_commits_everything_together(self):
        res = self._process_return()
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(SaleReturn.objects.filter(organisation=self.org).count(), 1)
        self.sale_item.refresh_from_db()
        self.assertEqual(self.sale_item.quantity_returned, Decimal("1"))
        from apps.accounting.models import JournalEntry
        self.assertTrue(
            JournalEntry.objects.filter(organisation=self.org, source_type="sale_return").exists()
        )
