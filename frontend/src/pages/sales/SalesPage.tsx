import { useEffect, useState } from 'react'
import { Plus, Receipt, Search, X, Loader2, CheckCircle, Ban, FileDown } from 'lucide-react'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import { salesApi } from '@/services/api'
import { formatCurrency, formatDate, getStatusColor } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import type { Invoice } from '@/types'

const STATUS_OPTIONS = ['', 'paid', 'confirmed', 'partially_paid', 'credit', 'overdue', 'voided']

async function exportInvoicePDF(inv: Invoice, orgName: string, orgLogo?: string, orgAddress?: string, orgPhone?: string, orgEmail?: string) {
  const { jsPDF } = await import('jspdf')
  const { default: autoTable } = await import('jspdf-autotable')

  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()

  // ── Brand colour (orange-500) ──────────────────────────────────────────────
  const BRAND: [number, number, number] = [249, 115, 22]
  const DARK:  [number, number, number] = [30,  30,  30]
  const MUTED: [number, number, number] = [100, 100, 100]

  let y = 14

  // ── Header bar ─────────────────────────────────────────────────────────────
  doc.setFillColor(...BRAND)
  doc.rect(0, 0, pageW, 2, 'F')

  // ── Logo (if available) ────────────────────────────────────────────────────
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
      const ext = blob.type.includes('png') ? 'PNG' : 'JPEG'
      doc.addImage(b64, ext, 14, y + 2, 28, 28)
      y += 2
    } catch { /* no logo — continue */ }
  }

  // ── Company info (left) ────────────────────────────────────────────────────
  const textX = orgLogo ? 48 : 14
  doc.setFontSize(16)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(...DARK)
  doc.text(orgName, textX, y + 8)

  doc.setFontSize(8)
  doc.setFont('helvetica', 'normal')
  doc.setTextColor(...MUTED)
  let infoY = y + 14
  if (orgAddress) { doc.text(orgAddress, textX, infoY); infoY += 5 }
  if (orgPhone)   { doc.text(`Tel: ${orgPhone}`, textX, infoY); infoY += 5 }
  if (orgEmail)   { doc.text(`Email: ${orgEmail}`, textX, infoY) }

  // ── INVOICE label (right) ──────────────────────────────────────────────────
  doc.setFontSize(26)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(...BRAND)
  doc.text('INVOICE', pageW - 14, y + 8, { align: 'right' })

  doc.setFontSize(9)
  doc.setFont('helvetica', 'normal')
  doc.setTextColor(...MUTED)
  doc.text(`Invoice #:  ${inv.invoice_number}`,                    pageW - 14, y + 16, { align: 'right' })
  doc.text(`Date:       ${formatDate(inv.issue_date)}`,            pageW - 14, y + 22, { align: 'right' })
  doc.text(`Status:     ${inv.status.replace(/_/g, ' ').toUpperCase()}`, pageW - 14, y + 28, { align: 'right' })

  y = Math.max(infoY, y + 34) + 8

  // ── Divider ────────────────────────────────────────────────────────────────
  doc.setDrawColor(...BRAND)
  doc.setLineWidth(0.4)
  doc.line(14, y, pageW - 14, y)
  y += 6

  // ── Billed To ─────────────────────────────────────────────────────────────
  doc.setFontSize(8)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(...BRAND)
  doc.text('BILLED TO', 14, y)
  y += 5

  doc.setFont('helvetica', 'normal')
  doc.setTextColor(...DARK)
  doc.setFontSize(10)
  doc.text(inv.customer_name ?? 'Walk-in Customer', 14, y)
  y += 10

  // ── Items table ────────────────────────────────────────────────────────────
  autoTable(doc, {
    startY: y,
    head: [['#', 'Product', 'SKU', 'Qty', 'Unit Price', 'Line Total']],
    body: (inv.items ?? []).map((item, i) => [
      i + 1,
      item.product_name,
      item.product_sku ?? '—',
      item.quantity,
      formatCurrency(item.unit_price),
      formatCurrency(item.line_total),
    ]),
    styles: {
      fontSize: 9,
      cellPadding: 4,
      textColor: DARK,
    },
    headStyles: {
      fillColor: BRAND,
      textColor: [255, 255, 255],
      fontStyle: 'bold',
      fontSize: 8,
    },
    alternateRowStyles: { fillColor: [252, 252, 252] },
    columnStyles: {
      0: { cellWidth: 10, halign: 'center' },
      1: { cellWidth: 'auto' },
      2: { cellWidth: 30 },
      3: { cellWidth: 16, halign: 'center' },
      4: { cellWidth: 32, halign: 'right' },
      5: { cellWidth: 32, halign: 'right' },
    },
    margin: { left: 14, right: 14 },
    tableLineColor: [220, 220, 220],
    tableLineWidth: 0.2,
  })

  // ── Totals block ───────────────────────────────────────────────────────────
  const afterTable = (doc as any).lastAutoTable.finalY + 8
  const colL = pageW - 90
  const colR = pageW - 14

  const row = (label: string, val: string, colour: [number,number,number], bold = false, yy = 0) => {
    doc.setFontSize(9)
    doc.setFont('helvetica', bold ? 'bold' : 'normal')
    doc.setTextColor(...MUTED)
    doc.text(label, colL, yy)
    doc.setTextColor(...colour)
    doc.text(val, colR, yy, { align: 'right' })
  }

  row('Subtotal',    formatCurrency(inv.total_amount),  DARK,             false, afterTable)
  row('Amount Paid', formatCurrency(inv.amount_paid),   [22, 163, 74],    false, afterTable + 7)

  doc.setDrawColor(200, 200, 200)
  doc.setLineWidth(0.3)
  doc.line(colL, afterTable + 11, colR, afterTable + 11)

  const amtDue = parseFloat(inv.amount_due ?? '0')
  row('Amount Due',  formatCurrency(inv.amount_due),
    amtDue > 0 ? [220, 38, 38] : [22, 163, 74],
    true, afterTable + 18)

  // ── Payment method note ────────────────────────────────────────────────────
  doc.setFontSize(8)
  doc.setFont('helvetica', 'normal')
  doc.setTextColor(...MUTED)
  doc.text(`Payment method: ${inv.payment_method.replace(/_/g, ' ')}`, 14, afterTable + 18)

  // ── Footer ─────────────────────────────────────────────────────────────────
  const pageH = doc.internal.pageSize.getHeight()
  doc.setFillColor(...BRAND)
  doc.rect(0, pageH - 2, pageW, 2, 'F')
  doc.setFontSize(7)
  doc.setTextColor(...MUTED)
  doc.text(`Generated by Finventory · ${new Date().toLocaleDateString()}`, pageW / 2, pageH - 5, { align: 'center' })

  doc.save(`Invoice-${inv.invoice_number}.pdf`)
}

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
    setPayAmount(inv.amount_due)
    try {
      const { data } = await salesApi.invoice(inv.id)
      setDetail(data)
    } catch {
      setDetail(inv)
    }
  }

  const handlePay = async () => {
    if (!selected) return
    setActing(true)
    try {
      await salesApi.pay(selected.id, { amount_paid: payAmount })
      toast.success('Payment recorded')
      setSelected(null); setDetail(null)
      load()
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
      setSelected(null); setDetail(null)
      load()
    } catch { toast.error('Failed to void invoice') }
    finally { setActing(false) }
  }

  const handleExportPDF = async () => {
    if (!inv) return
    setExporting(true)
    try {
      await exportInvoicePDF(
        inv,
        organisation?.name ?? 'Finventory',
        (organisation as any)?.logo,
        (organisation as any)?.address,
        (organisation as any)?.phone,
        (organisation as any)?.email,
      )
    } catch {
      toast.error('Failed to generate PDF')
    } finally {
      setExporting(false)
    }
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

      {/* Invoice Detail Drawer */}
      {selected && (
        <>
          <div className="fixed inset-0 z-40 bg-black/50" onClick={() => { setSelected(null); setDetail(null) }} />
          <div className="fixed right-0 top-0 bottom-0 z-50 w-full max-w-md bg-surface-900 border-l border-surface-700 shadow-2xl flex flex-col overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-5 border-b border-surface-700">
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wider">Invoice</p>
                <h2 className="font-bold text-white text-lg">{inv?.invoice_number}</h2>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleExportPDF}
                  disabled={exporting}
                  title="Export PDF"
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-brand-500/40 text-brand-400 hover:bg-brand-500/10 text-xs font-medium transition-colors disabled:opacity-50"
                >
                  {exporting
                    ? <Loader2 size={14} className="animate-spin" />
                    : <FileDown size={14} />}
                  Export PDF
                </button>
                <button onClick={() => { setSelected(null); setDetail(null) }} className="btn-ghost p-2">
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
              {/* Meta */}
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

              {/* Pay section */}
              {inv?.status !== 'paid' && inv?.status !== 'voided' && parseFloat(inv?.amount_due ?? '0') > 0 && (
                <div>
                  <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Record Payment</p>
                  <div className="flex gap-2">
                    <input
                      type="number"
                      step="0.01"
                      className="input flex-1"
                      value={payAmount}
                      onChange={(e) => setPayAmount(e.target.value)}
                      placeholder="Amount"
                    />
                    <button onClick={handlePay} disabled={acting} className="btn-primary px-4">
                      {acting ? <Loader2 size={16} className="animate-spin" /> : <><CheckCircle size={15} /> Pay</>}
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Footer actions */}
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
    </div>
  )
}
