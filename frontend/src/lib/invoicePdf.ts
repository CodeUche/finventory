import type { Invoice } from '@/types'

export interface PdfPreview { url: string; filename: string }

/** Parse a CSS hex color into an RGB triple for jsPDF. Falls back to orange on invalid input. */
export function hexToRgb(hex?: string): [number, number, number] {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
  if (!m) return [249, 115, 22]
  return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
}



/** Convert a data URL to a PNG with white/near-white pixels made transparent, removing box borders from stamp images. */
export async function stripStampBackground(dataUrl: string): Promise<string> {
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
export async function buildInvoicePDF(
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
  const { applyDocHeader, buildTableStyle, addDocFooter, pdfMoney, COLORS, TYPE } = await import('@/lib/pdfUtils')

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
  const itemAmounts = [...(inv.items ?? []).map(it => pdfMoney(it.line_total)), 'Amount']
  const itemPrices  = [...(inv.items ?? []).map(it => pdfMoney(it.unit_price)), 'Unit Price']
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
      pdfMoney(item.unit_price),
      pdfMoney(item.line_total),
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
  totalRows.push({ label: 'Subtotal', value: pdfMoney(subtotalNum) })
  if (discountNum > 0) totalRows.push({ label: 'Discount', value: `- ${pdfMoney(discountNum)}`, color: COLORS.AMBER })
  if (taxNum > 0)      totalRows.push({ label: 'Tax / VAT', value: pdfMoney(taxNum) })
  if (discountNum > 0 || taxNum > 0 || creditApplied > 0)
    totalRows.push({ label: 'Invoice Total', value: pdfMoney(totalNum), bold: true })
  if (creditApplied > 0)
    totalRows.push({ label: 'Store Credit Applied', value: `- ${pdfMoney(creditApplied)}`, color: COLORS.GREEN })
  if (amtPaidNum > 0) {
    totalRows.push({ label: 'Amount Tendered', value: pdfMoney(tenderedNum), color: COLORS.GREEN })
    if (changeNum > 0) totalRows.push({ label: 'Change Given', value: pdfMoney(changeNum), color: COLORS.GREEN })
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
  doc.text(pdfMoney(amtDue), tX + tW - PAD, rowY, { align: 'right' })

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

