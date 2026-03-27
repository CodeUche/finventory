from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0010_add_font_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="organisation",
            name="invoice_template",
            field=models.CharField(
                default="classic",
                help_text="Invoice PDF layout template: classic, modern, minimal, professional",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="pension_provider",
            field=models.CharField(
                blank=True,
                help_text="Default Pension Fund Administrator (PFA) for remittance guidance",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="ai_custom_context",
            field=models.TextField(
                blank=True,
                help_text="Custom business context that personalises the AI assistant for this organisation",
            ),
        ),
    ]
