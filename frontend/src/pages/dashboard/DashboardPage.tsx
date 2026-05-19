import { useEffect, useMemo, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { useNavigate } from 'react-router-dom'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import {
  TrendingUp, TrendingDown, Package,
  AlertTriangle, DollarSign, Zap, ArrowUpRight, ShoppingCart, Clock, Sparkles, RefreshCw,
} from 'lucide-react'
import { reportApi, inventoryApi, salesApi, einvoicingApi } from '@/services/api'
import type { FirsStats } from '@/types'
import { offlineCache } from '@/lib/offlineCache'
import { formatCurrency, getCurrencySymbol } from '@/lib/utils'
import { format, subDays, subMonths, subYears, startOfYear } from 'date-fns'
import AIChatModal from '@/components/AIChatModal'

// ─── Period options ─────────────────────────────────────────────────────────
type PeriodKey = 'today' | '7d' | '14d' | '30d' | '60d' | '90d' | '6m' | '1y' | 'ytd'

const PERIODS: { key: PeriodKey; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: '7d',   label: '7 Days' },
  { key: '14d',  label: '14 Days' },
  { key: '30d',  label: '30 Days' },
  { key: '60d',  label: '60 Days' },
  { key: '90d',  label: '90 Days' },
  { key: '6m',   label: '6 Months' },
  { key: '1y',   label: '1 Year' },
  { key: 'ytd',  label: 'Year to Date' },
]

function getDateRange(key: PeriodKey): { dateFrom: string; dateTo: string } {
  const now = new Date()
  const fmt = (d: Date) => format(d, 'yyyy-MM-dd')
  const today = fmt(now)
  switch (key) {
    case 'today': return { dateFrom: today, dateTo: today }
    case '7d':    return { dateFrom: fmt(subDays(now, 7)),       dateTo: today }
    case '14d':   return { dateFrom: fmt(subDays(now, 14)),      dateTo: today }
    case '30d':   return { dateFrom: fmt(subDays(now, 30)),      dateTo: today }
    case '60d':   return { dateFrom: fmt(subDays(now, 60)),      dateTo: today }
    case '90d':   return { dateFrom: fmt(subDays(now, 90)),      dateTo: today }
    case '6m':    return { dateFrom: fmt(subMonths(now, 6)),     dateTo: today }
    case '1y':    return { dateFrom: fmt(subYears(now, 1)),      dateTo: today }
    case 'ytd':   return { dateFrom: fmt(startOfYear(now)),      dateTo: today }
  }
}

// ─── StatCard ────────────────────────────────────────────────────────────────
function StatCard({
  label, value, sub, icon: Icon, trend, trendValue, color = 'orange', onClick,
}: {
  label: string; value: string; sub?: string; icon: React.ElementType
  trend?: 'up' | 'down'; trendValue?: string
  color?: 'orange' | 'green' | 'blue' | 'red'; onClick?: () => void
}) {
  const colorMap = {
    orange: 'text-brand-400 bg-brand-500/15 border-brand-500/30',
    green:  'text-green-400 bg-green-500/15 border-green-500/30',
    blue:   'text-blue-400 bg-blue-500/15 border-blue-500/30',
    red:    'text-red-400 bg-red-500/15 border-red-500/30',
  }
  return (
    <div
      className={`stat-card animate-slide-up ${onClick ? 'cursor-pointer hover:border-brand-500/50 transition-colors' : ''}`}
      onClick={onClick}
    >
      <div className="flex items-start justify-between">
        <div className={`p-2.5 rounded-xl border ${colorMap[color]}`}>
          <Icon size={20} />
        </div>
        {trend && trendValue && (
          <div className={`flex items-center gap-1 text-xs font-medium ${trend === 'up' ? 'text-green-400' : 'text-red-400'}`}>
            {trend === 'up' ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
            {trendValue}
          </div>
        )}
        {onClick && !trend && <ArrowUpRight size={14} className="text-slate-600" />}
      </div>
      <div>
        <p className="text-2xl font-bold text-white">{value}</p>
        <p className="text-sm text-slate-400 mt-0.5">{label}</p>
        {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function DashboardPage() {
  const navigate = useNavigate()
  const [period, setPeriod] = useState<PeriodKey>('30d')
  const [pnl, setPnl] = useState<any>(null)
  const [salesData, setSalesData] = useState<any[]>([])
  const [topProducts, setTopProducts] = useState<any[]>([])
  const [lowStock, setLowStock] = useState<any[]>([])
  const [lowStockTotal, setLowStockTotal] = useState(0)
  const [overdueInvoices, setOverdueInvoices] = useState<any[]>([])
  const [overdueTotal, setOverdueTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [showAI, setShowAI] = useState(false)
  const [_refreshTick, setRefreshTick] = useState(0)
  // FIRS compliance banner state — fetched once on mount, non-blocking
  const [firsStats, setFirsStats] = useState<FirsStats | null>(null)
  useDataRefresh(() => setRefreshTick((t) => t + 1))

  const { dateFrom, dateTo } = useMemo(() => getDateRange(period), [period])
  const periodLabel = PERIODS.find((p) => p.key === period)?.label ?? ''

  useEffect(() => {
    setLoading(true)
    const fetchAll = async () => {
      const [pnlRes, salesRes, topProdRes, stockRes, overdueRes] = await Promise.allSettled([
        reportApi.pnl({ date_from: dateFrom, date_to: dateTo }),
        reportApi.sales({ date_from: dateFrom, date_to: dateTo, group_by: 'day' }),
        reportApi.topProducts({ date_from: dateFrom, date_to: dateTo, limit: 5 }),
        inventoryApi.stock(),
        salesApi.invoices({ status: 'overdue', page_size: 5 }),
      ])

      if (pnlRes.status === 'fulfilled') setPnl(pnlRes.value.data)

      if (salesRes.status === 'fulfilled') {
        const d = salesRes.value.data
        setSalesData(Array.isArray(d) ? d : (d.results ?? []))
      }

      if (topProdRes.status === 'fulfilled') {
        const d = topProdRes.value.data
        setTopProducts(Array.isArray(d) ? d : (d.results ?? []))
      }

      if (stockRes.status === 'fulfilled') {
        const d = stockRes.value.data
        const allItems: any[] = Array.isArray(d) ? d : (d.results ?? [])
        const lowItems = allItems.filter((i: any) => i.stock_level === 'low' || i.is_low_stock)
        setLowStockTotal(lowItems.length)
        setLowStock(lowItems.slice(0, 5))
      }

      if (overdueRes.status === 'fulfilled') {
        const d = overdueRes.value.data
        const items: any[] = Array.isArray(d) ? d : (d.results ?? [])
        const total = Array.isArray(d) ? d.length : (d.count ?? items.length)
        setOverdueTotal(total)
        setOverdueInvoices(items.slice(0, 5))
      }

      setLoading(false)
    }
    fetchAll()

    // Refresh low stock every 60s
    const interval = setInterval(async () => {
      try {
        const res = await inventoryApi.stock()
        const d = res.data
        const allItems: any[] = Array.isArray(d) ? d : (d.results ?? [])
        const lowItems = allItems.filter((i: any) => i.stock_level === 'low' || i.is_low_stock)
        setLowStockTotal(lowItems.length)
        setLowStock(lowItems.slice(0, 5))
      } catch { /* silent */ }
    }, 60000)

    return () => clearInterval(interval)
  }, [dateFrom, dateTo, _refreshTick])

  // Fetch FIRS stats once on mount (independent of period changes)
  useEffect(() => {
    einvoicingApi.stats().then(({ data }) => setFirsStats(data)).catch(() => null)
  }, [])

  const chartData = salesData.map((d) => ({
    date: format(new Date(d.period), period === 'today' ? 'HH:mm' : 'MMM d'),
    revenue: parseFloat(d.total_revenue),
    invoices: d.invoice_count,
  }))

  const totalOrders = salesData.reduce((sum, d) => sum + (d.invoice_count ?? 0), 0)

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="text-slate-400 text-sm mt-0.5">
            {format(new Date(), 'EEEE, MMMM d yyyy')}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value as PeriodKey)}
            className="input text-sm py-1.5 w-auto"
          >
            {PERIODS.map(({ key, label }) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
          <button
            onClick={() => setShowAI(true)}
            className="flex items-center gap-2 px-3 py-2 bg-brand-500/15 border border-brand-500/30 hover:bg-brand-500/25 rounded-xl transition-colors"
            title="Ask Audity AI about your finances"
          >
            <Sparkles size={14} className="text-brand-400" />
            <span className="text-xs text-brand-400 font-medium hidden sm:inline">Explain My Money</span>
          </button>
          <button
            onClick={async () => {
              // Wipe stale membership/org cache so the retry hits the network
              await Promise.allSettled([
                offlineCache.invalidatePrefix('/tenancy/organisations/my_membership/'),
                offlineCache.invalidatePrefix('/tenancy/memberships/'),
                offlineCache.invalidatePrefix('/tenancy/organisations/'),
                offlineCache.invalidatePrefix('/subscriptions/current/'),
              ])
              setRefreshTick((t) => t + 1)
              // Tell AppLayout to re-run its org/membership/plan effects
              window.dispatchEvent(new CustomEvent('audity:app-refresh'))
              // Tell all pages to reload their data
              window.dispatchEvent(new CustomEvent('audity:data-changed'))
            }}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 bg-surface-800 border border-surface-700 hover:border-slate-500 rounded-xl transition-colors"
            title="Refresh all data"
          >
            <RefreshCw size={14} className={`text-slate-400 ${loading ? 'animate-spin' : ''}`} />
            <span className="text-xs text-slate-400 font-medium hidden sm:inline">Refresh</span>
          </button>
          <div className="flex items-center gap-2 px-3 py-2 bg-green-500/10 border border-green-500/30 rounded-xl">
            <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
            <span className="text-xs text-green-400 font-medium">Live</span>
          </div>
        </div>
      </div>

      <AIChatModal open={showAI} onClose={() => setShowAI(false)} />

      {/* ── FIRS compliance banner ───────────────────────────────────────────
          Shown only to enrolled orgs. Three states:
            • failed > 0  → red warning (submissions need attention)
            • sandbox mode → amber nudge (remind to switch to production)
            • all clear    → subtle green confirmation (collapsed after first view)
      */}
      {firsStats?.is_enrolled && firsStats.failed > 0 && (
        <div
          onClick={() => navigate('/settings?tab=firs')}
          className="flex items-center gap-3 p-4 bg-red-500/10 border border-red-500/30 rounded-xl cursor-pointer hover:bg-red-500/15 transition-colors"
        >
          <AlertTriangle size={16} className="text-red-400 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-white">
              {firsStats.failed} FIRS submission{firsStats.failed !== 1 ? 's' : ''} failed
            </p>
            <p className="text-xs text-slate-400">
              Click to open the FIRS settings and retry failed submissions.
            </p>
          </div>
          <span className="text-xs text-red-400 font-medium whitespace-nowrap">Fix now →</span>
        </div>
      )}
      {firsStats?.is_enrolled && firsStats.failed === 0 && firsStats.use_sandbox && (
        <div
          onClick={() => navigate('/settings?tab=firs')}
          className="flex items-center gap-3 p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl cursor-pointer hover:bg-amber-500/15 transition-colors"
        >
          <AlertTriangle size={16} className="text-amber-400 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-white">FIRS e-invoicing is in sandbox mode</p>
            <p className="text-xs text-slate-400">
              Submissions are going to DigiTax sandbox. Switch to production when ready to go live.
            </p>
          </div>
          <span className="text-xs text-amber-400 font-medium whitespace-nowrap">Configure →</span>
        </div>
      )}

      {/* KPI Row 1 — Financial */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label={`Total Revenue · ${periodLabel}`}
          value={loading ? '—' : formatCurrency(pnl?.revenue?.gross_sales ?? 0)}
          sub={loading ? 'Loading…' : undefined}
          icon={DollarSign}
          color="orange"
          onClick={() => navigate('/reports')}
        />
        <StatCard
          label={`Gross Profit · ${periodLabel}`}
          value={loading ? '—' : formatCurrency(pnl?.gross_profit ?? 0)}
          sub={loading ? undefined : pnl ? `${pnl.gross_margin_pct}% margin` : 'No data yet'}
          icon={TrendingUp}
          color="green"
          onClick={() => navigate('/reports')}
        />
        <StatCard
          label={`Net Profit · ${periodLabel}`}
          value={loading ? '—' : formatCurrency(pnl?.net_profit ?? 0)}
          sub={loading ? undefined : pnl ? `${pnl.net_margin_pct}% net margin` : 'No data yet'}
          icon={Zap}
          color="blue"
          onClick={() => navigate('/reports')}
        />
      </div>

      {/* KPI Row 2 — Operational */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label={`Total Orders · ${periodLabel}`}
          value={loading ? '—' : String(totalOrders)}
          sub="Invoices issued"
          icon={ShoppingCart}
          color="orange"
          onClick={() => navigate('/sales')}
        />
        <StatCard
          label="Low Stock Alerts"
          value={String(lowStockTotal)}
          sub="Items below reorder level"
          icon={AlertTriangle}
          color="red"
          onClick={() => navigate('/inventory/stock?filter=low')}
        />
        <StatCard
          label="Overdue Invoices"
          value={String(overdueTotal)}
          sub="Pending payment"
          icon={Clock}
          color="red"
          onClick={() => navigate('/sales?status=overdue')}
        />
      </div>

      {/* Revenue Trend — full width */}
      <div className="card">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="font-semibold text-white">Revenue Trend</h2>
            <p className="text-sm text-slate-400">{periodLabel}</p>
          </div>
          <button onClick={() => navigate('/reports')} className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1">
            Full Report <ArrowUpRight size={12} />
          </button>
        </div>
        {loading ? (
          <div className="h-56 flex items-center justify-center">
            <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : chartData.length === 0 ? (
          <div className="h-56 flex flex-col items-center justify-center text-slate-500">
            <TrendingUp size={28} className="mb-2 opacity-30" />
            <p className="text-sm">No revenue data for this period</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f97316" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#f97316" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false}
                tickFormatter={(v) => `${getCurrencySymbol()}${(v / 1000).toFixed(0)}k`} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '12px', fontSize: '13px' }}
                labelStyle={{ color: '#94a3b8' }}
                formatter={(v: number) => [formatCurrency(v), 'Revenue']}
              />
              <Area type="monotone" dataKey="revenue" stroke="#f97316" strokeWidth={2}
                fill="url(#grad)" dot={false} activeDot={{ r: 4, fill: '#f97316' }} />
            </AreaChart>
          </ResponsiveContainer>
        )}

        {/* Top Products directly below the chart */}
        {topProducts.length > 0 && (
          <div className="mt-6 pt-5 border-t border-surface-700">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-white">Top Products · {periodLabel}</h3>
              <button onClick={() => navigate('/inventory/products')} className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1">
                View all <ArrowUpRight size={12} />
              </button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {topProducts.slice(0, 6).map((p, i) => (
                <div key={i} className="flex items-center gap-3 p-3 rounded-xl bg-surface-800">
                  <span className="w-6 h-6 bg-surface-700 rounded-lg flex items-center justify-center text-xs font-mono text-slate-400 shrink-0">
                    {i + 1}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-white truncate">{p.product_name}</p>
                    <p className="text-xs text-slate-500">{parseFloat(p.units_sold ?? 0).toFixed(0)} units</p>
                  </div>
                  <p className="text-xs font-semibold text-brand-400 shrink-0">{formatCurrency(p.revenue)}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Bottom row — Overdue Invoices + Low Stock side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Overdue Invoices */}
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-white flex items-center gap-2">
              <Clock size={16} className="text-red-400" /> Overdue Invoices
            </h2>
            <button onClick={() => navigate('/sales?status=overdue')} className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1">
              View all <ArrowUpRight size={12} />
            </button>
          </div>
          {overdueInvoices.length === 0 ? (
            <div className="flex flex-col items-center py-8 text-slate-500">
              <Clock size={32} className="mb-2 text-green-400 opacity-50" />
              <p className="text-sm">No overdue invoices</p>
            </div>
          ) : (
            <div className="space-y-2">
              {overdueInvoices.map((inv, i) => (
                <button
                  key={i}
                  onClick={() => navigate('/sales?status=overdue')}
                  className="w-full flex items-center gap-3 p-3 rounded-xl bg-surface-800 hover:bg-surface-700 transition-colors text-left"
                >
                  <div className="w-2 h-2 bg-red-400 rounded-full animate-pulse shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-white truncate">
                      {inv.invoice_number} · {inv.customer_name ?? 'Walk-in'}
                    </p>
                    <p className="text-xs text-slate-500">Due {inv.due_date}</p>
                  </div>
                  <span className="badge-red shrink-0">{formatCurrency(inv.amount_due ?? inv.total_amount)}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Low Stock Alerts */}
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-white flex items-center gap-2">
              <AlertTriangle size={16} className="text-red-400" /> Low Stock Alerts
            </h2>
            <button onClick={() => navigate('/inventory/stock?filter=low')} className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1">
              View all <ArrowUpRight size={12} />
            </button>
          </div>
          {lowStock.length === 0 ? (
            <div className="flex flex-col items-center py-8 text-slate-500">
              <Package size={32} className="mb-2 text-green-400 opacity-50" />
              <p className="text-sm">All stock levels are healthy</p>
            </div>
          ) : (
            <div className="space-y-2">
              {lowStock.map((s, i) => (
                <button
                  key={i}
                  onClick={() => navigate('/inventory/stock?filter=low')}
                  className="w-full flex items-center gap-3 p-3 rounded-xl bg-surface-800 hover:bg-surface-700 transition-colors text-left"
                >
                  <div className="w-2 h-2 bg-red-400 rounded-full animate-pulse shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-white truncate">{s.product_name}</p>
                    <p className="text-xs text-slate-500">{s.warehouse_name}</p>
                  </div>
                  <span className="badge-red shrink-0">{s.quantity_on_hand} left</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
