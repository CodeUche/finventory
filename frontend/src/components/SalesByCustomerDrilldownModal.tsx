/**
 * SalesByCustomerDrilldownModal — full invoice history for one customer.
 *
 * Opened from the Sales Analytics "Top Customers" chart/table — clicking a
 * customer row/bar shows every invoice for that customer (defaults to a wide
 * 5-year window so it covers "first purchase till date"), with in-modal
 * filters (date range, product/text search, amount range) and an Excel
 * export of the currently selected customer + date range.
 */

import { useEffect, useState } from 'react'
import { X, Loader2, Receipt, Download } from 'lucide-react'
import toast from 'react-hot-toast'
import { reportApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import { saveBlobFile } from '@/lib/saveBlobFile'
import DateInput from '@/components/DateInput'

interface Props {
  open: boolean
  onClose: () => void
  customerId: string | null   // null/'walk-in' = walk-in customer bucket
  customerName: string
}

interface InvoiceRow {
  id: string
  invoice_number: string
  issue_date: string
  status: string
  total_amount: string
  amount_paid: string
  amount_due: string
}

/** Wide default window so the drill-down covers "first purchase till date." */
function defaultDateFrom(): string {
  const d = new Date()
  d.setFullYear(d.getFullYear() - 5)
  return d.toISOString().slice(0, 10)
}
function defaultDateTo(): string {
  return new Date().toISOString().slice(0, 10)
}

export default function SalesByCustomerDrilldownModal({ open, onClose, customerId, customerName }: Props) {
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [invoices, setInvoices] = useState<InvoiceRow[]>([])

  // In-modal filters
  const [dateFrom, setDateFrom] = useState(defaultDateFrom())
  const [dateTo, setDateTo] = useState(defaultDateTo())
  const [search, setSearch] = useState('')
  const [minAmount, setMinAmount] = useState('')
  const [maxAmount, setMaxAmount] = useState('')

  const load = async () => {
    if (!customerId) return
    setLoading(true)
    try {
      const res = await reportApi.customerInvoices({
        customer_id: customerId,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      })
      setInvoices(res.data.results ?? res.data)
    } catch {
      toast.error('Failed to load customer invoices')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open && customerId) {
      setSearch('')
      setMinAmount('')
      setMaxAmount('')
      load()
    }
  }, [open, customerId])

  const handleFilter = () => load()

  const filtered = invoices.filter(inv => {
    if (search) {
      const q = search.toLowerCase()
      if (!inv.invoice_number.toLowerCase().includes(q) && !inv.status.toLowerCase().includes(q)) {
        return false
      }
    }
    const amt = parseFloat(inv.total_amount)
    if (minAmount && amt < parseFloat(minAmount)) return false
    if (maxAmount && amt > parseFloat(maxAmount)) return false
    return true
  })

  const handleExport = async () => {
    if (!customerId) return
    setExporting(true)
    try {
      const resp = await reportApi.download('/reports/customer-invoices/', {
        customer_id: customerId,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        format: 'excel',
      })
      const blob = new Blob([resp.data as BlobPart], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      })
      const today = new Date().toISOString().slice(0, 10)
      await saveBlobFile(blob, `customer_invoices_${today}.xlsx`)
    } catch {
      toast.error('Export failed. Please try again.')
    } finally {
      setExporting(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-3xl shadow-2xl animate-slide-up max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-surface-700 shrink-0">
          <div>
            <h2 className="font-semibold text-white text-lg">Customer Sales History</h2>
            <p className="text-xs text-slate-400 mt-0.5">{customerName || 'Walk-in'}</p>
          </div>
          <button onClick={onClose} className="btn-ghost p-1.5"><X size={18} /></button>
        </div>

        {/* Filter bar */}
        <div className="px-5 py-3 border-b border-surface-700 shrink-0 space-y-2">
          <div className="flex flex-col sm:flex-row gap-2">
            <div className="flex items-center gap-2 shrink-0">
              <DateInput value={dateFrom} onChange={setDateFrom} placeholder="From" className="w-32 text-sm" />
              <span className="text-slate-500 text-sm">–</span>
              <DateInput value={dateTo} onChange={setDateTo} placeholder="To" className="w-32 text-sm" />
              <button
                onClick={handleFilter}
                disabled={loading}
                className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium transition-colors disabled:opacity-50"
              >
                Apply
              </button>
            </div>
            <input
              type="text"
              placeholder="Search invoice # or status..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="input py-1.5 text-sm flex-1"
            />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Amount:</span>
            <input
              type="number"
              placeholder="Min"
              value={minAmount}
              onChange={e => setMinAmount(e.target.value)}
              className="input py-1.5 text-sm w-24"
            />
            <span className="text-slate-500 text-sm">–</span>
            <input
              type="number"
              placeholder="Max"
              value={maxAmount}
              onChange={e => setMaxAmount(e.target.value)}
              className="input py-1.5 text-sm w-24"
            />
            <span className="text-xs text-slate-500 ml-auto">{filtered.length} of {invoices.length} invoices</span>
          </div>
        </div>

        {/* Body */}
        <div className="overflow-auto flex-1">
          {loading ? (
            <div className="py-16 text-center"><Loader2 size={24} className="animate-spin mx-auto text-brand-400" /></div>
          ) : filtered.length === 0 ? (
            <div className="py-16 text-center">
              <Receipt size={32} className="mx-auto mb-2 text-slate-600" />
              <p className="text-slate-500">No invoices match these filters</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-700">
                  {['Invoice #', 'Date', 'Status', 'Total', 'Paid', 'Due'].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map(inv => (
                  <tr key={inv.id} className="table-row">
                    <td className="px-4 py-3 font-mono text-xs text-brand-400">{inv.invoice_number}</td>
                    <td className="px-4 py-3 text-slate-300 whitespace-nowrap">{formatDate(inv.issue_date)}</td>
                    <td className="px-4 py-3">
                      <span className={`badge-${inv.status === 'paid' ? 'green' : inv.status === 'voided' ? 'red' : 'slate'}`}>
                        {inv.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-semibold text-white">{formatCurrency(inv.total_amount)}</td>
                    <td className="px-4 py-3 text-slate-300">{formatCurrency(inv.amount_paid)}</td>
                    <td className="px-4 py-3 text-slate-300">{formatCurrency(inv.amount_due)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 p-4 border-t border-surface-700 shrink-0">
          <button onClick={onClose} className="btn-ghost px-4 py-2 text-sm">Close</button>
          <button
            onClick={handleExport}
            disabled={exporting || !customerId}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition-colors disabled:opacity-50"
          >
            {exporting ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
            Export this customer
          </button>
        </div>
      </div>
    </div>
  )
}
