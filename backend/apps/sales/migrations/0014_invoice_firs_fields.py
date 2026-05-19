"""
Add FIRS e-invoicing fields to Invoice.

All new columns are nullable / have defaults so the migration is safe on a
live database: no backfill required, no table lock beyond an ALTER TABLE.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0013_alter_location_created_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="firs_status",
            field=models.CharField(
                db_index=True,
                default="not_enrolled",
                help_text="not_enrolled | pending | submitted | cleared | failed | bypassed",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="firs_irn",
            field=models.CharField(
                blank=True,
                help_text="FIRS Invoice Reference Number — assigned after clearance.",
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="firs_invoice_number",
            field=models.CharField(
                blank=True,
                help_text="FIRS-assigned invoice number (different from internal invoice_number).",
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="firs_csid",
            field=models.CharField(
                blank=True,
                help_text="Cryptographic Stamp Identifier from DigiTax.",
                max_length=500,
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="firs_transaction_type",
            field=models.CharField(
                blank=True,
                help_text="B2B | B2G | B2C — resolved at submission time.",
                max_length=3,
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="firs_qr_code",
            field=models.TextField(
                blank=True,
                help_text="Base64-encoded QR code PNG for embedding in invoice PDF.",
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="tax_point_date",
            field=models.DateField(
                blank=True,
                null=True,
                help_text="Date VAT becomes legally due. Defaults to issue_date if not set.",
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="delivery_start",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="invoice",
            name="delivery_end",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="invoice",
            name="payment_terms_text",
            field=models.CharField(
                blank=True,
                help_text="Free-text payment terms sent to FIRS (e.g. 'Net 30').",
                max_length=500,
            ),
        ),
    ]
