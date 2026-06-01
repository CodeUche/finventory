import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import Bill, BillItem, BillPayment

logger = logging.getLogger(__name__)


class BillService:
    @staticmethod
    @transaction.atomic
    def create_bill(validated_data, items_data, organisation, user):
        from apps.accounting.services import AccountingService
        issue_date = validated_data.get('issue_date') or timezone.now().date()
        if AccountingService.is_period_locked(organisation, issue_date):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied(f"The period {issue_date.year}-{issue_date.month:02d} is locked.")

        bill = Bill.objects.create(organisation=organisation, created_by=user, **validated_data)
        subtotal = Decimal('0')
        for item in items_data:
            qty = item['quantity']
            cost = item['unit_cost']
            line = qty * cost
            BillItem.objects.create(
                organisation=organisation,
                bill=bill,
                description=item['description'],
                quantity=qty,
                unit_cost=cost,
                line_total=line,
                expense_category_id=item.get('expense_category_id'),
                account_id=item.get('account_id'),
            )
            subtotal += line
        bill.subtotal = subtotal
        bill.total_amount = subtotal + bill.tax_amount
        bill.amount_due = bill.total_amount
        bill.save()
        return bill

    @staticmethod
    @transaction.atomic
    def record_payment(bill, amount, payment_date, method, reference, notes, user):
        if bill.status == Bill.VOIDED:
            raise ValueError("Cannot pay a voided bill")
        payment = BillPayment.objects.create(
            organisation=bill.organisation,
            bill=bill,
            amount=amount,
            payment_date=payment_date,
            method=method,
            reference=reference,
            notes=notes,
            recorded_by=user,
        )
        bill.amount_paid = (bill.amount_paid or Decimal('0')) + amount
        bill.amount_due = max(Decimal('0'), bill.total_amount - bill.amount_paid)
        if bill.amount_due <= 0:
            bill.status = Bill.PAID
        elif bill.amount_paid > 0:
            bill.status = Bill.PARTIALLY_PAID
        bill.save()

        # Auto-post journal entry (non-blocking)
        from apps.accounting.services import AccountingService, safe_post_gl
        safe_post_gl(
            AccountingService.post_bill_payment_journal, bill.organisation, bill, payment, user,
            model_instance=bill,
        )

        return payment

    @staticmethod
    @transaction.atomic
    def approve_bill(bill, approver):
        if bill.created_by and bill.created_by == approver:
            raise ValueError("You cannot approve a bill you created.")
        bill.status = Bill.APPROVED
        bill.approved_by = approver
        bill.save()

        # Auto-post journal entry (non-blocking)
        from apps.accounting.services import AccountingService, safe_post_gl
        safe_post_gl(
            AccountingService.post_bill_approved_journal, bill.organisation, bill, approver,
            model_instance=bill,
        )

        return bill
