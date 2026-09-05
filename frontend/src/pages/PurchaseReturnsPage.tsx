import { useEffect, useRef, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Search, X, Loader2, RotateCcw, FileDown } from 'lucide-react'
import toast from 'react-hot-toast'
import { purchaseReturnApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import DateInput from '@/components/DateInput'
import { useAuthStore } from '@/store/authStore'
import { saveBlobFile } from '@/lib/saveBlobFile'
import { usePagination } from '@/hooks/usePagination'
import Pagination from '@/components/Pagination'
import type { PurchaseReturn } from '@/types'

const REFUND_METHOD_LABEL: Record<string, string> = {
  ap: 'Reduce Payable (debit note)',
  cash: 'Cash Refund',
  bank: 'Bank Refund',
}

function hexToRgb(hex?: string): [number, number, number] {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
  if (!m) return [249, 115, 22]
  return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
}

export default function PurchaseReturnsPage() {
  const { organisation } = useAuthStore()
  const [returns, setReturns] = useState<PurchaseReturn[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [selected, setSelected] = useState<PurchaseReturn | null>(null)
  const [exporting, setExporting] = useState(false)

  // See SalesReturnsPage's identical guard: typing a date fires onChange per
  // keystroke, so an earlier, broader request can resolve after a later,
  // narrower one and overwrite the correctly filtered result with stale rows.
  const requestSeq = useRef(0)

  const load = async () => {
    const seq = ++requestSeq.current
    setLoading(true)
    try {
      const { data } = await purchaseReturnApi.list({
        search: search || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        page_size: 5000,
      })
      if (seq !== requestSeq.current) return
      setReturns(data.results ?? data)
    } catch {
      if (seq === requestSeq.current) toast.error('Failed to load purchase returns')
    } finally {
      if (seq === requestSeq.current) setLoading(false)
    }
  }

  useEffect(() => { load() }, [search, dateFrom, dateTo])
  useDataRefresh(load)

  const { page, setPage, pageSize, setPageSize, totalPages, paged, total } = usePagination(returns)

  const downloadDebitNote = async (ret: PurchaseReturn) => {
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
        docTitle: 'DEBIT NOTE',
        metaRows: [
          ['No.', ret.return_number],
          ['Date', formatDate(ret.return_date)],
          ['Against PO', ret.po_number],
          ['Refund Method', REFUND_METHOD_LABEL[ret.refund_method] ?? ret.refund_method],
        ],
      })

      const boxW = pageW - 28
      doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
      doc.roundedRect(14, y, boxW, 24, 2, 2, 'FD')
      doc.setFontSize(TYPE.H3.size); doc.setFont('helvetica', 'bold'); doc.setTextColor(...BRAND)
      doc.text('SUPPLIER', 17, y + 5)
      doc.setFontSize(TYPE.H2.size); doc.setFont('helvetica', 'bold'); doc.setTextColor(...DARK)
      doc.text(ret.supplier_name ?? 'Unnamed Supplier', 17, y + 11)
      if (ret.reason) {
        doc.setFontSize(TYPE.BODY.size); doc.setFont('helvetica', 'normal'); doc.setTextColor(...MUTED)
        doc.text(ret.reason, 17, y + 17, { maxWidth: boxW - 6 })
      }
      y += 24 + 6

      const ts = buildTableStyle(BRAND, 'helvetica')
      autoTable(doc, {
        ...ts,
        startY: y,
        head: [['Product', 'Qty', 'Unit Cost', 'Line Total']],
        body: ret.items.map((it) => [
          it.product_name,
          pdfQty(it.quantity_returned),
          pdfMoney(it.unit_cost),
          pdfMoney(it.line_total),
        ]),
        columnStyles: {
          1: { halign: 'right' as const, cellWidth: 22 },
          2: { halign: 'right' as const, cellWidth: 32 },
          3: { halign: 'right' as const, cellWidth: 34 },
        },
      })

      const finalY = (doc as any).lastAutoTable?.finalY ?? y + 20
      let ty = finalY + 8
      doc.setFontSize(TYPE.BODY.size); doc.setFont('helvetica', 'normal'); doc.setTextColor(...MUTED)
      doc.text('Subtotal', pageW - 70, ty)
      doc.setTextColor(...DARK)
      doc.text(pdfMoney(ret.subtotal), pageW - 16, ty, { align: 'right' })
      ty += 6
      doc.setTextColor(...MUTED)
      doc.text('VAT', pageW - 70, ty)
      doc.setTextColor(...DARK)
      doc.text(pdfMoney(ret.tax_amount), pageW - 16, ty, { align: 'right' })
      ty += 8
      doc.setFontSize(TYPE.H2.size); doc.setFont('helvetica', 'bold'); doc.setTextColor(...DARK)
      doc.text('Total', pageW - 70, ty)
      doc.setTextColor(...BRAND)
      doc.text(pdfMoney(ret.total_amount), pageW - 16, ty, { align: 'right' })

      addDocFooter(doc, {
        orgName: organisation?.name ?? 'Company',
        docTitle: 'DEBIT NOTE',
        docRef: ret.return_number,
        BRAND,
        pdfFont: 'helvetica',
      })

      await saveBlobFile(doc.output('blob'), `debit-note-${ret.return_number}.pdf`)
    } catch {
      toast.error('Failed to generate debit note PDF')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <RotateCcw size={22} className="text-brand-400" /> Purchase Returns
          </h1>
          <p className="text-slate-400 text-sm">Debit notes issued against purchase orders</p>
        </div>
      </div>

      <div className="card p-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            className="input pl-9"
            placeholder="Search return #, supplier or PO #…"
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
          <div className="p-10 text-center text-slate-500 text-sm">No purchase returns found</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-400 uppercase border-b border-surface-700">
                <th className="px-4 py-3">Return #</th>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">PO #</th>
                <th className="px-4 py-3">Supplier</th>
                <th className="px-4 py-3">Refund Method</th>
                <th className="px-4 py-3 text-right">Total</th>
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
                  <td className="px-4 py-3 text-slate-300">{ret.po_number}</td>
                  <td className="px-4 py-3 text-slate-300">{ret.supplier_name ?? '—'}</td>
                  <td className="px-4 py-3 text-slate-400">{REFUND_METHOD_LABEL[ret.refund_method] ?? ret.refund_method}</td>
                  <td className="px-4 py-3 text-right text-red-400">{formatCurrency(ret.total_amount)}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={(e) => { e.stopPropagation(); downloadDebitNote(ret) }}
                      disabled={exporting}
                      className="text-slate-400 hover:text-brand-400 transition-colors disabled:opacity-50"
                      title="Download Debit Note PDF"
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
                <p className="text-xs text-slate-400">Against PO {selected.po_number}</p>
              </div>
              <button onClick={() => setSelected(null)} className="text-slate-500 hover:text-white"><X size={18} /></button>
            </div>
            <div className="p-5 space-y-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><p className="text-xs text-slate-500">Date</p><p className="text-white">{formatDate(selected.return_date)}</p></div>
                <div><p className="text-xs text-slate-500">Supplier</p><p className="text-white">{selected.supplier_name ?? '—'}</p></div>
                <div><p className="text-xs text-slate-500">Refund Method</p><p className="text-white">{REFUND_METHOD_LABEL[selected.refund_method] ?? selected.refund_method}</p></div>
                <div><p className="text-xs text-slate-500">GL Status</p><p className="text-white capitalize">{selected.gl_post_status}</p></div>
                <div><p className="text-xs text-slate-500">Subtotal</p><p className="text-white">{formatCurrency(selected.subtotal)}</p></div>
                <div><p className="text-xs text-slate-500">Total</p><p className="text-red-400 font-semibold">{formatCurrency(selected.total_amount)}</p></div>
              </div>
              {selected.reason && (
                <div><p className="text-xs text-slate-500">Reason</p><p className="text-sm text-slate-300">{selected.reason}</p></div>
              )}
              <div className="border border-surface-700 rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-400 uppercase bg-surface-800">
                      <th className="px-3 py-2">Product</th>
                      <th className="px-3 py-2 text-right">Qty</th>
                      <th className="px-3 py-2 text-right">Line Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selected.items.map((it) => (
                      <tr key={it.id} className="border-t border-surface-800">
                        <td className="px-3 py-2 text-slate-300">{it.product_name}</td>
                        <td className="px-3 py-2 text-right text-slate-300">{it.quantity_returned}</td>
                        <td className="px-3 py-2 text-right text-red-400">{formatCurrency(it.line_total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button
                onClick={() => downloadDebitNote(selected)}
                disabled={exporting}
                className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {exporting ? <Loader2 size={16} className="animate-spin" /> : <FileDown size={16} />}
                Download Debit Note PDF
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
