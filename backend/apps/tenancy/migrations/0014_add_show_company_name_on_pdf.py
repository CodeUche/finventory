from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0013_add_settings_module'),
    ]

    operations = [
        migrations.AddField(
            model_name='organisation',
            name='show_company_name_on_pdf',
            field=models.BooleanField(
                default=True,
                help_text='Whether to show the company name text on invoices and PDFs (alongside the logo)',
            ),
        ),
    ]
