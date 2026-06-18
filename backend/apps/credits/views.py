import logging

from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsAccountant
from apps.customers.models import Customer

from .models import CreditTransaction
from .serializers import CreditTransactionSerializer, RecordCreditPaymentSerializer
from .services import CreditService

logger = logging.getLogger(__name__)


class CreditTransactionViewSet(TenantFilterMixin, viewsets.ReadOnlyModelViewSet):
    """View credit transaction history per customer."""

    queryset = CreditTransaction.objects.select_related("customer", "invoice")
    serializer_class = CreditTransactionSerializer
    permission_classes = [IsAuthenticated, IsAccountant]
    filterset_fields = ["customer", "transaction_type"]
    ordering_fields = ["created_at", "amount"]

    @action(detail=False, methods=["post"])
    def record_payment(self, request):
        """POST /api/v1/credits/record_payment/ — Record a credit payment from customer.

        If `invoice` is provided, this also creates a matching SalePayment on
        that invoice (via SaleService.record_payment, which itself calls
        CreditService.record_payment for credit invoices) so the credit
        ledger and the invoice's payment history never drift apart.
        """
        serializer = RecordCreditPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            customer = Customer.objects.get(id=d["customer_id"], organisation=request.organisation)
        except Customer.DoesNotExist:
            return Response({"error": "Customer not found."}, status=404)

        invoice_id = d.get("invoice")

        with transaction.atomic():
            if invoice_id:
                from apps.sales.models import Invoice
                from apps.sales.services import SaleService

                try:
                    invoice = Invoice.objects.get(id=invoice_id, organisation=request.organisation)
                except Invoice.DoesNotExist:
                    return Response({"error": "Invoice not found."}, status=404)

                payment_number = CreditTransaction.generate_payment_number(request.organisation)
                payment_mode = d.get("payment_mode") or CreditTransaction.PaymentMode.CREDIT_APPLIED
                # SalePayment.Method has no "other" choice — map it to the closest
                # valid value so the FK side stays within its declared choices.
                from apps.sales.models import SalePayment as _SalePayment
                valid_methods = {c[0] for c in _SalePayment.Method.choices}
                method = payment_mode if payment_mode in valid_methods else _SalePayment.Method.CASH
                reference = d.get("reference") or payment_number

                try:
                    # Creates the SalePayment + updates Invoice.amount_paid/amount_due/status,
                    # and (for credit invoices) internally calls CreditService.record_payment
                    # which creates the CreditTransaction + updates Customer.outstanding_balance.
                    SaleService.record_payment(
                        invoice=invoice,
                        amount=d["amount"],
                        method=method,
                        received_by=request.user,
                        reference=reference,
                    )
                except ValueError as exc:
                    return Response({"error": str(exc)}, status=422)

                # Fetch the CreditTransaction that SaleService.record_payment just created
                # (via CreditService.record_payment) so we can stamp it with the extra
                # payment-receipt detail captured on this request.
                txn = CreditTransaction.objects.filter(
                    organisation=request.organisation,
                    customer=customer,
                    invoice=invoice,
                    transaction_type=CreditTransaction.TransactionType.CREDIT,
                ).order_by("-created_at").first()

                if txn is None:
                    # Invoice wasn't a credit invoice (no automatic CreditService call) —
                    # fall back to recording the credit ledger entry directly so the
                    # customer's outstanding balance still reflects this payment.
                    txn = CreditService.record_payment(
                        organisation=request.organisation,
                        customer=customer,
                        amount=d["amount"],
                        recorded_by=request.user,
                        description=d.get("description", ""),
                        due_date=d.get("due_date"),
                    )
                    txn.invoice = invoice

                txn.payment_number = payment_number
                txn.payment_mode = d.get("payment_mode", "")
                txn.bank_name = d.get("bank_name", "")
                txn.bank_code = d.get("bank_code", "")
                txn.account_number = d.get("account_number", "")
                txn.account_name = d.get("account_name", "")

                update_fields = [
                    "invoice", "payment_number", "payment_mode", "bank_name",
                    "bank_code", "account_number", "account_name",
                ]

                # Optional manual GL posting — only if both accounts are supplied and a
                # generic manual-entry helper exists. AccountingService currently only
                # exposes domain-specific post_*_journal helpers (sale/bill/expense/
                # payroll/credit_payment), no generic post_manual_entry, so we leave this
                # unwired rather than invent a new journal-posting path (out of scope).
                debit_account_id = d.get("debit_account_id")
                credit_account_id = d.get("credit_account_id")
                if debit_account_id and credit_account_id:
                    from apps.accounting.models import Account
                    try:
                        txn.debit_account = Account.objects.get(id=debit_account_id, organisation=request.organisation)
                        txn.credit_account = Account.objects.get(id=credit_account_id, organisation=request.organisation)
                        update_fields += ["debit_account", "credit_account"]
                    except Account.DoesNotExist:
                        logger.warning("record_payment: debit/credit account not found for org %s", request.organisation_id)

                location_id = d.get("location_id")
                if location_id:
                    from apps.inventory.models import Warehouse
                    try:
                        txn.location = Warehouse.objects.get(id=location_id, organisation=request.organisation)
                        update_fields.append("location")
                    except Warehouse.DoesNotExist:
                        logger.warning("record_payment: location not found for org %s", request.organisation_id)

                txn.save(update_fields=update_fields)
            else:
                txn = CreditService.record_payment(
                    organisation=request.organisation,
                    customer=customer,
                    amount=d["amount"],
                    recorded_by=request.user,
                    description=d.get("description", ""),
                    due_date=d.get("due_date"),
                )

        return Response(CreditTransactionSerializer(txn).data, status=201)

    @action(detail=False, methods=["get"])
    def aging_report(self, request):
        """GET /api/v1/credits/aging_report/ — Accounts receivable aging."""
        report = CreditService.get_aging_report(request.organisation)
        return Response(report)
