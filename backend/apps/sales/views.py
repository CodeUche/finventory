"""Sales ViewSets."""

import django_filters
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsStaff
from apps.customers.models import Customer
from apps.inventory.models import Product, Warehouse

from .models import Invoice, RecurringInvoice
from .serializers import (
    CreateSaleSerializer,
    InvoiceSerializer,
    RecordPaymentSerializer,
    SalePaymentSerializer,
    RecurringInvoiceSerializer,
)
from .services import SaleService


class InvoiceFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=Invoice.Status.choices)
    customer = django_filters.UUIDFilter()
    date_from = django_filters.DateFilter(field_name="issue_date", lookup_expr="gte")
    date_to = django_filters.DateFilter(field_name="issue_date", lookup_expr="lte")
    min_amount = django_filters.NumberFilter(field_name="total_amount", lookup_expr="gte")
    max_amount = django_filters.NumberFilter(field_name="total_amount", lookup_expr="lte")

    class Meta:
        model = Invoice
        fields = ["status", "customer", "payment_method"]


class InvoiceViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """
    Sales invoice management.

    POST /sales/invoices/ — Create a new sale (triggers stock deduction)
    POST /sales/invoices/{id}/pay/ — Record a payment
    POST /sales/invoices/{id}/void/ — Void an invoice
    """

    queryset = Invoice.objects.select_related("customer", "warehouse").prefetch_related(
        "items__product", "payments"
    )
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    filterset_class = InvoiceFilter
    search_fields = ["invoice_number", "customer__name"]
    ordering_fields = ["issue_date", "total_amount", "status"]

    def create(self, request, *args, **kwargs):
        """Create a confirmed sale invoice."""
        serializer = CreateSaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            warehouse = Warehouse.objects.get(
                id=d["warehouse_id"], organisation=request.organisation
            )
            customer = None
            if d.get("customer_id"):
                customer = Customer.objects.get(
                    id=d["customer_id"], organisation=request.organisation
                )

            invoice = SaleService.create_sale(
                organisation=request.organisation,
                created_by=request.user,
                customer=customer,
                warehouse=warehouse,
                items=d["items"],
                payment_method=d["payment_method"],
                notes=d.get("notes", ""),
                issue_date=d.get("issue_date"),
                due_date=d.get("due_date"),
            )
            return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)

        except (Warehouse.DoesNotExist, Customer.DoesNotExist) as e:
            return Response({"error": str(e)}, status=404)
        except Product.DoesNotExist as e:
            return Response({"error": f"Product not found: {e}"}, status=422)
        except ValueError as e:
            return Response({"error": str(e)}, status=422)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        """POST /api/v1/sales/invoices/{id}/pay/ — Record a payment."""
        invoice = self.get_object()
        serializer = RecordPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            payment = SaleService.record_payment(
                invoice=invoice,
                amount=d["amount"],
                method=d["method"],
                reference=d.get("reference", ""),
                received_by=request.user,
            )
            return Response(SalePaymentSerializer(payment).data, status=201)
        except ValueError as e:
            return Response({"error": str(e)}, status=422)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def void(self, request, pk=None):
        """POST /api/v1/sales/invoices/{id}/void/"""
        invoice = self.get_object()
        try:
            invoice = SaleService.void_invoice(invoice, voided_by=request.user)
            return Response(InvoiceSerializer(invoice).data)
        except ValueError as e:
            return Response({"error": str(e)}, status=422)


class RecurringInvoiceViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Manage recurring invoice templates."""

    serializer_class = RecurringInvoiceSerializer
    permission_classes = [IsAuthenticated, IsStaff]

    def get_queryset(self):
        org = self._get_organisation()
        return RecurringInvoice.objects.filter(organisation=org).select_related('customer', 'warehouse')

    def perform_create(self, serializer):
        org = self._get_organisation()
        serializer.save(organisation=org, created_by=self.request.user)
