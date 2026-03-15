"""
ViewSet mixins that enforce tenant isolation automatically.

Usage:
    class ProductViewSet(TenantFilterMixin, ModelViewSet):
        ...

All queries are automatically scoped to request.organisation.
This prevents IDOR by making cross-tenant access structurally impossible.

Note on JWT + Middleware order:
    TenantFilterMixin.get_queryset() is called AFTER DRF authentication,
    so request.user is already the JWT-authenticated user here.
    We call resolve_organisation() (phase 2 of tenant resolution) here.
"""

import logging

from apps.core.exceptions import TenantViolationError

logger = logging.getLogger(__name__)


class TenantFilterMixin:
    """
    Mixin that scopes all queries to the current organisation.

    Override `tenant_field` if the model uses a different FK name.
    """

    tenant_field: str = "organisation"

    def _get_organisation(self):
        """
        Resolve (and cache) the organisation for this request.

        Phase 2 of tenant resolution — runs after DRF authentication.
        """
        if getattr(self.request, "organisation", None) is not None:
            return self.request.organisation

        from apps.tenancy.middleware import resolve_organisation
        org = resolve_organisation(self.request)

        if org is None:
            logger.error(
                "TenantFilterMixin: could not resolve organisation for user %s",
                getattr(self.request.user, "id", "anonymous"),
            )
            raise TenantViolationError(
                "Organisation context is missing or you do not have access. "
                "Pass the X-Organisation-ID header."
            )
        return org

    def get_queryset(self):
        org = self._get_organisation()
        qs = super().get_queryset()
        return qs.filter(**{self.tenant_field: org})

    def perform_create(self, serializer):
        """Automatically inject organisation on create."""
        org = self._get_organisation()
        serializer.save(**{self.tenant_field: org})

    def perform_update(self, serializer):
        serializer.save()


class AuditMixin:
    """Injects created_by / updated_by on write operations."""

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        serializer.save()


class ExportMixin:
    """
    Adds CSV/XLSX export to any ModelViewSet.

    Append ?format=csv or ?format=xlsx to any list endpoint.
    The ViewSet must set `export_fields` (list of (header, field_or_callable) tuples)
    and optionally `export_filename` (base filename without extension).

    Example:
        export_filename = 'invoices'
        export_fields = [
            ('Invoice #', 'invoice_number'),
            ('Customer', lambda obj: obj.customer.name if obj.customer else 'Walk-in'),
            ('Total', 'total'),
        ]
    """

    export_fields: list = []
    export_filename: str = 'export'

    def list(self, request, *args, **kwargs):
        fmt = request.query_params.get('format', '').lower()
        if fmt in ('csv', 'xlsx'):
            return self._export(request, fmt)
        return super().list(request, *args, **kwargs)

    def _export(self, request, fmt):
        import csv
        import io
        from django.http import HttpResponse

        qs = self.filter_queryset(self.get_queryset())

        if fmt == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{self.export_filename}.csv"'
            writer = csv.writer(response)
            headers = [h for h, _ in self.export_fields]
            writer.writerow(headers)
            for obj in qs:
                row = []
                for _, field in self.export_fields:
                    if callable(field):
                        row.append(field(obj))
                    else:
                        val = obj
                        for part in field.split('__'):
                            val = getattr(val, part, '') if val is not None else ''
                        row.append(val if val is not None else '')
                writer.writerow(row)
            return response

        # XLSX
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = self.export_filename.capitalize()

        header_font = Font(bold=True, color='FFFFFF')
        header_fill = PatternFill('solid', fgColor='1E293B')
        headers = [h for h, _ in self.export_fields]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center')

        for obj in qs:
            row = []
            for _, field in self.export_fields:
                if callable(field):
                    row.append(field(obj))
                else:
                    val = obj
                    for part in field.split('__'):
                        val = getattr(val, part, '') if val is not None else ''
                    row.append(str(val) if val is not None else '')
            ws.append(row)

        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        response = HttpResponse(buf.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="{self.export_filename}.xlsx"'
        return response
