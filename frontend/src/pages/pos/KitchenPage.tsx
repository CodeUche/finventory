import { useEffect, useState, useCallback } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Loader2, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import { posApi } from '@/services/api'
import { formatDate } from '@/lib/utils'

interface KItem { id: string; product_name: string; quantity: number; notes: string }
interface KOT {
  id: string; kot_number: string; order_number: string; table_name: string | null
  order_type: string; section: string; status: string; items: KItem[]; created_at: string
}

const NEXT: Record<string, string> = { new: 'preparing', preparing: 'ready', ready: 'served' }
// Kit badge colours (see .badge-* in styles/ds.css)
const STATUS_BADGE: Record<string, string> = {
  new: 'badge-blue',
  preparing: 'badge-yellow',
  ready: 'badge-green',
  served: 'badge-slate',
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
  useDataRefresh(load)

  const advance = async (k: KOT) => {
    const next = NEXT[k.status]
    if (!next) return
    try { await posApi.setKotStatus(k.id, next); load() } catch { toast.error('Failed to update') }
  }

  return (
    <div className="ds">
      <header className="ds-head">
        <div>
          <h1>Kitchen (KOT)</h1>
          <p>Orders waiting to be prepared</p>
        </div>
        <button onClick={load} aria-label="Refresh" title="Refresh" className="ds-icon-btn"><RefreshCw size={16} /></button>
      </header>
      {loading ? (
        <div className="flex justify-center py-16 text-slate-400"><Loader2 className="animate-spin" /></div>
      ) : kots.length === 0 ? (
        <div className="text-center text-slate-500 text-sm py-16">No kitchen tickets.</div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {kots.filter((k) => k.status !== 'served').map((k) => (
            <div key={k.id} className="card p-4">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <div className="text-base font-bold text-white">{k.kot_number}</div>
                  <div className="text-xs text-slate-500">
                    {k.order_number} · {k.order_type.replace('_', ' ')}{k.table_name ? ` · ${k.table_name}` : ''}
                  </div>
                </div>
                <span className={`badge ${STATUS_BADGE[k.status] ?? 'badge-slate'} capitalize`}>{k.status}</span>
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
                <button onClick={() => advance(k)} className="btn-primary w-full">
                  Mark {NEXT[k.status]}
                </button>
              )}
              <div className="text-xs text-slate-500 mt-2 text-right">{formatDate(k.created_at)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
