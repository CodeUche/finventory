from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0004_expense_budget_link'),
    ]

    operations = [
        migrations.AddField(
            model_name='expensegroup',
            name='deleted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
