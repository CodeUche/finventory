# Data migration: seed the account sub-type taxonomy for existing orgs and
# backfill account_group / normal_balance / control-account flags on existing
# accounts so they line up with the new COA classification.
from django.db import migrations


# Kept local (not imported from models) so the migration is stable if the module
# constants later change.
ACCOUNT_GROUP_SPEC = {
    'Income':                 ('revenue',   ['Sales Income', 'Other Income']),
    'Cost of Sales':          ('cogs',      ['Cost Of Production', 'Cost of Distribution', 'Damage & Waste']),
    'Indirect Cost':          ('expense',   ['Sales & Marketing', 'Distribution Cost', 'Salaries & Wages']),
    'Expenses':               ('expense',   ['Office Expenses', 'Admin Expenses', 'Finance Expenses',
                                             'Overhead Expenses', 'Depreciation Expenses', 'Tax Expenses']),
    'Asset':                  ('asset',     ['Accum. Depreciation', 'Current Asset', 'Other Asset', 'Fixed Asset',
                                             'Other Current Asset', 'Inventory', 'Receivables', 'Receivable Retainage']),
    'Cash & Cash Equivalent': ('asset',     ['Bank', 'Cash', 'Credit Card', 'Loan', 'Mobile Money']),
    'Liabilities':            ('liability', ['Short Term Liabilities', 'Long Term Liabilities', 'Other Liabilities',
                                             'Payables', 'Payable Retainage']),
    'Equity':                 ('equity',    ['Retained Earnings', "Equity Doesn't Close", 'Equity Get Close',
                                             'Take-On Suspense/Beginning Balance']),
}
DEFAULT_GROUP_FOR_TYPE = {
    'revenue': 'Income', 'cogs': 'Cost of Sales', 'expense': 'Expenses',
    'asset': 'Asset', 'liability': 'Liabilities', 'equity': 'Equity',
}
DEBIT_NORMAL = {'asset', 'expense', 'cogs'}
CONTROL_CODES = {'1100', '2001', '1200'}  # AR, AP, Inventory control accounts


def forwards(apps, schema_editor):
    Organisation = apps.get_model('tenancy', 'Organisation')
    AccountSubType = apps.get_model('accounting', 'AccountSubType')
    Account = apps.get_model('accounting', 'Account')

    for org in Organisation.objects.all():
        for group, (base_type, names) in ACCOUNT_GROUP_SPEC.items():
            for name in names:
                AccountSubType.objects.get_or_create(
                    organisation=org, account_group=group, name=name,
                    defaults={'base_account_type': base_type, 'is_system': True},
                )

    for acct in Account.objects.all():
        changed = False
        if not acct.account_group:
            acct.account_group = DEFAULT_GROUP_FOR_TYPE.get(acct.account_type, '')
            changed = True
        if not acct.normal_balance:
            acct.normal_balance = 'debit' if acct.account_type in DEBIT_NORMAL else 'credit'
            changed = True
        if acct.code in CONTROL_CODES and not acct.is_control_account:
            acct.is_control_account = True
            acct.allow_posting = False
            changed = True
        if changed:
            acct.save(update_fields=['account_group', 'normal_balance',
                                     'is_control_account', 'allow_posting'])


def backwards(apps, schema_editor):
    # Non-destructive reverse: leave backfilled values in place.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('accounting', '0006_account_account_group_account_allow_posting_and_more'),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
