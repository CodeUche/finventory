/**
 * DashboardPage — "Performance Overview" (new Audity design).
 *
 * Layout, top to bottom:
 *  • Header: title + period picker, Import Data, Explain My Money, Live pill
 *  • Four KPI cards  (Revenue, Gross Profit, Net Profit, Orders)
 *  • Financial Health Ratio strip  (DSO, DPO, Gross Margin, Net Margin,
 *                                   Customer Concentration)
 *  • Key Reports: P&L Snapshot, AR Aging, Revenue Trend (deep links to Reports)
 *  • Recent Invoices, Overdue Invoices (only when there are any),
 *    Inventory Alerts, and Quick Actions
 *
 * Data is unchanged from the previous dashboard: the ratios still come from
 * the P&L + AR/AP aging reports already fetched, DSO/DPO use the selected
 * period length. Styling lives in src/styles/dashboard.css (.ad scope).
 */

import { useEffect, useMemo, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Check, Scale } from 'lucide-react'
import { reportApi, inventoryApi, salesApi, einvoicingApi, bypassNextGets } from '@/services/api'
import type { FirsStats } from '@/types'
import { formatCurrency } from '@/lib/utils'
import {
  format, subDays, subMonths, subYears, startOfYear, differenceInDays,
} from 'date-fns'
import AIChatModal from '@/components/AIChatModal'
import { DesignerIcon } from '@/assets/designer-icons'
import '@/styles/dashboard.css'

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

/** Headline money: whole amounts drop the ".00" (₦160,000), fractions keep their kobo. */
const money = (v: string | number) => formatCurrency(v).replace(/\.00$/, '')

// ─── KPI card ─────────────────────────────────────────────────────────────────

function StatCard({
  label, value, sub, subTone, icon, tone, onClick,
}: {
  label: string; value: string; sub?: string; subTone?: 'up' | 'down'
  icon: React.ReactNode; tone: 'a' | 'g' | 'b' | 'r'
  onClick?: () => void
}) {
  return (
    <button type="button" className="stat-card ad-kpi" onClick={onClick}>
      <span className="go" aria-hidden="true"><DesignerIcon name="arrow-up-right" size={18} /></span>
      <span className={`ad-bubble ${tone}`} aria-hidden="true">{icon}</span>
      <span className="ad-kpi-body">
        <span className={`ad-kpi-value${value.length > 12 ? ' long' : ''}`}>{value}</span>
        <span className="ad-kpi-label">{label}</span>
        {sub && <span className={`ad-kpi-sub ${subTone ?? ''}`}>{sub}</span>}
      </span>
    </button>
  )
}

// ─── Invoice status pill ──────────────────────────────────────────────────────

function invoiceStatusBadge(status: string): { cls: 'green' | 'red' | 'yellow' | 'grey'; label: string } {
  const s = (status || '').toLowerCase()
  if (s === 'paid')                              return { cls: 'green',  label: 'Paid' }
  if (s === 'overdue')                           return { cls: 'red',    label: 'Overdue' }
  if (s === 'partial' || s === 'partially_paid') return { cls: 'yellow', label: 'Partial' }
  if (s === 'draft')                             return { cls: 'grey',   label: 'Draft' }
  if (s === 'proforma')                          return { cls: 'grey',   label: 'Proforma' }
  if (s === 'cancelled' || s === 'void')         return { cls: 'grey',   label: 'Cancelled' }
  return { cls: 'yellow', label: s ? s.charAt(0).toUpperCase() + s.slice(1) : 'Pending' }
}

// ─── Financial Health Ratio strip ─────────────────────────────────────────────

/**
 * Five read-only financial health indicators computed from existing dashboard
 * data. Thresholds use broad SME benchmarks; colour is indicative only —
 * always validate against your industry.
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
  const dso = revenue > 0 ? Math.round((arTotal / (revenue / Math.max(1, periodDays)))) : null

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
      label: 'Customer Concentration',
      value: concentration != null ? `Top 3 = ${concentration}%` : '—',
      note: 'Revenue from top 3 customers',
      // > 50 % in top 3 = concentration risk
      status: concentration == null ? 'neutral' : concentration <= 40 ? 'good' : concentration <= 60 ? 'warn' : 'bad',
    },
  ]

  return (
    <div className="ad-ratios">
      {ratios.map((r, i) => (
        <div key={r.label} className={`ad-ratio t${i}`}>
          <p className="lab">{r.label}</p>
          <p className={`val ${r.status}`}>{r.value}</p>
          <p className="note">{r.note}</p>
        </div>
      ))}
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function DashboardPage() {
  const navigate = useNavigate()

  const [period, setPeriod] = useState<PeriodKey>('ytd')

  // Current period data
  const [pnl,             setPnl]             = useState<any>(null)
  const [salesData,       setSalesData]       = useState<any[]>([])
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
  /** Tracks when data was last successfully fetched — shown on the Live pill */
  const [lastFetched,     setLastFetched]     = useState<Date | null>(null)

  // Prior-period sales, for the revenue growth line on the Revenue card
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
        pnlRes, salesRes, priorSalesRes,
        arRes, apRes, custRes, stockRes, overdueRes, recentRes,
      ] = await Promise.allSettled([
        reportApi.pnl({ date_from: dateFrom, date_to: dateTo }),
        reportApi.sales({ date_from: dateFrom, date_to: dateTo, group_by: 'day' }),
        reportApi.sales({ date_from: priorFrom, date_to: priorTo, group_by: 'day' }),
        reportApi.arAging(),
        reportApi.apAging(),
        reportApi.topCustomers({ date_from: dateFrom, date_to: dateTo, limit: 10 }),
        inventoryApi.stock(),
        salesApi.invoices({ status: 'overdue', page_size: 5 }),
        salesApi.invoices({ page_size: 6, ordering: '-issue_date' }),
      ])

      if (pnlRes.status === 'fulfilled')
        setPnl(pnlRes.value.data)

      if (salesRes.status === 'fulfilled') {
        const d = salesRes.value.data
        setSalesData(Array.isArray(d) ? d : (d.results ?? []))
      }

      if (priorSalesRes.status === 'fulfilled') {
        const d = priorSalesRes.value.data
        setPriorSalesData(Array.isArray(d) ? d : (d.results ?? []))
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

  const totalOrders = salesData.reduce((s, d) => s + (d.invoice_count ?? 0), 0)

  // Period-over-period growth for the Revenue card
  const priorRevTotal = priorSalesData.reduce((s, d) => s + parseFloat(d.total_revenue ?? 0), 0)
  const currRevTotal  = salesData.reduce((s, d) => s + parseFloat(d.total_revenue ?? 0), 0)
  const revGrowthPct  = priorRevTotal > 0
    ? ((currRevTotal - priorRevTotal) / priorRevTotal * 100).toFixed(1)
    : null

  const criticalStock = lowStockTotal

  // ─────────────────────────────────────────────────────────────────────────────

  return (
    <div className="ad">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="ad-head">
        <div>
          <h1>Performance Overview</h1>
          <p>Summary of your business health for this period</p>
        </div>
        <div className="ad-actions">
          <select
            value={period}
            onChange={e => { bypassNextGets(8000); setPeriod(e.target.value as PeriodKey) }}
            className="ad-select"
            aria-label="Reporting period"
          >
            {PERIODS.map(({ key, label }) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>

          <button
            type="button"
            onClick={() => navigate('/settings?tab=import')}
            className="ad-btn ad-btn-outline"
            title="Import CSV"
          >
            <DesignerIcon name="download" size={20} />
            Import Data
          </button>

          <button
            type="button"
            onClick={() => setShowAI(true)}
            className="ad-btn ad-btn-solid"
            title="Ask Audity AI about your finances"
          >
            Explain My Money
          </button>

          <span
            className="ad-live"
            title={lastFetched ? `Updated ${format(lastFetched, 'HH:mm')}` : 'Loading…'}
          >
            <i aria-hidden="true" />
            Live
          </span>
        </div>
      </div>

      <AIChatModal open={showAI} onClose={() => setShowAI(false)} />

      {/* ── FIRS compliance banner ──────────────────────────────────────────── */}
      {firsStats?.is_enrolled && firsStats.failed > 0 && (
        <div className="ad-banner red" onClick={() => navigate('/settings?tab=firs')}>
          <AlertTriangle size={18} className="shrink-0" />
          <div className="min-w-0">
            <strong>{firsStats.failed} FIRS submission{firsStats.failed !== 1 ? 's' : ''} failed</strong>
            <small>Click to open FIRS settings and retry.</small>
          </div>
          <span className="go">Fix now →</span>
        </div>
      )}
      {firsStats?.is_enrolled && firsStats.failed === 0 && firsStats.use_sandbox && (
        <div className="ad-banner amber" onClick={() => navigate('/settings?tab=firs')}>
          <AlertTriangle size={18} className="shrink-0" />
          <div className="min-w-0">
            <strong>FIRS e-invoicing is in sandbox mode</strong>
            <small>Switch to production when ready to go live.</small>
          </div>
          <span className="go">Configure →</span>
        </div>
      )}

      {/* ── KPI cards ───────────────────────────────────────────────────────── */}
      <div className="ad-kpis">
        <StatCard
          label={`Total Revenue · ${periodLabel}`}
          value={loading ? '—' : money(pnl?.revenue?.gross_sales ?? 0)}
          sub={revGrowthPct ? `${parseFloat(revGrowthPct) >= 0 ? '▲' : '▼'} ${Math.abs(parseFloat(revGrowthPct))}% vs prior period` : undefined}
          subTone={revGrowthPct ? (parseFloat(revGrowthPct) >= 0 ? 'up' : 'down') : undefined}
          icon={<DesignerIcon name="revenue" size={26} />}
          tone="a"
          onClick={() => navigate('/reports')}
        />
        <StatCard
          label={`Gross Profit · ${periodLabel}`}
          value={loading ? '—' : money(pnl?.gross_profit ?? 0)}
          sub={pnl ? `${parseFloat(pnl.gross_margin_pct ?? 0).toFixed(1)}% margin` : undefined}
          icon={<DesignerIcon name="trend-up" size={26} />}
          tone="g"
          onClick={() => navigate('/reports?tab=pnl')}
        />
        <StatCard
          label={`Net Profit · ${periodLabel}`}
          value={loading ? '—' : money(pnl?.net_profit ?? 0)}
          sub={pnl ? `${parseFloat(pnl.net_margin_pct ?? 0).toFixed(1)}% margin` : undefined}
          icon={<DesignerIcon name="bolt-circle" size={26} />}
          tone="b"
          onClick={() => navigate('/reports?tab=pnl')}
        />
        <StatCard
          label={`Total Orders · ${periodLabel}`}
          value={loading ? '—' : String(totalOrders)}
          sub="Invoices issued"
          icon={<DesignerIcon name="cart" size={26} />}
          tone="a"
          onClick={() => navigate('/sales')}
        />
      </div>

      {/* ── Financial Health Ratio strip ────────────────────────────────────── */}
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
        <div className="ad-ratios">
          {Array.from({ length: 5 }).map((_, i) => <div key={i} className="ad-skel" />)}
        </div>
      )}

      {/* ── Key Reports ─────────────────────────────────────────────────────── */}
      <section className="ad-card" aria-label="Key reports">
        <div className="ad-card-head">
          <h2>Key Reports</h2>
          <button type="button" className="ad-link" onClick={() => navigate('/reports')}>
            View All Reports <DesignerIcon name="arrow-right" size={18} />
          </button>
        </div>
        <div className="ad-reports">
          {([
            { title: 'P&L Snapshot',  sub: 'Revenue to profit',        icon: 'invoice' as const, to: '/reports?tab=pnl' },
            { title: 'AR Aging',      sub: 'Outstanding receivables',  icon: 'clock' as const,   to: '/reports?tab=aging' },
            { title: 'Revenue Trend', sub: periodLabel,                icon: 'trend-up' as const, to: '/reports?tab=overview' },
          ]).map(r => (
            <button key={r.title} type="button" className="ad-report" onClick={() => navigate(r.to)}>
              <span className="ico"><DesignerIcon name={r.icon} size={24} /></span>
              <span>
                <span className="t" style={{ display: 'block' }}>{r.title}</span>
                <span className="s" style={{ display: 'block' }}>{r.sub}</span>
              </span>
              <span className="chev"><DesignerIcon name="chevron-right" size={22} /></span>
            </button>
          ))}
        </div>
      </section>

      {/* ── Recent invoices, alerts and quick actions ───────────────────────── */}
      <div className="ad-lower">
        <div className="ad-stack">

          {/* Recent Invoices */}
          <section className="ad-card" aria-label="Recent invoices">
            <div className="ad-card-head">
              <h2>Recent Invoices</h2>
              <button type="button" className="ad-link" onClick={() => navigate('/sales')}>
                View All Invoices <DesignerIcon name="arrow-right" size={18} />
              </button>
            </div>

            {loading ? (
              <div className="ad-spin" role="status" aria-label="Loading invoices" />
            ) : recentInvoices.length === 0 ? (
              <div className="ad-empty">
                <DesignerIcon name="invoice" size={30} />
                <p>No invoices yet</p>
                <button type="button" className="ad-link" onClick={() => navigate('/sales/new')}>
                  Create your first invoice →
                </button>
              </div>
            ) : (
              <div>
                {recentInvoices.map((inv, i) => {
                  const badge = invoiceStatusBadge(inv.status)
                  return (
                    <button key={inv.id ?? i} type="button" className="ad-inv" onClick={() => navigate('/sales')}>
                      <span className="ico"><DesignerIcon name="invoice" size={22} /></span>
                      <span className="mid">
                        <span className="n" style={{ display: 'block' }}>{inv.invoice_number}</span>
                        <span className="c" style={{ display: 'block' }}>{inv.customer_name ?? 'Walk-in customer'}</span>
                      </span>
                      <span className="end">
                        <span className="amt">{money(inv.total_amount ?? inv.amount_due ?? 0)}</span>
                        <span className={`ad-pill ${badge.cls}`}>{badge.label}</span>
                      </span>
                    </button>
                  )
                })}
              </div>
            )}
          </section>

          {/* Overdue invoices — only shown when there are some */}
          {overdueTotal > 0 && (
            <section className="ad-card" aria-label="Overdue invoices">
              <div className="ad-card-head">
                <h2>Overdue Invoices</h2>
                <button type="button" className="ad-link danger" onClick={() => navigate('/sales?status=overdue')}>
                  {overdueTotal} Overdue <DesignerIcon name="arrow-right" size={18} />
                </button>
              </div>
              <div>
                {overdueInvoices.map((inv, i) => (
                  <button key={inv.id ?? i} type="button" className="ad-stock" onClick={() => navigate('/sales?status=overdue')}>
                    <span style={{ minWidth: 0 }}>
                      <span className="nm low" style={{ display: 'block' }}>
                        {inv.invoice_number} · {inv.customer_name ?? 'Walk-in'}
                      </span>
                      <span style={{ display: 'block', fontSize: 14, color: 'var(--ad-muted)' }}>Due {inv.due_date}</span>
                    </span>
                    <span className="ad-pill red">{money(inv.amount_due ?? inv.total_amount)}</span>
                  </button>
                ))}
              </div>
            </section>
          )}

          {/* Inventory Alerts */}
          <section className="ad-card" aria-label="Inventory alerts">
            <div className="ad-card-head">
              <h2>Inventory Alerts</h2>
              {criticalStock > 0 && (
                <button type="button" className="ad-link danger" onClick={() => navigate('/inventory/stock?filter=low')}>
                  {criticalStock} Item{criticalStock !== 1 ? 's' : ''} Critical <DesignerIcon name="arrow-right" size={18} />
                </button>
              )}
            </div>
            {criticalStock === 0 ? (
              !loading && (
                <div className="ad-allclear">
                  <i aria-hidden="true"><Check size={18} /></i>
                  <span>All clear — no overdue invoices and all stock levels are healthy.</span>
                </div>
              )
            ) : (
              <div>
                {lowStock.map((s, i) => {
                  const qty = parseFloat(s.quantity_on_hand ?? 0)
                  const out = qty <= 0
                  return (
                    <button key={s.id ?? i} type="button" className="ad-stock" onClick={() => navigate('/inventory/stock?filter=low')}>
                      <span className={`nm ${out ? '' : 'low'}`}>{s.product_name}</span>
                      <span className={`ad-pill ${out ? 'grey' : 'red'}`}>{out ? 'Out Of Stock' : `${s.quantity_on_hand} left`}</span>
                    </button>
                  )
                })}
              </div>
            )}
          </section>
        </div>

        {/* Quick Actions */}
        <section className="ad-quick" aria-label="Quick actions">
          <h2>Quick Actions</h2>
          <div className="ad-quick-grid">
            <button type="button" className="ad-qa" onClick={() => navigate('/sales/new')}>
              <span className="b blue"><DesignerIcon name="cart" size={28} /></span>
              New Sale
            </button>
            <button type="button" className="ad-qa" onClick={() => navigate('/customers?new=1')}>
              <span className="b green"><DesignerIcon name="user-plus" size={28} /></span>
              Add Customer
            </button>
            <button type="button" className="ad-qa" onClick={() => navigate('/expenses?new=1')}>
              <span className="b red"><DesignerIcon name="wallet" size={28} /></span>
              Expenses
            </button>
            <button type="button" className="ad-qa" onClick={() => navigate('/accounting/reconciliation')}>
              <span className="b plain"><Scale size={28} strokeWidth={1.5} /></span>
              Reconcile
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}
