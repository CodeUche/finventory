import logging
from decimal import Decimal
from django.db import transaction
from django.db.models import F, Q, Sum
from .models import Account, AccountType, JournalEntry, JournalLine, FixedAsset, DepreciationEntry, FinancialPeriod, AccountMapping

logger = logging.getLogger(__name__)


COA_SEED = [
    ('1001', 'Cash in Hand', AccountType.ASSET),
    ('1002', 'Bank Account', AccountType.ASSET),
    ('1100', 'Accounts Receivable', AccountType.ASSET),
    ('1200', 'Inventory', AccountType.ASSET),
    ('1300', 'Prepaid Expenses', AccountType.ASSET),
    ('1400', 'VAT Receivable (Input VAT)', AccountType.ASSET),   # C3: recoverable input VAT
    ('1500', 'Fixed Assets', AccountType.ASSET),
    ('1510', 'Accumulated Depreciation', AccountType.ASSET),
    ('1600', 'Deferred Tax Asset', AccountType.ASSET),
    ('2001', 'Accounts Payable', AccountType.LIABILITY),
    ('2050', 'Customer Deposits', AccountType.LIABILITY),   # advances/deposits — liability until earned
    ('2800', 'Deferred Tax Liability', AccountType.LIABILITY),
    ('2100', 'VAT Payable', AccountType.LIABILITY),
    ('2200', 'PAYE Payable', AccountType.LIABILITY),
    ('2300', 'Pension Payable', AccountType.LIABILITY),
    ('2400', 'WHT Payable', AccountType.LIABILITY),
    ('2500', 'NSITF Payable', AccountType.LIABILITY),
    ('2600', 'NHF Payable', AccountType.LIABILITY),
    ('2700', 'Accrued Liabilities', AccountType.LIABILITY),
    ('3001', 'Owner Equity', AccountType.EQUITY),
    ('3100', 'Retained Earnings', AccountType.EQUITY),
    ('3900', 'Take-On Suspense / Opening Balance Equity', AccountType.EQUITY),
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


def check_strict_gl_mode(organisation):
    """
    Raises ValueError if strict_gl_mode is enabled and any required mapping roles are null.
    Called at the start of business event creation (sale, bill, expense, payroll).
    """
    if not getattr(organisation, 'strict_gl_mode', False):
        return
    try:
        mapping = AccountMapping.objects.get(organisation=organisation)
    except AccountMapping.DoesNotExist:
        raise ValueError(
            "Strict GL mode is enabled but no account mapping exists for this organisation. "
            "Go to Settings → GL Mapping to configure accounts."
        )
    REQUIRED_ROLES = [
        'revenue_account', 'cogs_account', 'inventory_account', 'accounts_receivable',
        'cash_account', 'bank_account', 'accounts_payable',
    ]
    missing = [r for r in REQUIRED_ROLES if getattr(mapping, f'{r}_id') is None]
    if missing:
        raise ValueError(
            f"Strict GL mode is enabled but the following accounts are not mapped: "
            f"{', '.join(missing)}. Go to Settings → GL Mapping to configure them."
        )


def safe_post_gl(post_fn, *args, model_instance=None, **kwargs):
    """
    Wraps any post_*_journal call. Updates gl_post_status on the model instance.
    Never raises — logs errors and returns (success: bool, error: str|None).
    """
    from .exceptions import GLAccountNotConfigured
    try:
        post_fn(*args, **kwargs)
        if model_instance and hasattr(model_instance, 'gl_post_status'):
            model_instance.gl_post_status = 'posted'
            model_instance.gl_post_error = ''
            model_instance.save(update_fields=['gl_post_status', 'gl_post_error'])
        return True, None
    except GLAccountNotConfigured as e:
        err = f"GL account not configured: {e.role}"
        logger.warning("safe_post_gl not_configured: %s", err)
        if model_instance and hasattr(model_instance, 'gl_post_status'):
            model_instance.gl_post_status = 'not_configured'
            model_instance.gl_post_error = err
            model_instance.save(update_fields=['gl_post_status', 'gl_post_error'])
        return False, err
    except Exception as e:
        err = str(e)
        logger.error("safe_post_gl failed: %s", err, exc_info=True)
        if model_instance and hasattr(model_instance, 'gl_post_status'):
            model_instance.gl_post_status = 'failed'
            model_instance.gl_post_error = err
            model_instance.save(update_fields=['gl_post_status', 'gl_post_error'])
        return False, err


class AccountMappingService:
    """Service for managing GL account mappings."""

    # Maps role name → (account_type list, code prefix list, name keywords)
    ROLE_HINTS = {
        'revenue_account':         (['revenue'],          ['4001', '4'],  ['sales', 'revenue', 'income']),
        'cogs_account':            (['cogs'],             ['5001', '5'],  ['cost', 'cogs', 'goods']),
        'inventory_account':       (['asset'],            ['1200', '12'], ['inventory', 'stock']),
        'accounts_receivable':     (['asset'],            ['1100', '11'], ['receivable', 'debtor']),
        'cash_account':            (['asset'],            ['1001', '10'], ['cash']),
        'bank_account':            (['asset'],            ['1002', '10'], ['bank', 'current account']),
        'accounts_payable':        (['liability'],        ['2001', '20'], ['payable', 'creditor', 'payables']),
        'vat_output_account':      (['liability'],        ['2100', '21'], ['vat', 'output vat', 'vat payable']),
        'vat_input_account':       (['asset'],            ['1300'],       ['vat input', 'input vat', 'recoverable']),
        'paye_account':            (['liability'],        ['2200', '22'], ['paye', 'income tax', 'payroll tax']),
        'pension_account':         (['liability'],        ['2300', '23'], ['pension']),
        'nhf_account':             (['liability'],        ['2600', '26'], ['nhf', 'national housing', 'housing fund']),
        'wht_account':             (['liability'],        ['2400', '24'], ['withholding', 'wht']),
        'salary_expense_account':  (['expense'],          ['6001', '60'], ['salary', 'salaries', 'wages', 'payroll']),
        'general_expense_account': (['expense'],          ['6700', '67'], ['sundry', 'general', 'miscellaneous', 'other expenses']),
        'bank_charges_account':    (['expense'],          ['6500', '65'], ['bank charge', 'bank charges', 'commission', 'fee']),
    }

    @classmethod
    def get_or_create_mapping(cls, organisation) -> 'AccountMapping':
        mapping, created = AccountMapping.objects.get_or_create(organisation=organisation)
        if created:
            cls.auto_fill(mapping, organisation)
        return mapping

    @classmethod
    def auto_fill(cls, mapping: 'AccountMapping', organisation) -> None:
        """Best-effort auto-fill using hints. Never raises — just leaves null if nothing found."""
        accounts = list(Account.objects.filter(organisation=organisation, is_deleted=False))
        for role, (types, prefixes, keywords) in cls.ROLE_HINTS.items():
            if getattr(mapping, f'{role}_id') is not None:
                continue  # already set, don't overwrite
            best = cls._find_best_match(accounts, types, prefixes, keywords)
            if best:
                setattr(mapping, role, best)
        mapping.save()

    @classmethod
    def _find_best_match(cls, accounts, types, prefixes, keywords):
        """Score each account: type match (3pts) + code prefix (2pts) + keyword in name (1pt each)."""
        best, best_score = None, 0
        for acct in accounts:
            score = 0
            if acct.account_type in types:
                score += 3
            for p in prefixes:
                if acct.code.startswith(p):
                    score += 2
                    break
            name_lower = acct.name.lower()
            for kw in keywords:
                if kw in name_lower:
                    score += 1
            if score > best_score:
                best, best_score = acct, score
        return best if best_score >= 3 else None

    @classmethod
    def resolve(cls, organisation, role: str) -> 'Account':
        """Return the mapped account for a role. Raises GLAccountNotConfigured if not set."""
        from .exceptions import GLAccountNotConfigured
        mapping = cls.get_or_create_mapping(organisation)
        account = getattr(mapping, role, None)
        if account is None:
            raise GLAccountNotConfigured(role)
        return account

    @classmethod
    def suggest(cls, organisation, role: str) -> 'Account | None':
        """Return the best-guess account without raising. Used for UI suggestions."""
        accounts = list(Account.objects.filter(organisation=organisation, is_deleted=False))
        hints = cls.ROLE_HINTS.get(role, ([], [], []))
        return cls._find_best_match(accounts, *hints)


class AccountingService:
    @staticmethod
    def seed_account_sub_types(organisation):
        """Seed the default account sub-type taxonomy (client COA spec)."""
        from .models import AccountSubType, ACCOUNT_GROUP_SPEC
        for group, (base_type, _statement, sub_names) in ACCOUNT_GROUP_SPEC.items():
            for name in sub_names:
                AccountSubType.objects.get_or_create(
                    organisation=organisation,
                    account_group=group,
                    name=name,
                    defaults={'base_account_type': base_type, 'is_system': True},
                )

    # Control accounts accumulate from sub-ledgers (customers/suppliers/stock/assets)
    # and must not accept direct manual journals — only system auto-posting.
    # 1500/1510 are driven by the fixed-asset register (acquisition / depreciation /
    # disposal services), so they are control-locked too.
    CONTROL_CODES = {'1100', '2001', '1200', '1500', '1510'}  # AR, AP, Inventory, Fixed Assets, Accum. Dep

    @staticmethod
    def seed_chart_of_accounts(organisation):
        from .models import DEFAULT_GROUP_FOR_TYPE, normal_balance_for_type
        AccountingService.seed_account_sub_types(organisation)
        for code, name, acct_type in COA_SEED:
            is_control = code in AccountingService.CONTROL_CODES
            Account.objects.get_or_create(
                organisation=organisation,
                code=code,
                defaults={
                    'name': name,
                    'account_type': acct_type,
                    'account_group': DEFAULT_GROUP_FOR_TYPE.get(acct_type, ''),
                    'normal_balance': normal_balance_for_type(acct_type),
                    'is_control_account': is_control,
                    'allow_posting': not is_control,
                    'is_system': True,
                },
            )

    @staticmethod
    def _coerce_date(value):
        """Accept a date or an ISO 'YYYY-MM-DD' string and return a date."""
        from datetime import date as _date
        if isinstance(value, str):
            return _date.fromisoformat(value)
        return value

    @staticmethod
    def get_or_create_suspense_account(organisation):
        """Return the Take-On Suspense / Opening Balance Equity account (3900),
        creating it for legacy orgs that were seeded before it existed."""
        from .models import normal_balance_for_type
        acct = Account.objects.filter(organisation=organisation, code='3900').first()
        if acct:
            return acct
        return Account.objects.create(
            organisation=organisation,
            code='3900',
            name='Take-On Suspense / Opening Balance Equity',
            account_type=AccountType.EQUITY,
            account_group='Equity',
            normal_balance=normal_balance_for_type(AccountType.EQUITY),
            is_system=True,
        )

    @staticmethod
    def _mapped_or_code(organisation, role, code):
        """Resolve a control account via the GL mapping first, falling back to the
        default code. Keeps take-on / opening balances consistent with how business
        events post (so remapping AR/AP/Inventory flows through to take-on too)."""
        try:
            return AccountMappingService.resolve(organisation, role)
        except Exception:
            return AccountingService._get_account_by_code(organisation, code)

    @staticmethod
    @transaction.atomic
    def set_opening_balances(organisation, as_of_date, entries, created_by=None):
        """
        Post ONE balanced take-on journal for opening balances as of `as_of_date`.

        entries: list of dicts {account: Account, amount: Decimal, side: 'debit'|'credit'}

        Debit-balance accounts are debited, credit-balance accounts credited, and the
        net difference is plugged to Take-On Suspense (3900) so the entry always
        balances — the Sage/QuickBooks take-on pattern. Re-running for the same date
        reverses the prior take-on entries first so corrections are non-destructive.
        """
        as_of_date = AccountingService._coerce_date(as_of_date)
        suspense = AccountingService.get_or_create_suspense_account(organisation)

        # Reverse any prior posted opening-balance take-on for this date.
        prior = JournalEntry.objects.filter(
            organisation=organisation,
            source_type='opening_balance',
            source_ref__startswith=f'opening-{as_of_date}',
            status='posted',
        )
        for e in prior:
            AccountingService.reverse_journal_entry(e, actor=created_by)

        lines = []
        total_debit = Decimal('0')
        total_credit = Decimal('0')
        for item in entries:
            acct = item['account']
            amount = Decimal(str(item.get('amount') or 0))
            side = (item.get('side') or acct.effective_normal_balance).lower()
            if amount <= 0:
                continue
            if acct.code == '3900':
                # Never let the user post directly to the suspense plug line.
                continue
            if side == 'debit':
                lines.append((acct, amount, Decimal('0')))
                total_debit += amount
            else:
                lines.append((acct, Decimal('0'), amount))
                total_credit += amount
            acct.opening_balance = amount if side == 'debit' else -amount
            acct.opening_balance_date = as_of_date
            acct.save(update_fields=['opening_balance', 'opening_balance_date'])

        if not lines:
            return None

        # Plug the difference to Take-On Suspense so the take-on always balances.
        diff = total_debit - total_credit
        if diff > Decimal('0'):
            lines.append((suspense, Decimal('0'), diff))
        elif diff < Decimal('0'):
            lines.append((suspense, -diff, Decimal('0')))

        import uuid
        source_ref = f"opening-{as_of_date}-{uuid.uuid4().hex[:12]}"
        return AccountingService.post_journal_entry(
            organisation,
            description=f"Opening balances as of {as_of_date}",
            entry_date=as_of_date,
            lines=lines,
            created_by=created_by,
            ref='OPEN',
            source_type='opening_balance',
            source_ref=source_ref,
        )

    @staticmethod
    @transaction.atomic
    def set_account_opening_balance(organisation, account, amount, side, as_of_date, created_by=None):
        """
        Post an opening balance for a SINGLE account (the account-form 'Option 1' path).

        Reverses only THIS account's prior opening entry (keyed per-account, so it does
        not disturb the batch take-on) and posts DR/CR account + offsetting Take-On
        Suspense so it balances. Passing amount<=0 clears the opening entry.
        """
        as_of_date = AccountingService._coerce_date(as_of_date)
        amount = Decimal(str(amount or 0))
        side = (side or account.effective_normal_balance).lower()
        ref_prefix = f"opening-acct-{account.id}"

        prior = JournalEntry.objects.filter(
            organisation=organisation, source_type='opening_balance',
            source_ref__startswith=ref_prefix, status='posted',
        )
        for e in prior:
            AccountingService.reverse_journal_entry(e, actor=created_by)

        account.opening_balance = amount if side == 'debit' else -amount
        account.opening_balance_date = as_of_date
        account.save(update_fields=['opening_balance', 'opening_balance_date'])

        if amount <= 0:
            return None

        suspense = AccountingService.get_or_create_suspense_account(organisation)
        if account.id == suspense.id:
            return None
        if side == 'debit':
            lines = [(account, amount, Decimal('0')), (suspense, Decimal('0'), amount)]
        else:
            lines = [(account, Decimal('0'), amount), (suspense, amount, Decimal('0'))]

        import uuid
        return AccountingService.post_journal_entry(
            organisation,
            description=f"Opening balance — {account.code} {account.name}",
            entry_date=as_of_date,
            lines=lines,
            created_by=created_by,
            ref='OPEN',
            source_type='opening_balance',
            source_ref=f"{ref_prefix}-{uuid.uuid4().hex[:12]}",
        )

    @staticmethod
    @transaction.atomic
    def set_subledger_opening_balances(organisation, as_of_date, customers=None,
                                       suppliers=None, items=None, created_by=None):
        """
        Take-on opening balances for the sub-ledgers (the wizard's Add Customers /
        Add Suppliers / Add Items). Sets each subledger figure AND posts ONE balanced
        take-on journal:
            DR 1100 Accounts Receivable   = Σ customer opening balances
            DR 1200 Inventory             = Σ item (qty × cost)
            CR 2001 Accounts Payable      = Σ supplier opening balances
            plug 3900 Take-On Suspense.

        customers/suppliers: [{id, amount}]   items: [{product_id, warehouse_id?, quantity, unit_cost?}]
        Re-running for the same date reverses the prior subledger take-on first.
        """
        from apps.customers.models import Customer
        from apps.suppliers.models import Supplier
        from apps.inventory.models import Product, Warehouse
        from apps.inventory.services import InventoryService

        as_of_date = AccountingService._coerce_date(as_of_date)
        customers = customers or []
        suppliers = suppliers or []
        items = items or []

        ref_prefix = f"opening-subledger-{as_of_date}"
        prior = JournalEntry.objects.filter(
            organisation=organisation, source_type='opening_balance',
            source_ref__startswith=ref_prefix, status='posted',
        )
        for e in prior:
            AccountingService.reverse_journal_entry(e, actor=created_by)

        ar_total = Decimal('0')
        for c in customers:
            amount = Decimal(str(c.get('amount') or 0))
            if amount <= 0:
                continue
            cust = Customer.objects.filter(organisation=organisation, id=c.get('id')).first()
            if not cust:
                continue
            cust.outstanding_balance = amount
            cust.save(update_fields=['outstanding_balance'])
            ar_total += amount

        ap_total = Decimal('0')
        for s in suppliers:
            amount = Decimal(str(s.get('amount') or 0))
            if amount <= 0:
                continue
            sup = Supplier.objects.filter(organisation=organisation, id=s.get('id')).first()
            if not sup:
                continue
            sup.opening_balance = amount
            sup.save(update_fields=['opening_balance'])
            ap_total += amount

        inv_total = Decimal('0')
        default_wh = Warehouse.objects.filter(organisation=organisation).order_by('created_at').first()
        for it in items:
            qty = Decimal(str(it.get('quantity') or 0))
            if qty <= 0:
                continue
            product = Product.objects.filter(organisation=organisation, id=it.get('product_id')).first()
            if not product:
                continue
            warehouse = None
            if it.get('warehouse_id'):
                warehouse = Warehouse.objects.filter(organisation=organisation, id=it['warehouse_id']).first()
            warehouse = warehouse or default_wh
            if not warehouse:
                continue
            unit_cost = Decimal(str(it.get('unit_cost') or product.cost_price or 0))
            InventoryService.record_movement(
                organisation=organisation, product=product, warehouse=warehouse,
                quantity=qty, movement_type='opening', unit_cost=unit_cost,
                reference='Opening balance', notes=f'Opening stock as of {as_of_date}',
                created_by=created_by,
            )
            inv_total += qty * unit_cost

        ar = AccountingService._mapped_or_code(organisation, 'accounts_receivable', '1100')
        inv = AccountingService._mapped_or_code(organisation, 'inventory_account', '1200')
        ap = AccountingService._mapped_or_code(organisation, 'accounts_payable', '2001')
        suspense = AccountingService.get_or_create_suspense_account(organisation)

        lines = []
        if ar and ar_total > 0:
            lines.append((ar, ar_total, Decimal('0')))
        if inv and inv_total > 0:
            lines.append((inv, inv_total, Decimal('0')))
        if ap and ap_total > 0:
            lines.append((ap, Decimal('0'), ap_total))
        if not lines:
            return None

        total_debit = ar_total + inv_total
        total_credit = ap_total
        diff = total_debit - total_credit
        if diff > 0:
            lines.append((suspense, Decimal('0'), diff))
        elif diff < 0:
            lines.append((suspense, -diff, Decimal('0')))

        import uuid
        return AccountingService.post_journal_entry(
            organisation,
            description=f"Sub-ledger opening balances as of {as_of_date}",
            entry_date=as_of_date,
            lines=lines,
            created_by=created_by,
            ref='OPEN',
            source_type='opening_balance',
            source_ref=f"{ref_prefix}-{uuid.uuid4().hex[:12]}",
        )

    @staticmethod
    def _ledger_balance(account, as_of=None):
        """
        Posted-ledger balance for a single account, with the account's normal sign
        applied. This is the SAME source of truth the trial balance uses, optionally
        constrained to entries on/before `as_of`. One aggregate query per account.
        """
        lines = JournalLine.objects.filter(
            journal_entry__organisation=account.organisation,
            account=account,
            journal_entry__status='posted',
        )
        if as_of:
            lines = lines.filter(journal_entry__entry_date__lte=as_of)
        agg = lines.aggregate(d=Sum('debit'), c=Sum('credit'))
        debits = agg['d'] or Decimal('0')
        credits = agg['c'] or Decimal('0')
        if account.account_type in (AccountType.ASSET, AccountType.EXPENSE, AccountType.COST_OF_GOODS):
            return debits - credits
        return credits - debits

    @staticmethod
    def trial_balance(organisation, as_of=None):
        accounts = Account.objects.filter(organisation=organisation, is_active=True)
        result = []
        for acct in accounts:
            bal = AccountingService._ledger_balance(acct, as_of=as_of)
            if bal != 0:
                result.append({
                    'code': acct.code,
                    'name': acct.name,
                    'type': acct.account_type,
                    'balance': bal,
                })
        return result

    @staticmethod
    def balance_sheet(organisation, as_of=None):
        """
        Ledger-derived balance sheet. Every figure is read from the posted general
        ledger — the SAME source as the trial balance — so the sheet is guaranteed to
        balance whenever the trial balance does (a balanced TB mathematically implies
        Assets = Liabilities + Equity + (Revenue − Expenses)).

        Current-year P&L net (revenue − expenses − COGS) is rolled into equity as a
        computed "Current Year Earnings" line so profit not yet closed to retained
        earnings still lands on the sheet. Any residual (rounding) difference is
        plugged to a Take-On Suspense line so the statement ALWAYS presents balanced,
        per the client requirement.
        """
        accounts = Account.objects.filter(organisation=organisation, is_active=True)
        assets_data, liabilities_data, equity_data = [], [], []
        total_income = Decimal('0')
        total_expense = Decimal('0')

        for acct in accounts:
            bal = AccountingService._ledger_balance(acct, as_of=as_of)
            row = {'code': acct.code, 'name': acct.name, 'balance': bal}
            if acct.account_type == AccountType.ASSET:
                if bal != 0:
                    assets_data.append(row)
            elif acct.account_type == AccountType.LIABILITY:
                if bal != 0:
                    liabilities_data.append(row)
            elif acct.account_type == AccountType.EQUITY:
                if bal != 0:
                    equity_data.append(row)
            elif acct.account_type == AccountType.REVENUE:
                total_income += bal
            elif acct.account_type in (AccountType.EXPENSE, AccountType.COST_OF_GOODS):
                total_expense += bal

        # Roll current-year P&L net into equity (income − expenses).
        current_year_earnings = total_income - total_expense
        if current_year_earnings != 0:
            equity_data.append({
                'code': '',
                'name': 'Current Year Earnings',
                'balance': current_year_earnings,
                'is_computed': True,
            })

        total_assets = sum((r['balance'] for r in assets_data), Decimal('0'))
        total_liabilities = sum((r['balance'] for r in liabilities_data), Decimal('0'))
        total_equity = sum((r['balance'] for r in equity_data), Decimal('0'))

        # Safety plug: with a clean double-entry ledger the difference is 0 by
        # construction, but any residual is posted to Take-On Suspense so the sheet
        # is never presented as "not balanced".
        difference = total_assets - (total_liabilities + total_equity)
        if abs(difference) > Decimal('0.01'):
            equity_data.append({
                'code': '3900',
                'name': 'Take-On Suspense (auto-balance)',
                'balance': difference,
                'is_computed': True,
            })
            total_equity += difference

        return {
            'assets': assets_data,
            'liabilities': liabilities_data,
            'equity': equity_data,
            'total_assets': total_assets,
            'total_liabilities': total_liabilities,
            'total_equity': total_equity,
            'current_year_earnings': current_year_earnings,
            'balanced': abs(total_assets - (total_liabilities + total_equity)) < Decimal('0.01'),
            'as_of': str(as_of) if as_of else None,
        }

    @staticmethod
    def _synthetic_account_balances(organisation, as_of=None) -> dict:
        """
        DEPRECATED — no longer used by balance_sheet().

        This reconstructed balances from operational subledgers (SalePayment,
        Expense, StockItem, FixedAsset, Bill …) rather than the posted general
        ledger, which is exactly what caused the Balance Sheet to diverge from the
        Trial Balance (assets from subledgers, no offsetting L+E in the ledger).
        The Balance Sheet is now ledger-derived; do NOT re-wire this as its source.
        Kept only for reference / potential reconciliation tooling.

        Return a dict of {account_code: balance} computed from transaction data.
        """
        balances = {}
        zero = Decimal('0')

        # ── 1001 Cash in Hand ─────────────────────────────────────────────────
        try:
            from apps.sales.models import SalePayment
            sp_qs = SalePayment.objects.filter(organisation=organisation, method='cash')
            if as_of:
                sp_qs = sp_qs.filter(received_at__date__lte=as_of)
            cash_in = sp_qs.aggregate(t=Sum('amount'))['t'] or zero
            from apps.expenses.models import Expense
            exp_qs = Expense.objects.filter(organisation=organisation, is_income=False)
            if as_of:
                exp_qs = exp_qs.filter(expense_date__lte=as_of)
            cash_out = exp_qs.aggregate(t=Sum('amount'))['t'] or zero
            balances['1001'] = max(zero, cash_in - cash_out)
        except Exception:
            pass

        # ── 1002 Bank Account ──────────────────────────────────────────────────
        try:
            from apps.sales.models import SalePayment
            bank_sp_qs = SalePayment.objects.filter(
                organisation=organisation, method__in=['bank_transfer', 'pos']
            )
            if as_of:
                bank_sp_qs = bank_sp_qs.filter(received_at__date__lte=as_of)
            bank_in = bank_sp_qs.aggregate(t=Sum('amount'))['t'] or zero
            from apps.bills.models import BillPayment
            bp_qs = BillPayment.objects.filter(
                organisation=organisation,
                method__in=['bank_transfer', 'cheque', 'pos'],
            )
            if as_of:
                bp_qs = bp_qs.filter(payment_date__lte=as_of)
            bank_out = bp_qs.aggregate(t=Sum('amount'))['t'] or zero
            balances['1002'] = max(zero, bank_in - bank_out)
        except Exception:
            pass

        # ── 1100 Accounts Receivable ──────────────────────────────────────────
        try:
            from apps.customers.models import Customer
            from apps.sales.models import Invoice
            # Credit-sale AR: tracked on Customer.outstanding_balance
            ar = (
                Customer.objects.filter(organisation=organisation)
                .aggregate(t=Sum('outstanding_balance'))['t'] or zero
            )
            # Non-credit invoices with an outstanding balance (e.g. partial cash payments)
            partial_qs = Invoice.objects.filter(
                organisation=organisation,
                status__in=['confirmed', 'partially_paid', 'overdue'],
                amount_due__gt=0,
            ).exclude(payment_method='credit')
            if as_of:
                partial_qs = partial_qs.filter(issue_date__lte=as_of)
            partial_ar = partial_qs.aggregate(t=Sum('amount_due'))['t'] or zero
            balances['1100'] = ar + partial_ar
        except Exception:
            pass

        # ── 1200 Inventory ────────────────────────────────────────────────────
        try:
            from apps.inventory.models import StockItem
            items = (
                StockItem.objects
                .filter(organisation=organisation, quantity_on_hand__gt=0)
                .select_related('product')
            )
            inv_value = sum(
                item.quantity_on_hand * item.product.cost_price for item in items
            )
            balances['1200'] = Decimal(str(inv_value))
        except Exception:
            pass

        # ── 1500 Fixed Assets ─────────────────────────────────────────────────
        try:
            fa_qs = FixedAsset.objects.filter(
                organisation=organisation, is_active=True, disposal_date__isnull=True
            )
            if as_of:
                fa_qs = fa_qs.filter(purchase_date__lte=as_of)
            fa_cost = fa_qs.aggregate(t=Sum('purchase_cost'))['t'] or zero
            balances['1500'] = fa_cost
        except Exception:
            pass

        # ── 1510 Accumulated Depreciation (contra-asset — negative) ───────────
        try:
            dep_qs = DepreciationEntry.objects.filter(organisation=organisation)
            if as_of:
                dep_qs = dep_qs.filter(period_year__lt=as_of.year) | DepreciationEntry.objects.filter(
                    organisation=organisation,
                    period_year=as_of.year,
                    period_month__lte=as_of.month,
                )
            acc_dep = dep_qs.aggregate(t=Sum('depreciation_amount'))['t'] or zero
            balances['1510'] = -acc_dep
        except Exception:
            pass

        # ── 2001 Accounts Payable ─────────────────────────────────────────────
        try:
            from apps.bills.models import Bill
            bill_qs = Bill.objects.filter(
                organisation=organisation,
                status__in=['draft', 'received', 'approved', 'partially_paid', 'overdue'],
            )
            if as_of:
                bill_qs = bill_qs.filter(issue_date__lte=as_of)
            ap = bill_qs.aggregate(t=Sum('amount_due'))['t'] or zero
            balances['2001'] = ap
        except Exception:
            pass

        # ── 3100 Retained Earnings (all-time net profit) ──────────────────────
        try:
            from apps.sales.models import Invoice, SaleItem
            from apps.expenses.models import Expense

            inv_qs = Invoice.objects.filter(
                organisation=organisation,
                status__in=['paid', 'confirmed', 'partially_paid', 'credit'],
            )
            if as_of:
                inv_qs = inv_qs.filter(issue_date__lte=as_of)
            revenue = inv_qs.aggregate(t=Sum('total_amount'))['t'] or zero

            cogs = (
                SaleItem.objects.filter(
                    organisation=organisation,
                    invoice__in=inv_qs,
                ).aggregate(t=Sum('cost_of_goods'))['t'] or zero
            )
            re_exp_qs = Expense.objects.filter(organisation=organisation, is_income=False)
            if as_of:
                re_exp_qs = re_exp_qs.filter(expense_date__lte=as_of)
            expenses = re_exp_qs.aggregate(t=Sum('amount'))['t'] or zero
            re_inc_qs = Expense.objects.filter(organisation=organisation, is_income=True)
            if as_of:
                re_inc_qs = re_inc_qs.filter(expense_date__lte=as_of)
            misc_income = re_inc_qs.aggregate(t=Sum('amount'))['t'] or zero
            balances['3100'] = revenue - cogs - expenses + misc_income
        except Exception:
            pass

        return balances

    @staticmethod
    def _period_depreciation(asset, year, month, accumulated_so_far, current_nbv, depreciable_remaining):
        """Depreciation charge for one asset for one period, honouring the asset's
        method and (for the first period) its convention. Returns a Decimal (uncapped;
        the caller clamps to the remaining depreciable base)."""
        import calendar
        zero = Decimal('0')
        method = asset.depreciation_method

        if method == FixedAsset.ZERO:
            return zero
        if method == FixedAsset.IMMEDIATE:
            return depreciable_remaining  # fully written off in the first period
        if method == FixedAsset.UNITS:
            # Units of production needs per-period usage input; the unattended batch
            # run charges nothing (usage-driven posting is handled separately).
            return zero

        # "New month" convention: charge nothing in the purchase month; the first
        # charge lands the following month.
        if (accumulated_so_far <= zero
                and asset.depreciation_convention == FixedAsset.CONV_NEW_MONTH
                and asset.purchase_date.year == year and asset.purchase_date.month == month):
            return zero

        if method == FixedAsset.RB:
            if asset.reducing_balance_rate:
                annual_rate = Decimal(str(asset.reducing_balance_rate)) / Decimal('100')
            elif asset.useful_life_years > 0:
                annual_rate = Decimal('1') / asset.useful_life_years
            else:
                return zero
            monthly = current_nbv * annual_rate / 12
        else:  # straight line
            total_months = asset.useful_life_years * 12
            if total_months <= 0:
                return zero
            monthly = (asset.purchase_cost - asset.residual_value) / total_months

        # Pro-rata the first period (partial month of purchase) when configured.
        if accumulated_so_far <= zero and asset.depreciation_convention == FixedAsset.CONV_PRORATA:
            pd = asset.purchase_date
            if pd.year == year and pd.month == month:
                days_in_month = calendar.monthrange(year, month)[1]
                active_days = days_in_month - pd.day + 1
                if 0 < active_days < days_in_month:
                    monthly = monthly * Decimal(active_days) / Decimal(days_in_month)
        return monthly

    @staticmethod
    def run_depreciation_catch_up(organisation, up_to_year, up_to_month, created_by=None, draft=False):
        """Run depreciation for every month from the earliest asset's start up to the
        target period (the reviewer's 'yearly / through the life span' ask). Returns
        the combined list of entries created across all periods."""
        from datetime import date as _date
        assets = (
            FixedAsset.objects
            .filter(organisation=organisation, is_active=True, disposal_date__isnull=True)
            .exclude(category=FixedAsset.LAND)
        )
        starts = [a.purchase_date for a in assets]
        if not starts:
            return []
        start = min(starts)
        target = _date(up_to_year, up_to_month, 1)
        all_entries = []
        y, mo = start.year, start.month
        while _date(y, mo, 1) <= target:
            all_entries.extend(
                AccountingService.run_depreciation(organisation, y, mo, created_by=created_by, draft=draft)
            )
            y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
        return all_entries

    @staticmethod
    @transaction.atomic
    def run_depreciation(organisation, year, month, created_by=None, draft=False):
        import calendar
        from datetime import date as _date

        period_last_day = _date(year, month, calendar.monthrange(year, month)[1])
        assets = (
            FixedAsset.objects
            .filter(
                organisation=organisation,
                is_active=True,
                disposal_date__isnull=True,
                purchase_date__lte=period_last_day,
            )
            .exclude(category=FixedAsset.LAND)
            .prefetch_related('depreciation_entries')
        )
        entries = []
        for asset in assets:
            if any(
                e.period_year == year and e.period_month == month
                for e in asset.depreciation_entries.all()
            ):
                continue

            accumulated_so_far = sum(
                e.depreciation_amount for e in asset.depreciation_entries.all()
            ) or Decimal('0')
            current_nbv = asset.purchase_cost - accumulated_so_far
            depreciable_remaining = current_nbv - asset.residual_value

            if depreciable_remaining <= Decimal('0'):
                continue

            monthly_dep = AccountingService._period_depreciation(
                asset, year, month, accumulated_so_far, current_nbv, depreciable_remaining
            )
            monthly_dep = min(monthly_dep, depreciable_remaining)
            monthly_dep = max(Decimal('0'), monthly_dep)
            if monthly_dep <= 0:
                # 0% method, units with no usage, or nothing left to charge.
                continue

            accumulated = accumulated_so_far + monthly_dep
            nbv = max(asset.residual_value, asset.purchase_cost - accumulated)

            entry = DepreciationEntry.objects.create(
                organisation=organisation,
                asset=asset,
                period_year=year,
                period_month=month,
                depreciation_amount=monthly_dep,
                accumulated_to_date=accumulated,
                net_book_value=nbv,
            )
            # Post depreciation to the GL so it flows onto the ledger-derived P&L and
            # Balance Sheet: DR Depreciation Expense (6400) / CR Accumulated
            # Depreciation (1510). Non-fatal — a missing GL account never blocks the
            # depreciation run itself.
            try:
                AccountingService.post_depreciation_journal(
                    organisation, asset, monthly_dep, period_last_day, created_by=created_by, draft=draft
                )
            except Exception:
                logger.warning(
                    "Depreciation GL post skipped for asset %s %s-%s",
                    getattr(asset, 'asset_code', asset.pk), year, month,
                    exc_info=True,
                )
            entries.append(entry)
        return entries

    @staticmethod
    def _get_account_by_code(organisation, code):
        """Return the org's Account for a GL code, or None. Used for code-mapped roles
        (fixed assets / accumulated depreciation / depreciation expense) that have no
        AccountMapping role."""
        return Account.objects.filter(organisation=organisation, code=code).first()

    @staticmethod
    def post_depreciation_journal(organisation, asset, amount, entry_date, created_by=None, draft=False):
        """DR Depreciation Expense / CR Accumulated Depreciation. Uses the asset type's
        mapped accounts when set, else the defaults (6400 / 1510). When draft=True the
        journal is created as a DRAFT (pending approval) rather than posted, so an
        accountant can review the batch before it hits the ledger."""
        amount = Decimal(str(amount or 0))
        if amount <= 0:
            return None
        at = getattr(asset, 'asset_type', None)
        dep_exp = (at.depreciation_expense_account if at and at.depreciation_expense_account_id else None) \
            or AccountingService._get_account_by_code(organisation, '6400')
        acc_dep = (at.accumulated_depreciation_account if at and at.accumulated_depreciation_account_id else None) \
            or AccountingService._get_account_by_code(organisation, '1510')
        if not dep_exp or not acc_dep:
            return None
        return AccountingService.post_journal_entry(
            organisation,
            description=f"Depreciation — {getattr(asset, 'name', '')}".strip(' —'),
            entry_date=entry_date,
            lines=[(dep_exp, amount, Decimal('0')), (acc_dep, Decimal('0'), amount)],
            created_by=created_by,
            ref='DEP',
            source_type='depreciation',
            source_ref=f"{asset.pk}-{entry_date.year}-{entry_date.month}",
            status='draft' if draft else 'posted',
            approval_status='pending' if draft else 'none',
        )

    @staticmethod
    @transaction.atomic
    def record_usage_depreciation(organisation, asset, year, month, units, created_by=None):
        """Units-of-Production depreciation for one period: charge =
        units × (cost − residual) / total_units, capped at the remaining depreciable
        base. Creates the depreciation entry (with the units) and posts it to the GL.
        Idempotent per (asset, year, month)."""
        import calendar
        from datetime import date as _date
        from .models import DepreciationEntry
        units = Decimal(str(units or 0))
        total = Decimal(str(asset.total_units or 0))
        if units <= 0 or total <= 0:
            raise ValueError("Units of Usage needs a positive usage and a total-units figure on the asset.")
        if DepreciationEntry.objects.filter(asset=asset, period_year=year, period_month=month).exists():
            raise ValueError(f"Depreciation for {year}-{month:02d} already exists for this asset.")

        accumulated_so_far = Decimal(str(asset.accumulated_depreciation or 0))
        depreciable_remaining = Decimal(str(asset.purchase_cost)) - accumulated_so_far - Decimal(str(asset.residual_value or 0))
        if depreciable_remaining <= 0:
            raise ValueError("This asset is already fully depreciated.")

        charge = (units * (Decimal(str(asset.purchase_cost)) - Decimal(str(asset.residual_value or 0))) / total)
        charge = min(charge.quantize(Decimal('0.01')), depreciable_remaining)
        accumulated = accumulated_so_far + charge
        nbv = max(Decimal(str(asset.residual_value or 0)), Decimal(str(asset.purchase_cost)) - accumulated)
        period_last_day = _date(year, month, calendar.monthrange(year, month)[1])

        entry = DepreciationEntry.objects.create(
            organisation=organisation, asset=asset, period_year=year, period_month=month,
            depreciation_amount=charge, accumulated_to_date=accumulated, net_book_value=nbv, units=units,
        )
        AccountingService.post_depreciation_journal(
            organisation, asset, charge, period_last_day, created_by=created_by
        )
        return entry

    @staticmethod
    @transaction.atomic
    def post_depreciation_drafts(organisation, year, month, user=None):
        """Post (approve) all DRAFT depreciation journals for a period — the 'Post
        Batch' step of the semi-automated depreciation run."""
        import calendar
        from datetime import date as _date
        last_day = _date(year, month, calendar.monthrange(year, month)[1])
        drafts = JournalEntry.objects.filter(
            organisation=organisation, source_type='depreciation', status='draft',
            entry_date=last_day,
        )
        count = 0
        for je in drafts:
            je.status = 'posted'
            je.approval_status = 'approved'
            je.posted_by = user
            je.approved_by = user
            je.save(update_fields=['status', 'approval_status', 'posted_by', 'approved_by'])
            count += 1
        return count

    # ──────────────────────────────────────────────────────────────────────────
    # Auto-posting helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _has_active_grant(period, user) -> bool:
        """True if `user` holds an active (non-revoked, unexpired) posting grant for
        `period` — a time-boxed exception to post into a locked period."""
        from django.utils import timezone as _tz
        from .models import PeriodPostingGrant
        if user is None or not getattr(user, 'id', None):
            return False
        return PeriodPostingGrant.objects.filter(
            period=period, user=user, revoked=False, expires_at__gt=_tz.now(),
        ).exists()

    @staticmethod
    def is_period_locked(organisation, date, user=None) -> bool:
        """Return True if the financial period for date is locked.

        If `user` is given and holds an active posting grant for that period, it is
        treated as unlocked for them (time-boxed administrator exception).
        """
        try:
            locked = FinancialPeriod.objects.filter(
                organisation=organisation,
                year=date.year,
                month=date.month,
                is_locked=True,
            ).first()
            if not locked:
                return False
            if user is not None and AccountingService._has_active_grant(locked, user):
                return False
            return True
        except Exception:
            return False

    @staticmethod
    def _last_weekday_of_month(year, month, weekday):
        """Return the date of the last given weekday (0=Mon..6=Sun) in the month."""
        import calendar
        from datetime import date as _date, timedelta
        last_dom = calendar.monthrange(year, month)[1]
        d = _date(year, month, last_dom)
        return d - timedelta(days=(d.weekday() - weekday) % 7)

    @staticmethod
    @transaction.atomic
    def generate_fiscal_year(organisation, year, start_date, rule='last_day_of_month',
                             closing_day=None, weekday=None, created_by=None):
        """Generate a FiscalYear + its 12 monthly FinancialPeriods (the 'Generate
        Accounting Periods' wizard). Idempotent: returns the existing FiscalYear if
        one already exists for `year`. Existing periods are linked/updated, never
        duplicated, so locks are preserved.
        """
        import calendar
        from datetime import date as _date
        from .models import FiscalYear, FinancialPeriod

        start_date = AccountingService._coerce_date(start_date)
        existing = FiscalYear.objects.filter(organisation=organisation, year=int(year)).first()
        if existing:
            return existing

        periods = []
        cur_year, cur_month = start_date.year, start_date.month
        for i in range(12):
            p_start = start_date if i == 0 else _date(cur_year, cur_month, 1)
            last_dom = calendar.monthrange(cur_year, cur_month)[1]
            if rule == 'specific_day' and closing_day:
                p_end = _date(cur_year, cur_month, min(int(closing_day), last_dom))
            elif rule == 'last_weekday' and weekday is not None:
                p_end = AccountingService._last_weekday_of_month(cur_year, cur_month, int(weekday))
            else:
                p_end = _date(cur_year, cur_month, last_dom)
            periods.append((cur_year, cur_month, i + 1, p_start, p_end))
            cur_month += 1
            if cur_month > 12:
                cur_month, cur_year = 1, cur_year + 1

        fy = FiscalYear.objects.create(
            organisation=organisation, year=int(year), start_date=start_date,
            end_date=periods[-1][4], generation_rule=rule,
        )
        for (py, pm, pn, ps, pe) in periods:
            FinancialPeriod.objects.update_or_create(
                organisation=organisation, year=py, month=pm,
                defaults={'fiscal_year': fy, 'period_number': pn, 'start_date': ps, 'end_date': pe},
            )
        return fy

    @staticmethod
    def grant_period_access(organisation, period, user, granted_by=None, days=3,
                            expires_at=None, reason=''):
        """Grant a user a time-boxed exception to post into a locked period."""
        from django.utils import timezone as _tz
        from datetime import timedelta
        from .models import PeriodPostingGrant
        if expires_at is None:
            expires_at = _tz.now() + timedelta(days=int(days or 3))
        grant = PeriodPostingGrant.objects.create(
            organisation=organisation, period=period, user=user,
            granted_by=granted_by, expires_at=expires_at, reason=reason,
        )
        try:
            from apps.core.models import AuditLog
            AuditLog.log(
                action=AuditLog.UPDATE, user=granted_by, organisation=organisation,
                model_name='PeriodPostingGrant', object_id=str(grant.id), object_repr=str(grant),
                changes={'event': 'period_grant_created', 'user': str(user.id),
                         'period': str(period.id), 'expires_at': str(expires_at), 'reason': reason},
                is_owner_action=True,
            )
        except Exception:
            pass
        return grant

    @staticmethod
    def post_journal_entry(
        organisation,
        description: str,
        entry_date,
        lines: list,  # list of (Account_object, debit: Decimal, credit: Decimal)
        created_by=None,
        ref: str = 'AUTO',
        source_type: str = '',
        source_ref: str = '',
        status: str = 'posted',
        approval_status: str = 'none',
    ) -> 'JournalEntry':
        """
        Create a balanced double-entry journal entry.

        lines: list of (Account_object, debit: Decimal, credit: Decimal)

        Idempotent: if source_type+source_ref already exists for this org, returns
        the existing JournalEntry without creating a duplicate.

        Raises PeriodLockedError if the entry_date falls in a locked period.
        """
        from .exceptions import PeriodLockedError

        # Period lock check — honour a time-boxed posting grant for the acting user.
        if entry_date:
            locked_period = FinancialPeriod.objects.filter(
                organisation=organisation,
                year=entry_date.year,
                month=entry_date.month,
                is_locked=True,
            ).first()
            if locked_period:
                if AccountingService._has_active_grant(locked_period, created_by):
                    # Posted into a locked period under an administrator grant — record it.
                    try:
                        from apps.core.models import AuditLog
                        AuditLog.log(
                            action=AuditLog.UPDATE, user=created_by, organisation=organisation,
                            model_name='FinancialPeriod', object_id=str(locked_period.id),
                            object_repr=str(locked_period),
                            changes={'event': 'locked_period_post_via_grant', 'ref': ref,
                                     'source': f'{source_type}/{source_ref}'},
                        )
                    except Exception:
                        pass
                else:
                    raise PeriodLockedError(
                        f"Period {locked_period} is locked. Unlock it before posting."
                    )

        # Idempotency: return existing entry if same source already posted
        if source_type and source_ref:
            existing = JournalEntry.objects.filter(
                organisation=organisation,
                source_type=source_type,
                source_ref=source_ref,
            ).first()
            if existing:
                return existing

        # Filter out zero lines
        non_zero_lines = [(acct, d, c) for (acct, d, c) in lines if d > 0 or c > 0]
        if not non_zero_lines:
            logger.warning("post_journal_entry: all lines are zero, skipping. ref=%s", ref)
            return None

        # E2: validate debits == credits before committing (raise, don't silently post)
        total_debits  = sum(Decimal(str(d)) for _, d, _ in non_zero_lines)
        total_credits = sum(Decimal(str(c)) for _, _, c in non_zero_lines)
        if abs(total_debits - total_credits) > Decimal('0.01'):
            raise ValueError(
                f"Journal entry imbalanced: debits={total_debits}, credits={total_credits} "
                f"(ref={ref}, source={source_type}/{source_ref})"
            )

        with transaction.atomic():
            entry = JournalEntry.objects.create(
                organisation=organisation,
                description=description,
                entry_date=entry_date,
                reference='',  # will be auto-set in save()
                status=status,
                approval_status=approval_status,
                created_by=created_by,
                source_type=source_type,
                source_ref=source_ref,
            )
            for account, debit, credit in non_zero_lines:
                JournalLine.objects.create(
                    journal_entry=entry,
                    account=account,
                    debit=Decimal(str(debit)),
                    credit=Decimal(str(credit)),
                )

        # Emit audit log
        try:
            from apps.core.models import AuditLog
            AuditLog.log(
                action=AuditLog.CREATE,
                user=created_by,
                organisation=organisation,
                model_name='JournalEntry',
                object_id=str(entry.id),
                object_repr=str(entry),
                changes={
                    'reference': entry.reference,
                    'description': description,
                    'entry_date': str(entry_date),
                    'source_type': source_type,
                    'source_ref': source_ref,
                    'auto_posted': True,
                },
            )
        except Exception:
            pass  # Audit log is non-fatal

        return entry

    @staticmethod
    @transaction.atomic
    def reverse_journal_entry(journal_entry: 'JournalEntry', actor=None) -> 'JournalEntry':
        """
        Create a reversing JournalEntry that mirrors `journal_entry`'s lines with
        debit/credit swapped, netting every account back to its pre-entry balance
        WITHOUT modifying or deleting the original entry/lines (immutable ledger).

        Returns the new reversing JournalEntry.
        """
        from django.utils import timezone as _tz

        original_lines = list(journal_entry.lines.all())
        if not original_lines:
            raise ValueError(f"Journal entry {journal_entry.reference} has no lines to reverse.")

        reversing_entry = JournalEntry.objects.create(
            organisation=journal_entry.organisation,
            description=f"Reversal of {journal_entry.reference}: {journal_entry.description}",
            entry_date=_tz.now().date(),
            reference='',  # auto-assigned in save()
            status='posted',
            created_by=actor,
            source_type='reversal',
            source_ref=str(journal_entry.id),
        )
        for line in original_lines:
            JournalLine.objects.create(
                journal_entry=reversing_entry,
                account=line.account,
                debit=line.credit,   # swapped
                credit=line.debit,   # swapped
                description=f"Reversal: {line.description}" if line.description else "Reversal",
            )

        try:
            from apps.core.models import AuditLog
            AuditLog.log(
                action=AuditLog.CREATE,
                user=actor,
                organisation=journal_entry.organisation,
                model_name='JournalEntry',
                object_id=str(reversing_entry.id),
                object_repr=str(reversing_entry),
                changes={
                    'reference': reversing_entry.reference,
                    'reverses': journal_entry.reference,
                    'reverses_id': str(journal_entry.id),
                },
            )
        except Exception:
            pass  # Audit log is non-fatal

        return reversing_entry

    @staticmethod
    def post_sale_journal(organisation, invoice, user=None):
        """DR Cash/Bank/AR → CR Revenue + VAT; DR COGS → CR Inventory."""
        from apps.sales.models import SalePayment
        zero = Decimal('0')
        total = Decimal(str(invoice.total_amount))
        tax = Decimal(str(invoice.tax_amount or 0))
        revenue = total - tax

        # Determine payment method → which asset account to debit
        payment = SalePayment.objects.filter(invoice=invoice).first()
        ar_acct = AccountMappingService.resolve(organisation, 'accounts_receivable')

        if payment:
            if payment.method == 'cash':
                asset_account = AccountMappingService.resolve(organisation, 'cash_account')
            elif payment.method in ('bank_transfer', 'pos'):
                asset_account = AccountMappingService.resolve(organisation, 'bank_account')
            else:
                asset_account = ar_acct
        else:
            asset_account = ar_acct

        revenue_acct = AccountMappingService.resolve(organisation, 'revenue_account')

        # Partial cash/bank payment: split DR between cash/bank and AR
        paid_amount = Decimal(str(payment.amount)) if payment else zero
        remaining = Decimal(str(invoice.amount_due or 0))
        is_partial_cash = payment and remaining > zero and asset_account.id != ar_acct.id

        if is_partial_cash:
            lines = [
                (asset_account, paid_amount, zero),   # DR Cash/Bank (amount paid)
                (ar_acct, remaining, zero),            # DR AR (remaining balance)
                (revenue_acct, zero, revenue),         # CR Revenue
            ]
        else:
            lines = [
                (asset_account, total, zero),          # DR full amount to asset/AR
                (revenue_acct, zero, revenue),
            ]
        if tax > zero:
            vat_acct = AccountMappingService.resolve(organisation, 'vat_output_account')
            lines.append((vat_acct, zero, tax))

        # COGS
        try:
            cogs_total = sum(
                Decimal(str(item.cost_of_goods or 0))
                for item in invoice.items.all()
            )
            if cogs_total > zero:
                cogs_acct = AccountMappingService.resolve(organisation, 'cogs_account')
                inv_acct = AccountMappingService.resolve(organisation, 'inventory_account')
                lines.append((cogs_acct, cogs_total, zero))
                lines.append((inv_acct, zero, cogs_total))
        except Exception:
            pass

        return AccountingService.post_journal_entry(
            organisation, f"Sale {invoice.invoice_number}", invoice.issue_date,
            lines, user,
            ref=invoice.invoice_number,
            source_type='sale',
            source_ref=str(invoice.id),
        )

    @staticmethod
    def post_credit_payment_journal(organisation, customer, amount: Decimal, user=None, description="", date=None, invoice=None):
        """DR Cash/Bank → CR Accounts Receivable when a credit customer pays."""
        from django.utils import timezone
        zero = Decimal('0')
        amt = Decimal(str(amount))

        # Determine payment account from invoice if available
        cash_acct = AccountMappingService.resolve(organisation, 'cash_account')
        ar_acct = AccountMappingService.resolve(organisation, 'accounts_receivable')

        lines = [
            (cash_acct, amt, zero),   # DR Cash
            (ar_acct, zero, amt),     # CR Accounts Receivable
        ]
        ref_date = date or timezone.now().date()
        source_ref = f"CRPAY-{customer.id}" if not invoice else f"CRPAY-{invoice.id}"
        return AccountingService.post_journal_entry(
            organisation,
            description or f"Credit payment – {customer.name}",
            ref_date,
            lines,
            user,
            ref=f"CRPAY-{customer.code or str(customer.id)[:8]}",
            source_type='credit_payment',
            source_ref=source_ref,
        )

    @staticmethod
    def post_bill_approved_journal(organisation, bill, user=None):
        """
        DR Expense (net) + DR 1500 Fixed Assets (capitalised lines, net) + DR 1400
        Input VAT → CR Accounts Payable (gross).

        Bill lines flagged capitalise=True redirect their VAT-exclusive share from the
        expense account to Fixed Assets (1500) and create a FixedAsset register record
        on approval. The split is proportional to line_total so the entry stays balanced
        regardless of whether line totals are VAT-inclusive or exclusive.
        """
        zero     = Decimal('0')
        total    = Decimal(str(bill.total_amount))
        vat      = Decimal(str(bill.tax_amount or 0))
        net_cost = total - vat

        expense_acct  = AccountMappingService.resolve(organisation, 'general_expense_account')
        ap_acct       = AccountMappingService.resolve(organisation, 'accounts_payable')
        input_vat_acct = AccountingService._get_or_create_account(
            organisation, '1400', 'VAT Receivable (Input VAT)', AccountType.ASSET
        )

        # Split the net cost between capitalised lines (→ 1500) and expenses.
        items = list(bill.items.all())
        capital_items = [it for it in items if getattr(it, 'capitalise', False)]
        all_lines_total = sum((Decimal(str(it.line_total or 0)) for it in items), zero)
        capital_lines_total = sum((Decimal(str(it.line_total or 0)) for it in capital_items), zero)

        fa_acct = AccountingService._get_account_by_code(organisation, '1500') if capital_items else None
        capital_net = zero
        if fa_acct and capital_lines_total > 0 and all_lines_total > 0:
            capital_net = (net_cost * capital_lines_total / all_lines_total).quantize(Decimal('0.01'))
            capital_net = min(capital_net, net_cost)
        expense_net = net_cost - capital_net

        lines = []
        if expense_net > 0:
            lines.append((expense_acct, expense_net, zero))   # DR Expense (VAT-exclusive)
        if capital_net > 0:
            lines.append((fa_acct, capital_net, zero))         # DR Fixed Assets (capitalised)
        if vat > 0:
            lines.append((input_vat_acct, vat, zero))          # DR Input VAT Receivable
        lines.append((ap_acct, zero, total))                   # CR Accounts Payable (gross)

        entry = AccountingService.post_journal_entry(
            organisation, f"Bill approved {bill.bill_number}", bill.issue_date,
            lines, user,
            ref=bill.bill_number,
            source_type='bill_approved',
            source_ref=str(bill.id),
        )

        # Register the FixedAsset(s) for capitalised lines (idempotent; no separate JE).
        if capital_net > 0 and all_lines_total > 0:
            for it in capital_items:
                line_total = Decimal(str(it.line_total or 0))
                if line_total <= 0:
                    continue
                net_share = (net_cost * line_total / all_lines_total).quantize(Decimal('0.01'))
                vat_share = (vat * line_total / all_lines_total).quantize(Decimal('0.01')) if vat > 0 else zero
                CapitalisationService.register_asset_for_bill_line(
                    organisation, bill, it, net_share=net_share, vat_share=vat_share, created_by=user,
                )

        return entry

    @staticmethod
    def post_bill_payment_journal(organisation, bill, payment, user=None):
        """DR Accounts Payable → CR Bank/Cash."""
        zero = Decimal('0')
        amount = Decimal(str(payment.amount))

        ap_acct = AccountMappingService.resolve(organisation, 'accounts_payable')
        if payment.method == 'cash':
            bank_acct = AccountMappingService.resolve(organisation, 'cash_account')
        else:
            bank_acct = AccountMappingService.resolve(organisation, 'bank_account')

        lines = [
            (ap_acct, amount, zero),
            (bank_acct, zero, amount),
        ]
        return AccountingService.post_journal_entry(
            organisation, f"Bill payment {bill.bill_number}", payment.payment_date,
            lines, user,
            ref=f"{bill.bill_number}-PAY",
            source_type='bill_payment',
            source_ref=str(payment.id),
        )

    @staticmethod
    def post_expense_journal(organisation, expense, user=None):
        """DR Expense account → CR Cash/Bank."""
        zero = Decimal('0')
        amount = Decimal(str(expense.amount))

        if expense.is_income:
            # Misc income: DR Cash → CR Other Income
            cash_acct = AccountMappingService.resolve(organisation, 'cash_account')
            revenue_acct = AccountMappingService.resolve(organisation, 'revenue_account')
            lines = [
                (cash_acct, amount, zero),
                (revenue_acct, zero, amount),
            ]
        else:
            expense_acct = AccountMappingService.resolve(organisation, 'general_expense_account')
            if expense.payment_method in ('bank', 'cheque', 'card'):
                payment_acct = AccountMappingService.resolve(organisation, 'bank_account')
            else:
                payment_acct = AccountMappingService.resolve(organisation, 'cash_account')
            lines = [
                (expense_acct, amount, zero),
                (payment_acct, zero, amount),
            ]

        return AccountingService.post_journal_entry(
            organisation, f"Expense: {expense.description[:80]}", expense.expense_date,
            lines, user,
            ref=f"EXP-{expense.id}",
            source_type='expense',
            source_ref=str(expense.id),
        )

    @staticmethod
    def post_payroll_journal(organisation, payroll_run, user=None):
        """
        Balanced payroll GL journal (E1 fix):

        DR Salaries & Wages Expense       = total_gross
        DR Employer Pension Expense        = total_pension_employer
        DR NSITF Expense                   = total_nsitf
        ─────────────────────────────────────────────────────
        CR PAYE Payable                    = total_paye
        CR Pension Payable (emp + empr)    = total_pension_employee + total_pension_employer
        CR NHF Payable                     = total_nhf
        CR NSITF Payable                   = total_nsitf
        CR Bank / Net Pay                  = total_net
        """
        zero            = Decimal('0')
        gross           = Decimal(str(payroll_run.total_gross or 0))
        paye            = Decimal(str(payroll_run.total_paye or 0))
        pension_emp     = Decimal(str(payroll_run.total_pension_employee or 0))
        pension_empr    = Decimal(str(payroll_run.total_pension_employer or 0))
        total_pension   = pension_emp + pension_empr
        nhf             = Decimal(str(payroll_run.total_nhf or 0))
        nsitf           = Decimal(str(payroll_run.total_nsitf or 0))
        net             = Decimal(str(payroll_run.total_net or 0))

        salary_acct  = AccountMappingService.resolve(organisation, 'salary_expense_account')
        paye_acct    = AccountMappingService.resolve(organisation, 'paye_account')
        pension_acct = AccountMappingService.resolve(organisation, 'pension_account')
        bank_acct    = AccountMappingService.resolve(organisation, 'bank_account')

        # Employer-cost accounts (fall back gracefully if not mapped)
        try:
            nsitf_acct = AccountMappingService.resolve(organisation, 'nsitf_account')
        except Exception:
            nsitf_acct = AccountingService._get_or_create_account(
                organisation, '2500', 'NSITF Payable', AccountType.LIABILITY
            )
        try:
            nhf_acct = AccountMappingService.resolve(organisation, 'nhf_account')
        except Exception:
            nhf_acct = AccountingService._get_or_create_account(
                organisation, '2600', 'NHF Payable', AccountType.LIABILITY
            )

        lines = [
            # ── Debit side ──────────────────────────────────────────────────
            (salary_acct,  gross,        zero),    # DR Salaries & Wages (employee cost)
            (salary_acct,  pension_empr, zero),    # DR Employer Pension Expense
            (salary_acct,  nsitf,        zero),    # DR NSITF Expense (employer-borne)
            # ── Credit side ─────────────────────────────────────────────────
            (paye_acct,    zero, paye),            # CR PAYE Payable
            (pension_acct, zero, total_pension),   # CR Pension Payable (employee + employer)
            (bank_acct,    zero, net),             # CR Bank / Net Pay
        ]
        if nhf > zero:
            lines.append((nhf_acct, zero, nhf))   # CR NHF Payable
        if nsitf > zero:
            lines.append((nsitf_acct, zero, nsitf))  # CR NSITF Payable

        return AccountingService.post_journal_entry(
            organisation,
            f"Payroll {payroll_run.period_year}-{payroll_run.period_month:02d}",
            payroll_run.payment_date or payroll_run.created_at.date(),
            lines, user,
            ref=f"PAY-{payroll_run.id}",
            source_type='payroll',
            source_ref=str(payroll_run.id),
        )

    @staticmethod
    def post_deferred_tax_journal(organisation, deferred_item, user=None):
        """
        IAS 12 deferred tax journal.
        DTA (diff < 0): DR Deferred Tax Asset (1600) / CR Income Tax Expense (6700)
        DTL (diff > 0): DR Income Tax Expense (6700) / CR Deferred Tax Liability (2800)
        """
        from django.utils import timezone as tz
        zero = Decimal('0')
        amount = deferred_item.deferred_tax_amount
        if amount <= zero:
            return

        dta_acct = AccountingService._get_or_create_account(organisation, '1600', 'Deferred Tax Asset', AccountType.ASSET)
        dtl_acct = AccountingService._get_or_create_account(organisation, '2800', 'Deferred Tax Liability', AccountType.LIABILITY)
        tax_exp_acct = AccountingService._get_or_create_account(organisation, '6700', 'Other Expenses', AccountType.EXPENSE)

        desc = f"Deferred Tax — {deferred_item.get_category_display()} {deferred_item.tax_year}"
        ref = f"DTX-{deferred_item.id}"

        if deferred_item.deferred_type == 'DTA':
            lines = [
                (dta_acct, amount, zero),       # DR DTA
                (tax_exp_acct, zero, amount),   # CR Income Tax Expense
            ]
        else:  # DTL
            lines = [
                (tax_exp_acct, amount, zero),   # DR Income Tax Expense
                (dtl_acct, zero, amount),       # CR DTL
            ]

        return AccountingService.post_journal_entry(
            organisation, desc, tz.now().date(), lines, user,
            ref=ref, source_type='deferred_tax', source_ref=str(deferred_item.id),
        )

    @staticmethod
    def _get_or_create_account(organisation, code, name, account_type):
        """Get or create a GL account by code for this organisation."""
        acct, _ = Account.objects.get_or_create(
            organisation=organisation, code=code,
            defaults={'name': name, 'account_type': account_type, 'is_active': True},
        )
        return acct

    @staticmethod
    def get_gl_health(organisation) -> dict:
        """Return GL health summary and list of failures for this organisation."""
        from apps.sales.models import Invoice
        from apps.bills.models import Bill
        from apps.expenses.models import Expense
        from apps.payroll.models import PayrollRun

        summary = {'posted': 0, 'failed': 0, 'not_configured': 0, 'pending': 0}
        failures = []

        def _process_model(qs, model_name, ref_field, date_field, amount_field=None):
            for obj in qs:
                status = obj.gl_post_status
                summary[status] = summary.get(status, 0) + 1
                if status in ('failed', 'not_configured'):
                    failures.append({
                        'model': model_name,
                        'id': str(obj.id),
                        'number': getattr(obj, ref_field, ''),
                        'error': obj.gl_post_error,
                        'date': str(getattr(obj, date_field, '')),
                        'amount': str(getattr(obj, amount_field, '')) if amount_field else '',
                    })

        _process_model(
            Invoice.objects.filter(organisation=organisation),
            'invoice', 'invoice_number', 'issue_date', 'total_amount',
        )
        _process_model(
            Bill.objects.filter(organisation=organisation),
            'bill', 'bill_number', 'issue_date', 'total_amount',
        )
        _process_model(
            Expense.objects.filter(organisation=organisation),
            'expense', 'id', 'expense_date', 'amount',
        )
        _process_model(
            PayrollRun.objects.filter(organisation=organisation),
            'payroll', 'run_number', 'created_at',
        )

        return {
            'summary': summary,
            'failures': failures,
            'reconciliations': AccountingService.gl_health_reconciliations(organisation),
        }

    @staticmethod
    def gl_health_reconciliations(organisation) -> dict:
        """Prove the control accounts tie to their subledgers, and surface the
        PRE-PLUG imbalance (the Take-On Suspense balance) that the always-balancing
        balance sheet would otherwise mask. This is the real 'is the ledger broken?'
        check — a green balance sheet can still hide a plugged imbalance here."""
        from apps.customers.models import Customer
        from apps.bills.models import Bill
        zero = Decimal('0')

        suspense = Account.objects.filter(organisation=organisation, code='3900').first()
        suspense_balance = AccountingService._ledger_balance(suspense) if suspense else zero

        def _recon(name, control_acct, subledger_total):
            control = AccountingService._ledger_balance(control_acct) if control_acct else zero
            variance = control - subledger_total
            return {
                'name': name,
                'control': control,
                'subledger': subledger_total,
                'variance': variance,
                'reconciled': abs(variance) < Decimal('0.01'),
            }

        ar_acct = AccountingService._mapped_or_code(organisation, 'accounts_receivable', '1100')
        ap_acct = AccountingService._mapped_or_code(organisation, 'accounts_payable', '2001')
        inv_acct = AccountingService._mapped_or_code(organisation, 'inventory_account', '1200')

        ar_sub = Customer.objects.filter(organisation=organisation).aggregate(
            t=Sum('outstanding_balance'))['t'] or zero
        ap_sub = Bill.objects.filter(organisation=organisation).aggregate(
            t=Sum('amount_due'))['t'] or zero
        try:
            from apps.inventory.services import InventoryService
            inv_sub = sum(
                (getattr(i, 'total_value', zero) or zero)
                for i in InventoryService.get_stock_valuation(organisation)
            ) or zero
        except Exception:
            inv_sub = zero

        subledgers = [
            _recon('Accounts Receivable', ar_acct, Decimal(str(ar_sub))),
            _recon('Accounts Payable', ap_acct, Decimal(str(ap_sub))),
            _recon('Inventory', inv_acct, Decimal(str(inv_sub))),
        ]
        return {
            'pre_plug_imbalance': suspense_balance,   # the real break the auto-plug hides
            'is_balanced': abs(suspense_balance) < Decimal('0.01'),
            'subledgers': subledgers,
            'all_reconciled': (
                all(s['reconciled'] for s in subledgers)
                and abs(suspense_balance) < Decimal('0.01')
            ),
        }

    @staticmethod
    def period_close_checklist(organisation, year=None, month=None) -> dict:
        """Month-end readiness checklist that gates locking a period.

        Reuses GL Health: the ledger must have no failed/unmapped postings, the
        Take-On Suspense must be zero, and every subledger must tie to its control
        account. `ready` is True only when all checks pass.
        """
        health = AccountingService.get_gl_health(organisation)
        recon = health.get('reconciliations', {})
        summary = health.get('summary', {})
        failed = (summary.get('failed', 0) or 0) + (summary.get('not_configured', 0) or 0)

        unreconciled = [s['name'] for s in recon.get('subledgers', []) if not s.get('reconciled')]
        checks = [
            {
                'key': 'no_failed_gl',
                'label': 'No failed or unmapped GL postings',
                'passed': failed == 0,
                'detail': '' if failed == 0 else f'{failed} posting(s) need attention in GL Health.',
            },
            {
                'key': 'suspense_zero',
                'label': 'Take-On Suspense is zero',
                'passed': bool(recon.get('is_balanced', True)),
                'detail': '' if recon.get('is_balanced', True)
                          else f"Suspense balance: {recon.get('pre_plug_imbalance')}",
            },
            {
                'key': 'subledgers_reconciled',
                'label': 'Subledgers tie to their control accounts',
                'passed': bool(recon.get('all_reconciled', True)),
                'detail': '' if not unreconciled else 'Variance in: ' + ', '.join(unreconciled),
            },
        ]
        return {'ready': all(c['passed'] for c in checks), 'checks': checks}

    @staticmethod
    @transaction.atomic
    def close_year(organisation, fiscal_year, created_by=None):
        """Post a year-end closing entry that zeroes the P&L accounts and crystallises
        the net result into Retained Earnings (3100) — IFRS/GAAP year-end close.

        Non-destructive: re-running for the same year reverses the prior close first.
        P&L account balances are computed EXCLUDING any year-end-close entries, so the
        gross operating result is used regardless of prior closes/reversals.

        The P&L *report* reads source documents, so it is unaffected. The balance sheet
        reads the GL, so after closing its 'Current Year Earnings' line drops to zero and
        Retained Earnings rises by the same amount (no double count).
        """
        import uuid
        from datetime import date as _date
        zero = Decimal('0')
        year_end = _date(int(fiscal_year), 12, 31)
        # Unique per-attempt source_ref (post_journal_entry dedupes by exact source_ref,
        # so re-closing must NOT reuse the same ref) + prefix match to find prior closes.
        ref_prefix = f'year-end-close-{fiscal_year}'
        source_ref = f'{ref_prefix}-{uuid.uuid4().hex[:12]}'

        prior = JournalEntry.objects.filter(
            organisation=organisation, source_type='year_end_close',
            source_ref__startswith=ref_prefix, status='posted',
        )
        for e in prior:
            AccountingService.reverse_journal_entry(e, actor=created_by)

        re_acct = AccountingService._get_account_by_code(organisation, '3100')
        if re_acct is None:
            raise ValueError("Retained Earnings account (3100) not found.")

        # Gross operating result must ignore BOTH prior closing entries AND their
        # reversals, so re-closing (which reverses the old close) stays idempotent.
        close_ids = {
            str(i) for i in JournalEntry.objects.filter(
                organisation=organisation, source_type='year_end_close'
            ).values_list('id', flat=True)
        }

        def _gross_balance(acct):
            q = JournalLine.objects.filter(
                journal_entry__organisation=organisation, account=acct,
                journal_entry__status='posted',
                journal_entry__entry_date__lte=year_end,
            ).exclude(journal_entry__source_type='year_end_close').exclude(
                Q(journal_entry__source_type='reversal',
                  journal_entry__source_ref__in=close_ids)
            )
            agg = q.aggregate(d=Sum('debit'), c=Sum('credit'))
            d = agg['d'] or zero
            c = agg['c'] or zero
            return (c - d) if acct.account_type == AccountType.REVENUE else (d - c)

        pl_accounts = Account.objects.filter(
            organisation=organisation, is_active=True,
            account_type__in=[AccountType.REVENUE, AccountType.EXPENSE, AccountType.COST_OF_GOODS],
        )
        lines = []
        net = zero
        for acct in pl_accounts:
            bal = _gross_balance(acct)
            if bal == 0:
                continue
            if acct.account_type == AccountType.REVENUE:
                lines.append((acct, bal, zero))   # DR revenue to zero its credit balance
                net += bal
            else:
                lines.append((acct, zero, bal))   # CR expense/COGS to zero its debit balance
                net -= bal

        if not lines:
            return None

        if net > 0:
            lines.append((re_acct, zero, net))    # profit → CR Retained Earnings
        else:
            lines.append((re_acct, -net, zero))   # loss → DR Retained Earnings

        entry = AccountingService.post_journal_entry(
            organisation, f"Year-end close {fiscal_year}", year_end,
            lines, created_by,
            ref=f'YEC-{fiscal_year}', source_type='year_end_close', source_ref=source_ref,
        )
        return {'entry': entry, 'net_profit': net, 'fiscal_year': int(fiscal_year)}

    @staticmethod
    def retry_gl_post(organisation, model_name: str, object_id: str, user=None):
        """Retry a failed GL post for a given model/id."""
        from .exceptions import GLAccountNotConfigured

        model_name = model_name.lower()
        if model_name == 'invoice':
            from apps.sales.models import Invoice
            obj = Invoice.objects.get(id=object_id, organisation=organisation)
            success, err = safe_post_gl(
                AccountingService.post_sale_journal, organisation, obj, user,
                model_instance=obj,
            )
        elif model_name == 'bill':
            from apps.bills.models import Bill
            obj = Bill.objects.get(id=object_id, organisation=organisation)
            success, err = safe_post_gl(
                AccountingService.post_bill_approved_journal, organisation, obj, user,
                model_instance=obj,
            )
        elif model_name == 'expense':
            from apps.expenses.models import Expense
            obj = Expense.objects.get(id=object_id, organisation=organisation)
            success, err = safe_post_gl(
                AccountingService.post_expense_journal, organisation, obj, user,
                model_instance=obj,
            )
        elif model_name == 'payroll':
            from apps.payroll.models import PayrollRun
            obj = PayrollRun.objects.get(id=object_id, organisation=organisation)
            success, err = safe_post_gl(
                AccountingService.post_payroll_journal, organisation, obj, user,
                model_instance=obj,
            )
        else:
            return False, f"Unknown model: {model_name}"

        return success, err


class CapitalisationService:
    """
    Single writer for fixed-asset ACQUISITION journals.

    Every asset that enters the register on a purchase (direct on the asset form, or
    capitalised from a bill/expense line) posts the currently-missing debit to Fixed
    Assets here — DR 1500 Fixed Assets / CR funding (Bank / Cash / AP / Owner Capital).
    Without this the balance sheet's 1500 stays at 0 while the register shows the cost,
    and the asset's cost is double-expensed. This service closes that gap.

    Assets brought on via the opening-balance / take-on flow do NOT post here — that
    flow posts its own DR 1500 / CR 1510 / CR 3900 take-on entry.

    Idempotency: keyed on (org, source_type='asset_acquisition', source_ref) so a bill
    re-approval or a repeated save never double-posts.
    """

    DEFAULT_THRESHOLD = Decimal('100000')

    # funding_source → AccountMapping role for the credit leg.
    FUNDING_ROLE = {
        FixedAsset.FUND_BANK: 'bank_account',
        FixedAsset.FUND_CASH: 'cash_account',
        FixedAsset.FUND_PAYABLE: 'accounts_payable',
    }

    @staticmethod
    def get_threshold(organisation) -> Decimal:
        """Org-configurable capitalisation threshold; assets below it should be
        expensed, not capitalised. Falls back to the ₦100,000 default."""
        val = getattr(organisation, 'fixed_asset_capitalisation_threshold', None)
        if val is None:
            return CapitalisationService.DEFAULT_THRESHOLD
        try:
            return Decimal(str(val))
        except Exception:
            return CapitalisationService.DEFAULT_THRESHOLD

    @staticmethod
    def should_capitalise(organisation, cost) -> bool:
        """True if `cost` meets/exceeds the org threshold (i.e. capitalise vs expense).
        Used by the bill-line path to decide the tax/book channel."""
        try:
            return Decimal(str(cost or 0)) >= CapitalisationService.get_threshold(organisation)
        except Exception:
            return False

    @staticmethod
    def _fixed_asset_account(organisation, asset=None):
        """The Fixed Assets GL account — the asset's linked account, else its asset
        type's fixed-asset account, else 1500."""
        if asset is not None and asset.account_id:
            return asset.account
        at = getattr(asset, 'asset_type', None) if asset is not None else None
        if at and at.fixed_asset_account_id:
            return at.fixed_asset_account
        return AccountingService._get_account_by_code(organisation, '1500')

    @staticmethod
    def _resolve_funding_account(organisation, funding_source, funding_account=None):
        if funding_account is not None:
            return funding_account
        if funding_source == FixedAsset.FUND_EQUITY:
            # Owner's / Capital Introduced — 3001 Owner Equity.
            return AccountingService._get_or_create_account(
                organisation, '3001', 'Owner Equity', AccountType.EQUITY
            )
        role = CapitalisationService.FUNDING_ROLE.get(funding_source)
        if not role:
            return None
        return AccountMappingService.resolve(organisation, role)

    @staticmethod
    @transaction.atomic
    def post_acquisition(organisation, asset, funding_source=None, funding_account=None,
                         created_by=None, source_type='asset_acquisition', source_ref=None):
        """
        Post DR Fixed Assets (1500) / CR funding for a capitalised asset.

        Returns the JournalEntry, or None when nothing should post (no cost, take-on
        funding, or already posted). Idempotent on source_type+source_ref. Never
        raises for a missing funding/asset account — records the reason on the asset
        (acquisition_error) so it surfaces without blocking asset creation.
        """
        cost = Decimal(str(asset.purchase_cost or 0))
        funding_source = funding_source or asset.funding_source
        source_ref = source_ref or f"asset:{asset.pk}"

        if cost <= 0 or funding_source in (FixedAsset.FUND_NONE, FixedAsset.CAP_OPENING):
            return None
        if asset.acquisition_posted:
            return None

        fa_acct = CapitalisationService._fixed_asset_account(organisation, asset)
        if not fa_acct:
            CapitalisationService._stamp_error(asset, "Fixed Assets account (1500) not found")
            return None
        try:
            credit_acct = CapitalisationService._resolve_funding_account(
                organisation, funding_source, funding_account
            )
        except Exception as e:
            CapitalisationService._stamp_error(asset, f"Funding account not configured: {e}")
            return None
        if credit_acct is None:
            CapitalisationService._stamp_error(asset, f"Unknown funding source '{funding_source}'")
            return None

        entry = AccountingService.post_journal_entry(
            organisation,
            description=f"Asset acquisition — {asset.asset_code} {asset.name}".strip(' —'),
            entry_date=asset.purchase_date,
            lines=[(fa_acct, cost, Decimal('0')), (credit_acct, Decimal('0'), cost)],
            created_by=created_by,
            ref='FA',
            source_type=source_type,
            source_ref=source_ref,
        )
        FixedAsset.objects.filter(pk=asset.pk).update(
            acquisition_posted=True, acquisition_error='', source_document_ref=source_ref,
        )
        asset.acquisition_posted = True
        asset.acquisition_error = ''
        return entry

    @staticmethod
    def _stamp_error(asset, message):
        logger.warning("Asset acquisition post skipped for %s: %s",
                       getattr(asset, 'asset_code', asset.pk), message)
        FixedAsset.objects.filter(pk=asset.pk).update(acquisition_error=message[:500])
        asset.acquisition_error = message[:500]

    @staticmethod
    def _next_asset_code(organisation):
        """Generate the next unique FA-XXXX asset code for this org."""
        import re
        max_n = 0
        for code in FixedAsset.objects.filter(
            organisation=organisation, asset_code__startswith='FA-'
        ).values_list('asset_code', flat=True):
            m = re.search(r'(\d+)$', code or '')
            if m:
                max_n = max(max_n, int(m.group(1)))
        n = max_n + 1
        code = f"FA-{n:04d}"
        while FixedAsset.objects.filter(organisation=organisation, asset_code=code).exists():
            n += 1
            code = f"FA-{n:04d}"
        return code

    @staticmethod
    def register_asset_for_bill_line(organisation, bill, line, net_share=None,
                                     vat_share=None, created_by=None):
        """
        Create (idempotently) the FixedAsset register record for a capitalised bill
        line. Does NOT post a separate acquisition journal — the bill's own approval
        journal carries the DR 1500 (redirected from the expense account), so the
        asset is stamped acquisition_posted=True here.

        net_share is the VAT-exclusive capitalised cost for this line (the amount that
        was debited to 1500); vat_share is its §27(2) input-tax evidence.
        """
        source_ref = f"bill_line:{line.id}"
        existing = FixedAsset.objects.filter(
            organisation=organisation, source_document_ref=source_ref
        ).first()
        if existing:
            return existing

        cost = Decimal(str(net_share if net_share is not None else (line.line_total or 0)))
        raw_cat = (getattr(line, 'asset_category', '') or '').strip()
        valid_cats = {c for c, _ in FixedAsset.CATEGORY_CHOICES}
        category = raw_cat if raw_cat in valid_cats else FixedAsset.OTHER
        vat_amt = Decimal(str(vat_share)) if vat_share else None
        return FixedAsset.objects.create(
            organisation=organisation,
            name=(getattr(line, 'description', '') or 'Capitalised asset')[:200],
            asset_code=CapitalisationService._next_asset_code(organisation),
            category=category,
            purchase_date=bill.issue_date,
            purchase_cost=cost,
            useful_life_years=getattr(line, 'useful_life_years', None) or 5,
            funding_source=FixedAsset.FUND_PAYABLE,
            capitalisation_source=FixedAsset.CAP_BILL,
            source_document_ref=source_ref,
            acquisition_posted=True,   # the bill's approval JE carries the DR 1500
            qualifying_cost=cost,
            input_tax_paid=bool(vat_amt and vat_amt > 0),
            input_tax_amount=vat_amt,
        )

    @staticmethod
    @transaction.atomic
    def set_asset_opening_balance(organisation, asset, accumulated_depreciation=None, created_by=None):
        """
        Take-on an existing (already-owned) asset via the opening-balance flow:

            DR 1500 Fixed Assets        = gross cost
            CR 1510 Accumulated Dep.    = depreciation to date
            CR 3900 Take-On Suspense    = net book value (the plug)

        Seeds one opening DepreciationEntry equal to accumulated-dep-to-date so future
        depreciation runs continue from the correct NBV. Idempotent per asset. Assets
        taken on this way do NOT post a purchase acquisition (funding is 'none').
        """
        from .models import DepreciationEntry
        zero = Decimal('0')
        gross = Decimal(str(asset.purchase_cost or 0))
        accum = Decimal(str(accumulated_depreciation or 0))
        if gross <= 0 or asset.acquisition_posted:
            return None
        accum = max(zero, min(accum, gross))
        nbv = gross - accum

        fa = CapitalisationService._fixed_asset_account(organisation, asset)
        acc_dep = AccountingService._get_account_by_code(organisation, '1510')
        suspense = AccountingService.get_or_create_suspense_account(organisation)
        if not fa or not acc_dep:
            CapitalisationService._stamp_error(
                asset, "Fixed Asset / Accumulated Depreciation account missing"
            )
            return None

        lines = [(fa, gross, zero)]
        if accum > 0:
            lines.append((acc_dep, zero, accum))
        if nbv > 0:
            lines.append((suspense, zero, nbv))

        source_ref = f"asset_takeon:{asset.pk}"
        entry = AccountingService.post_journal_entry(
            organisation,
            description=f"Asset take-on — {asset.asset_code} {asset.name}".strip(' —'),
            entry_date=asset.purchase_date,
            lines=lines,
            created_by=created_by,
            ref='FA-OPEN',
            source_type='asset_takeon',
            source_ref=source_ref,
        )
        if accum > 0:
            DepreciationEntry.objects.get_or_create(
                organisation=organisation, asset=asset,
                period_year=asset.purchase_date.year, period_month=asset.purchase_date.month,
                defaults={
                    'depreciation_amount': accum, 'accumulated_to_date': accum,
                    'net_book_value': nbv,
                },
            )
        FixedAsset.objects.filter(pk=asset.pk).update(
            acquisition_posted=True, acquisition_error='', source_document_ref=source_ref,
            capitalisation_source=FixedAsset.CAP_OPENING, funding_source=FixedAsset.FUND_NONE,
        )
        asset.acquisition_posted = True
        return entry

    @staticmethod
    def gl_reconciliation(organisation, as_of=None):
        """
        Prove the fixed-asset register ties to the general ledger.

        Compares the sub-ledger (asset register + depreciation entries) against the
        posted GL (Fixed Asset + Accumulated Depreciation accounts, read via the
        sub-type taxonomy so multiple such accounts aggregate), reports the variance
        with a zero target, decomposes the Take-On Suspense (3900) balance by source,
        and lists any assets whose acquisition never posted. This is the control that
        makes the ₦94m-class defect visible instead of masking it.
        """
        zero = Decimal('0')
        assets = FixedAsset.objects.filter(
            organisation=organisation, is_active=True, disposal_date__isnull=True
        )
        reg_cost = sum((Decimal(str(a.purchase_cost or 0)) for a in assets), zero)
        reg_accum = DepreciationEntry.objects.filter(
            organisation=organisation, asset__in=assets
        ).aggregate(t=Sum('depreciation_amount'))['t'] or zero
        reg_nbv = reg_cost - reg_accum

        def _sum_accounts(codes, subtype_names):
            accts = Account.objects.filter(organisation=organisation).filter(
                Q(code__in=codes) | Q(sub_type__name__in=subtype_names)
            ).distinct()
            return sum((AccountingService._ledger_balance(a, as_of=as_of) for a in accts), zero)

        gl_cost = _sum_accounts(['1500'], ['Fixed Asset'])
        gl_accum_contra = _sum_accounts(['1510'], ['Accum. Depreciation'])  # negative
        gl_accum_magnitude = -gl_accum_contra
        gl_net = gl_cost + gl_accum_contra

        suspense = Account.objects.filter(organisation=organisation, code='3900').first()
        suspense_balance = AccountingService._ledger_balance(suspense, as_of=as_of) if suspense else zero
        suspense_by_source = []
        if suspense:
            rows = JournalLine.objects.filter(
                journal_entry__organisation=organisation, account=suspense,
                journal_entry__status='posted',
            )
            if as_of:
                rows = rows.filter(journal_entry__entry_date__lte=as_of)
            agg = rows.values('journal_entry__source_type').annotate(d=Sum('debit'), c=Sum('credit'))
            for r in agg:
                bal = (r['c'] or zero) - (r['d'] or zero)  # equity is credit-normal
                if bal != 0:
                    suspense_by_source.append({
                        'source_type': r['journal_entry__source_type'] or '(manual)',
                        'balance': bal,
                    })

        missing = [
            {'id': str(a.id), 'asset_code': a.asset_code, 'name': a.name,
             'cost': a.purchase_cost, 'error': a.acquisition_error}
            for a in assets
            if Decimal(str(a.purchase_cost or 0)) > 0 and not a.acquisition_posted
        ]

        var_cost = reg_cost - gl_cost
        var_accum = reg_accum - gl_accum_magnitude
        var_nbv = reg_nbv - gl_net
        return {
            'register': {'cost': reg_cost, 'accumulated_depreciation': reg_accum, 'net_book_value': reg_nbv},
            'gl': {'cost': gl_cost, 'accumulated_depreciation': gl_accum_magnitude, 'net_book_value': gl_net},
            'variance': {'cost': var_cost, 'accumulated_depreciation': var_accum, 'net_book_value': var_nbv},
            'suspense_balance': suspense_balance,
            'suspense_by_source': suspense_by_source,
            'assets_missing_acquisition': missing,
            'reconciled': abs(var_cost) < Decimal('0.01') and abs(var_nbv) < Decimal('0.01'),
            'as_of': str(as_of) if as_of else None,
        }

    @staticmethod
    def beginning_balances_summary(organisation):
        """Consolidated take-on / opening-balance status for the Beginning Balances page.

        Surfaces the Take-On Suspense (3900) plug prominently: a non-zero balance after
        take-on means the opening balances are incomplete or unbalanced and must be
        cleared before go-live. Control balances resolve through the GL mapping so a
        remapped AR/AP/Inventory account is reflected here too.
        """
        zero = Decimal('0')

        suspense = Account.objects.filter(organisation=organisation, code='3900').first()
        suspense_balance = AccountingService._ledger_balance(suspense) if suspense else zero
        suspense_by_source = []
        if suspense:
            agg = JournalLine.objects.filter(
                journal_entry__organisation=organisation, account=suspense,
                journal_entry__status='posted',
            ).values('journal_entry__source_type').annotate(d=Sum('debit'), c=Sum('credit'))
            for r in agg:
                bal = (r['c'] or zero) - (r['d'] or zero)  # equity is credit-normal
                if bal != 0:
                    suspense_by_source.append({
                        'source_type': r['journal_entry__source_type'] or '(manual)',
                        'balance': bal,
                    })

        # GL accounts carrying an opening balance
        opening_accts = Account.objects.filter(
            organisation=organisation, opening_balance__isnull=False,
        ).exclude(opening_balance=zero)
        accounts_with_opening = opening_accts.count()
        opening_total = sum((Decimal(str(a.opening_balance or 0)) for a in opening_accts), zero)

        # Subledger control accounts (resolve via mapping, fall back to default code)
        ar = AccountingService._mapped_or_code(organisation, 'accounts_receivable', '1100')
        ap = AccountingService._mapped_or_code(organisation, 'accounts_payable', '2001')
        inv = AccountingService._mapped_or_code(organisation, 'inventory_account', '1200')
        controls = {
            'accounts_receivable': AccountingService._ledger_balance(ar) if ar else zero,
            'accounts_payable': AccountingService._ledger_balance(ap) if ap else zero,
            'inventory': AccountingService._ledger_balance(inv) if inv else zero,
        }

        has_takeon = JournalEntry.objects.filter(
            organisation=organisation, source_type='opening_balance', status='posted',
        ).exists()

        is_zero = abs(suspense_balance) < Decimal('0.01')
        return {
            'suspense': {
                'balance': suspense_balance,
                'by_source': suspense_by_source,
                'is_zero': is_zero,
            },
            'accounts_with_opening': accounts_with_opening,
            'opening_total': opening_total,
            'controls': controls,
            'has_takeon': has_takeon,
            'balanced': is_zero,
        }

    @staticmethod
    @transaction.atomic
    def dispose_asset(organisation, asset, proceeds=None, disposal_date=None,
                      proceeds_funding='bank', created_by=None):
        """
        Derecognise a disposed/sold asset (IFRS for SMEs §17.27-30):

            DR Bank/Cash/Receivable     = proceeds
            DR 1510 Accumulated Dep.    = accumulated depreciation (clear the contra)
            CR 1500 Fixed Assets        = original cost
            CR/DR Gain-or-Loss (4200)   = balancing figure (proceeds − NBV)

        Marks the asset disposed and inactive. Idempotent per asset. Book gain/loss
        only — the tax (chargeable-gains) treatment is handled by the gated tax track.
        """
        from django.utils import timezone as _tz
        zero = Decimal('0')
        if asset.disposal_date:
            return None
        disposal_date = AccountingService._coerce_date(disposal_date) if disposal_date else _tz.now().date()
        proceeds = Decimal(str(proceeds or 0))
        gross = Decimal(str(asset.purchase_cost or 0))
        accum = Decimal(str(asset.accumulated_depreciation or 0))
        nbv = gross - accum
        gain = proceeds - nbv

        fa = CapitalisationService._fixed_asset_account(organisation, asset)
        acc_dep = AccountingService._get_account_by_code(organisation, '1510')
        gl_disposal = AccountingService._get_or_create_account(
            organisation, '4200', 'Gain/Loss on Disposal of Assets', AccountType.REVENUE
        )
        if not fa or not acc_dep:
            raise ValueError("Fixed Asset / Accumulated Depreciation account missing")

        lines = []
        if proceeds > 0:
            role = {'cash': 'cash_account', 'receivable': 'accounts_receivable'}.get(
                proceeds_funding, 'bank_account'
            )
            lines.append((AccountMappingService.resolve(organisation, role), proceeds, zero))
        if accum > 0:
            lines.append((acc_dep, accum, zero))     # DR clear accumulated depreciation
        lines.append((fa, zero, gross))              # CR remove cost
        if gain > 0:
            lines.append((gl_disposal, zero, gain))  # CR gain on disposal (income)
        elif gain < 0:
            lines.append((gl_disposal, -gain, zero)) # DR loss on disposal

        entry = AccountingService.post_journal_entry(
            organisation,
            description=f"Asset disposal — {asset.asset_code} {asset.name}".strip(' —'),
            entry_date=disposal_date, lines=lines, created_by=created_by,
            ref='FA-DISP', source_type='asset_disposal', source_ref=f"asset:{asset.pk}",
        )
        FixedAsset.objects.filter(pk=asset.pk).update(
            disposal_date=disposal_date, disposal_amount=proceeds, is_active=False
        )
        asset.disposal_date = disposal_date
        asset.disposal_amount = proceeds
        asset.is_active = False
        return {'entry': entry, 'gain_loss': gain, 'net_book_value': nbv, 'proceeds': proceeds}

    @staticmethod
    @transaction.atomic
    def transfer_asset(organisation, asset, to_location=None, to_cost_centre=None,
                       to_asset_type=None, transfer_date=None, reference='', notes='', created_by=None):
        """Record an asset transfer (location / cost-centre / asset type) and update the
        asset. Pure sub-ledger reclassification — no GL cost/depreciation change.
        Transferring to a new asset type is how the depreciation rules change going
        forward (the type supplies the method and GL accounts)."""
        from django.utils import timezone as _tz
        from .models import AssetTransfer
        transfer_date = (AccountingService._coerce_date(transfer_date)
                         if transfer_date else _tz.now().date())
        xfer = AssetTransfer.objects.create(
            organisation=organisation, asset=asset, transfer_date=transfer_date,
            from_location=asset.location, to_location=to_location,
            from_cost_centre=asset.cost_centre or '', to_cost_centre=to_cost_centre or '',
            from_asset_type=asset.asset_type, to_asset_type=to_asset_type,
            reference=reference or '', notes=notes or '',
        )
        fields = []
        if to_location is not None:
            asset.location = to_location; fields.append('location')
        if to_cost_centre is not None:
            asset.cost_centre = to_cost_centre or ''; fields.append('cost_centre')
        if to_asset_type is not None:
            asset.asset_type = to_asset_type; fields.append('asset_type')
        if fields:
            asset.save(update_fields=fields)
        return xfer

    @staticmethod
    @transaction.atomic
    def revalue_asset(organisation, asset, new_value, revaluation_date=None,
                      reference='', notes='', created_by=None):
        """
        IAS 16 revaluation (elimination method), GATED behind the org flag
        fixed_asset_revaluation_enabled (SME default is the cost model). Upward surplus
        → 3200 Revaluation Surplus (equity); downward deficit → 6800 Revaluation Loss
        (P&L). Restates the asset to the new carrying amount and resets accumulated
        depreciation so future depreciation runs on the revalued amount.

        Deferred tax on the surplus (IAS 12) and the non-taxability of the surplus are
        handled by the gated tax track — not here.
        """
        if not getattr(organisation, 'fixed_asset_revaluation_enabled', False):
            raise ValueError(
                "Revaluation is not enabled for this organisation. The SME default is "
                "the cost model; enabling revaluation requires practitioner sign-off."
            )
        from django.utils import timezone as _tz
        from .models import AssetRevaluation, DepreciationEntry
        zero = Decimal('0')
        revaluation_date = (AccountingService._coerce_date(revaluation_date)
                            if revaluation_date else _tz.now().date())
        new_value = Decimal(str(new_value))
        gross = Decimal(str(asset.purchase_cost or 0))
        accum = Decimal(str(asset.accumulated_depreciation or 0))
        nbv = gross - accum
        surplus = new_value - nbv

        fa = CapitalisationService._fixed_asset_account(organisation, asset)
        acc_dep = AccountingService._get_account_by_code(organisation, '1510')
        surplus_acct = AccountingService._get_or_create_account(
            organisation, '3200', 'Revaluation Surplus', AccountType.EQUITY
        )
        loss_acct = AccountingService._get_or_create_account(
            organisation, '6800', 'Revaluation Loss', AccountType.EXPENSE
        )
        if not fa or not acc_dep:
            raise ValueError("Fixed Asset / Accumulated Depreciation account missing")

        lines = []
        if accum > 0:
            lines.append((acc_dep, accum, zero))   # DR clear the contra
        delta = new_value - gross
        if delta > 0:
            lines.append((fa, delta, zero))
        elif delta < 0:
            lines.append((fa, zero, -delta))
        if surplus > 0:
            lines.append((surplus_acct, zero, surplus))   # CR equity
        elif surplus < 0:
            lines.append((loss_acct, -surplus, zero))      # DR P&L loss

        entry = AccountingService.post_journal_entry(
            organisation,
            description=f"Revaluation — {asset.asset_code} {asset.name}".strip(' —'),
            entry_date=revaluation_date, lines=lines, created_by=created_by,
            ref='FA-REVAL', source_type='asset_revaluation', source_ref=f"asset:{asset.pk}-{revaluation_date}",
        )
        # Restate the register: cost = new carrying amount, accumulated dep reset to 0
        # (elimination) via an offsetting entry so the property nets correctly.
        if accum > 0:
            DepreciationEntry.objects.create(
                organisation=organisation, asset=asset,
                period_year=revaluation_date.year, period_month=revaluation_date.month,
                depreciation_amount=-accum, accumulated_to_date=zero, net_book_value=new_value,
            )
        FixedAsset.objects.filter(pk=asset.pk).update(purchase_cost=new_value)
        asset.purchase_cost = new_value
        AssetRevaluation.objects.create(
            organisation=organisation, asset=asset, revaluation_date=revaluation_date,
            previous_carrying_amount=nbv, new_carrying_amount=new_value, surplus=surplus,
            reference=reference or '', notes=notes or '',
        )
        return {'entry': entry, 'surplus': surplus, 'previous_carrying_amount': nbv,
                'new_carrying_amount': new_value}

    # ── Reports ────────────────────────────────────────────────────────────────
    @staticmethod
    def _asset_figures(asset):
        gross = Decimal(str(asset.purchase_cost or 0))
        accum = Decimal(str(asset.accumulated_depreciation or 0))
        return gross, accum, gross - accum

    @staticmethod
    def asset_register_report(organisation):
        """Full asset register: every active asset with cost / accumulated
        depreciation / NBV, plus totals that tie to GL 1500/1510."""
        zero = Decimal('0')
        rows = []
        tc = ta = tn = zero
        assets = FixedAsset.objects.filter(
            organisation=organisation, is_active=True, disposal_date__isnull=True
        ).select_related('location').order_by('asset_code')
        for a in assets:
            gross, accum, nbv = CapitalisationService._asset_figures(a)
            tc += gross; ta += accum; tn += nbv
            rows.append({
                'id': str(a.id), 'asset_code': a.asset_code, 'name': a.name,
                'category': a.category, 'location': a.location.name if a.location else '',
                'purchase_date': str(a.purchase_date), 'cost': gross,
                'accumulated_depreciation': accum, 'net_book_value': nbv,
                'method': a.depreciation_method,
            })
        return {'rows': rows, 'totals': {'cost': tc, 'accumulated_depreciation': ta, 'net_book_value': tn}}

    @staticmethod
    def assets_by_category(organisation):
        zero = Decimal('0')
        groups = {}
        assets = FixedAsset.objects.filter(
            organisation=organisation, is_active=True, disposal_date__isnull=True
        )
        for a in assets:
            gross, accum, nbv = CapitalisationService._asset_figures(a)
            g = groups.setdefault(a.category or 'other',
                                  {'category': a.category or 'other', 'count': 0,
                                   'cost': zero, 'accumulated_depreciation': zero, 'net_book_value': zero})
            g['count'] += 1; g['cost'] += gross
            g['accumulated_depreciation'] += accum; g['net_book_value'] += nbv
        return {'groups': list(groups.values())}

    @staticmethod
    def assets_by_location(organisation):
        zero = Decimal('0')
        groups = {}
        assets = FixedAsset.objects.filter(
            organisation=organisation, is_active=True, disposal_date__isnull=True
        ).select_related('location')
        for a in assets:
            key = a.location.name if a.location else 'Unassigned'
            gross, accum, nbv = CapitalisationService._asset_figures(a)
            g = groups.setdefault(key, {'location': key, 'count': 0, 'cost': zero,
                                        'accumulated_depreciation': zero, 'net_book_value': zero})
            g['count'] += 1; g['cost'] += gross
            g['accumulated_depreciation'] += accum; g['net_book_value'] += nbv
        return {'groups': list(groups.values())}

    @staticmethod
    def transfer_report(organisation, date_from=None, date_to=None):
        from .models import AssetTransfer
        qs = AssetTransfer.objects.filter(organisation=organisation).select_related(
            'asset', 'from_location', 'to_location'
        )
        if date_from:
            qs = qs.filter(transfer_date__gte=date_from)
        if date_to:
            qs = qs.filter(transfer_date__lte=date_to)
        rows = [{
            'id': str(t.id), 'asset_code': t.asset.asset_code, 'asset_name': t.asset.name,
            'transfer_date': str(t.transfer_date),
            'from_location': t.from_location.name if t.from_location else '',
            'to_location': t.to_location.name if t.to_location else '',
            'from_cost_centre': t.from_cost_centre, 'to_cost_centre': t.to_cost_centre,
            'reference': t.reference,
        } for t in qs.order_by('-transfer_date')]
        return {'rows': rows}

    @staticmethod
    def depreciation_schedule(organisation, asset, forecast=False):
        """Posted depreciation history for an asset, optionally extended with a
        compute-only forward PROJECTION to end of life (never posts, never writes)."""
        zero = Decimal('0')
        actual = [{
            'period': f"{e.period_year}-{e.period_month:02d}", 'type': 'actual',
            'depreciation': e.depreciation_amount, 'accumulated': e.accumulated_to_date,
            'net_book_value': e.net_book_value,
        } for e in asset.ordered_entries]

        projected = []
        if forecast and asset.depreciation_method in (FixedAsset.SL, FixedAsset.RB):
            accum = Decimal(str(asset.accumulated_depreciation or 0))
            gross = Decimal(str(asset.purchase_cost or 0))
            residual = Decimal(str(asset.residual_value or 0))
            # Start from the period after the last actual entry.
            entries = list(asset.ordered_entries)
            if entries:
                y, mo = entries[-1].period_year, entries[-1].period_month
                y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
            else:
                y, mo = asset.purchase_date.year, asset.purchase_date.month
            guard = asset.useful_life_years * 12 + 24
            while guard > 0:
                guard -= 1
                nbv = gross - accum
                remaining = nbv - residual
                if remaining <= Decimal('0.01'):
                    break
                dep = AccountingService._period_depreciation(asset, y, mo, accum, nbv, remaining)
                dep = min(dep, remaining)
                if dep <= 0:
                    break
                accum += dep
                projected.append({
                    'period': f"{y}-{mo:02d}", 'type': 'projected',
                    'depreciation': dep, 'accumulated': accum, 'net_book_value': gross - accum,
                })
                y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
        return {
            'asset_code': asset.asset_code, 'name': asset.name,
            'schedule': actual + projected,
            'disclaimer': 'Projected rows are estimates (management accounts) — not posted to the ledger and not financial/tax advice.',
        }

    @staticmethod
    def disposal_report(organisation, date_from=None, date_to=None):
        """Disposed assets with cost, accumulated depreciation, NBV, proceeds and
        gain/loss on disposal."""
        zero = Decimal('0')
        qs = FixedAsset.objects.filter(organisation=organisation, disposal_date__isnull=False)
        if date_from:
            qs = qs.filter(disposal_date__gte=date_from)
        if date_to:
            qs = qs.filter(disposal_date__lte=date_to)
        rows = []
        total_proceeds = total_nbv = total_gain = zero
        for a in qs.order_by('-disposal_date'):
            gross = Decimal(str(a.purchase_cost or 0))
            accum = Decimal(str(a.accumulated_depreciation or 0))
            nbv = gross - accum
            proceeds = Decimal(str(a.disposal_amount or 0))
            gain = proceeds - nbv
            total_proceeds += proceeds; total_nbv += nbv; total_gain += gain
            rows.append({
                'id': str(a.id), 'asset_code': a.asset_code, 'name': a.name,
                'category': a.category, 'disposal_date': str(a.disposal_date),
                'cost': gross, 'accumulated_depreciation': accum, 'net_book_value': nbv,
                'proceeds': proceeds, 'gain_loss': gain,
            })
        return {
            'rows': rows,
            'totals': {'proceeds': total_proceeds, 'net_book_value': total_nbv, 'gain_loss': total_gain},
        }


class ReconciliationMatchingService:
    """
    Deterministic bank-reconciliation matcher — the reliable, offline, auditable path.

    Matches imported bank-statement lines to posted book journal lines on the
    reconciliation account by EXACT amount (+ direction), within a date tolerance, and
    prefers a reference hit. One-to-one (a book line is used once). Exact amount + same
    date (or a reference match) is auto-confirmed and the bank line marked cleared;
    weaker (still exact-amount) matches are proposed for review. Everything it produces
    is an ordinary AIReconMatch row, so the existing confirm / post-to-GL UI works
    unchanged. No external service, no waiting — the AI pass is reserved only for the
    lines this can't match.
    """

    DATE_TOLERANCE_DAYS = 4

    @staticmethod
    def _book_signed(jl):
        # On an asset/bank account, a debit is money IN, a credit is money OUT — mirror
        # the bank statement's signed amount (positive = inflow/deposit).
        return Decimal(str(jl.debit)) - Decimal(str(jl.credit))

    @staticmethod
    def _desc(jl):
        """Searchable text for a book line — its own note plus the entry description and
        reference (where a payment/invoice reference usually lives)."""
        je = jl.journal_entry
        return ' '.join([
            jl.description or '', je.description or '', je.reference or '',
        ]).lower()

    @staticmethod
    @transaction.atomic
    def deterministic_match(reconciliation, date_tolerance_days=None):
        from datetime import timedelta
        from .models import AIReconMatch, JournalLine

        tol = date_tolerance_days if date_tolerance_days is not None else \
            ReconciliationMatchingService.DATE_TOLERANCE_DAYS
        org = reconciliation.organisation

        # Drop prior unconfirmed proposals so re-running is clean; keep confirmed ones.
        AIReconMatch.objects.filter(reconciliation=reconciliation, status='proposed').delete()

        bank_lines = list(reconciliation.lines.filter(is_cleared=False))
        start = reconciliation.period_start - timedelta(days=tol)
        end = reconciliation.period_end + timedelta(days=tol)
        book = list(
            JournalLine.objects.filter(
                journal_entry__organisation=org, journal_entry__status='posted',
                account=reconciliation.account,
                journal_entry__entry_date__gte=start, journal_entry__entry_date__lte=end,
            ).select_related('journal_entry')
        )
        # Exclude book lines already reconciled in ANY confirmed match for this org — a
        # bank transaction must not be reconciled twice.
        already = set(
            AIReconMatch.objects.filter(
                organisation=org, status='confirmed', book_line__isnull=False
            ).values_list('book_line_id', flat=True)
        )
        book = [jl for jl in book if jl.id not in already]

        summary = {'matched': 0, 'unmatched_bank': 0,
                   'bank_lines': len(bank_lines), 'book_lines': len(book)}
        used = set()

        def _mark_unmatched(bank_line):
            summary['unmatched_bank'] += 1
            # Surface the unmatched line in the UI (mirrors the AI flow) so it never
            # silently reads as "all lines matched".
            AIReconMatch.objects.create(
                organisation=org, reconciliation=reconciliation, bank_line=bank_line,
                book_line=None, confidence=0.0, match_type='uncertain', status='proposed',
                ai_advice='No matching book entry found — record it in the ledger or match manually.',
            )

        for bl in bank_lines:
            b_amt = Decimal(str(bl.amount))
            # Exact signed amount first, then abs amount with the same direction.
            cands = [jl for jl in book if jl.id not in used
                     and ReconciliationMatchingService._book_signed(jl) == b_amt]
            if not cands:
                cands = [jl for jl in book if jl.id not in used
                         and abs(ReconciliationMatchingService._book_signed(jl)) == abs(b_amt)
                         and ((ReconciliationMatchingService._book_signed(jl) >= 0) == (b_amt >= 0))]
            if not cands:
                _mark_unmatched(bl)
                continue

            def _score(jl):
                dd = abs((jl.journal_entry.entry_date - bl.transaction_date).days)
                ref_hit = bool(bl.reference) and bl.reference.lower() in ReconciliationMatchingService._desc(jl)
                return (dd, 0 if ref_hit else 1)

            cands.sort(key=_score)
            best = cands[0]
            dd = abs((best.journal_entry.entry_date - bl.transaction_date).days)
            if dd > tol:
                _mark_unmatched(bl)
                continue

            used.add(best.id)
            ref_hit = bool(bl.reference) and bl.reference.lower() in ReconciliationMatchingService._desc(best)
            if dd == 0 or ref_hit:
                confidence = Decimal('1.0')   # exact amount, same day (or reference hit)
            elif dd <= 1:
                confidence = Decimal('0.97')
            else:
                confidence = Decimal('0.90')

            # Propose for the user to review/confirm — deterministic and auditable, but
            # never silently clears the ledger. Confirming posts it via the existing flow.
            AIReconMatch.objects.create(
                organisation=org, reconciliation=reconciliation, bank_line=bl, book_line=best,
                confidence=float(confidence), match_type='exact', status='proposed',
                ai_reasoning=(
                    f"Exact amount {b_amt}, date diff {dd}d"
                    + (", reference match" if ref_hit else "")
                ),
            )
            summary['matched'] += 1

        return summary
