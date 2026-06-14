import uuid
import apps.core.models
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tax', '0004_taxobligation'),
        ('tenancy', '0028_add_strict_gl_mode'),
    ]

    operations = [
        migrations.CreateModel(
            name='CapitalAllowanceClaim',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(db_index=True, default=False)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='tenancy.organisation')),
                ('asset_name', models.CharField(max_length=300)),
                ('asset_class', models.CharField(choices=[
                    ('industrial_building', 'Industrial Building'),
                    ('non_industrial_building', 'Non-Industrial Building'),
                    ('plant_machinery', 'Plant & Machinery'),
                    ('motor_vehicle', 'Motor Vehicle'),
                    ('furniture', 'Furniture & Fittings'),
                    ('computer', 'Computer & IT Equipment'),
                    ('other', 'Other'),
                ], default='plant_machinery', max_length=30)),
                ('tax_year', models.PositiveIntegerField()),
                ('cost', apps.core.models.MoneyField(decimal_places=4, max_digits=15)),
                ('opening_tax_written_down_value', apps.core.models.MoneyField(decimal_places=4, default=0, max_digits=15)),
                ('initial_allowance_rate', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('annual_allowance_rate', models.DecimalField(decimal_places=2, default=20, max_digits=5)),
                ('initial_allowance', apps.core.models.MoneyField(decimal_places=4, default=0, max_digits=15)),
                ('annual_allowance', apps.core.models.MoneyField(decimal_places=4, default=0, max_digits=15)),
                ('total_allowance', apps.core.models.MoneyField(decimal_places=4, default=0, max_digits=15)),
                ('closing_tax_written_down_value', apps.core.models.MoneyField(decimal_places=4, default=0, max_digits=15)),
                ('is_acquisition_year', models.BooleanField(default=False)),
                ('notes', models.TextField(blank=True)),
            ],
            options={'ordering': ['-tax_year', 'asset_name']},
        ),
        migrations.AddConstraint(
            model_name='capitalallowanceclaim',
            constraint=models.UniqueConstraint(
                fields=['organisation', 'asset_name', 'tax_year'],
                name='unique_capital_allowance_per_asset_year',
            ),
        ),
        migrations.CreateModel(
            name='DeferredTaxItem',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(db_index=True, default=False)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='tenancy.organisation')),
                ('deferred_type', models.CharField(choices=[('dta', 'Deferred Tax Asset'), ('dtl', 'Deferred Tax Liability')], max_length=3)),
                ('category', models.CharField(choices=[
                    ('depreciation', 'Accelerated Depreciation'), ('provision', 'Provision / Accrual'),
                    ('revenue', 'Revenue Recognition Timing'), ('expense', 'Disallowed / Deferred Expense'),
                    ('other', 'Other'),
                ], default='depreciation', max_length=20)),
                ('description', models.CharField(max_length=300)),
                ('tax_year', models.PositiveIntegerField()),
                ('timing_difference', apps.core.models.MoneyField(decimal_places=4, max_digits=15)),
                ('tax_rate', models.DecimalField(decimal_places=2, default=30, max_digits=5)),
                ('deferred_tax_amount', apps.core.models.MoneyField(decimal_places=4, default=0, max_digits=15)),
                ('is_recognised', models.BooleanField(default=True)),
                ('reversal_year', models.PositiveIntegerField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
            ],
            options={'ordering': ['-tax_year', 'deferred_type', 'description']},
        ),
        migrations.CreateModel(
            name='RelatedPartyTransaction',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(db_index=True, default=False)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='tenancy.organisation')),
                ('related_party_name', models.CharField(max_length=300)),
                ('relationship', models.CharField(max_length=200)),
                ('country', models.CharField(max_length=2)),
                ('transaction_type', models.CharField(choices=[
                    ('sale_goods', 'Sale of Goods'), ('purchase_goods', 'Purchase of Goods'),
                    ('services_rendered', 'Services Rendered'), ('services_received', 'Services Received'),
                    ('loan_advanced', 'Loan Advanced'), ('loan_received', 'Loan Received'),
                    ('royalties_paid', 'Royalties Paid'), ('royalties_received', 'Royalties Received'),
                    ('mgmt_fee_paid', 'Management Fee Paid'), ('mgmt_fee_received', 'Management Fee Received'),
                    ('dividend', 'Dividend'), ('other', 'Other'),
                ], max_length=30)),
                ('tax_year', models.PositiveIntegerField()),
                ('amount', apps.core.models.MoneyField(decimal_places=4, max_digits=15)),
                ('currency', models.CharField(default='NGN', max_length=3)),
                ('tp_method', models.CharField(choices=[
                    ('cup', 'Comparable Uncontrolled Price (CUP)'),
                    ('rpm', 'Resale Price Method (RPM)'),
                    ('cpm', 'Cost Plus Method (CPM)'),
                    ('tnmm', 'Transactional Net Margin Method (TNMM)'),
                    ('psm', 'Profit Split Method (PSM)'),
                    ('none', 'Not yet determined'),
                ], default='none', max_length=10)),
                ('arm_length_price', apps.core.models.MoneyField(decimal_places=4, default=0, max_digits=15)),
                ('adjustment_required', models.BooleanField(default=False)),
                ('adjustment_amount', apps.core.models.MoneyField(decimal_places=4, default=0, max_digits=15)),
                ('documentation_status', models.CharField(choices=[
                    ('not_prepared', 'Not Prepared'), ('in_progress', 'In Progress'),
                    ('completed', 'Completed'), ('filed', 'Filed with FIRS'),
                ], default='not_prepared', max_length=50)),
                ('notes', models.TextField(blank=True)),
            ],
            options={'ordering': ['-tax_year', 'related_party_name']},
        ),
    ]
