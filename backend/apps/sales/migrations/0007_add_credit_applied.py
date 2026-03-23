from django.db import migrations
import apps.core.models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0006_add_recurring_custom_customer'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='credit_applied',
            field=apps.core.models.MoneyField(decimal_places=4, default=0, max_digits=15),
        ),
    ]
