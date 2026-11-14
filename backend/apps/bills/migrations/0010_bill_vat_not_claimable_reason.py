from django.db import migrations, models


class Migration(migrations.Migration):
    """Additive: one defaulted (blank) column; no RLS change."""

    dependencies = [('bills', '0009_bill_vat_treatment')]

    operations = [
        migrations.AddField(
            model_name='bill', name='vat_not_claimable_reason',
            field=models.CharField(blank=True, choices=[
                ('private_use', 'Private or non-business use'), ('entertainment', 'Entertainment and hospitality'),
                ('motor_vehicle', 'Passenger motor vehicles'), ('other', 'Other')], default='', db_default='', max_length=20),
        ),
    ]
