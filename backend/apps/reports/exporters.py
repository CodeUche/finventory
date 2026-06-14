"""
Report export utilities — Excel (.xlsx) and PDF.

Usage:
    from apps.reports.exporters import export_excel, export_pdf

    # In a view:
    return export_excel(headers, rows, sheet_name='P&L', filename='pnl.xlsx')
    return export_pdf(headers, rows, title='Profit & Loss', filename='pnl.pdf')

Both functions return a fully-formed Django HttpResponse ready to return from
a view.  They do NOT touch the database — callers are responsible for providing
clean headers (list[str]) and rows (list[list]).
"""

import io
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from django.http import HttpResponse

# ─── Value normalisation ─────────────────────────────────────────────────────


def _clean(value: Any) -> Any:
    """
    Normalise a cell value to a type safe for both openpyxl and ReportLab.

    Rules
    -----
    * Decimal  → float  (Excel cells, ReportLab paragraphs both handle floats)
    * date / datetime → ISO string  (avoids timezone/tz-awareness issues)
    * None / '' → empty string
    * bool → 'Yes' / 'No'
    * Everything else → coerce to str only if not already a basic scalar
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    # UUIDs, enums, custom objects → string
    if not isinstance(value, (int, float, str)):
        return str(value)
    return value


# ─── Excel export ─────────────────────────────────────────────────────────────

# Audity brand colour (dark navy)
_BRAND_HEX = "1E3A5F"
_ALT_ROW_HEX = "EEF2F7"
_WHITE = "FFFFFF"


def export_excel(
    headers: list[str],
    rows: list[list],
    sheet_name: str = "Report",
    filename: str = "report.xlsx",
    subtitle: str = "",
) -> HttpResponse:
    """
    Build an .xlsx file and return it as an HttpResponse attachment.

    Args:
        headers:    Column header strings.
        rows:       Iterable of row iterables; values are normalised automatically.
        sheet_name: Worksheet tab label (max 31 chars, truncated if necessary).
        filename:   Suggested download filename.
        subtitle:   Optional subtitle row written below the sheet name header.

    Returns:
        HttpResponse with content-type application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    """
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]

    # ── Styles ────────────────────────────────────────────────────────────────
    header_fill = PatternFill(start_color=_BRAND_HEX, end_color=_BRAND_HEX, fill_type="solid")
    header_font = Font(color=_WHITE, bold=True, size=11)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    alt_fill = PatternFill(start_color=_ALT_ROW_HEX, end_color=_ALT_ROW_HEX, fill_type="solid")

    start_row = 1

    # ── Optional subtitle ─────────────────────────────────────────────────────
    if subtitle:
        ws.cell(row=1, column=1, value=subtitle).font = Font(italic=True, color="666666", size=10)
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(len(headers), 1))
        start_row = 2

    # ── Header row ────────────────────────────────────────────────────────────
    header_row = start_row
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=str(header))
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center

    # ── Data rows ─────────────────────────────────────────────────────────────
    data_start = header_row + 1
    cleaned_rows = []
    for row_idx, row in enumerate(rows, data_start):
        cleaned = [_clean(v) for v in row]
        cleaned_rows.append(cleaned)
        is_alt = (row_idx - data_start) % 2 == 1
        for col_idx, value in enumerate(cleaned, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.alignment = left
            if is_alt:
                cell.fill = alt_fill

    # ── Column auto-width ─────────────────────────────────────────────────────
    for col_idx, header in enumerate(headers, 1):
        col_letter = get_column_letter(col_idx)
        max_len = len(str(header))
        for cleaned in cleaned_rows:
            if col_idx - 1 < len(cleaned):
                max_len = max(max_len, len(str(cleaned[col_idx - 1])))
        ws.column_dimensions[col_letter].width = min(max_len + 4, 50)

    # ── Freeze header ─────────────────────────────────────────────────────────
    ws.freeze_panes = ws.cell(row=data_start, column=1)

    # ── Row height for header ─────────────────────────────────────────────────
    ws.row_dimensions[header_row].height = 22

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ─── PDF export ───────────────────────────────────────────────────────────────


def export_pdf(
    headers: list[str],
    rows: list[list],
    title: str = "Report",
    subtitle: str = "",
    filename: str = "report.pdf",
    org=None,
) -> HttpResponse:
    """
    Build a PDF file and return it as an HttpResponse attachment.

    Layout (matches the client-side pdfUtils stock-card template):
      - Header every page: logo (top-left), company name/address/phone/email,
        document title (top-right), subtitle below title.
      - Rule line separating header from body.
      - Body: branded table with alternating row shading.
      - Footer every page: rule + "OrgName · Generated by Audity · Date"
        left, title centre, "Page X of Y" right.
      - Brand accent bar flush at bottom of last page only.
      - Landscape A4 when more than 6 columns; portrait A4 otherwise.

    Args:
        headers:  Column header strings.
        rows:     Iterable of row iterables; values are normalised automatically.
        title:    Document title (e.g. "Profit & Loss Statement").
        subtitle: Period label shown below the title (e.g. "Jan – Dec 2025").
        filename: Suggested download filename.
        org:      Organisation model instance (provides branding + contact info).

    Returns:
        HttpResponse with content-type application/pdf
    """
    import io as _io
    import urllib.request

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.pagesizes import landscape as rl_landscape
    from reportlab.lib.units import mm
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    # ── Org branding ──────────────────────────────────────────────────────────
    raw_brand = (getattr(org, "brand_color", None) or "").lstrip("#") or _BRAND_HEX
    brand_color = colors.HexColor(f"#{raw_brand}")

    org_name    = (
        (getattr(org, "invoice_company_name", None) or "").strip()
        or getattr(org, "name", None) or ""
    )
    org_address = getattr(org, "address", None) or ""
    org_phone   = getattr(org, "phone",   None) or ""
    org_email   = getattr(org, "email",   None) or ""
    logo_url    = getattr(org, "logo",    None) or ""

    # ── Fetch logo bytes (best-effort, 3 s timeout) ───────────────────────────
    logo_reader = None
    if logo_url:
        try:
            from reportlab.lib.utils import ImageReader
            req = urllib.request.Request(logo_url, headers={"User-Agent": "Audity/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                logo_bytes = resp.read()
            logo_reader = ImageReader(_io.BytesIO(logo_bytes))
        except Exception:
            logo_reader = None

    # ── Page geometry ─────────────────────────────────────────────────────────
    is_landscape = len(headers) > 6
    page_size    = rl_landscape(A4) if is_landscape else A4
    page_w, page_h = page_size
    margin       = 15 * mm
    LOGO_SIZE    = 20 * mm
    HEADER_H     = 34 * mm   # top margin reserved for header block
    FOOTER_H     = 12 * mm   # bottom margin reserved for footer block

    today_str = datetime.today().strftime("%d %b %Y")

    # ── Numbered canvas — draws header + footer on every page ─────────────────
    class _HFCanvas(Canvas):
        def __init__(self, *args, **kwargs):
            Canvas.__init__(self, *args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            n = len(self._pages)
            for idx, state in enumerate(self._pages):
                self.__dict__.update(state)
                self._draw(idx + 1, n)
                Canvas.showPage(self)
            Canvas.save(self)

        def _draw(self, page_num: int, total: int):
            self.saveState()
            pw, ph = self._pagesize

            # ── Header ───────────────────────────────────────────────────────
            logo_x = margin
            logo_y = ph - margin - LOGO_SIZE

            if logo_reader:
                try:
                    self.drawImage(
                        logo_reader, logo_x, logo_y,
                        LOGO_SIZE, LOGO_SIZE,
                        mask="auto", preserveAspectRatio=True,
                    )
                except Exception:
                    pass

            name_x = margin + (LOGO_SIZE + 4 * mm if logo_reader else 0)

            if org_name:
                self.setFont("Helvetica-Bold", 11)
                self.setFillColor(colors.HexColor("#16161E"))
                self.drawString(name_x, ph - margin - 8 * mm, org_name)

            self.setFont("Helvetica", 8)
            self.setFillColor(colors.HexColor("#6B7280"))
            info_y = ph - margin - 14 * mm
            for line in filter(None, [org_address, org_phone, org_email]):
                self.drawString(name_x, info_y, line)
                info_y -= 4.5 * mm

            # Document title — top-right, brand colour
            self.setFont("Helvetica-Bold", 16)
            self.setFillColor(brand_color)
            self.drawRightString(pw - margin, ph - margin - 8 * mm, title.upper())

            # Subtitle — below title
            if subtitle:
                self.setFont("Helvetica", 8)
                self.setFillColor(colors.HexColor("#6B7280"))
                self.drawRightString(pw - margin, ph - margin - 15 * mm, subtitle)

            # Rule below header
            rule_y = ph - HEADER_H
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.3)
            self.line(margin, rule_y, pw - margin, rule_y)

            # ── Footer ───────────────────────────────────────────────────────
            footer_rule_y = FOOTER_H - 2 * mm
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.25)
            self.line(margin, footer_rule_y, pw - margin, footer_rule_y)

            self.setFont("Helvetica", 6.5)
            self.setFillColor(colors.HexColor("#6B7280"))
            left_txt = f"{org_name}  ·  Generated by Audity  ·  {today_str}"
            txt_y = footer_rule_y - 3.5 * mm
            self.drawString(margin, txt_y, left_txt)
            self.drawCentredString(pw / 2, txt_y, title)
            self.drawRightString(pw - margin, txt_y, f"Page {page_num} of {total}")

            # Brand accent bar — last page only
            if page_num == total:
                self.setFillColor(brand_color)
                self.rect(0, 0, pw, 2 * mm, fill=1, stroke=0)

            self.restoreState()

    # ── Build PDF ─────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=page_size,
        rightMargin=margin,
        leftMargin=margin,
        topMargin=HEADER_H + 4 * mm,
        bottomMargin=FOOTER_H + 4 * mm,
    )

    # ── Table ─────────────────────────────────────────────────────────────────
    alt_row_color = colors.HexColor(f"#{_ALT_ROW_HEX}")
    rule_color    = colors.HexColor("#E2E8F0")
    dark_color    = colors.HexColor("#16161E")

    table_data = [headers]
    for row in rows:
        table_data.append([str(_clean(v)) for v in row])

    usable_width = page_w - 2 * margin
    col_width    = usable_width / max(len(headers), 1)

    tbl = Table(table_data, colWidths=[col_width] * len(headers), repeatRows=1)

    style_cmds: list = [
        ("BACKGROUND",    (0, 0), (-1,  0), brand_color),
        ("TEXTCOLOR",     (0, 0), (-1,  0), colors.white),
        ("FONTNAME",      (0, 0), (-1,  0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1,  0), 7.5),
        ("ALIGN",         (0, 0), (-1,  0), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 8),
        ("TEXTCOLOR",     (0, 1), (-1, -1), dark_color),
        ("ALIGN",         (0, 1), (-1, -1), "LEFT"),
        ("GRID",          (0, 0), (-1, -1), 0.2, rule_color),
        ("TOPPADDING",    (0, 0), (-1, -1), 2.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 3.5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 3.5),
    ]
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), alt_row_color))

    tbl.setStyle(TableStyle(style_cmds))

    elements: list = [tbl]

    doc.build(elements, canvasmaker=_HFCanvas)
    buf.seek(0)

    response = HttpResponse(buf.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ─── Format dispatcher ────────────────────────────────────────────────────────


def dispatch_export(
    fmt: str,
    headers: list[str],
    rows: list[list],
    title: str = "Report",
    subtitle: str = "",
    filename_base: str = "report",
    org=None,
) -> Optional[HttpResponse]:
    """
    Return an HttpResponse for Excel or PDF, or None if fmt is not an export format.

    Args:
        fmt:           'excel' | 'pdf' | anything else (returns None → caller serves JSON)
        headers:       Column headers.
        rows:          Data rows.
        title:         Report title for PDF.
        subtitle:      Sub-heading / date range string for PDF.
        filename_base: Base filename without extension (e.g. 'pnl_report').
        org:           Organisation instance forwarded to export_pdf for branding.

    Returns:
        HttpResponse or None
    """
    if fmt == "excel":
        return export_excel(
            headers=headers,
            rows=rows,
            sheet_name=title[:31],
            filename=f"{filename_base}.xlsx",
            subtitle=subtitle,
        )
    if fmt == "pdf":
        return export_pdf(
            headers=headers,
            rows=rows,
            title=title,
            subtitle=subtitle,
            filename=f"{filename_base}.pdf",
            org=org,
        )
    return None
