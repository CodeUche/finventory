# Generated manually 2026-03-31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("purchases", "0002_purchaseorder_receipt"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseorder",
            name="delivery_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("self_collection", "Self Collection"),
                    ("haulage", "Haulage / Courier"),
                    ("other", "Other"),
                ],
                default="self_collection",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="purchaseorder",
            name="delivery_notes",
            field=models.CharField(
                blank=True,
                max_length=255,
                help_text="Custom delivery instructions",
            ),
        ),
    ]
