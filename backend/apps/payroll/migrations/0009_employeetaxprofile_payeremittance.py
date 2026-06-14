import uuid
import apps.core.models
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payroll', '0008_payrollrun_gl_post_error_payrollrun_gl_post_status'),
        ('tenancy', '0028_add_strict_gl_mode'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmployeeTaxProfile',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(db_index=True, default=False)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='tenancy.organisation')),
                ('employee', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='tax_profile', to='payroll.employee')),
                ('nhf_enrolled', models.BooleanField(default=True, help_text='Employee pays NHF (2.5% of basic)')),
                ('voluntary_pension', apps.core.models.MoneyField(decimal_places=4, default=0, max_digits=15)),
                ('life_assurance_premium', apps.core.models.MoneyField(decimal_places=4, default=0, max_digits=15)),
                ('paye_exempt', models.BooleanField(default=False, help_text='If True, no PAYE is deducted')),
                ('notes', models.TextField(blank=True)),
            ],
            options={
                'verbose_name': 'Employee Tax Profile',
            },
        ),
        migrations.CreateModel(
            name='PAYERemittance',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(db_index=True, default=False)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='tenancy.organisation')),
                ('payroll_run', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='paye_remittance', to='payroll.payrollrun')),
                ('period_year', models.PositiveIntegerField()),
                ('period_month', models.PositiveIntegerField()),
                ('amount_due', apps.core.models.MoneyField(decimal_places=4, default=0, max_digits=15)),
                ('amount_paid', apps.core.models.MoneyField(decimal_places=4, default=0, max_digits=15)),
                ('status', models.CharField(choices=[('pending', 'pending'), ('remitted', 'remitted'), ('overdue', 'overdue')], default='pending', max_length=20)),
                ('due_date', models.DateField()),
                ('remittance_date', models.DateField(blank=True, null=True)),
                ('reference', models.CharField(blank=True, max_length=200)),
                ('notes', models.TextField(blank=True)),
            ],
            options={
                'ordering': ['-period_year', '-period_month'],
            },
        ),
        migrations.AddConstraint(
            model_name='payeremittance',
            constraint=models.UniqueConstraint(fields=['organisation', 'period_year', 'period_month'], name='unique_paye_remittance_per_org_period'),
        ),
    ]
