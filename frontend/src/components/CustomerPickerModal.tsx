import { useEffect, useRef, useState } from 'react'
import { Search, X, User } from 'lucide-react'
import { customerApi } from '@/services/api'
import type { Customer } from '@/types'

interface CustomerPickerModalProps {
  open: boolean
  onClose: () => void
  onSelect: (customer: Customer) => void
}

export default function CustomerPickerModal({ open, onClose, onSelect }: CustomerPickerModalProps) {
  const [query, setQuery] = useState('')
  const [customers, setCustomers] = useState<Customer[]>([])
  const [loading, setLoading] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const load = async (search: string) => {
    setLoading(true)
    try {
      const { data } = await customerApi.list(search ? { search } : undefined)
      setCustomers(data.results ?? data)
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
  }, [open])

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
          <h2 className="text-base font-bold text-white">Choose Customer</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={20} /></button>
        </div>
        <div className="p-4 border-b border-surface-700">
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              autoFocus
              className="input pl-9"
              placeholder="Search customers…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        </div>
        <div className="overflow-y-auto flex-1">
          {loading ? (
            <div className="px-5 py-6 text-center text-sm text-slate-500">Searching…</div>
          ) : customers.length === 0 ? (
            <div className="px-5 py-6 text-center text-sm text-slate-500">No customers found</div>
          ) : (
            <ul className="divide-y divide-surface-700">
              {customers.map((c) => (
                <li key={c.id}>
                  <button
                    className="w-full flex items-center gap-3 px-5 py-3 hover:bg-surface-700/60 transition-colors text-left"
                    onClick={() => { onSelect(c); onClose() }}
                  >
                    <div className="w-8 h-8 rounded-lg bg-brand-500/15 flex items-center justify-center shrink-0">
                      <User size={15} className="text-brand-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-white font-medium truncate">{c.name}</p>
                      <p className="text-xs text-slate-500 truncate">{c.email || c.phone || c.code}</p>
                    </div>
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
