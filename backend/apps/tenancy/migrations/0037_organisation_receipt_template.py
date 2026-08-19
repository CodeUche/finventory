from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0036_membership_granted_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="organisation",
            name="receipt_template",
            field=models.CharField(
                default="compact",
                help_text=(
                    "POS receipt layout: compact, detailed, branded, classic_cash, "
                    "shop_barcode, stay_folio"
                ),
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="organisation",
            name="receipt_footer_note",
            field=models.CharField(
                blank=True,
                help_text="Closing message on the branded receipt template",
                max_length=200,
            ),
        ),
    ]
