"""
Product modifiers — the choices a customer makes when ordering.

"Jollof Rice — large, extra chicken, no pepper" is one sale line, not three
products. Modelling those as separate products would multiply a 40-item menu
into hundreds of SKUs and make stock and reporting meaningless.

So a modifier group hangs off a product (or is shared across many), each option
carries a price difference, and the chosen options ride along with the order
line. The base product keeps its own stock and cost.
"""

from django.db import models

from apps.core.models import MoneyField, TenantAwareModel


class ModifierGroup(TenantAwareModel):
    """A question asked at the point of sale, e.g. "Size" or "Extras"."""

    name = models.CharField(max_length=100)
    description = models.CharField(max_length=200, blank=True)
    # Attached to specific products; a group with no products is a template the
    # merchant can attach later.
    products = models.ManyToManyField(
        "inventory.Product", blank=True, related_name="modifier_groups",
    )
    is_required = models.BooleanField(
        default=False, help_text="The customer must choose before the item can be added.",
    )
    # min/max let one model cover both "pick a size" and "pick any toppings".
    min_choices = models.PositiveSmallIntegerField(default=0)
    max_choices = models.PositiveSmallIntegerField(
        default=1, help_text="0 means no limit.",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta(TenantAwareModel.Meta):
        # Alphabetical as a tie-break would silently reorder a menu the moment
        # two groups share a sort_order (the default) — "Extras" would jump
        # ahead of "Size" regardless of which one the merchant set up first.
        # created_at preserves the order groups were actually added in.
        ordering = ["sort_order", "created_at"]

    def __str__(self):
        return self.name


class ModifierOption(TenantAwareModel):
    """One answer, and what it does to the price.

    `price_delta` is a difference, not a price: "Large +₦500", "No pepper +₦0".
    Storing a delta means a base price change flows through automatically
    instead of leaving every option stale.
    """

    group = models.ForeignKey(
        ModifierGroup, on_delete=models.CASCADE, related_name="options",
    )
    name = models.CharField(max_length=100)
    price_delta = MoneyField(default=0)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta(TenantAwareModel.Meta):
        ordering = ["sort_order", "created_at"]

    def __str__(self):
        return f"{self.name} ({self.price_delta:+})" if self.price_delta else self.name
