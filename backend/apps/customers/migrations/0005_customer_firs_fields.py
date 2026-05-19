"""
Add FIRS e-invoicing fields to Customer.

tin               — Tax Identification Number; presence triggers B2B clearance flow
digitax_party_id  — DigiTax-assigned party ID cached after POST /parties registration
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0004_customerdebit"),
    ]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="tin",
            field=models.CharField(
                blank=True,
                help_text="Customer Tax Identification Number — triggers B2B flow when set.",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="customer",
            name="digitax_party_id",
            field=models.CharField(
                blank=True,
                help_text="DigiTax-assigned party ID for this customer. Cached after POST /parties.",
                max_length=100,
            ),
        ),
    ]
