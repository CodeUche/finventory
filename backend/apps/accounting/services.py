from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from .models import Account, AccountType, JournalEntry, JournalLine, FixedAsset, DepreciationEntry


COA_SEED = [
    ('1001', 'Cash in Hand', AccountType.ASSET),
    ('1002', 'Bank Account', AccountType.ASSET),
    ('1100', 'Accounts Receivable', AccountType.ASSET),
    ('1200', 'Inventory', AccountType.ASSET),
    ('1300', 'Prepaid Expenses', AccountType.ASSET),
    ('1500', 'Fixed Assets', AccountType.ASSET),
    ('1510', 'Accumulated Depreciation', AccountType.ASSET),
    ('2001', 'Accounts Payable', AccountType.LIABILITY),
    ('2100', 'VAT Payable', AccountType.LIABILITY),
    ('2200', 'PAYE Payable', AccountType.LIABILITY),
    ('2300', 'Pension Payable', AccountType.LIABILITY),
    ('2400', 'WHT Payable', AccountType.LIABILITY),
    ('2500', 'NSITF Payable', AccountType.LIABILITY),
    ('2600', 'NHF Payable', AccountType.LIABILITY),
    ('2700', 'Accrued Liabilities', AccountType.LIABILITY),
    ('3001', 'Owner Equity', AccountType.EQUITY),
    ('3100', 'Retained Earnings', AccountType.EQUITY),
    ('4001', 'Sales Revenue', AccountType.REVENUE),
    ('4100', 'Other Income', AccountType.REVENUE),
    ('5001', 'Cost of Goods Sold', AccountType.COST_OF_GOODS),
    ('6001', 'Salaries and Wages', AccountType.EXPENSE),
    ('6100', 'Rent Expense', AccountType.EXPENSE),
    ('6200', 'Utilities', AccountType.EXPENSE),
    ('6300', 'Marketing', AccountType.EXPENSE),
    ('6400', 'Depreciation Expense', AccountType.EXPENSE),
    ('6500', 'Bank Charges', AccountType.EXPENSE),
    ('6600', 'Legal and Professional', AccountType.EXPENSE),
    ('6700', 'Other Expenses', AccountType.EXPENSE),
]


class AccountingService:
    @staticmethod
    def seed_chart_of_accounts(organisation):
        for code, name, acct_type in COA_SEED:
            Account.objects.get_or_create(
                organisation=organisation,
                code=code,
                defaults={'name': name, 'account_type': acct_type, 'is_system': True}
            )

    @staticmethod
    def trial_balance(organisation):
        accounts = Account.objects.filter(organisation=organisation, is_active=True)
        result = []
        for acct in accounts:
            bal = acct.balance
            if bal != 0:
                result.append({
                    'code': acct.code,
                    'name': acct.name,
                    'type': acct.account_type,
                    'balance': bal,
                })
        return result

    @staticmethod
    def balance_sheet(organisation):
        accounts = Account.objects.filter(organisation=organisation, is_active=True)
        assets = [a for a in accounts if a.account_type == AccountType.ASSET]
        liabilities = [a for a in accounts if a.account_type == AccountType.LIABILITY]
        equity = [a for a in accounts if a.account_type == AccountType.EQUITY]
        return {
            'assets': [{'code': a.code, 'name': a.name, 'balance': a.balance} for a in assets],
            'liabilities': [{'code': a.code, 'name': a.name, 'balance': a.balance} for a in liabilities],
            'equity': [{'code': a.code, 'name': a.name, 'balance': a.balance} for a in equity],
            'total_assets': sum(a.balance for a in assets),
            'total_liabilities': sum(a.balance for a in liabilities),
            'total_equity': sum(a.balance for a in equity),
        }

    @staticmethod
    @transaction.atomic
    def run_depreciation(organisation, year, month):
        assets = FixedAsset.objects.filter(organisation=organisation, is_active=True, disposal_date__isnull=True)
        entries = []
        for asset in assets:
            if DepreciationEntry.objects.filter(asset=asset, period_year=year, period_month=month).exists():
                continue
            monthly_dep = asset.annual_depreciation / 12
            accumulated = asset.accumulated_depreciation + monthly_dep
            nbv = asset.purchase_cost - accumulated
            entry = DepreciationEntry.objects.create(
                organisation=organisation,
                asset=asset,
                period_year=year,
                period_month=month,
                depreciation_amount=monthly_dep,
                accumulated_to_date=accumulated,
                net_book_value=max(Decimal('0'), nbv),
            )
            entries.append(entry)
        return entries
