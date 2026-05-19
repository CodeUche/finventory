"""
Phase 4 migration: add submission_kind + sale_return FK to FirsSubmission.

submission_kind discriminates between regular invoice submissions and credit
notes so both can be tracked in the same audit log table.
sale_return links credit-note submissions back to the originating SaleReturn.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        # sales/0014 already exists (the FIRS fields migration from Phase 1)
        ("sales", "0014_invoice_firs_fields"),
        ("einvoicing", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="firssubmission",
            name="submission_kind",
            field=models.CharField(
                choices=[("invoice", "Invoice Submission"), ("credit_note", "Credit Note")],
                db_index=True,
                default="invoice",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="firssubmission",
            name="sale_return",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="firs_submissions",
                to="sales.salereturn",
                help_text="Populated for credit-note submissions; null for regular invoice submissions.",
            ),
        ),
    ]
