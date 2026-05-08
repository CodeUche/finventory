"""
Allow StockMovement.product to be NULL so that deleting a product does not
cascade-delete the entire stock ledger.  The ledger entries are preserved
as historical audit data; the product FK is simply nullified (SET_NULL).

Stock levels (StockItem) and batch records (Batch) already use CASCADE on
their product FK, so they are removed automatically when a product is deleted.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0006_batch_qty_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='stockmovement',
            name='product',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='movements',
                to='inventory.product',
            ),
        ),
    ]
