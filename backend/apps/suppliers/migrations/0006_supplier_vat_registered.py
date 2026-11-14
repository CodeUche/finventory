from django.db import migrations, models


class Migration(migrations.Migration):
    """Additive: one defaulted column; no backfill, no RLS change."""

    dependencies = [('suppliers', '0005_supplier_opening_balance_date')]

    operations = [
        migrations.AddField(
            model_name='supplier', name='vat_registered',
            field=models.CharField(choices=[('yes', 'Yes'), ('no', 'No'), ('unknown', 'Not known')], default='unknown', db_default='unknown', max_length=7),
        ),
    ]
