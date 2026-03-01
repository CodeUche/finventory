from decimal import Decimal
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsStaff, IsManager
from apps.suppliers.models import Supplier
from .models import Bill
from .serializers import BillSerializer, CreateBillSerializer, RecordBillPaymentSerializer
from .services import BillService


class BillViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = BillSerializer
    permission_classes = [IsAuthenticated, IsStaff]

    def get_queryset(self):
        org = self._get_organisation()
        qs = Bill.objects.filter(organisation=org).select_related('supplier').prefetch_related('items', 'payments')
        status_f = self.request.query_params.get('status')
        if status_f:
            qs = qs.filter(status=status_f)
        return qs

    def create(self, request, *args, **kwargs):
        org = self._get_organisation()
        ser = CreateBillSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        supplier = Supplier.objects.get(id=d['supplier'], organisation=org)
        items_data = []
        for item in d['items']:
            items_data.append({
                'description': item['description'],
                'quantity': Decimal(str(item.get('quantity', '1'))),
                'unit_cost': Decimal(str(item['unit_cost'])),
            })
        bill_data = {
            'supplier': supplier,
            'issue_date': d['issue_date'],
            'due_date': d['due_date'],
            'reference': d.get('reference', ''),
            'tax_amount': Decimal(str(d.get('tax_amount', '0'))),
            'notes': d.get('notes', ''),
        }
        bill = BillService.create_bill(bill_data, items_data, org, request.user)
        return Response(BillSerializer(bill).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        bill = self.get_object()
        bill = BillService.approve_bill(bill, request.user)
        return Response(BillSerializer(bill).data)

    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        bill = self.get_object()
        ser = RecordBillPaymentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        payment = BillService.record_payment(
            bill, d['amount'], d['payment_date'], d['method'],
            d.get('reference', ''), d.get('notes', ''), request.user
        )
        return Response(BillSerializer(bill).data)

    @action(detail=True, methods=['post'])
    def void(self, request, pk=None):
        bill = self.get_object()
        bill.status = Bill.VOIDED
        bill.save()
        return Response(BillSerializer(bill).data)
