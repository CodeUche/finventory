# Data migration: lock 1500 Fixed Assets and 1510 Accumulated Depreciation as
# control accounts for existing organisations. Their balances are driven by the
# fixed-asset register (acquisition / depreciation / disposal services), so direct
# manual journals to them must be blocked — only the services post (via
# AccountingService.post_journal_entry, which is exempt from the allow_posting gate).
from django.db import migrations

CONTROL_CODES = ('1500', '1510')


def lock_accounts(apps, schema_editor):
    Account = apps.get_model('accounting', 'Account')
    Account.objects.filter(code__in=CONTROL_CODES).update(
        is_control_account=True, allow_posting=False,
    )


def unlock_accounts(apps, schema_editor):
    Account = apps.get_model('accounting', 'Account')
    Account.objects.filter(code__in=CONTROL_CODES).update(
        is_control_account=False, allow_posting=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0010_fixedasset_acquisition_error_and_more'),
    ]

    operations = [
        migrations.RunPython(lock_accounts, unlock_accounts),
    ]
