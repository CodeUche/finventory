"""
Public storefront.

Everything here is reachable WITHOUT a login, which makes it the only part of
Audity where the tenant cannot come from an authenticated session. The
organisation is resolved from the slug in the URL and nothing else, so every
query in this app must be scoped by that resolved organisation explicitly.
"""

from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import MoneyField, TenantAwareModel

# Slugs appear in a public URL and are typed by customers, so keep them tight.
SLUG_VALIDATOR = RegexValidator(
    r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$",
    "Use 3–50 lowercase letters, numbers or hyphens.",
)

# Reserved so a merchant can never take a path the app itself needs.
RESERVED_SLUGS = {
    "api", "admin", "app", "www", "static", "media", "assets", "login",
    "logout", "register", "signup", "settings", "dashboard", "s", "order",
    "orders", "checkout", "cart", "help", "support", "about", "legal",
    "terms", "privacy", "audity",
}


class Storefront(TenantAwareModel):
    """A merchant's public shop page."""

    slug = models.SlugField(
        max_length=50, unique=True, validators=[SLUG_VALIDATOR],
        help_text="The address customers use, e.g. audity.app/s/kates-stores",
    )
    is_published = models.BooleanField(
        default=False,
        help_text="Off means the page returns 'not found' to the public.",
    )
    headline = models.CharField(max_length=120, blank=True)
    about = models.TextField(blank=True)
    whatsapp = models.CharField(max_length=30, blank=True)
    delivery_note = models.CharField(
        max_length=200, blank=True,
        help_text="e.g. 'Delivery within Ikeja, ₦1,500'.",
    )
    accent_colour = models.CharField(max_length=9, blank=True, default="#12694A")

    # Ordering controls
    accepts_orders = models.BooleanField(default=True)
    minimum_order = MoneyField(default=0)
    # Selling stock a shop does not have is the fastest way to lose a customer.
    hide_out_of_stock = models.BooleanField(default=True)

    class Meta(TenantAwareModel.Meta):
        pass

    def __str__(self):
        return f"/{self.slug}"


class StorefrontOrder(TenantAwareModel):
    """A public order, before and after it becomes an invoice.

    Kept separate from Invoice so an abandoned or unpaid order never pollutes
    the sales ledger, and so a customer can track it with a short reference
    instead of an internal id.
    """

    class Status(models.TextChoices):
        PLACED = "placed", "Placed"
        CONFIRMED = "confirmed", "Confirmed"
        READY = "ready", "Ready"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class Fulfilment(models.TextChoices):
        PICKUP = "pickup", "Pickup"
        DELIVERY = "delivery", "Delivery"
        TABLE = "table", "Table service"

    storefront = models.ForeignKey(
        Storefront, on_delete=models.CASCADE, related_name="orders",
    )
    reference = models.CharField(max_length=12, unique=True, db_index=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PLACED)
    fulfilment = models.CharField(
        max_length=10, choices=Fulfilment.choices, default=Fulfilment.PICKUP,
    )

    customer_name = models.CharField(max_length=120)
    customer_phone = models.CharField(max_length=30)
    customer_email = models.EmailField(blank=True)
    delivery_address = models.TextField(blank=True)
    note = models.CharField(max_length=300, blank=True)
    # Set for a QR order placed at a table.
    table = models.ForeignKey(
        "pos.RestaurantTable", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="storefront_orders",
    )

    subtotal = MoneyField(default=0)
    total = MoneyField(default=0)

    # Filled once the order is accepted and becomes a real sale.
    invoice = models.ForeignKey(
        "sales.Invoice", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="storefront_orders",
    )
    pos_order = models.ForeignKey(
        "pos.POSOrder", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="storefront_orders",
    )

    class Meta(TenantAwareModel.Meta):
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["organisation", "status"])]

    def __str__(self):
        return f"{self.reference} ({self.get_status_display()})"


class StorefrontOrderItem(TenantAwareModel):
    """A line on a public order.

    Name and price are copied at order time: a customer must be charged what
    they were shown, even if the merchant re-prices the item a minute later.
    """

    order = models.ForeignKey(
        StorefrontOrder, on_delete=models.CASCADE, related_name="items",
    )
    product = models.ForeignKey(
        "inventory.Product", null=True, on_delete=models.SET_NULL,
        related_name="storefront_order_items",
    )
    product_name = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    unit_price = MoneyField(default=0)
    line_total = MoneyField(default=0)

    class Meta(TenantAwareModel.Meta):
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.product_name} × {self.quantity}"
