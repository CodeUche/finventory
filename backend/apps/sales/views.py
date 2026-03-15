"""Sales ViewSets."""

import logging
import django_filters
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import ExportMixin, TenantFilterMixin
from apps.core.permissions import IsStaff
from apps.customers.models import Customer
from apps.inventory.models import Product, Warehouse

logger = logging.getLogger(__name__)

from .models import Invoice, InvoiceFolder, RecurringInvoice, SaleItem, SaleReturn
from .serializers import (
    CreateSaleSerializer,
    InvoiceSerializer,
    RecordPaymentSerializer,
    SalePaymentSerializer,
    RecurringInvoiceSerializer,
    SaleReturnSerializer,
    ProcessReturnSerializer,
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


class InvoiceViewSet(ExportMixin, TenantFilterMixin, viewsets.ModelViewSet):
    export_filename = 'invoices'
    export_fields = [
        ('Invoice #', 'invoice_number'),
        ('Date', 'invoice_date'),
        ('Due Date', 'due_date'),
        ('Customer', lambda o: o.customer.name if o.customer else 'Walk-in'),
        ('Status', 'status'),
        ('Subtotal', 'subtotal'),
        ('Tax', 'tax_amount'),
        ('Total', 'total'),
        ('Amount Due', 'amount_due'),
        ('Payment Method', 'payment_method'),
    ]
    """
    Sales invoice management.

    POST /sales/invoices/ — Create a new sale (triggers stock deduction)
    POST /sales/invoices/{id}/pay/ — Record a payment
    POST /sales/invoices/{id}/void/ — Void an invoice
    """

    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    filterset_class = InvoiceFilter
    search_fields = ["invoice_number", "customer__name"]
    ordering_fields = ["issue_date", "total_amount", "status"]

    def get_queryset(self):
        org = self._get_organisation()
        # Auto-mark overdue invoices on every list fetch
        try:
            from django.utils import timezone as tz
            today = tz.now().date()
            Invoice.objects.filter(
                organisation=org,
                due_date__lt=today,
                status__in=['confirmed', 'partially_paid', 'credit'],
            ).update(status=Invoice.Status.OVERDUE)
        except Exception:
            pass
        return Invoice.objects.filter(organisation=org).select_related("customer", "warehouse").prefetch_related(
            "items__product", "payments"
        )

    def create(self, request, *args, **kwargs):
        """Create a confirmed sale invoice."""
        serializer = CreateSaleSerializer(data=request.data)
        if not serializer.is_valid():
            # Flatten DRF validation errors into a single readable string
            errors = serializer.errors
            messages = []
            for field, errs in errors.items():
                if isinstance(errs, list):
                    messages.append(f"{field}: {'; '.join(str(e) for e in errs)}")
                elif isinstance(errs, dict):
                    for sub, sub_errs in errs.items():
                        messages.append(f"{field}.{sub}: {'; '.join(str(e) for e in sub_errs)}")
                else:
                    messages.append(str(errs))
            return Response({"error": " | ".join(messages)}, status=400)

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
                is_proforma=d.get("is_proforma", False),
                amount_paid=d.get("amount_paid"),
                amount_tendered=d.get("amount_tendered"),
            )
            return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)

        except (Warehouse.DoesNotExist, Customer.DoesNotExist) as e:
            return Response({"error": str(e)}, status=404)
        except Product.DoesNotExist as e:
            return Response({"error": f"Product not found: {e}"}, status=422)
        except ValueError as e:
            return Response({"error": str(e)}, status=422)
        except Exception as e:
            logger.exception("Unexpected error creating sale")
            return Response({"error": f"[{type(e).__name__}] {str(e)}"}, status=422)

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

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsStaff])
    def process_return(self, request, pk=None):
        """POST /api/v1/sales/invoices/{id}/process_return/ — Create a sales return."""
        invoice = self.get_object()
        serializer = ProcessReturnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        try:
            sale_return = SaleService.process_return(
                organisation=request.organisation,
                invoice=invoice,
                items=d["items"],
                reason=d["reason"],
                notes=d.get("notes", ""),
                processed_by=request.user,
                restocked=d.get("restocked", True),
                return_date=d.get("return_date"),
            )
            return Response(SaleReturnSerializer(sale_return).data, status=201)
        except ValueError as e:
            return Response({"error": str(e)}, status=422)
        except Exception as e:
            logger.exception("Unexpected error processing return")
            return Response({"error": f"[{type(e).__name__}] {str(e)}"}, status=422)


    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsStaff])
    def confirm_proforma(self, request, pk=None):
        """POST /api/v1/sales/invoices/{id}/confirm_proforma/ — convert proforma to confirmed invoice."""
        invoice = self.get_object()
        if invoice.status != Invoice.Status.PROFORMA:
            return Response({"error": "Only proforma invoices can be confirmed this way"}, status=422)
        try:
            # Deduct stock for all physical items now that it's confirmed
            from apps.inventory.services import InventoryService
            from apps.inventory.models import StockMovement
            for item in invoice.items.all():
                if item.product.product_type != "service":
                    InventoryService.record_movement(
                        organisation=invoice.organisation,
                        product=item.product,
                        warehouse=invoice.warehouse,
                        movement_type=StockMovement.MovementType.SALE_OUT,
                        quantity=-item.quantity,
                        unit_cost=item.cost_of_goods / item.quantity if item.quantity else item.product.cost_price,
                        reference=invoice.invoice_number,
                        created_by=request.user,
                        batch=item.batch,
                    )
            invoice.status = Invoice.Status.CONFIRMED
            invoice.save(update_fields=["status"])
            return Response(InvoiceSerializer(invoice).data)
        except Exception as e:
            logger.exception("Error confirming proforma")
            return Response({"error": f"[{type(e).__name__}] {str(e)}"}, status=422)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsStaff])
    def send_email(self, request, pk=None):
        """POST /api/v1/sales/invoices/{id}/send_email/ — send invoice to customer by email."""
        invoice = self.get_object()
        to_email = request.data.get("to_email") or (invoice.customer and invoice.customer.email)
        if not to_email:
            return Response({"error": "No recipient email address provided"}, status=422)

        # Get org SMTP config
        try:
            email_cfg = request.organisation.email_config
            if not email_cfg.is_active:
                return Response({"error": "Email is not configured. Go to Settings → Email."}, status=422)
        except Exception:
            return Response({"error": "Email is not configured. Go to Settings → Email."}, status=422)

        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            from_name  = email_cfg.from_name or request.organisation.name
            from_email = email_cfg.from_email or email_cfg.smtp_username

            items_html = "".join(
                f"<tr><td style='padding:6px 10px;border-bottom:1px solid #eee'>{i.product.name}</td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right'>{i.quantity}</td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right'>{i.unit_price}</td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right;font-weight:bold'>{i.line_total}</td></tr>"
                for i in invoice.items.all()
            )
            html = f"""
<html><body style='font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto'>
  <div style='background:#f97316;padding:20px;text-align:center'>
    <h1 style='color:white;margin:0;font-size:24px'>INVOICE</h1>
    <p style='color:white;margin:5px 0 0'>#{invoice.invoice_number}</p>
  </div>
  <div style='padding:24px'>
    <p>Dear {invoice.customer.name if invoice.customer else 'Customer'},</p>
    <p>Please find your invoice details below.</p>
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
      <p style='margin:4px 0'>Subtotal: <strong>{invoice.total_amount}</strong></p>
      <p style='margin:4px 0'>Paid: <strong style='color:green'>{invoice.amount_paid}</strong></p>
      <p style='margin:4px 0;font-size:18px'>Balance Due: <strong style='color:{"red" if float(invoice.amount_due) > 0 else "green"}'>{invoice.amount_due}</strong></p>
    </div>
    <hr style='margin:24px 0'>
    <p style='color:#888;font-size:12px'>Issued by {from_name}. Thank you for your business.</p>
  </div>
</body></html>"""

            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"Invoice {invoice.invoice_number} from {from_name}"
            msg["From"]    = f"{from_name} <{from_email}>"
            msg["To"]      = to_email
            msg.attach(MIMEText(html, "html"))

            import ssl as _ssl
            ctx = _ssl.create_default_context()
            if email_cfg.use_tls:
                # STARTTLS mode (typically port 587)
                conn = smtplib.SMTP(email_cfg.smtp_host, email_cfg.smtp_port, timeout=20)
                conn.ehlo()
                conn.starttls(context=ctx)
                conn.ehlo()
            else:
                # Direct SSL mode (typically port 465)
                conn = smtplib.SMTP_SSL(email_cfg.smtp_host, email_cfg.smtp_port, timeout=20, context=ctx)
                conn.ehlo()
            conn.login(email_cfg.smtp_username, email_cfg.smtp_password)
            conn.sendmail(from_email, [to_email], msg.as_string())
            try:
                conn.quit()
            except Exception:
                pass  # ignore quit errors — message is already sent

            return Response({"message": f"Invoice sent to {to_email}"})
        except smtplib.SMTPAuthenticationError:
            return Response({"error": "SMTP authentication failed. Check your username and password in Settings → Email."}, status=422)
        except smtplib.SMTPConnectError as e:
            return Response({"error": f"Could not connect to SMTP server ({email_cfg.smtp_host}:{email_cfg.smtp_port}). Check host and port settings."}, status=422)
        except OSError as e:
            err_str = str(e)
            if '10054' in err_str or 'forcibly closed' in err_str.lower():
                return Response({"error": "SMTP connection was reset by the server. Try switching between STARTTLS (port 587) and SSL (port 465) in Settings → Email."}, status=422)
            return Response({"error": f"Network error sending email: {err_str}"}, status=422)
        except Exception as e:
            logger.exception("Email send failed")
            return Response({"error": f"Failed to send email: {str(e)}"}, status=422)


    @action(detail=False, methods=["get"])
    def product_history(self, request):
        """GET /api/v1/sales/invoices/product_history/?product_id=<uuid>
        Returns all sale line items for a specific product (most recent first).
        """
        org = self._get_organisation()
        product_id = request.query_params.get("product_id")
        if not product_id:
            return Response({"error": "product_id is required"}, status=400)
        try:
            product = Product.objects.get(id=product_id, organisation=org)
        except Product.DoesNotExist:
            return Response({"error": "Product not found"}, status=404)

        items = (
            SaleItem.objects.filter(invoice__organisation=org, product=product)
            .select_related(
                "invoice",
                "invoice__customer",
                "invoice__warehouse",
                "invoice__created_by",
            )
            .order_by("-invoice__issue_date")[:200]
        )

        results = []
        for item in items:
            inv = item.invoice
            created_by = inv.created_by
            sold_by = (
                f"{created_by.first_name} {created_by.last_name}".strip()
                or created_by.email
            )
            results.append(
                {
                    "invoice_id": str(inv.id),
                    "invoice_number": inv.invoice_number,
                    "issue_date": inv.issue_date.isoformat(),
                    "customer_name": inv.customer.name if inv.customer else "Walk-in",
                    "sold_by": sold_by,
                    "warehouse": inv.warehouse.name,
                    "payment_method": inv.payment_method,
                    "quantity": str(item.quantity),
                    "unit_price": str(item.unit_price),
                    "line_total": str(item.line_total),
                    "status": inv.status,
                }
            )

        return Response({"product_name": product.name, "results": results})


class InvoiceFolderViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """CRUD for invoice folders. GET /sales/folders/, POST, PATCH, DELETE."""
    permission_classes = [IsAuthenticated, IsStaff]

    def get_serializer_class(self):
        from .serializers import InvoiceFolderSerializer
        return InvoiceFolderSerializer

    def get_queryset(self):
        org = self._get_organisation()
        qs = InvoiceFolder.objects.filter(organisation=org)
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
        """GET /sales/folders/{id}/contents/ — folder + children + invoices inside."""
        from .serializers import InvoiceFolderSerializer
        org = self._get_organisation()
        try:
            folder = InvoiceFolder.objects.get(id=pk, organisation=org)
        except InvoiceFolder.DoesNotExist:
            return Response({'error': 'Folder not found'}, status=404)
        children = InvoiceFolder.objects.filter(parent=folder, organisation=org)
        invoices = Invoice.objects.filter(folder=folder, organisation=org).select_related(
            'customer', 'warehouse'
        ).prefetch_related('items__product', 'payments')
        from .serializers import InvoiceSerializer
        return Response({
            'folder': InvoiceFolderSerializer(folder).data,
            'children': InvoiceFolderSerializer(children, many=True).data,
            'invoices': InvoiceSerializer(invoices, many=True).data,
        })


class SaleReturnViewSet(TenantFilterMixin, viewsets.ReadOnlyModelViewSet):
    """List and retrieve sale returns (credit notes)."""

    serializer_class = SaleReturnSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    search_fields = ["return_number", "invoice__invoice_number"]

    def get_queryset(self):
        org = self._get_organisation()
        return SaleReturn.objects.filter(organisation=org).select_related(
            "invoice", "processed_by"
        ).prefetch_related("items__product")


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

    @action(detail=True, methods=['post'])
    def generate_now(self, request, pk=None):
        """Immediately generate an invoice from this recurring template."""
        ri = self.get_object()
        org = self._get_organisation()
        try:
            from apps.inventory.models import Warehouse
            from apps.customers.models import Customer
            from decimal import Decimal

            warehouse = ri.warehouse
            customer = ri.customer
            items_raw = ri.items if isinstance(ri.items, list) else []

            if not items_raw:
                return Response({'error': 'Recurring invoice has no items configured'}, status=400)

            items_data = []
            for it in items_raw:
                from apps.inventory.models import Product
                try:
                    product = Product.objects.get(id=it.get('product_id') or it.get('product'), organisation=org)
                except Product.DoesNotExist:
                    continue
                items_data.append({
                    'product_id': product.id,
                    'quantity': Decimal(str(it.get('quantity', 1))),
                    'unit_price': Decimal(str(it.get('unit_price', product.selling_price))),
                    'discount_percent': Decimal(str(it.get('discount_percent', 0))),
                })

            if not items_data:
                return Response({'error': 'No valid products found in recurring template'}, status=400)

            invoice = SaleService.create_sale(
                organisation=org,
                created_by=request.user,
                customer=customer,
                warehouse=warehouse,
                items=items_data,
                payment_method=ri.payment_method if hasattr(ri, 'payment_method') else 'cash',
                notes=ri.notes if hasattr(ri, 'notes') else '',
            )

            # Advance next_run_date
            try:
                from dateutil.relativedelta import relativedelta
                from django.utils import timezone as tz
                freq = ri.frequency
                if freq == 'daily':
                    delta = relativedelta(days=1)
                elif freq == 'weekly':
                    delta = relativedelta(weeks=1)
                elif freq == 'monthly':
                    delta = relativedelta(months=1)
                elif freq == 'quarterly':
                    delta = relativedelta(months=3)
                elif freq == 'yearly':
                    delta = relativedelta(years=1)
                else:
                    delta = relativedelta(months=1)
                ri.next_run_date = (ri.next_run_date or tz.now().date()) + delta
                if hasattr(ri, 'occurrences_count'):
                    ri.occurrences_count = (ri.occurrences_count or 0) + 1
                ri.save()
            except Exception:
                pass

            return Response({'message': 'Invoice generated', 'invoice_id': str(invoice.id), 'invoice_number': invoice.invoice_number})
        except Exception as e:
            logger.exception("generate_now failed")
            return Response({'error': f"[{type(e).__name__}] {str(e)}"}, status=400)
