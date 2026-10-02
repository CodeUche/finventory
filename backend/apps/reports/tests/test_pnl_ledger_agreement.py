"""
The Profit & Loss report must agree with the ledger.

It used to sum invoice.total_amount, so output VAT — owed to the tax
authority — was reported as revenue, and sales returns were deducted from
neither revenue nor COGS. On staging that overstated revenue by the VAT plus
the returned sales, and COGS by the returned cost; the dashboard, the Reports
page, its exports and the financial report pack all showed those figures.
"""

from decimal import Decimal

from django.test import TestCase

from apps.accounting.models import Account, JournalLine
from apps.accounting.tests import _auth_client, _make_org, _make_user, _upgrade_to_business


class ProfitAndLossAgreesWithLedgerTests(TestCase):
    def setUp(self):
        from apps.customers.models import Customer
        from apps.inventory.models import Product, Warehouse
        from apps.inventory.services import InventoryService
        from apps.tax.models import TaxClass

        self.user = _make_user("pnl_ledger@example.com")
        self.org = _make_org(self.user, "PnL Ledger Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

        vat = TaxClass.objects.create(organisation=self.org, name="VAT 7.5", rate=Decimal("7.50"))
        self.wh = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.product = Product.objects.create(
            organisation=self.org, sku="PNL1", name="Widget",
            cost_price=Decimal("1000"), selling_price=Decimal("1500"),
            is_taxable=True, tax_class=vat,
        )
        InventoryService.record_movement(
            organisation=self.org, product=self.product, warehouse=self.wh,
            quantity=Decimal("10"), movement_type="purchase_in",
            unit_cost=Decimal("1000"), reference="SEED", created_by=self.user,
        )
        self.customer = Customer.objects.create(organisation=self.org, name="Buyer", customer_type="retail")

    def _ledger(self, code):
        acct = Account.objects.get(organisation=self.org, code=code)
        lines = JournalLine.objects.filter(account=acct, journal_entry__organisation=self.org)
        dr = sum((l.debit for l in lines), Decimal("0"))
        cr = sum((l.credit for l in lines), Decimal("0"))
        return cr - dr if code.startswith("4") else dr - cr

    def test_revenue_excludes_vat_and_both_sides_net_of_returns(self):
        from apps.sales.services import SaleService

        # 3 x 1,500 less 10% = 4,050 net; VAT 303.75; cost 3,000.
        invoice = SaleService.create_sale(
            organisation=self.org, created_by=self.user, customer=self.customer, warehouse=self.wh,
            items=[{"product_id": str(self.product.id), "quantity": 3, "discount_percent": "10"}],
            payment_method="credit",
        )
        # One unit back into stock: revenue 1,350, VAT 101.25, cost 1,000 reverse.
        SaleService.process_return(
            organisation=self.org, invoice=invoice,
            items=[{"sale_item_id": str(invoice.items.first().id), "quantity_returned": "1"}],
            reason="defective", notes="", processed_by=self.user, restocked=True,
        )

        res = self.client.get("/api/v1/reports/pnl/", {"period": "year"})
        self.assertEqual(res.status_code, 200, res.content[:300])
        pnl = res.json()
        rev = pnl["revenue"]

        self.assertEqual(Decimal(str(rev["sales_excl_vat"])), Decimal("4050.00"))
        self.assertEqual(Decimal(str(rev["returns"])), Decimal("1350.00"))
        self.assertEqual(Decimal(str(rev["gross_sales"])), Decimal("2700.00"))
        self.assertEqual(Decimal(str(pnl["cost_of_goods_sold"])), Decimal("2000.00"))
        self.assertEqual(Decimal(str(pnl["gross_profit"])), Decimal("700.00"))

        # And the same figures the ledger holds.
        self.assertEqual(Decimal(str(rev["gross_sales"])), self._ledger("4001"))
        self.assertEqual(Decimal(str(pnl["cost_of_goods_sold"])), self._ledger("5001"))

    def test_product_reports_exclude_vat_from_revenue_and_margin(self):
        """Top Products / Sales by Product summed line_total, which carries VAT,
        so each product's revenue and gross profit were overstated by its VAT."""
        from apps.reports.services import ReportService
        from apps.sales.services import SaleService

        SaleService.create_sale(
            organisation=self.org, created_by=self.user, customer=self.customer, warehouse=self.wh,
            items=[{"product_id": str(self.product.id), "quantity": 3, "discount_percent": "10"}],
            payment_method="credit",
        )
        for rows in (
            ReportService.sales_by_product(self.org, None, None),
            ReportService.top_products(self.org, None, None),
        ):
            row = rows[0]
            self.assertEqual(Decimal(str(row["revenue"])), Decimal("4050.00"))
            self.assertEqual(Decimal(str(row["gross_profit"])), Decimal("1050.00"))
