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
) -> HttpResponse:
    """
    Build a PDF file and return it as an HttpResponse attachment.

    Uses landscape A4 when there are more than 6 columns.

    Args:
        headers:  Column header strings.
        rows:     Iterable of row iterables; values are normalised automatically.
        title:    Large heading printed at the top of every page.
        subtitle: Smaller line below the title (e.g. date range).
        filename: Suggested download filename.

    Returns:
        HttpResponse with content-type application/pdf
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    brand_color = colors.HexColor(f"#{_BRAND_HEX}")
    alt_row_color = colors.HexColor(f"#{_ALT_ROW_HEX}")

    buf = io.BytesIO()
    page_size = landscape(A4) if len(headers) > 6 else A4

    doc = SimpleDocTemplate(
        buf,
        pagesize=page_size,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()
    elements = []

    # ── Title ─────────────────────────────────────────────────────────────────
    title_style = ParagraphStyle(
        "AudityTitle",
        parent=styles["Title"],
        fontSize=15,
        spaceAfter=4,
        textColor=brand_color,
    )
    elements.append(Paragraph(title, title_style))

    # ── Subtitle ──────────────────────────────────────────────────────────────
    if subtitle:
        sub_style = ParagraphStyle(
            "AuditySubtitle",
            parent=styles["Normal"],
            fontSize=9,
            spaceAfter=10,
            textColor=colors.HexColor("#718096"),
        )
        elements.append(Paragraph(subtitle, sub_style))

    elements.append(Spacer(1, 0.4 * cm))

    # ── Table data ────────────────────────────────────────────────────────────
    table_data = [headers]
    for row in rows:
        table_data.append([str(_clean(v)) for v in row])

    # Auto column widths
    usable_width = page_size[0] - 3 * cm
    col_width = usable_width / max(len(headers), 1)

    tbl = Table(table_data, colWidths=[col_width] * len(headers), repeatRows=1)

    # Build alternating row background commands
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), brand_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (0, 1), (-1, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E0")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]

    # Alternate row shading for data rows
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), alt_row_color))

    tbl.setStyle(TableStyle(style_cmds))
    elements.append(tbl)

    doc.build(elements)
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
        )
    return None
