import { useEffect, useState } from 'react'
import { Loader2, ShieldCheck, TrendingUp, TrendingDown, DollarSign, BarChart3 } from 'lucide-react'
import toast from 'react-hot-toast'
import { salesApi } from '@/services/api'
import { formatCurrency } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import { useNavigate } from 'react-router-dom'
import type { OwnerAnalytics } from '@/types'

const PERIODS = [
  { value: 'today', label: 'Today' },
  { value: 'week', label: 'Last 7 days' },
  { value: 'month', label: 'Last 30 days' },
  { value: 'year', label: 'Last 12 months' },
  { value: 'all', label: 'All time' },
]

function MetricCard({ label, value, sub, color = 'white' }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="card p-5">
      <p className="text-xs text-slate-400 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color === 'green' ? 'text-emerald-400' : color === 'orange' ? 'text-orange-400' : color === 'brand' ? 'text-brand-400' : 'text-white'}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </div>
  )
}

export default function OwnerAnalyticsPage() {
  const { user, memberRole, planModules } = useAuthStore()
  const navigate = useNavigate()
  const isOwner = memberRole === 'owner' || memberRole === 'admin' || user?.is_superuser === true
  const hasAccess = isOwner && (planModules === null || planModules.includes('owner_analytics') || !!user?.is_superuser)

  const [period, setPeriod] = useState('month')
  const [data, setData] = useState<OwnerAnalytics | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!hasAccess) { navigate('/billing'); return }
    setLoading(true)
    salesApi.ownerAnalytics(period)
      .then(({ data: d }) => setData(d))
      .catch(() => toast.error('Failed to load owner analytics'))
      .finally(() => setLoading(false))
  }, [period, hasAccess, navigate])

  if (!hasAccess) return null

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-brand-500/15 flex items-center justify-center">
            <ShieldCheck size={20} className="text-brand-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Owner Analytics</h1>
            <p className="text-slate-400 text-sm">Private profit view — visible to owners only</p>
          </div>
        </div>
        <select
          className="input w-auto sm:ml-auto text-sm"
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
        >
          {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
      </div>

      {loading ? (
        <div className="card p-16 flex justify-center"><Loader2 size={28} className="animate-spin text-brand-400" /></div>
      ) : !data ? null : (
        <>
          {/* KPI cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard label="Total Revenue" value={formatCurrency(data.total_revenue)} color="brand" />
            <MetricCard
              label="Company Gross Profit"
              value={formatCurrency(data.company_gross_profit)}
              sub={`${data.company_margin_pct}% margin (cost price)`}
              color={parseFloat(data.company_gross_profit) >= 0 ? 'green' : 'white'}
            />
            <MetricCard
              label="Owner Gross Profit"
              value={formatCurrency(data.owner_gross_profit)}
              sub={`${data.owner_margin_pct}% margin (owner cost)`}
              color={parseFloat(data.owner_gross_profit) >= 0 ? 'green' : 'white'}
            />
            <MetricCard
              label="Margin Uplift"
              value={`${(parseFloat(data.owner_margin_pct) - parseFloat(data.company_margin_pct)).toFixed(1)}%`}
              sub="Owner margin vs company margin"
              color="orange"
            />
          </div>

          {/* COGS comparison */}
          <div className="card p-5">
            <h2 className="text-base font-semibold text-white mb-4 flex items-center gap-2">
              <DollarSign size={16} className="text-brand-400" /> Cost Comparison
            </h2>
            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 rounded-xl bg-surface-700/40 border border-surface-700">
                <p className="text-xs text-slate-400 mb-1">Company COGS</p>
                <p className="text-xl font-bold text-white">{formatCurrency(data.company_cogs)}</p>
                <p className="text-xs text-slate-500 mt-0.5">Cost price × units sold</p>
              </div>
              <div className="p-4 rounded-xl bg-brand-500/5 border border-brand-500/20">
                <p className="text-xs text-brand-400 mb-1 flex items-center gap-1"><ShieldCheck size={11} /> Owner COGS</p>
                <p className="text-xl font-bold text-brand-400">{formatCurrency(data.owner_cogs)}</p>
                <p className="text-xs text-slate-500 mt-0.5">Owner cost price × units sold</p>
              </div>
            </div>
            {parseFloat(data.owner_cogs) > 0 && (
              <div className="mt-3 p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
                <p className="text-xs text-emerald-400">
                  Owner's additional margin vs company cost:{' '}
                  <span className="font-bold">{formatCurrency(String(parseFloat(data.company_cogs) - parseFloat(data.owner_cogs)))}</span>
                </p>
              </div>
            )}
          </div>

          {/* Top products by owner profit */}
          {data.top_products.length > 0 && (
            <div className="card p-5">
              <h2 className="text-base font-semibold text-white mb-4 flex items-center gap-2">
                <BarChart3 size={16} className="text-brand-400" /> Top Products — Owner Profit
              </h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-700">
                      {['Product', 'Revenue', 'Company GP', 'Owner GP'].map((h) => (
                        <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.top_products.map((p, i) => {
                      const ownerGP = parseFloat(p.owner_gross)
                      const companyGP = parseFloat(p.company_gross)
                      return (
                        <tr key={i} className="table-row">
                          <td className="px-4 py-3 text-white font-medium">{p.product_name}</td>
                          <td className="px-4 py-3 font-mono text-slate-300">{formatCurrency(p.revenue)}</td>
                          <td className="px-4 py-3 font-mono">
                            <span className={companyGP >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                              {formatCurrency(p.company_gross)}
                            </span>
                          </td>
                          <td className="px-4 py-3 font-mono">
                            <div className="flex items-center gap-1.5">
                              {ownerGP >= 0
                                ? <TrendingUp size={13} className="text-brand-400 shrink-0" />
                                : <TrendingDown size={13} className="text-red-400 shrink-0" />}
                              <span className={ownerGP >= 0 ? 'text-brand-400 font-semibold' : 'text-red-400'}>
                                {formatCurrency(p.owner_gross)}
                              </span>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
