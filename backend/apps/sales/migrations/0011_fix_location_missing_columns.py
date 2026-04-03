"""Add missing deleted_at column to sales_location (migration 0010 was hand-written and omitted it)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0010_location_invoice_location"),
    ]

    operations = [
        migrations.AddField(
            model_name="location",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
