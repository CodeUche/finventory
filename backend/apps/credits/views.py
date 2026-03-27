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


class CreditTransactionViewSet(TenantFilterMixin, viewsets.ReadOnlyModelViewSet):
    """View credit transaction history per customer."""

    queryset = CreditTransaction.objects.select_related("customer", "invoice")
    serializer_class = CreditTransactionSerializer
    permission_classes = [IsAuthenticated, IsAccountant]
    filterset_fields = ["customer", "transaction_type"]
    ordering_fields = ["created_at", "amount"]

    @action(detail=False, methods=["post"])
    def record_payment(self, request):
        """POST /api/v1/credits/record_payment/ — Record a credit payment from customer."""
        serializer = RecordCreditPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            customer = Customer.objects.get(id=d["customer_id"], organisation=request.organisation)
        except Customer.DoesNotExist:
            return Response({"error": "Customer not found."}, status=404)

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
