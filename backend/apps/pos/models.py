from django.conf import settings
from django.db import models

from apps.core.models import MoneyField, TenantAwareModel


class RestaurantTable(TenantAwareModel):
    """A physical table/room for dine-in / room-service seating."""

    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        OCCUPIED = "occupied", "Occupied"
        RESERVED = "reserved", "Reserved"

    name = models.CharField(max_length=50)
    capacity = models.PositiveIntegerField(default=4)
    section = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.AVAILABLE)
    is_active = models.BooleanField(default=True)

    class Meta(TenantAwareModel.Meta):
        ordering = ["section", "name"]

    def __str__(self):
        return self.name


class POSOrder(TenantAwareModel):
    """A hospitality order (restaurant/bar/hotel). Finalising it creates an Invoice
    so it flows through the standard sale → GL/inventory posting."""

    class OrderType(models.TextChoices):
        DINE_IN = "dine_in", "Dine In"
        DELIVERY = "delivery", "Delivery"
        PICKUP = "pickup", "Pickup"
        ROOM_SERVICE = "room_service", "Room Service"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready"
        SERVED = "served", "Served"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    order_number = models.CharField(max_length=40, db_index=True)
    order_type = models.CharField(max_length=15, choices=OrderType.choices, default=OrderType.DINE_IN)
    table = models.ForeignKey(
        RestaurantTable, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    room_number = models.CharField(max_length=30, blank=True)
    waiter = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="pos_orders_served")
    customer = models.ForeignKey(
        "customers.Customer", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="pos_orders")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    service_charge = MoneyField(default=0)
    tip_amount = MoneyField(default=0)
    notes = models.TextField(blank=True)
    invoice = models.ForeignKey(
        "sales.Invoice", null=True, blank=True, on_delete=models.SET_NULL, related_name="pos_orders")
    warehouse = models.ForeignKey(
        "inventory.Warehouse", null=True, blank=True, on_delete=models.SET_NULL, related_name="pos_orders")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pos_orders_created")

    class Meta(TenantAwareModel.Meta):
        ordering = ["-created_at"]

    def __str__(self):
        return self.order_number

    @classmethod
    def generate_number(cls, organisation):
        from django.db.models import Max
        import re
        prefix = str(organisation.id).replace("-", "")[:4].upper()
        pat = f"ORD-{prefix}-"
        last = cls.objects.filter(order_number__startswith=pat).aggregate(m=Max("order_number"))["m"]
        seq = 1
        if last:
            m = re.search(r"-(\d+)$", last)
            seq = (int(m.group(1)) + 1) if m else 1
        candidate = f"{pat}{seq:05d}"
        while cls.objects.filter(order_number=candidate).exists():
            seq += 1
            candidate = f"{pat}{seq:05d}"
        return candidate

    @property
    def items_subtotal(self):
        from decimal import Decimal
        return sum((i.line_total for i in self.items.all()), Decimal("0"))


class POSOrderItem(TenantAwareModel):
    class KitchenStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready"
        SERVED = "served", "Served"

    order = models.ForeignKey(POSOrder, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT, related_name="pos_order_items")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    unit_price = MoneyField()
    notes = models.CharField(max_length=255, blank=True)   # kitchen notes / modifiers
    kitchen_status = models.CharField(max_length=12, choices=KitchenStatus.choices, default=KitchenStatus.PENDING)

    class Meta(TenantAwareModel.Meta):
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.product_id} × {self.quantity}"

    @property
    def line_total(self):
        from decimal import Decimal
        return Decimal(str(self.quantity)) * Decimal(str(self.unit_price))


class KitchenOrderTicket(TenantAwareModel):
    """A Kitchen Order Ticket (KOT) generated from an order's items."""

    class Status(models.TextChoices):
        NEW = "new", "New"
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready"
        SERVED = "served", "Served"

    order = models.ForeignKey(POSOrder, on_delete=models.CASCADE, related_name="kots")
    kot_number = models.CharField(max_length=40, db_index=True)
    section = models.CharField(max_length=60, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW)
    printed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantAwareModel.Meta):
        ordering = ["-created_at"]

    def __str__(self):
        return self.kot_number
