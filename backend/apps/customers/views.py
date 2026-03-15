import django_filters
from datetime import date, datetime
from decimal import Decimal
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import ExportMixin, TenantFilterMixin
from apps.core.permissions import IsStaff
from rest_framework import viewsets

from .models import Customer
from .serializers import CustomerSerializer


class CustomerFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    customer_type = django_filters.ChoiceFilter(choices=Customer.CustomerType.choices)
    is_active = django_filters.BooleanFilter()

    class Meta:
        model = Customer
        fields = ["name", "customer_type", "is_active"]


class CustomerViewSet(ExportMixin, TenantFilterMixin, viewsets.ModelViewSet):
    export_filename = 'customers'
    export_fields = [
        ('Name', 'name'),
        ('Email', 'email'),
        ('Phone', 'phone'),
        ('Type', 'customer_type'),
        ('Credit Limit', 'credit_limit'),
        ('Outstanding Balance', 'outstanding_balance'),
        ('Active', lambda o: 'Yes' if o.is_active else 'No'),
    ]
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    filterset_class = CustomerFilter
    search_fields = ["name", "code", "email", "phone"]
    ordering_fields = ["name", "outstanding_balance", "created_at"]

    @action(detail=True, methods=["get"], url_path="statement")
    def statement(self, request, pk=None):
        """GET /customers/{id}/statement/?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD"""
        customer = self.get_object()

        today = date.today()
        first_of_month = today.replace(day=1)

        def parse_date(val, default):
            try:
                return datetime.strptime(val, "%Y-%m-%d").date() if val else default
            except ValueError:
                return default

        date_from = parse_date(request.query_params.get("date_from"), first_of_month)
        date_to   = parse_date(request.query_params.get("date_to"), today)

        from apps.sales.models import Invoice, SalePayment

        invoices = list(
            Invoice.objects.filter(
                organisation=request.organisation,
                customer=customer,
                issue_date__gte=date_from,
                issue_date__lte=date_to,
            )
            .exclude(status="voided")
            .order_by("issue_date")
            .values(
                "id", "invoice_number", "issue_date", "due_date",
                "status", "total_amount", "amount_paid", "amount_due",
            )
        )

        payments_qs = list(
            SalePayment.objects.filter(
                organisation=request.organisation,
                invoice__customer=customer,
                received_at__date__gte=date_from,
                received_at__date__lte=date_to,
            )
            .order_by("received_at")
            .values("id", "invoice__invoice_number", "amount", "method", "received_at", "reference")
        )

        total_invoiced = sum(Decimal(str(i["total_amount"])) for i in invoices)
        total_paid     = sum(Decimal(str(p["amount"])) for p in payments_qs)

        return Response({
            "customer": CustomerSerializer(customer).data,
            "period_start": date_from,
            "period_end": date_to,
            "invoices": invoices,
            "payments": [
                {
                    "id": p["id"],
                    "invoice_number": p["invoice__invoice_number"],
                    "amount": p["amount"],
                    "method": p["method"],
                    "received_at": p["received_at"],
                    "reference": p["reference"],
                }
                for p in payments_qs
            ],
            "summary": {
                "total_invoiced": total_invoiced,
                "total_paid": total_paid,
                "balance_due": total_invoiced - total_paid,
                "outstanding_balance": customer.outstanding_balance,
            },
        })
