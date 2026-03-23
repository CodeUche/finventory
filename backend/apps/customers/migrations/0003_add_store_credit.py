from django.db import migrations
import apps.core.models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0002_alter_customer_customer_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='store_credit',
            field=apps.core.models.MoneyField(decimal_places=4, default=0, max_digits=15, help_text='Pre-paid credit balance redeemable on future sales'),
        ),
    ]
