"""Tests for suppliers: statement opening (brought-forward) balance."""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.tests import _upgrade_to_business
from apps.authentication.models import User
from apps.bills.models import Bill
from apps.suppliers.models import Supplier
from apps.tenancy.services import OrganisationService


def _make_user(email="supp_owner@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Supp", last_name="Owner", is_verified=True,
    )


def _make_org(user, name="Supp Org"):
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


class SupplierStatementOpeningBalanceTests(TestCase):
    """
    C3b/C3c: mirrors CustomerStatementOpeningBalanceTests. Suppliers have no
    stored running balance the way Customer.outstanding_balance is — the view
    computes an all-time current_balance on the fly (take-on + all-time
    billed - paid - returned) and this test's opening_balance is derived
    backward from THAT the same way, so it should behave identically.
    """

    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        self.supplier = Supplier.objects.create(organisation=self.org, code="SUPST01", name="Statement Supplier")

    def _bill(self, issue_date, amount="10000.00"):
        res = self.client.post("/api/v1/bills/", {
            "supplier": str(self.supplier.id),
            "issue_date": issue_date,
            "due_date": issue_date,
            "status": "approved",
            "items": [{"description": "Line item", "quantity": 1, "unit_cost": amount}],
        }, format="json")
        self.assertIn(res.status_code, (200, 201), msg=str(res.data))
        return Bill.objects.get(id=res.data["id"])

    def _payment(self, bill, amount, payment_date):
        res = self.client.post(f"/api/v1/bills/{bill.id}/pay/", {
            "amount": str(amount), "payment_date": payment_date, "method": "cash",
        }, format="json")
        self.assertEqual(res.status_code, 200, msg=str(res.data))

    def test_opening_balance_excludes_period_transactions(self):
        self._bill(issue_date="2026-01-10")   # before window
        self._bill(issue_date="2026-03-15")   # inside window — must not count in opening

        res = self.client.get(f"/api/v1/suppliers/{self.supplier.id}/statement/", {
            "date_from": "2026-03-01", "date_to": "2026-03-31",
        })
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        summary = res.data["summary"]
        self.assertEqual(Decimal(summary["opening_balance"]), Decimal("10000.00"))
        self.assertEqual(Decimal(summary["total_billed"]), Decimal("10000.00"))
        self.assertEqual(Decimal(summary["balance_due"]), Decimal("20000.00"))

    def test_opening_balance_reflects_a_prior_payment(self):
        bill = self._bill(issue_date="2026-01-10")
        self._payment(bill, Decimal("4000"), "2026-01-20")

        res = self.client.get(f"/api/v1/suppliers/{self.supplier.id}/statement/", {
            "date_from": "2026-02-01", "date_to": "2026-02-28",
        })
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(Decimal(res.data["summary"]["opening_balance"]), Decimal("6000.00"))

    def test_balance_due_reconciles_to_live_current_balance_when_date_to_is_today(self):
        from django.utils import timezone
        self._bill(issue_date="2026-01-10")
        self._bill(issue_date=str(timezone.now().date()))

        res = self.client.get(f"/api/v1/suppliers/{self.supplier.id}/statement/", {
            "date_from": "2026-01-01",
        })
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        summary = res.data["summary"]
        self.assertEqual(Decimal(summary["balance_due"]), Decimal(summary["outstanding_balance"]))

    def test_opening_balance_is_zero_with_no_prior_activity(self):
        self._bill(issue_date="2026-06-01")
        res = self.client.get(f"/api/v1/suppliers/{self.supplier.id}/statement/", {
            "date_from": "2026-06-01", "date_to": "2026-06-30",
        })
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(Decimal(res.data["summary"]["opening_balance"]), Decimal("0"))

    def test_opening_balance_includes_the_take_on_amount(self):
        self.supplier.opening_balance = Decimal("5000")
        self.supplier.opening_balance_date = "2025-12-01"
        self.supplier.save(update_fields=["opening_balance", "opening_balance_date"])

        self._bill(issue_date="2026-01-10")

        res = self.client.get(f"/api/v1/suppliers/{self.supplier.id}/statement/", {
            "date_from": "2026-02-01", "date_to": "2026-02-28",
        })
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        # 5000 take-on + 10000 January bill, both before Feb 1
        self.assertEqual(Decimal(res.data["summary"]["opening_balance"]), Decimal("15000.00"))
