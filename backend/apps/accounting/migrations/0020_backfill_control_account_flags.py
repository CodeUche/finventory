from django.db import migrations

# Frozen copy of AccountingService.CONTROL_CODES at the time of this migration.
# Deliberately NOT imported — migrations must not shift when the service changes.
CONTROL_CODES = ['1100', '2001', '1200', '1500', '1510']


def set_control_flags(apps, schema_editor):
    """Repair control-account flags on orgs seeded before CONTROL_CODES existed.

    seed_chart_of_accounts sets these via get_or_create(defaults=...), which only
    apply on create — re-seeding never fixed already-created accounts, leaving
    AR/AP/Inventory/Fixed-Asset accounts open to direct manual journals and direct
    opening balances (which double the control account against its sub-ledger).
    """
    Account = apps.get_model('accounting', 'Account')
    Account.objects.filter(code__in=CONTROL_CODES).update(
        is_control_account=True, allow_posting=False
    )


def noop(apps, schema_editor):
    """Reverse is intentionally a no-op: we cannot tell which accounts were already
    correctly flagged before this ran, and clearing the flags would re-open the
    double-posting hole."""


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0019_backfill_period_dates'),
    ]

    operations = [
        migrations.RunPython(set_control_flags, noop),
    ]
