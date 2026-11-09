"""
Quotes must be priced exactly as the invoice they turn into.

Quotes took the VAT rate only from the request, which the Quotes screen never
sends, so a taxed product was quoted without VAT and invoiced with it: on
staging a quote of 3,000 converted into a 3,225 invoice.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from apps.accounting.tests import _auth_client, _make_org, _make_user, _upgrade_to_business
from apps.customers.models import Customer
from apps.inventory.models import Product, Warehouse
from apps.inventory.services import InventoryService
from apps.sales.models import Invoice
from apps.tax.models import TaxClass


class QuotePricingTests(TestCase):
    def setUp(self):
        self.user = _make_user("quotes@example.com")
        self.org = _make_org(self.user, "Quotes Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        self.wh = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)
        self.customer = Customer.objects.create(organisation=self.org, name="Buyer", customer_type="retail")
        vat = TaxClass.objects.create(organisation=self.org, name="VAT", rate=Decimal("7.5"))
        self.taxed = Product.objects.create(
            organisation=self.org, sku="Q1", name="Taxed", cost_price=Decimal("1000"),
            selling_price=Decimal("1500"), is_taxable=True, tax_class=vat,
        )
        self.inclusive = Product.objects.create(
            organisation=self.org, sku="Q2", name="Inclusive", cost_price=Decimal("500"),
            selling_price=Decimal("1075"), is_taxable=True, tax_class=vat, tax_type="inclusive",
        )
        for p in (self.taxed, self.inclusive):
            InventoryService.record_movement(
                organisation=self.org, product=p, warehouse=self.wh, quantity=Decimal("20"),
                movement_type="purchase_in", unit_cost=p.cost_price, reference="SEED", created_by=self.user,
            )

    def _quote(self, items):
        res = self.client.post("/api/v1/quotes/", {
            "customer": str(self.customer.id), "warehouse": str(self.wh.id),
            "issue_date": str(date.today()), "valid_until": str(date.today() + timedelta(days=30)),
            "items": items,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return res.data

    def _convert(self, quote_id):
        res = self.client.post(f"/api/v1/quotes/{quote_id}/convert/")
        self.assertEqual(res.status_code, 200, res.data)
        return Invoice.objects.get(id=res.data["invoice_id"])

    def test_a_taxed_product_is_quoted_with_its_vat_and_invoiced_the_same(self):
        q = self._quote([{"product": str(self.taxed.id), "quantity": 2}])  # what the screen sends
        self.assertEqual(Decimal(str(q["tax_amount"])), Decimal("225"))
        self.assertEqual(Decimal(str(q["total_amount"])), Decimal("3225"))
        self.assertEqual(self._convert(q["id"]).total_amount, Decimal(str(q["total_amount"])))

    def test_vat_inclusive_price_is_not_taxed_twice(self):
        q = self._quote([{"product": str(self.inclusive.id), "quantity": 1}])
        self.assertEqual(Decimal(str(q["total_amount"])), Decimal("1075"))
        self.assertEqual(Decimal(str(q["tax_amount"])), Decimal("75"))
        self.assertEqual(self._convert(q["id"]).total_amount, Decimal("1075"))

    def test_an_explicit_rate_including_zero_is_honoured_through_conversion(self):
        q = self._quote([{"product": str(self.taxed.id), "quantity": 2, "tax_rate": "0"}])
        self.assertEqual(Decimal(str(q["total_amount"])), Decimal("3000"))
        self.assertEqual(self._convert(q["id"]).total_amount, Decimal("3000"))
