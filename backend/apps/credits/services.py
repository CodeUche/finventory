"""Credit management service."""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import CreditTransaction

logger = logging.getLogger(__name__)


class CreditService:

    @staticmethod
    @transaction.atomic
    def record_credit_debit(organisation, customer, amount: Decimal, invoice=None, due_date=None, recorded_by=None, description="") -> CreditTransaction:
        """Record a new credit sale (customer owes money)."""
        new_balance = customer.outstanding_balance + amount
        txn = CreditTransaction.objects.create(
            organisation=organisation,
            customer=customer,
            invoice=invoice,
            transaction_type=CreditTransaction.TransactionType.DEBIT,
            amount=amount,
            balance_after=new_balance,
            due_date=due_date,
            description=description or f"Credit sale",
            recorded_by=recorded_by,
        )
        customer.outstanding_balance = new_balance
        customer.save(update_fields=["outstanding_balance", "updated_at"])
        return txn

    @staticmethod
    @transaction.atomic
    def record_payment(organisation, customer, amount: Decimal, recorded_by, description="", due_date=None) -> CreditTransaction:
        """Record a credit payment (reduces outstanding balance) and post GL entry."""
        new_balance = max(customer.outstanding_balance - amount, Decimal("0"))
        txn = CreditTransaction.objects.create(
            organisation=organisation,
            customer=customer,
            transaction_type=CreditTransaction.TransactionType.CREDIT,
            amount=amount,
            balance_after=new_balance,
            due_date=due_date,
            description=description or f"Payment received – {customer.name}",
            recorded_by=recorded_by,
        )
        customer.outstanding_balance = new_balance
        customer.save(update_fields=["outstanding_balance", "updated_at"])

        # Post GL: DR 1001 Cash → CR 1100 Accounts Receivable
        try:
            from apps.accounting.services import AccountingService
            from django.utils import timezone
            AccountingService.post_credit_payment_journal(
                organisation, customer, amount, recorded_by,
                txn.description, timezone.now().date(),
            )
        except Exception as exc:
            logger.warning("post_credit_payment_journal failed for %s: %s", customer.name, exc)

        try:
            from apps.core.models import AuditLog
            AuditLog.log(
                action=AuditLog.CREATE,
                user=recorded_by,
                organisation=organisation,
                model_name='CreditTransaction',
                object_id=str(txn.id),
                object_repr=str(txn),
                changes={
                    'amount': {'old': None, 'new': str(amount)},
                    'payment_mode': {'old': None, 'new': getattr(txn, 'payment_mode', '') or ''},
                    'customer': {'old': None, 'new': customer.name},
                },
            )
        except Exception:
            pass

        return txn

    @staticmethod
    def get_aging_report(organisation) -> list[dict]:
        """
        Generate accounts receivable aging report.

        Buckets: Current (0-30d), 31-60d, 61-90d, >90d overdue.
        """
        from apps.customers.models import Customer

        today = timezone.now().date()
        customers = Customer.objects.filter(
            organisation=organisation,
            outstanding_balance__gt=0,
        )

        report = []
        for customer in customers:
            # Get unpaid debit transactions
            debits = CreditTransaction.objects.filter(
                organisation=organisation,
                customer=customer,
                transaction_type=CreditTransaction.TransactionType.DEBIT,
            )

            buckets = {"current": 0, "30_60": 0, "61_90": 0, "over_90": 0}
            for debit in debits:
                if not debit.due_date:
                    buckets["current"] += debit.amount
                    continue
                days_overdue = (today - debit.due_date).days
                if days_overdue <= 30:
                    buckets["current"] += debit.amount
                elif days_overdue <= 60:
                    buckets["30_60"] += debit.amount
                elif days_overdue <= 90:
                    buckets["61_90"] += debit.amount
                else:
                    buckets["over_90"] += debit.amount

            report.append({
                "customer_id": str(customer.id),
                "customer_name": customer.name,
                "customer_code": customer.code,
                "outstanding_balance": customer.outstanding_balance,
                **buckets,
            })

        return sorted(report, key=lambda x: x["outstanding_balance"], reverse=True)
