"""Tax engine API views."""

from decimal import Decimal, ROUND_HALF_UP

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsAccountant, IsOwnerOrAdmin
from apps.core.permissions import requires_module
# The owner's per-person ticks, enforced server-side (H-2). Mirrors
# useModuleAccess.ts: owners and admins bypass; for everyone else no
# record means no access, and only what was granted is granted.
_ModAccess_tax = requires_module("tax")


from .models import (
    CapitalAllowanceClaim, DeferredTaxItem, ExciseDuty,
    RelatedPartyTransaction, TaxBracket, TaxClass, TaxConfig, TaxObligation, TaxReturn,
    VATTransaction, WHTCertificate, WHTRate, WHTTransaction,
)
from .serializers import (
    CapitalAllowanceClaimSerializer,
    DeferredTaxItemSerializer,
    ExciseDutySerializer,
    IncomeTaxCalculateSerializer,
    RelatedPartyTransactionSerializer,
    TaxBracketSerializer,
    TaxClassSerializer,
    TaxConfigSerializer,
    TaxObligationSerializer,
    TaxReturnSerializer,
    VATReportSerializer,
    VATReconciliationSerializer,
    VATTransactionSerializer,
    WHTCertificateSerializer,
    WHTRateSerializer,
    WHTTransactionSerializer,
    _validate_bracket_set,
)
from .services import TaxService


class TaxClassViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Manage VAT/sales tax classes assigned to products."""

    queryset = TaxClass.objects.filter(is_active=True)
    serializer_class = TaxClassSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _ModAccess_tax]


class TaxConfigViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Manage tax configurations (country-specific schedules)."""

    queryset = TaxConfig.objects.filter(is_active=True)
    serializer_class = TaxConfigSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin, _ModAccess_tax]

    @action(detail=False, methods=["post"])
    def calculate_income_tax(self, request):
        """
        POST /api/v1/tax/configs/calculate_income_tax/

        Calculate income tax for a given income.
        Body: { "income": 5000000, "tax_year": 2024 }
        """
        serializer = IncomeTaxCalculateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            result = TaxService.calculate_income_tax(
                organisation=request.organisation,
                income=d["income"],
                tax_year=d.get("tax_year"),
                allowances=d.get("allowances"),
                tax_type=d.get("tax_type"),
                gross_turnover=d.get("gross_turnover"),
                fixed_assets=d.get("fixed_assets"),
            )
            return Response(result)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)

    @action(detail=False, methods=["post"])
    def vat_report(self, request):
        """POST /api/v1/tax/configs/vat_report/ — VAT for a period."""
        serializer = VATReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        result = TaxService.calculate_vat_report(
            organisation=request.organisation,
            period_start=d["period_start"],
            period_end=d["period_end"],
        )
        return Response(result)

    @action(detail=True, methods=["put"])
    def brackets(self, request, pk=None):
        """
        PUT /api/v1/tax/configs/{id}/brackets/
        Replace all tax brackets for this config.
        Body: [{ lower_bound, upper_bound, rate, cumulative_tax_below }, ...]
        """
        config = self.get_object()
        serializer = TaxBracketSerializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        _validate_bracket_set(serializer.validated_data)
        config.brackets.all().delete()
        TaxBracket.objects.bulk_create([
            TaxBracket(config=config, **b) for b in serializer.validated_data
        ])
        return Response(TaxBracketSerializer(config.brackets.all(), many=True).data)


class TaxReturnViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Manage tax returns."""

    queryset = TaxReturn.objects.select_related("config")
    serializer_class = TaxReturnSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _ModAccess_tax]

    @action(detail=True, methods=["post"])
    def file(self, request, pk=None):
        """POST /api/v1/tax/returns/{id}/file/ — Mark return as filed."""
        from django.utils import timezone

        tax_return = self.get_object()
        if tax_return.status != TaxReturn.Status.DRAFT:
            return Response({"error": "Only draft returns can be filed."}, status=400)

        tax_return.status = TaxReturn.Status.FILED
        tax_return.filed_at = timezone.now()
        tax_return.save(update_fields=["status", "filed_at"])
        return Response(TaxReturnSerializer(tax_return).data)


class ExciseDutyViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Manage excise duty rates."""

    serializer_class = ExciseDutySerializer
    permission_classes = [IsAuthenticated, IsAccountant, _ModAccess_tax]

    def get_queryset(self):
        org = self._get_organisation()
        return ExciseDuty.objects.filter(organisation=org)


class WHTRateViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Manage withholding tax rates."""

    serializer_class = WHTRateSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _ModAccess_tax]

    def get_queryset(self):
        org = self._get_organisation()
        return WHTRate.objects.filter(organisation=org)


class WHTTransactionViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Manage withholding tax transactions."""

    serializer_class = WHTTransactionSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _ModAccess_tax]

    def get_queryset(self):
        org = self._get_organisation()
        return WHTTransaction.objects.filter(organisation=org)

    def _compute_wht(self, gross, rate_percent):
        """Return (wht_amount, net_amount) from gross and rate."""
        gross = Decimal(str(gross))
        rate = Decimal(str(rate_percent))
        wht = (gross * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return wht, gross - wht

    def perform_create(self, serializer):
        org = self._get_organisation()
        d = serializer.validated_data
        wht_amount, net_amount = self._compute_wht(d["gross_amount"], d["wht_rate_percent"])
        serializer.save(organisation=org, wht_amount=wht_amount, net_amount=net_amount)

    def perform_update(self, serializer):
        d = serializer.validated_data
        # Recompute if gross or rate changed
        gross = d.get("gross_amount", serializer.instance.gross_amount)
        rate = d.get("wht_rate_percent", serializer.instance.wht_rate_percent)
        wht_amount, net_amount = self._compute_wht(gross, rate)
        serializer.save(wht_amount=wht_amount, net_amount=net_amount)

    @action(detail=True, methods=["post"])
    def remit(self, request, pk=None):
        """
        POST /api/v1/tax/wht-transactions/{id}/remit/
        Mark WHT as remitted and auto-generate a credit certificate.
        Body: { "remittance_reference": "TXN-REF", "notes": "..." }
        """
        from datetime import date as _date
        import uuid as _uuid

        txn = self.get_object()
        if txn.status == WHTTransaction.REMITTED:
            return Response({"error": "Already remitted."}, status=400)

        ref = request.data.get("remittance_reference", "")
        notes = request.data.get("notes", "")

        txn.status = WHTTransaction.REMITTED
        txn.save(update_fields=["status"])

        # Generate certificate number: WHT-<4-char-org-prefix>-<8-char-uuid>
        org = request.organisation
        prefix = str(org.id)[:4].upper()
        cert_num = f"WHT-{prefix}-{str(_uuid.uuid4())[:8].upper()}"

        cert = WHTCertificate.objects.create(
            organisation=org,
            wht_transaction=txn,
            certificate_number=cert_num,
            issued_date=_date.today(),
            remittance_reference=ref,
            notes=notes,
        )
        return Response({
            "message": "WHT marked as remitted and certificate issued.",
            "certificate": WHTCertificateSerializer(cert).data,
            "transaction": WHTTransactionSerializer(txn).data,
        })

    @action(detail=True, methods=["get"], url_path="certificate_pdf")
    def certificate_pdf(self, request, pk=None):
        """
        GET /api/v1/tax/wht-transactions/{id}/certificate_pdf/
        Download the WHT Credit Note (Form WHT 03) as a PDF.
        """
        from datetime import date as _date
        import io as _io
        from django.http import HttpResponse as _HR
        from reportlab.pdfgen.canvas import Canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm

        txn = self.get_object()
        if not hasattr(txn, 'certificate'):
            return Response({"error": "No certificate issued — call /remit/ first."}, status=404)

        cert = txn.certificate
        org = request.organisation
        org_name = (getattr(org, 'invoice_company_name', None) or org.name or '').strip()

        buf = _io.BytesIO()
        c = Canvas(buf, pagesize=A4)
        pw, ph = A4

        brand = colors.HexColor(f"#{(getattr(org,'brand_color',None) or '').lstrip('#') or '1E3A5F'}")

        # Header bar
        c.setFillColor(brand)
        c.rect(0, ph - 30 * mm, pw, 30 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(pw / 2, ph - 18 * mm, "WITHHOLDING TAX CREDIT NOTE")
        c.setFont("Helvetica", 9)
        c.drawCentredString(pw / 2, ph - 24 * mm, "(Form WHT 03 — in accordance with FIRS regulations)")

        # Cert number box
        c.setFillColor(colors.HexColor("#F8FAFC"))
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.rect(15 * mm, ph - 55 * mm, pw - 30 * mm, 18 * mm, fill=1)
        c.setFillColor(colors.HexColor("#1E3A5F"))
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(pw / 2, ph - 45 * mm, f"Certificate No: {cert.certificate_number}")
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor("#6B7280"))
        c.drawCentredString(pw / 2, ph - 51 * mm, f"Issued: {cert.issued_date.strftime('%d %B %Y')}")

        # Details table
        def row(y, label, value, bold_val=False):
            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(colors.HexColor("#374151"))
            c.drawString(20 * mm, y, label)
            if bold_val:
                c.setFont("Helvetica-Bold", 9)
                c.setFillColor(brand)
            else:
                c.setFont("Helvetica", 9)
                c.setFillColor(colors.HexColor("#111827"))
            c.drawString(90 * mm, y, str(value))

        y = ph - 70 * mm
        gap = 9 * mm
        row(y, "Deducting Entity:", org_name)
        row(y - gap, "Payee / Counterparty:", txn.counterparty_name)
        row(y - 2 * gap, "Payee TIN:", txn.tin or "—")
        row(y - 3 * gap, "Transaction Type:", txn.wht_rate.transaction_type)
        row(y - 4 * gap, "Transaction Date:", txn.transaction_date.strftime('%d %B %Y'))
        row(y - 5 * gap, "Gross Amount:", f"₦{float(txn.gross_amount):,.2f}")
        row(y - 6 * gap, "WHT Rate:", f"{txn.wht_rate_percent}%")
        row(y - 7 * gap, "WHT Amount Deducted:", f"₦{float(txn.wht_amount):,.2f}", bold_val=True)
        row(y - 8 * gap, "Net Amount Paid:", f"₦{float(txn.net_amount):,.2f}")
        row(y - 9 * gap, "Remittance Reference:", cert.remittance_reference or "—")

        # Separator
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.line(15 * mm, y - 10.5 * gap, pw - 15 * mm, y - 10.5 * gap)

        # Note
        note_y = y - 11.5 * gap
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.HexColor("#6B7280"))
        c.drawString(20 * mm, note_y,
            "This certificate confirms that Withholding Tax has been deducted and remitted to FIRS on your behalf.")
        c.drawString(20 * mm, note_y - 5 * mm,
            "Present this certificate when filing your annual income tax return to claim the WHT credit.")

        # Footer accent
        c.setFillColor(brand)
        c.rect(0, 0, pw, 4 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica", 7)
        c.drawCentredString(pw / 2, 1.5 * mm, f"{org_name}  ·  Generated by Audity  ·  {_date.today().strftime('%d %b %Y')}")

        c.save()
        buf.seek(0)
        resp = _HR(buf.getvalue(), content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="WHT-Certificate-{cert.certificate_number}.pdf"'
        return resp


class WHTCertificateViewSet(TenantFilterMixin, viewsets.ReadOnlyModelViewSet):
    """GET /api/v1/tax/wht-certificates/ — list issued WHT credit notes."""
    serializer_class = WHTCertificateSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _ModAccess_tax]

    def get_queryset(self):
        org = self._get_organisation()
        return WHTCertificate.objects.filter(organisation=org).select_related('wht_transaction', 'wht_transaction__wht_rate')


class VATTransactionViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """CRUD /api/v1/tax/vat-transactions/ — per-transaction VAT ITC tracking."""
    serializer_class = VATTransactionSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _ModAccess_tax]

    def get_queryset(self):
        org = self._get_organisation()
        qs = VATTransaction.objects.filter(organisation=org)
        direction = self.request.query_params.get('direction')
        if direction in ('input', 'output'):
            qs = qs.filter(direction=direction)
        period_start = self.request.query_params.get('period_start')
        period_end = self.request.query_params.get('period_end')
        if period_start:
            qs = qs.filter(period_end__gte=period_start)
        if period_end:
            qs = qs.filter(period_start__lte=period_end)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(organisation=self._get_organisation())
        # A hand-typed row changes the VAT figure, so it leaves an audit trail.
        try:
            from apps.core.models import AuditLog
            AuditLog.log(
                action=AuditLog.CREATE, user=self.request.user, organisation=obj.organisation,
                model_name='VATTransaction', object_id=str(obj.id), object_repr=str(obj),
                changes={'manual_vat_adjustment': {'old': None, 'new': f"{obj.direction} {obj.vat_amount}"}},
                request=self.request,
            )
        except Exception:
            pass

    # ── Live view of the one VAT calculation ────────────────────────────────
    # Nothing here stores a snapshot any more. The list, the worksheet and the
    # PDF all read apps.tax.vat.compute_vat, so they cannot drift from the
    # reports. Rows a person typed in (VATTransaction) are shown as manual
    # adjustments and counted in the net.

    @staticmethod
    def _period(params):
        from datetime import date as _date, datetime
        from apps.tax.vat import month_range
        ps, pe = params.get("period_start"), params.get("period_end")
        try:
            if ps and pe:
                return datetime.strptime(ps, "%Y-%m-%d").date(), datetime.strptime(pe, "%Y-%m-%d").date()
        except ValueError:
            return None
        if ps or pe:
            return None
        today = _date.today()
        return month_range(today.year, today.month)

    @staticmethod
    def _row(line):
        return {
            "id": line["document_id"] if line["kind"] == "manual" else f"{line['kind']}:{line['document_id']}",
            "kind": line["kind"],
            "direction": line["direction"],
            "period_start": line["date"],
            "period_end": line["date"],
            "counterparty_name": line["counterparty_name"],
            "counterparty_tin": line["counterparty_tin"],
            "net_amount": str(line["net_amount"]),
            "vat_amount": str(line["vat_amount"]),
            "vat_rate": str(line["vat_rate"]) if line["vat_rate"] is not None else "",
            "is_claimable": line["is_claimable"] if line["direction"] == "input" else True,
            "reason": line["reason"],
            "source_ref": line["source_ref"],
            "confirmation": line.get("confirmation", ""),
            "supplier_id": line.get("supplier_id", ""),
            "notes": line["notes"] or line["reason"],
            "created_at": None,
        }

    def list(self, request, *args, **kwargs):
        """GET /api/v1/tax/vat-transactions/?period_start=&period_end=&direction=
        One live row per document (default: the current month)."""
        from apps.tax.vat import compute_vat
        period = self._period(request.query_params)
        if period is None:
            return Response({"error": "Invalid or incomplete period; send both period_start and period_end as YYYY-MM-DD."}, status=400)
        vat = compute_vat(self._get_organisation(), *period, with_reconciliation=False, with_previous_methods=False)
        rows = [self._row(l) for l in vat["lines"]]
        direction = request.query_params.get("direction")
        if direction in ("input", "output"):
            rows = [r for r in rows if r["direction"] == direction]
        # Same envelope the paginated list always had, so existing clients keep working.
        return Response({"count": len(rows), "next": None, "previous": None, "results": rows})

    @action(detail=False, methods=["get"])
    def worksheet(self, request):
        """GET /api/v1/tax/vat-transactions/worksheet/ — totals, turnover, reconciliation and rows."""
        from apps.tax.vat import compute_vat
        period = self._period(request.query_params)
        if period is None:
            return Response({"error": "Invalid or incomplete period; send both period_start and period_end as YYYY-MM-DD."}, status=400)
        vat = compute_vat(self._get_organisation(), *period)
        vat["rows"] = [self._row(l) for l in vat.pop("lines")]
        return Response(vat)

    @action(detail=False, methods=["get"])
    def comparison(self, request):
        """GET /api/v1/tax/vat-transactions/comparison/ — closed months of the last year:
        what the old Reports and Tax screens showed against the new figure."""
        from apps.tax.vat import comparison_table
        return Response({"rows": comparison_table(self._get_organisation())})

    @action(detail=False, methods=["post"])
    def set_supplier_vat(self, request):
        """POST /api/v1/tax/vat-transactions/set_supplier_vat/
        Quick action from the needs-attention list. Body: {supplier_id, vat_registered?, tax_id?}.
        Same tax-module gate as the rest of this page; audited."""
        from apps.suppliers.models import Supplier
        org = self._get_organisation()
        try:
            sup = Supplier.objects.get(id=request.data.get("supplier_id"), organisation=org)
        except Exception:
            return Response({"error": "Supplier not found."}, status=404)
        changes = {}
        vr = request.data.get("vat_registered")
        if vr is not None:
            if vr not in ("yes", "no", "unknown"):
                return Response({"error": "vat_registered must be yes, no or unknown."}, status=400)
            changes["vat_registered"] = {"old": sup.vat_registered, "new": vr}
            sup.vat_registered = vr
        tin = request.data.get("tax_id")
        if tin is not None:
            tin = str(tin).strip()[:100]
            changes["tax_id"] = {"old": sup.tax_id, "new": tin}
            sup.tax_id = tin
        if not changes:
            return Response({"error": "Nothing to change."}, status=400)
        sup.save()
        try:
            from apps.core.models import AuditLog
            AuditLog.log(action=AuditLog.UPDATE, user=request.user, organisation=org, model_name='Supplier',
                         object_id=str(sup.id), object_repr=str(sup), changes=changes, request=request)
        except Exception:
            pass
        return Response({"id": str(sup.id), "vat_registered": sup.vat_registered, "tax_id": sup.tax_id})

    @action(detail=False, methods=["post"])
    def sync_from_period(self, request):
        """
        POST /api/v1/tax/vat-transactions/sync_from_period/
        Kept so existing clients keep working. It no longer stores anything: the
        VAT ITC tab is a live read of the one VAT calculation. Returns the live
        totals for the period.
        Body: { "period_start": "2025-01-01", "period_end": "2025-01-31" }
        """
        from apps.tax.vat import compute_vat
        ser = VATReconciliationSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vat = compute_vat(
            self._get_organisation(), ser.validated_data['period_start'], ser.validated_data['period_end'],
            with_reconciliation=False, with_previous_methods=False,
        )
        n_out = sum(1 for l in vat["lines"] if l["direction"] == "output")
        n_in = sum(1 for l in vat["lines"] if l["direction"] == "input")
        return Response({
            "synced_output": 0,
            "synced_input": 0,
            "live_output_documents": n_out,
            "live_input_documents": n_in,
            "output_vat": vat["output_vat"],
            "input_vat_recoverable": vat["input_vat_recoverable"],
            "input_vat_irrecoverable": vat["input_vat_irrecoverable"],
            "net_vat_payable": vat["net_vat_payable"],
            "message": "VAT figures are read live from your sales and bills; nothing needs syncing.",
        })

    @action(detail=False, methods=["get"])
    def export_pdf(self, request):
        """
        GET /api/v1/tax/vat-transactions/export_pdf/?period_start=YYYY-MM-DD&period_end=YYYY-MM-DD
        VAT worksheet PDF, built from the same calculation as every VAT figure.
        """
        from datetime import date as _date
        from django.http import HttpResponse

        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from xml.sax.saxutils import escape
        except ImportError:
            return Response({"error": "ReportLab not installed."}, status=500)

        if not request.query_params.get("period_start") or not request.query_params.get("period_end"):
            return Response({"error": "period_start and period_end query params required."}, status=400)
        period = self._period(request.query_params)
        if period is None:
            return Response({"error": "Invalid date format; use YYYY-MM-DD."}, status=400)
        p_start, p_end = period

        from apps.tax.vat import compute_vat
        org = request.organisation
        vat = compute_vat(org, p_start, p_end, with_reconciliation=False, with_previous_methods=False)

        import io
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm, leftMargin=20*mm, rightMargin=20*mm)
        styles = getSampleStyleSheet()
        story = []
        story.append(Paragraph(f"<b>VAT Worksheet</b> — {escape(org.name)}", styles['Title']))
        if getattr(org, "tax_id", ""):
            story.append(Paragraph(f"TIN: {escape(org.tax_id)}", styles['Normal']))
        story.append(Paragraph(
            f"Period: {p_start.strftime('%d %b %Y')} to {p_end.strftime('%d %b %Y')}. {escape(vat['due_note'])}",
            styles['Normal']))
        story.append(Paragraph(f"Generated: {_date.today().strftime('%d %b %Y')}", styles['Normal']))
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph(f"<i>{escape(vat['worksheet_note'])}</i>", styles['Normal']))
        for w in vat["warnings"]:
            story.append(Paragraph(f"<b>{escape(w)}</b>", styles['Normal']))
        for n in vat["notes"]:
            if n != vat["bill_treatment_note"]:
                story.append(Paragraph(escape(n), styles['Normal']))
        story.append(Spacer(1, 6*mm))

        def m(v):
            return f"{v:,.2f}"

        summary_data = [
            ["", "Amount (₦)"],
            ["Output VAT on sales", m(vat["output_vat_on_sales"])],
            ["Less: VAT on sales returns / credit notes", m(vat["output_vat_returns"])],
            ["Manual output adjustments", m(vat["output_vat_manual_adjustments"])],
            ["Output VAT", m(vat["output_vat"])],
            ["Recoverable input VAT", m(vat["input_vat_recoverable"])],
            ["Net VAT payable / (refund or carry-forward)", m(vat["net_vat_payable"])],
            ["Irrecoverable input VAT (a cost, not claimed)", m(vat["input_vat_irrecoverable"])],
            [vat["input_vat_awaiting_supplier_invoice_label"], m(vat["input_vat_awaiting_supplier_invoice"])],
        ] + [[vat["turnover_labels"][k], m(v)] for k, v in vat["turnover"].items()]
        st = Table(summary_data, colWidths=[110*mm, 55*mm])
        st.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a5f')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 4), (-1, 4), 'Helvetica-Bold'),
            ('FONTNAME', (0, 6), (-1, 6), 'Helvetica-Bold'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(st)
        story.append(Spacer(1, 6*mm))
        story.append(Spacer(1, 2*mm))

        def _tx_table(title, lines):
            story.append(Paragraph(f"<b>{title}</b>", styles['Heading3']))
            if not lines:
                story.append(Paragraph("No documents in this period.", styles['Normal']))
                story.append(Spacer(1, 4*mm))
                return
            rows = [["Date", "Counterparty", "TIN", "Ref", "Net (₦)", "VAT (₦)", "Claim", "Note"]]
            for l in lines:
                rows.append([
                    l["date"] or "", escape((l["counterparty_name"] or "—")[:24]),
                    escape((l["counterparty_tin"] or "—")[:14]), escape((l["source_ref"] or "—")[:16]),
                    m(l["net_amount"]), m(l["vat_amount"]),
                    ("yes" if l["is_claimable"] else "no") if l["direction"] == "input" else "",
                    Paragraph(escape(l["reason"] or ""), styles['BodyText']),
                ])
            t = Table(rows, colWidths=[18*mm, 30*mm, 20*mm, 22*mm, 22*mm, 20*mm, 10*mm, 28*mm], repeatRows=1)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3b5998')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7),
                ('ALIGN', (4, 0), (5, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#cccccc')),
            ]))
            story.append(t)
            story.append(Spacer(1, 6*mm))

        _tx_table("Output VAT documents (sales, credit notes, adjustments)",
                  [l for l in vat["lines"] if l["direction"] == "output"])
        _tx_table("Input VAT documents (bills, purchase returns, adjustments)",
                  [l for l in vat["lines"] if l["direction"] == "input"])

        if vat["needs_attention"]:
            story.append(Paragraph(f"<b>Needs attention ({vat['needs_attention_count']})</b>", styles['Heading3']))
            story.append(Paragraph("Bills with VAT where the supplier's VAT status is not known or no TIN is on record.", styles['Normal']))
            for a in vat["needs_attention"]:
                story.append(Paragraph(escape(f"{a['bill_number']} — {a['supplier_name']}: {m(a['vat_amount'])} ({a['reason']})"), styles['Normal']))
            story.append(Spacer(1, 4*mm))
        if vat["ignored_duplicates"]:
            story.append(Paragraph(f"{len(vat['ignored_duplicates'])} stored row(s) ignored as duplicates of documents already counted live.", styles['Normal']))
        story.append(Spacer(1, 4*mm))
        story.append(Paragraph(f"<i>{escape(vat['bill_treatment_note'])}</i>", styles['Normal']))

        doc.build(story)
        buffer.seek(0)
        filename = f"VAT_Worksheet_{p_start.isoformat()}_{p_end.isoformat()}.pdf"
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class TaxObligationViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """
    CRUD /api/v1/tax/obligations/
    Tax compliance calendar — list, create, update obligations.
    Auto-generated obligations (VAT, PAYE) are created by Celery Beat.
    """
    serializer_class = TaxObligationSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _ModAccess_tax]

    def get_queryset(self):
        org = self._get_organisation()
        qs = TaxObligation.objects.filter(organisation=org)
        year = self.request.query_params.get('year')
        obligation_type = self.request.query_params.get('type')
        status_filter = self.request.query_params.get('status')
        if year:
            qs = qs.filter(period_year=year)
        if obligation_type:
            qs = qs.filter(obligation_type=obligation_type)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def perform_create(self, serializer):
        serializer.save(organisation=self._get_organisation(), is_auto_generated=False)

    @action(detail=True, methods=['post'])
    def mark_filed(self, request, pk=None):
        """POST /api/v1/tax/obligations/{id}/mark_filed/ — mark as filed."""
        from datetime import date as _date
        obligation = self.get_object()
        obligation.status = TaxObligation.FILED
        obligation.filed_date = _date.today()
        obligation.payment_reference = request.data.get('payment_reference', obligation.payment_reference)
        obligation.save()
        return Response(TaxObligationSerializer(obligation).data)

    @action(detail=True, methods=['post'])
    def mark_paid(self, request, pk=None):
        """POST /api/v1/tax/obligations/{id}/mark_paid/ — mark as paid."""
        from datetime import date as _date
        obligation = self.get_object()
        obligation.status = TaxObligation.PAID
        obligation.amount_due = request.data.get('amount_due', obligation.amount_due)
        obligation.payment_reference = request.data.get('payment_reference', obligation.payment_reference)
        if not obligation.filed_date:
            obligation.filed_date = _date.today()
        obligation.save()
        return Response(TaxObligationSerializer(obligation).data)

    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        """GET /api/v1/tax/obligations/upcoming/ — next 60 days of obligations."""
        from datetime import date as _date, timedelta
        today = _date.today()
        org = self._get_organisation()
        obligations = TaxObligation.objects.filter(
            organisation=org,
            due_date__gte=today,
            due_date__lte=today + timedelta(days=60),
        ).order_by('due_date')
        return Response(TaxObligationSerializer(obligations, many=True).data)

    @action(detail=False, methods=['post'])
    def generate_now(self, request):
        """POST /api/v1/tax/obligations/generate_now/ — manually trigger obligation generation for a period."""
        from apps.tax.tasks import generate_monthly_vat_obligations, generate_monthly_paye_obligations
        generate_monthly_vat_obligations.delay()
        generate_monthly_paye_obligations.delay()
        return Response({"message": "Obligation generation queued."})


class CapitalAllowanceClaimViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """CRUD /api/v1/tax/capital-allowances/ — capital allowance schedule per asset per year."""
    serializer_class = CapitalAllowanceClaimSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _ModAccess_tax]

    def get_queryset(self):
        org = self._get_organisation()
        qs = CapitalAllowanceClaim.objects.filter(organisation=org)
        year = self.request.query_params.get('year')
        if year:
            qs = qs.filter(tax_year=year)
        return qs

    def perform_create(self, serializer):
        serializer.save(organisation=self._get_organisation())

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """GET /api/v1/tax/capital-allowances/summary/?year=2025 — total CA by asset class."""
        from django.db.models import Sum
        org = self._get_organisation()
        year = request.query_params.get('year')
        qs = CapitalAllowanceClaim.objects.filter(organisation=org)
        if year:
            qs = qs.filter(tax_year=year)
        summary = qs.values('asset_class').annotate(
            total_cost=Sum('cost'),
            total_initial=Sum('initial_allowance'),
            total_annual=Sum('annual_allowance'),
            total_ca=Sum('total_allowance'),
            total_closing_wdv=Sum('closing_tax_written_down_value'),
        )
        return Response(list(summary))


class DeferredTaxItemViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """CRUD /api/v1/tax/deferred-tax/ — deferred tax schedule (IAS 12)."""
    serializer_class = DeferredTaxItemSerializer
    permission_classes = [IsAuthenticated, IsAccountant, _ModAccess_tax]

    def get_queryset(self):
        org = self._get_organisation()
        qs = DeferredTaxItem.objects.filter(organisation=org)
        year = self.request.query_params.get('year')
        if year:
            qs = qs.filter(tax_year=year)
        return qs

    def perform_create(self, serializer):
        org = self._get_organisation()
        instance = serializer.save(organisation=org)
        # Auto-post deferred tax GL journal (non-blocking)
        try:
            from apps.accounting.services import AccountingService
            AccountingService.post_deferred_tax_journal(org, instance, self.request.user)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("post_deferred_tax_journal failed: %s", exc)

    @action(detail=False, methods=['get'])
    def balance_sheet_impact(self, request):
        """GET /api/v1/tax/deferred-tax/balance_sheet_impact/?year=2025 — net DTA and DTL for B/S."""
        from django.db.models import Sum
        org = self._get_organisation()
        year = request.query_params.get('year')
        qs = DeferredTaxItem.objects.filter(organisation=org, is_recognised=True)
        if year:
            qs = qs.filter(tax_year=year)
        dta = qs.filter(deferred_type='dta').aggregate(total=Sum('deferred_tax_amount'))['total'] or 0
        dtl = qs.filter(deferred_type='dtl').aggregate(total=Sum('deferred_tax_amount'))['total'] or 0
        return Response({'deferred_tax_asset': dta, 'deferred_tax_liability': dtl, 'net': float(dta) - float(dtl)})


class RelatedPartyTransactionViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """CRUD /api/v1/tax/transfer-pricing/ — related party transactions for TP disclosure."""
    serializer_class = RelatedPartyTransactionSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin, _ModAccess_tax]

    def get_queryset(self):
        org = self._get_organisation()
        qs = RelatedPartyTransaction.objects.filter(organisation=org)
        year = self.request.query_params.get('year')
        if year:
            qs = qs.filter(tax_year=year)
        return qs

    def perform_create(self, serializer):
        serializer.save(organisation=self._get_organisation())

    @action(detail=False, methods=['get'])
    def disclosure_summary(self, request):
        """GET /api/v1/tax/transfer-pricing/disclosure_summary/?year=2025 — TP threshold check."""
        from django.db.models import Sum
        org = self._get_organisation()
        year = request.query_params.get('year')
        qs = RelatedPartyTransaction.objects.filter(organisation=org)
        if year:
            qs = qs.filter(tax_year=year)
        total = qs.aggregate(total=Sum('amount'))['total'] or 0
        threshold = 300_000_000
        return Response({
            'total_related_party_transactions': total,
            'disclosure_threshold': threshold,
            'disclosure_required': float(total) >= threshold,
            'transactions_requiring_adjustment': qs.filter(adjustment_required=True).count(),
        })
