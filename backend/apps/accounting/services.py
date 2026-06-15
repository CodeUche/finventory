import logging
from decimal import Decimal
from django.db import transaction
from django.db.models import F, Sum
from .models import Account, AccountType, JournalEntry, JournalLine, FixedAsset, DepreciationEntry, FinancialPeriod, AccountMapping

logger = logging.getLogger(__name__)


COA_SEED = [
    ('1001', 'Cash in Hand', AccountType.ASSET),
    ('1002', 'Bank Account', AccountType.ASSET),
    ('1100', 'Accounts Receivable', AccountType.ASSET),
    ('1200', 'Inventory', AccountType.ASSET),
    ('1300', 'Prepaid Expenses', AccountType.ASSET),
    ('1500', 'Fixed Assets', AccountType.ASSET),
    ('1510', 'Accumulated Depreciation', AccountType.ASSET),
    ('1600', 'Deferred Tax Asset', AccountType.ASSET),
    ('2001', 'Accounts Payable', AccountType.LIABILITY),
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
    def balance_sheet(organisation, as_of=None):
        """
        Compute a synthetic balance sheet from actual transaction data.
        """
        synthetic = AccountingService._synthetic_account_balances(organisation, as_of=as_of)
        accounts = Account.objects.filter(organisation=organisation, is_active=True)

        assets_data, liabilities_data, equity_data = [], [], []
        for acct in accounts:
            balance = synthetic.get(acct.code, acct.balance)
            row = {'code': acct.code, 'name': acct.name, 'balance': balance}
            if acct.account_type == AccountType.ASSET:
                assets_data.append(row)
            elif acct.account_type == AccountType.LIABILITY:
                liabilities_data.append(row)
            elif acct.account_type == AccountType.EQUITY:
                equity_data.append(row)

        return {
            'assets': assets_data,
            'liabilities': liabilities_data,
            'equity': equity_data,
            'total_assets': sum(r['balance'] for r in assets_data),
            'total_liabilities': sum(r['balance'] for r in liabilities_data),
            'total_equity': sum(r['balance'] for r in equity_data),
        }

    @staticmethod
    def _synthetic_account_balances(organisation, as_of=None) -> dict:
        """Return a dict of {account_code: balance} computed from transaction data."""
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
    @transaction.atomic
    def run_depreciation(organisation, year, month):
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

            if asset.depreciation_method == FixedAsset.SL:
                total_months = asset.useful_life_years * 12
                if total_months <= 0:
                    continue
                monthly_dep = (asset.purchase_cost - asset.residual_value) / total_months
            else:
                if asset.useful_life_years <= 0:
                    continue
                annual_rate = Decimal('1') / asset.useful_life_years
                monthly_dep = current_nbv * annual_rate / 12

            monthly_dep = min(monthly_dep, depreciable_remaining)
            monthly_dep = max(Decimal('0'), monthly_dep)

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
            entries.append(entry)
        return entries

    # ──────────────────────────────────────────────────────────────────────────
    # Auto-posting helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def is_period_locked(organisation, date) -> bool:
        """Return True if the financial period for date is locked."""
        try:
            return FinancialPeriod.objects.filter(
                organisation=organisation,
                year=date.year,
                month=date.month,
                is_locked=True,
            ).exists()
        except Exception:
            return False

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
    ) -> 'JournalEntry':
        """
        Create a balanced double-entry journal entry.

        lines: list of (Account_object, debit: Decimal, credit: Decimal)

        Idempotent: if source_type+source_ref already exists for this org, returns
        the existing JournalEntry without creating a duplicate.

        Raises PeriodLockedError if the entry_date falls in a locked period.
        """
        from .exceptions import PeriodLockedError

        # Period lock check
        if entry_date:
            locked_period = FinancialPeriod.objects.filter(
                organisation=organisation,
                year=entry_date.year,
                month=entry_date.month,
                is_locked=True,
            ).first()
            if locked_period:
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

        with transaction.atomic():
            entry = JournalEntry.objects.create(
                organisation=organisation,
                description=description,
                entry_date=entry_date,
                reference='',  # will be auto-set in save()
                status='posted',
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
        """DR Expense → CR Accounts Payable."""
        zero = Decimal('0')
        total = Decimal(str(bill.total_amount))

        expense_acct = AccountMappingService.resolve(organisation, 'general_expense_account')
        ap_acct = AccountMappingService.resolve(organisation, 'accounts_payable')

        lines = [
            (expense_acct, total, zero),
            (ap_acct, zero, total),
        ]
        return AccountingService.post_journal_entry(
            organisation, f"Bill approved {bill.bill_number}", bill.issue_date,
            lines, user,
            ref=bill.bill_number,
            source_type='bill_approved',
            source_ref=str(bill.id),
        )

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
        """DR Salaries → CR PAYE + Pension + NHF + NSITF + Bank (net pay)."""
        zero = Decimal('0')
        gross = Decimal(str(payroll_run.total_gross or 0))
        paye = Decimal(str(payroll_run.total_paye or 0))
        pension = Decimal(str(payroll_run.total_pension_employee or 0)) + Decimal(str(payroll_run.total_pension_employer or 0))
        nhf = Decimal(str(payroll_run.total_nhf or 0))
        nsitf = Decimal(str(payroll_run.total_nsitf or 0))
        net = Decimal(str(payroll_run.total_net or 0))

        salary_acct = AccountMappingService.resolve(organisation, 'salary_expense_account')
        paye_acct = AccountMappingService.resolve(organisation, 'paye_account')
        pension_acct = AccountMappingService.resolve(organisation, 'pension_account')
        bank_acct = AccountMappingService.resolve(organisation, 'bank_account')

        lines = [
            (salary_acct, gross, zero),    # DR Salaries & Wages
            (paye_acct, zero, paye),       # CR PAYE Payable
            (pension_acct, zero, pension), # CR Pension Payable
            (bank_acct, zero, net),        # CR Bank (net pay out)
        ]
        # NHF and NSITF — use bank account as fallback if wht/other not mapped
        if nhf > zero:
            try:
                nhf_acct = AccountMappingService.resolve(organisation, 'wht_account')
            except Exception:
                nhf_acct = bank_acct
            lines.append((nhf_acct, zero, nhf))
        if nsitf > zero:
            try:
                nsitf_acct = AccountMappingService.resolve(organisation, 'wht_account')
            except Exception:
                nsitf_acct = bank_acct
            lines.append((nsitf_acct, zero, nsitf))

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

        return {'summary': summary, 'failures': failures}

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
