from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0005_organisation_letterhead'),
    ]

    operations = [
        migrations.AddField(
            model_name='organisation',
            name='brand_color',
            field=models.CharField(
                default='#f97316',
                max_length=7,
                help_text='Hex color code (#rrggbb) used in invoice/PDF templates when no letterhead is uploaded',
            ),
        ),
        migrations.AddField(
            model_name='organisation',
            name='use_letterhead',
            field=models.BooleanField(
                default=False,
                help_text='When True, use the uploaded letterhead banner instead of the colored template header',
            ),
        ),
    ]
