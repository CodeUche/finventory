from django.db import migrations, models


class Migration(migrations.Migration):
    """Additive: one defaulted column (100 = today's behaviour); no RLS change."""

    dependencies = [('tenancy', '0039_organisation_charges_vat')]

    operations = [
        migrations.AddField(
            model_name='organisation', name='input_vat_share_percent',
            field=models.DecimalField(decimal_places=2, default=100, max_digits=5),
        ),
    ]
