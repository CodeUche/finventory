import { useEffect, useState } from 'react'
import { Plus, Receipt, Search, X, Loader2, CheckCircle, Ban, FileDown, Mail, MessageCircle, Download, RotateCcw, Truck } from 'lucide-react'
import SortSelect from '@/components/SortSelect'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import { salesApi } from '@/services/api'
import { formatCurrency, formatDate, getStatusColor, formatAmountInput, stripCommas } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import DateInput from '@/components/DateInput'
import type { Invoice } from '@/types'

const STATUS_OPTIONS = ['', 'paid', 'proforma', 'confirmed', 'partially_paid', 'credit', 'overdue', 'voided']
const RETURN_REASONS = [
  { value: 'defective',       label: 'Defective / Damaged' },
  { value: 'wrong_item',      label: 'Wrong Item Delivered' },
  { value: 'customer_change', label: 'Customer Changed Mind' },
  { value: 'overcharge',      label: 'Overcharge / Price Error' },
  { value: 'other',           label: 'Other' },
]

interface PdfPreview { url: string; filename: string }
interface ReturnLineItem { sale_item_id: string; quantity_returned: string; max_qty: number; product_name: string; unit_price: string }

/** Parse a CSS hex color into an RGB triple for jsPDF. Falls back to orange on invalid input. */
function hexToRgb(hex?: string): [number, number, number] {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
  if (!m) return [249, 115, 22]
  return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
}

/** Fetch any URL and return a base-64 data URL for jsPDF addImage. */
async function urlToDataUrl(url: string): Promise<string | null> {
  try {
    const res = await fetch(url)
    const blob = await res.blob()
    return await new Promise<string>((resolve, reject) => {
      const r = new FileReader()
      r.onloadend = () => resolve(r.result as string)
      r.onerror = reject
      r.readAsDataURL(blob)
    })
  } catch {
    return null
  }
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
  orgLetterhead?: string,
  brandColorHex?: string,
  useLetterhead?: boolean,
): Promise<PdfPreview> {
  const { jsPDF } = await import('jspdf')
  const { default: autoTable } = await import('jspdf-autotable')

  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()
  const pageH = doc.internal.pageSize.getHeight()

  const BRAND: [number, number, number] = hexToRgb(brandColorHex)
  const DARK: [number, number, number]  = [30,  30,  30]
  const MUTED: [number, number, number] = [100, 100, 100]
  const LIGHT: [number, number, number] = [250, 250, 248]

  let y = 14

  // ── Header: letterhead banner OR brand-color bar ────────────────────────────
  if (useLetterhead && orgLetterhead) {
    // Only image letterheads can be embedded by jsPDF (PDF/DOC cannot be inlined)
    const isImageUrl = /\.(png|jpe?g|gif|webp|svg)(\?|$)/i.test(orgLetterhead)
    if (isImageUrl) {
      const lhData = await urlToDataUrl(orgLetterhead)
      if (lhData) {
        const LETTERHEAD_H = 30
        doc.addImage(lhData, 'PNG', 0, 0, pageW, LETTERHEAD_H)
        y = LETTERHEAD_H + 4
      } else {
        doc.setFillColor(...BRAND)
        doc.rect(0, 0, pageW, 3, 'F')
      }
    } else {
      doc.setFillColor(...BRAND)
      doc.rect(0, 0, pageW, 3, 'F')
    }
  } else {
    doc.setFillColor(...BRAND)
    doc.rect(0, 0, pageW, 3, 'F')
  }

  // ── Logo ───────────────────────────────────────────────────────────────────
  if (orgLogo && !(useLetterhead && orgLetterhead)) {
    try {
      const b64 = await urlToDataUrl(orgLogo)
      if (b64) doc.addImage(b64, b64.includes('image/png') ? 'PNG' : 'JPEG', 14, y + 2, 26, 26)
    } catch { /* skip logo on error */ }
  }

  // ── Company info (left) ────────────────────────────────────────────────────
  const textX = (orgLogo && !(useLetterhead && orgLetterhead)) ? 46 : 14
  doc.setFontSize(14)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(...DARK)
  doc.text(orgName, textX, y + 10)

  doc.setFontSize(8)
  doc.setFont('helvetica', 'normal')
  doc.setTextColor(...MUTED)
  let infoY = y + 16
  if (orgAddress) { doc.text(orgAddress, textX, infoY); infoY += 4.5 }
  if (orgPhone)   { doc.text(`Tel: ${orgPhone}`, textX, infoY); infoY += 4.5 }
  if (orgEmail)   { doc.text(`Email: ${orgEmail}`, textX, infoY); infoY += 4.5 }

  // ── INVOICE label + meta (right) ──────────────────────────────────────────
  doc.setFontSize(28)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(...BRAND)
  doc.text('INVOICE', pageW - 14, y + 10, { align: 'right' })

  const metaY = y + 18
  const metaRows: [string, string][] = [
    ['Invoice No.',  inv.invoice_number],
    ['Issue Date',   formatDate(inv.issue_date)],
    ['Payment Via',  inv.payment_method.replace(/_/g, ' ')],
    ['Status',       inv.status.replace(/_/g, ' ').toUpperCase()],
  ]
  metaRows.forEach(([label, value], i) => {
    doc.setFontSize(8)
    doc.setFont('helvetica', 'normal')
    doc.setTextColor(...MUTED)
    doc.text(label, pageW - 70, metaY + i * 5.5)
    doc.setFont('helvetica', 'bold')
    doc.setTextColor(...DARK)
    doc.text(value, pageW - 14, metaY + i * 5.5, { align: 'right' })
  })

  y = Math.max(infoY, metaY + metaRows.length * 5.5) + 6

  // ── Divider ────────────────────────────────────────────────────────────────
  doc.setDrawColor(...BRAND)
  doc.setLineWidth(0.5)
  doc.line(14, y, pageW - 14, y)
  y += 8

  // ── Bill To block ─────────────────────────────────────────────────────────
  const billW = (pageW - 28) * 0.48
  doc.setFillColor(...LIGHT)
  doc.roundedRect(14, y, billW, 20, 2, 2, 'F')

  doc.setFontSize(7)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(...BRAND)
  doc.text('BILL TO', 19, y + 6)

  doc.setFontSize(10)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(...DARK)
  doc.text(inv.customer_name ?? 'Walk-in Customer', 19, y + 13)

  doc.setFontSize(7.5)
  doc.setFont('helvetica', 'normal')
  doc.setTextColor(...MUTED)
  doc.text('General Customer', 19, y + 18)

  y += 28

  // ── Items table ───────────────────────────────────────────────────────────
  autoTable(doc, {
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
    styles: {
      fontSize: 9,
      cellPadding: { top: 4, bottom: 4, left: 5, right: 5 },
      textColor: DARK,
    },
    headStyles: {
      fillColor: BRAND,
      textColor: [255, 255, 255],
      fontStyle: 'bold',
      fontSize: 8,
    },
    alternateRowStyles: { fillColor: [248, 248, 248] },
    columnStyles: {
      0: { cellWidth: 10,  halign: 'center' },
      1: { cellWidth: 'auto' },
      2: { cellWidth: 28,  halign: 'center' },
      3: { cellWidth: 14,  halign: 'center' },
      4: { cellWidth: 32,  halign: 'right' },
      5: { cellWidth: 32,  halign: 'right', fontStyle: 'bold' },
    },
    margin: { left: 14, right: 14 },
    tableLineColor: [225, 225, 225],
    tableLineWidth: 0.2,
  })

  // ── Totals block ──────────────────────────────────────────────────────────
  const tY   = (doc as any).lastAutoTable.finalY + 8
  const tX   = pageW - 100
  const tW   = 86

  const subtotalNum      = parseFloat(inv.subtotal ?? inv.total_amount ?? '0')
  const discountNum      = parseFloat(inv.discount_amount ?? '0')
  const taxNum           = parseFloat(inv.tax_amount ?? '0')
  const totalNum         = parseFloat(inv.total_amount ?? '0')
  const amtPaidNum       = parseFloat(inv.amount_paid ?? '0')
  const amtDue           = parseFloat(inv.amount_due ?? '0')

  // Extract tendered amount from first payment notes: "Tendered: X, Change: Y"
  const firstPaymentNotes = inv.payments?.[0]?.notes ?? ''
  const tenderedMatch = firstPaymentNotes.match(/Tendered:\s*([\d.]+)/)
  const tenderedNum = tenderedMatch ? parseFloat(tenderedMatch[1]) : amtPaidNum
  const changeNum = tenderedNum > amtPaidNum ? tenderedNum - amtPaidNum : 0

  // Build dynamic rows
  const totalRows: Array<{ label: string; value: string; bold?: boolean; color?: [number,number,number] }> = []
  totalRows.push({ label: 'Subtotal:', value: formatCurrency(subtotalNum) })
  if (discountNum > 0) totalRows.push({ label: 'Discount:', value: `- ${formatCurrency(discountNum)}`, color: [180, 80, 0] })
  if (taxNum > 0)      totalRows.push({ label: 'Tax / VAT:', value: formatCurrency(taxNum) })
  if (discountNum > 0 || taxNum > 0)
    totalRows.push({ label: 'Invoice Total:', value: formatCurrency(totalNum), bold: true })
  if (amtPaidNum > 0) {
    totalRows.push({ label: 'Amount Tendered:', value: formatCurrency(tenderedNum), color: [22, 163, 74] })
    if (changeNum > 0) totalRows.push({ label: 'Change Given:', value: formatCurrency(changeNum), color: [22, 163, 74] })
  }

  const ROW_H = 9
  const PADDING_TOP = 9
  const DIVIDER_GAP = 4
  const boxRows = totalRows.length
  const boxH = PADDING_TOP + boxRows * ROW_H + DIVIDER_GAP + ROW_H + 6  // rows + divider + balance due + bottom pad

  doc.setFillColor(...LIGHT)
  doc.roundedRect(tX, tY, tW, boxH, 2, 2, 'F')

  let rowY = tY + PADDING_TOP
  totalRows.forEach(({ label, value, bold = false, color = DARK }) => {
    doc.setFontSize(9)
    doc.setFont('helvetica', bold ? 'bold' : 'normal')
    doc.setTextColor(...MUTED)
    doc.text(label, tX + 5, rowY)
    doc.setTextColor(...color)
    doc.text(value, pageW - 19, rowY, { align: 'right' })
    rowY += ROW_H
  })

  doc.setDrawColor(210, 210, 210)
  doc.setLineWidth(0.3)
  doc.line(tX + 5, rowY + 2, pageW - 19, rowY + 2)
  rowY += DIVIDER_GAP + 2

  // BALANCE DUE
  doc.setFontSize(10)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(...MUTED)
  doc.text('BALANCE DUE:', tX + 5, rowY)
  const dueColor: [number,number,number] = amtDue > 0 ? [220, 38, 38] : [22, 163, 74]
  doc.setTextColor(...dueColor)
  doc.text(formatCurrency(amtDue), pageW - 19, rowY, { align: 'right' })
  const afterTotalsY = tY + boxH

  // ── Payment note (left of totals) ─────────────────────────────────────────
  doc.setFontSize(7.5)
  doc.setFont('helvetica', 'italic')
  doc.setTextColor(...MUTED)
  doc.text(`Payment method: ${inv.payment_method.replace(/_/g, ' ')}`, 14, tY + 9)

  // ── Bank details block ────────────────────────────────────────────────────
  if (bankName || bankAccountNumber) {
    const bY = afterTotalsY - boxH + 20
    doc.setFontSize(7)
    doc.setFont('helvetica', 'bold')
    doc.setTextColor(...BRAND)
    doc.text('PAYMENT DETAILS', 14, bY)
    doc.setFont('helvetica', 'normal')
    doc.setTextColor(...DARK)
    let bRow = bY + 5
    if (bankName)          { doc.text(`Bank: ${bankName}`,             14, bRow); bRow += 4.5 }
    if (bankAccountName)   { doc.text(`Account Name: ${bankAccountName}`, 14, bRow); bRow += 4.5 }
    if (bankAccountNumber) { doc.text(`Account No.: ${bankAccountNumber}`, 14, bRow); bRow += 4.5 }
    if (bankSortCode)      { doc.text(`Sort Code: ${bankSortCode}`,    14, bRow); bRow += 4.5 }
  }

  // ── Thank you ─────────────────────────────────────────────────────────────
  const thankY = afterTotalsY + 8
  doc.setFontSize(9)
  doc.setFont('helvetica', 'italic')
  doc.setTextColor(...MUTED)
  doc.text('Thank you for your business!', 14, thankY)

  // ── Footer ─────────────────────────────────────────────────────────────────
  doc.setFillColor(...BRAND)
  doc.rect(0, pageH - 12, pageW, 12, 'F')
  doc.setFontSize(7)
  doc.setFont('helvetica', 'normal')
  doc.setTextColor(255, 255, 255)
  doc.text(orgName, 14, pageH - 4.5)
  doc.text(`Generated by Audity  ·  ${new Date().toLocaleDateString()}`, pageW / 2, pageH - 4.5, { align: 'center' })
  if (orgEmail) doc.text(orgEmail, pageW - 14, pageH - 4.5, { align: 'right' })

  // ── Return blob URL ────────────────────────────────────────────────────────
  const blob = doc.output('blob')
  const url  = URL.createObjectURL(blob)
  const filename = `Invoice-${inv.invoice_number}.pdf`
  return { url, filename }
}

// ── Delivery Note PDF builder ─────────────────────────────────────────────────
async function buildDeliveryNotePDF(
  inv: Invoice,
  orgName: string,
  orgAddress?: string,
  orgLetterhead?: string,
  brandColorHex?: string,
  useLetterhead?: boolean,
): Promise<PdfPreview> {
  const { jsPDF } = await import('jspdf')
  const { default: autoTable } = await import('jspdf-autotable')
  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()
  const BRAND: [number, number, number] = hexToRgb(brandColorHex)
  const DARK: [number, number, number] = [30, 30, 30]
  const MUTED: [number, number, number] = [100, 100, 100]

  let y = 14
  if (useLetterhead && orgLetterhead && /\.(png|jpe?g|gif|webp|svg)(\?|$)/i.test(orgLetterhead)) {
    const lhData = await urlToDataUrl(orgLetterhead)
    if (lhData) {
      doc.addImage(lhData, 'PNG', 0, 0, pageW, 30)
      y = 34
    } else {
      doc.setFillColor(...BRAND); doc.rect(0, 0, pageW, 3, 'F')
    }
  } else {
    doc.setFillColor(...BRAND); doc.rect(0, 0, pageW, 3, 'F')
  }
  doc.setFontSize(20)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(...BRAND)
  doc.text('DELIVERY NOTE', pageW / 2, y + 10, { align: 'center' })
  y += 18

  doc.setFontSize(8)
  doc.setFont('helvetica', 'normal')
  doc.setTextColor(...MUTED)
  doc.text(`Ref: ${inv.invoice_number}`, 14, y)
  doc.text(`Date: ${new Date().toLocaleDateString()}`, pageW - 14, y, { align: 'right' })
  y += 7

  doc.setFontSize(10)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(...DARK)
  doc.text('Deliver To:', 14, y)
  doc.setFont('helvetica', 'normal')
  doc.text(inv.customer_name ?? 'Walk-in Customer', 14, y + 5)
  y += 14

  autoTable(doc, {
    startY: y,
    head: [['#', 'Product', 'SKU', 'Qty', '☐ Received']],
    body: (inv.items ?? []).map((item, i) => [
      i + 1, item.product_name, item.product_sku ?? '—', Number(item.quantity), '',
    ]),
    styles: { fontSize: 9, cellPadding: { top: 5, bottom: 5, left: 5, right: 5 } },
    headStyles: { fillColor: BRAND, textColor: [255, 255, 255], fontStyle: 'bold', fontSize: 8 },
    columnStyles: { 0: { cellWidth: 10, halign: 'center' }, 4: { cellWidth: 30, halign: 'center' } },
    margin: { left: 14, right: 14 },
  })

  const finalY = (doc as any).lastAutoTable.finalY + 20
  doc.setFontSize(8)
  doc.setTextColor(...MUTED)
  doc.text('Received by: ___________________________', 14, finalY)
  doc.text('Signature: ___________________________', 14, finalY + 10)
  doc.text(`From: ${orgName}${orgAddress ? ' · ' + orgAddress : ''}`, 14, finalY + 20)

  const blob = doc.output('blob')
  return { url: URL.createObjectURL(blob), filename: `DeliveryNote-${inv.invoice_number}.pdf` }
}

// ─────────────────────────────────────────────────────────────────────────────

export default function SalesPage() {
  const { organisation } = useAuthStore()
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
  const [pdfPreview, setPdfPreview] = useState<PdfPreview | null>(null)
  const [exportingDelivery, setExportingDelivery] = useState(false)
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

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await salesApi.invoices({ search, status: status || undefined, ordering: sortBy })
      setInvoices(data.results ?? data)
    } catch { toast.error('Failed to load invoices') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [search, status, sortBy])

  const openDetail = async (inv: Invoice) => {
    setSelected(inv)
    setPayAmount(formatAmountInput(inv.amount_due))
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
      await salesApi.pay(selected.id, { amount: stripCommas(payAmount), method: payMethod })
      toast.success('Payment recorded')
      closeDetail(); load()
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

  const handleExportPDF = async () => {
    if (!inv) return
    setExporting(true)
    try {
      const preview = await buildInvoicePDF(
        inv,
        organisation?.name ?? 'Audity',
        organisation?.logo,
        organisation?.address,
        organisation?.phone,
        organisation?.email,
        organisation?.bank_name,
        organisation?.bank_account_number,
        organisation?.bank_account_name,
        organisation?.bank_sort_code,
        organisation?.letterhead,
        organisation?.brand_color,
        organisation?.use_letterhead,
      )
      setPdfPreview(preview)
    } catch { toast.error('Failed to generate PDF') }
    finally { setExporting(false) }
  }

  const closePdfPreview = () => {
    if (pdfPreview) URL.revokeObjectURL(pdfPreview.url)
    setPdfPreview(null)
  }

  const saveToDevice = () => {
    if (!pdfPreview) return
    const a = document.createElement('a')
    a.href     = pdfPreview.url
    a.download = pdfPreview.filename
    a.click()
  }

  const shareViaEmail = () => {
    if (!inv) return
    const subject = encodeURIComponent(`Invoice ${inv.invoice_number} – ${organisation?.name ?? 'Audity'}`)
    const invDetail = detail ?? inv
    const itemLines = (invDetail?.items ?? []).map((item: any) =>
      `  • ${item.product_name}  ×${Number(item.quantity)}  @ ${formatCurrency(item.unit_price)}  =  ${formatCurrency(item.line_total)}`
    ).join('\n')
    const body = encodeURIComponent(
      `Dear ${inv.customer_name ?? 'Customer'},\n\n` +
      `Please find the details for Invoice ${inv.invoice_number} below.\n\n` +
      `Invoice No.: ${inv.invoice_number}\n` +
      `Date:        ${formatDate(inv.issue_date)}\n` +
      (inv.due_date ? `Due Date:    ${formatDate(inv.due_date)}\n` : '') +
      `Status:      ${inv.status.replace(/_/g, ' ').toUpperCase()}\n\n` +
      (itemLines ? `${itemLines}\n\n` : '') +
      `Total:       ${formatCurrency(inv.total_amount)}\n` +
      `Paid:        ${formatCurrency(inv.amount_paid)}\n` +
      `Balance Due: ${formatCurrency(inv.amount_due)}\n\n` +
      `Thank you for your business!\n\n${organisation?.name ?? 'Audity'}`
    )
    window.open(`mailto:?subject=${subject}&body=${body}`, '_blank')
  }

  const shareViaWhatsApp = () => {
    if (!inv) return
    const invDetail = detail ?? inv
    const itemLines = (invDetail?.items ?? []).map((item: any) =>
      `  • ${item.product_name} ×${Number(item.quantity)} = ${formatCurrency(item.line_total)}`
    ).join('\n')
    const msg = encodeURIComponent(
      `*Invoice ${inv.invoice_number}*\n` +
      `From: ${organisation?.name ?? 'Audity'}\n` +
      `Customer: ${inv.customer_name ?? 'Walk-in'}\n` +
      `Date: ${formatDate(inv.issue_date)}\n\n` +
      (itemLines ? `${itemLines}\n\n` : '') +
      `*Total: ${formatCurrency(inv.total_amount)}*\n` +
      `Paid: ${formatCurrency(inv.amount_paid)}\n` +
      `*Balance Due: ${formatCurrency(inv.amount_due)}*\n\n` +
      `Thank you for your business!`
    )
    window.open(`https://wa.me/?text=${msg}`, '_blank')
  }

  const handleDeliveryNote = async () => {
    if (!inv) return
    setExportingDelivery(true)
    try {
      const preview = await buildDeliveryNotePDF(
        inv,
        organisation?.name ?? 'Audity',
        organisation?.address,
        organisation?.letterhead,
        organisation?.brand_color,
        organisation?.use_letterhead,
      )
      setPdfPreview(preview)
    } catch { toast.error('Failed to generate delivery note') }
    finally { setExportingDelivery(false) }
  }

  const openEmailModal = () => {
    setEmailTo(inv?.customer_name ? '' : '')
    setShowEmailModal(true)
  }

  const handleSendEmail = async () => {
    if (!selected) return
    setSendingEmail(true)
    try {
      await salesApi.sendEmail(selected.id, { to_email: emailTo || undefined })
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
    setReturnItems(
      (detail.items ?? []).map((item: any) => ({
        sale_item_id: item.id,
        quantity_returned: String(item.quantity),
        max_qty: parseFloat(item.quantity),
        product_name: item.product_name,
        unit_price: item.unit_price,
      }))
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
        <Link to="/sales/new" className="btn-primary sm:ml-auto">
          <Plus size={16} /> New Sale
        </Link>
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
                    </td>
                    <td className="px-5 py-3.5">
                      <button onClick={() => openDetail(inv)} className="text-xs text-brand-400 hover:text-brand-300 font-medium">
                        View
                      </button>
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
                      onChange={(e) => setPayMethod(e.target.value)}
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
                    className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border border-amber-500/30 text-amber-400 hover:bg-amber-500/10 text-sm font-medium transition-colors disabled:opacity-50"
                  >
                    <RotateCcw size={14} /> Process Return / Credit Note
                  </button>
                )}
                <button
                  onClick={handleVoid}
                  disabled={acting}
                  className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl border border-red-500/30 text-red-400 hover:bg-red-500/10 text-sm font-medium transition-colors"
                >
                  <Ban size={14} /> Void Invoice
                </button>
              </div>
            )}
          </div>
        </>
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
              Invoice <span className="text-brand-400 font-mono">{inv?.invoice_number}</span> will be sent as HTML email.
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
                        <p className="text-xs text-slate-500">Max: {item.max_qty} · {formatCurrency(item.unit_price)} each</p>
                      </div>
                      <input
                        type="text"
                        inputMode="decimal"
                        className="input w-24 text-right text-sm"
                        value={item.quantity_returned}
                        onChange={(e) => {
                          const v = e.target.value
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
            <div className="flex items-center gap-2 min-w-0">
              <FileDown size={15} className="text-brand-400 shrink-0" />
              <span className="text-sm font-medium text-white truncate">{pdfPreview.filename}</span>
            </div>
            <div className="flex items-center gap-2 ml-4">
              {/* Save to device */}
              <button
                onClick={saveToDevice}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-brand-500 text-white text-xs font-semibold hover:bg-brand-600 transition-colors"
              >
                <Download size={13} /> Save to Device
              </button>
              {/* Email */}
              <button
                onClick={shareViaEmail}
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
