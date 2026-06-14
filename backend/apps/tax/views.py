"""Tax engine API views."""

from decimal import Decimal, ROUND_HALF_UP

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsAccountant, IsOwnerOrAdmin

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
)
from .services import TaxService


class TaxClassViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Manage VAT/sales tax classes assigned to products."""

    queryset = TaxClass.objects.filter(is_active=True)
    serializer_class = TaxClassSerializer
    permission_classes = [IsAuthenticated, IsAccountant]


class TaxConfigViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Manage tax configurations (country-specific schedules)."""

    queryset = TaxConfig.objects.filter(is_active=True)
    serializer_class = TaxConfigSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

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
        config.brackets.all().delete()
        TaxBracket.objects.bulk_create([
            TaxBracket(config=config, **b) for b in serializer.validated_data
        ])
        return Response(TaxBracketSerializer(config.brackets.all(), many=True).data)


class TaxReturnViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Manage tax returns."""

    queryset = TaxReturn.objects.select_related("config")
    serializer_class = TaxReturnSerializer
    permission_classes = [IsAuthenticated, IsAccountant]

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
    permission_classes = [IsAuthenticated, IsAccountant]

    def get_queryset(self):
        org = self._get_organisation()
        return ExciseDuty.objects.filter(organisation=org)


class WHTRateViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Manage withholding tax rates."""

    serializer_class = WHTRateSerializer
    permission_classes = [IsAuthenticated, IsAccountant]

    def get_queryset(self):
        org = self._get_organisation()
        return WHTRate.objects.filter(organisation=org)


class WHTTransactionViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """Manage withholding tax transactions."""

    serializer_class = WHTTransactionSerializer
    permission_classes = [IsAuthenticated, IsAccountant]

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
    permission_classes = [IsAuthenticated, IsAccountant]

    def get_queryset(self):
        org = self._get_organisation()
        return WHTCertificate.objects.filter(organisation=org).select_related('wht_transaction', 'wht_transaction__wht_rate')


class VATTransactionViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """CRUD /api/v1/tax/vat-transactions/ — per-transaction VAT ITC tracking."""
    serializer_class = VATTransactionSerializer
    permission_classes = [IsAuthenticated, IsAccountant]

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
        serializer.save(organisation=self._get_organisation())

    @action(detail=False, methods=["post"])
    def sync_from_period(self, request):
        """
        POST /api/v1/tax/vat-transactions/sync_from_period/
        Auto-sync VAT transactions from sales invoices and bills for a given period.
        Body: { "period_start": "2025-01-01", "period_end": "2025-01-31" }
        """
        from decimal import Decimal as _Dec
        from django.db.models import Sum

        ser = VATReconciliationSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        p_start = ser.validated_data['period_start']
        p_end = ser.validated_data['period_end']
        org = request.organisation

        created_output = created_input = 0

        # Output VAT from sales
        from apps.sales.models import Invoice, SaleItem
        invoices = Invoice.objects.filter(
            organisation=org,
            issue_date__gte=p_start,
            issue_date__lte=p_end,
            status__in=['paid', 'confirmed', 'partially_paid', 'credit', 'overdue'],
        ).exclude(tax_amount=0)

        for inv in invoices:
            ref = inv.invoice_number
            if not VATTransaction.objects.filter(organisation=org, source_ref=ref, direction=VATTransaction.OUTPUT).exists():
                VATTransaction.objects.create(
                    organisation=org,
                    direction=VATTransaction.OUTPUT,
                    period_start=p_start,
                    period_end=p_end,
                    counterparty_name=inv.customer.name if inv.customer else '',
                    net_amount=_Dec(str(inv.total_amount)) - _Dec(str(inv.tax_amount or 0)),
                    vat_amount=_Dec(str(inv.tax_amount or 0)),
                    source_ref=ref,
                )
                created_output += 1

        # Input VAT from bills
        from apps.bills.models import Bill
        bills = Bill.objects.filter(
            organisation=org,
            issue_date__gte=p_start,
            issue_date__lte=p_end,
            status__in=[Bill.APPROVED, Bill.PAID, Bill.PARTIALLY_PAID],
        ).exclude(tax_amount=0)

        for bill in bills:
            ref = str(bill.id)[:12]
            if not VATTransaction.objects.filter(organisation=org, source_ref=ref, direction=VATTransaction.INPUT).exists():
                VATTransaction.objects.create(
                    organisation=org,
                    direction=VATTransaction.INPUT,
                    period_start=p_start,
                    period_end=p_end,
                    counterparty_name=bill.supplier.name if bill.supplier else '',
                    net_amount=_Dec(str(bill.subtotal or 0)),
                    vat_amount=_Dec(str(bill.tax_amount or 0)),
                    source_ref=ref,
                )
                created_input += 1

        return Response({
            "synced_output": created_output,
            "synced_input": created_input,
            "message": f"Synced {created_output} output + {created_input} input VAT transactions.",
        })


class TaxObligationViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    """
    CRUD /api/v1/tax/obligations/
    Tax compliance calendar — list, create, update obligations.
    Auto-generated obligations (VAT, PAYE) are created by Celery Beat.
    """
    serializer_class = TaxObligationSerializer
    permission_classes = [IsAuthenticated, IsAccountant]

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
    permission_classes = [IsAuthenticated, IsAccountant]

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
    permission_classes = [IsAuthenticated, IsAccountant]

    def get_queryset(self):
        org = self._get_organisation()
        qs = DeferredTaxItem.objects.filter(organisation=org)
        year = self.request.query_params.get('year')
        if year:
            qs = qs.filter(tax_year=year)
        return qs

    def perform_create(self, serializer):
        serializer.save(organisation=self._get_organisation())

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
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

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
