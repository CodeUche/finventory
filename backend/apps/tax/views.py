"""Tax engine API views."""

from decimal import Decimal, ROUND_HALF_UP

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsAccountant, IsOwnerOrAdmin

from .models import TaxBracket, TaxClass, TaxConfig, TaxReturn, ExciseDuty, WHTRate, WHTTransaction
from .serializers import (
    IncomeTaxCalculateSerializer,
    TaxBracketSerializer,
    TaxClassSerializer,
    TaxConfigSerializer,
    TaxReturnSerializer,
    VATReportSerializer,
    ExciseDutySerializer,
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
