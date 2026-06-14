import uuid
import apps.core.models
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tax', '0002_exciseduty_whtrate_whttransaction'),
        ('tenancy', '0028_add_strict_gl_mode'),
    ]

    operations = [
        migrations.CreateModel(
            name='WHTCertificate',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(db_index=True, default=False)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='tenancy.organisation')),
                ('wht_transaction', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='certificate', to='tax.whttransaction')),
                ('certificate_number', models.CharField(max_length=50, unique=True)),
                ('issued_date', models.DateField()),
                ('remittance_reference', models.CharField(blank=True, max_length=200)),
                ('notes', models.TextField(blank=True)),
            ],
            options={
                'ordering': ['-issued_date'],
            },
        ),
        migrations.CreateModel(
            name='VATTransaction',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(db_index=True, default=False)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='tenancy.organisation')),
                ('direction', models.CharField(choices=[('output', 'Output (collected)'), ('input', 'Input (paid)')], max_length=10)),
                ('period_start', models.DateField()),
                ('period_end', models.DateField()),
                ('counterparty_name', models.CharField(blank=True, max_length=200)),
                ('counterparty_tin', models.CharField(blank=True, max_length=50)),
                ('net_amount', apps.core.models.MoneyField(decimal_places=4, max_digits=15)),
                ('vat_amount', apps.core.models.MoneyField(decimal_places=4, max_digits=15)),
                ('vat_rate', models.DecimalField(decimal_places=2, default=7.5, max_digits=5)),
                ('is_claimable', models.BooleanField(default=True)),
                ('source_ref', models.CharField(blank=True, max_length=200)),
                ('notes', models.TextField(blank=True)),
            ],
            options={
                'ordering': ['-period_end', 'direction'],
            },
        ),
    ]
