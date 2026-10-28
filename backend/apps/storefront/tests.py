"""
Storefront tests.

This is the only unauthenticated surface in Audity, so most of these are about
what must NOT happen: no cost prices, no stock quantities, no other tenant's
data, no client-supplied prices, and no way to enumerate merchants.
"""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.inventory.models import Product, StockItem, Warehouse
from apps.inventory.services import InventoryService
from apps.pos.models import RestaurantTable
from apps.sales.models import Invoice
from apps.storefront.models import Storefront, StorefrontOrder
from apps.storefront.services import StorefrontError, StorefrontService
from apps.subscriptions.models import Plan
from apps.subscriptions.services import SubscriptionService
from apps.tenancy.services import OrganisationService


def _user(email):
    return User.objects.create_user(
        email=email, password="TestPass123!", first_name="Shop", last_name="Owner",
        is_verified=True,
    )


class StorefrontTestBase(TestCase):
    def setUp(self):
        self.user = _user("shop@example.com")
        self.org = OrganisationService.create_organisation(
            name="Kate's Stores", owner=self.user, extra={"currency": "NGN", "country": "NG"},
        )
        SubscriptionService.upgrade_plan(self.org, Plan.objects.get(slug="business"))
        self.org.refresh_from_db()

        self.client = APIClient()          # authenticated merchant
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}",
            HTTP_X_ORGANISATION_ID=str(self.org.id),
        )
        self.public = APIClient()          # the open internet — no credentials

        self.warehouse = Warehouse.objects.create(
            organisation=self.org, name="Main", is_default=True,
        )
        self.shop = Storefront.objects.create(
            organisation=self.org, slug="kates-stores", is_published=True,
            headline="Provisions in Ikeja",
        )
        self.rice = self._product("RICE", "Rice 5kg", cost="6000", price="9200", stock=20)

    def _product(self, sku, name, cost, price, stock=0, published=True):
        product = Product.objects.create(
            organisation=self.org, sku=sku, name=name,
            cost_price=Decimal(cost), selling_price=Decimal(price),
            is_published=published,
        )
        if stock:
            InventoryService.record_movement(
                organisation=self.org, product=product, warehouse=self.warehouse,
                quantity=Decimal(stock), movement_type="opening",
                unit_cost=Decimal(cost), reference="seed", created_by=self.user,
            )
        return product

    def _order_payload(self, **overrides):
        payload = {
            "customer_name": "Ada Buyer",
            "customer_phone": "08030000000",
            "fulfilment": "pickup",
            "items": [{"product": str(self.rice.id), "quantity": "2"}],
        }
        payload.update(overrides)
        return payload

    def _place(self, **overrides):
        return self.public.post(
            f"/api/v1/shop/{self.shop.slug}/orders/",
            self._order_payload(**overrides), format="json",
        )


class PublicAccessTests(StorefrontTestBase):
    def test_a_customer_needs_no_login(self):
        res = self.public.get(f"/api/v1/shop/{self.shop.slug}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["name"], "Kate's Stores")

    def test_an_unpublished_shop_is_invisible(self):
        self.shop.is_published = False
        self.shop.save(update_fields=["is_published"])
        self.assertEqual(self.public.get(f"/api/v1/shop/{self.shop.slug}/").status_code, 404)

    def test_unknown_and_unpublished_are_indistinguishable(self):
        """Otherwise the difference lets anyone enumerate which merchants exist."""
        self.shop.is_published = False
        self.shop.save(update_fields=["is_published"])
        hidden = self.public.get(f"/api/v1/shop/{self.shop.slug}/")
        missing = self.public.get("/api/v1/shop/no-such-shop/")
        self.assertEqual(hidden.status_code, missing.status_code)
        self.assertEqual(str(hidden.data), str(missing.data))


class CatalogueLeakageTests(StorefrontTestBase):
    """The public catalogue must never expose commercially sensitive data."""

    def test_cost_price_is_never_returned(self):
        res = self.public.get(f"/api/v1/shop/{self.shop.slug}/products/")
        body = str(res.data)
        self.assertNotIn("cost_price", body)
        self.assertNotIn("6000", body)
        self.assertNotIn("owner_cost", body)

    def test_stock_quantity_is_a_flag_not_a_number(self):
        res = self.public.get(f"/api/v1/shop/{self.shop.slug}/products/")
        item = res.data["results"][0]
        self.assertIn("in_stock", item)
        self.assertIs(item["in_stock"], True)
        self.assertNotIn("total_stock", item)
        self.assertNotIn("quantity_on_hand", str(res.data))

    def test_only_published_products_appear(self):
        self._product("SECRET", "Trade Only Item", cost="10", price="20", stock=5, published=False)
        res = self.public.get(f"/api/v1/shop/{self.shop.slug}/products/")
        names = [p["name"] for p in res.data["results"]]
        self.assertIn("Rice 5kg", names)
        self.assertNotIn("Trade Only Item", names)

    def test_inactive_products_are_hidden(self):
        self.rice.is_active = False
        self.rice.save(update_fields=["is_active"])
        res = self.public.get(f"/api/v1/shop/{self.shop.slug}/products/")
        self.assertEqual(len(res.data["results"]), 0)

    def test_out_of_stock_items_are_hidden_when_the_merchant_asks(self):
        empty = self._product("EMPTY", "Sold Out", cost="10", price="20", stock=0)
        res = self.public.get(f"/api/v1/shop/{self.shop.slug}/products/")
        self.assertNotIn("Sold Out", [p["name"] for p in res.data["results"]])

        self.shop.hide_out_of_stock = False
        self.shop.save(update_fields=["hide_out_of_stock"])
        res = self.public.get(f"/api/v1/shop/{self.shop.slug}/products/")
        row = next(p for p in res.data["results"] if p["name"] == "Sold Out")
        self.assertIs(row["in_stock"], False)
        self.assertEqual(empty.name, "Sold Out")

    def test_another_merchants_catalogue_is_never_returned(self):
        other_user = _user("rival@example.com")
        other_org = OrganisationService.create_organisation(
            name="Rival Shop", owner=other_user, extra={"currency": "NGN", "country": "NG"},
        )
        Product.objects.create(
            organisation=other_org, sku="RIVAL", name="Rival Secret Product",
            cost_price=Decimal("1"), selling_price=Decimal("2"), is_published=True,
        )
        res = self.public.get(f"/api/v1/shop/{self.shop.slug}/products/")
        self.assertNotIn("Rival Secret Product", str(res.data))


class PlaceOrderTests(StorefrontTestBase):
    def test_an_order_can_be_placed_without_logging_in(self):
        res = self._place()
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(res.data["status"], "placed")
        self.assertTrue(res.data["reference"])

    def test_the_total_is_computed_from_our_prices(self):
        res = self._place()
        self.assertEqual(Decimal(str(res.data["total"])), Decimal("18400"))  # 2 × 9,200

    def test_a_price_sent_by_the_customer_is_ignored(self):
        """The whole point: anyone can post JSON, so prices must come from us."""
        res = self.public.post(
            f"/api/v1/shop/{self.shop.slug}/orders/",
            self._order_payload(items=[
                {"product": str(self.rice.id), "quantity": "2", "unit_price": "1"},
            ]),
            format="json",
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Decimal(str(res.data["total"])), Decimal("18400"))

    def test_an_unpublished_product_cannot_be_ordered(self):
        hidden = self._product("HID", "Hidden", cost="10", price="20", stock=5, published=False)
        res = self.public.post(
            f"/api/v1/shop/{self.shop.slug}/orders/",
            self._order_payload(items=[{"product": str(hidden.id), "quantity": "1"}]),
            format="json",
        )
        self.assertEqual(res.status_code, 422)

    def test_a_product_from_another_merchant_cannot_be_ordered(self):
        other_user = _user("rival2@example.com")
        other_org = OrganisationService.create_organisation(
            name="Rival 2", owner=other_user, extra={"currency": "NGN", "country": "NG"},
        )
        theirs = Product.objects.create(
            organisation=other_org, sku="X", name="Theirs",
            cost_price=Decimal("1"), selling_price=Decimal("2"), is_published=True,
        )
        res = self.public.post(
            f"/api/v1/shop/{self.shop.slug}/orders/",
            self._order_payload(items=[{"product": str(theirs.id), "quantity": "1"}]),
            format="json",
        )
        self.assertEqual(res.status_code, 422)

    def test_zero_and_negative_quantities_are_refused(self):
        for bad in ("0", "-3"):
            res = self.public.post(
                f"/api/v1/shop/{self.shop.slug}/orders/",
                self._order_payload(items=[{"product": str(self.rice.id), "quantity": bad}]),
                format="json",
            )
            self.assertEqual(res.status_code, 400, msg=f"quantity {bad}")

    def test_delivery_requires_an_address(self):
        res = self._place(fulfilment="delivery")
        self.assertEqual(res.status_code, 400)
        self.assertIn("delivery_address", str(res.data))

    def test_a_shop_can_stop_taking_orders(self):
        self.shop.accepts_orders = False
        self.shop.save(update_fields=["accepts_orders"])
        self.assertEqual(self._place().status_code, 422)

    def test_a_minimum_order_is_enforced(self):
        self.shop.minimum_order = Decimal("100000")
        self.shop.save(update_fields=["minimum_order"])
        res = self._place()
        self.assertEqual(res.status_code, 422)
        self.assertIn("Orders start at", str(res.data["error"]))

    def test_placing_an_order_does_not_create_a_sale_yet(self):
        """An abandoned order must never pollute the ledger."""
        self._place()
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 0)

    def test_the_reference_is_readable_over_the_phone(self):
        ref = self._place().data["reference"]
        self.assertEqual(len(ref), 8)
        for confusable in ("I", "O", "0", "1"):
            self.assertNotIn(confusable, ref)


class OrderTrackingTests(StorefrontTestBase):
    def test_a_customer_can_track_with_the_reference(self):
        ref = self._place().data["reference"]
        res = self.public.get(f"/api/v1/shop/{self.shop.slug}/orders/{ref}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["reference"], ref)
        self.assertEqual(res.data["items"][0]["product_name"], "Rice 5kg")

    def test_an_unknown_reference_is_not_found(self):
        res = self.public.get(f"/api/v1/shop/{self.shop.slug}/orders/ZZZZZZZZ/")
        self.assertEqual(res.status_code, 404)

    def test_an_order_cannot_be_read_through_another_shop(self):
        ref = self._place().data["reference"]
        other_user = _user("other-shop@example.com")
        other_org = OrganisationService.create_organisation(
            name="Other Shop", owner=other_user, extra={"currency": "NGN", "country": "NG"},
        )
        Storefront.objects.create(organisation=other_org, slug="other-shop", is_published=True)
        res = self.public.get(f"/api/v1/shop/other-shop/orders/{ref}/")
        self.assertEqual(res.status_code, 404)

    def test_tracking_reveals_nothing_sensitive(self):
        ref = self._place().data["reference"]
        body = str(self.public.get(f"/api/v1/shop/{self.shop.slug}/orders/{ref}/").data)
        self.assertNotIn("cost", body)
        self.assertNotIn("08030000000", body)   # not even the phone back


class AcceptOrderTests(StorefrontTestBase):
    def _order(self):
        ref = self._place().data["reference"]
        return StorefrontOrder.objects.get(reference=ref)

    def test_accepting_creates_a_real_invoice(self):
        order = self._order()
        res = self.client.post(f"/api/v1/storefront/orders/{order.id}/accept/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        order.refresh_from_db()
        self.assertIsNotNone(order.invoice)
        self.assertEqual(order.status, StorefrontOrder.Status.CONFIRMED)
        self.assertEqual(Decimal(str(order.invoice.total_amount)), Decimal("18400"))

    def test_the_invoice_is_unpaid_until_money_arrives(self):
        order = self._order()
        self.client.post(f"/api/v1/storefront/orders/{order.id}/accept/")
        order.refresh_from_db()
        self.assertEqual(Decimal(str(order.invoice.amount_paid)), Decimal("0"))

    def test_accepting_twice_does_not_create_two_sales(self):
        order = self._order()
        self.client.post(f"/api/v1/storefront/orders/{order.id}/accept/")
        second = self.client.post(f"/api/v1/storefront/orders/{order.id}/accept/")
        self.assertEqual(second.status_code, 422)
        self.assertEqual(Invoice.objects.filter(organisation=self.org).count(), 1)

    def test_a_repeat_buyer_is_one_customer_not_many(self):
        from apps.customers.models import Customer
        for _ in range(2):
            order = self._order()
            self.client.post(f"/api/v1/storefront/orders/{order.id}/accept/")
        self.assertEqual(
            Customer.objects.filter(organisation=self.org, phone="08030000000").count(), 1,
        )

    def _accept(self, **overrides):
        ref = self._place(**overrides).data["reference"]
        order = StorefrontOrder.objects.get(reference=ref)
        self.client.post(f"/api/v1/storefront/orders/{order.id}/accept/")
        order.refresh_from_db()
        return order

    def test_the_same_person_in_a_different_phone_format_is_still_one_customer(self):
        first = self._accept()
        second = self._accept(customer_phone="+234 803 000 0000", customer_name="ada  BUYER")
        self.assertEqual(first.invoice.customer_id, second.invoice.customer_id)

    def test_someone_else_using_a_customers_phone_is_not_booked_to_that_customer(self):
        """Phone-only matching put an anonymous buyer's order, as money owed,
        on an existing customer's account."""
        owner_of_number = self._accept()
        stranger = self._accept(customer_name="Someone Else")
        self.assertNotEqual(owner_of_number.invoice.customer_id, stranger.invoice.customer_id)
        self.assertIn("Ada Buyer", stranger.invoice.customer.notes)

    def test_another_merchant_cannot_see_or_accept_the_order(self):
        order = self._order()
        other_user = _user("nosy@example.com")
        other_org = OrganisationService.create_organisation(
            name="Nosy Ltd", owner=other_user, extra={"currency": "NGN", "country": "NG"},
        )
        nosy = APIClient()
        nosy.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(other_user).access_token}",
            HTTP_X_ORGANISATION_ID=str(other_org.id),
        )
        self.assertEqual(nosy.get("/api/v1/storefront/orders/").data["count"], 0)
        self.assertEqual(
            nosy.post(f"/api/v1/storefront/orders/{order.id}/accept/").status_code, 404,
        )


class TableQrOrderTests(StorefrontTestBase):
    """A guest scans the QR on their table and orders from their seat."""

    def setUp(self):
        super().setUp()
        self.table = RestaurantTable.objects.create(
            organisation=self.org, name="T4", capacity=4,
        )

    def test_a_table_order_is_marked_table_service(self):
        res = self._place(table_code="T4")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(res.data["fulfilment"], "table")

    def test_an_unknown_table_is_refused(self):
        res = self._place(table_code="T99")
        self.assertEqual(res.status_code, 422)

    def test_accepting_a_table_order_reaches_the_kitchen_not_an_invoice(self):
        ref = self._place(table_code="T4").data["reference"]
        order = StorefrontOrder.objects.get(reference=ref)
        self.client.post(f"/api/v1/storefront/orders/{order.id}/accept/")
        order.refresh_from_db()
        self.assertIsNotNone(order.pos_order)
        self.assertIsNone(order.invoice)
        self.assertEqual(order.pos_order.table_id, self.table.id)

    def test_a_table_from_another_restaurant_cannot_be_used(self):
        other_user = _user("other-rest@example.com")
        other_org = OrganisationService.create_organisation(
            name="Other Rest", owner=other_user, extra={"currency": "NGN", "country": "NG"},
        )
        RestaurantTable.objects.create(organisation=other_org, name="Z9")
        self.assertEqual(self._place(table_code="Z9").status_code, 422)


class MerchantSettingsTests(StorefrontTestBase):
    def test_mine_creates_a_storefront_on_first_visit(self):
        Storefront.objects.filter(organisation=self.org).delete()
        res = self.client.get("/api/v1/storefront/settings/mine/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["slug"])
        self.assertFalse(res.data["is_published"])   # off until the merchant says so

    def test_reserved_slugs_are_refused(self):
        res = self.client.patch(
            f"/api/v1/storefront/settings/{self.shop.id}/", {"slug": "admin"}, format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("reserved", str(res.data).lower())

    def test_a_slug_cannot_be_taken_twice(self):
        other_user = _user("dup@example.com")
        other_org = OrganisationService.create_organisation(
            name="Dup Ltd", owner=other_user, extra={"currency": "NGN", "country": "NG"},
        )
        dup = APIClient()
        dup.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(other_user).access_token}",
            HTTP_X_ORGANISATION_ID=str(other_org.id),
        )
        res = dup.post(
            "/api/v1/storefront/settings/", {"slug": "kates-stores"}, format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_a_merchant_can_publish_a_product_through_the_api(self):
        """Nothing could set is_published (it was not on ProductSerializer),
        so every shop stayed empty however the merchant configured it."""
        product = Product.objects.create(
            organisation=self.org, sku="PUB", name="To Publish",
            cost_price=Decimal("1"), selling_price=Decimal("2"),
        )
        res = self.client.patch(f"/api/v1/inventory/products/{product.id}/", {"is_published": True}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        product.refresh_from_db()
        self.assertTrue(product.is_published)

    def test_products_are_unpublished_by_default(self):
        """Enabling a shop must not dump the whole catalogue onto the internet."""
        product = Product.objects.create(
            organisation=self.org, sku="NEW", name="Just Added",
            cost_price=Decimal("1"), selling_price=Decimal("2"),
        )
        self.assertFalse(product.is_published)


class DeliveryChargeTests(StorefrontTestBase):
    """Scoped delivery pricing: a flat fee, optionally waived above a
    subtotal threshold. No per-km pricing — see apps/storefront/models.py.

    Every order here is 2 × Rice 5kg @ 9,200 = 18,400 subtotal, from
    StorefrontTestBase._order_payload.
    """

    def _deliver(self, **overrides):
        return self._place(fulfilment="delivery", delivery_address="12 Allen Ave, Ikeja", **overrides)

    def test_fields_unset_means_no_charge_at_all(self):
        """Old free-text-only behaviour: nothing added unless the merchant configures it."""
        self.assertIsNone(self.shop.free_delivery_threshold)
        self.assertEqual(self.shop.fixed_delivery_charge, 0)
        res = self._deliver()
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(Decimal(str(res.data["total"])), Decimal("18400"))
        self.assertEqual(Decimal(str(res.data["subtotal"])), Decimal("18400"))

    def test_no_threshold_set_charge_always_applies(self):
        self.shop.fixed_delivery_charge = Decimal("1500")
        self.shop.save(update_fields=["fixed_delivery_charge"])
        res = self._deliver()
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(Decimal(str(res.data["total"])), Decimal("19900"))  # 18400 + 1500
        self.assertEqual(Decimal(str(res.data["subtotal"])), Decimal("18400"))

    def test_threshold_unmet_charge_applies(self):
        self.shop.fixed_delivery_charge = Decimal("1500")
        self.shop.free_delivery_threshold = Decimal("20000")  # above our 18,400 subtotal
        self.shop.save(update_fields=["fixed_delivery_charge", "free_delivery_threshold"])
        res = self._deliver()
        self.assertEqual(Decimal(str(res.data["total"])), Decimal("19900"))

    def test_threshold_met_delivery_is_free(self):
        self.shop.fixed_delivery_charge = Decimal("1500")
        self.shop.free_delivery_threshold = Decimal("15000")  # below our 18,400 subtotal
        self.shop.save(update_fields=["fixed_delivery_charge", "free_delivery_threshold"])
        res = self._deliver()
        self.assertEqual(Decimal(str(res.data["total"])), Decimal("18400"))

    def test_threshold_met_exactly_is_free(self):
        """'At or above' — an order exactly at the threshold should not be charged."""
        self.shop.fixed_delivery_charge = Decimal("1500")
        self.shop.free_delivery_threshold = Decimal("18400")  # exactly our subtotal
        self.shop.save(update_fields=["fixed_delivery_charge", "free_delivery_threshold"])
        res = self._deliver()
        self.assertEqual(Decimal(str(res.data["total"])), Decimal("18400"))

    def test_the_invoice_carries_the_delivery_charge_the_customer_agreed_to(self):
        """Accepting a delivery order raised an invoice with no delivery on it."""
        self.shop.fixed_delivery_charge = Decimal("1500")
        self.shop.save(update_fields=["fixed_delivery_charge"])
        res = self._deliver()
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        order = StorefrontOrder.objects.get(reference=res.data["reference"])
        self.client.post(f"/api/v1/storefront/orders/{order.id}/accept/")
        order.refresh_from_db()
        self.assertEqual(order.invoice.shipping_amount, Decimal("1500"))

    def test_charge_never_applies_to_pickup(self):
        self.shop.fixed_delivery_charge = Decimal("1500")
        self.shop.save(update_fields=["fixed_delivery_charge"])
        res = self._place(fulfilment="pickup")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(Decimal(str(res.data["total"])), Decimal("18400"))

    def test_charge_never_applies_to_table_service(self):
        table = RestaurantTable.objects.create(organisation=self.org, name="T1")
        self.shop.fixed_delivery_charge = Decimal("1500")
        self.shop.save(update_fields=["fixed_delivery_charge"])
        res = self._place(table_code="T1")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(res.data["fulfilment"], "table")
        self.assertEqual(Decimal(str(res.data["total"])), Decimal("18400"))

    def test_new_fields_are_visible_on_the_public_page(self):
        self.shop.fixed_delivery_charge = Decimal("1500")
        self.shop.free_delivery_threshold = Decimal("20000")
        self.shop.save(update_fields=["fixed_delivery_charge", "free_delivery_threshold"])
        res = self.public.get(f"/api/v1/shop/{self.shop.slug}/")
        self.assertEqual(Decimal(str(res.data["fixed_delivery_charge"])), Decimal("1500"))
        self.assertEqual(Decimal(str(res.data["free_delivery_threshold"])), Decimal("20000"))

    def test_merchant_can_configure_delivery_pricing(self):
        res = self.client.patch(
            f"/api/v1/storefront/settings/{self.shop.id}/",
            {"fixed_delivery_charge": "2000", "free_delivery_threshold": "25000"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.shop.refresh_from_db()
        self.assertEqual(self.shop.fixed_delivery_charge, Decimal("2000"))
        self.assertEqual(self.shop.free_delivery_threshold, Decimal("25000"))


class VatInclusivePricingTests(StorefrontTestBase):
    """The shop shows the price the customer pays, VAT included, and the invoice
    raised from the order matches it to the kobo."""

    def setUp(self):
        super().setUp()
        from apps.tax.models import TaxClass
        self.vat = TaxClass.objects.create(organisation=self.org, name="VAT", rate=Decimal("7.5"))

    def _taxable(self, sku, price, tax_type="exclusive"):
        product = self._product(sku, sku, cost="100", price=price, stock=50)
        product.is_taxable = True
        product.tax_class = self.vat
        product.tax_type = tax_type
        product.save()
        return product

    def _order_for(self, product, qty, **overrides):
        res = self._place(items=[{"product": str(product.id), "quantity": str(qty)}], **overrides)
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        return StorefrontOrder.objects.get(reference=res.data["reference"])

    def test_catalogue_price_includes_vat(self):
        product = self._taxable("VATP", "1999")
        data = self.public.get(f"/api/v1/shop/{self.shop.slug}/products/").data
        rows = data["results"] if isinstance(data, dict) else data
        row = next(r for r in rows if r["id"] == str(product.id))
        self.assertEqual(Decimal(row["selling_price"]), Decimal("2148.93"))
        self.assertEqual(Decimal(row["vat_included"]), Decimal("149.93"))

    def test_order_total_is_what_the_customer_was_shown_and_the_invoice_matches(self):
        product = self._taxable("VATP", "1999")
        order = self._order_for(product, 3)
        self.assertEqual(order.total, Decimal("6446.78"))
        self.client.post(f"/api/v1/storefront/orders/{order.id}/accept/")
        order.refresh_from_db()
        self.assertEqual(Decimal(str(order.invoice.total_amount)), Decimal("6446.78"))

    def test_inclusive_product_is_not_taxed_twice(self):
        product = self._taxable("INCL", "1075", tax_type="inclusive")
        order = self._order_for(product, 2)
        self.assertEqual(order.total, Decimal("2150.00"))
        self.client.post(f"/api/v1/storefront/orders/{order.id}/accept/")
        order.refresh_from_db()
        self.assertEqual(Decimal(str(order.invoice.total_amount)), Decimal("2150.00"))

    def test_delivery_is_added_after_the_vat_inclusive_subtotal(self):
        product = self._taxable("VATP", "2790.70")   # 3,000.00 with VAT
        self.shop.fixed_delivery_charge = Decimal("500")
        self.shop.save(update_fields=["fixed_delivery_charge"])
        order = self._order_for(product, 1, fulfilment="delivery", delivery_address="12 Allen Ave")
        self.assertEqual(order.subtotal, Decimal("3000.00"))
        self.assertEqual(order.total, Decimal("3500.00"))
        self.client.post(f"/api/v1/storefront/orders/{order.id}/accept/")
        order.refresh_from_db()
        self.assertEqual(Decimal(str(order.invoice.total_amount)), Decimal("3500.00"))

    def test_free_delivery_threshold_is_judged_on_the_price_paid(self):
        product = self._taxable("VATP", "2790.70")   # 3,000.00 with VAT
        self.shop.fixed_delivery_charge = Decimal("500")
        self.shop.free_delivery_threshold = Decimal("3000")
        self.shop.save(update_fields=["fixed_delivery_charge", "free_delivery_threshold"])
        order = self._order_for(product, 1, fulfilment="delivery", delivery_address="12 Allen Ave")
        self.assertEqual(order.total, Decimal("3000.00"))

    def test_an_order_placed_before_this_change_is_invoiced_at_the_total_shown(self):
        """Old orders stored the pre-VAT price as what the customer saw, and the
        invoice then added VAT on top. They are now invoiced at what was shown."""
        product = self._taxable("OLDP", "1000")
        order = self._order_for(product, 1)
        order.items.update(
            unit_price=Decimal("1075.00"), line_total=Decimal("1075.00"),
            net_unit_price=Decimal("0"), tax_rate=None, vat_amount=Decimal("0"),
        )
        order.subtotal = order.total = Decimal("1075.00")
        order.save(update_fields=["subtotal", "total"])
        self.client.post(f"/api/v1/storefront/orders/{order.id}/accept/")
        order.refresh_from_db()
        self.assertEqual(Decimal(str(order.invoice.total_amount)), Decimal("1075.00"))
