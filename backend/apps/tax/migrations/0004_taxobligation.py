import uuid
import apps.core.models
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tax', '0003_whtcertificate_vattransaction'),
        ('tenancy', '0028_add_strict_gl_mode'),
    ]

    operations = [
        migrations.CreateModel(
            name='TaxObligation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(db_index=True, default=False)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='tenancy.organisation')),
                ('obligation_type', models.CharField(choices=[
                    ('vat', 'VAT Return'), ('paye', 'PAYE Remittance'), ('cit', 'Companies Income Tax'),
                    ('pit', 'Personal Income Tax'), ('wht', 'WHT Remittance'),
                    ('pension', 'Pension Contribution'), ('custom', 'Custom'),
                ], max_length=20)),
                ('label', models.CharField(max_length=200)),
                ('period_year', models.PositiveIntegerField()),
                ('period_month', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('due_date', models.DateField()),
                ('status', models.CharField(choices=[
                    ('pending', 'Pending'), ('filed', 'Filed'), ('paid', 'Paid'), ('overdue', 'Overdue'),
                ], default='pending', max_length=20)),
                ('amount_due', apps.core.models.MoneyField(decimal_places=4, default=0, max_digits=15)),
                ('filed_date', models.DateField(blank=True, null=True)),
                ('payment_reference', models.CharField(blank=True, max_length=200)),
                ('notes', models.TextField(blank=True)),
                ('is_auto_generated', models.BooleanField(default=False)),
            ],
            options={
                'ordering': ['due_date'],
            },
        ),
        migrations.AddConstraint(
            model_name='taxobligation',
            constraint=models.UniqueConstraint(
                fields=['organisation', 'obligation_type', 'period_year', 'period_month'],
                name='unique_tax_obligation_per_org_period',
            ),
        ),
    ]
