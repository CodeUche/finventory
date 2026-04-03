# Generated manually 2026-03-31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0005_product_max_stock_level_quantity_in_pack"),
    ]

    operations = [
        migrations.AddField(
            model_name="batch",
            name="min_quantity",
            field=models.DecimalField(
                blank=True, null=True, max_digits=12, decimal_places=2,
                help_text="Minimum quantity threshold",
            ),
        ),
        migrations.AddField(
            model_name="batch",
            name="max_quantity",
            field=models.DecimalField(
                blank=True, null=True, max_digits=12, decimal_places=2,
                help_text="Maximum quantity cap",
            ),
        ),
        migrations.AddField(
            model_name="batch",
            name="qty_per_pack",
            field=models.DecimalField(
                blank=True, null=True, max_digits=10, decimal_places=2,
                help_text="Units per pack/carton in this batch",
            ),
        ),
    ]
