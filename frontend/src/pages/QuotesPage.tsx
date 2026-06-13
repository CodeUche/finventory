import { useEffect, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, X, ClipboardList, Loader2, FileText, ChevronDown, ChevronUp, Trash2, FileDown, Mail, MessageCircle, CheckCircle, ExternalLink, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import { quoteApi, customerApi, inventoryApi, salesApi, urlToDataUrl, bypassNextGets } from '@/services/api'
import { formatCurrency, formatDate, formatAmountInput, stripCommas } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import { saveBlobFile } from '@/lib/saveBlobFile'
import type { Quote, Customer, Warehouse, Product, Invoice } from '@/types'
import DateInput from '@/components/DateInput'
import YearFilter, { yearToDateParams } from '@/components/YearFilter'
import MonthFilter, { monthToDateParams, type ArchiveMonth } from '@/components/MonthFilter'
import { FieldTooltip } from '@/components/FieldTooltip'

interface PdfPreview { url: string; filename: string; quoteId: string }

function hexToRgb(hex?: string): [number, number, number] {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
  if (!m) return [249, 115, 22]
  return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
}


async function buildQuotePDF(
  q: Quote,
  orgName: string,
  orgLogo?: string,
  orgAddress?: string,
  orgPhone?: string,
  orgEmail?: string,
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
): Promise<PdfPreview> {
  const { jsPDF } = await import('jspdf')
  const { default: autoTable } = await import('jspdf-autotable')
  const { applyDocHeader, buildTableStyle, addDocFooter, COLORS, TYPE } = await import('@/lib/pdfUtils')

  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  doc.setLineHeightFactor(1.15)
  const pageW = doc.internal.pageSize.getWidth()
  const tmpl  = invoiceTemplate ?? 'classic'

  const BRAND: [number,number,number] = hexToRgb(brandColorHex)
  const DARK   = COLORS.DARK
  const MUTED  = COLORS.MUTED
  const LIGHT  = COLORS.LIGHT
  const RULE   = COLORS.RULE

  const displayName = companyNameOverride?.trim() || orgName
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
    const c = companyFontColor
    if (!c || c === '#ffffff') return (tmpl === 'modern' || tmpl === 'minimal') ? DARK : COLORS.WHITE
    return hexToRgb(c)
  })()

  let logoData: string | null = null
  if (orgLogo) { try { logoData = await urlToDataUrl(orgLogo) } catch { /* skip */ } }

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
    docTitle: 'QUOTE',
    metaRows: [
      ['No.',         q.quote_number],
      ['Date',        formatDate(q.issue_date)],
      ['Valid Until', formatDate(q.valid_until)],
      ['Status',      q.status?.replace(/_/g, ' ').toUpperCase() ?? ''],
    ],
  })

  // ── Quote For + Quote Details side-by-side boxes ───────────────────────────
  const boxW = 85
  const boxH = 32
  const lBoxX = 14
  const rBoxX = lBoxX + boxW + 4

  // Left: Quote For
  doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
  doc.roundedRect(lBoxX, y, boxW, boxH, 2, 2, 'FD')
  doc.setFontSize(TYPE.H3.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...BRAND)
  doc.text('QUOTE FOR', lBoxX + 3, y + 5)
  doc.setFontSize(TYPE.H2.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...DARK)
  doc.text(q.customer_name ?? 'Walk-in Customer', lBoxX + 3, y + 11)
  doc.setFontSize(TYPE.BODY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
  doc.text(`Valid until: ${formatDate(q.valid_until)}`, lBoxX + 3, y + 16.5)

  // Right: From (seller / organisation details from settings)
  doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
  doc.roundedRect(rBoxX, y, boxW, boxH, 2, 2, 'FD')
  doc.setFontSize(TYPE.H3.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...BRAND)
  doc.text('FROM', rBoxX + 3, y + 5)
  doc.setFontSize(TYPE.H2.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...DARK)
  doc.text(displayName || orgName, rBoxX + 3, y + 11)
  let fromY = y + 16.5
  doc.setFontSize(TYPE.BODY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
  if (orgAddress) { doc.text(orgAddress, rBoxX + 3, fromY); fromY += 4.5 }
  if (orgPhone)   { doc.text(orgPhone,   rBoxX + 3, fromY); fromY += 4.5 }
  if (orgEmail)   { doc.text(orgEmail,   rBoxX + 3, fromY) }

  y += boxH + 6

  // ── Items table ────────────────────────────────────────────────────────────
  const ts = buildTableStyle(BRAND, pdfFont)

  const qAmounts = [...(q.items ?? []).map(it => formatCurrency(it.line_total)), 'Amount']
  const qPrices  = [...(q.items ?? []).map(it => formatCurrency(it.unit_price)), 'Unit Price']
  const qQtys    = [...(q.items ?? []).map(it => String(Number(it.quantity))), 'Qty']
  doc.setFontSize(9)
  const amtColW   = Math.min(58, Math.max(26, Math.max(...qAmounts.map(s => doc.getTextWidth(s))) + 8))
  const priceColW = Math.min(52, Math.max(24, Math.max(...qPrices.map(s => doc.getTextWidth(s))) + 8))
  const qtyColW   = Math.min(20, Math.max(14, Math.max(...qQtys.map(s => doc.getTextWidth(s))) + 6))

  autoTable(doc, {
    ...ts,
    startY: y,
    head: [['#', 'Product / Description', 'Qty', 'Unit Price', 'Disc%', 'Amount']],
    body: (q.items ?? []).map((item, i) => [
      i + 1,
      item.product_name,
      Number(item.quantity),
      formatCurrency(item.unit_price),
      parseFloat(item.discount_percent) > 0 ? `${item.discount_percent}%` : '—',
      formatCurrency(item.line_total),
    ]),
    columnStyles: {
      0: { cellWidth: 8,         halign: 'center' as const },
      1: { cellWidth: 'auto' as const },
      2: { cellWidth: qtyColW,   halign: 'center' as const },
      3: { cellWidth: priceColW, halign: 'right' as const },
      4: { cellWidth: 16,        halign: 'center' as const },
      5: { cellWidth: amtColW,   halign: 'right' as const, fontStyle: 'bold' as const, textColor: DARK },
    },
  })

  // ── Totals block — right-aligned 72mm box ──────────────────────────────────
  const tY = (doc as any).lastAutoTable.finalY + 6
  const tW = 72
  const tX = pageW - 14 - tW

  const subtotalNum = parseFloat(q.subtotal ?? q.total_amount ?? '0')
  const discountNum = parseFloat(q.discount_amount ?? '0')
  const taxNum      = parseFloat(q.tax_amount ?? '0')
  const totalNum    = parseFloat(q.total_amount ?? '0')

  const totalRows: Array<{ label: string; value: string; color?: [number,number,number] }> = []
  totalRows.push({ label: 'Subtotal', value: formatCurrency(subtotalNum) })
  if (discountNum > 0) totalRows.push({ label: 'Discount', value: `- ${formatCurrency(discountNum)}`, color: COLORS.AMBER })
  if (taxNum > 0) totalRows.push({ label: 'Tax / VAT', value: formatCurrency(taxNum) })

  const ROW_H = 5.5
  const PAD   = 4
  const boxContentH = totalRows.length * ROW_H + 2 + ROW_H + PAD * 2 + 3
  doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
  doc.roundedRect(tX, tY, tW, boxContentH, 2, 2, 'FD')

  let rowY = tY + PAD + ROW_H * 0.5
  totalRows.forEach(({ label, value, color }) => {
    doc.setFontSize(TYPE.SMALL.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
    doc.text(label, tX + PAD, rowY)
    doc.setFontSize(TYPE.BODY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...(color ?? DARK))
    doc.text(value, tX + tW - PAD, rowY, { align: 'right' })
    rowY += ROW_H
  })
  doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
  doc.line(tX + PAD, rowY + 1, tX + tW - PAD, rowY + 1)
  rowY += 3

  // Grand total row
  doc.setFontSize(TYPE.H3.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...DARK)
  doc.text('QUOTE TOTAL', tX + PAD, rowY)
  doc.setFontSize(TYPE.H2.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...BRAND)
  doc.text(formatCurrency(totalNum), tX + tW - PAD, rowY, { align: 'right' })

  const afterTotalsY = tY + boxContentH + 6

  // ── Notes box ─────────────────────────────────────────────────────────────
  if (q.notes) {
    doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
    const noteLines = doc.splitTextToSize(q.notes, pageW - 28 - 6)
    const noteBoxH = noteLines.length * 4.5 + 10
    doc.roundedRect(14, afterTotalsY, pageW - 28, noteBoxH, 2, 2, 'FD')
    doc.setFontSize(TYPE.H3.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...BRAND)
    doc.text('NOTES', 17, afterTotalsY + 5)
    doc.setFontSize(TYPE.BODY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
    doc.text(noteLines, 17, afterTotalsY + 10)
  }

  // ── Terms box ─────────────────────────────────────────────────────────────
  if (q.terms) {
    const termsTopY = afterTotalsY + (q.notes ? doc.splitTextToSize(q.notes, pageW - 28 - 6).length * 4.5 + 10 + 4 : 0)
    doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
    const termLines = doc.splitTextToSize(q.terms, pageW - 28 - 6)
    const termBoxH = termLines.length * 4.5 + 10
    doc.roundedRect(14, termsTopY, pageW - 28, termBoxH, 2, 2, 'FD')
    doc.setFontSize(TYPE.H3.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...BRAND)
    doc.text('TERMS & CONDITIONS', 17, termsTopY + 5)
    doc.setFontSize(TYPE.BODY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
    doc.text(termLines, 17, termsTopY + 10)
  }

  // ── Company stamp ──────────────────────────────────────────────────────────
  if (companyStamp) {
    try {
      const stampData = await urlToDataUrl(companyStamp)
      if (stampData) {
        const pageH = doc.internal.pageSize.getHeight()
        const SZ = 34
        doc.saveGraphicsState()
        doc.setGState(new (doc as any).GState({ opacity: 0.50 }))
        doc.addImage(stampData, 'PNG', pageW - 16 - SZ, pageH - 18 - SZ, SZ, SZ)
        doc.restoreGraphicsState()
      }
    } catch { /* skip stamp on error */ }
  }

  // ── Footer (every page) ────────────────────────────────────────────────────
  addDocFooter(doc, { orgName, docTitle: 'QUOTE', docRef: q.quote_number, BRAND, pdfFont })

  return { url: URL.createObjectURL(doc.output('blob')), filename: `Quote-${q.quote_number}.pdf`, quoteId: q.id }
}

type StatusFilter = 'all' | 'draft' | 'sent' | 'accepted' | 'rejected' | 'expired' | 'converted'

const STATUS_BADGE: Record<string, string> = {
  draft: 'badge-slate',
  sent: 'badge-blue',
  accepted: 'badge-green',
  rejected: 'badge-red',
  expired: 'badge-slate',
  converted: 'badge-orange',
}

interface QuoteLineForm {
  product: string
  product_name: string
  quantity: string
  unit_price: string
  discount_percent: string
}

const BLANK_LINE: QuoteLineForm = { product: '', product_name: '', quantity: '1', unit_price: '', discount_percent: '0' }

interface QuoteForm {
  customer: string
  warehouse: string
  status: string
  issue_date: string
  valid_until: string
  notes: string
  terms: string
}

const today = new Date().toISOString().split('T')[0]
const inTwoWeeks = new Date(Date.now() + 14 * 86400000).toISOString().split('T')[0]

const BLANK_FORM: QuoteForm = {
  customer: '', warehouse: '', status: 'draft', issue_date: today, valid_until: inTwoWeeks, notes: '', terms: '',
}

export default function QuotesPage() {
  const { organisation } = useAuthStore()
  const [quotes, setQuotes] = useState<Quote[]>([])
  const [customers, setCustomers] = useState<Customer[]>([])
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [archiveYear, setArchiveYear] = useState<number | null>(null)
  const [archiveMonth, setArchiveMonth] = useState<ArchiveMonth | null>(null)
  const activeDateParams = archiveMonth ? monthToDateParams(archiveMonth) : yearToDateParams(archiveYear)
  const handleYearChange = (y: number | null) => { setArchiveYear(y); if (y !== null) setArchiveMonth(null) }
  const handleMonthChange = (m: ArchiveMonth | null) => { setArchiveMonth(m); if (m !== null) setArchiveYear(null) }

  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState<QuoteForm>(BLANK_FORM)
  const [lines, setLines] = useState<QuoteLineForm[]>([{ ...BLANK_LINE }])
  const [saving, setSaving] = useState(false)
  const [expandedRow, setExpandedRow] = useState<string | null>(null)

  // Converted invoice — shown as inline banner + drawer
  const [convertedInvoice, setConvertedInvoice] = useState<Invoice | null>(null)
  const [viewingInvoice, setViewingInvoice] = useState(false)

  // PDF / share state
  const [pdfPreview, setPdfPreview] = useState<PdfPreview | null>(null)
  const [exporting, setExporting] = useState<string | null>(null) // quoteId being exported
  const [showEmailModal, setShowEmailModal] = useState(false)
  const [emailTo, setEmailTo] = useState('')
  const [sendingEmail, setSendingEmail] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = { ...activeDateParams }
      if (statusFilter !== 'all') params.status = statusFilter
      const [qRes, cRes, wRes, pRes] = await Promise.all([
        quoteApi.list(params),
        customerApi.list(),
        inventoryApi.warehouses(),
        inventoryApi.products(),
      ])
      setQuotes(qRes.data.results ?? qRes.data)
      setCustomers(cRes.data.results ?? cRes.data)
      setWarehouses(wRes.data.results ?? wRes.data)
      setProducts(pRes.data.results ?? pRes.data)
    } catch { toast.error('Failed to load quotes') }
    finally { setLoading(false) }
  }

  useEffect(() => {
    load()
    const interval = setInterval(load, 5 * 60 * 1000) // poll every 5 minutes for auto-expiry
    return () => clearInterval(interval)
  }, [statusFilter, archiveYear, archiveMonth])
  useDataRefresh(load)

  const handleCreate = async () => {
    if (!form.warehouse) { toast.error('Select a warehouse'); return }
    if (lines.some((l) => !l.product || !l.unit_price)) { toast.error('Fill in all line items'); return }
    setSaving(true)
    try {
      await quoteApi.create({
        ...form,
        customer: form.customer || null,
        items: lines.map((l) => ({
          product_id: l.product,
          quantity: parseFloat(l.quantity) || 1,
          unit_price: parseFloat(stripCommas(l.unit_price)) || 0,
          discount_percent: parseFloat(l.discount_percent) || 0,
        })),
      })
      toast.success('Quote created')
      setShowModal(false)
      setForm(BLANK_FORM)
      setLines([{ ...BLANK_LINE }])
      load()
    } catch { toast.error('Failed to create quote') }
    finally { setSaving(false) }
  }

  const handleConvert = async (q: Quote) => {
    if (q.status === 'rejected') { toast.error('This quote was rejected and cannot be converted'); return }
    if (q.status === 'expired') { toast.error('This quote has expired. Please create a new quote'); return }
    if (!confirm(`Convert quote ${q.quote_number} to invoice?`)) return
    try {
      const { data } = await quoteApi.convert(q.id)
      load()
      // Fetch the full invoice and show the inline banner
      if (data?.invoice_id) {
        try {
          const invRes = await salesApi.invoice(data.invoice_id)
          setConvertedInvoice(invRes.data)
          setViewingInvoice(false)
        } catch { /* non-fatal — banner just won't show */ }
      }
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to convert quote')
      toast.error(msg)
    }
  }

  const handleSend = async (q: Quote) => {
    try {
      await quoteApi.send(q.id)
      toast.success('Quote marked as sent')
      load()
    } catch { toast.error('Failed to update quote') }
  }

  const handleReject = async (q: Quote) => {
    if (!confirm(`Mark quote ${q.quote_number} as rejected?`)) return
    try {
      await quoteApi.reject(q.id)
      toast.success('Quote marked as rejected')
      load()
    } catch { toast.error('Failed to reject quote') }
  }

  const updateLine = (i: number, field: keyof QuoteLineForm, value: string) => {
    setLines(lines.map((l, idx) => {
      if (idx !== i) return l
      const updated = { ...l, [field]: value }
      if (field === 'product') {
        const p = products.find((pr) => pr.id === value)
        if (p) { updated.product_name = p.name; updated.unit_price = formatAmountInput(p.selling_price) }
      }
      if (field === 'unit_price') updated.unit_price = formatAmountInput(value)
      return updated
    }))
  }

  const handleExportPDF = async (q: Quote) => {
    setExporting(q.id)
    try {
      const preview = await buildQuotePDF(
        q,
        organisation?.name ?? 'Audity',
        organisation?.logo,
        organisation?.address,
        organisation?.phone,
        organisation?.email,
        organisation?.brand_color,
        organisation?.invoice_company_name,
        organisation?.company_name_font,
        organisation?.company_name_font_size,
        organisation?.company_name_font_bold,
        organisation?.company_name_font_italic,
        organisation?.company_name_font_underline,
        organisation?.company_name_font_color,
        organisation?.invoice_template,
        organisation?.company_stamp,
      )
      setPdfPreview(preview)
    } catch { toast.error('Failed to generate PDF') }
    finally { setExporting(null) }
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
    if (!pdfPreview) return
    const q = quotes.find((x) => x.id === pdfPreview.quoteId)
    if (!q) return
    const itemLines = (q.items ?? []).map((item) =>
      `  • ${item.product_name} ×${Number(item.quantity)} = ${formatCurrency(item.line_total)}`
    ).join('\n')
    const msg =
      `*Quote ${q.quote_number}*\n` +
      `From: ${organisation?.name ?? 'Audity'}\n` +
      `Customer: ${q.customer_name ?? 'Walk-in'}\n` +
      `Date: ${formatDate(q.issue_date)} · Valid Until: ${formatDate(q.valid_until)}\n\n` +
      (itemLines ? `${itemLines}\n\n` : '') +
      `*Total: ${formatCurrency(q.total_amount)}*\n\n` +
      `Thank you for your interest!`
    const url = `https://wa.me/?text=${encodeURIComponent(msg)}`
    navigator.clipboard.writeText(url).then(() => {
      toast.success('WhatsApp link copied! Open WhatsApp and paste to share.')
    }).catch(() => { toast('WhatsApp link: ' + url, { duration: 8000 }) })
  }

  const handleSendEmail = async () => {
    if (!pdfPreview || !emailTo.trim()) return
    setSendingEmail(true)
    try {
      // Build PDF and convert to base64 for attachment
      const res = await fetch(pdfPreview.url)
      const blob = await res.blob()
      const base64 = await new Promise<string>((resolve, reject) => {
        const r = new FileReader()
        r.onloadend = () => resolve((r.result as string).split(',')[1])
        r.onerror = reject
        r.readAsDataURL(blob)
      })
      await quoteApi.sendEmail(pdfPreview.quoteId, { to_email: emailTo.trim(), pdf_base64: base64 })
      toast.success(`Quote sent to ${emailTo.trim()}`)
      setShowEmailModal(false)
      setEmailTo('')
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Failed to send email'
      toast.error(typeof msg === 'string' ? msg : 'Failed to send email')
    } finally { setSendingEmail(false) }
  }

  const total = quotes.filter((q) => statusFilter === 'all' ? true : q.status === statusFilter).length
  const accepted = quotes.filter((q) => q.status === 'accepted').length
  const expired = quotes.filter((q) => q.status === 'expired').length
  const converted = quotes.filter((q) => q.status === 'converted').length
  const convRate = total > 0 ? Math.round((converted / total) * 100) : 0

  const filtered = statusFilter === 'all' ? quotes : quotes.filter((q) => q.status === statusFilter)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Quotes / Estimates</h1>
          <p className="text-slate-400 text-sm">{quotes.length} total quotes</p>
        </div>
        <div className="flex items-center gap-2 sm:ml-auto">
          <button onClick={() => { bypassNextGets(); load() }} disabled={loading} className="btn-ghost p-2 text-slate-400 hover:text-white" title="Refresh">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <button className="btn-primary" onClick={() => setShowModal(true)}>
            <Plus size={16} /> New Quote
          </button>
        </div>
      </div>

      {/* Converted invoice banner */}
      {convertedInvoice && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-green-500/10 border border-green-500/25">
          <CheckCircle size={16} className="text-green-400 shrink-0" />
          <p className="text-sm text-green-300 flex-1">
            Quote converted — Invoice{' '}
            <span className="font-mono font-semibold text-white">{convertedInvoice.invoice_number}</span>{' '}
            created successfully.
          </p>
          <button
            onClick={() => setViewingInvoice(true)}
            className="flex items-center gap-1.5 text-xs font-medium text-green-300 hover:text-white bg-green-500/15 hover:bg-green-500/25 px-3 py-1.5 rounded-lg transition-colors shrink-0"
          >
            <ExternalLink size={12} /> View Invoice
          </button>
          <button
            onClick={() => setConvertedInvoice(null)}
            className="text-slate-500 hover:text-slate-300 transition-colors shrink-0"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Total Quotes', value: quotes.length, color: 'text-white', bg: 'bg-brand-500/15' },
          { label: 'Accepted', value: accepted, color: 'text-emerald-400', bg: 'bg-emerald-500/15' },
          { label: 'Expired', value: expired, color: 'text-red-400', bg: 'bg-red-500/15' },
          { label: 'Conversion Rate', value: `${convRate}%`, color: 'text-blue-400', bg: 'bg-blue-500/15' },
        ].map((c) => (
          <div key={c.label} className="card p-5 flex items-center gap-4">
            <div className={`w-10 h-10 rounded-xl ${c.bg} flex items-center justify-center`}>
              <ClipboardList size={18} className={c.color} />
            </div>
            <div>
              <p className="text-xs text-slate-400">{c.label}</p>
              <p className={`text-xl font-bold ${c.color}`}>{c.value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Status filter tabs */}
      <div className="flex gap-1 p-1 bg-surface-800 rounded-xl w-fit flex-wrap">
        {(['all', 'draft', 'sent', 'accepted', 'rejected', 'expired', 'converted'] as StatusFilter[]).map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={statusFilter === s
              ? 'px-3 py-1.5 rounded-lg text-sm font-semibold bg-brand-500 text-white'
              : 'px-3 py-1.5 rounded-lg text-sm text-slate-400 hover:text-white transition-colors capitalize'}
          >
            {s === 'all' ? 'All' : s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <YearFilter selectedYear={archiveYear} onChange={handleYearChange} />
        <MonthFilter selectedMonth={archiveMonth} onChange={handleMonthChange} />
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['', 'Quote #', 'Customer', 'Issue Date', 'Valid Until', 'Amount', 'Status', 'Actions'].map((h) => (
                  <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 8 }).map((_, j) => (
                      <td key={j} className="px-4 py-3.5">
                        <div className="h-4 bg-surface-700 rounded animate-pulse w-16" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center">
                    <ClipboardList size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No quotes found</p>
                  </td>
                </tr>
              ) : filtered.map((q) => {
                const isExpiringSoon = (q.status === 'draft' || q.status === 'sent') && q.valid_until < today
                return (
                <>
                  <tr key={q.id} className={`table-row ${isExpiringSoon ? 'border-l-2 border-amber-500/60' : ''}`}>
                    <td className="px-4 py-3.5">
                      <button onClick={() => setExpandedRow(expandedRow === q.id ? null : q.id)} className="text-slate-400 hover:text-white">
                        {expandedRow === q.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>
                    </td>
                    <td className="px-4 py-3.5 font-mono text-brand-400">{q.quote_number}</td>
                    <td className="px-4 py-3.5 text-slate-300">{q.customer_name ?? <span className="text-slate-500 italic">Walk-in</span>}</td>
                    <td className="px-4 py-3.5 text-slate-400">{formatDate(q.issue_date)}</td>
                    <td className="px-4 py-3.5 text-slate-400">{formatDate(q.valid_until)}</td>
                    <td className="px-4 py-3.5 font-semibold text-white">{formatCurrency(q.total_amount)}</td>
                    <td className="px-4 py-3.5">
                      <span className={STATUS_BADGE[q.status] ?? 'badge-slate'}>{q.status}</span>
                    </td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-1.5">
                        {q.status === 'draft' && (
                          <button onClick={() => handleSend(q)} className="text-xs px-2.5 py-1 rounded-lg bg-blue-500/15 text-blue-400 hover:bg-blue-500/25 transition-colors">
                            Send
                          </button>
                        )}
                        {(q.status === 'accepted' || q.status === 'sent') && (
                          <>
                            <button onClick={() => handleConvert(q)} className="text-xs px-2.5 py-1 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 transition-colors">
                              Convert
                            </button>
                            <button onClick={() => handleReject(q)} className="text-xs px-2.5 py-1 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors">
                              Reject
                            </button>
                          </>
                        )}
                        <button
                          onClick={() => handleExportPDF(q)}
                          disabled={exporting === q.id}
                          title="Export PDF"
                          className="p-1.5 text-slate-500 hover:text-brand-400 hover:bg-brand-500/10 rounded-lg transition-colors disabled:opacity-50"
                        >
                          {exporting === q.id ? <Loader2 size={14} className="animate-spin" /> : <FileDown size={14} />}
                        </button>
                      </div>
                    </td>
                  </tr>
                  {expandedRow === q.id && (
                    <tr key={`${q.id}-detail`} className="bg-surface-900/50">
                      <td colSpan={8} className="px-6 py-4">
                        <div className="space-y-2">
                          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Line Items</p>
                          {q.items.map((item, idx) => (
                            <div key={idx} className="flex items-center gap-4 text-sm">
                              <span className="text-slate-300 flex-1">{item.product_name}</span>
                              <span className="text-slate-400">Qty: {item.quantity}</span>
                              <span className="text-slate-400">@ {formatCurrency(item.unit_price)}</span>
                              {parseFloat(item.discount_percent) > 0 && (
                                <span className="badge-yellow">{item.discount_percent}% off</span>
                              )}
                              <span className="text-white font-semibold">{formatCurrency(item.line_total)}</span>
                            </div>
                          ))}
                          <div className="border-t border-surface-700 pt-2 flex justify-end gap-8 text-sm">
                            <span className="text-slate-400">Subtotal: <span className="text-white">{formatCurrency(q.subtotal)}</span></span>
                            <span className="text-slate-400">Tax: <span className="text-white">{formatCurrency(q.tax_amount)}</span></span>
                            <span className="text-slate-400">Total: <span className="text-brand-400 font-bold">{formatCurrency(q.total_amount)}</span></span>
                          </div>
                          {q.notes && <p className="text-xs text-slate-500">Notes: {q.notes}</p>}
                          {isExpiringSoon && (
                            <p className="text-xs text-amber-400 font-medium mt-1">⚠ Valid until date has passed — this quote may have auto-expired</p>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* PDF Preview Modal */}
      {pdfPreview && (
        <div className="fixed inset-0 z-[60] flex flex-col">
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
              <button onClick={() => { setEmailTo(''); setShowEmailModal(true) }} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 transition-colors">
                <Mail size={13} /> Email
              </button>
              <button onClick={shareViaWhatsApp} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-600 text-white text-xs font-semibold hover:bg-green-700 transition-colors">
                <MessageCircle size={13} /> WhatsApp
              </button>
              <button onClick={closePdfPreview} className="p-1.5 text-slate-400 hover:text-white hover:bg-surface-700 rounded-lg transition-colors">
                <X size={16} />
              </button>
            </div>
          </div>
          <iframe src={pdfPreview.url} className="flex-1 w-full border-0 bg-white" title="Quote Preview" />
        </div>
      )}

      {/* Email Modal */}
      {showEmailModal && pdfPreview && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowEmailModal(false)} />
          <div className="relative card w-full max-w-md p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Send Quote by Email</h2>
              <button onClick={() => setShowEmailModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Recipient Email *</label>
              <input
                className="input"
                type="email"
                placeholder="customer@example.com"
                value={emailTo}
                onChange={(e) => setEmailTo(e.target.value)}
                autoFocus
              />
            </div>
            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowEmailModal(false)}>Cancel</button>
              <button
                className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50"
                onClick={handleSendEmail}
                disabled={sendingEmail || !emailTo.trim()}
              >
                {sendingEmail ? <Loader2 size={16} className="animate-spin" /> : <><Mail size={15} /> Send</>}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* New Quote Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative card w-full max-w-2xl p-6 space-y-5 overflow-y-auto max-h-[90vh]">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">New Quote</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Customer (optional)<FieldTooltip text="Who this quote is for. Optional — you can prepare a general quote without naming a customer yet." /></label>
                <select className="input" value={form.customer} onChange={(e) => setForm({ ...form, customer: e.target.value })}>
                  <option value="">Walk-in / No customer</option>
                  {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Location *<FieldTooltip text="Which warehouse the quoted stock will come from." /></label>
                <select className="input" value={form.warehouse} onChange={(e) => setForm({ ...form, warehouse: e.target.value })}>
                  <option value="">— Select —</option>
                  {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Status<FieldTooltip text="Draft = still being prepared. Sent = shared with the customer. Accepted = customer agreed. Rejected = turned down." /></label>
                <select className="input" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  <option value="draft">Draft</option>
                  <option value="sent">Sent</option>
                  <option value="accepted">Accepted</option>
                  <option value="rejected">Rejected</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Issue Date<FieldTooltip text="The date you're creating this quote." /></label>
                <DateInput value={form.issue_date} onChange={(v) => setForm({ ...form, issue_date: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Valid Until<FieldTooltip text="The expiry date of this quote — after this, the prices are no longer guaranteed. Typically 7–30 days ahead." /></label>
                <DateInput value={form.valid_until} onChange={(v) => setForm({ ...form, valid_until: v })} />
              </div>
            </div>

            {/* Line items */}
            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Line Items</p>
              <div className="space-y-2">
                {lines.map((line, i) => (
                  <div key={i} className="grid grid-cols-12 gap-2 items-center">
                    <div className="col-span-4">
                      <select className="input py-1.5 text-sm" value={line.product} onChange={(e) => updateLine(i, 'product', e.target.value)}>
                        <option value="">— Product —</option>
                        {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                    </div>
                    <div className="col-span-2">
                      <input type="number" min="1" className="input py-1.5 text-sm" placeholder="Qty" value={line.quantity} onChange={(e) => updateLine(i, 'quantity', e.target.value)} />
                    </div>
                    <div className="col-span-3">
                      <input type="text" inputMode="decimal" className="input py-1.5 text-sm" placeholder="Unit Price" value={line.unit_price} onChange={(e) => updateLine(i, 'unit_price', e.target.value)} />
                    </div>
                    <div className="col-span-2">
                      <input type="number" min="0" max="100" className="input py-1.5 text-sm" placeholder="Disc%" value={line.discount_percent} onChange={(e) => updateLine(i, 'discount_percent', e.target.value)} />
                    </div>
                    <div className="col-span-1 flex justify-center">
                      <button onClick={() => setLines(lines.filter((_, idx) => idx !== i))} className="p-1 text-slate-500 hover:text-red-400 transition-colors">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              <button onClick={() => setLines([...lines, { ...BLANK_LINE }])} className="btn-ghost text-sm mt-2 flex items-center gap-1">
                <Plus size={13} /> Add Line
              </button>
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">Notes<FieldTooltip text="Terms, conditions, or extra info for the customer — e.g. 'Price valid for 14 days' or 'Delivery not included'." /></label>
              <textarea className="input resize-none" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Any notes for the customer…" />
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Terms & Conditions</label>
              <textarea className="input resize-none" rows={2} value={form.terms} onChange={(e) => setForm({ ...form, terms: e.target.value })} placeholder="Payment terms, delivery conditions…" />
            </div>

            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleCreate} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : <><FileText size={15} /> Create Quote</>}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Invoice viewer drawer */}
      {viewingInvoice && convertedInvoice && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setViewingInvoice(false)} />
          <div className="relative bg-surface-900 border-l border-surface-700 w-full max-w-lg flex flex-col shadow-2xl overflow-y-auto">
            {/* Drawer header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-surface-700 sticky top-0 bg-surface-900 z-10">
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wider">Invoice</p>
                <h2 className="text-lg font-bold text-white font-mono">{convertedInvoice.invoice_number}</h2>
              </div>
              <button onClick={() => setViewingInvoice(false)} className="btn-ghost p-2">
                <X size={18} />
              </button>
            </div>

            <div className="p-6 space-y-5">
              {/* Status + dates */}
              <div className="flex flex-wrap gap-2 items-center">
                <span className={`badge ${
                  convertedInvoice.status === 'paid' ? 'badge-green'
                  : convertedInvoice.status === 'overdue' ? 'badge-red'
                  : convertedInvoice.status === 'confirmed' ? 'badge-blue'
                  : 'badge-slate'
                }`}>
                  {convertedInvoice.status}
                </span>
                <span className="text-xs text-slate-500">{formatDate(convertedInvoice.issue_date)}</span>
                {convertedInvoice.due_date && (
                  <span className="text-xs text-slate-500">Due {formatDate(convertedInvoice.due_date)}</span>
                )}
              </div>

              {/* Customer */}
              {convertedInvoice.customer_name && (
                <div className="card-sm">
                  <p className="text-xs text-slate-500 mb-0.5">Billed To</p>
                  <p className="text-white font-medium">{convertedInvoice.customer_name}</p>
                </div>
              )}

              {/* Line items */}
              <div>
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Items</p>
                <div className="card-sm p-0 overflow-hidden">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-surface-700">
                        <th className="text-left px-4 py-2.5 text-xs text-slate-500 font-medium">Item</th>
                        <th className="text-center px-3 py-2.5 text-xs text-slate-500 font-medium">Qty</th>
                        <th className="text-right px-4 py-2.5 text-xs text-slate-500 font-medium">Amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {convertedInvoice.items?.map((item, i) => (
                        <tr key={i} className="border-b border-surface-700 last:border-0">
                          <td className="px-4 py-2.5 text-slate-200">{item.product_name}</td>
                          <td className="px-3 py-2.5 text-center text-slate-400">{item.quantity}</td>
                          <td className="px-4 py-2.5 text-right text-white font-mono">
                            {formatCurrency(String(parseFloat(item.unit_price) * parseFloat(item.quantity)))}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Totals */}
              <div className="card-sm space-y-2">
                <div className="flex justify-between text-sm">
                  <span className="text-slate-400">Subtotal</span>
                  <span className="text-white">{formatCurrency(convertedInvoice.subtotal)}</span>
                </div>
                {parseFloat(convertedInvoice.discount_amount) > 0 && (
                  <div className="flex justify-between text-sm">
                    <span className="text-slate-400">Discount</span>
                    <span className="text-red-400">− {formatCurrency(convertedInvoice.discount_amount)}</span>
                  </div>
                )}
                {parseFloat(convertedInvoice.tax_amount) > 0 && (
                  <div className="flex justify-between text-sm">
                    <span className="text-slate-400">Tax</span>
                    <span className="text-white">{formatCurrency(convertedInvoice.tax_amount)}</span>
                  </div>
                )}
                <div className="flex justify-between text-base font-bold border-t border-surface-700 pt-2 mt-1">
                  <span className="text-white">Total</span>
                  <span className="text-brand-400">{formatCurrency(convertedInvoice.total_amount)}</span>
                </div>
                {parseFloat(convertedInvoice.amount_due) > 0 && (
                  <div className="flex justify-between text-sm">
                    <span className="text-slate-400">Amount Due</span>
                    <span className="text-amber-400 font-semibold">{formatCurrency(convertedInvoice.amount_due)}</span>
                  </div>
                )}
              </div>

              {convertedInvoice.notes && (
                <div>
                  <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Notes</p>
                  <p className="text-sm text-slate-300">{convertedInvoice.notes}</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
