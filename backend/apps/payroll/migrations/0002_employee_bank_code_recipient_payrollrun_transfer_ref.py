from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payroll', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='bank_code',
            field=models.CharField(
                blank=True,
                help_text='Paystack bank code (3-6 digit)',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='employee',
            name='paystack_recipient_code',
            field=models.CharField(
                blank=True,
                help_text='Cached Paystack transfer recipient code (auto-populated on first transfer)',
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name='payrollrun',
            name='transfer_reference',
            field=models.CharField(
                blank=True,
                help_text='Paystack bulk transfer batch_transfer_code or reference',
                max_length=200,
            ),
        ),
    ]
