import apps.core.models
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payroll', '0002_employee_bank_code_recipient_payrollrun_transfer_ref'),
        ('tenancy', '0001_initial'),
    ]

    operations = [
        # ── New fields on PayslipLine ─────────────────────────────────────────
        migrations.AddField(
            model_name='payslipline',
            name='penalty_deductions',
            field=apps.core.models.MoneyField(decimal_places=2, default=0, max_digits=15),
        ),
        migrations.AddField(
            model_name='payslipline',
            name='loan_deductions',
            field=apps.core.models.MoneyField(decimal_places=2, default=0, max_digits=15),
        ),

        # ── EmployeePenalty ───────────────────────────────────────────────────
        migrations.CreateModel(
            name='EmployeePenalty',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(default=False, db_index=True)),
                ('reason', models.CharField(max_length=500)),
                ('amount', apps.core.models.MoneyField(decimal_places=2, max_digits=15)),
                ('penalty_date', models.DateField()),
                ('status', models.CharField(
                    choices=[('pending', 'pending'), ('applied', 'applied'), ('waived', 'waived')],
                    default='pending',
                    max_length=20,
                )),
                ('organisation', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='%(class)s_set',
                    to='tenancy.organisation',
                )),
                ('employee', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='penalties',
                    to='payroll.employee',
                )),
                ('applied_in_run', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='applied_penalties',
                    to='payroll.payrollrun',
                )),
            ],
            options={
                'ordering': ['-penalty_date'],
                'abstract': False,
            },
        ),

        # ── EmployeeLoan ──────────────────────────────────────────────────────
        migrations.CreateModel(
            name='EmployeeLoan',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(default=False, db_index=True)),
                ('principal_amount', apps.core.models.MoneyField(decimal_places=2, max_digits=15)),
                ('interest_rate', models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ('duration_months', models.PositiveIntegerField()),
                ('start_date', models.DateField()),
                ('total_repayable', apps.core.models.MoneyField(decimal_places=2, default=0, max_digits=15)),
                ('monthly_installment', apps.core.models.MoneyField(decimal_places=2, default=0, max_digits=15)),
                ('amount_repaid', apps.core.models.MoneyField(decimal_places=2, default=0, max_digits=15)),
                ('status', models.CharField(
                    choices=[('active', 'active'), ('settled', 'settled'), ('cancelled', 'cancelled')],
                    default='active',
                    max_length=20,
                )),
                ('notes', models.TextField(blank=True)),
                ('organisation', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='%(class)s_set',
                    to='tenancy.organisation',
                )),
                ('employee', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='loans',
                    to='payroll.employee',
                )),
            ],
            options={
                'ordering': ['-start_date'],
                'abstract': False,
            },
        ),
    ]
