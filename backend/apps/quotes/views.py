from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsStaff, plan_requires

_PlanQuotes = plan_requires('quotes')
from apps.customers.models import Customer
from apps.inventory.models import Warehouse, Product
from .models import Quote
from .serializers import QuoteSerializer, CreateQuoteSerializer
from .services import QuoteService
from decimal import Decimal


class QuoteViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = QuoteSerializer
    permission_classes = [IsAuthenticated, IsStaff, _PlanQuotes]
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
        except Exception:
            import logging as _log
            _log.getLogger(__name__).exception("Unexpected error converting quote")
            return Response({'error': "An unexpected error occurred. Please try again."}, status=400)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsStaff])
    def send_email(self, request, pk=None):
        """POST /api/v1/quotes/{id}/send_email/ — send quote to customer by email."""
        quote = self.get_object()
        to_email = request.data.get('to_email') or (quote.customer and quote.customer.email)
        if not to_email:
            return Response({'error': 'No recipient email address provided'}, status=422)

        try:
            email_cfg = request.organisation.email_config
            if not email_cfg.is_active:
                return Response({'error': 'Email is not configured. Go to Settings → Email.'}, status=422)
        except Exception:
            return Response({'error': 'Email is not configured. Go to Settings → Email.'}, status=422)

        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from django.utils.html import escape as _esc

            from_name  = email_cfg.from_name or request.organisation.name
            from_email = email_cfg.from_email or email_cfg.smtp_username

            items_html = ''.join(
                f"<tr><td style='padding:6px 10px;border-bottom:1px solid #eee'>{_esc(i.product.name)}</td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right'>{_esc(str(i.quantity))}</td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right'>{_esc(str(i.unit_price))}</td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right;font-weight:bold'>{_esc(str(i.line_total))}</td></tr>"
                for i in quote.items.all()
            )
            customer_name = _esc(quote.customer.name) if quote.customer else 'Customer'
            html = f"""
<html><body style='font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto'>
  <div style='background:#f97316;padding:20px;text-align:center'>
    <h1 style='color:white;margin:0;font-size:24px'>QUOTE</h1>
    <p style='color:white;margin:5px 0 0'>#{_esc(quote.quote_number)}</p>
  </div>
  <div style='padding:24px'>
    <p>Dear {customer_name},</p>
    <p>Please find your quote details below. This quote is valid until {_esc(str(quote.valid_until))}.</p>
    <table style='width:100%;border-collapse:collapse;margin:16px 0'>
      <thead><tr style='background:#f97316;color:white'>
        <th style='padding:8px 10px;text-align:left'>Item</th>
        <th style='padding:8px 10px;text-align:right'>Qty</th>
        <th style='padding:8px 10px;text-align:right'>Unit Price</th>
        <th style='padding:8px 10px;text-align:right'>Total</th>
      </tr></thead>
      <tbody>{items_html}</tbody>
    </table>
    <div style='text-align:right;margin-top:12px'>
      <p style='margin:4px 0;font-size:18px'>Total: <strong>{_esc(str(quote.total_amount))}</strong></p>
    </div>
    <hr style='margin:24px 0'>
    <p style='color:#888;font-size:12px'>Issued by {_esc(from_name)}. Thank you for your interest.</p>
  </div>
</body></html>"""

            msg = MIMEMultipart('mixed')
            msg['Subject'] = f"Quote {quote.quote_number} from {from_name}"
            msg['From']    = f"{from_name} <{from_email}>"
            msg['To']      = to_email

            alt = MIMEMultipart('alternative')
            alt.attach(MIMEText(html, 'html'))
            msg.attach(alt)

            pdf_base64 = request.data.get('pdf_base64')
            if pdf_base64:
                import base64
                from email.mime.base import MIMEBase
                from email import encoders
                try:
                    pdf_bytes = base64.b64decode(pdf_base64)
                    pdf_part = MIMEBase('application', 'pdf')
                    pdf_part.set_payload(pdf_bytes)
                    encoders.encode_base64(pdf_part)
                    pdf_part.add_header('Content-Disposition', 'attachment', filename=f"Quote-{quote.quote_number}.pdf")
                    msg.attach(pdf_part)
                except Exception:
                    pass

            import ssl as _ssl
            ctx = _ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
            if email_cfg.use_tls:
                conn = smtplib.SMTP(email_cfg.smtp_host, email_cfg.smtp_port, timeout=20)
                conn.ehlo(); conn.starttls(context=ctx); conn.ehlo()
            else:
                conn = smtplib.SMTP_SSL(email_cfg.smtp_host, email_cfg.smtp_port, timeout=20, context=ctx)
                conn.ehlo()
            conn.login(email_cfg.smtp_username, email_cfg.smtp_password)
            conn.sendmail(from_email, [to_email], msg.as_string())
            try:
                conn.quit()
            except Exception:
                pass

            return Response({'message': f"Quote sent to {to_email}"})
        except smtplib.SMTPAuthenticationError:
            return Response({'error': 'SMTP authentication failed. Check your username and password in Settings → Email.'}, status=422)
        except Exception:
            import logging as _log
            _log.getLogger(__name__).exception("Quote email send failed")
            return Response({'error': "Failed to send email. Please check your SMTP settings."}, status=422)
