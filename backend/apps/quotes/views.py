from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsStaff
from apps.customers.models import Customer
from apps.inventory.models import Warehouse, Product
from .models import Quote
from .serializers import QuoteSerializer, CreateQuoteSerializer
from .services import QuoteService
from decimal import Decimal


class QuoteViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = QuoteSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    filterset_fields = ['status']

    def get_queryset(self):
        org = self._get_organisation()
        # Auto-expire quotes whose valid_until date has passed
        try:
            from django.utils import timezone as tz
            today = tz.now().date()
            Quote.objects.filter(
                organisation=org,
                valid_until__lt=today,
                status__in=[Quote.DRAFT, Quote.SENT],
            ).update(status=Quote.EXPIRED)
        except Exception:
            pass

        qs = Quote.objects.filter(organisation=org).select_related('customer', 'warehouse', 'converted_invoice').prefetch_related('items__product')
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        return qs

    def create(self, request, *args, **kwargs):
        org = self._get_organisation()
        ser = CreateQuoteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        customer = None
        if d.get('customer'):
            customer = Customer.objects.get(id=d['customer'], organisation=org)
        warehouse = Warehouse.objects.get(id=d['warehouse'], organisation=org)

        items_raw = d['items']
        items_data = []
        for item in items_raw:
            product_key = item.get("product_id") or item.get("product")
            product = Product.objects.get(id=product_key, organisation=org)
            items_data.append({
                'product': product,
                'quantity': Decimal(str(item['quantity'])),
                'unit_price': Decimal(str(item.get('unit_price', product.selling_price))),
                'discount_percent': Decimal(str(item.get('discount_percent', '0'))),
                'tax_rate': Decimal(str(item.get('tax_rate', '0'))),
            })

        quote_data = {
            'customer': customer,
            'warehouse': warehouse,
            'status': d.get('status', Quote.DRAFT),
            'issue_date': d['issue_date'],
            'valid_until': d['valid_until'],
            'notes': d.get('notes', ''),
            'terms': d.get('terms', ''),
        }
        quote = QuoteService.create_quote(quote_data, items_data, org, request.user)
        return Response(QuoteSerializer(quote).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        quote = self.get_object()
        if quote.status != Quote.DRAFT:
            return Response({'error': 'Only draft quotes can be sent'}, status=400)
        quote.status = Quote.SENT
        quote.save()
        return Response(QuoteSerializer(quote).data)

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        quote = self.get_object()
        quote.status = Quote.ACCEPTED
        quote.save()
        return Response(QuoteSerializer(quote).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        quote = self.get_object()
        quote.status = Quote.REJECTED
        quote.save()
        return Response(QuoteSerializer(quote).data)

    @action(detail=True, methods=['post'])
    def convert(self, request, pk=None):
        quote = self.get_object()
        if quote.status == Quote.REJECTED:
            return Response({'error': 'This quote was rejected and cannot be converted to an invoice.'}, status=400)
        if quote.status == Quote.EXPIRED:
            return Response({'error': 'This quote has expired. Please create a new quote.'}, status=400)
        try:
            invoice = QuoteService.convert_to_invoice(quote, request.user)
            return Response({'message': 'Converted successfully', 'invoice_id': str(invoice.id)})
        except ValueError as e:
            return Response({'error': str(e)}, status=400)
        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).exception("Unexpected error converting quote")
            return Response({'error': f"[{type(e).__name__}] {str(e)}"}, status=400)
