import { useEffect, useMemo, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Loader2, RefreshCw, TrendingDown } from 'lucide-react'
import toast from 'react-hot-toast'
import { accountingApi, bypassNextGets } from '@/services/api'
import { confirmDialog } from '@/lib/dialog'
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
  const [runningDep, setRunningDep] = useState(false)
  const [postingBatch, setPostingBatch] = useState(false)

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

  // Same run flow as the Fixed Assets page — so depreciation can be run from here too.
  const handleRunDepreciation = async (draft = false) => {
    const now = new Date()
    const monthLabel = now.toLocaleString('default', { month: 'long' })
    const verb = draft ? 'Generate a DRAFT depreciation batch' : 'Run and POST depreciation'
    const catchUp = await confirmDialog(
      `${verb} up to ${monthLabel} ${now.getFullYear()}?\n\nClick OK to catch up ALL outstanding months through this period, or Cancel to run just this month.`,
    )
    const payload = { year: now.getFullYear(), month: now.getMonth() + 1, catch_up: catchUp, draft }
    setRunningDep(true)
    try {
      const { data } = await accountingApi.runDepreciation(payload)
      const d = data as { entries_created?: number; already_run?: boolean; message?: string }
      if (d.already_run) toast(d.message ?? 'Depreciation already run for this period.', { icon: 'ℹ️' })
      else toast.success(d.message ?? `Depreciation run complete — ${d.entries_created ?? 0} entries created`)
      bypassNextGets()
      load()
    } catch { toast.error('Failed to run depreciation') }
    finally { setRunningDep(false) }
  }

  const handlePostBatch = async () => {
    const now = new Date()
    setPostingBatch(true)
    try {
      const { data } = await accountingApi.postDepreciationBatch({
        year: now.getFullYear(), month: now.getMonth() + 1,
      })
      toast.success((data as { message?: string }).message ?? 'Draft batch posted')
      bypassNextGets()
      load()
    } catch { toast.error('Failed to post depreciation batch') }
    finally { setPostingBatch(false) }
  }

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

  // Register-wide totals (always across all assets, independent of the period filter).
  const totalCost = assets.reduce((s, a) => s + parseFloat(a.purchase_cost || '0'), 0)
  const totalNBV = assets.reduce((s, a) => s + parseFloat(a.net_book_value || '0'), 0)

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
          <button onClick={() => handleRunDepreciation(false)} disabled={runningDep} className="btn-primary flex items-center gap-2 text-sm" title="Compute and post depreciation">
            {runningDep ? <Loader2 size={14} className="animate-spin" /> : <TrendingDown size={14} />}
            Run Depreciation
          </button>
          <button onClick={() => handleRunDepreciation(true)} disabled={runningDep} className="btn-ghost text-sm" title="Compute depreciation as a draft batch for review">
            Draft Batch
          </button>
          <button onClick={handlePostBatch} disabled={postingBatch} className="btn-ghost text-sm" title="Post this month's draft depreciation batch">
            {postingBatch ? <Loader2 size={14} className="animate-spin" /> : 'Post Batch'}
          </button>
        </div>
      </div>

      {/* Register totals — the asset value, depreciation and NBV summary lives here. */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="card p-5">
          <p className="text-xs text-slate-400">Total Assets Value</p>
          <p className="text-xl font-bold text-white mt-1">{formatCurrency(String(totalCost))}</p>
        </div>
        <div className="card p-5">
          <p className="text-xs text-slate-400">Total Depreciation{period ? ` (${period})` : ''}</p>
          <p className="text-xl font-bold text-red-400 mt-1">{formatCurrency(String(totalDep))}</p>
        </div>
        <div className="card p-5">
          <p className="text-xs text-slate-400">Net Book Value</p>
          <p className="text-xl font-bold text-emerald-400 mt-1">{formatCurrency(String(totalNBV))}</p>
        </div>
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
                    <p className="text-slate-500">No depreciation posted yet. Click Run Depreciation above to post this period.</p>
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
