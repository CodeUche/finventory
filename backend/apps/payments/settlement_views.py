"""Card terminal settlement endpoints — import, match, review."""

import logging

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import BaseParser, FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import TenantFilterMixin
from apps.core.permissions import IsAccountant, IsStaff

from .settlement_models import SettlementBatch, SettlementLine
from .settlement_services import SettlementError, SettlementService

logger = logging.getLogger(__name__)

# A terminal export is a small text file; anything larger is a mistake.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


class RawTextParser(BaseParser):
    """Accept a CSV posted as a raw body rather than multipart.

    The desktop build routes requests through Tauri, whose IPC layer serialises
    FormData as application/x-www-form-urlencoded — the file never arrives. The
    app already works around that for images by posting raw bytes, so the
    settlement import accepts the same shape. Multipart still works for anything
    posting a normal browser form.
    """

    media_type = "text/csv"

    def parse(self, stream, media_type=None, parser_context=None):
        return stream.read().decode("utf-8-sig", errors="replace")


class RawPlainTextParser(RawTextParser):
    media_type = "text/plain"


class RawBinaryParser(RawTextParser):
    media_type = "application/octet-stream"


class SettlementBatchSerializer(serializers.ModelSerializer):
    matched_count = serializers.SerializerMethodField()
    unmatched_count = serializers.SerializerMethodField()

    class Meta:
        model = SettlementBatch
        fields = [
            "id", "provider", "source", "reference", "statement_date",
            "line_count", "total_amount", "note", "matched_count",
            "unmatched_count", "created_at",
        ]
        read_only_fields = fields

    def get_matched_count(self, obj) -> int:
        return obj.lines.filter(status=SettlementLine.Status.MATCHED).count()

    def get_unmatched_count(self, obj) -> int:
        return obj.lines.filter(status=SettlementLine.Status.UNMATCHED).count()


class SettlementLineSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    invoice_number = serializers.CharField(
        source="payment.invoice.invoice_number", read_only=True, default="",
    )
    payment_amount = serializers.DecimalField(
        source="payment.amount", max_digits=15, decimal_places=2,
        read_only=True, default=None,
    )

    class Meta:
        model = SettlementLine
        fields = [
            "id", "batch", "provider_reference", "paid_at", "amount", "fee",
            "terminal_id", "card_last4", "narration", "status", "status_label",
            "payment", "payment_amount", "invoice_number", "matched_automatically",
            "review_note", "created_at",
        ]
        read_only_fields = [
            f for f in fields if f not in ("payment", "review_note")
        ]


class SettlementBatchViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = SettlementBatchSerializer
    permission_classes = [IsAuthenticated, IsAccountant]
    http_method_names = ["get", "post", "head", "options"]
    parser_classes = [
        MultiPartParser, FormParser,
        RawTextParser, RawPlainTextParser, RawBinaryParser,
    ]

    def get_queryset(self):
        return SettlementBatch.objects.filter(organisation=self._get_organisation())

    @action(detail=False, methods=["post"])
    def upload(self, request):
        """Import a terminal export, then match it in the same call.

        Matching immediately is the point — a merchant uploads the day's file
        and wants to see what is left over, not to press a second button.
        """
        upload = request.FILES.get("file")
        name = ""
        if upload is not None:
            if upload.size > MAX_UPLOAD_BYTES:
                return Response(
                    {"error": "That file is too large to be a settlement export."}, status=400,
                )
            try:
                content = upload.read().decode("utf-8-sig", errors="replace")
            except Exception:
                return Response({"error": "That file could not be read as text."}, status=400)
            name = upload.name
        elif isinstance(request.data, str) and request.data.strip():
            # Raw body — the desktop path, see RawTextParser.
            content = request.data
            if len(content.encode("utf-8", errors="ignore")) > MAX_UPLOAD_BYTES:
                return Response(
                    {"error": "That file is too large to be a settlement export."}, status=400,
                )
            name = request.headers.get("X-File-Name", "")
        else:
            return Response({"error": "Choose the export file from your terminal."}, status=400)

        org = self._get_organisation()
        try:
            rows = SettlementService.parse_csv(content)
            batch = SettlementService.import_rows(
                org, rows,
                provider=(request.data.get("provider", "")
                          if hasattr(request.data, "get") else ""),
                reference=(name or "terminal export")[:120],
            )
            result = SettlementService.match_batch(batch)
        except SettlementError as exc:
            return Response({"error": str(exc)}, status=422)

        return Response(
            {**SettlementBatchSerializer(batch).data, **result},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def rematch(self, request, pk=None):
        """Try again — usually after the missing sales have been entered."""
        return Response(SettlementService.match_batch(self.get_object()))


class SettlementLineViewSet(TenantFilterMixin, viewsets.ModelViewSet):
    serializer_class = SettlementLineSerializer
    permission_classes = [IsAuthenticated, IsStaff]
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = ["status", "batch"]

    def get_queryset(self):
        return (
            SettlementLine.objects
            .filter(organisation=self._get_organisation())
            .select_related("payment", "payment__invoice", "batch")
        )

    @action(detail=False, methods=["get"])
    def summary(self, request):
        return Response(SettlementService.summary(self._get_organisation()))

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        from apps.sales.models import SalePayment
        payment = SalePayment.objects.filter(
            id=request.data.get("payment"), organisation=self._get_organisation(),
        ).first()
        if payment is None:
            return Response({"error": "That payment could not be found."}, status=404)
        try:
            line = SettlementService.assign(
                self.get_object(), payment, request.data.get("note", ""),
            )
        except SettlementError as exc:
            return Response({"error": str(exc)}, status=422)
        return Response(SettlementLineSerializer(line).data)

    @action(detail=True, methods=["post"])
    def other_income(self, request, pk=None):
        try:
            line = SettlementService.record_as_other_income(
                self.get_object(), request.user, request.data.get("note", ""),
            )
        except SettlementError as exc:
            return Response({"error": str(exc)}, status=422)
        return Response(SettlementLineSerializer(line).data)

    @action(detail=True, methods=["post"])
    def ignore(self, request, pk=None):
        try:
            line = SettlementService.ignore(self.get_object(), request.data.get("note", ""))
        except SettlementError as exc:
            return Response({"error": str(exc)}, status=422)
        return Response(SettlementLineSerializer(line).data)

    @action(detail=True, methods=["post"])
    def unmatch(self, request, pk=None):
        return Response(
            SettlementLineSerializer(SettlementService.unmatch(self.get_object())).data
        )

    @action(detail=False, methods=["get"])
    def candidates(self, request):
        """Card payments with no payout against them — what a human picks from."""
        from apps.sales.models import SalePayment
        payments = (
            SalePayment.objects
            .filter(organisation=self._get_organisation(), method__in=["pos", "card"])
            .exclude(settlement_lines__isnull=False)
            .select_related("invoice")
            .order_by("-received_at")[:100]
        )
        return Response({"results": [
            {
                "id": str(p.id),
                "amount": p.amount,
                "received_at": p.received_at,
                "method": p.method,
                "reference": p.reference,
                "invoice_number": p.invoice.invoice_number if p.invoice_id else "",
            }
            for p in payments
        ]})
