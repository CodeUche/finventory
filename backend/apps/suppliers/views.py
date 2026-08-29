from datetime import date, datetime
from decimal import Decimal

from django.db.models import Sum
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsStaff, plan_requires
from apps.core.permissions import requires_module
# The owner's per-person ticks, enforced server-side (H-2). Mirrors
# useModuleAccess.ts: owners and admins bypass; for everyone else no
# record means no access, and only what was granted is granted.
_ModAccess_suppliers = requires_module("suppliers")


_PlanSuppliers = plan_requires('suppliers')
from .models import Supplier
from .serializers import SupplierSerializer
from apps.core.unique_errors import FriendlyUniqueErrorMixin


class SupplierViewSet(FriendlyUniqueErrorMixin, TenantFilterMixin, viewsets.ModelViewSet):
    unique_error_message = "A supplier with that code already exists in your organisation."
    queryset = Supplier.objects.filter(is_active=True)
    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated, IsStaff, _PlanSuppliers, _ModAccess_suppliers]
    search_fields = ["name", "code", "email", "phone"]
    ordering_fields = ["name", "created_at"]

    @action(detail=True, methods=["post"], url_path="set-opening-balance")
    def set_opening_balance(self, request, pk=None):
        """
        POST /api/v1/suppliers/<id>/set-opening-balance/
        Body: { amount, side?, as_of_date? }

        GL-correct opening/take-on balance for ONE supplier — mirrors the
        customer/product equivalents. Posts Credit mapped payable account / Debit
        Take-On Suspense for a credit balance (reversed for a debit balance).
        """
        from datetime import date as _date
        from apps.accounting.services import AccountingService

        supplier = self.get_object()
        org = self._get_organisation()

        as_of_str = request.data.get("as_of_date")
        try:
            as_of = _date.fromisoformat(as_of_str) if as_of_str else _date.today()
        except (ValueError, TypeError):
            return Response({"error": "as_of_date must be YYYY-MM-DD"}, status=400)

        try:
            AccountingService.set_supplier_opening_balance(
                org, supplier,
                amount=request.data.get("amount", 0),
                side=request.data.get("side"),
                as_of_date=as_of,
                created_by=request.user,
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=422)
        except Exception as e:
            return Response({"error": f"[{type(e).__name__}] {e}"}, status=422)

        return Response(SupplierSerializer(supplier).data)

    @action(detail=True, methods=["get"], url_path="statement")
    def statement(self, request, pk=None):
        """GET /suppliers/{id}/statement/?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD

        Mirrors CustomerViewSet.statement — a bespoke aggregation over this
        supplier's Bills/BillPayments/PurchaseReturns, since suppliers have no
        running outstanding_balance field the way Customer does and (unlike the
        GL account drill-down) most suppliers share one org-level AP control
        account rather than a dedicated GL account each.
        """
        supplier = self.get_object()

        today = date.today()
        first_of_month = today.replace(day=1)

        def parse_date(val, default):
            try:
                return datetime.strptime(val, "%Y-%m-%d").date() if val else default
            except ValueError:
                return default

        date_from = parse_date(request.query_params.get("date_from"), first_of_month)
        date_to   = parse_date(request.query_params.get("date_to"), today)

        from apps.bills.models import Bill, BillPayment
        from apps.purchases.models import PurchaseReturn

        bill_qs = (
            Bill.objects.filter(
                organisation=request.organisation,
                supplier=supplier,
                issue_date__gte=date_from,
                issue_date__lte=date_to,
            )
            .exclude(status=Bill.VOIDED)
            .order_by("issue_date")
            .prefetch_related("items")
        )

        bills = []
        for bill in bill_qs:
            items = [
                {
                    "description": item.description,
                    "quantity": str(item.quantity),
                    "unit_cost": str(item.unit_cost),
                    "line_total": str(item.line_total),
                }
                for item in bill.items.all()
            ]
            bills.append({
                "id": str(bill.id),
                "bill_number": bill.bill_number,
                "reference": bill.reference,
                "issue_date": bill.issue_date,
                "due_date": bill.due_date,
                "status": bill.status,
                "subtotal": str(bill.subtotal),
                "tax_amount": str(bill.tax_amount),
                "total_amount": str(bill.total_amount),
                "amount_paid": str(bill.amount_paid),
                "amount_due": str(bill.amount_due),
                "items": items,
            })

        payments_qs = list(
            BillPayment.objects.filter(
                organisation=request.organisation,
                bill__supplier=supplier,
                payment_date__gte=date_from,
                payment_date__lte=date_to,
            )
            .order_by("payment_date")
            .values("id", "bill__bill_number", "amount", "method", "payment_date", "reference")
        )

        returns_qs = list(
            PurchaseReturn.objects.filter(
                organisation=request.organisation,
                supplier=supplier,
                return_date__gte=date_from,
                return_date__lte=date_to,
            )
            .order_by("return_date")
            .values("id", "return_number", "total_amount", "reason", "return_date")
        )

        total_billed  = sum(Decimal(str(b["total_amount"])) for b in bills)
        total_tax     = sum(Decimal(str(b["tax_amount"])) for b in bills)
        total_paid    = sum(Decimal(str(p["amount"])) for p in payments_qs)
        total_returns = sum(Decimal(str(r["total_amount"])) for r in returns_qs)

        payments_list = [
            {
                "id": str(p["id"]),
                "bill_number": p["bill__bill_number"],
                "amount": str(p["amount"]),
                "method": p["method"],
                "payment_date": p["payment_date"],
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

        # Running balance owed to this supplier: opening take-on balance (signed,
        # positive = we owe them) plus everything billed/returned/paid since —
        # not scoped to the date window, since it's a point-in-time position.
        all_time_billed = Decimal(str(
            Bill.objects.filter(organisation=request.organisation, supplier=supplier)
            .exclude(status=Bill.VOIDED)
            .aggregate(total=Sum("total_amount"))["total"] or 0
        ))
        all_time_paid = Decimal(str(
            BillPayment.objects.filter(organisation=request.organisation, bill__supplier=supplier)
            .aggregate(total=Sum("amount"))["total"] or 0
        ))
        all_time_returned = Decimal(str(
            PurchaseReturn.objects.filter(organisation=request.organisation, supplier=supplier)
            .aggregate(total=Sum("total_amount"))["total"] or 0
        ))
        current_balance = (
            Decimal(str(supplier.opening_balance or 0))
            + all_time_billed - all_time_paid - all_time_returned
        )

        return Response({
            "supplier": SupplierSerializer(supplier).data,
            "period_start": date_from,
            "period_end": date_to,
            "bills": bills,
            "payments": payments_list,
            "returns": [
                {
                    "id": str(r["id"]),
                    "return_number": r["return_number"],
                    "amount": str(r["total_amount"]),
                    "reason": r["reason"] or "",
                    "return_date": str(r["return_date"]),
                }
                for r in returns_qs
            ],
            "summary": {
                "total_billed": str(total_billed),
                "total_tax": str(total_tax),
                "total_returns": str(total_returns),
                "total_paid": str(total_paid),
                "balance_due": str(total_billed - total_paid - total_returns),
                "outstanding_balance": str(current_balance),
                "payment_by_method": payment_by_method,
            },
        })
