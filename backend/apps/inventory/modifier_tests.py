"""
Product modifier tests.

The rule that matters: prices come from our catalogue, never from the caller.
A POS request is client-supplied input, so "extra chicken, +₦0" must be
impossible to send through.
"""

from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.inventory.models import Product, Warehouse
from apps.inventory.modifier_models import ModifierGroup, ModifierOption
from apps.inventory.modifier_services import ModifierError, ModifierService
from apps.pos.services import POSOrderService
from apps.subscriptions.models import Plan
from apps.subscriptions.services import SubscriptionService
from apps.tenancy.services import OrganisationService


def _user(email):
    return User.objects.create_user(
        email=email, password="TestPass123!", first_name="Mod", last_name="User",
        is_verified=True,
    )


class ModifierTestBase(TestCase):
    def setUp(self):
        self.user = _user("mods@example.com")
        self.org = OrganisationService.create_organisation(
            name="Mod Org", owner=self.user, extra={"currency": "NGN", "country": "NG"},
        )
        SubscriptionService.upgrade_plan(self.org, Plan.objects.get(slug="business"))
        self.org.refresh_from_db()
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}",
            HTTP_X_ORGANISATION_ID=str(self.org.id),
        )
        self.warehouse = Warehouse.objects.create(
            organisation=self.org, name="Main", is_default=True,
        )
        self.jollof = Product.objects.create(
            organisation=self.org, sku="JOL", name="Jollof Rice",
            cost_price=Decimal("800"), selling_price=Decimal("2500"),
            product_type=Product.ProductType.SERVICE,   # kitchen item, no stock
        )

        # "Size" — must pick exactly one.
        self.size = ModifierGroup.objects.create(
            organisation=self.org, name="Size", is_required=True,
            min_choices=1, max_choices=1,
        )
        self.size.products.add(self.jollof)
        self.regular = ModifierOption.objects.create(
            organisation=self.org, group=self.size, name="Regular",
            price_delta=Decimal("0"), is_default=True,
        )
        self.large = ModifierOption.objects.create(
            organisation=self.org, group=self.size, name="Large",
            price_delta=Decimal("500"),
        )

        # "Extras" — pick any, up to two.
        self.extras = ModifierGroup.objects.create(
            organisation=self.org, name="Extras", min_choices=0, max_choices=2,
        )
        self.extras.products.add(self.jollof)
        self.chicken = ModifierOption.objects.create(
            organisation=self.org, group=self.extras, name="Extra chicken",
            price_delta=Decimal("1200"),
        )
        self.plantain = ModifierOption.objects.create(
            organisation=self.org, group=self.extras, name="Plantain",
            price_delta=Decimal("700"),
        )
        self.egg = ModifierOption.objects.create(
            organisation=self.org, group=self.extras, name="Egg",
            price_delta=Decimal("400"),
        )


class PricingTests(ModifierTestBase):
    def test_the_delta_is_added_to_the_base_price(self):
        price, snapshot = ModifierService.unit_price(
            self.jollof, [self.large.id, self.chicken.id],
        )
        self.assertEqual(price, Decimal("4200"))       # 2500 + 500 + 1200
        self.assertEqual(len(snapshot), 2)

    def test_a_zero_delta_option_costs_nothing(self):
        price, _ = ModifierService.unit_price(self.jollof, [self.regular.id])
        self.assertEqual(price, Decimal("2500"))

    def test_the_snapshot_records_the_price_at_the_time_of_sale(self):
        """A later price change must not rewrite what a customer was charged."""
        _, snapshot = ModifierService.unit_price(self.jollof, [self.large.id])
        self.assertEqual(snapshot[0]["price_delta"], "500.00")

        self.large.price_delta = Decimal("900")
        self.large.save(update_fields=["price_delta"])
        self.assertEqual(snapshot[0]["price_delta"], "500.00")

    def test_options_are_grouped_in_display_order(self):
        _, snapshot = ModifierService.unit_price(
            self.jollof, [self.chicken.id, self.large.id],
        )
        self.assertEqual(snapshot[0]["group"], "Size")
        self.assertEqual(snapshot[1]["group"], "Extras")

    def test_the_description_reads_like_a_kitchen_ticket(self):
        _, snapshot = ModifierService.unit_price(
            self.jollof, [self.large.id, self.chicken.id],
        )
        self.assertEqual(ModifierService.describe(snapshot), "Large, Extra chicken")


class ValidationTests(ModifierTestBase):
    def test_a_required_group_must_be_answered(self):
        with self.assertRaises(ModifierError) as ctx:
            ModifierService.unit_price(self.jollof, [])
        self.assertIn("size", str(ctx.exception).lower())

    def test_picking_two_sizes_is_refused(self):
        with self.assertRaises(ModifierError) as ctx:
            ModifierService.unit_price(self.jollof, [self.regular.id, self.large.id])
        self.assertIn("no more than 1", str(ctx.exception))

    def test_exceeding_the_extras_limit_is_refused(self):
        with self.assertRaises(ModifierError):
            ModifierService.unit_price(self.jollof, [
                self.large.id, self.chicken.id, self.plantain.id, self.egg.id,
            ])

    def test_an_option_from_another_product_is_refused(self):
        other = Product.objects.create(
            organisation=self.org, sku="DRINK", name="Malt",
            cost_price=Decimal("200"), selling_price=Decimal("600"),
        )
        drink_group = ModifierGroup.objects.create(organisation=self.org, name="Chill")
        drink_group.products.add(other)
        chilled = ModifierOption.objects.create(
            organisation=self.org, group=drink_group, name="Chilled",
            price_delta=Decimal("100"),
        )
        with self.assertRaises(ModifierError) as ctx:
            ModifierService.unit_price(self.jollof, [self.large.id, chilled.id])
        self.assertIn("not an option", str(ctx.exception))

    def test_an_unknown_option_is_refused_rather_than_ignored(self):
        import uuid
        with self.assertRaises(ModifierError):
            ModifierService.unit_price(self.jollof, [self.large.id, str(uuid.uuid4())])

    def test_a_deactivated_option_can_no_longer_be_chosen(self):
        self.chicken.is_active = False
        self.chicken.save(update_fields=["is_active"])
        with self.assertRaises(ModifierError):
            ModifierService.unit_price(self.jollof, [self.large.id, self.chicken.id])

    def test_another_organisations_option_is_refused(self):
        other_user = _user("rival-mods@example.com")
        other_org = OrganisationService.create_organisation(
            name="Rival", owner=other_user, extra={"currency": "NGN", "country": "NG"},
        )
        their_group = ModifierGroup.objects.create(organisation=other_org, name="Theirs")
        their_option = ModifierOption.objects.create(
            organisation=other_org, group=their_group, name="Free upgrade",
            price_delta=Decimal("-2000"),
        )
        with self.assertRaises(ModifierError):
            ModifierService.unit_price(self.jollof, [self.large.id, their_option.id])


class OrderLineTests(ModifierTestBase):
    """Modifiers must reach the order at the price we computed."""

    def _order(self, option_ids, quantity="1"):
        return POSOrderService.create_order(
            organisation=self.org, created_by=self.user, order_type="dine_in",
            items=[{
                "product_id": str(self.jollof.id),
                "quantity": quantity,
                "modifiers": [str(o) for o in option_ids],
            }],
        )

    def test_the_line_is_priced_with_its_modifiers(self):
        order = self._order([self.large.id, self.chicken.id])
        line = order.items.first()
        self.assertEqual(line.unit_price, Decimal("4200"))

    def test_the_chosen_options_are_stored_on_the_line(self):
        order = self._order([self.large.id, self.chicken.id])
        names = [m["name"] for m in order.items.first().modifiers]
        self.assertEqual(names, ["Large", "Extra chicken"])

    def test_a_price_sent_by_the_client_cannot_make_extras_free(self):
        """The whole point — a POS request is untrusted input."""
        order = POSOrderService.create_order(
            organisation=self.org, created_by=self.user, order_type="dine_in",
            items=[{
                "product_id": str(self.jollof.id), "quantity": "1",
                "unit_price": "2500",
                "modifiers": [str(self.large.id), str(self.chicken.id)],
            }],
        )
        # The supplied base is honoured, but the deltas are still ours.
        self.assertEqual(order.items.first().unit_price, Decimal("4200"))

    def test_quantity_multiplies_the_modified_price(self):
        order = self._order([self.large.id], quantity="3")
        line = order.items.first()
        self.assertEqual(line.unit_price, Decimal("3000"))
        self.assertEqual(line.quantity, Decimal("3"))

    def test_an_order_without_a_required_choice_is_refused(self):
        with self.assertRaises(ModifierError):
            self._order([])

    def test_a_product_with_no_groups_is_unaffected(self):
        plain = Product.objects.create(
            organisation=self.org, sku="WATER", name="Water",
            cost_price=Decimal("100"), selling_price=Decimal("300"),
            product_type=Product.ProductType.SERVICE,
        )
        order = POSOrderService.create_order(
            organisation=self.org, created_by=self.user, order_type="dine_in",
            items=[{"product_id": str(plain.id), "quantity": "1"}],
        )
        line = order.items.first()
        self.assertEqual(line.unit_price, Decimal("300"))
        self.assertEqual(line.modifiers, [])


class ModifierApiTests(ModifierTestBase):
    def test_groups_can_be_listed(self):
        res = self.client.get("/api/v1/inventory/modifier-groups/")
        self.assertEqual(res.status_code, 200)
        names = [g["name"] for g in (res.data.get("results") or res.data)]
        self.assertIn("Size", names)
        self.assertIn("Extras", names)

    def test_the_till_can_ask_what_to_show_for_a_product(self):
        res = self.client.get(
            f"/api/v1/inventory/modifier-groups/for_product/?product={self.jollof.id}"
        )
        self.assertEqual(res.status_code, 200)
        groups = res.data["results"]
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["name"], "Size")
        self.assertTrue(groups[0]["is_required"])
        self.assertEqual(len(groups[0]["options"]), 2)

    def test_a_product_with_no_modifiers_returns_nothing_to_ask(self):
        plain = Product.objects.create(
            organisation=self.org, sku="P2", name="Plain",
            cost_price=Decimal("1"), selling_price=Decimal("2"),
        )
        res = self.client.get(
            f"/api/v1/inventory/modifier-groups/for_product/?product={plain.id}"
        )
        self.assertEqual(res.data["results"], [])

    def test_a_group_can_be_created(self):
        res = self.client.post("/api/v1/inventory/modifier-groups/", {
            "name": "Spice level", "is_required": True,
            "min_choices": 1, "max_choices": 1,
        }, format="json")
        self.assertEqual(res.status_code, 201, msg=str(res.data))

    def test_a_minimum_above_the_maximum_is_refused(self):
        res = self.client.post("/api/v1/inventory/modifier-groups/", {
            "name": "Broken", "min_choices": 3, "max_choices": 1,
        }, format="json")
        self.assertEqual(res.status_code, 400)

    def test_another_organisation_sees_no_groups(self):
        other_user = _user("outsider-mods@example.com")
        other_org = OrganisationService.create_organisation(
            name="Outsider", owner=other_user, extra={"currency": "NGN", "country": "NG"},
        )
        outsider = APIClient()
        outsider.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(other_user).access_token}",
            HTTP_X_ORGANISATION_ID=str(other_org.id),
        )
        res = outsider.get("/api/v1/inventory/modifier-groups/")
        self.assertEqual(res.data["count"], 0)
