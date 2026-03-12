from decimal import Decimal
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsStaff, IsManager
from apps.suppliers.models import Supplier
from .models import Bill, BillFolder
from .serializers import BillFolderSerializer, BillSerializer, CreateBillSerializer, RecordBillPaymentSerializer
from .services import BillService


class BillFolderViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """CRUD for bill folders. GET /bills/folders/, POST, PATCH, DELETE."""
    serializer_class = BillFolderSerializer
    permission_classes = [IsAuthenticated, IsStaff]

    def get_queryset(self):
        org = self._get_organisation()
        qs = BillFolder.objects.filter(organisation=org)
        parent = self.request.query_params.get('parent')
        if parent == 'null':
            qs = qs.filter(parent__isnull=True)
        elif parent:
            qs = qs.filter(parent_id=parent)
        return qs

    def perform_create(self, serializer):
        serializer.save(organisation=self._get_organisation())

    @action(detail=True, methods=['get'])
    def contents(self, request, pk=None):
        """GET /bills/folders/{id}/contents/ — folder + children + bills inside."""
        org = self._get_organisation()
        try:
            folder = BillFolder.objects.get(id=pk, organisation=org)
        except BillFolder.DoesNotExist:
            return Response({'error': 'Folder not found'}, status=404)
        children = BillFolder.objects.filter(parent=folder, organisation=org)
        bills = Bill.objects.filter(folder=folder, organisation=org).select_related('supplier').prefetch_related('items', 'payments')
        return Response({
            'folder': BillFolderSerializer(folder).data,
            'children': BillFolderSerializer(children, many=True).data,
            'bills': BillSerializer(bills, many=True).data,
        })


class BillViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = BillSerializer
    permission_classes = [IsAuthenticated, IsStaff]

    def get_queryset(self):
        org = self._get_organisation()
        qs = Bill.objects.filter(organisation=org).select_related('supplier').prefetch_related('items', 'payments')
        status_f = self.request.query_params.get('status')
        if status_f:
            qs = qs.filter(status=status_f)
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(issue_date__gte=date_from)
        if date_to:
            qs = qs.filter(issue_date__lte=date_to)
        return qs

    def create(self, request, *args, **kwargs):
        org = self._get_organisation()
        ser = CreateBillSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        supplier = Supplier.objects.get(id=d['supplier'], organisation=org)
        items_data = []
        for item in d['items']:
            # Values are already typed Decimals from BillItemInputSerializer — no casting needed
            entry = {
                'description': item['description'],
                'quantity': item['quantity'],
                'unit_cost': item['unit_cost'],
            }
            # Pass optional FK fields if provided
            if item.get('expense_category_id'):
                entry['expense_category_id'] = item['expense_category_id']
            if item.get('account_id'):
                entry['account_id'] = item['account_id']
            items_data.append(entry)
        bill_data = {
            'supplier': supplier,
            'issue_date': d['issue_date'],
            'due_date': d['due_date'],
            'reference': d.get('reference', ''),
            'tax_amount': Decimal(str(d.get('tax_amount', '0'))),
            'notes': d.get('notes', ''),
            'status': d.get('status', 'draft'),
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
