import { useEffect, useMemo, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { RefreshCw, TrendingDown } from 'lucide-react'
import toast from 'react-hot-toast'
import { accountingApi, bypassNextGets } from '@/services/api'
import { formatCurrency } from '@/lib/utils'
import type { FixedAsset } from '@/types'

interface DepRow {
  key: string
  asset_code: string
  asset_name: string
  period: string
  depreciation: string
  accumulated: string
  net_book_value: string
}

export default function DepreciationPage() {
  const [assets, setAssets] = useState<FixedAsset[]>([])
  const [loading, setLoading] = useState(true)
  const [period, setPeriod] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await accountingApi.assets()
      setAssets(data.results ?? data)
    } catch { toast.error('Failed to load depreciation') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])
  useDataRefresh(load)

  const rows = useMemo<DepRow[]>(() => {
    const out: DepRow[] = []
    for (const a of assets) {
      for (const d of a.depreciation_entries ?? []) {
        out.push({
          key: `${a.id}-${d.id}`,
          asset_code: a.asset_code,
          asset_name: a.name,
          period: `${d.period_year}-${String(d.period_month).padStart(2, '0')}`,
          depreciation: d.depreciation_amount,
          accumulated: d.accumulated_to_date,
          net_book_value: d.net_book_value,
        })
      }
    }
    out.sort((x, y) => (y.period + y.asset_code).localeCompare(x.period + x.asset_code))
    return out
  }, [assets])

  const periods = useMemo(() => Array.from(new Set(rows.map((r) => r.period))).sort().reverse(), [rows])
  const filtered = period ? rows.filter((r) => r.period === period) : rows
  const totalDep = filtered.reduce((s, r) => s + parseFloat(r.depreciation), 0)

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Depreciation Register</h1>
          <p className="text-slate-400 text-sm">Posted depreciation across all assets</p>
        </div>
        <div className="sm:ml-auto flex items-center gap-2">
          <select className="input py-2 text-sm" value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="">All periods</option>
            {periods.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <button onClick={() => { bypassNextGets(); load() }} disabled={loading} className="btn-ghost p-2 text-slate-400 hover:text-white" title="Refresh">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <div className="card p-5 max-w-xs">
        <p className="text-xs text-slate-400">Total Depreciation{period ? ` (${period})` : ''}</p>
        <p className="text-xl font-bold text-red-400 mt-1">{formatCurrency(String(totalDep))}</p>
      </div>

      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Period', 'Code', 'Asset', 'Depreciation', 'Accumulated', 'Net Book Value'].map((h) => (
                  <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 6 }).map((_, j) => (
                      <td key={j} className="px-4 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-16" /></td>
                    ))}
                  </tr>
                ))
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center">
                    <TrendingDown size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No depreciation posted yet. Run depreciation from the Fixed Assets page.</p>
                  </td>
                </tr>
              ) : filtered.map((r) => (
                <tr key={r.key} className="table-row">
                  <td className="px-4 py-3.5 text-slate-400 font-mono">{r.period}</td>
                  <td className="px-4 py-3.5 text-slate-400 font-mono">{r.asset_code}</td>
                  <td className="px-4 py-3.5 text-white">{r.asset_name}</td>
                  <td className="px-4 py-3.5 font-mono text-red-400">{formatCurrency(r.depreciation)}</td>
                  <td className="px-4 py-3.5 font-mono text-slate-400">{formatCurrency(r.accumulated)}</td>
                  <td className="px-4 py-3.5 font-mono text-emerald-400">{formatCurrency(r.net_book_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
