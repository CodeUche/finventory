"""
Applying modifiers to an order line.

The rules a point of sale actually needs: a required group must be answered, a
group cannot be over-picked, and the price is the base plus the chosen deltas —
computed here, never taken from the caller.
"""

from __future__ import annotations

from decimal import Decimal

from .modifier_models import ModifierGroup, ModifierOption

ZERO = Decimal("0")


class ModifierError(Exception):
    """A choice the cashier or customer needs to correct."""


class ModifierService:
    @staticmethod
    def groups_for(product):
        """Every active group attached to this product, in display order."""
        return (
            ModifierGroup.objects
            .filter(organisation=product.organisation, products=product, is_active=True)
            .prefetch_related("options")
            .order_by("sort_order", "created_at")
        )

    @staticmethod
    def resolve(product, option_ids) -> tuple[list[dict], Decimal]:
        """Validate the chosen options and return (snapshot, total delta).

        The snapshot is what gets stored on the line and printed on the
        receipt: names and prices as they were at the moment of sale.
        """
        option_ids = [str(o) for o in (option_ids or [])]
        groups = list(ModifierService.groups_for(product))

        chosen = list(
            ModifierOption.objects
            .filter(
                organisation=product.organisation, id__in=option_ids,
                is_active=True, group__is_active=True,
            )
            .select_related("group")
        )
        # An id we cannot resolve is a bug or tampering — never silently drop it.
        if len(chosen) != len(set(option_ids)):
            raise ModifierError("One of those choices is no longer available.")

        # Every chosen option must belong to a group attached to this product.
        allowed_group_ids = {g.id for g in groups}
        for option in chosen:
            if option.group_id not in allowed_group_ids:
                raise ModifierError(f"'{option.name}' is not an option for {product.name}.")

        by_group: dict = {}
        for option in chosen:
            by_group.setdefault(option.group_id, []).append(option)

        for group in groups:
            picked = by_group.get(group.id, [])
            if group.is_required and not picked:
                raise ModifierError(f"Please choose {group.name.lower()}.")
            if len(picked) < group.min_choices:
                raise ModifierError(
                    f"Choose at least {group.min_choices} from {group.name}."
                )
            if group.max_choices and len(picked) > group.max_choices:
                raise ModifierError(
                    f"Choose no more than {group.max_choices} from {group.name}."
                )

        snapshot, delta = [], ZERO
        for group in groups:
            for option in by_group.get(group.id, []):
                price = Decimal(str(option.price_delta or 0))
                snapshot.append({
                    "group": group.name,
                    "name": option.name,
                    # 2dp: a MoneyField Decimal prints "500.0000", which is not
                    # a value a receipt or a frontend money formatter expects.
                    "price_delta": str(price.quantize(Decimal("0.01"))),
                })
                delta += price
        return snapshot, delta

    @staticmethod
    def unit_price(product, option_ids, base_price=None) -> tuple[Decimal, list[dict]]:
        """Base price plus the chosen deltas."""
        snapshot, delta = ModifierService.resolve(product, option_ids)
        base = Decimal(str(base_price if base_price is not None else product.selling_price or 0))
        return base + delta, snapshot

    @staticmethod
    def describe(snapshot) -> str:
        """One-line summary for a kitchen ticket or receipt."""
        return ", ".join(entry.get("name", "") for entry in (snapshot or []) if entry.get("name"))
