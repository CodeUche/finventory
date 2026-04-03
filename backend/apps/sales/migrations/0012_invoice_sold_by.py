"""Add sold_by field to Invoice for staff sales tracking."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0011_fix_location_missing_columns"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="sold_by",
            field=models.CharField(blank=True, db_index=True, max_length=200),
        ),
    ]
