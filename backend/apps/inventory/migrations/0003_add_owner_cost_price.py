"""Add owner_cost_price to Product model."""

from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0002_add_product_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="owner_cost_price",
            field=models.DecimalField(
                decimal_places=4,
                default=Decimal("0"),
                help_text="Owner's actual purchase cost — visible to owners only for margin analytics",
                max_digits=15,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
            ),
        ),
    ]
