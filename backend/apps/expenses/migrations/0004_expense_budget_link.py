from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('budgets', '0002_add_line_fields'),
        ('expenses', '0003_expense_groups'),
    ]

    operations = [
        migrations.AddField(
            model_name='expense',
            name='budget',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='expenses',
                to='budgets.budget',
            ),
        ),
    ]
