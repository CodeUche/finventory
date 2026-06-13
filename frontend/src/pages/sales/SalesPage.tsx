import { useEffect, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, Receipt, Search, X, Loader2, CheckCircle, Ban, FileDown, Mail, MessageCircle, RotateCcw, Truck, Pencil, Trash2, CalendarClock, RefreshCw } from 'lucide-react'
import SortSelect from '@/components/SortSelect'
import YearFilter, { yearToDateParams } from '@/components/YearFilter'
import MonthFilter, { monthToDateParams, type ArchiveMonth } from '@/components/MonthFilter'
import ExportButton from '@/components/ExportButton'
import { Link, useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { salesApi, urlToDataUrl, bypassNextGets } from '@/services/api'
import { formatCurrency, formatDate, getStatusColor, formatAmountInput, stripCommas } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import { useModuleAccess } from '@/hooks/useModuleAccess'
import DateInput from '@/components/DateInput'
import { saveBlobFile } from '@/lib/saveBlobFile'
import type { Invoice } from '@/types'

const STATUS_OPTIONS = ['', 'paid', 'proforma', 'confirmed', 'partially_paid', 'credit', 'overdue', 'returned', 'voided']
const RETURN_REASONS = [
  { value: 'defective',       label: 'Defective / Damaged' },
  { value: 'wrong_item',      label: 'Wrong Item Delivered' },
  { value: 'customer_change', label: 'Customer Changed Mind' },
  { value: 'overcharge',      label: 'Overcharge / Price Error' },
  { value: 'other',           label: 'Other' },
]

interface PdfPreview { url: string; filename: string }
interface ReturnLineItem { sale_item_id: string; quantity_returned: string; max_qty: number; already_returned: number; product_name: string; unit_price: string }

/** Parse a CSS hex color into an RGB triple for jsPDF. Falls back to orange on invalid input. */
function hexToRgb(hex?: string): [number, number, number] {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
  if (!m) return [249, 115, 22]
  return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
}



/** Convert a data URL to a PNG with white/near-white pixels made transparent, removing box borders from stamp images. */
async function stripStampBackground(dataUrl: string): Promise<string> {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = img.width; canvas.height = img.height
      const ctx = canvas.getContext('2d')!
      ctx.drawImage(img, 0, 0)
      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
      const d = imageData.data
      for (let i = 0; i < d.length; i += 4) {
        // Make near-white pixels transparent (threshold: all channels > 230)
        if (d[i] > 230 && d[i + 1] > 230 && d[i + 2] > 230) d[i + 3] = 0
      }
      ctx.putImageData(imageData, 0, 0)
      resolve(canvas.toDataURL('image/png'))
    }
    img.onerror = () => resolve(dataUrl) // fallback to original on error
    img.src = dataUrl
  })
}

// ── PDF builder ───────────────────────────────────────────────────────────────
async function buildInvoicePDF(
  inv: Invoice,
  orgName: string,
  orgLogo?: string,
  orgAddress?: string,
  orgPhone?: string,
  orgEmail?: string,
  bankName?: string,
  bankAccountNumber?: string,
  bankAccountName?: string,
  bankSortCode?: string,
  brandColorHex?: string,
  companyNameOverride?: string,
  companyFont?: string,
  companyFontSize?: number,
  companyFontBold?: boolean,
  companyFontItalic?: boolean,
  companyFontUnderline?: boolean,
  companyFontColor?: string,
  invoiceTemplate?: string,
  companyStamp?: string,
  showCompanyName?: boolean,
): Promise<PdfPreview> {
  const { jsPDF } = await import('jspdf')
  const { default: autoTable } = await import('jspdf-autotable')
  const { applyDocHeader, buildTableStyle, addDocFooter, COLORS, TYPE } = await import('@/lib/pdfUtils')

  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  doc.setLineHeightFactor(1.15)
  const pageW = doc.internal.pageSize.getWidth()
  const tmpl  = invoiceTemplate ?? 'classic'

  const BRAND: [number, number, number] = hexToRgb(brandColorHex)
  const DARK   = COLORS.DARK
  const MUTED  = COLORS.MUTED
  const LIGHT  = COLORS.LIGHT
  const RULE   = COLORS.RULE

  const displayName = showCompanyName === false ? '' : (companyNameOverride?.trim() || orgName)
  const pdfFont = companyFont?.toLowerCase().includes('times') || companyFont === 'Georgia'
    || companyFont === 'Playfair Display' || companyFont === 'Merriweather' || companyFont === 'Lora'
    || companyFont === 'Libre Baskerville' || companyFont === 'EB Garamond' || companyFont === 'Crimson Text'
    || companyFont === 'Cinzel' || companyFont === 'Cormorant Garamond' || companyFont === 'Spectral'
    ? 'times'
    : companyFont === 'courier' || companyFont === 'JetBrains Mono' || companyFont === 'Fira Code'
    ? 'courier' : 'helvetica'
  const isBold   = companyFontBold !== false
  const isItalic = companyFontItalic === true
  const pdfStyle = isBold && isItalic ? 'bolditalic' : isBold ? 'bold' : isItalic ? 'italic' : 'normal'
  const fontSize = Math.max(8, Math.min(36, companyFontSize ?? 12))
  const nameColor: [number, number, number] = (() => {
    if (!companyFontColor || companyFontColor === '#ffffff') {
      return (tmpl === 'modern' || tmpl === 'minimal') ? DARK : COLORS.WHITE
    }
    return hexToRgb(companyFontColor)
  })()

  // Pre-load logo — if already a data URL (from Zustand store), use it directly
  let logoData: string | null = null
  if (orgLogo) {
    if (orgLogo.startsWith('data:')) { logoData = orgLogo }
    else { try { logoData = await urlToDataUrl(orgLogo) } catch { /* skip */ } }
  }

  let y = applyDocHeader(doc, {
    tmpl, pageW, BRAND, DARK, MUTED,
    logoData,
    displayName,
    orgAddress,
    orgPhone,
    orgEmail,
    pdfFont,
    fontSize,
    pdfStyle,
    nameColor,
    companyFontUnderline,
    showCompanyName: showCompanyName !== false,
    docTitle: 'INVOICE',
    metaRows: [
      ['No.',     inv.invoice_number],
      ['Date',    formatDate(inv.issue_date)],
      ['Payment', inv.payment_method.replace(/_/g, ' ')],
      ['Status',  inv.status.replace(/_/g, ' ').toUpperCase()],
      ...(inv.sold_by ? [['Sold By', inv.sold_by] as [string, string]] : []),
    ],
  })

  // ── Bill To box (full width) ───────────────────────────────────────────────
  const boxW = pageW - 28
  const boxH = 32
  const lBoxX = 14

  doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
  doc.roundedRect(lBoxX, y, boxW, boxH, 2, 2, 'FD')
  doc.setFontSize(TYPE.H3.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...BRAND)
  doc.text('BILL TO', lBoxX + 3, y + 5)
  doc.setFontSize(TYPE.H2.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...DARK)
  doc.text(inv.customer_name ?? 'Walk-in Customer', lBoxX + 3, y + 11)
  doc.setFontSize(TYPE.BODY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
  doc.text(inv.payment_method.replace(/_/g, ' ') + ' payment', lBoxX + 3, y + 16.5)

  y += boxH + 6

  // ── Items table ────────────────────────────────────────────────────────────
  const ts = buildTableStyle(BRAND, pdfFont)

  // Dynamically size monetary columns so large numbers always fit
  const itemAmounts = [...(inv.items ?? []).map(it => formatCurrency(it.line_total)), 'Amount']
  const itemPrices  = [...(inv.items ?? []).map(it => formatCurrency(it.unit_price)), 'Unit Price']
  const itemQtys    = [...(inv.items ?? []).map(it => String(Number(it.quantity))), 'Qty']
  doc.setFontSize(9)
  const amtColW   = Math.min(58, Math.max(26, Math.max(...itemAmounts.map(s => doc.getTextWidth(s))) + 8))
  const priceColW = Math.min(52, Math.max(24, Math.max(...itemPrices.map(s => doc.getTextWidth(s))) + 8))
  const qtyColW   = Math.min(20, Math.max(14, Math.max(...itemQtys.map(s => doc.getTextWidth(s))) + 6))

  autoTable(doc, {
    ...ts,
    startY: y,
    head: [['#', 'Product / Description', 'SKU', 'Qty', 'Unit Price', 'Amount']],
    body: (inv.items ?? []).map((item, i) => [
      i + 1,
      item.product_name,
      item.product_sku ?? '—',
      Number(item.quantity),
      formatCurrency(item.unit_price),
      formatCurrency(item.line_total),
    ]),
    columnStyles: {
      0: { cellWidth: 8,        halign: 'center' as const },
      1: { cellWidth: 'auto' as const },
      2: { cellWidth: 22,       halign: 'center' as const },
      3: { cellWidth: qtyColW,  halign: 'center' as const },
      4: { cellWidth: priceColW,halign: 'right' as const },
      5: { cellWidth: amtColW,  halign: 'right' as const, fontStyle: 'bold' as const, textColor: DARK },
    },
  })

  // ── Totals block — right-aligned 72mm box ─────────────────────────────────
  const tY = (doc as any).lastAutoTable.finalY + 6
  const tW = 72
  const tX = pageW - 14 - tW

  const subtotalNum    = parseFloat(inv.subtotal ?? inv.total_amount ?? '0')
  const discountNum    = parseFloat(inv.discount_amount ?? '0')
  const taxNum         = parseFloat(inv.tax_amount ?? '0')
  const totalNum       = parseFloat(inv.total_amount ?? '0')
  const creditApplied  = parseFloat((inv as any).credit_applied ?? '0')
  const amtPaidNum     = parseFloat(inv.amount_paid ?? '0')
  const amtDue         = parseFloat(inv.amount_due ?? '0')

  const firstPaymentNotes = inv.payments?.[0]?.notes ?? ''
  const tenderedMatch = firstPaymentNotes.match(/Tendered:\s*([\d.]+)/)
  const tenderedNum = tenderedMatch ? parseFloat(tenderedMatch[1]) : amtPaidNum
  const changeNum   = tenderedNum > amtPaidNum ? tenderedNum - amtPaidNum : 0

  const totalRows: Array<{ label: string; value: string; bold?: boolean; color?: [number,number,number] }> = []
  totalRows.push({ label: 'Subtotal', value: formatCurrency(subtotalNum) })
  if (discountNum > 0) totalRows.push({ label: 'Discount', value: `- ${formatCurrency(discountNum)}`, color: COLORS.AMBER })
  if (taxNum > 0)      totalRows.push({ label: 'Tax / VAT', value: formatCurrency(taxNum) })
  if (discountNum > 0 || taxNum > 0 || creditApplied > 0)
    totalRows.push({ label: 'Invoice Total', value: formatCurrency(totalNum), bold: true })
  if (creditApplied > 0)
    totalRows.push({ label: 'Store Credit Applied', value: `- ${formatCurrency(creditApplied)}`, color: COLORS.GREEN })
  if (amtPaidNum > 0) {
    totalRows.push({ label: 'Amount Tendered', value: formatCurrency(tenderedNum), color: COLORS.GREEN })
    if (changeNum > 0) totalRows.push({ label: 'Change Given', value: formatCurrency(changeNum), color: COLORS.GREEN })
  }

  const ROW_H = 5.5
  const PAD   = 4
  const boxContentH = totalRows.length * ROW_H + 2 + ROW_H + PAD * 2 + 3
  const totalsBoxH  = boxContentH

  doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
  doc.roundedRect(tX, tY, tW, totalsBoxH, 2, 2, 'FD')

  let rowY = tY + PAD + ROW_H * 0.5
  totalRows.forEach(({ label, value, bold = false, color }) => {
    const valColor = color ?? DARK
    doc.setFontSize(TYPE.SMALL.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
    doc.text(label, tX + PAD, rowY)
    doc.setFontSize(TYPE.BODY.size); doc.setFont(pdfFont, bold ? 'bold' : 'normal'); doc.setTextColor(...valColor)
    doc.text(value, tX + tW - PAD, rowY, { align: 'right' })
    rowY += ROW_H
  })
  // Divider
  doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
  doc.line(tX + PAD, rowY + 1, tX + tW - PAD, rowY + 1)
  rowY += 3

  // Grand total row
  const dueColor: [number,number,number] = amtDue > 0 ? COLORS.RED : COLORS.GREEN
  doc.setFontSize(TYPE.H3.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...DARK)
  doc.text('BALANCE DUE', tX + PAD, rowY)
  doc.setFontSize(TYPE.H2.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...dueColor)
  doc.text(formatCurrency(amtDue), tX + tW - PAD, rowY, { align: 'right' })

  const afterTotalsY = tY + totalsBoxH

  // ── Payment details (left of totals, 85mm wide) ────────────────────────────
  if (bankName || bankAccountNumber) {
    const bX  = 14
    const bW  = 85
    doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
    doc.roundedRect(bX, tY, bW, totalsBoxH, 2, 2, 'FD')
    doc.setFontSize(TYPE.H3.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...BRAND)
    doc.text('PAYMENT DETAILS', bX + 3, tY + 5)
    doc.setFontSize(TYPE.BODY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...DARK)
    let bRow = tY + 11
    if (bankName)          { doc.text(`Bank: ${bankName}`,                   bX + 3, bRow); bRow += 4.5 }
    if (bankAccountName)   { doc.text(`Account Name: ${bankAccountName}`,    bX + 3, bRow); bRow += 4.5 }
    if (bankAccountNumber) { doc.text(`Account No.: ${bankAccountNumber}`,   bX + 3, bRow); bRow += 4.5 }
    if (bankSortCode)      { doc.text(`Sort Code: ${bankSortCode}`,          bX + 3, bRow) }
  } else {
    doc.setFontSize(TYPE.SMALL.size); doc.setFont(pdfFont, 'italic'); doc.setTextColor(...MUTED)
    doc.text(`Payment: ${inv.payment_method.replace(/_/g, ' ')}`, 14, tY + 5.5)
  }

  // ── Thank you note ─────────────────────────────────────────────────────────
  doc.setFontSize(TYPE.BODY.size); doc.setFont(pdfFont, 'italic'); doc.setTextColor(...MUTED)
  doc.text('Thank you for your business!', 14, afterTotalsY + 6)

  // ── FIRS Compliance block (IRN + QR code) ─────────────────────────────────
  const firsIrn   = (inv as any).firs_irn  as string | undefined
  const firsQr    = (inv as any).firs_qr_code as string | undefined
  const firsInvNo = (inv as any).firs_invoice_number as string | undefined
  const firsCsid  = (inv as any).firs_csid as string | undefined

  if (firsIrn) {
    const FIRS_TOP   = afterTotalsY + 14
    const FIRS_QR_SZ = 24
    const FIRS_H     = 30
    const FIRS_GREEN: [number,number,number] = [21, 128, 61]
    const FIRS_LIGHT: [number,number,number] = [220, 252, 231]

    doc.setFillColor(...FIRS_LIGHT); doc.setDrawColor(...FIRS_GREEN); doc.setLineWidth(0.3)
    doc.roundedRect(14, FIRS_TOP, pageW - 28, FIRS_H, 2, 2, 'FD')

    doc.setFontSize(TYPE.H3.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...FIRS_GREEN)
    doc.text('FIRS VERIFIED — e-Invoice', 19, FIRS_TOP + 6)

    doc.setFontSize(TYPE.TINY.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...DARK)
    doc.text('IRN:', 19, FIRS_TOP + 12)
    doc.setFont(pdfFont, 'normal')
    const irnDisplay = firsIrn.length > 55 ? firsIrn.slice(0, 55) + '…' : firsIrn
    doc.text(irnDisplay, 28, FIRS_TOP + 12)

    if (firsInvNo && firsInvNo !== inv.invoice_number) {
      doc.setFont(pdfFont, 'bold'); doc.text('FIRS No.:', 19, FIRS_TOP + 18)
      doc.setFont(pdfFont, 'normal')
      doc.text(firsInvNo.length > 50 ? firsInvNo.slice(0, 50) + '…' : firsInvNo, 38, FIRS_TOP + 18)
    }
    if (firsCsid) {
      doc.setFont(pdfFont, 'bold'); doc.text('CSID:', 19, FIRS_TOP + 24)
      doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
      doc.text(firsCsid.length > 52 ? firsCsid.slice(0, 52) + '…' : firsCsid, 28, FIRS_TOP + 24)
    }
    if (firsQr) {
      try {
        const qrDataUrl = firsQr.startsWith('data:') ? firsQr : `data:image/png;base64,${firsQr}`
        doc.addImage(qrDataUrl, 'PNG', pageW - 14 - FIRS_QR_SZ - 4, FIRS_TOP + (FIRS_H - FIRS_QR_SZ) / 2, FIRS_QR_SZ, FIRS_QR_SZ)
      } catch { /* skip QR if malformed */ }
    }
  }

  // ── Company stamp (bottom-right of last page, semi-transparent) ───────────
  if (companyStamp) {
    try {
      const raw = companyStamp.startsWith('data:') ? companyStamp : await urlToDataUrl(companyStamp)
      if (raw) {
        const stampData = await stripStampBackground(raw)
        const pageH = doc.internal.pageSize.getHeight()
        const SZ = 34
        doc.saveGraphicsState()
        doc.setGState(new (doc as any).GState({ opacity: 0.55 }))
        doc.addImage(stampData, 'PNG', pageW - 16 - SZ, pageH - 18 - SZ, SZ, SZ)
        doc.restoreGraphicsState()
      }
    } catch { /* skip stamp on error */ }
  }

  // ── Footer (every page) ────────────────────────────────────────────────────
  addDocFooter(doc, { orgName, docTitle: 'INVOICE', docRef: inv.invoice_number, BRAND, pdfFont })

  const blob = doc.output('blob')
  return { url: URL.createObjectURL(blob), filename: `Invoice-${inv.invoice_number}.pdf` }
}

// ── Delivery Note PDF builder ─────────────────────────────────────────────────
async function buildDeliveryNotePDF(
  inv: Invoice,
  orgName: string,
  orgAddress?: string,
  brandColorHex?: string,
  companyNameOverride?: string,
  companyFont?: string,
  orgLogo?: string,
  companyStamp?: string,
  invoiceTemplate?: string,
  showCompanyName?: boolean,
  companyFontColor?: string,
  companyFontSize?: number,
  companyFontBold?: boolean,
  companyFontItalic?: boolean,
  companyFontUnderline?: boolean,
  orgPhone?: string,
  orgEmail?: string,
): Promise<PdfPreview> {
  const { jsPDF } = await import('jspdf')
  const { default: autoTable } = await import('jspdf-autotable')
  const { applyDocHeader, buildTableStyle, addDocFooter, COLORS, TYPE } = await import('@/lib/pdfUtils')

  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  doc.setLineHeightFactor(1.15)
  const pageW = doc.internal.pageSize.getWidth()

  const BRAND: [number,number,number] = hexToRgb(brandColorHex)
  const DARK   = COLORS.DARK
  const MUTED  = COLORS.MUTED
  const LIGHT  = COLORS.LIGHT
  const RULE   = COLORS.RULE
  const tmpl   = invoiceTemplate ?? 'classic'

  const displayName = showCompanyName === false ? '' : (companyNameOverride?.trim() || orgName)
  const pdfFont = companyFont?.toLowerCase().includes('times') || companyFont === 'Georgia'
    || companyFont === 'Playfair Display' || companyFont === 'Merriweather' || companyFont === 'Lora'
    || companyFont === 'Libre Baskerville' || companyFont === 'EB Garamond' || companyFont === 'Crimson Text'
    || companyFont === 'Cinzel' || companyFont === 'Cormorant Garamond' || companyFont === 'Spectral'
    ? 'times'
    : companyFont === 'courier' || companyFont === 'JetBrains Mono' || companyFont === 'Fira Code'
    ? 'courier' : 'helvetica'
  const isBold   = companyFontBold !== false
  const isItalic = companyFontItalic === true
  const pdfStyle = isBold && isItalic ? 'bolditalic' : isBold ? 'bold' : isItalic ? 'italic' : 'normal'
  const fontSize = Math.max(8, Math.min(36, companyFontSize ?? 12))
  const nameColor: [number,number,number] = (() => {
    if (!companyFontColor || companyFontColor === '#ffffff') {
      return (tmpl === 'modern' || tmpl === 'minimal') ? DARK : COLORS.WHITE
    }
    return hexToRgb(companyFontColor)
  })()

  let logoData: string | null = null
  if (orgLogo) {
    if (orgLogo.startsWith('data:')) { logoData = orgLogo }
    else { try { logoData = await urlToDataUrl(orgLogo) } catch { /* skip */ } }
  }

  let y = applyDocHeader(doc, {
    tmpl, pageW, BRAND, DARK, MUTED,
    logoData,
    displayName,
    orgAddress,
    orgPhone,
    orgEmail,
    pdfFont,
    fontSize,
    pdfStyle,
    nameColor,
    companyFontUnderline,
    showCompanyName: showCompanyName !== false,
    docTitle: 'DELIVERY NOTE',
    metaRows: [
      ['Ref No.', inv.invoice_number],
      ['Date',    formatDate(inv.issue_date)],
    ],
  })

  // "Deliver To" info block
  doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
  doc.roundedRect(14, y, 85, 20, 2, 2, 'FD')
  doc.setFontSize(TYPE.H3.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...BRAND)
  doc.text('DELIVER TO', 17, y + 5)
  doc.setFontSize(TYPE.H2.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...DARK)
  doc.text(inv.customer_name ?? 'Walk-in Customer', 17, y + 11)
  doc.setFontSize(TYPE.BODY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
  doc.text(`Date: ${formatDate(inv.issue_date)}`, 17, y + 16.5)
  y += 26

  const ts = buildTableStyle(BRAND, pdfFont)
  autoTable(doc, {
    ...ts,
    startY: y,
    head: [['#', 'Product', 'SKU', 'Qty Ordered', '☐ Received']],
    body: (inv.items ?? []).map((item, i) => [
      i + 1, item.product_name, item.product_sku ?? '—', Number(item.quantity), '',
    ]),
    columnStyles: {
      0: { cellWidth: 8,  halign: 'center' as const },
      2: { cellWidth: 22, halign: 'center' as const },
      3: { cellWidth: 22, halign: 'center' as const },
      4: { cellWidth: 28, halign: 'center' as const },
    },
  })

  const finalY = (doc as any).lastAutoTable.finalY + 18
  doc.setFontSize(TYPE.BODY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
  doc.text('Received by: ___________________________', 14, finalY)
  doc.text('Signature:  ___________________________', 14, finalY + 9)
  doc.text(`Dispatched by: ${displayName}${orgAddress ? '  ·  ' + orgAddress : ''}`, 14, finalY + 18)

  // ── Company stamp ──────────────────────────────────────────────────────────
  if (companyStamp) {
    try {
      const raw = companyStamp.startsWith('data:') ? companyStamp : await urlToDataUrl(companyStamp)
      if (raw) {
        const stampData = await stripStampBackground(raw)
        const pageH = doc.internal.pageSize.getHeight()
        const SZ = 34
        doc.saveGraphicsState()
        doc.setGState(new (doc as any).GState({ opacity: 0.55 }))
        doc.addImage(stampData, 'PNG', pageW - 16 - SZ, pageH - 18 - SZ, SZ, SZ)
        doc.restoreGraphicsState()
      }
    } catch { /* skip stamp on error */ }
  }

  // ── Footer (every page) ────────────────────────────────────────────────────
  addDocFooter(doc, { orgName, docTitle: 'DELIVERY NOTE', docRef: inv.invoice_number, BRAND, pdfFont })

  return { url: URL.createObjectURL(doc.output('blob')), filename: `DeliveryNote-${inv.invoice_number}.pdf` }
}

// ─────────────────────────────────────────────────────────────────────────────

export default function SalesPage() {
  const navigate = useNavigate()
  const { organisation, memberRole, user, logoDataUrl, stampDataUrl } = useAuthStore()
  const { canEdit: canEditSales } = useModuleAccess('sales')
  const isOwnerOrAdmin = memberRole === 'owner' || memberRole === 'admin' || user?.is_superuser === true
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [sortBy, setSortBy] = useState('-issue_date')
  const [selected, setSelected] = useState<Invoice | null>(null)
  const [detail, setDetail] = useState<Invoice | null>(null)
  const [acting, setActing] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [payAmount, setPayAmount] = useState('')
  const [payMethod, setPayMethod] = useState('cash')
  const [tenderedAmount, setTenderedAmount] = useState('')
  const [pdfPreview, setPdfPreview] = useState<PdfPreview | null>(null)
  const [exportingDelivery, setExportingDelivery] = useState(false)
  // Edit invoice state
  const [showEditInvoice, setShowEditInvoice] = useState(false)
  const [editInvoiceForm, setEditInvoiceForm] = useState({ notes: '', due_date: '', issue_date: '', payment_method: '' })
  const [savingEdit, setSavingEdit] = useState(false)
  // Email modal state
  const [showEmailModal, setShowEmailModal] = useState(false)
  const [emailTo, setEmailTo] = useState('')
  const [sendingEmail, setSendingEmail] = useState(false)
  // Return modal state
  const [showReturn, setShowReturn] = useState(false)
  const [returnItems, setReturnItems] = useState<ReturnLineItem[]>([])
  const [returnReason, setReturnReason] = useState('other')
  const [returnNotes, setReturnNotes] = useState('')
  const [returnDate, setReturnDate] = useState(() => new Date().toISOString().split('T')[0])
  const [returnRestocked, setReturnRestocked] = useState(true)
  const [processingReturn, setProcessingReturn] = useState(false)
  const [archiveYear, setArchiveYear] = useState<number | null>(null)
  const [archiveMonth, setArchiveMonth] = useState<ArchiveMonth | null>(null)
  const [customDateFrom, setCustomDateFrom] = useState('')
  const [customDateTo, setCustomDateTo] = useState('')
  const activeDateParams = customDateFrom || customDateTo
    ? { date_from: customDateFrom || undefined, date_to: customDateTo || undefined }
    : archiveMonth ? monthToDateParams(archiveMonth) : yearToDateParams(archiveYear)
  const handleYearChange = (y: number | null) => { setArchiveYear(y); if (y !== null) { setArchiveMonth(null); setCustomDateFrom(''); setCustomDateTo('') } }
  const handleMonthChange = (m: ArchiveMonth | null) => { setArchiveMonth(m); if (m !== null) { setArchiveYear(null); setCustomDateFrom(''); setCustomDateTo('') } }
  const handleCustomDateFrom = (v: string) => { setCustomDateFrom(v); setArchiveYear(null); setArchiveMonth(null) }
  const handleCustomDateTo = (v: string) => { setCustomDateTo(v); setArchiveYear(null); setArchiveMonth(null) }
  const [showExtendDue, setShowExtendDue] = useState(false)
  const [extendDueDate, setExtendDueDate] = useState('')
  const [extendReason, setExtendReason] = useState('')
  const [extendingDue, setExtendingDue] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await salesApi.invoices({ search, status: status || undefined, ordering: sortBy, ...activeDateParams })
      setInvoices(data.results ?? data)
    } catch { toast.error('Failed to load invoices') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [search, status, sortBy, archiveYear, archiveMonth, customDateFrom, customDateTo])
  useDataRefresh(load)

  const openDetail = async (inv: Invoice) => {
    setSelected(inv)
    setPayAmount(formatAmountInput(inv.amount_due))
    setTenderedAmount('')
    try {
      const { data } = await salesApi.invoice(inv.id)
      setDetail(data)
    } catch { setDetail(inv) }
  }

  const closeDetail = () => { setSelected(null); setDetail(null) }

  const handlePay = async () => {
    if (!selected) return
    setActing(true)
    try {
      const amount = stripCommas(payAmount)
      const tendered = stripCommas(tenderedAmount)
      const notes = payMethod === 'cash' && tendered && parseFloat(tendered) > 0
        ? `Tendered: ${tendered}, Change: ${(parseFloat(tendered) - parseFloat(amount)).toFixed(2)}`
        : undefined
      await salesApi.pay(selected.id, { amount, method: payMethod, ...(notes ? { notes } : {}) })
      toast.success('Payment recorded')
      setTenderedAmount(''); closeDetail(); load()
    } catch { toast.error('Payment failed') }
    finally { setActing(false) }
  }

  const handleVoid = async () => {
    if (!selected) return
    if (!confirm('Void this invoice? This cannot be undone.')) return
    setActing(true)
    try {
      await salesApi.void(selected.id)
      toast.success('Invoice voided')
      closeDetail(); load()
    } catch { toast.error('Failed to void invoice') }
    finally { setActing(false) }
  }

  const handleExtendDue = async () => {
    if (!selected || !extendDueDate) return
    setExtendingDue(true)
    try {
      const [d, m, y] = extendDueDate.split('/')
      const isoDate = `${y}-${m}-${d}`
      const res = await salesApi.extendDueDate(selected.id, { new_due_date: isoDate, reason: extendReason })
      setDetail(res.data)
      setSelected(res.data)
      setInvoices((prev) => prev.map((i) => i.id === selected.id ? res.data : i))
      setShowExtendDue(false)
      setExtendDueDate('')
      setExtendReason('')
      toast.success('Due date extended')
    } catch (err: any) {
      const msg = err?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : 'Failed to extend due date')
    } finally { setExtendingDue(false) }
  }

  const handleSaveEdit = async () => {
    if (!selected) return
    setSavingEdit(true)
    try {
      const { data } = await salesApi.updateInvoice(selected.id, editInvoiceForm)
      toast.success('Invoice updated')
      setDetail(data)
      setSelected(data)
      setShowEditInvoice(false)
      load()
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to update invoice'))
    } finally { setSavingEdit(false) }
  }

  const handleDeleteInvoice = async () => {
    if (!selected) return
    if (!confirm(`Delete invoice ${selected.invoice_number}? This cannot be undone.`)) return
    try {
      await salesApi.deleteInvoice(selected.id)
      toast.success('Invoice deleted')
      closeDetail()
      load()
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to delete invoice'))
    }
  }

  const handleExportPDF = async () => {
    if (!inv) return
    setExporting(true)
    try {
      const preview = await buildInvoicePDF(
        inv,
        organisation?.name ?? 'Audity',
        logoDataUrl ?? organisation?.logo,
        organisation?.address,
        organisation?.phone,
        organisation?.email,
        organisation?.bank_name,
        organisation?.bank_account_number,
        organisation?.bank_account_name,
        organisation?.bank_sort_code,
        organisation?.brand_color,
        organisation?.invoice_company_name,
        organisation?.company_name_font,
        organisation?.company_name_font_size,
        organisation?.company_name_font_bold,
        organisation?.company_name_font_italic,
        organisation?.company_name_font_underline,
        organisation?.company_name_font_color,
        organisation?.invoice_template,
        stampDataUrl ?? organisation?.company_stamp,
        organisation?.show_company_name_on_pdf ?? true,
      )
      setPdfPreview(preview)
    } catch { toast.error('Failed to generate PDF') }
    finally { setExporting(false) }
  }

  const closePdfPreview = () => {
    if (pdfPreview) URL.revokeObjectURL(pdfPreview.url)
    setPdfPreview(null)
  }

  const saveToDevice = async () => {
    if (!pdfPreview) return
    const res = await fetch(pdfPreview.url)
    const blob = await res.blob()
    await saveBlobFile(blob, pdfPreview.filename)
  }

  const shareViaWhatsApp = () => {
    if (!inv) return
    const invDetail = detail ?? inv
    const itemLines = (invDetail?.items ?? []).map((item: any) =>
      `  • ${item.product_name} ×${Number(item.quantity)} = ${formatCurrency(item.line_total)}`
    ).join('\n')
    const msg =
      `*Invoice ${inv.invoice_number}*\n` +
      `From: ${organisation?.name ?? 'Audity'}\n` +
      `Customer: ${inv.customer_name ?? 'Walk-in'}\n` +
      `Date: ${formatDate(inv.issue_date)}\n\n` +
      (itemLines ? `${itemLines}\n\n` : '') +
      `*Total: ${formatCurrency(inv.total_amount)}*\n` +
      `Paid: ${formatCurrency(inv.amount_paid)}\n` +
      `*Balance Due: ${formatCurrency(inv.amount_due)}*\n\n` +
      `Thank you for your business!`
    const url = `https://wa.me/?text=${encodeURIComponent(msg)}`
    navigator.clipboard.writeText(url).then(() => {
      toast.success('WhatsApp link copied! Open WhatsApp and paste to share.')
    }).catch(() => {
      toast('WhatsApp link: ' + url, { duration: 8000 })
    })
  }

  const handleDeliveryNote = async () => {
    if (!inv) return
    setExportingDelivery(true)
    try {
      const preview = await buildDeliveryNotePDF(
        inv,
        organisation?.name ?? 'Audity',
        organisation?.address,
        organisation?.brand_color,
        organisation?.invoice_company_name,
        organisation?.company_name_font,
        logoDataUrl ?? organisation?.logo,
        stampDataUrl ?? organisation?.company_stamp,
        organisation?.invoice_template,
        organisation?.show_company_name_on_pdf ?? true,
        organisation?.company_name_font_color,
        organisation?.company_name_font_size,
        organisation?.company_name_font_bold,
        organisation?.company_name_font_italic,
        organisation?.company_name_font_underline,
        organisation?.phone,
        organisation?.email,
      )
      setPdfPreview(preview)
    } catch { toast.error('Failed to generate delivery note') }
    finally { setExportingDelivery(false) }
  }

  const openEmailModal = () => {
    setEmailTo('')
    setShowEmailModal(true)
  }

  const handleSendEmail = async () => {
    if (!selected) return
    setSendingEmail(true)
    try {
      let pdf_base64: string | undefined

      // Always generate the PDF as an attachment — use existing preview if available,
      // otherwise build it on-the-fly so the email always includes the PDF attachment.
      const inv = selected
      const pdfUrl = pdfPreview?.url
      try {
        let blobUrl = pdfUrl
        if (!blobUrl) {
          const freshPreview = await buildInvoicePDF(
            inv,
            organisation?.name ?? 'Audity',
            logoDataUrl ?? organisation?.logo,
            organisation?.address,
            organisation?.phone,
            organisation?.email,
            organisation?.bank_name,
            organisation?.bank_account_number,
            organisation?.bank_account_name,
            organisation?.bank_sort_code,
            organisation?.brand_color,
            organisation?.invoice_company_name,
            organisation?.company_name_font,
            organisation?.company_name_font_size,
            organisation?.company_name_font_bold,
            organisation?.company_name_font_italic,
            organisation?.company_name_font_underline,
            organisation?.company_name_font_color,
            organisation?.invoice_template,
            stampDataUrl ?? organisation?.company_stamp,
          )
          blobUrl = freshPreview.url
        }
        const resp = await fetch(blobUrl)
        const buf = await resp.arrayBuffer()
        const bytes = new Uint8Array(buf)
        let binary = ''
        bytes.forEach((b) => { binary += String.fromCharCode(b) })
        pdf_base64 = btoa(binary)
      } catch { /* send email without attachment if PDF generation fails */ }

      await salesApi.sendEmail(selected.id, { to_email: emailTo || undefined, pdf_base64 })
      toast.success('Invoice sent by email')
      setShowEmailModal(false)
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to send email')
      toast.error(msg)
    } finally { setSendingEmail(false) }
  }

  const handleConfirmProforma = async () => {
    if (!selected) return
    if (!confirm('Convert this proforma to a confirmed invoice? Stock will be deducted.')) return
    setActing(true)
    try {
      await salesApi.confirmProforma(selected.id)
      toast.success('Proforma confirmed')
      closeDetail(); load()
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to confirm'))
    } finally { setActing(false) }
  }

  const openReturnModal = () => {
    if (!detail) return
    const returnable = (detail.items ?? []).filter((item: any) => {
      const sold = parseFloat(item.quantity)
      const returned = parseFloat(item.quantity_returned ?? '0')
      return sold - returned > 0
    })
    if (returnable.length === 0) {
      toast.error('All items on this invoice have already been fully returned.')
      return
    }
    setReturnItems(
      returnable.map((item: any) => {
        const sold = parseFloat(item.quantity)
        const alreadyReturned = parseFloat(item.quantity_returned ?? '0')
        const remaining = sold - alreadyReturned
        return {
          sale_item_id: item.id,
          quantity_returned: String(remaining),
          max_qty: remaining,
          already_returned: alreadyReturned,
          product_name: item.product_name,
          unit_price: item.unit_price,
        }
      })
    )
    setReturnReason('other')
    setReturnNotes('')
    setReturnDate(new Date().toISOString().split('T')[0])
    setReturnRestocked(true)
    setShowReturn(true)
  }

  const handleReturn = async () => {
    if (!selected) return
    const items = returnItems
      .filter((i) => parseFloat(i.quantity_returned) > 0)
      .map((i) => ({ sale_item_id: i.sale_item_id, quantity_returned: stripCommas(i.quantity_returned) }))
    if (items.length === 0) { toast.error('Enter at least one item quantity to return'); return }
    setProcessingReturn(true)
    try {
      await salesApi.processReturn(selected.id, {
        items,
        reason: returnReason,
        notes: returnNotes,
        return_date: returnDate,
        restocked: returnRestocked,
      })
      toast.success('Return processed successfully')
      setShowReturn(false)
      closeDetail()
      load()
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to process return')
      toast.error(msg)
    } finally { setProcessingReturn(false) }
  }

  const inv = detail ?? selected

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Sales & Invoices</h1>
          <p className="text-slate-400 text-sm">{invoices.length} invoices</p>
        </div>
        <div className="flex items-center gap-2 sm:ml-auto">
          <button onClick={() => { bypassNextGets(); load() }} disabled={loading} className="btn-ghost p-2 text-slate-400 hover:text-white" title="Refresh">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <Link to="/sales/new" className="btn-primary">
            <Plus size={16} /> New Sale
          </Link>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input className="input pl-9" placeholder="Search invoice number…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <SortSelect
          value={sortBy}
          onChange={setSortBy}
          options={[
            { label: 'Newest first', value: '-issue_date' },
            { label: 'Oldest first', value: 'issue_date' },
            { label: 'Amount ↓', value: '-total_amount' },
            { label: 'Amount ↑', value: 'total_amount' },
          ]}
        />
        <select className="input max-w-xs" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {STATUS_OPTIONS.filter(Boolean).map((s) => (
            <option key={s} value={s}>{s.replace('_', ' ')}</option>
          ))}
        </select>
        <YearFilter selectedYear={archiveYear} onChange={handleYearChange} />
        <MonthFilter selectedMonth={archiveMonth} onChange={handleMonthChange} />
        <DateInput value={customDateFrom} onChange={handleCustomDateFrom} placeholder="From" className="input py-1.5 text-sm w-32" />
        <DateInput value={customDateTo} onChange={handleCustomDateTo} placeholder="To" className="input py-1.5 text-sm w-32" />
        {(customDateFrom || customDateTo) && (
          <button onClick={() => { setCustomDateFrom(''); setCustomDateTo('') }} className="btn-ghost p-1.5 text-slate-400 hover:text-white" title="Clear custom date filter"><X size={14} /></button>
        )}
        <ExportButton endpoint="/sales/invoices/" filename="invoices" params={activeDateParams} />
      </div>

      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Invoice #', 'Customer', 'Date', 'Total', 'Paid', 'Due', 'Status', ''].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 8 }).map((_, j) => (
                      <td key={j} className="px-5 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-20" /></td>
                    ))}
                  </tr>
                ))
              ) : invoices.length === 0 ? (
                <tr><td colSpan={8} className="px-5 py-12 text-center">
                  <Receipt size={32} className="mx-auto mb-2 text-slate-600" />
                  <p className="text-slate-500">No invoices yet</p>
                </td></tr>
              ) : (
                invoices.map((inv) => (
                  <tr key={inv.id} className="table-row">
                    <td className="px-5 py-3.5 font-mono text-brand-400 text-xs font-medium">{inv.invoice_number}</td>
                    <td className="px-5 py-3.5 text-white">{inv.customer_name ?? <span className="text-slate-500">Walk-in</span>}</td>
                    <td className="px-5 py-3.5 text-slate-400">{formatDate(inv.issue_date)}</td>
                    <td className="px-5 py-3.5 font-semibold text-white">{formatCurrency(inv.total_amount)}</td>
                    <td className="px-5 py-3.5 text-green-400">{formatCurrency(inv.amount_paid)}</td>
                    <td className="px-5 py-3.5 text-red-400">{formatCurrency(inv.amount_due)}</td>
                    <td className="px-5 py-3.5">
                      <span className={getStatusColor(inv.status)}>{inv.status.replace('_', ' ')}</span>
                      {/* FIRS compliance badge — only shown when the org is enrolled and the invoice has a FIRS status */}
                      {inv.firs_status && inv.firs_status !== 'not_enrolled' && (
                        <span className={`ml-1.5 px-1 py-0.5 rounded text-[9px] font-bold uppercase tracking-wide ${
                          inv.firs_status === 'cleared'   ? 'bg-green-500/20 text-green-300' :
                          inv.firs_status === 'submitted' ? 'bg-blue-500/20 text-blue-300' :
                          inv.firs_status === 'failed'    ? 'bg-red-500/20 text-red-300' :
                          inv.firs_status === 'bypassed'  ? 'bg-slate-600/50 text-slate-400' :
                          'bg-amber-500/20 text-amber-300'
                        }`} title={`FIRS: ${inv.firs_status}`}>
                          FIRS {inv.firs_status === 'cleared' ? '✓' : inv.firs_status}
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-1">
                        <button onClick={() => openDetail(inv)} className="btn-ghost p-1.5 text-brand-400 hover:text-brand-300" title="View details">
                          <Receipt size={14} />
                        </button>
                        {(isOwnerOrAdmin || canEditSales) && inv.status !== 'voided' && (
                          <button
                            onClick={async (e) => {
                              e.stopPropagation()
                              await openDetail(inv)
                              setEditInvoiceForm({
                                notes: inv.notes ?? '',
                                due_date: inv.due_date ?? '',
                                issue_date: inv.issue_date ?? '',
                                payment_method: inv.payment_method ?? '',
                              })
                              setShowEditInvoice(true)
                            }}
                            className="btn-ghost p-1.5 text-slate-400 hover:text-white"
                            title="Edit invoice"
                          >
                            <Pencil size={14} />
                          </button>
                        )}
                        {isOwnerOrAdmin && (inv.status === 'draft' || inv.status === 'proforma') && (
                          <button
                            onClick={async (e) => {
                              e.stopPropagation()
                              if (!confirm(`Delete invoice ${inv.invoice_number}?`)) return
                              try {
                                await salesApi.deleteInvoice(inv.id)
                                toast.success('Invoice deleted')
                                load()
                              } catch (err: any) {
                                const apiErr = err?.response?.data?.error
                                toast.error(typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to delete'))
                              }
                            }}
                            className="btn-ghost p-1.5 text-slate-400 hover:text-red-400"
                            title="Delete invoice"
                          >
                            <Trash2 size={14} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Invoice Detail Drawer ───────────────────────────────────────────── */}
      {selected && (
        <>
          <div className="fixed inset-0 z-40 bg-black/50" onClick={closeDetail} />
          <div className="fixed right-0 top-0 bottom-0 z-50 w-full max-w-md bg-surface-900 border-l border-surface-700 shadow-2xl flex flex-col overflow-hidden">
            {/* Drawer header */}
            <div className="flex items-center justify-between px-6 py-5 border-b border-surface-700">
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wider">Invoice</p>
                <h2 className="font-bold text-white text-lg">{inv?.invoice_number}</h2>
              </div>
              <div className="flex items-center gap-2">
                {(isOwnerOrAdmin || canEditSales) && inv?.status !== 'voided' && inv && (
                  <button
                    onClick={() => navigate(`/sales/invoices/${inv.id}/edit`)}
                    title="Edit Invoice"
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-600 text-slate-300 hover:bg-surface-700 text-xs font-medium transition-colors"
                  >
                    <Pencil size={14} /> Edit
                  </button>
                )}
                <button
                  onClick={handleDeliveryNote}
                  disabled={exportingDelivery || !detail}
                  title="Generate Delivery Note"
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/10 text-xs font-medium transition-colors disabled:opacity-50"
                >
                  {exportingDelivery ? <Loader2 size={14} className="animate-spin" /> : <Truck size={14} />}
                  Delivery Note
                </button>
                <button
                  onClick={openEmailModal}
                  title="Send by Email"
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-600 text-slate-300 hover:bg-surface-700 text-xs font-medium transition-colors"
                >
                  <Mail size={14} /> Email
                </button>
                <button
                  onClick={handleExportPDF}
                  disabled={exporting}
                  title="Preview & Export PDF"
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-brand-500/40 text-brand-400 hover:bg-brand-500/10 text-xs font-medium transition-colors disabled:opacity-50"
                >
                  {exporting ? <Loader2 size={14} className="animate-spin" /> : <FileDown size={14} />}
                  Export PDF
                </button>
                <button onClick={closeDetail} className="btn-ghost p-2"><X size={18} /></button>
              </div>
            </div>

            {/* Drawer body */}
            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-slate-500 mb-1">Customer</p>
                  <p className="text-sm font-medium text-white">{inv?.customer_name ?? 'Walk-in'}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500 mb-1">Date</p>
                  <p className="text-sm text-slate-300">{inv ? formatDate(inv.issue_date) : '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-500 mb-1">Status</p>
                  <span className={getStatusColor(inv?.status ?? '')}>{inv?.status.replace('_', ' ')}</span>
                </div>
                <div>
                  <p className="text-xs text-slate-500 mb-1">Payment</p>
                  <p className="text-sm text-slate-300">{inv?.payment_method.replace('_', ' ')}</p>
                </div>
                {inv?.sold_by && (
                  <div>
                    <p className="text-xs text-slate-500 mb-1">Sold By</p>
                    <p className="text-sm text-slate-300">{inv.sold_by}</p>
                  </div>
                )}
              </div>

              {/* Line items */}
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wider mb-3">Items</p>
                <div className="space-y-2">
                  {(inv?.items ?? []).map((item) => (
                    <div key={item.id} className="flex items-center gap-3 py-2.5 border-b border-surface-700/60 last:border-0">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-white truncate">{item.product_name}</p>
                        <p className="text-xs text-slate-500">{item.product_sku} · {item.quantity} × {formatCurrency(item.unit_price)}</p>
                      </div>
                      <p className="text-sm font-semibold text-white shrink-0">{formatCurrency(item.line_total)}</p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Totals */}
              <div className="bg-surface-800 rounded-xl p-4 space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-slate-400">Total</span>
                  <span className="font-semibold text-white">{formatCurrency(inv?.total_amount ?? 0)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-slate-400">Paid</span>
                  <span className="text-green-400">{formatCurrency(inv?.amount_paid ?? 0)}</span>
                </div>
                <div className="flex justify-between text-sm border-t border-surface-700 pt-2">
                  <span className="text-slate-400">Amount Due</span>
                  <span className={`font-bold ${parseFloat(inv?.amount_due ?? '0') > 0 ? 'text-red-400' : 'text-green-400'}`}>
                    {formatCurrency(inv?.amount_due ?? 0)}
                  </span>
                </div>
              </div>

              {/* Record payment */}
              {inv?.status !== 'paid' && inv?.status !== 'voided' && parseFloat(inv?.amount_due ?? '0') > 0 && (
                <div>
                  <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Record Payment</p>
                  <div className="flex gap-2 mb-2">
                    <select
                      className="input w-36 text-sm"
                      value={payMethod}
                      onChange={(e) => { setPayMethod(e.target.value); setTenderedAmount('') }}
                    >
                      <option value="cash">Cash</option>
                      <option value="pos">POS</option>
                      <option value="bank_transfer">Bank Transfer</option>
                      <option value="cheque">Cheque</option>
                      <option value="credit_applied">Credit Applied</option>
                    </select>
                    <input
                      type="text"
                      inputMode="decimal"
                      className="input flex-1"
                      value={payAmount}
                      onChange={(e) => setPayAmount(formatAmountInput(e.target.value))}
                      placeholder="Amount"
                    />
                    <button onClick={handlePay} disabled={acting} className="btn-primary px-4">
                      {acting ? <Loader2 size={16} className="animate-spin" /> : <><CheckCircle size={15} /> Pay</>}
                    </button>
                  </div>
                  {payMethod === 'cash' && (
                    <div className="space-y-1.5">
                      <input
                        type="text"
                        inputMode="decimal"
                        className="input w-full text-sm"
                        value={tenderedAmount}
                        onChange={(e) => setTenderedAmount(formatAmountInput(e.target.value))}
                        placeholder="Amount tendered (optional)"
                      />
                      {tenderedAmount && parseFloat(stripCommas(tenderedAmount)) >= 0 && (
                        <div className="flex justify-between text-sm px-1">
                          <span className="text-slate-400">Change due</span>
                          <span className={parseFloat(stripCommas(tenderedAmount)) - parseFloat(stripCommas(payAmount)) >= 0 ? 'text-emerald-400 font-semibold' : 'text-red-400 font-semibold'}>
                            {formatCurrency(String(Math.max(0, parseFloat(stripCommas(tenderedAmount)) - parseFloat(stripCommas(payAmount)))))}
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Drawer footer */}
            {inv?.status !== 'voided' && (
              <div className="border-t border-surface-700 px-6 py-4 space-y-2">
                {inv?.status === 'proforma' && (
                  <button
                    onClick={handleConfirmProforma}
                    disabled={acting}
                    className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border border-brand-500/30 text-brand-400 hover:bg-brand-500/10 text-sm font-medium transition-colors disabled:opacity-50"
                  >
                    <CheckCircle size={14} /> Confirm Proforma → Invoice
                  </button>
                )}
                {(inv?.status === 'paid' || inv?.status === 'partially_paid' || inv?.status === 'credit' || inv?.status === 'confirmed') && (
                  <button
                    onClick={openReturnModal}
                    disabled={acting || !detail}
                    className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border border-green-500/30 text-green-400 hover:bg-green-500/10 text-sm font-medium transition-colors disabled:opacity-50"
                  >
                    <RotateCcw size={14} /> Process Return / Credit Note
                  </button>
                )}
                {(inv?.status === 'credit' || inv?.status === 'overdue' || inv?.status === 'partially_paid') && (
                  <button
                    onClick={() => setShowExtendDue(true)}
                    className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border border-sky-500/30 text-sky-400 hover:bg-sky-500/10 text-sm font-medium transition-colors"
                  >
                    <CalendarClock size={14} /> Extend Due Date
                  </button>
                )}
                <button
                  onClick={handleVoid}
                  disabled={acting}
                  className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border border-red-500/30 text-red-400 hover:bg-red-500/10 text-sm font-medium transition-colors"
                >
                  <Ban size={14} /> Void Invoice
                </button>
                {isOwnerOrAdmin && (inv?.status === 'draft' || inv?.status === 'proforma') && (
                  <button
                    onClick={handleDeleteInvoice}
                    className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border border-red-800/40 text-red-500 hover:bg-red-900/20 text-sm font-medium transition-colors"
                  >
                    <Trash2 size={14} /> Delete Invoice
                  </button>
                )}
              </div>
            )}
          </div>
        </>
      )}

      {/* ── Edit Invoice Modal ──────────────────────────────────────────────── */}
      {showEditInvoice && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60" onClick={() => setShowEditInvoice(false)} />
          <div className="relative bg-surface-900 border border-surface-700 rounded-2xl shadow-2xl w-full max-w-sm p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Edit Invoice</h2>
              <button onClick={() => setShowEditInvoice(false)} className="btn-ghost p-1.5"><X size={18} /></button>
            </div>
            <p className="text-xs text-slate-500">
              Editing <span className="text-brand-400 font-mono">{inv?.invoice_number}</span> · Only metadata can be changed. Amounts and items are locked to preserve accounting integrity.
            </p>
            <div className="space-y-3">
              <div>
                <label className="label">Issue Date</label>
                <DateInput
                  value={editInvoiceForm.issue_date}
                  onChange={(v) => setEditInvoiceForm(f => ({ ...f, issue_date: v }))}
                />
              </div>
              <div>
                <label className="label">Due Date</label>
                <DateInput
                  value={editInvoiceForm.due_date}
                  onChange={(v) => setEditInvoiceForm(f => ({ ...f, due_date: v }))}
                />
              </div>
              <div>
                <label className="label">Payment Method</label>
                <select
                  className="input"
                  value={editInvoiceForm.payment_method}
                  onChange={(e) => setEditInvoiceForm(f => ({ ...f, payment_method: e.target.value }))}
                >
                  <option value="cash">Cash</option>
                  <option value="pos">POS</option>
                  <option value="bank_transfer">Bank Transfer</option>
                  <option value="cheque">Cheque</option>
                  <option value="credit">Credit</option>
                </select>
              </div>
              <div>
                <label className="label">Notes</label>
                <textarea
                  className="input resize-none"
                  rows={3}
                  value={editInvoiceForm.notes}
                  onChange={(e) => setEditInvoiceForm(f => ({ ...f, notes: e.target.value }))}
                  placeholder="Internal notes…"
                />
              </div>
            </div>
            <div className="flex gap-3 pt-1">
              <button onClick={() => setShowEditInvoice(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleSaveEdit} disabled={savingEdit} className="btn-primary flex-1 flex items-center justify-center gap-2">
                {savingEdit ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle size={15} />}
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Extend Due Date Modal ──────────────────────────────────────────── */}
      {showExtendDue && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60" onClick={() => setShowExtendDue(false)} />
          <div className="relative bg-surface-900 border border-surface-700 rounded-2xl shadow-2xl w-full max-w-sm p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Extend Due Date</h2>
              <button onClick={() => setShowExtendDue(false)} className="btn-ghost p-1.5"><X size={18} /></button>
            </div>
            <p className="text-xs text-slate-500">
              Invoice <span className="text-brand-400 font-mono">{inv?.invoice_number}</span> · Current due date: <span className="text-white">{inv?.due_date ? formatDate(inv.due_date) : '—'}</span>
            </p>
            <div className="space-y-3">
              <div>
                <label className="label">New Due Date</label>
                <DateInput
                  value={extendDueDate}
                  onChange={setExtendDueDate}
                  placeholder="DD/MM/YYYY"
                />
              </div>
              <div>
                <label className="label">Reason (optional)</label>
                <textarea
                  className="input resize-none"
                  rows={2}
                  value={extendReason}
                  onChange={(e) => setExtendReason(e.target.value)}
                  placeholder="e.g. Customer requested extension…"
                />
              </div>
            </div>
            <div className="flex gap-3 pt-1">
              <button onClick={() => setShowExtendDue(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleExtendDue} disabled={extendingDue || !extendDueDate} className="btn-primary flex-1 flex items-center justify-center gap-2">
                {extendingDue ? <Loader2 size={15} className="animate-spin" /> : <CalendarClock size={15} />}
                Extend
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Send Email Modal ────────────────────────────────────────────────── */}
      {showEmailModal && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60" onClick={() => setShowEmailModal(false)} />
          <div className="relative bg-surface-900 border border-surface-700 rounded-2xl shadow-2xl w-full max-w-sm p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Send Invoice by Email</h2>
              <button onClick={() => setShowEmailModal(false)} className="btn-ghost p-1.5"><X size={18} /></button>
            </div>
            <p className="text-xs text-slate-500">
              Invoice <span className="text-brand-400 font-mono">{inv?.invoice_number}</span> will be sent with a PDF attachment.
            </p>
            <div>
              <label className="label">Recipient Email</label>
              <input
                type="email"
                className="input"
                placeholder={inv?.customer_name ? `${inv.customer_name}'s email` : 'customer@email.com'}
                value={emailTo}
                onChange={(e) => setEmailTo(e.target.value)}
                autoFocus
              />
              <p className="text-xs text-slate-500 mt-1">Leave blank to use customer's saved email.</p>
            </div>
            <div className="flex gap-3 pt-1">
              <button onClick={() => setShowEmailModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleSendEmail} disabled={sendingEmail} className="btn-primary flex-1">
                {sendingEmail ? <Loader2 size={15} className="animate-spin" /> : <Mail size={15} />}
                Send
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Sales Return Modal ──────────────────────────────────────────────── */}
      {showReturn && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60" onClick={() => setShowReturn(false)} />
          <div className="relative bg-surface-900 border border-surface-700 rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-surface-700">
              <div>
                <h2 className="text-lg font-bold text-white">Process Return</h2>
                <p className="text-xs text-slate-500">Credit Note for {inv?.invoice_number}</p>
              </div>
              <button onClick={() => setShowReturn(false)} className="btn-ghost p-2"><X size={18} /></button>
            </div>
            {/* Body */}
            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
              {/* Items */}
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Return Quantities</p>
                <div className="space-y-2">
                  {returnItems.map((item, idx) => (
                    <div key={item.sale_item_id} className="flex items-center gap-3 bg-surface-800 rounded-lg px-3 py-2.5">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-white truncate">{item.product_name}</p>
                        <p className="text-xs text-slate-500">
                          Returnable: {item.max_qty}
                          {item.already_returned > 0 && (
                            <span className="ml-1 text-amber-400">({item.already_returned} already returned)</span>
                          )}
                          {' · '}{formatCurrency(item.unit_price)} each
                        </p>
                      </div>
                      <input
                        type="text"
                        inputMode="decimal"
                        className="input w-24 text-right text-sm"
                        value={item.quantity_returned}
                        onChange={(e) => {
                          const v = e.target.value
                          const num = parseFloat(v)
                          if (!isNaN(num) && num > item.max_qty) return
                          setReturnItems((prev) => prev.map((it, i) => i === idx ? { ...it, quantity_returned: v } : it))
                        }}
                        placeholder="Qty"
                      />
                    </div>
                  ))}
                </div>
              </div>

              {/* Reason */}
              <div>
                <label className="label">Reason</label>
                <select className="input" value={returnReason} onChange={(e) => setReturnReason(e.target.value)}>
                  {RETURN_REASONS.map((r) => (
                    <option key={r.value} value={r.value}>{r.label}</option>
                  ))}
                </select>
              </div>

              {/* Return date */}
              <div>
                <label className="label">Return Date</label>
                <DateInput value={returnDate} onChange={setReturnDate} />
              </div>

              {/* Restock toggle */}
              <div className="flex items-center gap-3">
                <input
                  id="restock"
                  type="checkbox"
                  checked={returnRestocked}
                  onChange={(e) => setReturnRestocked(e.target.checked)}
                  className="w-4 h-4 rounded accent-brand-500"
                />
                <label htmlFor="restock" className="text-sm text-slate-300 cursor-pointer">
                  Items physically returned to stock
                </label>
              </div>

              {/* Notes */}
              <div>
                <label className="label">Notes (optional)</label>
                <textarea
                  className="input"
                  rows={2}
                  value={returnNotes}
                  onChange={(e) => setReturnNotes(e.target.value)}
                  placeholder="Any additional notes…"
                />
              </div>
            </div>
            {/* Footer */}
            <div className="px-6 py-4 border-t border-surface-700 flex gap-3 justify-end">
              <button onClick={() => setShowReturn(false)} className="btn-ghost">Cancel</button>
              <button
                onClick={handleReturn}
                disabled={processingReturn}
                className="btn-primary"
              >
                {processingReturn ? <Loader2 size={15} className="animate-spin" /> : <RotateCcw size={15} />}
                Process Return
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── PDF Preview Modal ───────────────────────────────────────────────── */}
      {pdfPreview && (
        <div className="fixed inset-0 z-[60] flex flex-col">
          {/* Toolbar */}
          <div className="flex items-center justify-between px-4 py-3 bg-surface-900 border-b border-surface-700 shrink-0">
            <button
              onClick={saveToDevice}
              title="Save to device"
              className="flex items-center gap-2 min-w-0 group hover:opacity-80 transition-opacity"
            >
              <FileDown size={15} className="text-brand-400 shrink-0 group-hover:text-brand-300" />
              <span className="text-sm font-medium text-white truncate">{pdfPreview.filename}</span>
            </button>
            <div className="flex items-center gap-2 ml-4">
              {/* Email — sends via backend API with PDF attached */}
              <button
                onClick={openEmailModal}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-surface-600 text-slate-300 text-xs font-medium hover:bg-surface-700 transition-colors"
              >
                <Mail size={13} /> Email
              </button>
              {/* WhatsApp */}
              <button
                onClick={shareViaWhatsApp}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-green-500/40 text-green-400 text-xs font-medium hover:bg-green-500/10 transition-colors"
              >
                <MessageCircle size={13} /> WhatsApp
              </button>
              {/* Close */}
              <button
                onClick={closePdfPreview}
                className="ml-1 p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-surface-700 transition-colors"
              >
                <X size={18} />
              </button>
            </div>
          </div>
          {/* PDF iframe */}
          <iframe
            src={pdfPreview.url}
            className="flex-1 w-full border-0 bg-white"
            title="Invoice Preview"
          />
        </div>
      )}
    </div>
  )
}
