import { useEffect, useRef, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Search, X, Loader2, RotateCcw, FileDown } from 'lucide-react'
import toast from 'react-hot-toast'
import { salesApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import DateInput from '@/components/DateInput'
import { useAuthStore } from '@/store/authStore'
import { saveBlobFile } from '@/lib/saveBlobFile'
import { usePagination } from '@/hooks/usePagination'
import Pagination from '@/components/Pagination'
import type { SaleReturn } from '@/types'

const REASON_LABEL: Record<string, string> = {
  defective: 'Defective / Damaged',
  wrong_item: 'Wrong Item Delivered',
  customer_change: 'Customer Changed Mind',
  overcharge: 'Overcharge / Price Error',
  other: 'Other',
}

function hexToRgb(hex?: string): [number, number, number] {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
  if (!m) return [249, 115, 22]
  return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
}

export default function SalesReturnsPage() {
  const { organisation } = useAuthStore()
  const [returns, setReturns] = useState<SaleReturn[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [selected, setSelected] = useState<SaleReturn | null>(null)
  const [exporting, setExporting] = useState(false)

  // Typing a date fires onChange per keystroke (DateInput commits partial
  // valid dates as they form), so "From date" then "To date" can each kick
  // off their own load(). Network responses aren't guaranteed to land in the
  // order they were sent — without this guard, an earlier, broader request
  // (e.g. from-date-only, before to-date was typed) can resolve AFTER the
  // later, narrower one and silently overwrite the correctly filtered result
  // with stale rows. requestSeq tags each call; only the most recent one is
  // allowed to commit state.
  const requestSeq = useRef(0)

  const load = async () => {
    const seq = ++requestSeq.current
    setLoading(true)
    try {
      const { data } = await salesApi.listReturns({
        search: search || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        page_size: 5000,
      })
      if (seq !== requestSeq.current) return // a newer request has since started
      setReturns(data.results ?? data)
    } catch {
      if (seq === requestSeq.current) toast.error('Failed to load sales returns')
    } finally {
      if (seq === requestSeq.current) setLoading(false)
    }
  }

  useEffect(() => { load() }, [search, dateFrom, dateTo])
  useDataRefresh(load)

  const { page, setPage, pageSize, setPageSize, totalPages, paged, total } = usePagination(returns)

  const downloadCreditNote = async (ret: SaleReturn) => {
    setExporting(true)
    try {
      const { jsPDF } = await import('jspdf')
      const { default: autoTable } = await import('jspdf-autotable')
      const { applyDocHeader, buildTableStyle, addDocFooter, pdfMoney, pdfQty, COLORS, TYPE, resolveOrgLogo } = await import('@/lib/pdfUtils')

      const doc = new jsPDF({ unit: 'mm', format: 'a4' })
      doc.setLineHeightFactor(1.15)
      const pageW = doc.internal.pageSize.getWidth()

      const BRAND = hexToRgb(organisation?.brand_color)
      const DARK = COLORS.DARK
      const MUTED = COLORS.MUTED
      const LIGHT = COLORS.LIGHT
      const RULE = COLORS.RULE
      const tmpl = organisation?.invoice_template ?? 'classic'
      const logoData = await resolveOrgLogo(organisation?.logo)
      const displayName = organisation?.show_company_name_on_pdf === false
        ? '' : (organisation?.invoice_company_name?.trim() || organisation?.name || 'Audity')

      let y = applyDocHeader(doc, {
        tmpl, pageW, BRAND, DARK, MUTED,
        logoData,
        displayName,
        orgAddress: organisation?.address,
        orgPhone: organisation?.phone,
        orgEmail: organisation?.email,
        pdfFont: 'helvetica',
        fontSize: 12,
        pdfStyle: 'bold',
        nameColor: (tmpl === 'modern' || tmpl === 'minimal') ? DARK : COLORS.WHITE,
        showCompanyName: organisation?.show_company_name_on_pdf !== false,
        docTitle: 'CREDIT NOTE',
        metaRows: [
          ['No.', ret.return_number],
          ['Date', formatDate(ret.return_date)],
          ['Against Invoice', ret.invoice_number],
          ['Reason', REASON_LABEL[ret.reason] ?? ret.reason],
        ],
      })

      const boxW = pageW - 28
      doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
      doc.roundedRect(14, y, boxW, 24, 2, 2, 'FD')
      doc.setFontSize(TYPE.H3.size); doc.setFont('helvetica', 'bold'); doc.setTextColor(...BRAND)
      doc.text('CUSTOMER', 17, y + 5)
      doc.setFontSize(TYPE.H2.size); doc.setFont('helvetica', 'bold'); doc.setTextColor(...DARK)
      doc.text(ret.customer_name ?? 'Walk-in Customer', 17, y + 11)
      doc.setFontSize(TYPE.BODY.size); doc.setFont('helvetica', 'normal'); doc.setTextColor(...MUTED)
      doc.text(ret.restocked ? 'Items restocked to inventory' : 'Items not restocked', 17, y + 17)
      y += 24 + 6

      const ts = buildTableStyle(BRAND, 'helvetica')
      autoTable(doc, {
        ...ts,
        startY: y,
        head: [['Product', 'Qty', 'Unit Price', 'Refund Amount']],
        body: ret.items.map((it) => [
          it.product_name,
          pdfQty(it.quantity_returned),
          pdfMoney(it.unit_price),
          pdfMoney(it.refund_amount),
        ]),
        columnStyles: {
          1: { halign: 'right' as const, cellWidth: 22 },
          2: { halign: 'right' as const, cellWidth: 32 },
          3: { halign: 'right' as const, cellWidth: 34 },
        },
      })

      const finalY = (doc as any).lastAutoTable?.finalY ?? y + 20
      let ty = finalY + 8
      doc.setFontSize(TYPE.H2.size); doc.setFont('helvetica', 'bold'); doc.setTextColor(...DARK)
      doc.text('Total Refund', pageW - 70, ty)
      doc.setTextColor(...BRAND)
      doc.text(pdfMoney(ret.total_refund), pageW - 16, ty, { align: 'right' })

      if (ret.notes) {
        ty += 10
        doc.setFontSize(TYPE.SMALL.size); doc.setFont('helvetica', 'normal'); doc.setTextColor(...MUTED)
        doc.text(`Notes: ${ret.notes}`, 14, ty, { maxWidth: pageW - 28 })
      }

      addDocFooter(doc, {
        orgName: organisation?.name ?? 'Company',
        docTitle: 'CREDIT NOTE',
        docRef: ret.return_number,
        BRAND,
        pdfFont: 'helvetica',
      })

      await saveBlobFile(doc.output('blob'), `credit-note-${ret.return_number}.pdf`)
    } catch {
      toast.error('Failed to generate credit note PDF')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <RotateCcw size={22} className="text-brand-400" /> Sales Returns
          </h1>
          <p className="text-slate-400 text-sm">Credit notes issued against sales invoices</p>
        </div>
      </div>

      <div className="card p-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            className="input pl-9"
            placeholder="Search return # or invoice #…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <DateInput value={dateFrom} onChange={setDateFrom} placeholder="From date" />
        <DateInput value={dateTo} onChange={setDateTo} placeholder="To date" min={dateFrom || undefined} />
        {(search || dateFrom || dateTo) && (
          <button
            onClick={() => { setSearch(''); setDateFrom(''); setDateTo('') }}
            className="btn-ghost text-sm flex items-center gap-1"
          >
            <X size={14} /> Clear
          </button>
        )}
      </div>

      <div className="card overflow-x-auto">
        {loading ? (
          <div className="p-10 flex justify-center"><Loader2 className="animate-spin text-slate-500" size={24} /></div>
        ) : paged.length === 0 ? (
          <div className="p-10 text-center text-slate-500 text-sm">No sales returns found</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-400 uppercase border-b border-surface-700">
                <th className="px-4 py-3">Return #</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Invoice</th>
                <th className="px-4 py-3">Customer</th>
                <th className="px-4 py-3">Reason</th>
                <th className="px-4 py-3 text-right">Refund</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {paged.map((ret) => (
                <tr
                  key={ret.id}
                  className="border-b border-surface-800 hover:bg-surface-800/50 cursor-pointer transition-colors"
                  onClick={() => setSelected(ret)}
                >
                  <td className="px-4 py-3 font-mono text-xs text-brand-400">{ret.return_number}</td>
                  <td className="px-4 py-3 text-slate-300">{formatDate(ret.return_date)}</td>
                  <td className="px-4 py-3 text-slate-300">{ret.invoice_number}</td>
                  <td className="px-4 py-3 text-slate-300">{ret.customer_name ?? 'Walk-in Customer'}</td>
                  <td className="px-4 py-3 text-slate-400">{REASON_LABEL[ret.reason] ?? ret.reason}</td>
                  <td className="px-4 py-3 text-right text-red-400">{formatCurrency(ret.total_refund)}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={(e) => { e.stopPropagation(); downloadCreditNote(ret) }}
                      disabled={exporting}
                      className="text-slate-400 hover:text-brand-400 transition-colors disabled:opacity-50"
                      title="Download Credit Note PDF"
                    >
                      <FileDown size={16} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Pagination page={page} totalPages={totalPages} pageSize={pageSize} total={total} onPage={setPage} onPageSize={setPageSize} />

      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setSelected(null)}>
          <div className="bg-surface-900 border border-surface-700 rounded-2xl max-w-lg w-full max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="p-5 border-b border-surface-700 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold text-white">{selected.return_number}</h2>
                <p className="text-xs text-slate-400">Against invoice {selected.invoice_number}</p>
              </div>
              <button onClick={() => setSelected(null)} className="text-slate-500 hover:text-white"><X size={18} /></button>
            </div>
            <div className="p-5 space-y-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><p className="text-xs text-slate-500">Date</p><p className="text-white">{formatDate(selected.return_date)}</p></div>
                <div><p className="text-xs text-slate-500">Customer</p><p className="text-white">{selected.customer_name ?? 'Walk-in Customer'}</p></div>
                <div><p className="text-xs text-slate-500">Reason</p><p className="text-white">{REASON_LABEL[selected.reason] ?? selected.reason}</p></div>
                <div><p className="text-xs text-slate-500">Restocked</p><p className="text-white">{selected.restocked ? 'Yes' : 'No'}</p></div>
                <div><p className="text-xs text-slate-500">Processed By</p><p className="text-white">{selected.processed_by_name ?? '—'}</p></div>
                <div><p className="text-xs text-slate-500">Total Refund</p><p className="text-red-400 font-semibold">{formatCurrency(selected.total_refund)}</p></div>
              </div>
              {selected.notes && (
                <div><p className="text-xs text-slate-500">Notes</p><p className="text-sm text-slate-300">{selected.notes}</p></div>
              )}
              <div className="border border-surface-700 rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-400 uppercase bg-surface-800">
                      <th className="px-3 py-2">Product</th>
                      <th className="px-3 py-2 text-right">Qty</th>
                      <th className="px-3 py-2 text-right">Refund</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selected.items.map((it) => (
                      <tr key={it.id} className="border-t border-surface-800">
                        <td className="px-3 py-2 text-slate-300">{it.product_name}</td>
                        <td className="px-3 py-2 text-right text-slate-300">{it.quantity_returned}</td>
                        <td className="px-3 py-2 text-right text-red-400">{formatCurrency(it.refund_amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button
                onClick={() => downloadCreditNote(selected)}
                disabled={exporting}
                className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {exporting ? <Loader2 size={16} className="animate-spin" /> : <FileDown size={16} />}
                Download Credit Note PDF
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
