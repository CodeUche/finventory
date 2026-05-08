from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("purchases", "0003_purchaseorder_delivery_type"),
        ("suppliers", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="purchaseorder",
            name="supplier",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="purchase_orders",
                to="suppliers.supplier",
            ),
        ),
    ]
