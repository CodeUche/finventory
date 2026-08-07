"""
Server-side payslip PDF rendering (A.5).

Replaces the client-render-and-POST-back flow in views.PayrollRunViewSet.send_payslips
(which still works, unchanged, for callers that render client-side) with a path
that needs no client involvement at all: build_payslip_pdf() renders a payslip
entirely on the server, in the same reportlab style used elsewhere in the
codebase (see apps/tax/views.py's VAT return PDF and apps/reports/exporters.py).
"""
import io
from decimal import Decimal


def _money(v, currency='NGN'):
    try:
        return f"{currency} {Decimal(str(v or 0)):,.2f}"
    except Exception:
        return f"{currency} 0.00"


def build_payslip_pdf(payslip) -> bytes:
    """Render one PayslipLine to a PDF and return the raw bytes."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

    run = payslip.payroll_run
    employee = payslip.employee
    org = payslip.organisation
    currency = getattr(org, 'currency', 'NGN') or 'NGN'
    period_label = f"{run.period_year}-{run.period_month:02d}"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=20 * mm, rightMargin=20 * mm,
    )
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(f"<b>PAYSLIP — {org.name}</b>", styles['Title']))
    story.append(Paragraph(f"Pay period: {period_label} ({run.get_run_type_display()})", styles['Normal']))
    story.append(Paragraph(
        f"Employee: {employee.full_name} ({employee.employee_id}) — {employee.job_title}",
        styles['Normal'],
    ))
    story.append(Spacer(1, 6 * mm))

    earnings_rows = [
        ["Earnings", f"Amount ({currency})"],
        ["Basic Salary", f"{payslip.basic_salary:,.2f}"],
        ["Housing Allowance", f"{payslip.housing_allowance:,.2f}"],
        ["Transport Allowance", f"{payslip.transport_allowance:,.2f}"],
        ["Leave Allowance", f"{payslip.leave_allowance:,.2f}"],
        ["Other Allowances", f"{payslip.other_allowances:,.2f}"],
        ["Bonus", f"{payslip.bonus_amount:,.2f}"],
        ["Overtime", f"{payslip.overtime_amount:,.2f}"],
        ["Gross Pay", f"{payslip.gross_salary:,.2f}"],
    ]
    earnings_table = Table(earnings_rows, colWidths=[90 * mm, 60 * mm])
    earnings_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a5f')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8f0fe')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(earnings_table)
    story.append(Spacer(1, 6 * mm))

    deductions_rows = [
        ["Deductions", f"Amount ({currency})"],
        ["Employee Pension (8%)", f"{payslip.employee_pension:,.2f}"],
        ["NHF", f"{payslip.nhf:,.2f}"],
        ["PAYE Tax", f"{payslip.paye_tax:,.2f}"],
        ["Loan Repayment", f"{payslip.loan_deductions:,.2f}"],
        ["Penalty", f"{payslip.penalty_deductions:,.2f}"],
        ["Advance Recovered", f"{payslip.advance_deductions:,.2f}"],
        ["Benefit Premium", f"{payslip.benefit_deductions:,.2f}"],
        ["Attendance Deduction", f"{payslip.attendance_deduction:,.2f}"],
        ["Total Deductions", f"{payslip.total_deductions:,.2f}"],
    ]
    deductions_table = Table(deductions_rows, colWidths=[90 * mm, 60 * mm])
    deductions_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8b1e1e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#fdecec')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(deductions_table)
    story.append(Spacer(1, 8 * mm))

    net_table = Table(
        [["NET PAY", f"{currency} {payslip.net_salary:,.2f}"]], colWidths=[90 * mm, 60 * mm],
    )
    net_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d1f3c')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(net_table)
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        "This is a system-generated payslip and does not require a signature.",
        styles['Normal'],
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()
