"""Round 2 of the VAT calculation: supplier flag, needs-attention, purchase returns that
follow the original bill, buckets, memo lines, apportionment, duplicates, comparison."""
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.suppliers.models import Supplier
from apps.tax.models import VATTransaction
from apps.tax.tests import _auth_client
from apps.tax.test_vat import D, OCT, NOV, _seq, VatBase
from apps.tax.vat import compute_vat, comparison_table


class SupplierFlagTests(VatBase):
    def _sup(self, flag, tin):
        return Supplier.objects.create(organisation=self.org, code=f"F{next(_seq)}", name=f"S-{flag}-{bool(tin)}",
                                       vat_registered=flag, tax_id=tin)

    def test_four_combinations(self):
        cases = [("yes", "", True, "confirmed"), ("no", "123", False, "confirmed"),
                 ("unknown", "123", True, "unconfirmed"), ("unknown", "", False, "unconfirmed")]
        for flag, tin, ok, conf in cases:
            Supplier_bill = self.bill(date(2025, 10, 5), "1000", supplier=self._sup(flag, tin))
            line = [l for l in self.vat()["lines"] if l["document_id"] == str(Supplier_bill.id)][0]
            self.assertEqual(line["is_claimable"], ok, (flag, tin))
            self.assertEqual(line["confirmation"], conf, (flag, tin))
            Supplier_bill.delete()

    def test_default_is_unknown_and_not_backfilled(self):
        self.assertEqual(self.sup_ok.vat_registered, "unknown")
        self.assertEqual(Supplier.objects.filter(organisation=self.org).exclude(vat_registered="unknown").count(), 0)


class NeedsAttentionTests(VatBase):
    def test_rows_count_and_quick_action(self):
        self.bill(date(2025, 10, 5), "1000", supplier=self.sup_ok)         # unknown + TIN
        self.bill(date(2025, 10, 6), "2000", supplier=self.sup_no_tin)     # unknown + no TIN
        yes = Supplier.objects.create(organisation=self.org, code="Y", name="Yes Ltd", vat_registered="yes", tax_id="1")
        self.bill(date(2025, 10, 7), "3000", supplier=yes)                 # fine
        no = Supplier.objects.create(organisation=self.org, code="N", name="No Ltd", vat_registered="no")
        self.bill(date(2025, 10, 8), "4000", supplier=no)                  # decided: not listed
        v = self.vat()
        self.assertEqual(v["needs_attention_count"], 2)
        self.assertEqual({a["supplier_name"] for a in v["needs_attention"]}, {self.sup_ok.name, self.sup_no_tin.name})
        client = _auth_client(self.user, self.org)
        p = {"period_start": "2025-10-01", "period_end": "2025-10-31"}
        self.assertEqual(client.get("/api/v1/tax/vat-transactions/worksheet/", p).data["needs_attention_count"], 2)
        r = client.post("/api/v1/tax/vat-transactions/set_supplier_vat/",
                        {"supplier_id": str(self.sup_ok.id), "vat_registered": "yes"}, format="json")
        self.assertEqual(r.status_code, 200)
        r = client.post("/api/v1/tax/vat-transactions/set_supplier_vat/",
                        {"supplier_id": str(self.sup_no_tin.id), "vat_registered": "yes", "tax_id": "777"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.vat()["needs_attention_count"], 0)
        self.assertEqual(self.vat()["input_vat_recoverable"], D("6000.00"))   # 1000 + 2000 + 3000

    def test_quick_action_is_tenant_scoped_and_role_gated(self):
        from apps.tax.tests import _make_org, _make_user, _upgrade_to_business
        other_user = _make_user(f"o{next(_seq)}@example.com")
        other = _make_org(other_user, f"Other {next(_seq)}")
        _upgrade_to_business(other)
        theirs = Supplier.objects.create(organisation=other, code="T", name="Theirs")
        client = _auth_client(self.user, self.org)
        r = client.post("/api/v1/tax/vat-transactions/set_supplier_vat/",
                        {"supplier_id": str(theirs.id), "vat_registered": "yes"}, format="json")
        self.assertEqual(r.status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.vat_registered, "unknown")
        from apps.authentication.models import User
        from apps.tenancy.models import Membership
        staff = User.objects.create_user(email=f"st{next(_seq)}@example.com", password="TestPass123!",
                                         first_name="S", last_name="T", is_verified=True)
        Membership.objects.create(user=staff, organisation=self.org, role="staff", is_active=True)
        r = _auth_client(staff, self.org).post("/api/v1/tax/vat-transactions/set_supplier_vat/",
                                               {"supplier_id": str(self.sup_ok.id), "vat_registered": "yes"}, format="json")
        self.assertEqual(r.status_code, 403)


class PurchaseReturnFollowsOriginalBillTests(VatBase):
    def _po(self, supplier=None):
        from apps.purchases.models import PurchaseOrder
        return PurchaseOrder.objects.create(
            organisation=self.org, supplier=supplier or self.sup_ok, warehouse=self.wh,
            po_number=f"PO-R-{next(_seq)}", order_date=date(2025, 10, 1), created_by=self.user)

    def _ret(self, po, vat="750", supplier=None, when=date(2025, 11, 5)):
        from apps.purchases.models import PurchaseReturn
        return PurchaseReturn.objects.create(
            organisation=self.org, purchase_order=po, supplier=supplier or self.sup_ok, warehouse=self.wh,
            return_number=f"PRET-R-{next(_seq)}", return_date=when, subtotal=D("10000"),
            tax_amount=D(vat), total_amount=D("10000") + D(vat), created_by=self.user)

    def _yes(self):
        return Supplier.objects.create(organisation=self.org, code=f"Y{next(_seq)}", name="Yes Ltd",
                                       vat_registered="yes", tax_id="1")

    def test_return_on_claimable_bill_reduces_input(self):
        sup = self._yes(); po = self._po(sup)
        self.bill(date(2025, 10, 3), "7500", supplier=sup, source_purchase_order=po)
        self._ret(po, supplier=sup)
        nov = self.vat(NOV)
        self.assertEqual(nov["input_vat_recoverable"], D("-750.00"))

    def test_return_on_exempt_bill_does_not_reduce_claimable(self):
        sup = self._yes(); po = self._po(sup)
        self.bill(date(2025, 10, 3), "7500", supplier=sup, treatment="exempt", source_purchase_order=po)
        self._ret(po, supplier=sup)
        nov = self.vat(NOV)
        self.assertEqual(nov["input_vat_recoverable"], D("0"))
        ret = [l for l in nov["lines"] if l["kind"] == "purchase_return"][0]
        self.assertFalse(ret["is_claimable"])
        self.assertIn("Exempt", ret["reason"])
        self.assertIn("Follows original bill", ret["reason"])

    def test_return_on_not_claimable_bill_does_not_reduce_claimable(self):
        sup = self._yes(); po = self._po(sup)
        self.bill(date(2025, 10, 3), "7500", supplier=sup, vat_not_claimable_reason="entertainment",
                  source_purchase_order=po)
        self._ret(po, supplier=sup)
        self.assertEqual(self.vat(NOV)["input_vat_recoverable"], D("0"))

    def test_return_against_unclaimed_received_bill_does_not_reduce(self):
        sup = self._yes(); po = self._po(sup)
        self.bill(date(2025, 10, 3), "7500", supplier=sup, status="received", source_purchase_order=po)
        self._ret(po, supplier=sup)
        self.assertEqual(self.vat(NOV)["input_vat_recoverable"], D("0"))

    def test_return_with_no_linked_bill_uses_supplier_status(self):
        yes = self._yes()
        self.assertEqual(self.vat_for_return(self._po(yes), yes), D("-750.00"))
        no = Supplier.objects.create(organisation=self.org, code="NN", name="No", vat_registered="no")
        self.assertEqual(self.vat_for_return(self._po(no), no), D("0"))

    def vat_for_return(self, po, sup):
        r = self._ret(po, supplier=sup)
        v = self.vat(NOV)
        r.delete()
        return v["input_vat_recoverable"]


class BucketsAndTurnoverTests(VatBase):
    def test_not_taxable_and_nil_vat_buckets_are_visible(self):
        from apps.inventory.models import Product
        p_nt = Product.objects.create(organisation=self.org, sku="NT", name="NT", cost_price=D("1"),
                                      selling_price=D("1"), is_taxable=False)
        p_nil = self._product("NIL", None)
        self.invoice(date(2025, 10, 3), [("10000", "0", p_nt), ("20000", "0", p_nil), ("100000", "7.5", self.p_std)])
        t = self.vat()["turnover"]
        self.assertEqual(t["not_taxable"], D("10000.00"))
        self.assertEqual(t["nil_vat_needs_class"], D("20000.00"))
        self.assertEqual(t["taxable_standard"], D("100000.00"))
        self.assertIn("please classify", self.vat()["turnover_labels"]["not_taxable"])
        self.assertEqual(self.vat()["turnover_labels"]["nil_vat_needs_class"], "Nil VAT, needs a VAT class")

    def test_turnover_is_net_of_returns_in_the_return_period(self):
        inv, items = self.invoice(date(2025, 10, 10), [("100000", "7.5", self.p_std)])
        self.sale_return(inv, items[0], date(2025, 11, 4), vat=D("750"), gross=D("10750"))
        self.assertEqual(self.vat(OCT)["turnover"]["taxable_standard"], D("100000.00"))
        self.assertEqual(self.vat(NOV)["turnover"]["taxable_standard"], D("-10000.00"))

    def test_zero_rated_return_reduces_zero_rated_turnover(self):
        inv, items = self.invoice(date(2025, 10, 10), [("500000", "0", self.p_zero)])
        self.sale_return(inv, items[0], date(2025, 11, 4), vat=D("0"), gross=D("50000"))
        self.assertEqual(self.vat(NOV)["turnover"]["zero_rated"], D("-50000.00"))


class MemoNotClaimableApportionTests(VatBase):
    def test_received_po_bill_is_memo_and_reconciliation_explains_ledger(self):
        from apps.purchases.models import PurchaseOrder
        po = PurchaseOrder.objects.create(organisation=self.org, supplier=self.sup_ok, warehouse=self.wh,
                                          po_number=f"PO-M-{next(_seq)}", order_date=date(2025, 10, 1),
                                          created_by=self.user)
        self.bill(date(2025, 10, 3), "500", status="received", source_purchase_order=po)
        self.bill(date(2025, 10, 4), "1000", status="approved")
        v = self.vat()
        self.assertEqual(v["input_vat_awaiting_supplier_invoice"], D("500.00"))
        self.assertIn("awaiting supplier invoice", v["input_vat_awaiting_supplier_invoice_label"])
        rec = v["reconciliation"]
        self.assertEqual(rec["input_vat_booked_by_documents"], D("1500.00"))   # 1000 approved + 500 received
        self.assertEqual(rec["input_split"]["goods_received_awaiting_supplier_invoice"], D("500.00"))
        self.assertIn("goods received", rec["note"])
        memo = [l for l in v["lines"] if l["kind"] == "bill_awaiting_invoice"][0]
        self.assertFalse(memo["is_claimable"])

    def test_not_claimable_reason_excludes_and_shows_reason(self):
        sup = Supplier.objects.create(organisation=self.org, code="Z", name="Z", vat_registered="yes", tax_id="1")
        self.bill(date(2025, 10, 4), "1000", supplier=sup, vat_not_claimable_reason="motor_vehicle")
        self.bill(date(2025, 10, 5), "2000", supplier=sup)
        v = self.vat()
        self.assertEqual(v["input_vat_recoverable"], D("2000.00"))
        self.assertEqual(v["input_vat_irrecoverable"], D("1000.00"))
        line = [l for l in v["lines"] if l["kind"] == "bill" and not l["is_claimable"]][0]
        self.assertIn("Passenger motor vehicles", line["reason"])

    def test_apportionment_percentage(self):
        sup = Supplier.objects.create(organisation=self.org, code="Z", name="Z", vat_registered="yes", tax_id="1")
        self.bill(date(2025, 10, 4), "10000", supplier=sup)
        self.org.input_vat_share_percent = D("60")
        self.org.save(update_fields=["input_vat_share_percent"])
        v = self.vat()
        self.assertEqual(v["input_vat_recoverable"], D("6000.00"))
        self.assertEqual(v["input_vat_not_apportioned"], D("4000.00"))
        self.assertEqual(v["input_vat_irrecoverable"], D("4000.00"))
        self.assertTrue(any("60" in n for n in v["notes"]))

    def test_share_percent_is_validated_and_admin_only(self):
        client = _auth_client(self.user, self.org)
        url = f"/api/v1/tenancy/organisations/{self.org.id}/"
        self.assertEqual(client.patch(url, {"input_vat_share_percent": "150"}, format="json").status_code, 400)
        r = client.patch(url, {"input_vat_share_percent": "75"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.org.refresh_from_db()
        self.assertEqual(self.org.input_vat_share_percent, D("75"))


class NotesDuplicatesAndComparisonTests(VatBase):
    def test_texts_and_warnings(self):
        v = self.vat((date(2025, 12, 1), date(2025, 12, 31)))
        self.assertTrue(any("1 January 2026" in n for n in v["notes"]))           # period before 2026
        self.assertFalse(any("1 January 2026" in n for n in self.vat((date(2026, 1, 1), date(2026, 1, 31)))["notes"]))
        self.assertTrue(any("whole bill" in n for n in v["notes"]))
        self.assertIn("not tax advice", v["worksheet_note"])
        self.assertIn("21st of the following month", v["due_note"])
        inv, items = self.invoice(date(2025, 10, 10), [("100000", "7.5", self.p_std)])
        self.org.charges_vat = False
        self.org.save(update_fields=["charges_vat"])
        v = self.vat()
        self.assertEqual(len(v["warnings"]), 1)
        self.assertIn("marked as not registered", v["warnings"][0])
        self.assertIn("small businesses".lower(), v["registration_note"].lower())

    def test_negative_note(self):
        self.invoice(date(2025, 10, 10), [("1000", "7.5", self.p_std)])
        sup = Supplier.objects.create(organisation=self.org, code="Z", name="Z", vat_registered="yes", tax_id="1")
        self.bill(date(2025, 10, 11), "5000", supplier=sup)
        v = self.vat()
        self.assertLess(v["net_vat_payable"], 0)
        self.assertTrue(any("refund or a carry-forward" in n for n in v["notes"]))

    def test_ignored_duplicates_are_listed(self):
        inv, _ = self.invoice(date(2025, 10, 3), [("100000", "7.5", self.p_std)])
        VATTransaction.objects.create(organisation=self.org, direction="output", period_start=OCT[0],
                                      period_end=OCT[1], net_amount=D("1"), vat_amount=D("7500"),
                                      source_ref=inv.invoice_number)
        VATTransaction.objects.create(organisation=self.org, direction="output", period_start=OCT[0],
                                      period_end=OCT[1], net_amount=D("1"), vat_amount=D("5"),
                                      source_ref="IRN-1", notes="E-Invoice IRN-1")
        v = self.vat()
        self.assertEqual(v["superseded_snapshot_rows"], 2)
        self.assertEqual(len(v["ignored_duplicates"]), 2)
        self.assertTrue(all(r["reason"] for r in v["ignored_duplicates"]))
        client = _auth_client(self.user, self.org)
        ws = client.get("/api/v1/tax/vat-transactions/worksheet/", {"period_start": "2025-10-01", "period_end": "2025-10-31"}).data
        self.assertEqual(len(ws["ignored_duplicates"]), 2)

    def test_old_bill_snapshot_is_matched_in_sql_not_by_looping_every_bill(self):
        target = self.bill(date(2025, 10, 3), "1000")
        VATTransaction.objects.create(organisation=self.org, direction="input", period_start=OCT[0],
                                      period_end=OCT[1], net_amount=D("1"), vat_amount=D("1000"),
                                      source_ref=str(target.id)[:12])
        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                v = self.vat(with_reconciliation=False, with_previous_methods=False)
            return len(ctx), v
        few, v = count_queries()
        self.assertEqual(len(v["ignored_duplicates"]), 1)
        for _ in range(25):
            self.bill(date(2025, 10, 4), "10")
        many, v = count_queries()
        self.assertEqual(len(v["ignored_duplicates"]), 1)
        # Query count does not grow with the number of bills.
        self.assertEqual(many, few)

    def test_party_tin_fields_show_correctly(self):
        self.invoice(date(2025, 10, 3), [("1000", "7.5", self.p_std)])
        self.bill(date(2025, 10, 3), "100")
        lines = self.vat()["lines"]
        self.assertEqual([l["counterparty_tin"] for l in lines if l["kind"] == "sale"], ["12345678-0001"])
        self.assertEqual([l["counterparty_tin"] for l in lines if l["kind"] == "bill"], ["99887766-0001"])

    def test_comparison_table_closed_months_with_why_and_wording(self):
        inv, items = self.invoice(date(2025, 10, 10), [("100000", "7.5", self.p_std)], status="overdue")
        self.sale_return(inv, items[0], date(2025, 11, 4), vat=D("750"), gross=D("10750"))
        rows = comparison_table(self.org, today=date(2025, 12, 15), months=3)
        self.assertEqual([r["period_start"] for r in rows], [date(2025, 11, 1), date(2025, 10, 1), date(2025, 9, 1)])
        nov = rows[0]
        self.assertEqual(nov["now"], D("-750.00"))
        self.assertEqual(nov["reports_page_showed"], D("0"))
        self.assertEqual(nov["tax_page_showed"], D("0"))
        self.assertEqual(nov["difference_from_tax_page"], D("-750.00"))
        self.assertTrue(nov["different"])
        self.assertTrue(any("Credit notes" in w for w in nov["why"]))
        self.assertTrue(any("negative result" in w for w in nov["why"]))
        octr = rows[1]
        self.assertEqual(octr["reports_page_showed"], D("7500.00"))
        self.assertTrue(any("past due" in w for w in octr["why"]))
        self.assertFalse(rows[2]["different"])
        self.assertEqual(rows[2]["why"], [])
        # the endpoint is gated like the rest of the Tax page and tenant scoped
        client = _auth_client(self.user, self.org)
        res = client.get("/api/v1/tax/vat-transactions/comparison/")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.data["rows"], list)
