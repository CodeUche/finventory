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


class FixedAssetFullJourneyE2ETest(TestCase):
    """End-to-end Fixed Asset journey through the HTTP API — the exact calls the UI
    fires. A single real-user session: buy assets, bring one on as opening balance,
    capitalise a bill line, run a DRAFT depreciation batch and post it, dispose,
    transfer, revalue, pull every report, wire an asset type, and toggle the gated
    tax engine — asserting the register reconciles to the ledger at each stage."""

    def setUp(self):
        from apps.accounting.models import AccountMapping, Account
        from apps.inventory.models import Warehouse
        self.user = _make_user("fa_journey@example.com")
        self.org = _make_org(self.user, "FA Journey Org")
        _upgrade_to_business(self.org)
        self.c = _auth_client(self.user, self.org)
        # Deterministic funding accounts (a real org would map these in GL settings).
        m = AccountMapping.objects.get(organisation=self.org)
        m.bank_account = Account.objects.get(organisation=self.org, code="1002")
        m.cash_account = Account.objects.get(organisation=self.org, code="1001")
        m.accounts_payable = Account.objects.get(organisation=self.org, code="2001")
        m.general_expense_account = Account.objects.get(organisation=self.org, code="6700")
        m.save()
        self.wh = Warehouse.objects.create(organisation=self.org, name="Head Office", is_default=True)

    def _gl(self, code):
        res = self.c.get("/api/v1/accounting/accounts/trial_balance/")
        for r in res.data:
            if r["code"] == code:
                return float(r["balance"])
        return 0.0

    def _recon(self):
        res = self.c.get("/api/v1/accounting/assets/reconciliation/")
        self.assertEqual(res.status_code, 200)
        return res.data

    def _bs_balanced(self):
        res = self.c.get("/api/v1/accounting/accounts/balance_sheet/")
        self.assertEqual(res.status_code, 200)
        return res.data["balanced"]

    def test_full_fixed_asset_journey(self):
        from apps.suppliers.models import Supplier
        from apps.accounting.models import FixedAsset

        # 1. Open the Fixed Assets page — empty register, reconciled.
        res = self.c.get("/api/v1/accounting/assets/")
        self.assertEqual(res.status_code, 200)
        rows = res.data["results"] if isinstance(res.data, dict) and "results" in res.data else res.data
        self.assertEqual(len(rows), 0)
        self.assertTrue(self._recon()["reconciled"])

        # 2. Add a bank-funded asset (the "Add Asset" modal) → posts DR 1500 / CR Bank.
        a = self.c.post("/api/v1/accounting/assets/", {
            "name": "Toyota Hilux", "asset_code": "VEH-001", "category": "vehicle",
            "purchase_date": "2026-07-01", "purchase_cost": "1200000",
            "useful_life_years": 5, "residual_value": "0", "funding_source": "bank",
        }, format="json")
        self.assertEqual(a.status_code, 201, msg=str(a.data))
        asset_a = a.data["id"]
        self.assertTrue(a.data["acquisition_posted"])
        self.assertAlmostEqual(self._gl("1500"), 1200000.0, places=2)
        self.assertAlmostEqual(self._gl("1002"), -1200000.0, places=2)
        self.assertTrue(self._bs_balanced())

        # 3. Bring an already-owned asset on as an opening balance (take-on).
        b = self.c.post("/api/v1/accounting/assets/", {
            "name": "Legacy Truck", "asset_code": "VEH-002", "category": "vehicle",
            "purchase_date": "2026-07-01", "purchase_cost": "1000000",
            "useful_life_years": 5, "residual_value": "0",
            "funding_source": "none", "capitalisation_source": "opening_balance",
            "opening_accumulated_depreciation": "200000",
        }, format="json")
        self.assertEqual(b.status_code, 201, msg=str(b.data))
        self.assertAlmostEqual(self._gl("1500"), 2200000.0, places=2)
        self.assertAlmostEqual(self._gl("1510"), -200000.0, places=2)
        self.assertAlmostEqual(self._gl("3900"), 800000.0, places=2)  # take-on suspense
        self.assertTrue(self._bs_balanced())

        # 4. Capitalise a bill line — a supplier bill with a "capitalise" line creates
        #    the asset and books it to 1500 instead of an expense.
        supplier = Supplier.objects.create(organisation=self.org, name="PowerGen Ltd")
        bill = self.c.post("/api/v1/bills/", {
            "supplier": str(supplier.id), "issue_date": "2026-07-05", "due_date": "2026-08-05",
            "status": "approved", "tax_amount": "0",
            "items": [
                {"description": "Generator", "quantity": "1", "unit_cost": "800000",
                 "capitalise": True, "asset_category": "equipment", "useful_life_years": 5},
                {"description": "Cabling", "quantity": "1", "unit_cost": "200000"},
            ],
        }, format="json")
        self.assertIn(bill.status_code, [200, 201], msg=str(bill.data))
        self.assertAlmostEqual(self._gl("1500"), 3000000.0, places=2)   # +800k capital line
        self.assertAlmostEqual(self._gl("6700"), 200000.0, places=2)    # expense line
        self.assertAlmostEqual(self._gl("2001"), 1000000.0, places=2)   # AP gross
        self.assertEqual(FixedAsset.objects.filter(organisation=self.org, capitalisation_source="bill").count(), 1)
        asset_c = FixedAsset.objects.get(organisation=self.org, capitalisation_source="bill").id

        # 5. Reconciliation panel — register ties to the GL exactly.
        rec = self._recon()
        self.assertTrue(rec["reconciled"], msg=str(rec))
        self.assertAlmostEqual(float(rec["variance"]["cost"]), 0.0, places=2)

        # 6. Run depreciation as a DRAFT batch (accountant review). Entries are drafted,
        #    the ledger is NOT yet updated, so reconciliation correctly flags the gap.
        run = self.c.post("/api/v1/accounting/assets/run_depreciation/",
                          {"year": 2026, "month": 7, "draft": True}, format="json")
        self.assertEqual(run.status_code, 200, msg=str(run.data))
        self.assertEqual(run.data["entries_created"], 2)  # Hilux + Generator (Legacy occupies July via take-on)
        self.assertAlmostEqual(self._gl("1510"), -200000.0, places=2)  # unchanged — drafts not posted
        self.assertFalse(self._recon()["reconciled"])                  # variance surfaced

        # 7. Post the batch — drafts become posted, ledger catches up, reconciled again.
        post = self.c.post("/api/v1/accounting/assets/post_depreciation_batch/",
                           {"year": 2026, "month": 7}, format="json")
        self.assertEqual(post.status_code, 200, msg=str(post.data))
        self.assertAlmostEqual(self._gl("1510"), -233333.33, places=1)  # 200k + 20k + 13,333.33
        self.assertTrue(self._recon()["reconciled"])
        self.assertTrue(self._bs_balanced())

        # 8. Depreciation schedule (with forward projection) for one asset.
        sched = self.c.get(f"/api/v1/accounting/assets/{asset_a}/depreciation_schedule/?forecast=true")
        self.assertEqual(sched.status_code, 200)
        types = {r["type"] for r in sched.data["schedule"]}
        self.assertIn("actual", types)
        self.assertIn("projected", types)

        # 9. Dispose the Hilux for a gain → derecognised from the GL, gain to P&L.
        disp = self.c.post(f"/api/v1/accounting/assets/{asset_a}/dispose/",
                           {"proceeds": "1300000", "disposal_date": "2026-08-01"}, format="json")
        self.assertEqual(disp.status_code, 200, msg=str(disp.data))
        self.assertAlmostEqual(float(disp.data["gain_loss"]), 120000.0, places=2)  # 1.3m − 1.18m NBV
        self.assertAlmostEqual(self._gl("1500"), 1800000.0, places=2)  # Hilux cost removed
        self.assertAlmostEqual(self._gl("4200"), 120000.0, places=2)   # gain on disposal
        self.assertTrue(self._recon()["reconciled"])
        self.assertTrue(self._bs_balanced())
        drep = self.c.get("/api/v1/accounting/assets/disposal_report/")
        self.assertEqual(len(drep.data["rows"]), 1)

        # 10. Transfer the Legacy truck to a location.
        trf = self.c.post(f"/api/v1/accounting/assets/{b.data['id']}/transfer/",
                          {"to_location": str(self.wh.id), "to_cost_centre": "Operations",
                           "transfer_date": "2026-08-02"}, format="json")
        self.assertEqual(trf.status_code, 200, msg=str(trf.data))
        trep = self.c.get("/api/v1/accounting/assets/transfer_report/")
        self.assertEqual(len(trep.data["rows"]), 1)
        self.assertEqual(trep.data["rows"][0]["to_location"], "Head Office")

        # 11. Enable revaluation in Settings (org PATCH) and revalue the Generator.
        patch = self.c.patch(f"/api/v1/tenancy/organisations/{self.org.id}/",
                             {"fixed_asset_revaluation_enabled": True}, format="json")
        self.assertIn(patch.status_code, [200, 201])
        rev = self.c.post(f"/api/v1/accounting/assets/{asset_c}/revalue/",
                          {"new_value": "900000", "revaluation_date": "2026-08-03"}, format="json")
        self.assertEqual(rev.status_code, 200, msg=str(rev.data))
        self.assertGreater(self._gl("3200"), 0.0)   # revaluation surplus in equity
        self.assertTrue(self._bs_balanced())

        # 12. All the register/grouping reports respond with the expected totals.
        reg = self.c.get("/api/v1/accounting/assets/register_report/")
        self.assertEqual(reg.status_code, 200)
        self.assertGreater(float(reg.data["totals"]["cost"]), 0.0)
        self.assertEqual(self.c.get("/api/v1/accounting/assets/by_category/").status_code, 200)
        self.assertEqual(self.c.get("/api/v1/accounting/assets/by_location/").status_code, 200)

        # 13. Asset Types — create a type carrying method + GL accounts, use it on an asset.
        at = self.c.post("/api/v1/accounting/asset-types/", {
            "code": "MV", "name": "Motor Vehicles", "category": "vehicle",
            "depreciation_method": "straight_line", "useful_life_years": 4,
        }, format="json")
        self.assertIn(at.status_code, [200, 201], msg=str(at.data))
        typed = self.c.post("/api/v1/accounting/assets/", {
            "name": "Van", "asset_code": "VEH-003", "category": "vehicle",
            "purchase_date": "2026-08-01", "purchase_cost": "600000",
            "useful_life_years": 4, "residual_value": "0", "funding_source": "cash",
            "asset_type": at.data["id"],
        }, format="json")
        self.assertEqual(typed.status_code, 201, msg=str(typed.data))
        self.assertEqual(str(FixedAsset.objects.get(id=typed.data["id"]).asset_type_id), str(at.data["id"]))

        # 14. Toggle the gated NTA-2025 capital-allowance engine in Settings, confirm it
        #     now drives the tax computation (off by default = no effect).
        from apps.tax.services import CapitalAllowanceService
        off = CapitalAllowanceService.compute_assessable_profit(self.org, Decimal("1000000"), 2026)
        self.assertFalse(off["ca_enabled"])
        self.assertEqual(off["capital_allowances"], Decimal("0"))
        patch2 = self.c.patch(f"/api/v1/tenancy/organisations/{self.org.id}/",
                              {"capital_allowance_nta2025_enabled": True}, format="json")
        self.assertIn(patch2.status_code, [200, 201])
        self.org.refresh_from_db()
        on = CapitalAllowanceService.compute_assessable_profit(self.org, Decimal("1000000"), 2026)
        self.assertTrue(on["ca_enabled"])
        self.assertGreater(float(on["capital_allowances"]), 0.0)

        # Final invariant: after the whole journey the books still balance and the
        # register still ties to the ledger.
        self.assertTrue(self._bs_balanced())
        self.assertTrue(self._recon()["reconciled"])
