import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft, BarChart3, Download, ChevronUp, ChevronDown,
  TrendingUp, Users, AlertCircle, DollarSign, Loader2,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { partnerApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'

// ── Types ────────────────────────────────────────────────────────────────────

interface ConsolidatedClient {
  link_id: string
  org_id: string
  org_name: string
  plan: string
  revenue_this_month: number
  outstanding_balance: number
  overdue_count: number
}

interface ConsolidatedData {
  clients: ConsolidatedClient[]
  totals: {
    total_revenue: number
    total_outstanding: number
    total_customers: number
    client_count: number
  }
}

type SortField = 'org_name' | 'revenue_this_month' | 'outstanding_balance' | 'overdue_count'
type SortDir = 'asc' | 'desc'

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtMoney(v: string | number) {
  const n = parseFloat(String(v))
  if (isNaN(n)) return '₦—'
  return '₦' + n.toLocaleString('en-NG', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function csvEscape(v: string | number) {
  const s = String(v)
  return s.includes(',') || s.includes('"') ? `"${s.replace(/"/g, '""')}"` : s
}

function exportCSV(clients: ConsolidatedClient[]) {
  const header = ['Organisation', 'Plan', 'Revenue This Month (₦)', 'Outstanding Balance (₦)', 'Overdue Invoices']
  const rows = clients.map((c) => [
    csvEscape(c.org_name),
    csvEscape(c.plan),
    csvEscape(c.revenue_this_month),
    csvEscape(c.outstanding_balance),
    csvEscape(c.overdue_count),
  ])
  const csv = [header, ...rows].map((r) => r.join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `partner-report-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

// ── KPI Tile ─────────────────────────────────────────────────────────────────

function KpiTile({
  label, value, sub, icon: Icon, accent,
}: { label: string; value: string | number; sub?: string; icon: React.ElementType; accent?: string }) {
  return (
    <div className="card space-y-2 py-4">
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        <Icon size={12} />
        <span>{label}</span>
      </div>
      <p className={`text-2xl font-bold leading-none ${accent ?? 'text-white'}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500">{sub}</p>}
    </div>
  )
}

// ── Sort Header ───────────────────────────────────────────────────────────────

function SortTh({
  field, label, current, dir, onSort,
}: { field: SortField; label: string; current: SortField; dir: SortDir; onSort: (f: SortField) => void }) {
  const active = field === current
  return (
    <th
      className="px-4 py-2.5 text-xs font-semibold text-slate-400 uppercase tracking-wide text-right cursor-pointer select-none hover:text-white transition-colors"
      onClick={() => onSort(field)}
    >
      <span className="inline-flex items-center justify-end gap-1">
        {label}
        {active
          ? (dir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />)
          : <ChevronDown size={12} className="opacity-30" />}
      </span>
    </th>
  )
}

// ── Upgrade Prompt ────────────────────────────────────────────────────────────

function UpgradePrompt() {
  const navigate = useNavigate()
  return (
    <div className="flex-1 flex items-center justify-center py-20">
      <div className="text-center max-w-sm space-y-4">
        <div className="w-14 h-14 rounded-full bg-brand-500/15 flex items-center justify-center mx-auto">
          <BarChart3 size={24} className="text-brand-400" />
        </div>
        <h2 className="text-lg font-semibold text-white">Consolidated Reports</h2>
        <p className="text-sm text-slate-400">
          Get a unified view of all your clients' revenue, outstanding balances, and overdue invoices —
          available on Partner Pro and Agency plans.
        </p>
        <ul className="text-xs text-slate-400 space-y-1 text-left list-inside">
          <li className="flex items-start gap-2"><span className="text-brand-400 mt-0.5">✓</span> Revenue across all clients this month</li>
          <li className="flex items-start gap-2"><span className="text-brand-400 mt-0.5">✓</span> Outstanding & overdue balances at a glance</li>
          <li className="flex items-start gap-2"><span className="text-brand-400 mt-0.5">✓</span> Sortable table with CSV export</li>
        </ul>
        <button
          onClick={() => navigate('/billing')}
          className="btn-primary text-sm"
        >
          Upgrade to Pro or Agency
        </button>
      </div>
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function PartnerReportPage() {
  const navigate = useNavigate()
  const { planName } = useAuthStore()

  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<ConsolidatedData | null>(null)
  const [sortField, setSortField] = useState<SortField>('revenue_this_month')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  // Partner Pro/Agency have consolidated_reporting feature; Starter does not.
  // planName is lowercased e.g. "partner pro", "partner agency", "partner starter"
  const canAccess = planName?.startsWith('partner') &&
    !planName?.includes('starter')

  useEffect(() => {
    if (!canAccess) { setLoading(false); return }
    partnerApi.consolidated()
      .then((r) => setData(r.data))
      .catch((err) => {
        const msg = err?.response?.data?.error?.message ?? err?.response?.data?.detail ?? 'Failed to load report'
        toast.error(msg)
      })
      .finally(() => setLoading(false))
  }, [canAccess])

  const handleSort = (field: SortField) => {
    if (field === sortField) setSortDir((d) => d === 'asc' ? 'desc' : 'asc')
    else { setSortField(field); setSortDir('desc') }
  }

  const sorted = useMemo(() => {
    if (!data?.clients) return []
    return [...data.clients].sort((a, b) => {
      const av = a[sortField]
      const bv = b[sortField]
      if (typeof av === 'string') return sortDir === 'asc' ? av.localeCompare(bv as string) : (bv as string).localeCompare(av)
      return sortDir === 'asc' ? (av as number) - (bv as number) : (bv as number) - (av as number)
    })
  }, [data, sortField, sortDir])

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6 max-w-6xl mx-auto w-full">
      {/* Breadcrumb + title */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate('/partner')}
          className="p-1.5 rounded-lg hover:bg-surface-700 transition-colors text-slate-400 hover:text-white"
        >
          <ArrowLeft size={18} />
        </button>
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <BarChart3 size={20} className="text-brand-400" />
            Consolidated Report
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">Unified view across all managed clients</p>
        </div>
      </div>

      {loading && (
        <div className="flex-1 flex items-center justify-center py-20">
          <Loader2 size={24} className="animate-spin text-brand-400" />
        </div>
      )}

      {!loading && !canAccess && <UpgradePrompt />}

      {!loading && canAccess && data && (
        <>
          {/* KPI strip */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <KpiTile
              label="Total Clients"
              value={data.totals.client_count}
              icon={Users}
            />
            <KpiTile
              label="Revenue This Month"
              value={fmtMoney(data.totals.total_revenue)}
              icon={TrendingUp}
              accent="text-green-400"
            />
            <KpiTile
              label="Outstanding Balance"
              value={fmtMoney(data.totals.total_outstanding)}
              icon={DollarSign}
              accent={data.totals.total_outstanding > 0 ? 'text-red-400' : 'text-white'}
            />
            <KpiTile
              label="Total Customers"
              value={data.totals.total_customers}
              icon={Users}
            />
          </div>

          {/* Table card */}
          <div className="card overflow-hidden p-0">
            <div className="flex items-center justify-between px-4 py-3 border-b border-surface-700">
              <h2 className="text-sm font-semibold text-white">Client Breakdown</h2>
              <button
                onClick={() => exportCSV(sorted)}
                className="btn-ghost text-xs flex items-center gap-1.5 text-brand-400 hover:text-brand-300"
              >
                <Download size={14} />
                Export CSV
              </button>
            </div>

            {sorted.length === 0 ? (
              <div className="py-12 text-center">
                <AlertCircle size={32} className="mx-auto text-slate-600 mb-2" />
                <p className="text-sm text-slate-500">No client data available yet.</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-surface-800/60">
                    <tr>
                      <th className="px-4 py-2.5 text-xs font-semibold text-slate-400 uppercase tracking-wide text-left cursor-pointer select-none hover:text-white transition-colors"
                        onClick={() => handleSort('org_name')}>
                        <span className="inline-flex items-center gap-1">
                          Organisation
                          {sortField === 'org_name'
                            ? (sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />)
                            : <ChevronDown size={12} className="opacity-30" />}
                        </span>
                      </th>
                      <th className="px-4 py-2.5 text-xs font-semibold text-slate-400 uppercase tracking-wide text-left">Plan</th>
                      <SortTh field="revenue_this_month" label="Revenue" current={sortField} dir={sortDir} onSort={handleSort} />
                      <SortTh field="outstanding_balance" label="Outstanding" current={sortField} dir={sortDir} onSort={handleSort} />
                      <SortTh field="overdue_count" label="Overdue" current={sortField} dir={sortDir} onSort={handleSort} />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-700/50">
                    {sorted.map((c) => (
                      <tr key={c.link_id} className="hover:bg-surface-700/30 transition-colors">
                        <td className="px-4 py-3 font-medium text-white">{c.org_name}</td>
                        <td className="px-4 py-3 text-slate-400 capitalize text-xs">{c.plan}</td>
                        <td className="px-4 py-3 text-right text-green-400 font-mono text-xs">{fmtMoney(c.revenue_this_month)}</td>
                        <td className={`px-4 py-3 text-right font-mono text-xs ${c.outstanding_balance > 0 ? 'text-red-400' : 'text-slate-400'}`}>
                          {fmtMoney(c.outstanding_balance)}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {c.overdue_count > 0
                            ? <span className="badge-red text-xs">{c.overdue_count}</span>
                            : <span className="text-slate-500 text-xs">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
