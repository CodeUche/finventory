from django.db import migrations, models


class Migration(migrations.Migration):
    """Additive only: one new column with a default, no data change, no RLS change."""

    dependencies = [
        ('bills', '0008_backfill_source_purchase_order'),
    ]

    operations = [
        migrations.AddField(
            model_name='bill',
            name='vat_treatment',
            field=models.CharField(
                choices=[('standard', 'Standard rate'), ('zero_rated', 'Zero-rated'), ('exempt', 'Exempt')],
                default='standard', db_default='standard', max_length=12,
            ),
        ),
    ]
