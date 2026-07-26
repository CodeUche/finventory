import { useEffect, useState, useCallback } from 'react'
import { ClipboardCheck, Loader2, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import { posApi } from '@/services/api'
import { formatDate } from '@/lib/utils'

interface KItem { id: string; product_name: string; quantity: number; notes: string }
interface KOT {
  id: string; kot_number: string; order_number: string; table_name: string | null
  order_type: string; section: string; status: string; items: KItem[]; created_at: string
}

const NEXT: Record<string, string> = { new: 'preparing', preparing: 'ready', ready: 'served' }
const STATUS_BADGE: Record<string, string> = {
  new: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  preparing: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  ready: 'bg-green-500/15 text-green-400 border-green-500/30',
  served: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
}

export default function KitchenPage() {
  const [kots, setKots] = useState<KOT[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await posApi.kots()
      setKots(data.results ?? data)
    } catch { toast.error('Failed to load kitchen tickets') } finally { setLoading(false) }
  }, [])
  useEffect(() => { load(); const i = setInterval(load, 20000); return () => clearInterval(i) }, [load])

  const advance = async (k: KOT) => {
    const next = NEXT[k.status]
    if (!next) return
    try { await posApi.setKotStatus(k.id, next); load() } catch { toast.error('Failed to update') }
  }

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold text-white flex items-center gap-2"><ClipboardCheck size={20} /> Kitchen Display (KOT)</h1>
        <button onClick={load} className="btn-ghost"><RefreshCw size={16} /></button>
      </div>
      {loading ? (
        <div className="flex justify-center py-16 text-slate-400"><Loader2 className="animate-spin" /></div>
      ) : kots.length === 0 ? (
        <div className="text-center text-slate-500 text-sm py-16">No kitchen tickets.</div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {kots.filter((k) => k.status !== 'served').map((k) => (
            <div key={k.id} className="rounded-xl border border-surface-700 bg-surface-800/40 p-3">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <div className="text-sm font-bold text-white font-mono">{k.kot_number}</div>
                  <div className="text-[11px] text-slate-500">
                    {k.order_number} · {k.order_type.replace('_', ' ')}{k.table_name ? ` · ${k.table_name}` : ''}
                  </div>
                </div>
                <span className={`text-[11px] px-2 py-1 rounded border ${STATUS_BADGE[k.status] ?? ''}`}>{k.status}</span>
              </div>
              <ul className="space-y-1 mb-3">
                {k.items.map((it) => (
                  <li key={it.id} className="text-sm text-slate-200 flex justify-between">
                    <span>{it.product_name}{it.notes ? ` — ${it.notes}` : ''}</span>
                    <span className="text-slate-400">×{it.quantity}</span>
                  </li>
                ))}
              </ul>
              {NEXT[k.status] && (
                <button onClick={() => advance(k)} className="btn-primary w-full text-xs">
                  Mark {NEXT[k.status]}
                </button>
              )}
              <div className="text-[10px] text-slate-600 mt-1 text-right">{formatDate(k.created_at)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
