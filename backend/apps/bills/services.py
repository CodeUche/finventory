from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import Bill, BillItem, BillPayment


class BillService:
    @staticmethod
    @transaction.atomic
    def create_bill(validated_data, items_data, organisation, user):
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
        return payment

    @staticmethod
    @transaction.atomic
    def approve_bill(bill, approver):
        bill.status = Bill.APPROVED
        bill.approved_by = approver
        bill.save()
        return bill
