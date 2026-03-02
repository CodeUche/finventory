import { useEffect, useState } from 'react'
import { Plus, Receipt, Search, X, Loader2, CheckCircle, Ban, FileDown, Mail, MessageCircle, Download } from 'lucide-react'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import { salesApi } from '@/services/api'
import { formatCurrency, formatDate, getStatusColor, formatAmountInput, stripCommas } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import type { Invoice } from '@/types'

const STATUS_OPTIONS = ['', 'paid', 'confirmed', 'partially_paid', 'credit', 'overdue', 'voided']

interface PdfPreview { url: string; filename: string }

// ── PDF builder ───────────────────────────────────────────────────────────────
async function buildInvoicePDF(
  inv: Invoice,
  orgName: string,
  orgLogo?: string,
  orgAddress?: string,
  orgPhone?: string,
  orgEmail?: string,
): Promise<PdfPreview> {
  const { jsPDF } = await import('jspdf')
  const { default: autoTable } = await import('jspdf-autotable')

  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()
  const pageH = doc.internal.pageSize.getHeight()

  const BRAND: [number, number, number] = [249, 115, 22]
  const DARK: [number, number, number]  = [30,  30,  30]
  const MUTED: [number, number, number] = [100, 100, 100]
  const LIGHT: [number, number, number] = [250, 250, 248]

  let y = 14

  // ── Top brand bar ──────────────────────────────────────────────────────────
  doc.setFillColor(...BRAND)
  doc.rect(0, 0, pageW, 3, 'F')

  // ── Logo ───────────────────────────────────────────────────────────────────
  if (orgLogo) {
    try {
      const res = await fetch(orgLogo)
      const blob = await res.blob()
      const b64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onloadend = () => resolve(reader.result as string)
        reader.onerror = reject
        reader.readAsDataURL(blob)
      })
      doc.addImage(b64, blob.type.includes('png') ? 'PNG' : 'JPEG', 14, y + 2, 26, 26)
    } catch { /* skip logo on error */ }
  }

  // ── Company info (left) ────────────────────────────────────────────────────
  const textX = orgLogo ? 46 : 14
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
  const amtDue = parseFloat(inv.amount_due ?? '0')

  doc.setFillColor(...LIGHT)
  doc.roundedRect(tX, tY, tW, 38, 2, 2, 'F')

  const tRow = (label: string, value: string, bold: boolean, color: [number,number,number], yOff: number) => {
    doc.setFontSize(9)
    doc.setFont('helvetica', bold ? 'bold' : 'normal')
    doc.setTextColor(...MUTED)
    doc.text(label, tX + 5, tY + 9 + yOff)
    doc.setTextColor(...color)
    doc.text(value, pageW - 19, tY + 9 + yOff, { align: 'right' })
  }

  tRow('Subtotal:',     formatCurrency(inv.total_amount),  false, DARK,            0)
  tRow('Amount Paid:',  formatCurrency(inv.amount_paid),   false, [22, 163, 74],   9)

  doc.setDrawColor(210, 210, 210)
  doc.setLineWidth(0.3)
  doc.line(tX + 5, tY + 22, pageW - 19, tY + 22)

  tRow('BALANCE DUE:',  formatCurrency(inv.amount_due),    true,
    amtDue > 0 ? [220, 38, 38] : [22, 163, 74], 20)

  // ── Payment note (left of totals) ─────────────────────────────────────────
  doc.setFontSize(7.5)
  doc.setFont('helvetica', 'italic')
  doc.setTextColor(...MUTED)
  doc.text(`Payment method: ${inv.payment_method.replace(/_/g, ' ')}`, 14, tY + 9)

  // ── Thank you ─────────────────────────────────────────────────────────────
  const thankY = tY + 46
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
  doc.text(`Generated by Finventory  ·  ${new Date().toLocaleDateString()}`, pageW / 2, pageH - 4.5, { align: 'center' })
  if (orgEmail) doc.text(orgEmail, pageW - 14, pageH - 4.5, { align: 'right' })

  // ── Return blob URL ────────────────────────────────────────────────────────
  const blob = doc.output('blob')
  const url  = URL.createObjectURL(blob)
  const filename = `Invoice-${inv.invoice_number}.pdf`
  return { url, filename }
}

// ─────────────────────────────────────────────────────────────────────────────

export default function SalesPage() {
  const { organisation } = useAuthStore()
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [selected, setSelected] = useState<Invoice | null>(null)
  const [detail, setDetail] = useState<Invoice | null>(null)
  const [acting, setActing] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [payAmount, setPayAmount] = useState('')
  const [pdfPreview, setPdfPreview] = useState<PdfPreview | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await salesApi.invoices({ search, status: status || undefined })
      setInvoices(data.results ?? data)
    } catch { toast.error('Failed to load invoices') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [search, status])

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
      await salesApi.pay(selected.id, { amount_paid: stripCommas(payAmount) })
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
        organisation?.name ?? 'Finventory',
        (organisation as any)?.logo,
        (organisation as any)?.address,
        (organisation as any)?.phone,
        (organisation as any)?.email,
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
    const subject = encodeURIComponent(`Invoice ${inv.invoice_number} – ${organisation?.name ?? 'Finventory'}`)
    const body = encodeURIComponent(
      `Dear ${inv.customer_name ?? 'Customer'},\n\nPlease find below the details for Invoice ${inv.invoice_number}.\n\n` +
      `Invoice No.: ${inv.invoice_number}\nDate: ${formatDate(inv.issue_date)}\nTotal: ${formatCurrency(inv.total_amount)}\n` +
      `Amount Paid: ${formatCurrency(inv.amount_paid)}\nBalance Due: ${formatCurrency(inv.amount_due)}\n\n` +
      `Thank you for your business!\n\n${organisation?.name ?? 'Finventory'}`
    )
    window.open(`mailto:?subject=${subject}&body=${body}`, '_blank')
  }

  const shareViaWhatsApp = () => {
    if (!inv) return
    const msg = encodeURIComponent(
      `*Invoice ${inv.invoice_number}*\n` +
      `From: ${organisation?.name ?? 'Finventory'}\n` +
      `Customer: ${inv.customer_name ?? 'Walk-in'}\n` +
      `Date: ${formatDate(inv.issue_date)}\n` +
      `Total: ${formatCurrency(inv.total_amount)}\n` +
      `Paid: ${formatCurrency(inv.amount_paid)}\n` +
      `*Balance Due: ${formatCurrency(inv.amount_due)}*\n\n` +
      `Thank you for your business!`
    )
    window.open(`https://wa.me/?text=${msg}`, '_blank')
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
                  <div className="flex gap-2">
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
              <div className="border-t border-surface-700 px-6 py-4">
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
