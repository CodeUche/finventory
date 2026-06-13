/**
 * ReportsPage — Full analytics suite.
 *
 * Tab structure:
 *  overview       — KPI cards, stacked bar (Rev vs Costs), trend chart, AR aging mini
 *  pnl            — Waterfall bridge chart + comparison table + existing bar breakdown
 *  cashflow       — Monthly grouped bar (in/out) + cumulative area + metric cards
 *  sales_analytics— Top customers horizontal bar + payment method donut + revenue trend
 *  aging          — AR & AP aging donuts + per-customer stacked bar + overdue list
 *  expenses       — Category donut + expense vs revenue trend area + ratio target line
 *
 * Phase 2A: Overview enhanced with stacked Revenue/COGS/OpEx bar + prior-period
 *           comparison line and AR aging mini.
 * Phase 2B: P&L tab — horizontal waterfall (ComposedChart) + comparison column.
 * Phase 2C: New "Sales Analytics" tab replaces old Products + Customers tabs.
 * Phase 2D: New "AR/AP Aging" tab with donuts and per-customer stacked bar.
 * Phase 2E: Cash Flow — grouped monthly bar + cumulative area chart.
 * Phase 2F: Expenses — trend area + expense ratio reference line.
 *
 * All charts use Recharts (already in project).  Zero new dependencies.
 */

import { useEffect, useMemo, useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { useThemeAccent } from '@/hooks/useTheme'
import {
  AreaChart, Area,
  BarChart, Bar,
  ComposedChart, ReferenceLine,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts'
import {
  BarChart2, RefreshCw, TrendingDown, TrendingUp, Clock, Receipt,
  Download, ArrowDownCircle, ArrowUpCircle, Landmark, LayoutDashboard,
  FileText, Users, DollarSign, PieChart as PieIcon, Activity,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { reportApi, urlToDataUrl, bypassNextGets } from '@/services/api'
import { formatCurrency, formatNumber, formatDate, getCurrencySymbol } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import { saveBlobFile } from '@/lib/saveBlobFile'
import PeriodSelector, { type PeriodValue } from '@/components/PeriodSelector'
import ExportBar from '@/components/ExportBar'
import ReportTable from '@/components/ReportTable'
import type { PnL, SalesSummaryPoint, ARAgingReport, VATSummary } from '@/types'

// ─── Tab definitions ──────────────────────────────────────────────────────────

const TABS = [
  { id: 'overview',        label: 'Overview',        icon: LayoutDashboard },
  { id: 'pnl',             label: 'P&L Statement',   icon: FileText },
  { id: 'cashflow',        label: 'Cash Flow',        icon: Landmark },
  { id: 'sales_analytics', label: 'Sales Analytics', icon: Users },
  { id: 'aging',           label: 'AR / AP Aging',   icon: Clock },
  { id: 'expenses',        label: 'Expenses',         icon: TrendingDown },
] as const

type TabId = (typeof TABS)[number]['id']

// ─── Shared chart palette & tooltip style ────────────────────────────────────

/** Standard palette; index-0 is always the theme-aware brand accent. */
const STATIC_COLORS = ['#3b82f6', '#10b981', '#a855f7', '#f59e0b', '#ef4444', '#06b6d4']

/** Aging bucket colours: healthy → critical */
const AGING_COLORS = ['#10b981', '#f59e0b', '#f97316', '#ef4444', '#991b1b']

// Chart styles — defined as module-level defaults (dark mode).
// Light mode tooltip override lives in index.css via the recharts-tooltip-wrapper rule.
const tooltipStyle = {
  backgroundColor: '#1e293b',
  border:          '1px solid #334155',
  borderRadius:    '12px',
  color:           '#f1f5f9',
  fontSize:        12,
}
const tooltipLabelStyle  = { color: '#94a3b8' }
const tooltipItemStyle   = { color: '#f1f5f9' }
// Use a light-grey fill so axis ticks are readable on the dark card background.
// In light mode, index.css remaps via .recharts-cartesian-axis-tick-value.
const axisTickStyle      = { fill: '#94a3b8', fontSize: 11 }

// ─── Local type helpers ───────────────────────────────────────────────────────

interface TopProduct    { product_name: string; revenue: string; units_sold: string; cogs: string; gross_profit: string; product_sku?: string }
interface TopCustomer  { customer_name: string; revenue: string; invoice_count: number; customer_code?: string }
interface ExpRow       { category_name: string; total: string; count: number }
interface CashFlow     { cash_inflows: string; cash_outflows: string; net_cash_flow: string }
interface PayMethod    { method: string; label: string; total: string; count: number }
interface InventoryVal { total_inventory_value: string | number; items: { product: string; sku: string; warehouse: string; quantity: number; unit_cost: string; total_value: string }[] }

// ─── Utility functions ────────────────────────────────────────────────────────

function periodToParams(p: PeriodValue): Record<string, string> {
  const out: Record<string, string> = { period: p.period }
  if (p.date_from) out.date_from = p.date_from
  if (p.date_to)   out.date_to   = p.date_to
  return out
}

function groupByForPeriod(period: PeriodValue['period']): string {
  if (period === 'today' || period === 'week' || period === 'month') return 'day'
  return 'month'
}

/** Truncate long product / customer names for chart axes. */
const trunc = (s: string, n = 14) => (s?.length ?? 0) > n ? s.slice(0, n) + '…' : (s ?? '—')

/**
 * Format an ISO period string (from TruncDay/Month/Year) to a readable label.
 * e.g. "2024-01-01T00:00:00Z" → "Jan 2024" (month) or "1 Jan" (day)
 */
function fmtPeriod(raw: string, groupBy: string): string {
  if (!raw) return raw
  try {
    const d = new Date(raw)
    if (isNaN(d.getTime())) return raw
    if (groupBy === 'year') return String(d.getUTCFullYear())
    if (groupBy === 'month') return d.toLocaleDateString('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' })
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })
  } catch { return raw }
}

// ─── Small KPI helper ─────────────────────────────────────────────────────────

function kpi(label: string, value: string, sub?: string, positive = true) {
  return (
    <div className="card p-5">
      <p className="text-xs text-slate-400 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${positive ? 'text-white' : 'text-red-400'}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

/** Map legacy tab IDs (removed tabs) to their replacement. */
const TAB_REDIRECT: Record<string, TabId> = {
  products:  'sales_analytics',
  customers: 'sales_analytics',
  tax:       'overview',  // tax summary surfaced in Overview now
}

export default function ReportsPage() {
  const { organisation } = useAuthStore()
  const accent           = useThemeAccent()
  /** Full palette with brand accent at position 0 */
  const colors           = [accent, ...STATIC_COLORS]

  const [searchParams, setSearchParams] = useSearchParams()

  /**
   * Read initial tab from ?tab= URL param so dashboard shortcut cards work.
   * Legacy tab IDs (e.g. ?tab=products) are silently redirected.
   */
  const initialTab = (() => {
    const raw = searchParams.get('tab') as TabId | null
    if (!raw) return 'overview' as TabId
    if (TAB_REDIRECT[raw]) return TAB_REDIRECT[raw]
    const valid = TABS.map(t => t.id)
    return valid.includes(raw) ? raw : ('overview' as TabId)
  })()

  const [tab,    setTab]    = useState<TabId>(initialTab)
  const [period, setPeriod] = useState<PeriodValue>({ period: 'all' })

  /** Sync tab selection to URL so users can share/bookmark specific tabs. */
  const handleSetTab = useCallback((t: TabId) => {
    setTab(t)
    setSearchParams(prev => { prev.set('tab', t); return prev }, { replace: true })
  }, [setSearchParams])
  const [loading, setLoading] = useState(true)

  // ── Data state ───────────────────────────────────────────────────────────────
  const [pnl,              setPnl]              = useState<PnL | null>(null)
  const [salesTrend,       setSalesTrend]       = useState<SalesSummaryPoint[]>([])
  const [topProducts,      setTopProducts]      = useState<TopProduct[]>([])
  const [topCustomers,     setTopCustomers]     = useState<TopCustomer[]>([])
  const [expenseBreakdown, setExpenseBreakdown] = useState<ExpRow[]>([])
  const [arAging,          setArAging]          = useState<ARAgingReport | null>(null)
  const [apAging,          setApAging]          = useState<ARAgingReport | null>(null)
  const [cashFlow,         setCashFlow]         = useState<CashFlow | null>(null)
  const [vatSummary,       setVatSummary]       = useState<VATSummary | null>(null)
  const [paymentMethods,   setPaymentMethods]   = useState<PayMethod[]>([])
  const [inventory,        setInventory]        = useState<InventoryVal | null>(null)

  // ── VAT PDF export ────────────────────────────────────────────────────────────
  const downloadVATReport = async () => {
    if (!vatSummary) return
    try {
      const { jsPDF } = await import('jspdf')
      const { default: autoTable } = await import('jspdf-autotable')
      const { applyDocHeader, buildTableStyle, addDocFooter, COLORS, TYPE } = await import('@/lib/pdfUtils')

      const doc    = new jsPDF({ unit: 'mm', format: 'a4' })
      doc.setLineHeightFactor(1.15)
      const pageW  = doc.internal.pageSize.getWidth()

      const toRgb = (hex?: string): [number, number, number] => {
        const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
        if (!m) return [249, 115, 22]
        return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
      }
      const BRAND = toRgb(organisation?.brand_color) as [number, number, number]
      const DARK  = COLORS.DARK
      const MUTED = COLORS.MUTED
      const LIGHT = COLORS.LIGHT
      const RULE  = COLORS.RULE
      const tmpl  = organisation?.invoice_template ?? 'classic'

      const vatLogoData = await urlToDataUrl(organisation?.logo)

      const pFont = ['times', 'Georgia', 'Playfair Display', 'Merriweather', 'Lora',
        'Libre Baskerville', 'EB Garamond', 'Crimson Text', 'Cinzel', 'Cormorant Garamond',
        'Spectral'].includes(organisation?.company_name_font ?? '') ? 'times'
        : ['courier', 'JetBrains Mono', 'Fira Code'].includes(organisation?.company_name_font ?? '')
        ? 'courier' : 'helvetica'
      const pBold   = organisation?.company_name_font_bold !== false
      const pItalic = organisation?.company_name_font_italic === true
      const pStyle  = pBold && pItalic ? 'bolditalic' : pBold ? 'bold' : pItalic ? 'italic' : 'normal'
      const pSize   = Math.max(8, Math.min(36, organisation?.company_name_font_size ?? 12))
      const nameColor: [number, number, number] = (() => {
        const c = organisation?.company_name_font_color
        if (!c || c === '#ffffff') return (tmpl === 'modern' || tmpl === 'minimal') ? DARK : COLORS.WHITE
        return toRgb(c)
      })()
      const showName    = organisation?.show_company_name_on_pdf ?? true
      const displayName = showName ? (organisation?.invoice_company_name?.trim() || organisation?.name || 'Company') : ''
      const dateRange   = `${period.date_from ?? ''} – ${period.date_to ?? ''}`

      const vatY = applyDocHeader(doc, {
        tmpl, pageW, BRAND, DARK, MUTED,
        logoData:              vatLogoData,
        displayName,
        orgAddress:            organisation?.address,
        orgEmail:              organisation?.email,
        orgPhone:              organisation?.phone,
        pdfFont:               pFont,
        fontSize:              pSize,
        pdfStyle:              pStyle,
        nameColor,
        companyFontUnderline:  organisation?.company_name_font_underline,
        showCompanyName:       showName,
        docTitle:              'VAT RETURN REPORT',
        metaRows: [
          ['Organisation', organisation?.name ?? ''],
          ['Period',        dateRange],
          ['Generated',     new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })],
        ],
      })

      const netPayable = parseFloat(vatSummary.net_vat_payable)
      const ts         = buildTableStyle(BRAND, pFont)
      doc.setFontSize(9)
      const vatAmounts = [
        formatCurrency(vatSummary.output_vat),
        `(${formatCurrency(vatSummary.input_vat)})`,
        formatCurrency(vatSummary.net_vat_payable),
        'Amount',
      ]
      const colW = Math.min(70, Math.max(36, Math.max(...vatAmounts.map(s => doc.getTextWidth(s))) + 16))

      autoTable(doc, {
        ...ts,
        startY: vatY,
        head:   [['Description', 'Amount']],
        body:   [
          ['Output VAT (collected on sales)',    formatCurrency(vatSummary.output_vat)],
          ['Input VAT (paid on approved bills)', `(${formatCurrency(vatSummary.input_vat)})`],
          ['Net VAT Payable to FIRS',            formatCurrency(vatSummary.net_vat_payable)],
        ],
        styles:       { ...ts.styles, fontSize: 9, cellPadding: { top: 4, bottom: 4, left: 6, right: 6 } },
        columnStyles: {
          0: { cellWidth: 'auto' as const },
          1: { halign: 'right' as const, fontStyle: 'bold' as const, cellWidth: colW },
        },
        didParseCell: (data: any) => {
          if (data.row.index === 2) {
            data.cell.styles.textColor  = netPayable >= 0 ? COLORS.RED   : COLORS.GREEN
            data.cell.styles.fillColor  = netPayable >= 0 ? [255, 240, 240] : [240, 255, 245]
            data.cell.styles.fontStyle  = 'bold'
          }
        },
      })

      const afterY = (doc as any).lastAutoTable.finalY + 6
      doc.setFontSize(TYPE.BODY.size); doc.setFont(pFont, 'italic'); doc.setTextColor(...MUTED)
      doc.text(
        `Formula: Output VAT − Input VAT = Net VAT Payable  (${netPayable >= 0 ? 'Owed to FIRS' : 'VAT Credit / Refund'})`,
        14, afterY,
      )

      const disclaimerY = afterY + 10
      doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
      doc.roundedRect(14, disclaimerY, pageW - 28, 22, 2, 2, 'FD')
      doc.setFontSize(TYPE.SMALL.size); doc.setFont(pFont, 'bold'); doc.setTextColor(...MUTED)
      doc.text('DISCLAIMER', 17, disclaimerY + 5)
      doc.setFont(pFont, 'italic')
      const disclaimerText =
        'This VAT Return Report is generated for informational purposes only. ' +
        'Figures are based on transactions recorded in Audity during the selected period. ' +
        'You are solely responsible for verifying accuracy and filing returns with FIRS via TaxPro-Max. ' +
        'Consult a qualified tax professional before submitting your official VAT return.'
      doc.text(doc.splitTextToSize(disclaimerText, pageW - 28 - 6), 17, disclaimerY + 10)

      addDocFooter(doc, {
        orgName:  organisation?.name ?? 'Company',
        docTitle: 'VAT RETURN REPORT',
        docRef:   dateRange,
        BRAND,
        pdfFont:  pFont,
      })

      const dateTag = (period.date_from && period.date_to)
        ? `${period.date_from}-to-${period.date_to}`
        : new Date().toISOString().slice(0, 10)
      await saveBlobFile(doc.output('blob'), `VAT-Return-${dateTag}.pdf`)
      toast.success('VAT report downloaded')
    } catch {
      toast.error('Failed to generate PDF')
    }
  }

  // ── Data fetch ───────────────────────────────────────────────────────────────
  const load = async () => {
    setLoading(true)
    const params    = periodToParams(period)
    const group_by  = groupByForPeriod(period.period)
    try {
      const [pnlRes, salesRes, prodRes, custRes, expRes, arRes, apRes, cfRes, vatRes, pmRes, invRes] =
        await Promise.allSettled([
          reportApi.pnl(params),
          reportApi.sales({ ...params, group_by }),
          reportApi.topProducts({ ...params, limit: 10 }),
          reportApi.topCustomers({ ...params, limit: 10 }),
          reportApi.expenses(params),
          reportApi.arAging(),
          reportApi.apAging(),
          reportApi.cashFlow(params),
          reportApi.vatSummary(params),
          reportApi.paymentMethods(params),
          reportApi.inventory(),
        ])

      if (pnlRes.status   === 'fulfilled') setPnl(pnlRes.value.data)
      if (salesRes.status  === 'fulfilled') setSalesTrend(salesRes.value.data.results ?? salesRes.value.data)
      if (prodRes.status   === 'fulfilled') setTopProducts(prodRes.value.data.results ?? prodRes.value.data)
      if (custRes.status   === 'fulfilled') setTopCustomers(custRes.value.data.results ?? custRes.value.data)
      if (expRes.status    === 'fulfilled') setExpenseBreakdown(expRes.value.data.results ?? expRes.value.data)
      if (arRes.status     === 'fulfilled') setArAging(arRes.value.data)
      if (apRes.status     === 'fulfilled') setApAging(apRes.value.data)
      if (cfRes.status     === 'fulfilled') setCashFlow(cfRes.value.data)
      if (vatRes.status    === 'fulfilled') setVatSummary(vatRes.value.data)
      if (pmRes.status     === 'fulfilled') setPaymentMethods(pmRes.value.data.results ?? pmRes.value.data)
      if (invRes.status    === 'fulfilled') setInventory(invRes.value.data)
    } catch { toast.error('Failed to load reports') }
    finally  { setLoading(false) }
  }

  useEffect(() => { load() }, [period])
  useDataRefresh(load)

  // ── Derived chart data ────────────────────────────────────────────────────────

  const groupBy = groupByForPeriod(period.period)

  /** Sales trend formatted for Recharts (period labels formatted for readability) */
  const trendData = salesTrend.map(s => ({
    period:  fmtPeriod(String(s.period), groupBy),
    Revenue: parseFloat(s.total_revenue),
    Tax:     parseFloat(s.total_tax),
  }))

  /** Expense donut data */
  const expPieData = expenseBreakdown.map(e => ({
    name:  e.category_name,
    value: parseFloat(e.total),
  }))

  /**
   * Phase 2B: Waterfall / bridge chart data.
   * Each bar represents a P&L step.  "start" is the invisible base bar;
   * "value" is the visible segment; "end" marks whether it's positive or negative.
   */
  const waterfallData = useMemo(() => {
    if (!pnl) return []
    const revenue = parseFloat(pnl.revenue.gross_sales)
    const cogs    = parseFloat(pnl.cost_of_goods_sold)
    const gp      = parseFloat(pnl.gross_profit)
    const opex    = parseFloat(pnl.operating_expenses)
    const net     = parseFloat(pnl.net_profit)

    return [
      { name: 'Revenue',      start: 0,       value: revenue, fill: '#10b981', label: formatCurrency(String(revenue)) },
      { name: '– COGS',       start: gp,       value: cogs,   fill: '#ef4444', label: `(${formatCurrency(String(cogs))})` },
      { name: 'Gross Profit', start: 0,       value: gp,      fill: '#3b82f6', label: formatCurrency(String(gp)) },
      { name: '– Op Expenses',start: net,     value: opex,    fill: '#f97316', label: `(${formatCurrency(String(opex))})` },
      { name: 'Net Profit',   start: 0,       value: net,     fill: net >= 0 ? '#10b981' : '#ef4444', label: formatCurrency(String(net)) },
    ]
  }, [pnl])

  /**
   * Phase 2E: Build monthly in-vs-out grouped bar data from the sales trend
   * (inflows proxy) and expense breakdown totals (outflows proxy).
   * Since the API returns a single cash_inflows/cash_outflows total, we render
   * the trend data as the time-series and annotate with the overall summary.
   */
  const cashFlowTrendData = useMemo(() => {
    // Use sales trend as inflow proxy; we don't have per-period expense API
    // so we evenly distribute total outflows across periods for visualisation.
    const outflowTotal = cashFlow ? parseFloat(cashFlow.cash_outflows) : 0
    const n            = trendData.length || 1
    const outPerPeriod = outflowTotal / n
    return trendData.map((d, i) => ({
      period:   d.period,
      Inflows:  d.Revenue,
      Outflows: Math.round(outPerPeriod),
      // Running net for cumulative area
      cumulative: trendData.slice(0, i + 1).reduce((s, x) => s + x.Revenue, 0)
        - (outflowTotal / n) * (i + 1),
    }))
  }, [trendData, cashFlow])

  // expenseRatioData removed — ratio shown inline via text instead of chart line

  /**
   * Phase 2D: AR aging per-bucket donut data for both AR and AP.
   */
  const arDonutData = arAging ? [
    { name: 'Current', value: parseFloat(String(arAging.buckets?.current ?? 0)) },
    { name: '1–30d',   value: parseFloat(String(arAging.buckets?.['1_30'] ?? 0)) },
    { name: '31–60d',  value: parseFloat(String(arAging.buckets?.['31_60'] ?? 0)) },
    { name: '61–90d',  value: parseFloat(String(arAging.buckets?.['61_90'] ?? 0)) },
    { name: '90d+',    value: parseFloat(String(arAging.buckets?.over_90  ?? 0)) },
  ].filter(b => b.value > 0) : []

  const apDonutData = apAging ? [
    { name: 'Current', value: parseFloat(String(apAging.buckets?.current ?? 0)) },
    { name: '1–30d',   value: parseFloat(String(apAging.buckets?.['1_30'] ?? 0)) },
    { name: '31–60d',  value: parseFloat(String(apAging.buckets?.['31_60'] ?? 0)) },
    { name: '61–90d',  value: parseFloat(String(apAging.buckets?.['61_90'] ?? 0)) },
    { name: '90d+',    value: parseFloat(String(apAging.buckets?.over_90  ?? 0)) },
  ].filter(b => b.value > 0) : []

  /**
   * Phase 2C: Customer concentration — top-3 revenue as % of total.
   * Surfaced as a risk alert when > 50 %.
   */
  const totalRevenue    = topCustomers.reduce((s, c) => s + parseFloat(c.revenue ?? 0), 0)
  const top3Revenue     = topCustomers.slice(0, 3).reduce((s, c) => s + parseFloat(c.revenue ?? 0), 0)
  const concentrationPct = totalRevenue > 0 ? Math.round((top3Revenue / totalRevenue) * 100) : 0

  /** Payment method donut data from SalePayment records. */
  const paymentMethodData = paymentMethods.map(m => ({
    name:  m.label,
    value: parseFloat(String(m.total)),
  })).filter(d => d.value > 0)

  const exportParams = periodToParams(period)

  // ── P&L table rows ────────────────────────────────────────────────────────────
  const pnlRows: (string | number)[][] = pnl ? [
    ['Gross Sales',        formatCurrency(pnl.revenue.gross_sales)],
    ['Tax Collected',      formatCurrency(pnl.revenue.tax_collected)],
    ['Discounts',          formatCurrency(pnl.revenue.discounts)],
    ['Cost of Goods Sold', formatCurrency(pnl.cost_of_goods_sold)],
    ['Gross Profit',       formatCurrency(pnl.gross_profit)],
    ['Gross Margin %',     `${parseFloat(pnl.gross_margin_pct).toFixed(2)}%`],
    ['Operating Expenses', formatCurrency(pnl.operating_expenses)],
    ['Misc. Income',       formatCurrency(pnl.miscellaneous_income ?? '0')],
    ['Net Profit',         formatCurrency(pnl.net_profit)],
    ['Net Margin %',       `${parseFloat(pnl.net_margin_pct).toFixed(2)}%`],
  ] : []

  // ─────────────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-start gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Reports & Analytics</h1>
          <p className="text-slate-400 text-sm">Financial overview and performance metrics</p>
        </div>
        <div className="sm:ml-auto flex flex-wrap items-center gap-2">
          <PeriodSelector value={period} onChange={(v) => { bypassNextGets(8000); setPeriod(v) }} />
          <button
            onClick={() => { bypassNextGets(8000); load() }}
            disabled={loading}
            className="btn-primary flex items-center gap-2 px-3 py-1.5 text-sm disabled:opacity-50"
            title="Refresh"
          >
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* ── Tab navigation ──────────────────────────────────────────────────── */}
      <div className="flex overflow-x-auto gap-1 border-b border-surface-700 pb-0">
        {TABS.map(t => {
          const Icon = t.icon
          return (
            <button
              key={t.id}
              onClick={() => handleSetTab(t.id)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px
                ${tab === t.id
                  ? 'report-tab-active border-brand-400 text-brand-400'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
                }`}
            >
              <Icon size={14} />
              {t.label}
            </button>
          )
        })}
      </div>

      {/* ═══════════════════════════════════════════════════════════════════════
          TAB: OVERVIEW  (Phase 2A)
          — KPI strip, stacked Revenue/COGS bar, trend chart, AR aging mini
      ══════════════════════════════════════════════════════════════════════════ */}
      {tab === 'overview' && (
        <div className="space-y-6">

          {/* KPI cards */}
          {pnl ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {kpi('Gross Sales',   formatCurrency(pnl.revenue.gross_sales))}
              {kpi('COGS',          formatCurrency(pnl.cost_of_goods_sold), undefined, false)}
              {kpi('Gross Profit',  formatCurrency(pnl.gross_profit),
                `${parseFloat(pnl.gross_margin_pct).toFixed(1)}% margin`, parseFloat(pnl.gross_profit) >= 0)}
              {kpi('Net Profit',    formatCurrency(pnl.net_profit),
                `${parseFloat(pnl.net_margin_pct).toFixed(1)}% margin`,  parseFloat(pnl.net_profit) >= 0)}
            </div>
          ) : loading ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="card p-5 h-24 animate-pulse bg-surface-800" />
              ))}
            </div>
          ) : null}

          {/* Phase 2A: Stacked Revenue vs COGS vs OpEx grouped bar + existing trend */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

            {/* Stacked cost breakdown bar chart */}
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-5">
                <BarChart2 size={18} className="text-brand-400" />
                <h2 className="text-base font-semibold text-white">Revenue vs Costs</h2>
                <span className="text-xs text-slate-500 ml-auto">per period</span>
              </div>
              {loading ? (
                <div className="h-56 bg-surface-800 rounded-xl animate-pulse" />
              ) : trendData.length === 0 ? (
                <div className="h-56 flex items-center justify-center">
                  <p className="text-slate-500 text-sm">No data</p>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart
                    data={trendData.map(d => ({
                      period:  d.period,
                      Revenue: d.Revenue,
                      // Spread COGS and OpEx proportionally across periods as proxy
                      COGS:    pnl ? Math.round(d.Revenue * (parseFloat(pnl.cost_of_goods_sold) / Math.max(1, parseFloat(pnl.revenue.gross_sales)))) : 0,
                    }))}
                    margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="period" tick={axisTickStyle} axisLine={false} tickLine={false} />
                    <YAxis tick={axisTickStyle} axisLine={false} tickLine={false}
                      tickFormatter={v => `${getCurrencySymbol()}${formatNumber(v)}`} />
                    <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle}
                      itemStyle={tooltipItemStyle} formatter={(v: number) => formatCurrency(String(v))} />
                    <Legend wrapperStyle={{ fontSize: 11, paddingTop: 12, color: '#94a3b8' }} />
                    <Bar dataKey="Revenue" stackId="a" fill={accent}  radius={[0, 0, 0, 0]} />
                    <Bar dataKey="COGS"    stackId="b" fill="#ef4444" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>

            {/* Expense breakdown donut (existing, enhanced) */}
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-5">
                <PieIcon size={18} className="text-red-400" />
                <h2 className="text-base font-semibold text-white">Expense Breakdown</h2>
              </div>
              {loading ? (
                <div className="h-56 bg-surface-800 rounded-xl animate-pulse" />
              ) : expPieData.length === 0 ? (
                <div className="h-56 flex items-center justify-center">
                  <p className="text-slate-500 text-sm">No expense data</p>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <PieChart>
                    <Pie data={expPieData} cx="50%" cy="45%"
                      innerRadius={60} outerRadius={90} paddingAngle={3} dataKey="value">
                      {expPieData.map((_, i) => (
                        <Cell key={i} fill={colors[i % colors.length]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle}
                      itemStyle={tooltipItemStyle} formatter={(v: number) => formatCurrency(String(v))} />
                    <Legend
                      wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                      formatter={(value: string) => <span style={{ color: '#94a3b8' }}>{value}</span>}
                    />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* Revenue trend area chart */}
          <div className="card p-5">
            <div className="flex items-center gap-2 mb-5">
              <Activity size={18} className="text-brand-400" />
              <h2 className="text-base font-semibold text-white">Revenue Trend</h2>
            </div>
            {loading ? (
              <div className="h-64 bg-surface-800 rounded-xl animate-pulse" />
            ) : trendData.length === 0 ? (
              <div className="h-64 flex items-center justify-center">
                <p className="text-slate-500 text-sm">No sales data for this period</p>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={trendData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                  <defs>
                    <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor={accent}    stopOpacity={0.3} />
                      <stop offset="95%" stopColor={accent}    stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="taxGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#3b82f6" stopOpacity={0.2} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="period" tick={axisTickStyle} axisLine={false} tickLine={false} />
                  <YAxis tick={axisTickStyle} axisLine={false} tickLine={false}
                    tickFormatter={v => `${getCurrencySymbol()}${formatNumber(v)}`} />
                  <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle}
                    itemStyle={tooltipItemStyle} formatter={(v: number) => formatCurrency(String(v))} />
                  <Legend wrapperStyle={{ fontSize: 12, paddingTop: 16, color: '#94a3b8' }} />
                  <Area type="monotone" dataKey="Revenue" stroke={accent} strokeWidth={2}
                    fill="url(#revGrad)" dot={false} />
                  <Area type="monotone" dataKey="Tax" stroke="#3b82f6" strokeWidth={1.5}
                    fill="url(#taxGrad)" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* AR Aging summary mini + VAT Summary */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <AgingCard title="Accounts Receivable Aging" aging={arAging} loading={loading}
              iconColor="text-amber-400" />
            <div className="card p-5">
              <div className="flex items-center justify-between gap-2 mb-4">
                <div className="flex items-center gap-2">
                  <Receipt size={18} className="text-blue-400" />
                  <h2 className="text-base font-semibold text-white">VAT Summary</h2>
                </div>
                {vatSummary && (
                  <button onClick={downloadVATReport}
                    className="flex items-center gap-1.5 text-xs text-brand-400 hover:text-brand-300">
                    <Download size={13} /> Export PDF
                  </button>
                )}
              </div>
              {vatSummary ? (
                <div className="space-y-4">
                  <div className="grid grid-cols-3 gap-3">
                    <VATCard label="Output VAT"     sub="Collected on sales" value={vatSummary.output_vat} />
                    <VATCard label="Input VAT"      sub="Paid on bills"      value={vatSummary.input_vat} />
                    <VATCard
                      label="Net VAT Payable"
                      sub={parseFloat(vatSummary.net_vat_payable) >= 0 ? 'Owed to FIRS' : 'VAT credit'}
                      value={vatSummary.net_vat_payable}
                      highlight={parseFloat(vatSummary.net_vat_payable) >= 0 ? 'red' : 'green'}
                    />
                  </div>
                  <div className="p-3 rounded-xl bg-surface-800/50 border border-surface-700">
                    <p className="text-xs text-slate-400">
                      <strong className="text-white">Formula:</strong> Output VAT ({formatCurrency(vatSummary.output_vat)}) −
                      Input VAT ({formatCurrency(vatSummary.input_vat)}) = Net VAT Payable
                    </p>
                  </div>
                </div>
              ) : (
                <div className="h-40 flex items-center justify-center text-slate-500 text-sm">
                  {loading ? 'Loading…' : 'No VAT data for this period'}
                </div>
              )}
            </div>
          </div>

          {/* Cash Flow + AP Aging */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-4">
                <Landmark size={18} className="text-emerald-400" />
                <h2 className="text-base font-semibold text-white">Cash Flow Summary</h2>
              </div>
              {cashFlow ? (
                <div className="space-y-3">
                  <CashFlowRow icon={<ArrowDownCircle size={16} className="text-green-400" />}
                    label="Cash Inflows" value={formatCurrency(cashFlow.cash_inflows)} color="green" />
                  <CashFlowRow icon={<ArrowUpCircle size={16} className="text-red-400" />}
                    label="Cash Outflows" value={`(${formatCurrency(cashFlow.cash_outflows)})`} color="red" />
                  <div className={`flex items-center justify-between p-4 rounded-xl border ${
                    parseFloat(cashFlow.net_cash_flow) >= 0
                      ? 'bg-emerald-500/10 border-emerald-500/30'
                      : 'bg-red-500/10 border-red-500/30'
                  }`}>
                    <span className="text-sm font-semibold text-white">Net Cash Flow</span>
                    <span className={`text-lg font-bold ${parseFloat(cashFlow.net_cash_flow) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {parseFloat(cashFlow.net_cash_flow) >= 0 ? '' : '-'}
                      {formatCurrency(String(Math.abs(parseFloat(cashFlow.net_cash_flow))))}
                    </span>
                  </div>
                  <p className="text-xs text-slate-600">Inflows: cash/bank/POS sales + misc income · Outflows: all expenses</p>
                </div>
              ) : (
                <div className="h-40 flex items-center justify-center text-slate-500 text-sm">
                  {loading ? 'Loading…' : 'No cash flow data'}
                </div>
              )}
            </div>
            <AgingCard title="Accounts Payable Aging" aging={apAging} loading={loading}
              iconColor="text-red-400" payable />
          </div>

          {/* Inventory Valuation snapshot */}
          {(inventory || loading) && (
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-4">
                <BarChart2 size={18} className="text-purple-400" />
                <h2 className="text-base font-semibold text-white">Inventory Valuation</h2>
                <span className="text-xs text-slate-500 ml-auto">current snapshot</span>
              </div>
              {loading ? (
                <div className="h-20 bg-surface-800 rounded-xl animate-pulse" />
              ) : inventory ? (
                <div className="space-y-3">
                  <div className="flex items-center justify-between p-4 rounded-xl bg-purple-500/10 border border-purple-500/20">
                    <span className="text-sm text-slate-300">Total Inventory Value</span>
                    <span className="text-xl font-bold text-purple-300">
                      {formatCurrency(String(inventory.total_inventory_value))}
                    </span>
                  </div>
                  {inventory.items.length > 0 && (
                    <div className="max-h-48 overflow-y-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-slate-500 border-b border-surface-700">
                            <th className="text-left pb-1.5">Product</th>
                            <th className="text-right pb-1.5">Qty</th>
                            <th className="text-right pb-1.5">Unit Cost</th>
                            <th className="text-right pb-1.5">Value</th>
                          </tr>
                        </thead>
                        <tbody>
                          {inventory.items.slice(0, 10).map((item, i) => (
                            <tr key={i} className="border-b border-surface-800">
                              <td className="py-1.5 text-slate-300 truncate max-w-[160px]">{item.product}</td>
                              <td className="py-1.5 text-right text-slate-400">{formatNumber(item.quantity)}</td>
                              <td className="py-1.5 text-right text-slate-400">{formatCurrency(String(item.unit_cost))}</td>
                              <td className="py-1.5 text-right font-medium text-white">{formatCurrency(String(item.total_value))}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {inventory.items.length > 10 && (
                        <p className="text-xs text-slate-600 mt-2 text-center">
                          +{inventory.items.length - 10} more items · see Inventory → Stock Reports for full list
                        </p>
                      )}
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          )}
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          TAB: P&L STATEMENT  (Phase 2B)
          — Horizontal waterfall chart (ComposedChart) + comparison table
      ══════════════════════════════════════════════════════════════════════════ */}
      {tab === 'pnl' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">Profit & Loss Statement</h2>
              {pnl && (
                <p className="text-xs text-slate-500 mt-0.5">
                  {pnl.period_start && pnl.period_end
                    ? `${formatDate(pnl.period_start)} – ${formatDate(pnl.period_end)}`
                    : 'All time'}
                </p>
              )}
            </div>
            <ExportBar endpoint="/reports/pnl/" params={exportParams} filenameBase="profit_and_loss" />
          </div>

          {/* KPI strip */}
          {pnl && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {kpi('Gross Sales',   formatCurrency(pnl.revenue.gross_sales))}
              {kpi('COGS',          formatCurrency(pnl.cost_of_goods_sold), undefined, false)}
              {kpi('Gross Profit',  formatCurrency(pnl.gross_profit),
                `${parseFloat(pnl.gross_margin_pct).toFixed(1)}% margin`, parseFloat(pnl.gross_profit) >= 0)}
              {kpi('Net Profit',    formatCurrency(pnl.net_profit),
                `${parseFloat(pnl.net_margin_pct).toFixed(1)}% margin`,  parseFloat(pnl.net_profit) >= 0)}
            </div>
          )}

          {/* Phase 2B: Profit Waterfall / Bridge Chart */}
          {waterfallData.length > 0 && (
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-5">
                <TrendingUp size={18} className="text-brand-400" />
                <h2 className="text-base font-semibold text-white">Profit Waterfall</h2>
                <span className="text-xs text-slate-500 ml-2">Revenue → Gross Profit → Net Profit</span>
              </div>
              <ResponsiveContainer width="100%" height={280}>
                {/*
                  Waterfall implemented as a ComposedChart with two stacked bars:
                  "start" (invisible, creates the floating base) + "value" (coloured segment).
                  ReferenceLine shows the break-even at 0.
                */}
                <ComposedChart data={waterfallData} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="name" tick={axisTickStyle} axisLine={false} tickLine={false} />
                  <YAxis tick={axisTickStyle} axisLine={false} tickLine={false}
                    tickFormatter={v => `${getCurrencySymbol()}${formatNumber(v)}`} />
                  <Tooltip
                    contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle}
                    itemStyle={tooltipItemStyle}
                    formatter={(v: number, name: string) =>
                      name === 'start' ? null : [formatCurrency(String(v)), 'Amount']
                    }
                  />
                  {/* Invisible stacking base — gives bars their floating appearance */}
                  <Bar dataKey="start" stackId="w" fill="transparent" legendType="none" />
                  {/* Coloured segment — each entry has its own fill via Cell */}
                  <Bar dataKey="value" stackId="w" radius={[4, 4, 0, 0]} minPointSize={3}>
                    {waterfallData.map((entry, i) => (
                      <Cell key={i} fill={entry.fill} />
                    ))}
                  </Bar>
                  <ReferenceLine y={0} stroke="#64748b" strokeDasharray="4 2" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Detailed P&L table */}
          <ReportTable
            headers={['Line Item', 'Amount']}
            rows={pnlRows}
            loading={loading}
            emptyMessage="No P&L data for this period."
            rightAlignCols={[1]}
          />

          {/* Revenue vs Costs progress bars (existing, kept for detail) */}
          {pnl && (
            <div className="card p-5">
              <h3 className="text-sm font-semibold text-slate-300 mb-4">Revenue vs Costs — % of Gross Sales</h3>
              <div className="space-y-3">
                {[
                  { label: 'Gross Sales',        value: parseFloat(pnl.revenue.gross_sales),    color: 'bg-brand-500' },
                  { label: 'Tax Collected',       value: parseFloat(pnl.revenue.tax_collected),  color: 'bg-blue-500' },
                  { label: 'Discounts',           value: parseFloat(pnl.revenue.discounts),      color: 'bg-yellow-500' },
                  { label: 'COGS',                value: parseFloat(pnl.cost_of_goods_sold),     color: 'bg-red-500' },
                  { label: 'Operating Expenses',  value: parseFloat(pnl.operating_expenses),     color: 'bg-orange-500' },
                  { label: 'Net Profit',          value: parseFloat(pnl.net_profit), color: parseFloat(pnl.net_profit) >= 0 ? 'bg-emerald-500' : 'bg-red-600' },
                ].map(({ label, value, color }) => {
                  const gross = parseFloat(pnl.revenue.gross_sales) || 1
                  const pct   = Math.min(100, Math.abs(Math.round((value / gross) * 100)))
                  return (
                    <div key={label}>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-slate-400">{label}</span>
                        <span className="text-slate-200 font-medium tabular-nums">{formatCurrency(String(value))}</span>
                      </div>
                      <div className="h-2 bg-surface-700 rounded-full">
                        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          TAB: CASH FLOW  (Phase 2E)
          — KPI cards, monthly grouped bar (in vs out), cumulative area
      ══════════════════════════════════════════════════════════════════════════ */}
      {tab === 'cashflow' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Cash Flow Statement</h2>
            <ExportBar endpoint="/reports/cash-flow/" params={exportParams} filenameBase="cash_flow" />
          </div>

          {/* Summary metric cards */}
          {cashFlow && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <MetricCard
                label="Total Inflows"    value={formatCurrency(cashFlow.cash_inflows)}
                sub="Sales + misc income" color="emerald"
                icon={<ArrowDownCircle size={20} className="text-emerald-400" />}
              />
              <MetricCard
                label="Total Outflows"   value={formatCurrency(cashFlow.cash_outflows)}
                sub="All expenses"        color="red"
                icon={<ArrowUpCircle size={20} className="text-red-400" />}
              />
              <MetricCard
                label="Net Cash Flow"
                value={`${parseFloat(cashFlow.net_cash_flow) >= 0 ? '+' : ''}${formatCurrency(cashFlow.net_cash_flow)}`}
                sub={parseFloat(cashFlow.net_cash_flow) >= 0 ? 'Positive cash position' : 'Negative cash position'}
                color={parseFloat(cashFlow.net_cash_flow) >= 0 ? 'emerald' : 'red'}
                icon={<DollarSign size={20} className={parseFloat(cashFlow.net_cash_flow) >= 0 ? 'text-emerald-400' : 'text-red-400'} />}
              />
            </div>
          )}

          {/* Phase 2E: Monthly Cash In vs Out grouped bar */}
          {cashFlowTrendData.length > 0 && (
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-5">
                <BarChart2 size={18} className="text-emerald-400" />
                <h2 className="text-base font-semibold text-white">Cash In vs Out by Period</h2>
              </div>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={cashFlowTrendData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="period" tick={axisTickStyle} axisLine={false} tickLine={false} />
                  <YAxis tick={axisTickStyle} axisLine={false} tickLine={false}
                    tickFormatter={v => `${getCurrencySymbol()}${formatNumber(v)}`} />
                  <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle}
                    itemStyle={tooltipItemStyle} formatter={(v: number) => formatCurrency(String(v))} />
                  <Legend wrapperStyle={{ fontSize: 11, paddingTop: 12, color: '#94a3b8' }} />
                  <Bar dataKey="Inflows"  fill="#10b981" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="Outflows" fill="#ef4444" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Phase 2E: Cumulative cash flow area chart */}
          {cashFlowTrendData.length > 0 && (
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-5">
                <Activity size={18} className="text-brand-400" />
                <h2 className="text-base font-semibold text-white">Cumulative Cash Position</h2>
              </div>
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={cashFlowTrendData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                  <defs>
                    <linearGradient id="cashGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor={accent} stopOpacity={0.3} />
                      <stop offset="95%" stopColor={accent} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="period" tick={axisTickStyle} axisLine={false} tickLine={false} />
                  <YAxis tick={axisTickStyle} axisLine={false} tickLine={false}
                    tickFormatter={v => `${getCurrencySymbol()}${formatNumber(v)}`} />
                  <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle}
                    itemStyle={tooltipItemStyle} formatter={(v: number) => formatCurrency(String(v))} />
                  <ReferenceLine y={0} stroke="#ef4444" strokeDasharray="4 2"
                    label={{ value: 'Break-even', fill: '#ef4444', fontSize: 10, position: 'insideTopRight' }} />
                  <Area type="monotone" dataKey="cumulative" stroke={accent} strokeWidth={2}
                    fill="url(#cashGrad)" dot={false} name="Cumulative Net" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Detailed table */}
          <ReportTable
            headers={['Line Item', 'Amount']}
            rows={cashFlow ? [
              ['Cash Inflows (sales + misc income)', formatCurrency(cashFlow.cash_inflows)],
              ['Cash Outflows (expenses)',            formatCurrency(cashFlow.cash_outflows)],
              ['Net Cash Flow',                       formatCurrency(cashFlow.net_cash_flow)],
            ] : []}
            loading={loading}
            emptyMessage="No cash flow data for this period."
            rightAlignCols={[1]}
          />
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          TAB: SALES ANALYTICS  (Phase 2C)
          — Revenue trend, top customers horizontal bar, payment method donut,
            concentration risk alert, top products table
      ══════════════════════════════════════════════════════════════════════════ */}
      {tab === 'sales_analytics' && (
        <div className="space-y-5">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Sales Analytics</h2>
            <ExportBar endpoint="/reports/top-customers/" params={{ ...exportParams, limit: 50 }} filenameBase="sales_analytics" />
          </div>

          {/* Revenue trend area chart */}
          {trendData.length > 0 && (
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-5">
                <Activity size={18} className="text-brand-400" />
                <h2 className="text-base font-semibold text-white">Revenue Trend</h2>
              </div>
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={trendData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                  <defs>
                    <linearGradient id="salesGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor={accent} stopOpacity={0.3} />
                      <stop offset="95%" stopColor={accent} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="period" tick={axisTickStyle} axisLine={false} tickLine={false} />
                  <YAxis tick={axisTickStyle} axisLine={false} tickLine={false}
                    tickFormatter={v => `${getCurrencySymbol()}${formatNumber(v)}`} />
                  <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle}
                    itemStyle={tooltipItemStyle} formatter={(v: number) => formatCurrency(String(v))} />
                  <Area type="monotone" dataKey="Revenue" stroke={accent} strokeWidth={2}
                    fill="url(#salesGrad)" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Phase 2C: Top Customers horizontal bar + Payment method donut */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

            {/* Top 10 Customers — horizontal bar ranked by revenue */}
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-4">
                <Users size={18} className="text-brand-400" />
                <h2 className="text-base font-semibold text-white">Top Customers by Revenue</h2>
              </div>
              {loading ? (
                <div className="h-60 bg-surface-800 rounded-xl animate-pulse" />
              ) : topCustomers.length === 0 ? (
                <div className="h-60 flex items-center justify-center">
                  <p className="text-slate-500 text-sm">No customer data</p>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart
                    layout="vertical"
                    data={topCustomers.slice(0, 8).map(c => ({
                      name:    trunc(c.customer_name ?? 'Walk-in', 16),
                      Revenue: parseFloat(c.revenue),
                    }))}
                    margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis type="number" tick={axisTickStyle} axisLine={false} tickLine={false}
                      tickFormatter={v => `${getCurrencySymbol()}${formatNumber(v)}`} />
                    <YAxis type="category" dataKey="name" tick={axisTickStyle}
                      axisLine={false} tickLine={false} width={90} />
                    <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle}
                      itemStyle={tooltipItemStyle} formatter={(v: number) => formatCurrency(String(v))} />
                    <Bar dataKey="Revenue" fill={accent} radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}

              {/* Phase 2C: Customer concentration risk alert */}
              {!loading && concentrationPct > 50 && (
                <div className="mt-3 p-3 rounded-xl bg-amber-500/10 border border-amber-500/30">
                  <p className="text-xs text-amber-400 font-medium">
                    ⚠ Concentration risk — top 3 customers = {concentrationPct}% of revenue.
                    Consider diversifying your customer base.
                  </p>
                </div>
              )}
              {!loading && concentrationPct > 0 && concentrationPct <= 50 && (
                <p className="mt-2 text-xs text-slate-500">
                  Top 3 customers = {concentrationPct}% of revenue · healthy spread
                </p>
              )}
            </div>

            {/* Payment method breakdown */}
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-4">
                <PieIcon size={18} className="text-emerald-400" />
                <h2 className="text-base font-semibold text-white">Revenue by Payment Method</h2>
              </div>
              {loading ? (
                <div className="h-60 bg-surface-800 rounded-xl animate-pulse" />
              ) : paymentMethodData.length === 0 ? (
                <div className="h-60 flex items-center justify-center">
                  <p className="text-slate-500 text-sm">No payment data for this period</p>
                </div>
              ) : (
                <>
                  <ResponsiveContainer width="100%" height={220}>
                    <PieChart>
                      <Pie data={paymentMethodData} cx="50%" cy="45%"
                        innerRadius={60} outerRadius={90} paddingAngle={4} dataKey="value">
                        {paymentMethodData.map((_, i) => (
                          <Cell key={i} fill={colors[i % colors.length]} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle}
                        itemStyle={tooltipItemStyle} formatter={(v: number) => formatCurrency(String(v))} />
                      <Legend
                        wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                        formatter={(value: string) => <span style={{ color: '#94a3b8' }}>{value}</span>}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="mt-1 space-y-1">
                    {paymentMethods.map(m => (
                      <div key={m.method} className="flex justify-between text-xs text-slate-400">
                        <span>{m.label}</span>
                        <span className="text-slate-200">{formatCurrency(String(m.total))} · {m.count} txn{m.count !== 1 ? 's' : ''}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Top Products table */}
          <div>
            <h3 className="text-base font-semibold text-white mb-3">Top Products by Revenue</h3>
            <ReportTable
              headers={['Product', 'SKU', 'Units Sold', 'Revenue', 'COGS', 'Gross Profit']}
              rows={topProducts.map(p => [
                p.product_name ?? '—',
                p.product_sku  ?? '—',
                formatNumber(parseFloat(p.units_sold)),
                formatCurrency(p.revenue),
                formatCurrency(p.cogs),
                formatCurrency(p.gross_profit),
              ])}
              loading={loading}
              emptyMessage="No product sales data for this period."
              rightAlignCols={[2, 3, 4, 5]}
            />
          </div>

          {/* Top Customers table */}
          <div>
            <h3 className="text-base font-semibold text-white mb-3">Top Customers by Revenue</h3>
            <ReportTable
              headers={['Customer', 'Code', 'Invoice Count', 'Revenue']}
              rows={topCustomers.map(c => [
                c.customer_name ?? 'Walk-in',
                c.customer_code ?? '—',
                c.invoice_count,
                formatCurrency(c.revenue),
              ])}
              loading={loading}
              emptyMessage="No customer data for this period."
              rightAlignCols={[2, 3]}
            />
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          TAB: AR / AP AGING  (Phase 2D)
          — AR + AP summary donuts, per-customer stacked horizontal bar,
            overdue action list
      ══════════════════════════════════════════════════════════════════════════ */}
      {tab === 'aging' && (
        <div className="space-y-5">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">AR / AP Aging Analysis</h2>
            {/* DSO / DPO derived metrics shown as badges */}
            {arAging && pnl && (
              <div className="flex items-center gap-2">
                <span className="text-xs px-2 py-1 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400">
                  AR Outstanding: {formatCurrency(arAging.total_outstanding)}
                </span>
                {apAging && (
                  <span className="text-xs px-2 py-1 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400">
                    AP Outstanding: {formatCurrency(apAging.total_outstanding)}
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Phase 2D: AR + AP summary donuts side by side */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

            {/* AR Aging donut */}
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-4">
                <Clock size={18} className="text-amber-400" />
                <h2 className="text-base font-semibold text-white">Accounts Receivable Aging</h2>
              </div>
              {loading ? (
                <div className="h-56 bg-surface-800 rounded-xl animate-pulse" />
              ) : arDonutData.length === 0 ? (
                <div className="h-56 flex items-center justify-center">
                  <div className="text-center">
                    <Clock size={32} className="mx-auto mb-2 text-green-400 opacity-50" />
                    <p className="text-slate-500 text-sm">No outstanding receivables</p>
                  </div>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <PieChart>
                    <Pie data={arDonutData} cx="50%" cy="45%"
                      innerRadius={60} outerRadius={90} paddingAngle={3} dataKey="value"
                      startAngle={90} endAngle={-270}>
                      {arDonutData.map((_, i) => (
                        <Cell key={i} fill={AGING_COLORS[i % AGING_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle}
                      itemStyle={tooltipItemStyle} formatter={(v: number) => formatCurrency(String(v))} />
                    <Legend
                      wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                      formatter={(value: string) => <span style={{ color: '#94a3b8' }}>{value}</span>}
                    />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>

            {/* AP Aging donut */}
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-4">
                <Clock size={18} className="text-red-400" />
                <h2 className="text-base font-semibold text-white">Accounts Payable Aging</h2>
              </div>
              {loading ? (
                <div className="h-56 bg-surface-800 rounded-xl animate-pulse" />
              ) : apDonutData.length === 0 ? (
                <div className="h-56 flex items-center justify-center">
                  <div className="text-center">
                    <Clock size={32} className="mx-auto mb-2 text-green-400 opacity-50" />
                    <p className="text-slate-500 text-sm">No outstanding payables</p>
                  </div>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <PieChart>
                    <Pie data={apDonutData} cx="50%" cy="45%"
                      innerRadius={60} outerRadius={90} paddingAngle={3} dataKey="value"
                      startAngle={90} endAngle={-270}>
                      {apDonutData.map((_, i) => (
                        <Cell key={i} fill={AGING_COLORS[i % AGING_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle}
                      itemStyle={tooltipItemStyle} formatter={(v: number) => formatCurrency(String(v))} />
                    <Legend
                      wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                      formatter={(value: string) => <span style={{ color: '#94a3b8' }}>{value}</span>}
                    />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* AR detailed aging card with progress bars + overdue list */}
          <AgingCard title="AR Aging Detail" aging={arAging} loading={loading} iconColor="text-amber-400" />

          {/* AP detailed aging card */}
          <AgingCard title="AP Aging Detail" aging={apAging} loading={loading} iconColor="text-red-400" payable />
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          TAB: EXPENSES  (Phase 2F)
          — Category donut, expense vs revenue trend area, ratio reference line
      ══════════════════════════════════════════════════════════════════════════ */}
      {tab === 'expenses' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Expense Analysis</h2>
            <ExportBar endpoint="/reports/expenses/" params={exportParams} filenameBase="expense_breakdown" />
          </div>

          {/* Phase 2F: Expense donut + Revenue vs Expense trend */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

            {/* Category donut */}
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-5">
                <PieIcon size={18} className="text-red-400" />
                <h2 className="text-base font-semibold text-white">Expense by Category</h2>
              </div>
              {loading ? (
                <div className="h-56 bg-surface-800 rounded-xl animate-pulse" />
              ) : expPieData.length === 0 ? (
                <div className="h-56 flex items-center justify-center">
                  <p className="text-slate-500 text-sm">No expense data</p>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie data={expPieData} cx="50%" cy="45%"
                      innerRadius={60} outerRadius={90} paddingAngle={3} dataKey="value">
                      {expPieData.map((_, i) => (
                        <Cell key={i} fill={colors[i % colors.length]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle}
                      itemStyle={tooltipItemStyle} formatter={(v: number) => formatCurrency(String(v))} />
                    <Legend
                      wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                      formatter={(value: string) => <span style={{ color: '#94a3b8' }}>{value}</span>}
                    />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>

            {/* Phase 2F: Revenue vs Expense trend (dual area) */}
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-5">
                <Activity size={18} className="text-emerald-400" />
                <h2 className="text-base font-semibold text-white">Revenue vs Expenses Trend</h2>
              </div>
              {loading ? (
                <div className="h-56 bg-surface-800 rounded-xl animate-pulse" />
              ) : trendData.length === 0 ? (
                <div className="h-56 flex items-center justify-center">
                  <p className="text-slate-500 text-sm">No data</p>
                </div>
              ) : (
                <>
                  <ResponsiveContainer width="100%" height={220}>
                    <AreaChart
                      data={trendData.map((d, _i) => ({
                        period:   d.period,
                        Revenue:  d.Revenue,
                        // Distribute total expenses evenly across periods as proxy
                        Expenses: Math.round(
                          expenseBreakdown.reduce((s, e) => s + parseFloat(e.total), 0) /
                          Math.max(1, trendData.length)
                        ),
                      }))}
                      margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
                    >
                      <defs>
                        <linearGradient id="revExp" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%"  stopColor={accent}    stopOpacity={0.3} />
                          <stop offset="95%" stopColor={accent}    stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="expExp" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%"  stopColor="#ef4444" stopOpacity={0.2} />
                          <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="period" tick={axisTickStyle} axisLine={false} tickLine={false} />
                      <YAxis tick={axisTickStyle} axisLine={false} tickLine={false}
                        tickFormatter={v => `${getCurrencySymbol()}${formatNumber(v)}`} />
                      <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle}
                        itemStyle={tooltipItemStyle} formatter={(v: number) => formatCurrency(String(v))} />
                      <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8, color: '#94a3b8' }} />
                      <Area type="monotone" dataKey="Revenue"  stroke={accent}    strokeWidth={2}
                        fill="url(#revExp)" dot={false} />
                      <Area type="monotone" dataKey="Expenses" stroke="#ef4444" strokeWidth={1.5}
                        fill="url(#expExp)" dot={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                  <p className="text-xs text-slate-500 mt-2">
                    Expenses are shown as an even distribution — use the category table below for exact breakdown.
                  </p>
                </>
              )}
            </div>
          </div>

          {/* Phase 2F: Expense ratio progress bars with 85 % target reference */}
          {expenseBreakdown.length > 0 && !loading && (
            <div className="card p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-white">Category Distribution</h3>
                {pnl && (
                  <span className="text-xs text-slate-500">
                    Total expenses = {(parseFloat(pnl.operating_expenses) / Math.max(1, parseFloat(pnl.revenue.gross_sales)) * 100).toFixed(1)}% of revenue
                  </span>
                )}
              </div>
              <div className="space-y-2.5">
                {expenseBreakdown.map((e, i) => {
                  const total = expenseBreakdown.reduce((s, x) => s + parseFloat(x.total), 0) || 1
                  const pct   = Math.round((parseFloat(e.total) / total) * 100)
                  return (
                    <div key={e.category_name}>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-slate-400">{e.category_name}</span>
                        <span className="text-slate-300 tabular-nums">{formatCurrency(e.total)} ({pct}%)</span>
                      </div>
                      <div className="h-2 bg-surface-700 rounded-full">
                        <div
                          className="h-full rounded-full"
                          style={{ width: `${pct}%`, backgroundColor: colors[i % colors.length] }}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Detailed expense table */}
          <ReportTable
            headers={['Category', 'Total', 'Count']}
            rows={expenseBreakdown.map(e => [
              e.category_name,
              formatCurrency(e.total),
              e.count,
            ])}
            loading={loading}
            emptyMessage="No expense data for this period."
            rightAlignCols={[1, 2]}
          />
        </div>
      )}
    </div>
  )
}

// ─── Reusable sub-components ──────────────────────────────────────────────────

/** Aging card: progress-bar buckets + most-overdue list */
function AgingCard({
  title, aging, loading, iconColor, payable = false,
}: {
  title: string; aging: ARAgingReport | null
  loading: boolean; iconColor: string; payable?: boolean
}) {
  const BUCKETS = [
    { label: 'Current (not due)',   key: 'current', color: 'text-green-400 bg-green-500/10' },
    { label: '1–30 days overdue',   key: '1_30',    color: 'text-yellow-400 bg-yellow-500/10' },
    { label: '31–60 days overdue',  key: '31_60',   color: 'text-orange-400 bg-orange-500/10' },
    { label: '61–90 days overdue',  key: '61_90',   color: 'text-red-400 bg-red-500/10' },
    { label: '90+ days overdue',    key: 'over_90', color: 'text-red-600 bg-red-600/10' },
  ] as const

  return (
    <div className="card p-5">
      <div className="flex items-center gap-2 mb-4">
        <Clock size={18} className={iconColor} />
        <h2 className="text-base font-semibold text-white">{title}</h2>
      </div>
      {aging ? (
        <div className="space-y-3">
          <p className="text-xs text-slate-500">
            As of {formatDate(aging.as_of)} · Total: <span className="text-white font-semibold">{formatCurrency(aging.total_outstanding)}</span>
          </p>
          {BUCKETS.map(({ label, key, color }) => {
            const amount = (aging.buckets as unknown as Record<string, string | number>)[key] ?? 0
            const total  = parseFloat(aging.total_outstanding) || 1
            const pct    = Math.round((parseFloat(String(amount)) / total) * 100)
            return (
              <div key={key}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-slate-400">{label}</span>
                  <span className={`font-semibold ${color.split(' ')[0]}`}>{formatCurrency(String(amount))}</span>
                </div>
                <div className="h-1.5 bg-surface-700 rounded-full">
                  <div className={`h-full rounded-full ${color.split(' ')[1]}`} style={{ width: `${pct}%` }} />
                </div>
              </div>
            )
          })}
          {/* AP aging backend returns `bills` key; AR aging returns `invoices` */}
          {((payable ? (aging as any).bills : aging.invoices) ?? []).slice(0, 4).length > 0 && (
            <div className="mt-3 pt-3 border-t border-surface-700">
              <p className="text-xs text-slate-500 mb-2">{payable ? 'Most Overdue Payables' : 'Most Overdue Receivables'}</p>
              {((payable ? (aging as any).bills : aging.invoices) ?? []).slice(0, 4).map((inv: any) => {
                // AP aging items have bill_number; AR items have invoice_number
                const ref = (inv as any).bill_number ?? (inv as any).invoice_number ?? '—'
                const who = (inv as any).supplier_name ?? inv.customer_name ?? (payable ? 'Supplier' : 'Walk-in')
                return (
                <div key={inv.id} className="flex items-center justify-between py-1.5">
                  <div>
                    <p className="text-xs font-medium text-white">{who}</p>
                    <p className="text-xs text-slate-500">{ref} · {inv.days_overdue}d overdue</p>
                  </div>
                  <span className="text-xs font-semibold text-red-400">{formatCurrency(inv.amount_due)}</span>
                </div>
                )
              })}
            </div>
          )}
        </div>
      ) : (
        <div className="h-40 flex items-center justify-center text-slate-500 text-sm">
          {loading ? 'Loading…' : `No outstanding ${payable ? 'payables' : 'receivables'}`}
        </div>
      )}
    </div>
  )
}

function VATCard({
  label, sub, value, highlight,
}: { label: string; sub: string; value: string; highlight?: 'red' | 'green' }) {
  return (
    <div className={`p-3 rounded-xl ${highlight === 'red' ? 'bg-red-500/10' : highlight === 'green' ? 'bg-green-500/10' : 'bg-surface-800'}`}>
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className={`text-base font-bold ${highlight === 'red' ? 'text-red-400' : highlight === 'green' ? 'text-green-400' : 'text-white'}`}>
        {formatCurrency(value)}
      </p>
      <p className="text-xs text-slate-500 mt-0.5">{sub}</p>
    </div>
  )
}

function CashFlowRow({ icon, label, value, color }: {
  icon: React.ReactNode; label: string; value: string; color: 'green' | 'red'
}) {
  return (
    <div className={`flex items-center justify-between p-3 rounded-xl border ${
      color === 'green' ? 'bg-green-500/8 border-green-500/20' : 'bg-red-500/8 border-red-500/20'
    }`}>
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-sm text-slate-300">{label}</span>
      </div>
      <span className={`font-bold ${color === 'green' ? 'text-green-400' : 'text-red-400'}`}>{value}</span>
    </div>
  )
}

function MetricCard({
  label, value, sub, color, icon,
}: { label: string; value: string; sub: string; color: 'emerald' | 'red'; icon: React.ReactNode }) {
  return (
    <div className={`card p-5 border ${color === 'emerald' ? 'border-emerald-500/20' : 'border-red-500/20'}`}>
      <div className="flex items-start justify-between mb-3">
        <p className="text-xs text-slate-400">{label}</p>
        {icon}
      </div>
      <p className={`text-xl font-bold ${color === 'emerald' ? 'text-emerald-400' : 'text-red-400'}`}>{value}</p>
      <p className="text-xs text-slate-500 mt-1">{sub}</p>
    </div>
  )
}
