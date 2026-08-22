import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, ArrowUpDown, BarChart3, Loader2, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import { budgetApi, bypassNextGets } from '@/services/api'
import { formatCurrency } from '@/lib/utils'
import type { BudgetMonitoringRow } from '@/types'

type SortKey = 'budget_name' | 'account' | 'period_month' | 'budgeted_amount' | 'actual_amount' | 'variance_pct'
type SortDir = 'asc' | 'desc'

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function variancePct(row: BudgetMonitoringRow): number {
  const budgeted = parseFloat(row.budgeted_amount)
  const variance = parseFloat(row.variance)
  if (!budgeted) return 0
  return (variance / budgeted) * 100
}

export default function BudgetMonitoringPage() {
  const [rows, setRows] = useState<BudgetMonitoringRow[]>([])
  const [loading, setLoading] = useState(true)
  const [budgetType, setBudgetType] = useState<'' | 'operational' | 'capital'>('')
  const [statusFilter, setStatusFilter] = useState<'active' | 'all'>('active')
  const [sortKey, setSortKey] = useState<SortKey>('budget_name')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = { status: statusFilter }
      if (budgetType) params.budget_type = budgetType
      const { data } = await budgetApi.monitoring(params)
      setRows(data)
    } catch { toast.error('Failed to load budget monitoring data') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [budgetType, statusFilter]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir('asc') }
  }

  const sortedRows = useMemo(() => {
    const copy = [...rows]
    copy.sort((a, b) => {
      let av: number | string
      let bv: number | string
      switch (sortKey) {
        case 'account':
          av = a.account?.name ?? ''
          bv = b.account?.name ?? ''
          break
        case 'period_month':
          av = a.period_month ?? 0
          bv = b.period_month ?? 0
          break
        case 'budgeted_amount':
          av = parseFloat(a.budgeted_amount)
          bv = parseFloat(b.budgeted_amount)
          break
        case 'actual_amount':
          av = parseFloat(a.actual_amount)
          bv = parseFloat(b.actual_amount)
          break
        case 'variance_pct':
          av = variancePct(a)
          bv = variancePct(b)
          break
        default:
          av = a.budget_name
          bv = b.budget_name
      }
      if (av < bv) return sortDir === 'asc' ? -1 : 1
      if (av > bv) return sortDir === 'asc' ? 1 : -1
      return 0
    })
    return copy
  }, [rows, sortKey, sortDir])

  const totals = useMemo(() => {
    const budgeted = rows.reduce((s, r) => s + parseFloat(r.budgeted_amount), 0)
    const actual = rows.reduce((s, r) => s + parseFloat(r.actual_amount), 0)
    return { budgeted, actual, remaining: budgeted - actual }
  }, [rows])

  const SortHeader = ({ label, k }: { label: string; k: SortKey }) => (
    <th
      onClick={() => toggleSort(k)}
      className="px-4 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider cursor-pointer select-none hover:text-white transition-colors"
    >
      <span className="inline-flex items-center gap-1">
        {label}
        <ArrowUpDown size={11} className={sortKey === k ? 'text-brand-400' : 'text-slate-600'} />
      </span>
    </th>
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <Link to="/budgets" className="text-slate-400 hover:text-white text-xs inline-flex items-center gap-1 mb-1">
            <ArrowLeft size={12} /> Back to Budgets
          </Link>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <BarChart3 size={22} className="text-brand-400" /> Budget Monitoring
          </h1>
          <p className="text-slate-400 text-sm">{rows.length} line{rows.length !== 1 ? 's' : ''} across every {statusFilter === 'active' ? 'active' : ''} budget</p>
        </div>
        <div className="flex items-center gap-2 sm:ml-auto">
          <button onClick={() => { bypassNextGets(); load() }} disabled={loading} className="btn-ghost p-2 text-slate-400 hover:text-white" title="Refresh">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <select className="input w-auto" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as 'active' | 'all')}>
            <option value="active">Active budgets only</option>
            <option value="all">All statuses</option>
          </select>
          <select className="input w-auto" value={budgetType} onChange={(e) => setBudgetType(e.target.value as '' | 'operational' | 'capital')}>
            <option value="">All types</option>
            <option value="operational">Operational</option>
            <option value="capital">Capital</option>
          </select>
        </div>
      </div>

      {/* Totals strip */}
      {!loading && rows.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="card p-4">
            <p className="text-slate-500 text-xs uppercase tracking-wide">Total Budgeted</p>
            <p className="text-white font-mono text-lg mt-1">{formatCurrency(totals.budgeted)}</p>
          </div>
          <div className="card p-4">
            <p className="text-slate-500 text-xs uppercase tracking-wide">Total Actual</p>
            <p className="text-white font-mono text-lg mt-1">{formatCurrency(totals.actual)}</p>
          </div>
          <div className="card p-4">
            <p className="text-slate-500 text-xs uppercase tracking-wide">Remaining</p>
            <p className={`font-mono text-lg mt-1 ${totals.remaining < 0 ? 'text-red-400' : 'text-emerald-400'}`}>{formatCurrency(totals.remaining)}</p>
          </div>
        </div>
      )}

      {loading ? (
        <div className="card p-12 text-center">
          <Loader2 size={28} className="mx-auto mb-3 text-slate-600 animate-spin" />
          <p className="text-slate-400 text-sm">Loading monitoring data…</p>
        </div>
      ) : rows.length === 0 ? (
        <div className="card p-12 text-center">
          <BarChart3 size={36} className="mx-auto mb-3 text-slate-600" />
          <p className="text-slate-400 font-medium">Nothing to monitor yet</p>
          <p className="text-slate-500 text-sm mt-1">
            {statusFilter === 'active'
              ? 'Activate a budget (and add lines to it) to see it here.'
              : 'Create a budget and add lines to start tracking.'}
          </p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-700 bg-surface-800/50">
                  <SortHeader label="Budget" k="budget_name" />
                  <SortHeader label="Account" k="account" />
                  <SortHeader label="Period" k="period_month" />
                  <SortHeader label="Budgeted" k="budgeted_amount" />
                  <SortHeader label="Actual" k="actual_amount" />
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">Remaining</th>
                  <SortHeader label="Variance %" k="variance_pct" />
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-700">
                {sortedRows.map((row) => {
                  const pct = variancePct(row)
                  const remaining = parseFloat(row.budgeted_amount) - parseFloat(row.actual_amount)
                  return (
                    <tr key={row.id} className="table-row">
                      <td className="px-4 py-3">
                        <p className="text-slate-200">{row.budget_name}</p>
                        <p className="text-xs text-slate-500">{row.category_name} · <span className={row.budget_type === 'capital' ? 'text-blue-400' : 'text-slate-500'}>{row.budget_type}</span></p>
                      </td>
                      <td className="px-4 py-3 text-slate-400">
                        {row.account ? `${row.account.code} · ${row.account.name}` : '—'}
                      </td>
                      <td className="px-4 py-3 text-slate-400">{row.period_month ? MONTH_NAMES[row.period_month - 1] : 'All'}</td>
                      <td className="px-4 py-3 font-mono text-white">{formatCurrency(row.budgeted_amount)}</td>
                      <td className="px-4 py-3 font-mono text-slate-300">{formatCurrency(row.actual_amount)}</td>
                      <td className={`px-4 py-3 font-mono ${remaining < 0 ? 'text-red-400' : 'text-emerald-400'}`}>{formatCurrency(remaining)}</td>
                      <td className="px-4 py-3">
                        <span className={row.over_budget ? 'badge-red' : 'badge-green'}>
                          {pct > 0 ? '+' : ''}{pct.toFixed(1)}%
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
