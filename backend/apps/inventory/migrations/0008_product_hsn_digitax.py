"""
Add FIRS e-invoicing fields to Product.

hsn_code        — Harmonized System Nomenclature code (required on FIRS line items)
digitax_item_id — DigiTax-assigned item ID cached after POST /items registration
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0007_stockmovement_product_set_null"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="hsn_code",
            field=models.CharField(
                blank=True,
                help_text="Harmonized System Nomenclature code — required for FIRS e-invoicing line items.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="digitax_item_id",
            field=models.CharField(
                blank=True,
                help_text="DigiTax-assigned item ID after POST /items. Cached to avoid re-registration.",
                max_length=100,
            ),
        ),
    ]
