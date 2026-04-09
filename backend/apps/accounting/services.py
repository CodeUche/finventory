import logging
from decimal import Decimal
from django.db import transaction
from django.db.models import F, Sum
from .models import Account, AccountType, JournalEntry, JournalLine, FixedAsset, DepreciationEntry, FinancialPeriod

logger = logging.getLogger(__name__)


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
    def balance_sheet(organisation, as_of=None):
        """
        Compute a synthetic balance sheet from actual transaction data.

        Key accounts (1001, 1002, 1100, 1200, 1500, 1510, 2001, 3100) are
        computed directly from Sales, Bills, Inventory, and Expenses rather
        than requiring manual journal entries.  All other accounts fall back
        to the standard JournalLine balance.

        as_of: optional date — filters transactions up to and including this date.
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
        """
        Return a dict of {account_code: balance} computed from transaction data.

        These override the journal-line balance for accounts that can be derived
        automatically:

        Assets
        ------
        1001  Cash in Hand       — cash sale payments received
        1002  Bank Account       — bank/POS sale payments minus bill payments via bank
        1100  Accounts Receivable — sum of customer outstanding balances
        1200  Inventory           — current stock valuation (qty × cost)
        1500  Fixed Assets        — purchase cost of undisposed active assets
        1510  Accumulated Dep.    — total depreciation taken (contra-asset, negative)

        Liabilities
        -----------
        2001  Accounts Payable    — sum of amount_due on unpaid bills

        Equity
        ------
        3100  Retained Earnings   — all-time net profit (Revenue − COGS − Expenses)
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
            # Subtract cash expenses paid out
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
            ar = (
                Customer.objects.filter(organisation=organisation)
                .aggregate(t=Sum('outstanding_balance'))['t'] or zero
            )
            balances['1100'] = ar
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

        # Land never depreciates; only assets placed in service on or before period end
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
            # Skip if already processed for this period
            if any(
                e.period_year == year and e.period_month == month
                for e in asset.depreciation_entries.all()
            ):
                continue

            # Use prefetched entries to compute accumulated / NBV without extra queries
            accumulated_so_far = sum(
                e.depreciation_amount for e in asset.depreciation_entries.all()
            ) or Decimal('0')
            current_nbv = asset.purchase_cost - accumulated_so_far
            depreciable_remaining = current_nbv - asset.residual_value

            # Skip if fully depreciated (NBV already at or below residual value)
            if depreciable_remaining <= Decimal('0'):
                continue

            if asset.depreciation_method == FixedAsset.SL:
                # Straight-line: spread (cost − residual) evenly over useful life
                total_months = asset.useful_life_years * 12
                if total_months <= 0:
                    continue
                monthly_dep = (asset.purchase_cost - asset.residual_value) / total_months
            else:
                # Reducing balance: apply annual rate to current NBV, monthly fraction
                if asset.useful_life_years <= 0:
                    continue
                annual_rate = Decimal('1') / asset.useful_life_years
                monthly_dep = current_nbv * annual_rate / 12

            # Never depreciate below residual value
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
    def post_journal_entry(organisation, description, entry_date, lines, created_by=None, ref='AUTO'):
        """
        Create a balanced double-entry journal entry from a list of line tuples.

        lines: iterable of (account_code: str, debit: Decimal, credit: Decimal)

        Silently skips if no chart of accounts is seeded.  Never re-raises.
        """
        try:
            if not Account.objects.filter(organisation=organisation).exists():
                logger.error(
                    "AUTO-POST SKIPPED: org %s (%s) has no chart of accounts. "
                    "Run: python manage.py reseed_coa --org %s",
                    organisation.id, getattr(organisation, 'name', '?'), organisation.id,
                )
                # Auto-heal: seed on the fly so future posts work
                try:
                    AccountingService.seed_chart_of_accounts(organisation)
                    logger.info("Auto-healed COA for org %s", organisation.id)
                except Exception as heal_exc:
                    logger.error("COA auto-heal failed for org %s: %s", organisation.id, heal_exc)
                    return
            with transaction.atomic():
                entry = JournalEntry.objects.create(
                    organisation=organisation,
                    description=description,
                    entry_date=entry_date,
                    reference=f"AUTO-{ref}",
                    status='posted',
                    created_by=created_by,
                )
                for code, debit, credit in lines:
                    try:
                        account = Account.objects.get(organisation=organisation, code=code)
                    except Account.DoesNotExist:
                        continue
                    JournalLine.objects.create(
                        organisation=organisation,
                        journal_entry=entry,
                        account=account,
                        debit=Decimal(str(debit)),
                        credit=Decimal(str(credit)),
                    )
        except Exception as exc:
            logger.warning("Auto-journal posting failed (%s): %s", ref, exc)

    @staticmethod
    def post_sale_journal(organisation, invoice, user=None):
        """DR Cash/Bank/AR → CR Revenue + VAT; DR COGS → CR Inventory."""
        try:
            from apps.sales.models import SalePayment
            zero = Decimal('0')
            total = Decimal(str(invoice.total_amount))
            tax = Decimal(str(invoice.tax_amount or 0))
            revenue = total - tax

            # Determine payment method → which asset account to debit
            payment = SalePayment.objects.filter(invoice=invoice).first()
            if payment:
                if payment.method == 'cash':
                    asset_code = '1001'
                elif payment.method in ('bank_transfer', 'pos'):
                    asset_code = '1002'
                else:
                    asset_code = '1100'  # Receivable for other methods
            else:
                asset_code = '1100'  # Unpaid → AR

            lines = [
                (asset_code, total, zero),
                ('4001', zero, revenue),
            ]
            if tax > zero:
                lines.append(('2100', zero, tax))

            # COGS
            try:
                cogs_total = sum(
                    Decimal(str(item.cost_of_goods or 0))
                    for item in invoice.items.all()
                )
                if cogs_total > zero:
                    lines.append(('5001', cogs_total, zero))
                    lines.append(('1200', zero, cogs_total))
            except Exception:
                pass

            AccountingService.post_journal_entry(
                organisation, f"Sale {invoice.invoice_number}", invoice.issue_date,
                lines, user, ref=invoice.invoice_number,
            )
        except Exception as exc:
            logger.warning("post_sale_journal failed: %s", exc)

    @staticmethod
    def post_credit_payment_journal(organisation, customer, amount: Decimal, user=None, description="", date=None):
        """DR Cash (1001) → CR Accounts Receivable (1100) when a credit customer pays."""
        try:
            from django.utils import timezone
            zero = Decimal('0')
            amt = Decimal(str(amount))
            lines = [
                ('1001', amt, zero),   # DR Cash
                ('1100', zero, amt),   # CR Accounts Receivable
            ]
            ref_date = date or timezone.now().date()
            AccountingService.post_journal_entry(
                organisation,
                description or f"Credit payment – {customer.name}",
                ref_date,
                lines,
                user,
                ref=f"CRPAY-{customer.code or str(customer.id)[:8]}",
            )
        except Exception as exc:
            logger.warning("post_credit_payment_journal failed: %s", exc)

    @staticmethod
    def post_bill_approved_journal(organisation, bill, user=None):
        """DR Expense → CR Accounts Payable."""
        try:
            zero = Decimal('0')
            total = Decimal(str(bill.total_amount))
            lines = [
                ('6700', total, zero),
                ('2001', zero, total),
            ]
            AccountingService.post_journal_entry(
                organisation, f"Bill approved {bill.bill_number}", bill.issue_date,
                lines, user, ref=bill.bill_number,
            )
        except Exception as exc:
            logger.warning("post_bill_approved_journal failed: %s", exc)

    @staticmethod
    def post_bill_payment_journal(organisation, bill, payment, user=None):
        """DR Accounts Payable → CR Bank/Cash."""
        try:
            zero = Decimal('0')
            amount = Decimal(str(payment.amount))
            cash_methods = ('cash',)
            bank_code = '1001' if payment.method in cash_methods else '1002'
            lines = [
                ('2001', amount, zero),
                (bank_code, zero, amount),
            ]
            AccountingService.post_journal_entry(
                organisation, f"Bill payment {bill.bill_number}", payment.payment_date,
                lines, user, ref=f"{bill.bill_number}-PAY",
            )
        except Exception as exc:
            logger.warning("post_bill_payment_journal failed: %s", exc)

    @staticmethod
    def post_expense_journal(organisation, expense, user=None):
        """DR Expense account → CR Cash/Bank."""
        try:
            zero = Decimal('0')
            amount = Decimal(str(expense.amount))
            if expense.is_income:
                # Misc income: DR Cash → CR Other Income
                lines = [
                    ('1001', amount, zero),
                    ('4100', zero, amount),
                ]
            else:
                lines = [
                    ('6700', amount, zero),
                    ('1001', zero, amount),
                ]
            AccountingService.post_journal_entry(
                organisation, f"Expense: {expense.description[:80]}", expense.expense_date,
                lines, user, ref=f"EXP-{expense.id}",
            )
        except Exception as exc:
            logger.warning("post_expense_journal failed: %s", exc)

    @staticmethod
    def post_payroll_journal(organisation, payroll_run, user=None):
        """DR Salaries → CR PAYE + Pension + NHF + NSITF + Bank (net pay)."""
        try:
            zero = Decimal('0')
            gross = Decimal(str(payroll_run.total_gross or 0))
            paye = Decimal(str(payroll_run.total_paye or 0))
            pension = Decimal(str(payroll_run.total_pension_employee or 0)) + Decimal(str(payroll_run.total_pension_employer or 0))
            nhf = Decimal(str(payroll_run.total_nhf or 0))
            nsitf = Decimal(str(payroll_run.total_nsitf or 0))
            net = Decimal(str(payroll_run.total_net or 0))

            lines = [
                ('6001', gross, zero),      # DR Salaries & Wages
                ('2200', zero, paye),       # CR PAYE Payable
                ('2300', zero, pension),    # CR Pension Payable
                ('2600', zero, nhf),        # CR NHF Payable
                ('2500', zero, nsitf),      # CR NSITF Payable
                ('1002', zero, net),        # CR Bank (net pay out)
            ]
            AccountingService.post_journal_entry(
                organisation,
                f"Payroll {payroll_run.period_year}-{payroll_run.period_month:02d}",
                payroll_run.payment_date or payroll_run.created_at.date(),
                lines, user, ref=f"PAY-{payroll_run.id}",
            )
        except Exception as exc:
            logger.warning("post_payroll_journal failed: %s", exc)
