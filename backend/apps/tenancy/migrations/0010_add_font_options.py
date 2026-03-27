from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0009_add_invoice_company_name_font"),
    ]

    operations = [
        # Remove choices restriction and extend max_length on existing font field
        migrations.AlterField(
            model_name="organisation",
            name="company_name_font",
            field=models.CharField(
                default="helvetica",
                help_text="Font used for the company name on invoices and PDF documents",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="company_name_font_color",
            field=models.CharField(
                default="#ffffff",
                help_text="Hex color for the company name text on invoices",
                max_length=7,
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="company_name_font_size",
            field=models.PositiveSmallIntegerField(
                default=14,
                help_text="Font size (pt) for the company name on invoices",
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="company_name_font_bold",
            field=models.BooleanField(
                default=True,
                help_text="Whether the company name is bold on invoices",
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="company_name_font_italic",
            field=models.BooleanField(
                default=False,
                help_text="Whether the company name is italic on invoices",
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="company_name_font_underline",
            field=models.BooleanField(
                default=False,
                help_text="Whether the company name is underlined on invoices",
            ),
        ),
    ]
