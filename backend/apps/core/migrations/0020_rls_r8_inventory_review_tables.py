"""
R-8 — enable RLS on the four tenant tables the Inventory Review phases added.

ItemClassGLDefault (accounting 0022), StockCostLayer (inventory 0014),
ProductImage (inventory 0016) and ComboComponent (inventory 0017) all inherit
TenantAwareModel and shipped with no row-level security policy. RlsCoverageTests
flags them — it derives the expected set from the models — but that test only
does anything on PostgreSQL, so it stayed red without anyone seeing it.

StockCostLayer is the one that matters most: it holds every FIFO/LIFO cost
layer, i.e. each organisation's purchase costs.

Policy shape, the FORCE decision, savepoint handling and the deliberate
exclusions are documented in apps/core/rls_policy.py and migration 0013.
"""

from django.db import migrations

from apps.core.rls_policy import apply_rls, revert_rls

TABLES = [
    "accounting_itemclassgldefault",
    "inventory_combocomponent",
    "inventory_productimage",
    "inventory_stockcostlayer",
]

LABEL = "core.0020 (R-8)"


class Migration(migrations.Migration):
    atomic = False

    # Both apps must have created these tables first — see the note in 0016.
    dependencies = [
        ("core", "0019_rls_r7_budgets_period_allocation"),
        ("accounting", "0024_accountmapping_goods_in_transit_account"),
        ("inventory", "0018_item_class_gl_defaults_and_custom_fields"),
    ]

    operations = [
        migrations.RunPython(apply_rls(TABLES, LABEL), revert_rls(TABLES, LABEL), atomic=False),
    ]
