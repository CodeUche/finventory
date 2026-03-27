"""
Add company_stamp ImageField; remove letterhead FileField and use_letterhead BooleanField.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0011_add_ai_pension_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="organisation",
            name="company_stamp",
            field=models.ImageField(
                blank=True,
                help_text="Optional digital company stamp/seal shown on invoices and delivery notes",
                null=True,
                upload_to="org_stamps/",
            ),
        ),
        migrations.RemoveField(
            model_name="organisation",
            name="letterhead",
        ),
        migrations.RemoveField(
            model_name="organisation",
            name="use_letterhead",
        ),
    ]
