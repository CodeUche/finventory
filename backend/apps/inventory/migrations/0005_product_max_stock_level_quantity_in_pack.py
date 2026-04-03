# Generated manually 2026-03-31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0004_alter_product_owner_cost_price"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="max_stock_level",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                help_text="Maximum safety level — do not order above this",
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="quantity_in_pack",
            field=models.DecimalField(
                decimal_places=2,
                default=1,
                help_text="Number of units in one pack / carton",
                max_digits=10,
            ),
        ),
        migrations.AlterField(
            model_name="product",
            name="reorder_level",
            field=models.PositiveIntegerField(
                default=10,
                help_text="Minimum safety level — alert when stock drops below this",
            ),
        ),
    ]
