import { useEffect, useRef, useState } from 'react'
import { Search, X, Receipt } from 'lucide-react'
import { salesApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import type { Invoice } from '@/types'

interface InvoicePickerModalProps {
  open: boolean
  onClose: () => void
  onSelect: (invoice: Invoice) => void
  customerId: string
}

export default function InvoicePickerModal({ open, onClose, onSelect, customerId }: InvoicePickerModalProps) {
  const [query, setQuery] = useState('')
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [loading, setLoading] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const load = async (search: string) => {
    if (!customerId) return
    setLoading(true)
    try {
      const params: Record<string, unknown> = { customer: customerId, ordering: '-issue_date' }
      if (search) params.search = search
      const { data } = await salesApi.invoices(params)
      setInvoices(data.results ?? data)
    } catch {
      // non-critical
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return
    load('')
    setQuery('')
  }, [open, customerId])

  useEffect(() => {
    if (!open) return
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => load(query), 350)
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [query, open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative card w-full max-w-md p-0 overflow-hidden flex flex-col max-h-[80vh]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-surface-700">
          <h2 className="text-base font-bold text-white">Choose Invoice</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={20} /></button>
        </div>
        <div className="p-4 border-b border-surface-700">
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              autoFocus
              className="input pl-9"
              placeholder="Search invoice number…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        </div>
        <div className="overflow-y-auto flex-1">
          {loading ? (
            <div className="px-5 py-6 text-center text-sm text-slate-500">Searching…</div>
          ) : invoices.length === 0 ? (
            <div className="px-5 py-6 text-center text-sm text-slate-500">No invoices found for this customer</div>
          ) : (
            <ul className="divide-y divide-surface-700">
              {invoices.map((inv) => (
                <li key={inv.id}>
                  <button
                    className="w-full flex items-center gap-3 px-5 py-3 hover:bg-surface-700/60 transition-colors text-left"
                    onClick={() => { onSelect(inv); onClose() }}
                  >
                    <div className="w-8 h-8 rounded-lg bg-emerald-500/15 flex items-center justify-center shrink-0">
                      <Receipt size={15} className="text-emerald-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-white font-medium truncate">{inv.invoice_number}</p>
                      <p className="text-xs text-slate-500 truncate">
                        {formatDate(inv.issue_date)} · {formatCurrency(inv.total_amount)} · {inv.status}
                      </p>
                    </div>
                    <div className="text-xs text-slate-400 shrink-0">Due {formatCurrency(inv.amount_due)}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
