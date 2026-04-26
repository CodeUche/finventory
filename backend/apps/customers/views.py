import django_filters
from datetime import date, datetime
from decimal import Decimal
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import ExportMixin, TenantFilterMixin
from apps.core.permissions import IsStaff
from rest_framework import viewsets

from .models import Customer, CustomerDebit
from .serializers import CustomerSerializer, CustomerDebitSerializer


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

    def create(self, request, *args, **kwargs):
        from django.db import IntegrityError, transaction
        from apps.subscriptions.services import SubscriptionService
        from apps.tenancy.models import Organisation
        org = self._get_organisation()
        try:
            with transaction.atomic():
                Organisation.objects.select_for_update().get(pk=org.pk)
                count = Customer.objects.filter(organisation=org).count()
                err = SubscriptionService.get_write_limit_error(org, "max_customers", count)
                if err:
                    return Response({"error": err, "upgrade_required": True}, status=402)
                return super().create(request, *args, **kwargs)
        except IntegrityError:
            return Response({"error": "A customer with this code already exists."}, status=400)

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

        from apps.sales.models import Invoice, SalePayment, SaleItem

        invoice_qs = (
            Invoice.objects.filter(
                organisation=request.organisation,
                customer=customer,
                issue_date__gte=date_from,
                issue_date__lte=date_to,
            )
            .exclude(status="voided")
            .order_by("issue_date")
            .select_related("created_by")
            .prefetch_related("items__product")
        )

        invoices = []
        for inv in invoice_qs:
            items = [
                {
                    "product": item.product.name,
                    "qty": str(item.quantity),
                    "unit_cost": str(item.unit_price),
                    "discount_percent": str(item.discount_percent),
                    "discount_amount": str(item.discount_amount),
                    "tax_amount": str(item.tax_amount),
                    "line_total": str(item.line_total),
                }
                for item in inv.items.all()
            ]
            # Use Invoice.sold_by field directly (set at sale creation time, may differ from created_by)
            sold_by = inv.sold_by or (
                f"{inv.created_by.first_name} {inv.created_by.last_name}".strip()
                if inv.created_by else ""
            )
            invoices.append({
                "id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "issue_date": inv.issue_date,
                "due_date": inv.due_date,
                "status": inv.status,
                "total_amount": str(inv.total_amount),
                "discount_amount": str(inv.discount_amount),
                "tax_amount": str(inv.tax_amount),
                "amount_paid": str(inv.amount_paid),
                "amount_due": str(inv.amount_due),
                "sold_by": sold_by,
                "items": items,
            })

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

        debits_qs = list(
            CustomerDebit.objects.filter(
                organisation=request.organisation,
                customer=customer,
                debit_date__gte=date_from,
                debit_date__lte=date_to,
            )
            .order_by("debit_date")
            .values("id", "amount", "reference", "description", "debit_date")
        )

        total_invoiced   = sum(Decimal(str(i["total_amount"])) for i in invoices)
        total_discounts  = sum(Decimal(str(i["discount_amount"])) for i in invoices)
        total_tax        = sum(Decimal(str(i["tax_amount"])) for i in invoices)
        total_debits     = sum(Decimal(str(d["amount"])) for d in debits_qs)
        total_paid       = sum(Decimal(str(p["amount"])) for p in payments_qs)

        # Payment breakdown by method
        payments_list = [
            {
                "id": str(p["id"]),
                "invoice_number": p["invoice__invoice_number"],
                "amount": str(p["amount"]),
                "method": p["method"],
                "received_at": p["received_at"],
                "reference": p["reference"],
            }
            for p in payments_qs
        ]
        payment_by_method: dict = {}
        for p in payments_list:
            m = p["method"].replace("_", " ").title()
            payment_by_method[m] = str(
                Decimal(payment_by_method.get(m, "0")) + Decimal(p["amount"])
            )

        # Returns / credit notes in the period
        from apps.sales.models import SaleReturn
        returns_qs = list(
            SaleReturn.objects.filter(
                organisation=request.organisation,
                invoice__customer=customer,
                created_at__date__gte=date_from,
                created_at__date__lte=date_to,
            )
            .order_by("created_at")
            .values("id", "invoice__invoice_number", "total_refund", "reason", "created_at")
        )
        total_returns = sum(Decimal(str(r["total_refund"])) for r in returns_qs)

        return Response({
            "customer": CustomerSerializer(customer).data,
            "period_start": date_from,
            "period_end": date_to,
            "invoices": invoices,
            "payments": payments_list,
            "debits": [
                {
                    "id": str(d["id"]),
                    "amount": str(d["amount"]),
                    "reference": d["reference"],
                    "description": d["description"],
                    "debit_date": str(d["debit_date"]),
                }
                for d in debits_qs
            ],
            "returns": [
                {
                    "id": str(r["id"]),
                    "invoice_number": r["invoice__invoice_number"],
                    "amount": str(r["total_refund"]),
                    "reason": r["reason"] or "",
                    "created_at": r["created_at"],
                }
                for r in returns_qs
            ],
            "summary": {
                "total_invoiced": str(total_invoiced),
                "total_discounts": str(total_discounts),
                "total_tax": str(total_tax),
                "total_debits": str(total_debits),
                "total_returns": str(total_returns),
                "total_charged": str(total_invoiced + total_debits),
                "total_paid": str(total_paid),
                "balance_due": str(total_invoiced + total_debits - total_paid - total_returns),
                "outstanding_balance": str(customer.outstanding_balance),
                "payment_by_method": payment_by_method,
            },
        })

    @action(detail=True, methods=["post"], url_path="record_debit")
    def record_debit(self, request, pk=None):
        """POST /customers/{id}/record_debit/  — record a manual debit charge."""
        customer = self.get_object()
        serializer = CustomerDebitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            organisation=request.organisation,
            customer=customer,
            recorded_by=request.user,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)
