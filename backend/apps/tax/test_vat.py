"""
Tests for the one VAT calculation (apps.tax.vat.compute_vat) and every place
that now reads it. Each test states its expected numbers.
"""
import itertools
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.bills.models import Bill
from apps.core.utils import round_money
from apps.customers.models import Customer
from apps.inventory.models import Product, Warehouse
from apps.sales.models import Invoice, SaleItem, SaleReturn, SaleReturnItem
from apps.suppliers.models import Supplier
from apps.tax.models import TaxClass, VATTransaction
from apps.tax.tests import _auth_client, _make_org, _make_user, _upgrade_to_business
from apps.tax.vat import compute_vat

D = Decimal
_seq = itertools.count(1)

OCT = (date(2025, 10, 1), date(2025, 10, 31))
NOV = (date(2025, 11, 1), date(2025, 11, 30))
OCT_NOV = (date(2025, 10, 1), date(2025, 11, 30))


class VatBase(TestCase):
    def setUp(self):
        self.user = _make_user(f"vat{next(_seq)}@example.com")
        self.org = _make_org(self.user, f"Vat Org {next(_seq)}")
        _upgrade_to_business(self.org)
        self.wh = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.std = TaxClass.objects.create(organisation=self.org, name="Std", rate=D("7.5"), treatment="standard")
        self.zero = TaxClass.objects.create(organisation=self.org, name="Zero", rate=D("0"), treatment="zero_rated")
        self.exempt = TaxClass.objects.create(organisation=self.org, name="Ex", rate=D("0"), treatment="exempt")
        self.p_std = self._product("P-STD", self.std)
        self.p_zero = self._product("P-ZERO", self.zero)
        self.cust = Customer.objects.create(organisation=self.org, name="Buyer", tin="12345678-0001")
        self.sup_ok = Supplier.objects.create(organisation=self.org, code="S1", name="Registered Ltd", tax_id="99887766-0001")
        self.sup_no_tin = Supplier.objects.create(organisation=self.org, code="S2", name="Small Trader", tax_id="")

    def _product(self, sku, tax_class, org=None):
        return Product.objects.create(
            organisation=org or self.org, sku=sku, name=sku, cost_price=D("1"),
            selling_price=D("1"), is_taxable=True, tax_class=tax_class,
        )

    def invoice(self, issue_date, lines, status="paid", amount_paid=None, org=None, user=None):
        """lines: list of (net_price, rate, product). Exclusive VAT, rounded per line half-up."""
        org = org or self.org
        inv_no = f"INV-T-{next(_seq)}"
        subtotal = tax = D("0")
        built = []
        for net, rate, product in lines:
            net, rate = D(str(net)), D(str(rate))
            line_tax = round_money(net * rate / D("100"))
            built.append((net, rate, line_tax, product))
            subtotal += net
            tax += line_tax
        inv = Invoice.objects.create(
            organisation=org, customer=self.cust if org == self.org else None, status=status,
            warehouse=self.wh if org == self.org else Warehouse.objects.create(organisation=org, name="WH2"),
            issue_date=issue_date, due_date=issue_date, invoice_number=inv_no,
            subtotal=subtotal, tax_amount=tax, total_amount=subtotal + tax,
            amount_paid=amount_paid if amount_paid is not None else subtotal + tax,
            created_by=user or self.user,
        )
        items = []
        for net, rate, line_tax, product in built:
            items.append(SaleItem.objects.create(
                organisation=org, invoice=inv, product=product, quantity=D("1"), unit_price=net,
                tax_rate=rate, tax_amount=line_tax, line_total=net + line_tax, cost_of_goods=D("0"),
            ))
        return inv, items

    def sale_return(self, invoice, item, return_date, vat, gross):
        r = SaleReturn.objects.create(
            organisation=self.org, invoice=invoice, return_number=f"RTN-T-{next(_seq)}",
            return_date=return_date, total_refund=gross, processed_by=self.user,
        )
        SaleReturnItem.objects.create(
            organisation=self.org, sale_return=r, original_item=item, product=item.product,
            quantity_returned=D("1"), unit_price=item.unit_price, refund_amount=gross, tax_refund=vat,
        )
        return r

    def bill(self, issue_date, vat, supplier=None, status="approved", treatment="standard", net="100000", org=None, **kw):
        org = org or self.org
        return Bill.objects.create(
            organisation=org, supplier=supplier or self.sup_ok, status=status, issue_date=issue_date,
            due_date=issue_date, subtotal=D(net), tax_amount=D(vat), total_amount=D(net) + D(vat),
            amount_due=D(net) + D(vat), vat_treatment=treatment, created_by=self.user, **kw,
        )

    def vat(self, period=OCT, org=None, **kw):
        return compute_vat(org or self.org, *period, **kw)


class MainScenarioTests(VatBase):
    def _scenario(self):
        a, items = self.invoice(date(2025, 10, 5), [("100000", "7.5", self.p_std)], status="paid")
        self.invoice(date(2025, 10, 9), [("50000", "7.5", self.p_std)], status="overdue")
        self.sale_return(a, items[0], date(2025, 10, 20), vat=D("750"), gross=D("10750"))

    def test_exempt_bill_is_not_recoverable(self):
        self._scenario()
        self.bill(date(2025, 10, 12), "1500", treatment="exempt", net="20000")
        v = self.vat()
        self.assertEqual(v["output_vat_on_sales"], D("11250.00"))   # 7,500 + 3,750
        self.assertEqual(v["output_vat_returns"], D("750.00"))
        self.assertEqual(v["output_vat"], D("10500.00"))
        self.assertEqual(v["input_vat_recoverable"], D("0"))
        self.assertEqual(v["input_vat_irrecoverable"], D("1500.00"))
        self.assertEqual(v["net_vat_payable"], D("10500.00"))
        exempt_line = [l for l in v["lines"] if l["kind"] == "bill"][0]
        self.assertFalse(exempt_line["is_claimable"])
        self.assertIn("Exempt", exempt_line["reason"])

    def test_standard_bill_with_registered_org_is_recoverable(self):
        self._scenario()
        self.bill(date(2025, 10, 12), "1500", treatment="exempt", net="20000")
        self.bill(date(2025, 10, 14), "1500", treatment="standard", net="20000")
        v = self.vat()
        self.assertEqual(v["input_vat_recoverable"], D("1500.00"))
        self.assertEqual(v["input_vat_irrecoverable"], D("1500.00"))
        self.assertEqual(v["net_vat_payable"], D("9000.00"))
        self.assertEqual(v["position"], "payable")

    def test_unregistered_org_recovers_nothing(self):
        self._scenario()
        self.bill(date(2025, 10, 14), "1500", net="20000")
        self.org.charges_vat = False
        self.org.save(update_fields=["charges_vat"])
        v = self.vat()
        self.assertFalse(v["vat_registered"])
        self.assertEqual(v["input_vat_recoverable"], D("0"))
        self.assertEqual(v["input_vat_irrecoverable"], D("1500.00"))
        self.assertEqual(v["net_vat_payable"], D("10500.00"))
        self.assertIn("not marked as registered", v["registration_note"])


class PeriodRuleTests(VatBase):
    def test_credit_note_in_later_period_is_not_floored(self):
        inv, items = self.invoice(date(2025, 10, 10), [("100000", "7.5", self.p_std)])
        self.sale_return(inv, items[0], date(2025, 11, 4), vat=D("750"), gross=D("10750"))
        self.assertEqual(self.vat(OCT)["output_vat"], D("7500.00"))
        nov = self.vat(NOV)
        self.assertEqual(nov["output_vat"], D("-750.00"))
        self.assertEqual(nov["net_vat_payable"], D("-750.00"))
        self.assertEqual(nov["position"], "refund_or_carry_forward")

    def test_fully_returned_invoice_counts_in_its_own_period(self):
        inv, items = self.invoice(date(2025, 10, 10), [("100000", "7.5", self.p_std)], status="returned")
        self.sale_return(inv, items[0], date(2025, 11, 2), vat=D("7500"), gross=D("107500"))
        self.assertEqual(self.vat(OCT)["output_vat"], D("7500.00"))
        self.assertEqual(self.vat(NOV)["output_vat"], D("-7500.00"))
        self.assertEqual(self.vat(OCT_NOV)["output_vat"], D("0.00"))

    def test_part_paid_invoice_is_output_vat_in_invoice_period(self):
        inv, _ = self.invoice(date(2025, 10, 10), [("100000", "7.5", self.p_std)],
                              status="partially_paid", amount_paid=D("40000"))
        self.assertEqual(inv.total_amount, D("107500.00"))
        self.assertEqual(self.vat(OCT)["output_vat"], D("7500.00"))
        self.assertEqual(self.vat(NOV)["output_vat"], D("0"))

    def test_draft_proforma_void_are_excluded(self):
        for st in ("draft", "proforma", "voided"):
            self.invoice(date(2025, 10, 10), [("100000", "7.5", self.p_std)], status=st)
        self.assertEqual(self.vat(OCT)["output_vat"], D("0"))


class ZeroRatedAndInputTests(VatBase):
    def test_zero_rated_export_with_input_vat_gives_refund_position(self):
        self.invoice(date(2025, 10, 10), [("1000000", "0", self.p_zero)])
        self.bill(date(2025, 10, 11), "75000", net="1000000")
        v = self.vat()
        self.assertEqual(v["output_vat"], D("0"))
        self.assertEqual(v["turnover"]["zero_rated"], D("1000000.00"))
        self.assertEqual(v["turnover"]["taxable_standard"], D("0"))
        self.assertEqual(v["input_vat_recoverable"], D("75000.00"))
        self.assertEqual(v["net_vat_payable"], D("-75000.00"))

    def test_exempt_sales_are_in_turnover_with_zero_tax(self):
        p_ex = self._product("P-EX", self.exempt)
        self.invoice(date(2025, 10, 10), [("40000", "0", p_ex)])
        v = self.vat()
        self.assertEqual(v["turnover"]["exempt"], D("40000.00"))
        self.assertEqual(v["output_vat"], D("0"))

    def test_bill_from_supplier_without_tin_and_no_vat(self):
        self.bill(date(2025, 10, 10), "0", supplier=self.sup_no_tin, net="50000")
        v = self.vat()
        self.assertEqual(v["input_vat_recoverable"], D("0"))
        self.assertEqual(v["input_vat_irrecoverable"], D("0"))

    def test_supplier_without_tin_who_adds_vat_is_irrecoverable(self):
        self.bill(date(2025, 10, 10), "3750", supplier=self.sup_no_tin, net="50000")
        v = self.vat()
        self.assertEqual(v["input_vat_recoverable"], D("0"))
        self.assertEqual(v["input_vat_irrecoverable"], D("3750.00"))
        self.assertEqual(v["net_vat_payable"], D("0"))
        line = [l for l in v["lines"] if l["kind"] == "bill"][0]
        self.assertIn("no TIN", line["reason"])

    def test_bill_status_rules(self):
        self.bill(date(2025, 10, 1), "100", status="draft")
        self.bill(date(2025, 10, 1), "200", status="voided")
        self.bill(date(2025, 10, 1), "400", status="received")               # not from a PO: out
        self.bill(date(2025, 10, 1), "800", status="overdue")
        self.bill(date(2025, 10, 1), "1600", status="partially_paid")
        self.assertEqual(self.vat()["input_vat_recoverable"], D("2400.00"))

    def _po(self):
        from apps.purchases.models import PurchaseOrder
        return PurchaseOrder.objects.create(
            organisation=self.org, supplier=self.sup_ok, warehouse=self.wh,
            po_number=f"PO-T-{next(_seq)}", order_date=date(2025, 10, 1), created_by=self.user,
        )

    def test_po_origin_received_bill_counts(self):
        self.bill(date(2025, 10, 3), "500", status="received", source_purchase_order=self._po())
        self.assertEqual(self.vat()["input_vat_recoverable"], D("500.00"))

    def test_purchase_return_reduces_input_vat_in_period_issued(self):
        from apps.purchases.models import PurchaseReturn
        self.bill(date(2025, 10, 3), "7500")
        PurchaseReturn.objects.create(
            organisation=self.org, purchase_order=self._po(), supplier=self.sup_ok, warehouse=self.wh,
            return_number=f"PRET-T-{next(_seq)}", return_date=date(2025, 11, 5),
            subtotal=D("10000"), tax_amount=D("750"), total_amount=D("10750"), created_by=self.user,
        )
        self.assertEqual(self.vat(OCT)["input_vat_recoverable"], D("7500.00"))
        self.assertEqual(self.vat(NOV)["input_vat_recoverable"], D("-750.00"))


class RoundingAndReconciliationTests(VatBase):
    def test_two_inclusive_lines_of_5_37(self):
        from apps.sales.services import SaleService
        incl = Product(tax_type=Product.TaxType.INCLUSIVE)
        tax_each, total_each = SaleService.apply_tax(incl, D("5.37"), D("7.5"))
        self.assertEqual(tax_each, D("0.37"))          # 5.37 * 7.5 / 107.5 = 0.3746 -> 0.37
        self.assertEqual(total_each, D("5.37"))
        inv = Invoice.objects.create(
            organisation=self.org, customer=self.cust, status="paid", warehouse=self.wh,
            issue_date=date(2025, 10, 3), invoice_number=f"INV-T-{next(_seq)}",
            subtotal=D("10.74"), tax_amount=D("0.74"), total_amount=D("10.74"), created_by=self.user,
        )
        for _ in range(2):
            SaleItem.objects.create(
                organisation=self.org, invoice=inv, product=self.p_std, quantity=D("1"),
                unit_price=D("5.37"), tax_rate=D("7.5"), tax_amount=tax_each, line_total=total_each,
                cost_of_goods=D("0"),
            )
        v = self.vat()
        self.assertEqual(v["output_vat"], D("0.74"))   # not 0.75 (rounding the 10.74 total once)
        self.assertEqual(v["invoice_vat_mismatches"], [])

    def test_header_vs_line_mismatch_is_flagged_not_changed(self):
        inv, _ = self.invoice(date(2025, 10, 3), [("100000", "7.5", self.p_std)])
        Invoice.objects.filter(id=inv.id).update(tax_amount=D("7499.00"))
        v = self.vat()
        self.assertEqual(v["output_vat"], D("7500.00"))      # lines win
        self.assertEqual(len(v["invoice_vat_mismatches"]), 1)
        self.assertEqual(v["invoice_vat_mismatches"][0]["difference"], D("1.00"))

    def test_line_rate_is_used_not_a_hard_coded_7_5(self):
        self.invoice(date(2025, 10, 3), [("100000", "5", self.p_std)])
        self.assertEqual(self.vat()["output_vat"], D("5000.00"))

    def test_ledger_reconciliation_block_and_previous_methods(self):
        self.invoice(date(2025, 10, 3), [("100000", "7.5", self.p_std)])
        v = self.vat()
        rec = v["reconciliation"]
        self.assertEqual(rec["gl_output_vat"], D("0"))
        self.assertEqual(rec["output_difference"], D("7500.00"))   # ledger empty in this fixture: reported
        prev = v["previous_methods"]
        self.assertEqual(prev["reports_summary"]["output_vat"], D("7500.00"))
        self.assertEqual(prev["tax_page"]["output_vat"], D("7500.00"))
        self.assertEqual(prev["new_minus_reports_summary_net"], D("0.00"))
        # periods that have not ended are not compared
        today = date.today()
        self.assertIsNone(compute_vat(self.org, today.replace(day=1), date(today.year + 1, 1, 1))["previous_methods"])

    def test_previous_methods_show_the_old_floor_and_returns_difference(self):
        inv, items = self.invoice(date(2025, 10, 10), [("100000", "7.5", self.p_std)])
        self.sale_return(inv, items[0], date(2025, 11, 4), vat=D("750"), gross=D("10750"))
        nov = self.vat(NOV)
        self.assertEqual(nov["previous_methods"]["tax_page"]["output_vat"], D("0"))      # old floor
        self.assertEqual(nov["previous_methods"]["reports_summary"]["output_vat"], D("0"))  # old: no returns
        self.assertEqual(nov["net_vat_payable"], D("-750.00"))


class ManualAdjustmentAndSnapshotTests(VatBase):
    def test_snapshot_rows_are_ignored_and_manual_rows_counted(self):
        inv, _ = self.invoice(date(2025, 10, 3), [("100000", "7.5", self.p_std)])
        # stale sync snapshot of the same invoice + an e-invoice auto row for it
        VATTransaction.objects.create(
            organisation=self.org, direction="output", period_start=OCT[0], period_end=OCT[1],
            net_amount=D("100000"), vat_amount=D("7500"), source_ref=inv.invoice_number)
        VATTransaction.objects.create(
            organisation=self.org, direction="output", period_start=OCT[0], period_end=OCT[1],
            net_amount=D("100000"), vat_amount=D("7500"), source_ref="IRN-XYZ", notes="E-Invoice IRN-XYZ")
        VATTransaction.objects.create(
            organisation=self.org, direction="input", period_start=OCT[0], period_end=OCT[1],
            net_amount=D("10000"), vat_amount=D("750"), source_ref="adj-1", notes="Opening credit")
        v = self.vat()
        self.assertEqual(v["output_vat"], D("7500.00"))          # not doubled
        self.assertEqual(v["superseded_snapshot_rows"], 2)
        self.assertEqual(v["input_vat_manual_adjustments"], D("750.00"))
        self.assertEqual(v["net_vat_payable"], D("6750.00"))
        self.assertEqual([l["kind"] for l in v["lines"] if l["kind"] == "manual"], ["manual"])


class TenantAndEntryPointTests(VatBase):
    def setUp(self):
        super().setUp()
        self.other_user = _make_user(f"other{next(_seq)}@example.com")
        self.other = _make_org(self.other_user, f"Other Org {next(_seq)}")
        _upgrade_to_business(self.other)
        p = self._product("P-OTHER", None, org=self.other)
        self.invoice(date(2025, 10, 5), [("999999", "7.5", p)], org=self.other, user=self.other_user)
        self.bill(date(2025, 10, 5), "5000", org=self.other,
                  supplier=Supplier.objects.create(organisation=self.other, code="X", name="X", tax_id="1"))

    def _own_data(self):
        a, items = self.invoice(date(2025, 10, 5), [("100000", "7.5", self.p_std)])
        self.invoice(date(2025, 10, 9), [("50000", "7.5", self.p_std)], status="overdue")
        self.sale_return(a, items[0], date(2025, 10, 20), vat=D("750"), gross=D("10750"))
        self.bill(date(2025, 10, 12), "1500", net="20000")

    def test_other_orgs_data_never_appears(self):
        self._own_data()
        v = self.vat()
        self.assertEqual(v["output_vat"], D("10500.00"))
        self.assertEqual(v["input_vat_recoverable"], D("1500.00"))
        self.assertTrue(all("999999" not in str(l["net_amount"]) for l in v["lines"]))
        theirs = self.vat(org=self.other)
        self.assertEqual(theirs["output_vat"], D("74999.93"))
        self.assertEqual(theirs["input_vat_recoverable"], D("5000.00"))
        # endpoint level: org A's client sees only org A
        client = _auth_client(self.user, self.org)
        res = client.get("/api/v1/tax/vat-transactions/", {"period_start": "2025-10-01", "period_end": "2025-10-31"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(sum(D(r["vat_amount"]) for r in res.data["results"] if r["direction"] == "output"), D("10500.00"))

    def test_every_entry_point_returns_the_same_net(self):
        self._own_data()
        expected = self.vat()["net_vat_payable"]
        self.assertEqual(expected, D("9000.00"))
        client = _auth_client(self.user, self.org)
        qs = {"period": "custom", "date_from": "2025-10-01", "date_to": "2025-10-31"}
        p = {"period_start": "2025-10-01", "period_end": "2025-10-31"}

        def money(x):
            return D(str(x))

        got = {}
        got["overview card /reports/vat-summary/"] = money(client.get("/api/v1/reports/vat-summary/", qs).data["net_vat_payable"])
        got["registry vat-return"] = money(client.get("/api/v1/reports/r/vat-return/", qs).data["data"]["net_vat_payable"])
        got["registry tax-summary"] = money(client.get("/api/v1/reports/r/tax-summary/", qs).data["data"]["vat"]["net_vat_payable"])
        got["registry gl-tax-summary (old key)"] = money(client.get("/api/v1/reports/r/gl-tax-summary/", qs).data["data"]["vat"]["net_vat_payable"])
        got["tax page vat_report"] = money(client.post("/api/v1/tax/configs/vat_report/", p, format="json").data["net_vat_payable"])
        got["VAT ITC worksheet"] = money(client.get("/api/v1/tax/vat-transactions/worksheet/", p).data["net_vat_payable"])
        got["VAT ITC sync_from_period"] = money(client.post("/api/v1/tax/vat-transactions/sync_from_period/", p, format="json").data["net_vat_payable"])
        got["compute_vat"] = expected
        for name, value in got.items():
            self.assertEqual(value, expected, name)

    def test_tax_page_report_keys_and_negative_not_floored(self):
        inv, items = self.invoice(date(2025, 10, 10), [("100000", "7.5", self.p_std)])
        self.sale_return(inv, items[0], date(2025, 11, 4), vat=D("750"), gross=D("10750"))
        client = _auth_client(self.user, self.org)
        r = client.post("/api/v1/tax/configs/vat_report/",
                        {"period_start": "2025-11-01", "period_end": "2025-11-30"}, format="json").data
        self.assertEqual(D(str(r["vat_output"])), D("-750.00"))
        self.assertEqual(D(str(r["vat_on_returns"])), D("750.00"))
        self.assertEqual(D(str(r["net_vat_payable"])), D("-750.00"))

    def test_itc_list_is_live_and_sync_stores_nothing(self):
        self._own_data()
        client = _auth_client(self.user, self.org)
        p = {"period_start": "2025-10-01", "period_end": "2025-10-31"}
        res = client.post("/api/v1/tax/vat-transactions/sync_from_period/", p, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["synced_output"], 0)
        self.assertEqual(VATTransaction.objects.filter(organisation=self.org).count(), 0)
        rows = client.get("/api/v1/tax/vat-transactions/", p).data["results"]
        kinds = sorted(r["kind"] for r in rows)
        self.assertEqual(kinds, ["bill", "sale", "sale", "sale_return"])
        sale = [r for r in rows if r["kind"] == "sale"][0]
        self.assertEqual(sale["counterparty_tin"], "12345678-0001")

    def test_pdf_is_titled_vat_worksheet_and_works(self):
        self._own_data()
        client = _auth_client(self.user, self.org)
        res = client.get("/api/v1/tax/vat-transactions/export_pdf/",
                         {"period_start": "2025-10-01", "period_end": "2025-10-31"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.content.startswith(b"%PDF"))
        self.assertIn("VAT_Worksheet_", res["Content-Disposition"])
        self.assertNotIn("VAT_Return", res["Content-Disposition"])

    def test_tax_endpoints_keep_their_role_gate(self):
        from apps.authentication.models import User
        from apps.tenancy.models import Membership
        staff = User.objects.create_user(email=f"staff{next(_seq)}@example.com", password="TestPass123!",
                                         first_name="S", last_name="T", is_verified=True)
        Membership.objects.create(user=staff, organisation=self.org, role="staff", is_active=True)
        client = _auth_client(staff, self.org)
        p = {"period_start": "2025-10-01", "period_end": "2025-10-31"}
        self.assertEqual(client.get("/api/v1/tax/vat-transactions/worksheet/", p).status_code, 403)
        self.assertEqual(client.get("/api/v1/tax/vat-transactions/", p).status_code, 403)
        self.assertEqual(client.post("/api/v1/tax/configs/vat_report/", p, format="json").status_code, 403)
        self.assertEqual(client.get("/api/v1/tax/vat-transactions/export_pdf/", p).status_code, 403)
