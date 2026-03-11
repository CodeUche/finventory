import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0002_add_previous_price'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExpenseGroup',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(default=False, db_index=True)),
                ('name', models.CharField(max_length=200)),
                ('description', models.TextField(blank=True)),
                ('group_date', models.DateField(blank=True, null=True, help_text='Date of the event/run (optional)')),
                ('organisation', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='expensegroups',
                    to='tenancy.organisation',
                )),
                ('parent', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='children',
                    to='expenses.expensegroup',
                )),
            ],
            options={
                'ordering': ['-group_date', 'name'],
                'abstract': False,
            },
        ),
        migrations.AddField(
            model_name='expense',
            name='group',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='expenses',
                to='expenses.expensegroup',
            ),
        ),
    ]
