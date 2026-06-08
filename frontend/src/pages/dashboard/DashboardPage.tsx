/**
 * DashboardPage — Executive command centre.
 *
 * Architecture:
 *  • Four financial KPI cards  (Revenue, Gross Profit, Net Profit, Orders)
 *  • Financial Health Ratio strip  (DSO, DPO, Gross Margin, Net Margin,
 *                                   Customer Concentration)
 *  • Revenue Trend area chart  with prior-period comparison overlay
 *  • Report Shortcuts panel   (4 mini-charts that deep-link to Reports module)
 *  • Recent Invoices + Quick Actions
 *  • Merged Alerts panel      (Overdue Invoices + Low Stock in one banner)
 *
 * Phase 1A: removed duplicate Low Stock / Overdue KPI tiles — data still
 *           surfaces in the Alerts panel below.
 * Phase 1B: Financial Health Ratio strip computes DSO, DPO, and margins
 *           from AR/AP aging + P&L data already fetched.
 * Phase 1C: Sparklines inside KPI cards + prior-period line on revenue chart.
 * Phase 1D: Report Shortcuts panel with 4 mini Recharts visualisations.
 */

import { useEffect, useMemo, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { useNavigate } from 'react-router-dom'
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import {
  TrendingUp, TrendingDown, Package, AlertTriangle, DollarSign,
  Zap, ArrowUpRight, ShoppingCart, Clock, Sparkles, RefreshCw,
  Upload, Receipt, UserPlus, Plus, Scale, Wallet, FileText,
  BarChart2, Activity,
} from 'lucide-react'
import { reportApi, inventoryApi, salesApi, einvoicingApi } from '@/services/api'
import type { FirsStats } from '@/types'
import { offlineCache } from '@/lib/offlineCache'
import { formatCurrency, getCurrencySymbol } from '@/lib/utils'
import {
  format, subDays, subMonths, subYears, startOfYear, differenceInDays,
} from 'date-fns'
import AIChatModal from '@/components/AIChatModal'
import { useThemeAccent } from '@/hooks/useTheme'

// ─── Period helpers ────────────────────────────────────────────────────────────

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
    case '7d':    return { dateFrom: fmt(subDays(now, 7)),    dateTo: today }
    case '14d':   return { dateFrom: fmt(subDays(now, 14)),   dateTo: today }
    case '30d':   return { dateFrom: fmt(subDays(now, 30)),   dateTo: today }
    case '60d':   return { dateFrom: fmt(subDays(now, 60)),   dateTo: today }
    case '90d':   return { dateFrom: fmt(subDays(now, 90)),   dateTo: today }
    case '6m':    return { dateFrom: fmt(subMonths(now, 6)),  dateTo: today }
    case '1y':    return { dateFrom: fmt(subYears(now, 1)),   dateTo: today }
    case 'ytd':   return { dateFrom: fmt(startOfYear(now)),   dateTo: today }
  }
}

/**
 * Shift a date range backwards by its own length to produce the "prior period".
 * e.g. "last 30 days" → the 30 days before that.
 */
function getPriorDateRange(dateFrom: string, dateTo: string) {
  const from = new Date(dateFrom)
  const to   = new Date(dateTo)
  const span = Math.max(1, differenceInDays(to, from))
  const priorTo   = format(subDays(from, 1), 'yyyy-MM-dd')
  const priorFrom = format(subDays(from, span), 'yyyy-MM-dd')
  return { priorFrom, priorTo }
}

// ─── KPI card with optional sparkline ────────────────────────────────────────

function StatCard({
  label, value, sub, icon: Icon, trend, trendValue,
  color = 'orange', onClick, sparkData,
}: {
  label: string; value: string; sub?: string; icon: React.ElementType
  trend?: 'up' | 'down'; trendValue?: string
  color?: 'orange' | 'green' | 'blue' | 'red'
  onClick?: () => void
  /** Optional 7-point mini trend line rendered inside the card */
  sparkData?: number[]
}) {
  const accent = useThemeAccent()
  const colorMap = {
    orange: { icon: 'text-brand-400 bg-brand-500/15 border-brand-500/30', spark: accent },
    green:  { icon: 'text-green-400 bg-green-500/15 border-green-500/30',  spark: '#10b981' },
    blue:   { icon: 'text-blue-400 bg-blue-500/15 border-blue-500/30',    spark: '#3b82f6' },
    red:    { icon: 'text-red-400 bg-red-500/15 border-red-500/30',       spark: '#ef4444' },
  }
  const sparkPoints = sparkData?.map((v, i) => ({ v, i })) ?? []

  return (
    <div
      className={`stat-card animate-slide-up ${onClick ? 'cursor-pointer hover:border-brand-500/50 transition-colors' : ''}`}
      onClick={onClick}
    >
      <div className="flex items-start justify-between">
        <div className={`p-2.5 rounded-xl border ${colorMap[color].icon}`}>
          <Icon size={20} />
        </div>
        {/* Phase 1C: trend badge */}
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

      {/* Phase 1C: sparkline — tiny inline line chart without axes */}
      {sparkPoints.length >= 3 && (
        <div className="h-8 mt-1 -mx-1">
          <ResponsiveContainer width="100%" height={32}>
            <LineChart data={sparkPoints}>
              <Line
                type="monotone" dataKey="v" dot={false}
                stroke={colorMap[color].spark} strokeWidth={1.5}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}

// ─── Invoice status badge ─────────────────────────────────────────────────────

function invoiceStatusBadge(status: string): { cls: string; label: string } {
  const s = (status || '').toLowerCase()
  if (s === 'paid')                            return { cls: 'badge-green',  label: 'Paid' }
  if (s === 'overdue')                         return { cls: 'badge-red',    label: 'Overdue' }
  if (s === 'partial' || s === 'partially_paid') return { cls: 'badge-yellow', label: 'Partial' }
  if (s === 'draft')                           return { cls: 'badge-slate',  label: 'Draft' }
  if (s === 'proforma')                        return { cls: 'badge-blue',   label: 'Proforma' }
  if (s === 'cancelled' || s === 'void')       return { cls: 'badge-slate',  label: 'Cancelled' }
  return { cls: 'badge-yellow', label: s ? s.charAt(0).toUpperCase() + s.slice(1) : 'Pending' }
}

// ─── Phase 1B — Financial Health Ratio strip ─────────────────────────────────

/**
 * Displays five read-only financial health indicators computed from existing
 * dashboard data.  Thresholds use broad SME benchmarks; colour is indicative
 * only — always validate against your industry.
 */
function HealthRatioStrip({
  pnl, arAging, apAging, topCustomers, periodDays,
}: {
  pnl: any
  arAging: any
  apAging: any
  topCustomers: any[]
  periodDays: number
}) {
  if (!pnl) return null

  const revenue = parseFloat(pnl.revenue?.gross_sales ?? 0)
  const cogs    = parseFloat(pnl.cost_of_goods_sold ?? 0)
  const arTotal = parseFloat(arAging?.total_outstanding ?? 0)
  const apTotal = parseFloat(apAging?.total_outstanding ?? 0)

  // Days Sales Outstanding: avg days to collect receivables
  const dso = revenue > 0 ? Math.round((arTotal / (revenue / Math.max(1, periodDays))) ) : null

  // Days Payable Outstanding: avg days to pay suppliers
  const dpo = cogs > 0 ? Math.round((apTotal / (cogs / Math.max(1, periodDays)))) : null

  // Gross and net margin percentages directly from P&L
  const gm = parseFloat(pnl.gross_margin_pct ?? 0)
  const nm = parseFloat(pnl.net_margin_pct ?? 0)

  // Customer concentration: top-3 revenue as % of total
  const top3Revenue = topCustomers.slice(0, 3).reduce((s: number, c: any) => s + parseFloat(c.revenue ?? 0), 0)
  const concentration = revenue > 0 ? Math.round((top3Revenue / revenue) * 100) : null

  const ratios: {
    label: string; value: string; note: string
    status: 'good' | 'warn' | 'bad' | 'neutral'
  }[] = [
    {
      label: 'DSO',
      value: dso != null ? `${dso}d` : '—',
      note: 'Days to collect AR',
      // < 30 days is healthy for most SMEs
      status: dso == null ? 'neutral' : dso <= 30 ? 'good' : dso <= 60 ? 'warn' : 'bad',
    },
    {
      label: 'DPO',
      value: dpo != null ? `${dpo}d` : '—',
      note: 'Days to pay suppliers',
      // Higher DPO means more cash in hand; > 60 may strain suppliers
      status: dpo == null ? 'neutral' : dpo <= 45 ? 'good' : dpo <= 75 ? 'warn' : 'bad',
    },
    {
      label: 'Gross Margin',
      value: `${gm.toFixed(1)}%`,
      note: '% revenue after COGS',
      status: gm >= 25 ? 'good' : gm >= 15 ? 'warn' : 'bad',
    },
    {
      label: 'Net Margin',
      value: `${nm.toFixed(1)}%`,
      note: '% revenue kept as profit',
      status: nm >= 10 ? 'good' : nm >= 5 ? 'warn' : 'bad',
    },
    {
      label: 'Cust. Concentration',
      value: concentration != null ? `Top 3 = ${concentration}%` : '—',
      note: 'Revenue from top 3 customers',
      // > 50 % in top 3 = concentration risk
      status: concentration == null ? 'neutral' : concentration <= 40 ? 'good' : concentration <= 60 ? 'warn' : 'bad',
    },
  ]

  const statusColor = {
    good:    'text-emerald-400',
    warn:    'text-amber-400',
    bad:     'text-red-400',
    neutral: 'text-slate-400',
  }
  // Each ratio card gets its own identity tint so no two cards ever share a
  // colour (Gross Margin vs Net Margin in particular). Financial health is
  // still conveyed by the status-coloured value below, not the card background.
  const cardTheme = [
    'bg-blue-500/10 border-blue-500/20',     // DSO
    'bg-violet-500/10 border-violet-500/20', // DPO
    'bg-teal-500/10 border-teal-500/20',     // Gross Margin
    'bg-pink-500/10 border-pink-500/20',     // Net Margin
    'bg-cyan-500/10 border-cyan-500/20',     // Cust. Concentration
  ]

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      {ratios.map((r, i) => (
        <div key={r.label} className={`rounded-xl border p-3 ${cardTheme[i % cardTheme.length]}`}>
          <p className="text-xs text-slate-500 mb-1 leading-tight">{r.label}</p>
          <p className={`text-lg font-bold tabular-nums ${statusColor[r.status]}`}>{r.value}</p>
          <p className="text-[10px] text-slate-500 mt-0.5 leading-snug">{r.note}</p>
        </div>
      ))}
    </div>
  )
}

// ─── Phase 1D — Report Shortcuts mini charts ──────────────────────────────────

/**
 * Four mini-chart cards that give a 5-second preview of key reports and deep-
 * link to the full Reports module.  All data comes from props already fetched
 * by the parent — no extra API calls.
 */
function ReportShortcuts({
  pnl, arAging, topProducts, expenses, accent,
}: {
  pnl: any; arAging: any; topProducts: any[]; expenses: any[]; accent: string
}) {
  const navigate = useNavigate()
  const COLORS   = [accent, '#3b82f6', '#10b981', '#a855f7', '#f59e0b']

  // P&L waterfall data: Revenue → Gross Profit → Net Profit
  const pnlBars = pnl ? [
    { name: 'Revenue',      value: parseFloat(pnl.revenue?.gross_sales ?? 0) },
    { name: 'Gross Profit', value: parseFloat(pnl.gross_profit ?? 0) },
    { name: 'Net Profit',   value: parseFloat(pnl.net_profit ?? 0) },
  ] : []

  // AR aging donut data (5 buckets)
  const agingDonut = arAging ? [
    { name: 'Current',  value: parseFloat(arAging.buckets?.current ?? 0) },
    { name: '1–30d',    value: parseFloat(arAging.buckets?.['1_30'] ?? 0) },
    { name: '31–60d',   value: parseFloat(arAging.buckets?.['31_60'] ?? 0) },
    { name: '61–90d',   value: parseFloat(arAging.buckets?.['61_90'] ?? 0) },
    { name: '90d+',     value: parseFloat(arAging.buckets?.over_90 ?? 0) },
  ].filter(b => b.value > 0) : []

  const AGING_COLORS = ['#10b981', '#f59e0b', '#f97316', '#ef4444', '#991b1b']

  // Top 5 products spark bars
  const prodBars = topProducts.slice(0, 5).map(p => ({
    name: (p.product_name ?? '').slice(0, 10),
    rev:  parseFloat(p.revenue ?? 0),
  }))

  // Expense donut
  const expDonut = expenses.slice(0, 5).map(e => ({
    name:  e.category_name ?? 'Other',
    value: parseFloat(e.total ?? 0),
  }))

  const tooltipStyle = {
    background: '#1e293b', border: '1px solid #334155',
    borderRadius: 8, fontSize: 11,
  }

  const cards = [
    {
      title: 'P&L Snapshot',
      sub: 'Revenue → Profit',
      icon: FileText,
      iconColor: 'text-brand-400',
      to: '/reports?tab=pnl',
      chart: pnlBars.length > 0 ? (
        <ResponsiveContainer width="100%" height={80}>
          <BarChart data={pnlBars} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <Bar dataKey="value" radius={[3, 3, 0, 0]}>
              {pnlBars.map((_, i) => (
                <Cell key={i} fill={i === 0 ? accent : i === 1 ? '#10b981' : '#3b82f6'} />
              ))}
            </Bar>
            <Tooltip
              contentStyle={tooltipStyle} labelStyle={{ color: '#94a3b8' }}
              formatter={(v: number) => formatCurrency(String(v))}
            />
          </BarChart>
        </ResponsiveContainer>
      ) : null,
    },
    {
      title: 'AR Aging',
      sub: 'Outstanding receivables',
      icon: Clock,
      iconColor: 'text-amber-400',
      to: '/reports?tab=aging',
      chart: agingDonut.length > 0 ? (
        <ResponsiveContainer width="100%" height={80}>
          <PieChart>
            <Pie data={agingDonut} cx="50%" cy="50%" innerRadius={20} outerRadius={36}
              paddingAngle={2} dataKey="value" startAngle={90} endAngle={-270}>
              {agingDonut.map((_, i) => (
                <Cell key={i} fill={AGING_COLORS[i % AGING_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={tooltipStyle} labelStyle={{ color: '#94a3b8' }}
              formatter={(v: number) => formatCurrency(String(v))}
            />
          </PieChart>
        </ResponsiveContainer>
      ) : null,
    },
    {
      title: 'Top Products',
      sub: 'Revenue by product',
      icon: Package,
      iconColor: 'text-emerald-400',
      to: '/reports?tab=sales_analytics',
      chart: prodBars.length > 0 ? (
        <ResponsiveContainer width="100%" height={80}>
          <BarChart data={prodBars} layout="vertical"
            margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <Bar dataKey="rev" fill="#10b981" radius={[0, 3, 3, 0]} />
            <Tooltip
              contentStyle={tooltipStyle} labelStyle={{ color: '#94a3b8' }}
              formatter={(v: number) => formatCurrency(String(v))}
            />
          </BarChart>
        </ResponsiveContainer>
      ) : null,
    },
    {
      title: 'Expense Mix',
      sub: 'Breakdown by category',
      icon: TrendingDown,
      iconColor: 'text-red-400',
      to: '/reports?tab=expenses',
      chart: expDonut.length > 0 ? (
        <ResponsiveContainer width="100%" height={80}>
          <PieChart>
            <Pie data={expDonut} cx="50%" cy="50%" innerRadius={20} outerRadius={36}
              paddingAngle={2} dataKey="value" startAngle={90} endAngle={-270}>
              {expDonut.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={tooltipStyle} labelStyle={{ color: '#94a3b8' }}
              formatter={(v: number) => formatCurrency(String(v))}
            />
          </PieChart>
        </ResponsiveContainer>
      ) : null,
    },
  ]

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {cards.map(c => {
        const Icon = c.icon
        return (
          <button
            key={c.title}
            onClick={() => navigate(c.to)}
            className="card p-4 text-left hover:border-brand-500/40 transition-colors group"
          >
            <div className="flex items-start justify-between gap-1 mb-2">
              <div className="flex items-start gap-1.5 min-w-0">
                <Icon size={14} className={`${c.iconColor} shrink-0 mt-px`} />
                <p className="text-xs font-semibold text-white leading-tight">{c.title}</p>
              </div>
              <ArrowUpRight size={12} className="shrink-0 text-slate-600 group-hover:text-brand-400 transition-colors" />
            </div>
            <p className="text-[10px] text-slate-500 mb-2">{c.sub}</p>
            {/* Mini chart or skeleton placeholder */}
            {c.chart ?? (
              <div className="h-20 flex items-center justify-center">
                <p className="text-[10px] text-slate-600">No data yet</p>
              </div>
            )}
          </button>
        )
      })}
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function DashboardPage() {
  const navigate = useNavigate()
  const accent   = useThemeAccent()

  const [period, setPeriod] = useState<PeriodKey>('30d')

  // Current period data
  const [pnl,             setPnl]             = useState<any>(null)
  const [salesData,       setSalesData]       = useState<any[]>([])
  const [topProducts,     setTopProducts]     = useState<any[]>([])
  const [expenses,        setExpenses]        = useState<any[]>([])
  const [arAging,         setArAging]         = useState<any>(null)
  const [apAging,         setApAging]         = useState<any>(null)
  const [topCustomers,    setTopCustomers]    = useState<any[]>([])
  const [lowStock,        setLowStock]        = useState<any[]>([])
  const [lowStockTotal,   setLowStockTotal]   = useState(0)
  const [overdueInvoices, setOverdueInvoices] = useState<any[]>([])
  const [overdueTotal,    setOverdueTotal]    = useState(0)
  const [recentInvoices,  setRecentInvoices]  = useState<any[]>([])
  const [loading,         setLoading]         = useState(true)
  const [showAI,          setShowAI]          = useState(false)
  const [_refreshTick,    setRefreshTick]     = useState(0)
  const [firsStats,       setFirsStats]       = useState<FirsStats | null>(null)
  /** Tracks when data was last successfully fetched — shown in the header */
  const [lastFetched,     setLastFetched]     = useState<Date | null>(null)

  // Phase 1C: prior-period sales for comparison line on revenue chart
  const [priorSalesData, setPriorSalesData] = useState<any[]>([])

  useDataRefresh(() => setRefreshTick(t => t + 1))

  const { dateFrom, dateTo } = useMemo(() => getDateRange(period), [period])
  const periodLabel = PERIODS.find(p => p.key === period)?.label ?? ''

  // Number of days in the selected window — used for DSO / DPO calculations
  const periodDays = useMemo(() => {
    const diff = differenceInDays(new Date(dateTo), new Date(dateFrom))
    return Math.max(1, diff + 1)
  }, [dateFrom, dateTo])

  // ── Main data fetch ──────────────────────────────────────────────────────────
  useEffect(() => {
    setLoading(true)

    const { priorFrom, priorTo } = getPriorDateRange(dateFrom, dateTo)

    const fetchAll = async () => {
      const [
        pnlRes, salesRes, priorSalesRes, topProdRes, expRes,
        arRes, apRes, custRes, stockRes, overdueRes, recentRes,
      ] = await Promise.allSettled([
        reportApi.pnl({ date_from: dateFrom, date_to: dateTo }),
        reportApi.sales({ date_from: dateFrom, date_to: dateTo, group_by: 'day' }),
        // Phase 1C: prior-period sales for the comparison overlay
        reportApi.sales({ date_from: priorFrom, date_to: priorTo, group_by: 'day' }),
        reportApi.topProducts({ date_from: dateFrom, date_to: dateTo, limit: 5 }),
        reportApi.expenses({ date_from: dateFrom, date_to: dateTo }),
        reportApi.arAging(),
        reportApi.apAging(),
        reportApi.topCustomers({ date_from: dateFrom, date_to: dateTo, limit: 10 }),
        inventoryApi.stock(),
        salesApi.invoices({ status: 'overdue', page_size: 5 }),
        salesApi.invoices({ page_size: 6 }),
      ])

      if (pnlRes.status === 'fulfilled')
        setPnl(pnlRes.value.data)

      if (salesRes.status === 'fulfilled') {
        const d = salesRes.value.data
        setSalesData(Array.isArray(d) ? d : (d.results ?? []))
      }

      // Phase 1C: store prior period sales indexed by position (0…n-1) for overlay
      if (priorSalesRes.status === 'fulfilled') {
        const d = priorSalesRes.value.data
        setPriorSalesData(Array.isArray(d) ? d : (d.results ?? []))
      }

      if (topProdRes.status === 'fulfilled') {
        const d = topProdRes.value.data
        setTopProducts(Array.isArray(d) ? d : (d.results ?? []))
      }

      if (expRes.status === 'fulfilled') {
        const d = expRes.value.data
        setExpenses(Array.isArray(d) ? d : (d.results ?? []))
      }

      if (arRes.status === 'fulfilled')   setArAging(arRes.value.data)
      if (apRes.status === 'fulfilled')   setApAging(apRes.value.data)

      if (custRes.status === 'fulfilled') {
        const d = custRes.value.data
        setTopCustomers(Array.isArray(d) ? d : (d.results ?? []))
      }

      if (stockRes.status === 'fulfilled') {
        const d    = stockRes.value.data
        const all: any[] = Array.isArray(d) ? d : (d.results ?? [])
        const low  = all.filter((i: any) => i.stock_level === 'low' || i.is_low_stock)
        setLowStockTotal(low.length)
        setLowStock(low.slice(0, 5))
      }

      if (overdueRes.status === 'fulfilled') {
        const d     = overdueRes.value.data
        const items: any[] = Array.isArray(d) ? d : (d.results ?? [])
        const total = Array.isArray(d) ? d.length : (d.count ?? items.length)
        setOverdueTotal(total)
        setOverdueInvoices(items.slice(0, 5))
      }

      if (recentRes.status === 'fulfilled') {
        const d = recentRes.value.data
        setRecentInvoices((Array.isArray(d) ? d : (d.results ?? [])).slice(0, 6))
      }

      setLoading(false)
      setLastFetched(new Date())
    }

    fetchAll()

    // Refresh low stock every 60 s without re-fetching everything
    const interval = setInterval(async () => {
      try {
        const res  = await inventoryApi.stock()
        const d    = res.data
        const all: any[] = Array.isArray(d) ? d : (d.results ?? [])
        const low  = all.filter((i: any) => i.stock_level === 'low' || i.is_low_stock)
        setLowStockTotal(low.length)
        setLowStock(low.slice(0, 5))
      } catch { /* silent */ }
    }, 60_000)

    return () => clearInterval(interval)
  }, [dateFrom, dateTo, _refreshTick])

  // Fetch FIRS compliance stats once on mount (non-blocking)
  useEffect(() => {
    einvoicingApi.stats().then(({ data }) => setFirsStats(data)).catch(() => null)
  }, [])

  // ── Derived chart data ───────────────────────────────────────────────────────

  /**
   * Phase 1C: Merge current and prior period sales onto a shared positional
   * index (0…n-1) so both lines can be rendered on the same AreaChart.
   * X-axis labels come from the current period; the prior line is labelled
   * "Prior Period" in the tooltip.
   */
  const chartData = useMemo(() => {
    const current = salesData.map((d, i) => ({
      date:        format(new Date(d.period), period === 'today' ? 'HH:mm' : 'MMM d'),
      revenue:     parseFloat(d.total_revenue),
      priorRevenue: priorSalesData[i] ? parseFloat(priorSalesData[i].total_revenue) : undefined,
    }))
    return current
  }, [salesData, priorSalesData, period])

  // Sparkline data: 7 most recent daily revenue points for the KPI card
  const revSparkline = useMemo(
    () => salesData.slice(-7).map(d => parseFloat(d.total_revenue)),
    [salesData],
  )

  const totalOrders = salesData.reduce((s, d) => s + (d.invoice_count ?? 0), 0)

  // Phase 1C: compute period-over-period growth for the Revenue KPI badge
  const priorRevTotal = priorSalesData.reduce((s, d) => s + parseFloat(d.total_revenue ?? 0), 0)
  const currRevTotal  = salesData.reduce((s, d) => s + parseFloat(d.total_revenue ?? 0), 0)
  const revGrowthPct  = priorRevTotal > 0
    ? ((currRevTotal - priorRevTotal) / priorRevTotal * 100).toFixed(1)
    : null

  // ── Shared chart tooltip style (theme-aware) ─────────────────────────────────
  const tooltipStyle = {
    background: '#1e293b', border: '1px solid #334155',
    borderRadius: '12px', fontSize: '13px',
  }

  // ── Refresh helper ───────────────────────────────────────────────────────────
  const handleRefresh = async () => {
    await Promise.allSettled([
      offlineCache.invalidatePrefix('/tenancy/organisations/my_membership/'),
      offlineCache.invalidatePrefix('/tenancy/memberships/'),
      offlineCache.invalidatePrefix('/tenancy/organisations/'),
      offlineCache.invalidatePrefix('/subscriptions/current/'),
    ])
    setRefreshTick(t => t + 1)
    window.dispatchEvent(new CustomEvent('audity:app-refresh'))
    window.dispatchEvent(new CustomEvent('audity:data-changed'))
  }

  // ─────────────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">

      {/* ── Page header ────────────────────────────────────────────────────── */}
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
            onChange={e => setPeriod(e.target.value as PeriodKey)}
            className="input text-sm py-1.5 w-auto"
          >
            {PERIODS.map(({ key, label }) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>

          <button
            onClick={() => navigate('/settings?tab=import')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-surface-800 border border-surface-700 hover:border-brand-500/50 hover:bg-surface-700 transition-colors text-sm text-slate-300 hover:text-white"
            title="Import CSV"
          >
            <Upload size={14} className="text-brand-400" />
            <span className="text-xs font-medium hidden sm:inline">Import</span>
          </button>

          <button
            onClick={() => setShowAI(true)}
            className="flex items-center gap-2 px-3 py-2 bg-brand-500/15 border border-brand-500/30 hover:bg-brand-500/25 rounded-xl transition-colors"
            title="Ask Audity AI about your finances"
          >
            <Sparkles size={14} className="text-brand-400" />
            <span className="text-xs text-brand-400 font-medium hidden sm:inline">Explain My Money</span>
          </button>

          <button
            onClick={handleRefresh}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 bg-surface-800 border border-surface-700 hover:border-slate-500 rounded-xl transition-colors"
            title="Refresh all data"
          >
            <RefreshCw size={14} className={`text-slate-400 ${loading ? 'animate-spin' : ''}`} />
            <span className="text-xs text-slate-400 font-medium hidden sm:inline">
              {loading ? 'Loading…' : lastFetched
                ? `Updated ${format(lastFetched, 'HH:mm')}`
                : 'Refresh'}
            </span>
          </button>

          <div className="flex items-center gap-2 px-3 py-2 bg-green-500/10 border border-green-500/30 rounded-xl">
            <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
            <span className="text-xs text-green-400 font-medium">Live</span>
          </div>
        </div>
      </div>

      <AIChatModal open={showAI} onClose={() => setShowAI(false)} />

      {/* ── FIRS compliance banner ──────────────────────────────────────────── */}
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
            <p className="text-xs text-slate-400">Click to open FIRS settings and retry.</p>
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
            <p className="text-xs text-slate-400">Switch to production when ready to go live.</p>
          </div>
          <span className="text-xs text-amber-400 font-medium whitespace-nowrap">Configure →</span>
        </div>
      )}

      {/* ── Phase 1A: 4 KPI cards (Low Stock + Overdue tiles removed) ──────── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label={`Total Revenue · ${periodLabel}`}
          value={loading ? '—' : formatCurrency(pnl?.revenue?.gross_sales ?? 0)}
          icon={DollarSign}
          color="orange"
          trend={revGrowthPct ? (parseFloat(revGrowthPct) >= 0 ? 'up' : 'down') : undefined}
          trendValue={revGrowthPct ? `${revGrowthPct}%` : undefined}
          sparkData={revSparkline}
          onClick={() => navigate('/reports')}
        />
        <StatCard
          label={`Gross Profit · ${periodLabel}`}
          value={loading ? '—' : formatCurrency(pnl?.gross_profit ?? 0)}
          sub={pnl ? `${parseFloat(pnl.gross_margin_pct ?? 0).toFixed(1)}% margin` : undefined}
          icon={TrendingUp}
          color="green"
          onClick={() => navigate('/reports?tab=pnl')}
        />
        <StatCard
          label={`Net Profit · ${periodLabel}`}
          value={loading ? '—' : formatCurrency(pnl?.net_profit ?? 0)}
          sub={pnl ? `${parseFloat(pnl.net_margin_pct ?? 0).toFixed(1)}% margin` : undefined}
          icon={Zap}
          color="blue"
          onClick={() => navigate('/reports?tab=pnl')}
        />
        <StatCard
          label={`Total Orders · ${periodLabel}`}
          value={loading ? '—' : String(totalOrders)}
          sub="Invoices issued"
          icon={ShoppingCart}
          color="orange"
          onClick={() => navigate('/sales')}
        />
      </div>

      {/* ── Phase 1B: Financial Health Ratio strip ─────────────────────────── */}
      {!loading && (
        <HealthRatioStrip
          pnl={pnl}
          arAging={arAging}
          apAging={apAging}
          topCustomers={topCustomers}
          periodDays={periodDays}
        />
      )}
      {loading && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="rounded-xl border border-surface-700 p-3 h-16 bg-surface-800 animate-pulse" />
          ))}
        </div>
      )}

      {/* ── Phase 1C: Revenue Trend + Phase 1D: Report Shortcuts ───────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Revenue Trend — 2/3 width — with prior-period comparison overlay */}
        <div className="card lg:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="font-semibold text-white flex items-center gap-2">
                <Activity size={16} className="text-brand-400" /> Revenue Trend
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                {periodLabel}
                {priorSalesData.length > 0 && ' · dashed line = prior period'}
              </p>
            </div>
            <button
              onClick={() => navigate('/reports')}
              className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1"
            >
              Full Report <ArrowUpRight size={12} />
            </button>
          </div>

          {loading ? (
            <div className="h-48 bg-surface-800 rounded-xl animate-pulse" />
          ) : chartData.length === 0 ? (
            <div className="h-48 flex flex-col items-center justify-center text-slate-500">
              <TrendingUp size={28} className="mb-2 opacity-30" />
              <p className="text-sm">No revenue data for this period</p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <defs>
                  <linearGradient id="dashGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor={accent} stopOpacity={0.3} />
                    <stop offset="95%" stopColor={accent} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 10 }}
                  axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#64748b', fontSize: 10 }}
                  axisLine={false} tickLine={false}
                  tickFormatter={v => `${getCurrencySymbol()}${(v / 1000).toFixed(0)}k`} />
                <Tooltip
                  contentStyle={tooltipStyle}
                  labelStyle={{ color: '#94a3b8' }}
                  formatter={(v: number, name: string) => [
                    formatCurrency(String(v)),
                    name === 'revenue' ? 'Revenue' : 'Prior Period',
                  ]}
                />
                {/* Current period — solid fill */}
                <Area type="monotone" dataKey="revenue" stroke={accent} strokeWidth={2}
                  fill="url(#dashGrad)" dot={false} activeDot={{ r: 4 }} />
                {/* Prior period — dashed line, no fill */}
                {priorSalesData.length > 0 && (
                  <Area type="monotone" dataKey="priorRevenue"
                    stroke={accent} strokeWidth={1.5} strokeDasharray="5 3"
                    fill="transparent" dot={false} />
                )}
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Phase 1D: Report Shortcuts — 1/3 width */}
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-white flex items-center gap-2">
              <BarChart2 size={16} className="text-brand-400" /> Reports
            </h2>
            <button
              onClick={() => navigate('/reports')}
              className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1"
            >
              All reports <ArrowUpRight size={12} />
            </button>
          </div>
          {loading ? (
            <div className="grid grid-cols-2 gap-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="rounded-xl border border-surface-700 h-28 bg-surface-800 animate-pulse" />
              ))}
            </div>
          ) : (
            <ReportShortcuts
              pnl={pnl}
              arAging={arAging}
              topProducts={topProducts}
              expenses={expenses}
              accent={accent}
            />
          )}
        </div>
      </div>

      {/* ── Recent Invoices + Quick Actions ──────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Recent Invoices */}
        <div className="card lg:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-white flex items-center gap-2">
              <Receipt size={16} className="text-brand-400" /> Recent Invoices
            </h2>
            <button onClick={() => navigate('/sales')}
              className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1">
              View all <ArrowUpRight size={12} />
            </button>
          </div>

          {loading ? (
            <div className="h-40 flex items-center justify-center">
              <div className="w-7 h-7 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : recentInvoices.length === 0 ? (
            <div className="flex flex-col items-center py-10 text-slate-500">
              <FileText size={30} className="mb-2 opacity-30" />
              <p className="text-sm">No invoices yet</p>
              <button onClick={() => navigate('/sales/new')}
                className="mt-3 text-xs text-brand-400 hover:text-brand-300 font-medium">
                Create your first invoice →
              </button>
            </div>
          ) : (
            <div className="divide-y divide-surface-700/60">
              {recentInvoices.map((inv, i) => {
                const badge = invoiceStatusBadge(inv.status)
                return (
                  <button
                    key={i}
                    onClick={() => navigate('/sales')}
                    className="w-full flex items-center gap-3 py-2.5 first:pt-0 last:pb-0 hover:bg-surface-700/40 rounded-lg px-2 -mx-2 transition-colors text-left"
                  >
                    <div className="w-9 h-9 rounded-xl bg-brand-500/15 border border-brand-500/25 flex items-center justify-center shrink-0">
                      <FileText size={15} className="text-brand-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-white truncate">{inv.invoice_number}</p>
                      <p className="text-xs text-slate-500 truncate">{inv.customer_name ?? 'Walk-in customer'}</p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-sm font-semibold text-white">{formatCurrency(inv.total_amount ?? inv.amount_due ?? 0)}</p>
                      <span className={`${badge.cls} mt-0.5`}>{badge.label}</span>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>

        {/* Quick Actions */}
        <div className="card">
          <h2 className="font-semibold text-white flex items-center gap-2 mb-4">
            <Zap size={16} className="text-brand-400" /> Quick Actions
          </h2>
          <div className="grid grid-cols-2 gap-3">
            {([
              { label: 'New Sale',      icon: ShoppingCart, color: 'text-brand-400 bg-brand-500/15 border-brand-500/25',  to: '/sales/new' },
              { label: 'New Bill',      icon: Receipt,      color: 'text-blue-400 bg-blue-500/15 border-blue-500/25',     to: '/bills?new=1' },
              { label: 'Add Customer',  icon: UserPlus,     color: 'text-green-400 bg-green-500/15 border-green-500/25',  to: '/customers?new=1' },
              { label: 'Add Product',   icon: Package,      color: 'text-brand-400 bg-brand-500/15 border-brand-500/25',  to: '/inventory/products?new=1' },
              { label: 'Expense',       icon: Wallet,       color: 'text-red-400 bg-red-500/15 border-red-500/25',        to: '/expenses?new=1' },
              { label: 'Reconcile',     icon: Scale,        color: 'text-blue-400 bg-blue-500/15 border-blue-500/25',     to: '/accounting/reconciliation' },
            ] as { label: string; icon: React.ElementType; color: string; to: string }[]).map(a => (
              <button
                key={a.label}
                onClick={() => navigate(a.to)}
                className="flex flex-col items-center justify-center gap-2 p-4 rounded-xl bg-surface-800 border border-surface-700 hover:border-brand-500/50 hover:bg-surface-700/60 transition-colors"
              >
                <span className={`w-10 h-10 rounded-xl border flex items-center justify-center ${a.color}`}>
                  <a.icon size={18} />
                </span>
                <span className="text-xs font-medium text-slate-300 text-center leading-tight">{a.label}</span>
              </button>
            ))}
          </div>
          <button onClick={() => navigate('/sales/new')} className="btn-primary w-full justify-center mt-4 py-2.5">
            <Plus size={16} /> New Sale
          </button>
        </div>
      </div>

      {/* ── Top Products bar (below the revenue chart section) ────────────── */}
      {topProducts.length > 0 && !loading && (
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-white flex items-center gap-2">
              <Package size={16} className="text-emerald-400" /> Top Products · {periodLabel}
            </h2>
            <button onClick={() => navigate('/reports?tab=sales_analytics')}
              className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1">
              Full report <ArrowUpRight size={12} />
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

      {/* ── Phase 1A: Merged Alerts panel (replaces two separate widgets) ──── */}
      {(overdueTotal > 0 || lowStockTotal > 0) && (
        <div className="card">
          <h2 className="font-semibold text-white flex items-center gap-2 mb-4">
            <AlertTriangle size={16} className="text-amber-400" /> Alerts
          </h2>
          <div className="space-y-3">

            {/* Overdue invoices alert row */}
            {overdueTotal > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Clock size={14} className="text-red-400" />
                    <p className="text-sm font-medium text-white">
                      {overdueTotal} Overdue Invoice{overdueTotal !== 1 ? 's' : ''}
                    </p>
                  </div>
                  <button onClick={() => navigate('/sales?status=overdue')}
                    className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1">
                    View all <ArrowUpRight size={11} />
                  </button>
                </div>
                <div className="space-y-1.5">
                  {overdueInvoices.map((inv, i) => (
                    <button
                      key={i}
                      onClick={() => navigate('/sales?status=overdue')}
                      className="w-full flex items-center gap-3 px-3 py-2 rounded-lg bg-surface-800 hover:bg-surface-700 transition-colors text-left"
                    >
                      <div className="w-1.5 h-1.5 bg-red-400 rounded-full animate-pulse shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-white truncate">
                          {inv.invoice_number} · {inv.customer_name ?? 'Walk-in'}
                        </p>
                        <p className="text-[10px] text-slate-500">Due {inv.due_date}</p>
                      </div>
                      <span className="badge-red text-[10px] shrink-0">
                        {formatCurrency(inv.amount_due ?? inv.total_amount)}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Divider between sections when both are present */}
            {overdueTotal > 0 && lowStockTotal > 0 && (
              <div className="border-t border-surface-700" />
            )}

            {/* Low stock alert row */}
            {lowStockTotal > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Package size={14} className="text-amber-400" />
                    <p className="text-sm font-medium text-white">
                      {lowStockTotal} Low Stock Item{lowStockTotal !== 1 ? 's' : ''}
                    </p>
                  </div>
                  <button onClick={() => navigate('/inventory/stock?filter=low')}
                    className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1">
                    View all <ArrowUpRight size={11} />
                  </button>
                </div>
                <div className="space-y-1.5">
                  {lowStock.map((s, i) => (
                    <button
                      key={i}
                      onClick={() => navigate('/inventory/stock?filter=low')}
                      className="w-full flex items-center gap-3 px-3 py-2 rounded-lg bg-surface-800 hover:bg-surface-700 transition-colors text-left"
                    >
                      <div className="w-1.5 h-1.5 bg-amber-400 rounded-full animate-pulse shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-white truncate">{s.product_name}</p>
                        <p className="text-[10px] text-slate-500">{s.warehouse_name}</p>
                      </div>
                      <span className="badge-yellow text-[10px] shrink-0">{s.quantity_on_hand} left</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* All-clear state when no alerts */}
      {!loading && overdueTotal === 0 && lowStockTotal === 0 && (
        <div className="card p-5 flex items-center gap-3">
          <div className="w-8 h-8 bg-emerald-500/15 border border-emerald-500/30 rounded-xl flex items-center justify-center">
            <TrendingUp size={16} className="text-emerald-400" />
          </div>
          <div>
            <p className="text-sm font-medium text-white">All clear</p>
            <p className="text-xs text-slate-500">No overdue invoices and all stock levels are healthy.</p>
          </div>
        </div>
      )}
    </div>
  )
}
