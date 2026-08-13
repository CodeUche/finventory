"""Sales ViewSets."""

import logging
import datetime
import django_filters
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.idempotency import IdempotencyMixin
from apps.core.mixins import ExportMixin, TenantFilterMixin
from apps.core.permissions import IsStaff, IsOwnerOrAdmin, has_minimum_role, plan_requires
from apps.core.throttles import FinancialWriteThrottle

_PlanRecurring = plan_requires('recurring')
from apps.customers.models import Customer
from apps.inventory.models import Product, Warehouse

logger = logging.getLogger(__name__)

from .models import Invoice, InvoiceFolder, Location, RecurringInvoice, SaleItem, SalePayment, SaleReturn
from .serializers import (
    CreateSaleSerializer,
    InvoiceFolderSerializer,
    InvoiceSerializer,
    LocationSerializer,
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


class InvoiceViewSet(IdempotencyMixin, ExportMixin, TenantFilterMixin, viewsets.ModelViewSet):
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
    throttle_classes = [FinancialWriteThrottle]
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
        cached, idem_key = self.check_idempotency(request, 'invoice:create')
        if cached is not None:
            return cached

        # ── Plan limit check (atomic to prevent race-condition bypass) ────────
        from django.db import transaction as _tx
        from django.utils import timezone as _tz
        from apps.subscriptions.services import SubscriptionService
        from apps.tenancy.models import Organisation
        org = self._get_organisation()
        _now = _tz.now()
        with _tx.atomic():
            Organisation.objects.select_for_update().get(pk=org.pk)
            monthly_count = Invoice.objects.filter(
                organisation=org,
                created_at__year=_now.year,
                created_at__month=_now.month,
            ).count()
            _limit_err = SubscriptionService.get_write_limit_error(org, "max_invoices_per_month", monthly_count)
            if _limit_err:
                return Response({"error": _limit_err, "upgrade_required": True}, status=402)
        # ─────────────────────────────────────────────────────────────────────

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
            location = None
            if d.get("location_id"):
                location = Location.objects.get(
                    id=d["location_id"], organisation=request.organisation
                )

            # Security: staff can only record themselves as sold_by.
            # Managers, admins, owners, and superusers may specify any name.
            raw_sold_by = d.get("sold_by", "").strip()
            can_override = request.user.is_superuser or has_minimum_role(
                request.user, request.organisation, "manager"
            )
            sold_by = raw_sold_by if (raw_sold_by and can_override) else ""

            invoice = SaleService.create_sale(
                organisation=request.organisation,
                created_by=request.user,
                customer=customer,
                warehouse=warehouse,
                items=d["items"],
                payment_method=d["payment_method"],
                notes=d.get("notes", ""),
                sold_by=sold_by,
                issue_date=d.get("issue_date"),
                due_date=d.get("due_date"),
                is_proforma=d.get("is_proforma", False),
                amount_paid=d.get("amount_paid"),
                amount_tendered=d.get("amount_tendered"),
                credit_applied=d.get("credit_applied"),
                location=location,
                wht_rate_id=d.get("wht_rate_id"),
                defer_fulfillment=d.get("defer_fulfillment", False),
            )
            try:
                from apps.core.models import AuditLog as _AL
                _AL.log(
                    action=_AL.CREATE,
                    user=request.user,
                    organisation=request.organisation,
                    model_name='Invoice',
                    object_id=str(invoice.id),
                    object_repr=str(invoice),
                    changes={'invoice_number': {'old': None, 'new': invoice.invoice_number}},
                    request=request,
                )
            except Exception:
                pass
            resp = Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)
            self.save_idempotency(idem_key, request.user.id, resp)
            return resp

        except (Warehouse.DoesNotExist, Customer.DoesNotExist) as e:
            return Response({"error": str(e)}, status=404)
        except Product.DoesNotExist as e:
            return Response({"error": f"Product not found: {e}"}, status=422)
        except (ValueError, DjangoValidationError, PermissionDenied) as e:
            # Period-locked (PermissionDenied), strict-GL / stock / store-credit
            # (ValueError) and validation errors all carry a clear, user-actionable
            # message — surface it instead of the opaque "unexpected error" toast
            # (this was the POS "An unexpected error occurred" bug on locked periods).
            msg = "; ".join(e.messages) if isinstance(e, DjangoValidationError) else str(e)
            return Response({"error": msg}, status=422)
        except Exception as e:
            logger.exception("Unexpected error creating sale")
            return Response(
                {"error": f"Could not complete sale: {type(e).__name__}: {e}"}, status=422
            )

    def _check_invoice_edit_permission(self, request):
        """
        Returns True if the user can edit invoices.
        Owner/admin always can. Other users need 'edit' level on the 'sales' module permission.
        """
        org = request.organisation
        if not org:
            return False
        if has_minimum_role(request.user, org, "admin"):
            return True
        # Check module-level 'edit' permission for sub-accounts
        from apps.tenancy.models import Membership, ModulePermission
        try:
            membership = Membership.objects.get(organisation=org, user=request.user, is_active=True)
            perm = ModulePermission.objects.filter(membership=membership, module="sales").first()
            return perm is not None and perm.access_level == "edit"
        except Membership.DoesNotExist:
            return False

    def update(self, request, *args, **kwargs):
        """
        PATCH /sales/invoices/{id}/ — Edit invoice metadata.

        Allowed fields: notes, due_date, issue_date, payment_method, folder, status (limited).
        Requires owner/admin role OR 'edit' sales module permission.
        Paid and voided invoices are read-only except for notes.
        """
        if not self._check_invoice_edit_permission(request):
            return Response(
                {"error": "You need edit-level sales permission to update invoices. Ask the account owner to grant access."},
                status=403,
            )

        invoice = self.get_object()

        LOCKED_STATUSES = {Invoice.Status.PAID, Invoice.Status.VOIDED}
        if invoice.status in LOCKED_STATUSES:
            # Only allow notes update on paid/voided invoices
            allowed = {k: v for k, v in request.data.items() if k == "notes"}
            if not allowed:
                return Response(
                    {"error": f"Paid and voided invoices cannot be edited. Use Void + Re-issue for corrections."},
                    status=422,
                )
            request._full_data = allowed  # type: ignore[attr-defined]

        # Only allow safe metadata fields — never allow changing financial amounts
        ALLOWED_FIELDS = {"notes", "due_date", "issue_date", "payment_method", "folder", "status"}
        # Status can only be changed between non-financial states
        if "status" in request.data:
            new_status = request.data.get("status")
            forbidden_transitions = {Invoice.Status.PAID, Invoice.Status.VOIDED}
            if new_status in forbidden_transitions:
                return Response(
                    {"error": "Status cannot be set to 'paid' or 'voided' via edit. Use the Pay or Void actions."},
                    status=422,
                )

        # Filter data to only allowed fields
        filtered_data = {k: v for k, v in request.data.items() if k in ALLOWED_FIELDS}
        serializer = self.get_serializer(invoice, data=filtered_data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=["patch"], url_path="edit_lines")
    def edit_lines(self, request, pk=None):
        """
        PATCH /sales/invoices/{id}/edit_lines/

        Full invoice edit: line items, customer, dates, notes.
        Requires the same permission as update().
        Allowed on all statuses except paid and voided.

        Body:
          {
            "items": [{"product_id": ..., "quantity": ..., "unit_price": ..., "discount_percent": ...}],
            "customer_id": "...",      (optional)
            "warehouse_id": "...",     (optional)
            "notes": "...",            (optional)
            "issue_date": "YYYY-MM-DD",
            "due_date": "YYYY-MM-DD",
            "payment_method": "..."
          }
        """
        if not self._check_invoice_edit_permission(request):
            return Response(
                {"error": "You need edit-level sales permission to update invoices."},
                status=403,
            )

        invoice = self.get_object()

        items = request.data.get("items")
        if not items or not isinstance(items, list) or len(items) == 0:
            return Response({"error": "At least one line item is required."}, status=422)

        # Resolve optional foreign keys
        customer = None
        customer_id = request.data.get("customer_id")
        if customer_id:
            from apps.customers.models import Customer
            try:
                customer = Customer.objects.get(id=customer_id, organisation=request.organisation)
            except Customer.DoesNotExist:
                return Response({"error": "Customer not found."}, status=404)

        warehouse = None
        warehouse_id = request.data.get("warehouse_id")
        if warehouse_id:
            from apps.inventory.models import Warehouse
            try:
                warehouse = Warehouse.objects.get(id=warehouse_id, organisation=request.organisation)
            except Warehouse.DoesNotExist:
                return Response({"error": "Warehouse not found."}, status=404)

        from datetime import date as _date, datetime as _dt
        def parse_date(s):
            if not s:
                return None
            try:
                return _dt.strptime(s, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return None

        try:
            updated = SaleService.update_sale(
                invoice=invoice,
                updated_by=request.user,
                customer=customer,
                warehouse=warehouse,
                items=items,
                notes=request.data.get("notes", invoice.notes),
                issue_date=parse_date(request.data.get("issue_date")),
                due_date=parse_date(request.data.get("due_date")),
                payment_method=request.data.get("payment_method"),
            )
        except (ValueError, Exception) as exc:
            logger.error("[edit_lines] %s – %s", type(exc).__name__, exc)
            return Response({"error": f"[{type(exc).__name__}] {exc}"}, status=422)

        serializer = self.get_serializer(updated)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        """
        DELETE /sales/invoices/{id}/ — Soft-delete an invoice.

        Requires owner/admin role. Only draft and proforma invoices may be deleted —
        confirmed/paid invoices must be voided to preserve the audit trail.
        """
        org = request.organisation
        if not org or not has_minimum_role(request.user, org, "admin"):
            return Response(
                {"error": "Only the account owner or admin can delete invoices."},
                status=403,
            )

        invoice = self.get_object()
        DELETABLE_STATUSES = {Invoice.Status.DRAFT, Invoice.Status.PROFORMA}
        if invoice.status not in DELETABLE_STATUSES:
            return Response(
                {"error": f"Only draft and proforma invoices can be deleted. To cancel a confirmed invoice, use the Void action instead."},
                status=422,
            )

        invoice.delete()  # SoftDeleteModel.delete() sets is_deleted=True
        logger.info("Invoice %s deleted by %s", invoice.invoice_number, request.user.email)
        return Response(status=204)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        """POST /api/v1/sales/invoices/{id}/pay/ — Record a payment."""
        cached, idem_key = self.check_idempotency(request, f'invoice:pay:{pk}')
        if cached is not None:
            return cached

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
            resp = Response(SalePaymentSerializer(payment).data, status=201)
            self.save_idempotency(idem_key, request.user.id, resp)
            return resp
        except ValueError as e:
            return Response({"error": str(e)}, status=422)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def pay_split(self, request, pk=None):
        """POST /api/v1/sales/invoices/{id}/pay_split/ — record multiple tenders
        (split payment: e.g. part cash + part transfer) in one call."""
        invoice = self.get_object()
        tenders = request.data.get("tenders") or request.data.get("payments") or []
        try:
            payments = SaleService.record_split_payment(invoice, tenders, received_by=request.user)
        except ValueError as e:
            return Response({"error": str(e)}, status=422)
        invoice.refresh_from_db()
        return Response({
            "payments": SalePaymentSerializer(payments, many=True).data,
            "invoice": InvoiceSerializer(invoice).data,
        }, status=201)

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
            from django.db import transaction as _tx
            with _tx.atomic():
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
        except Exception:
            logger.exception("Unexpected error processing return")
            return Response({"error": "An unexpected error occurred. Please try again."}, status=422)


    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsStaff])
    def confirm_proforma(self, request, pk=None):
        """POST /api/v1/sales/invoices/{id}/confirm_proforma/ — convert proforma to confirmed invoice."""
        try:
            from django.db import transaction as _tx
            from apps.inventory.services import InventoryService
            from apps.inventory.models import StockMovement
            with _tx.atomic():
                # Re-read with row lock to prevent concurrent double-confirmation
                invoice = Invoice.objects.select_for_update().get(
                    pk=self.get_object().pk,
                    organisation=request.organisation,
                )
                if invoice.status != Invoice.Status.PROFORMA:
                    return Response({"error": "Only proforma invoices can be confirmed this way"}, status=422)
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
        except Exception:
            logger.exception("Error confirming proforma")
            return Response({"error": "An unexpected error occurred. Please try again."}, status=422)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsStaff])
    def fulfill(self, request, pk=None):
        """POST /api/v1/sales/invoices/{id}/fulfill/ — deduct stock + post GL for a deferred invoice."""
        invoice = self.get_object()
        try:
            invoice = SaleService.fulfill_invoice(invoice, actor=request.user)
            return Response(InvoiceSerializer(invoice).data)
        except ValueError as e:
            return Response({"error": str(e)}, status=422)
        except Exception:
            logger.exception("Error fulfilling invoice")
            return Response({"error": "An unexpected error occurred. Please try again."}, status=422)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsOwnerOrAdmin])
    def delete_invoice(self, request, pk=None):
        """
        POST /api/v1/sales/invoices/{id}/delete_invoice/ — Reversal-based hard delete.

        Unlike DELETE (which only soft-deletes draft/proforma invoices), this
        action can delete ANY invoice: it reverses GL postings, restores stock,
        and resets customer balance contributions before soft-deleting the
        invoice and its line items/payments. Owner/admin or superuser only.
        """
        invoice = self.get_object()
        try:
            SaleService.delete_invoice(invoice, actor=request.user)
            return Response(status=204)
        except ValueError as e:
            return Response({"error": str(e)}, status=422)
        except Exception:
            logger.exception("Error deleting invoice")
            return Response({"error": "An unexpected error occurred. Please try again."}, status=422)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsStaff])
    def send_email(self, request, pk=None):
        """POST /api/v1/sales/invoices/{id}/send_email/ — send invoice to customer by email."""
        invoice = self.get_object()
        requested_email = request.data.get("to_email", "").strip()

        # Only owners/admins may override the customer email address
        if requested_email and invoice.customer and requested_email != invoice.customer.email:
            from apps.core.permissions import has_minimum_role
            if not has_minimum_role(request.user, request.organisation, "admin"):
                return Response(
                    {"error": "Only admins can redirect an invoice to a different email address."},
                    status=403,
                )

        to_email = requested_email or (invoice.customer and invoice.customer.email)
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
            from django.utils.html import escape as _esc

            from_name  = email_cfg.from_name or request.organisation.name
            from_email = email_cfg.from_email or email_cfg.smtp_username

            items_html = "".join(
                f"<tr><td style='padding:6px 10px;border-bottom:1px solid #eee'>{_esc(i.product.name)}</td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right'>{_esc(str(i.quantity))}</td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right'>{_esc(str(i.unit_price))}</td>"
                f"<td style='padding:6px 10px;border-bottom:1px solid #eee;text-align:right;font-weight:bold'>{_esc(str(i.line_total))}</td></tr>"
                for i in invoice.items.all()
            )
            customer_name = _esc(invoice.customer.name) if invoice.customer else 'Customer'
            html = f"""
<html><body style='font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto'>
  <div style='background:#f97316;padding:20px;text-align:center'>
    <h1 style='color:white;margin:0;font-size:24px'>INVOICE</h1>
    <p style='color:white;margin:5px 0 0'>#{_esc(invoice.invoice_number)}</p>
  </div>
  <div style='padding:24px'>
    <p>Dear {customer_name},</p>
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
      <p style='margin:4px 0'>Subtotal: <strong>{_esc(str(invoice.total_amount))}</strong></p>
      <p style='margin:4px 0'>Paid: <strong style='color:green'>{_esc(str(invoice.amount_paid))}</strong></p>
      <p style='margin:4px 0;font-size:18px'>Balance Due: <strong style='color:{"red" if float(invoice.amount_due) > 0 else "green"}'>{_esc(str(invoice.amount_due))}</strong></p>
    </div>
    <hr style='margin:24px 0'>
    <p style='color:#888;font-size:12px'>Issued by {_esc(from_name)}. Thank you for your business.</p>
  </div>
</body></html>"""

            msg = MIMEMultipart("mixed")
            msg["Subject"] = f"Invoice {invoice.invoice_number} from {from_name}"
            msg["From"]    = f"{from_name} <{from_email}>"
            msg["To"]      = to_email

            # HTML body wrapped in alternative part
            alt = MIMEMultipart("alternative")
            alt.attach(MIMEText(html, "html"))
            msg.attach(alt)

            # Attach PDF if provided
            pdf_base64 = request.data.get("pdf_base64")
            if pdf_base64:
                import base64
                from email.mime.base import MIMEBase
                from email import encoders
                try:
                    pdf_bytes = base64.b64decode(pdf_base64)
                    pdf_part = MIMEBase("application", "pdf")
                    pdf_part.set_payload(pdf_bytes)
                    encoders.encode_base64(pdf_part)
                    pdf_part.add_header(
                        "Content-Disposition",
                        "attachment",
                        filename=f"Invoice-{invoice.invoice_number}.pdf",
                    )
                    msg.attach(pdf_part)

                    # Auto-save to Google Drive if connected — this is the
                    # only point the backend ever sees actual invoice PDF
                    # bytes server-side (invoice PDFs are otherwise rendered
                    # client-side; see apps.reports.exporters' docstring
                    # note on the client-side pdfUtils template). Never
                    # raises — a Drive hiccup must not stop the email send.
                    from apps.connectors.services import maybe_save_pdf_to_drive
                    maybe_save_pdf_to_drive(
                        request.organisation, f"Invoice-{invoice.invoice_number}.pdf", pdf_bytes,
                    )
                except Exception:
                    pass  # skip attachment on decode error — still send the email

            import ssl as _ssl
            ctx = _ssl.create_default_context()
            # Some SMTP servers use certificates that fail strict Python SSL
            # validation (e.g. missing Basic Constraints critical flag).
            # Disable hostname/cert checking for outbound SMTP — acceptable risk.
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
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
        except Exception:
            logger.exception("Email send failed")
            return Response({"error": "Failed to send email. Please check your SMTP settings."}, status=422)


    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsStaff])
    def extend_due_date(self, request, pk=None):
        """POST /api/v1/sales/invoices/{id}/extend_due_date/
        Body: { new_due_date: "YYYY-MM-DD", reason: "optional note" }
        """
        from datetime import date
        invoice = self.get_object()
        new_due_date = request.data.get("new_due_date")
        reason = request.data.get("reason", "")
        if not new_due_date:
            return Response({"error": "new_due_date is required"}, status=422)
        try:
            parsed = date.fromisoformat(new_due_date)
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD."}, status=422)
        if parsed <= date.today():
            return Response({"error": "New due date must be in the future."}, status=422)

        old_date = invoice.due_date
        invoice.due_date = parsed
        # If the invoice was overdue, reset status back to credit so it's collectable again
        if invoice.status == "overdue":
            invoice.status = "credit"
        invoice.save(update_fields=["due_date", "status"])

        try:
            from apps.core.utils import log_audit
            log_audit(request, invoice, "UPDATE",
                      f"Due date extended from {old_date} to {parsed}. Reason: {reason}")
        except Exception:
            pass

        return Response(InvoiceSerializer(invoice, context={"request": request}).data)

    @action(detail=False, methods=["get"])
    def owner_analytics(self, request):
        """GET /sales/invoices/owner_analytics/?period=month
        Owner-only view: total revenue vs company COGS vs owner COGS vs gross profit at each level.
        period: today | week | month | year | all
        """
        from django.db.models import Sum, DecimalField
        from django.db.models.functions import Coalesce
        import decimal

        org = self._get_organisation()

        # Verify owner or admin
        from apps.tenancy.models import Membership
        try:
            membership = Membership.objects.get(
                organisation=org, user=request.user, is_active=True
            )
        except Membership.DoesNotExist:
            return Response({"error": "Not a member"}, status=403)
        if membership.role not in (Membership.Role.OWNER, Membership.Role.ADMIN):
            return Response({"error": "Owner or admin access required"}, status=403)

        period = request.query_params.get("period", "month")
        today = timezone.now().date()
        if period == "today":
            date_from = today
        elif period == "week":
            date_from = today - datetime.timedelta(days=7)
        elif period == "year":
            date_from = today - datetime.timedelta(days=365)
        elif period == "all":
            date_from = None
        else:
            date_from = today - datetime.timedelta(days=30)

        active_statuses = [
            Invoice.Status.CONFIRMED, Invoice.Status.PAID,
            Invoice.Status.PARTIALLY_PAID, Invoice.Status.OVERDUE,
            Invoice.Status.CREDIT,
        ]
        item_qs = SaleItem.objects.filter(
            invoice__organisation=org, invoice__status__in=active_statuses
        ).select_related("product")
        if date_from:
            item_qs = item_qs.filter(invoice__issue_date__gte=date_from)

        zero = decimal.Decimal("0")
        total_revenue = zero
        company_cogs = zero
        owner_cogs = zero
        product_map: dict = {}

        # Single pass over item_qs (was iterated twice) — halves DB/CPU cost
        # for orgs with large sales volumes while keeping identical arithmetic.
        for item in item_qs:
            qty = item.quantity
            owner_price = item.product.owner_cost_price or zero
            item_owner_cogs = qty * owner_price

            total_revenue += item.line_total
            company_cogs += item.cost_of_goods
            owner_cogs += item_owner_cogs

            pid = str(item.product_id)
            if pid not in product_map:
                product_map[pid] = {
                    "product_name": item.product.name,
                    "revenue": zero,
                    "company_cogs": zero,
                    "owner_cogs": zero,
                }
            product_map[pid]["revenue"] += item.line_total
            product_map[pid]["company_cogs"] += item.cost_of_goods
            product_map[pid]["owner_cogs"] += item_owner_cogs

        company_gross = total_revenue - company_cogs
        owner_gross = total_revenue - owner_cogs
        company_margin = (company_gross / total_revenue * 100) if total_revenue else zero
        owner_margin = (owner_gross / total_revenue * 100) if total_revenue else zero

        # Top products by owner profit

        top_products = sorted(
            [
                {
                    "product_name": v["product_name"],
                    "revenue": str(v["revenue"].quantize(decimal.Decimal("0.01"))),
                    "company_gross": str((v["revenue"] - v["company_cogs"]).quantize(decimal.Decimal("0.01"))),
                    "owner_gross": str((v["revenue"] - v["owner_cogs"]).quantize(decimal.Decimal("0.01"))),
                }
                for v in product_map.values()
            ],
            key=lambda x: float(x["owner_gross"]),
            reverse=True,
        )[:10]

        return Response({
            "period": period,
            "total_revenue": str(total_revenue.quantize(decimal.Decimal("0.01"))),
            "company_cogs": str(company_cogs.quantize(decimal.Decimal("0.01"))),
            "owner_cogs": str(owner_cogs.quantize(decimal.Decimal("0.01"))),
            "company_gross_profit": str(company_gross.quantize(decimal.Decimal("0.01"))),
            "owner_gross_profit": str(owner_gross.quantize(decimal.Decimal("0.01"))),
            "company_margin_pct": str(company_margin.quantize(decimal.Decimal("0.1"))),
            "owner_margin_pct": str(owner_margin.quantize(decimal.Decimal("0.1"))),
            "top_products": top_products,
        })

    @action(detail=False, methods=["get"])
    def warehouse_sales(self, request):
        """GET /sales/invoices/warehouse_sales/?period=month
        Returns revenue totals grouped by warehouse, with top-5 products per warehouse.
        period: today | week | month | year | all (default: month)
        """
        from django.db.models import Sum, Count, DecimalField
        from django.db.models.functions import Coalesce
        import decimal

        org = self._get_organisation()
        period = request.query_params.get("period", "month")

        today = timezone.now().date()
        if period == "today":
            date_from = today
        elif period == "week":
            date_from = today - datetime.timedelta(days=7)
        elif period == "year":
            date_from = today - datetime.timedelta(days=365)
        elif period == "all":
            date_from = None
        else:  # month
            date_from = today - datetime.timedelta(days=30)

        active_statuses = [
            Invoice.Status.CONFIRMED, Invoice.Status.PAID,
            Invoice.Status.PARTIALLY_PAID, Invoice.Status.OVERDUE,
            Invoice.Status.CREDIT,
        ]
        qs = Invoice.objects.filter(organisation=org, status__in=active_statuses)
        if date_from:
            qs = qs.filter(issue_date__gte=date_from)

        # Revenue per warehouse
        warehouse_totals = (
            qs.values("warehouse__id", "warehouse__name")
            .annotate(
                total_revenue=Coalesce(Sum("total_amount"), decimal.Decimal("0"), output_field=DecimalField()),
                invoice_count=Count("id"),
            )
            .order_by("-total_revenue")
        )

        results = []
        for row in warehouse_totals:
            wid = row["warehouse__id"]
            # Top 5 products for this warehouse in this period
            item_qs = SaleItem.objects.filter(
                invoice__organisation=org,
                invoice__status__in=active_statuses,
                invoice__warehouse_id=wid,
            )
            if date_from:
                item_qs = item_qs.filter(invoice__issue_date__gte=date_from)
            top_products = (
                item_qs
                .values("product__name")
                .annotate(
                    units=Coalesce(Sum("quantity"), decimal.Decimal("0"), output_field=DecimalField()),
                    revenue=Coalesce(Sum("line_total"), decimal.Decimal("0"), output_field=DecimalField()),
                )
                .order_by("-revenue")[:5]
            )
            results.append({
                "warehouse_id": str(wid),
                "warehouse_name": row["warehouse__name"],
                "total_revenue": str(row["total_revenue"]),
                "invoice_count": row["invoice_count"],
                "top_products": [
                    {
                        "product_name": p["product__name"],
                        "units_sold": str(p["units"]),
                        "revenue": str(p["revenue"]),
                    }
                    for p in top_products
                ],
            })

        return Response({"period": period, "results": results})

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

        qs = SaleItem.objects.filter(invoice__organisation=org, product=product)
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        if date_from:
            qs = qs.filter(invoice__issue_date__gte=date_from)
        if date_to:
            qs = qs.filter(invoice__issue_date__lte=date_to)
        items = (
            qs.select_related(
                "invoice",
                "invoice__customer",
                "invoice__warehouse",
                "invoice__created_by",
            )
            .order_by("-invoice__issue_date")[:500]
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
        from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
        from django.db.models.functions import Coalesce

        org = self._get_organisation()
        qs = InvoiceFolder.objects.filter(organisation=org)
        parent = self.request.query_params.get('parent')
        if parent == 'null':
            qs = qs.filter(parent__isnull=True)
        elif parent:
            qs = qs.filter(parent_id=parent)
        # Per-row counts as subqueries — avoids 2 queries per folder (N+1).
        children_sq = (InvoiceFolder.objects.filter(parent=OuterRef('pk'))
                       .values('parent').annotate(c=Count('id')).values('c')[:1])
        invoices_sq = (Invoice.objects.filter(folder=OuterRef('pk'))
                       .values('folder').annotate(c=Count('id')).values('c')[:1])
        return qs.annotate(
            _children_count=Coalesce(Subquery(children_sq, output_field=IntegerField()), Value(0, output_field=IntegerField())),
            _invoices_count=Coalesce(Subquery(invoices_sq, output_field=IntegerField()), Value(0, output_field=IntegerField())),
        )

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
    permission_classes = [IsAuthenticated, IsStaff, _PlanRecurring]

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
                # Recurring invoices are billed ahead (subscription-style): create the
                # invoice now regardless of on-hand stock. Stock deduction + GL posting
                # are deferred until the goods are actually fulfilled (call
                # SaleService.fulfill_invoice later). This prevents "Insufficient stock"
                # from blocking generation of an otherwise valid recurring invoice.
                defer_fulfillment=True,
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
        except (ValueError, DjangoValidationError, DRFValidationError, PermissionDenied) as e:
            # Expected business-rule failures (e.g. insufficient stock, locked
            # period, invalid product). Surface the real message so the user can
            # act on it instead of seeing a generic "unexpected error".
            logger.warning("generate_now rejected: %s", e)
            detail = e.messages[0] if hasattr(e, "messages") and e.messages else str(e)
            return Response({'error': detail or 'Could not generate invoice'}, status=400)
        except Exception as e:
            logger.exception("generate_now failed")
            return Response({'error': f"[{type(e).__name__}] {e}"}, status=400)



class LocationViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """CRUD for sales locations / branches."""

    serializer_class = LocationSerializer
    permission_classes = [IsStaff, IsOwnerOrAdmin]

    def get_queryset(self):
        return Location.objects.filter(organisation=self._get_organisation())

    @action(detail=False, methods=["get"], url_path="sales_analytics")
    def sales_analytics(self, request):
        """GET /sales/locations/sales_analytics/?period=month
        Returns revenue totals grouped by sales location (Invoice.location).
        """
        from django.db.models import Sum, Count, DecimalField
        from django.db.models.functions import Coalesce
        import decimal

        org = self._get_organisation()
        period = request.query_params.get("period", "month")

        today = timezone.now().date()
        if period == "today":
            date_from = today
        elif period == "week":
            date_from = today - datetime.timedelta(days=7)
        elif period == "year":
            date_from = today - datetime.timedelta(days=365)
        elif period == "all":
            date_from = None
        else:
            date_from = today - datetime.timedelta(days=30)

        active_statuses = [
            Invoice.Status.CONFIRMED, Invoice.Status.PAID,
            Invoice.Status.PARTIALLY_PAID, Invoice.Status.OVERDUE,
            Invoice.Status.CREDIT,
        ]
        qs = Invoice.objects.filter(organisation=org, status__in=active_statuses)
        if date_from:
            qs = qs.filter(issue_date__gte=date_from)

        location_totals = (
            qs.values("location__id", "location__name")
            .annotate(
                total_revenue=Coalesce(Sum("total_amount"), decimal.Decimal("0"), output_field=DecimalField()),
                invoice_count=Count("id"),
            )
            .order_by("-total_revenue")
        )

        results = []
        for row in location_totals:
            lid = row["location__id"]
            item_qs = SaleItem.objects.filter(
                invoice__organisation=org,
                invoice__status__in=active_statuses,
                invoice__location_id=lid,
            )
            if date_from:
                item_qs = item_qs.filter(invoice__issue_date__gte=date_from)
            top_products = (
                item_qs
                .values("product__name")
                .annotate(
                    units=Coalesce(Sum("quantity"), decimal.Decimal("0"), output_field=DecimalField()),
                    revenue=Coalesce(Sum("line_total"), decimal.Decimal("0"), output_field=DecimalField()),
                )
                .order_by("-revenue")[:5]
            )
            results.append({
                "location_id": str(lid) if lid else None,
                "location_name": row["location__name"] or "No Location",
                "total_revenue": str(row["total_revenue"]),
                "invoice_count": row["invoice_count"],
                "top_products": [
                    {
                        "product_name": p["product__name"],
                        "units_sold": str(p["units"]),
                        "revenue": str(p["revenue"]),
                    }
                    for p in top_products
                ],
            })

        return Response({"period": period, "results": results})
