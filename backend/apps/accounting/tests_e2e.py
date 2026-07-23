"""End-to-end user-journey test for the COA/GL feature.

Walks the ENTIRE journey a real user performs, in order, through the HTTP API —
the same endpoints the frontend calls — and asserts the reports balance at each
stage. This is the 'tested like a real user' end-to-end pass.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone  # noqa: F401 (kept for parity/debugging)

from apps.accounting.models import Account, AccountSubType
from apps.accounting.tests import (
    _make_user, _make_org, _upgrade_to_business, _auth_client,
)


class EndToEndUserJourneyTest(TestCase):
    def setUp(self):
        self.user = _make_user("journey_owner@example.com")
        self.org = _make_org(self.user, "Journey Org")
        _upgrade_to_business(self.org)
        self.c = _auth_client(self.user, self.org)

    def _tb_balanced(self):
        # Mirrors the Trial Balance screen: balances come back normal-signed, so the
        # debit/credit columns are split by account type, not by sign.
        res = self.c.get("/api/v1/accounting/accounts/trial_balance/")
        self.assertEqual(res.status_code, 200)
        DEBIT_NORMAL = {"asset", "expense", "cogs"}
        dr = sum(float(r["balance"]) for r in res.data if r["type"] in DEBIT_NORMAL)
        cr = sum(float(r["balance"]) for r in res.data if r["type"] not in DEBIT_NORMAL)
        return abs(dr - cr) < 0.01

    def _bs(self):
        res = self.c.get("/api/v1/accounting/accounts/balance_sheet/")
        self.assertEqual(res.status_code, 200)
        return res.data

    def test_full_journey(self):
        # 1. Chart of accounts seeded + listable
        res = self.c.get("/api/v1/accounting/accounts/")
        self.assertEqual(res.status_code, 200)
        self.assertGreater(len(res.data.get("results") or res.data), 0)

        # 2. Taxonomy powers the dependent dropdowns
        res = self.c.get("/api/v1/accounting/accounts/taxonomy/")
        self.assertEqual(res.status_code, 200)
        groups = {g["group"] for g in res.data["groups"]}
        self.assertTrue({"Income", "Cash & Cash Equivalent", "Indirect Cost", "Equity"} <= groups)

        # 3. A brand-new P&L (revenue) account CAN be created (client's complaint)
        sub = AccountSubType.objects.get(organisation=self.org, name="Other Income")
        res = self.c.post("/api/v1/accounting/accounts/", {
            "code": "4200", "name": "Consulting Income", "account_type": "revenue",
            "account_group": "Income", "sub_type": str(sub.id),
        }, format="json")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        rev_id = res.data["id"]

        # 4. A manual journal CAN be posted to that P&L account and shows on the TB
        cash = Account.objects.get(organisation=self.org, code="1001")
        je = self.c.post("/api/v1/accounting/journal/", {
            "description": "Consulting sale", "entry_date": "2026-02-01",
            "lines": [
                {"account": str(cash.id), "debit": "300000", "credit": "0"},
                {"account": rev_id, "debit": "0", "credit": "300000"},
            ],
        }, format="json")
        self.assertIn(je.status_code, [200, 201], msg=str(je.data))
        post = self.c.post(f"/api/v1/accounting/journal/{je.data['id']}/post_entry/")
        self.assertIn(post.status_code, [200, 201])
        tb = self.c.get("/api/v1/accounting/accounts/trial_balance/")
        self.assertTrue(any(r["code"] == "4200" for r in tb.data), "P&L account missing from TB")
        self.assertTrue(self._tb_balanced())

        # 5. Balance Sheet balances (the headline bug) with profit rolled to equity
        bs = self._bs()
        self.assertTrue(bs["balanced"], msg=f"BS not balanced: {bs}")
        self.assertAlmostEqual(float(bs["current_year_earnings"]), 300000.0, places=2)

        # 6. Direct manual journal to a CONTROL account (AR) is blocked
        ar = Account.objects.get(organisation=self.org, code="1100")
        blocked = self.c.post("/api/v1/accounting/journal/", {
            "description": "Illegal AR post", "entry_date": "2026-02-02",
            "lines": [
                {"account": str(ar.id), "debit": "1000", "credit": "0"},
                {"account": str(cash.id), "debit": "0", "credit": "1000"},
            ],
        }, format="json")
        self.assertEqual(blocked.status_code, 400)

        # 7. Opening balances wizard (accounts tab) — posts and stays balanced
        bank = Account.objects.get(organisation=self.org, code="1002")
        equity = Account.objects.get(organisation=self.org, code="3001")
        ob = self.c.post("/api/v1/accounting/accounts/opening_balances/", {
            "as_of_date": "2026-01-01",
            "entries": [
                {"account": str(bank.id), "amount": "5000000", "side": "debit"},
                {"account": str(equity.id), "amount": "5000000", "side": "credit"},
            ],
        }, format="json")
        self.assertEqual(ob.status_code, 201, msg=str(ob.data))
        self.assertTrue(self._bs()["balanced"])

        # 8. Sub-ledger opening balances (customers / suppliers / items) stay balanced
        from apps.customers.models import Customer
        from apps.suppliers.models import Supplier
        from apps.inventory.models import Product, Warehouse
        cust = Customer.objects.create(organisation=self.org, name="Journey Client")
        sup = Supplier.objects.create(organisation=self.org, code="JS1", name="Journey Supplier")
        wh = Warehouse.objects.create(organisation=self.org, name="WH", is_default=True)
        prod = Product.objects.create(organisation=self.org, sku="JP1", name="Item",
                                      cost_price=Decimal("50"), selling_price=Decimal("80"))
        sub_ob = self.c.post("/api/v1/accounting/accounts/subledger_opening_balances/", {
            "as_of_date": "2026-01-01",
            "customers": [{"id": str(cust.id), "amount": "400000"}],
            "suppliers": [{"id": str(sup.id), "amount": "150000"}],
            "items": [{"product_id": str(prod.id), "warehouse_id": str(wh.id), "quantity": "20", "unit_cost": "50"}],
        }, format="json")
        self.assertEqual(sub_ob.status_code, 201, msg=str(sub_ob.data))
        self.assertTrue(self._bs()["balanced"])

        # 9. General-ledger drill-down returns posted lines with a running balance
        led = self.c.get(f"/api/v1/accounting/accounts/{bank.id}/ledger/")
        self.assertEqual(led.status_code, 200)
        self.assertGreaterEqual(len(led.data["lines"]), 1)

        # 10. Journal approval workflow: draft -> submit -> approve+post
        expense = Account.objects.get(organisation=self.org, code="6700")
        draft = self.c.post("/api/v1/accounting/journal/", {
            "description": "Accrued expense", "entry_date": "2026-02-03",
            "lines": [
                {"account": str(expense.id), "debit": "20000", "credit": "0"},
                {"account": str(cash.id), "debit": "0", "credit": "20000"},
            ],
        }, format="json")
        self.assertIn(draft.status_code, [200, 201], msg=str(draft.data))
        did = draft.data["id"]
        self.assertEqual(self.c.post(f"/api/v1/accounting/journal/{did}/submit_for_approval/").status_code, 200)
        appr = self.c.post(f"/api/v1/accounting/journal/{did}/approve/", {"post": True}, format="json")
        self.assertEqual(appr.status_code, 200)
        self.assertEqual(appr.data["status"], "posted")

        # 11. Sub-type management: create a custom sub-type and see it listed
        st = self.c.post("/api/v1/accounting/account-sub-types/", {
            "name": "USSD Wallet", "account_group": "Cash & Cash Equivalent", "base_account_type": "asset",
        }, format="json")
        self.assertIn(st.status_code, [200, 201], msg=str(st.data))
        lst = self.c.get("/api/v1/accounting/account-sub-types/")
        names = [s["name"] for s in (lst.data.get("results") or lst.data)]
        self.assertIn("USSD Wallet", names)

        # Final invariant: TB balanced AND BS balanced together
        self.assertTrue(self._tb_balanced())
        self.assertTrue(self._bs()["balanced"])
