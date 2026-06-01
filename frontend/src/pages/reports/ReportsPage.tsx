import { useEffect, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import {
  BarChart2, RefreshCw, TrendingDown, TrendingUp, Clock, Receipt,
  Download, ArrowDownCircle, ArrowUpCircle, Landmark, LayoutDashboard,
  FileText, Users, Package, DollarSign,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { reportApi, tauriFetch, bypassNextGets } from '@/services/api'
import { formatCurrency, formatNumber, formatDate, getCurrencySymbol } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import { saveBlobFile } from '@/lib/saveBlobFile'
import PeriodSelector, { type PeriodValue } from '@/components/PeriodSelector'
import ExportBar from '@/components/ExportBar'
import ReportTable from '@/components/ReportTable'
import type { PnL, SalesSummaryPoint, ARAgingReport, VATSummary } from '@/types'

// ─── Tab definitions ──────────────────────────────────────────────────────────

const TABS = [
  { id: 'overview',   label: 'Overview',      icon: LayoutDashboard },
  { id: 'pnl',        label: 'P&L Statement', icon: FileText },
  { id: 'cashflow',   label: 'Cash Flow',     icon: Landmark },
  { id: 'products',   label: 'Top Products',  icon: Package },
  { id: 'customers',  label: 'Top Customers', icon: Users },
  { id: 'expenses',   label: 'Expenses',      icon: TrendingDown },
] as const

type TabId = (typeof TABS)[number]['id']

// ─── Helpers ──────────────────────────────────────────────────────────────────

const COLORS = ['#f97316', '#3b82f6', '#10b981', '#a855f7', '#f59e0b', '#ef4444']

function kpi(label: string, value: string, sub?: string, positive = true) {
  return (
    <div className="card p-5">
      <p className="text-xs text-slate-400 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${positive ? 'text-white' : 'text-red-400'}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </div>
  )
}

function periodToParams(p: PeriodValue): Record<string, string> {
  const out: Record<string, string> = { period: p.period }
  if (p.date_from) out.date_from = p.date_from
  if (p.date_to)   out.date_to   = p.date_to
  return out
}

function groupByForPeriod(period: PeriodValue['period']): string {
  if (period === 'today' || period === 'week') return 'day'
  if (period === 'month') return 'day'
  return 'month'
}

// ─── Local types ──────────────────────────────────────────────────────────────

interface TopProduct { product_name: string; revenue: string; units_sold: string; cogs: string; gross_profit: string; product_sku?: string }
interface TopCustomer { customer_name: string; revenue: string; invoice_count: number; customer_code?: string }
interface ExpenseBreakdown { category_name: string; total: string; count: number }
interface CashFlow { cash_inflows: string; cash_outflows: string; net_cash_flow: string }

// ─── Component ────────────────────────────────────────────────────────────────

export default function ReportsPage() {
  const { organisation } = useAuthStore()
  const [tab, setTab] = useState<TabId>('overview')
  const [period, setPeriod] = useState<PeriodValue>({ period: 'month' })
  const [loading, setLoading] = useState(true)

  // Data state
  const [pnl, setPnl]                       = useState<PnL | null>(null)
  const [salesTrend, setSalesTrend]          = useState<SalesSummaryPoint[]>([])
  const [topProducts, setTopProducts]        = useState<TopProduct[]>([])
  const [topCustomers, setTopCustomers]      = useState<TopCustomer[]>([])
  const [expenseBreakdown, setExpenseBreakdown] = useState<ExpenseBreakdown[]>([])
  const [arAging, setArAging]                = useState<ARAgingReport | null>(null)
  const [apAging, setApAging]                = useState<ARAgingReport | null>(null)
  const [cashFlow, setCashFlow]              = useState<CashFlow | null>(null)
  const [vatSummary, setVatSummary]          = useState<VATSummary | null>(null)

  // ── VAT PDF export ────────────────────────────────────────────────────────────
  const downloadVATReport = async () => {
    if (!vatSummary) return
    try {
      const { jsPDF } = await import('jspdf')
      const { default: autoTable } = await import('jspdf-autotable')
      const { applyDocHeader, buildTableStyle, addDocFooter, COLORS, TYPE } = await import('@/lib/pdfUtils')

      const doc = new jsPDF({ unit: 'mm', format: 'a4' })
      doc.setLineHeightFactor(1.15)
      const pageW = doc.internal.pageSize.getWidth()

      const toRgb = (hex?: string): [number,number,number] => {
        const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
        if (!m) return [249, 115, 22]
        return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
      }
      const BRAND = toRgb(organisation?.brand_color) as [number,number,number]
      const DARK   = COLORS.DARK
      const MUTED  = COLORS.MUTED
      const LIGHT  = COLORS.LIGHT
      const RULE   = COLORS.RULE
      const tmpl   = organisation?.invoice_template ?? 'classic'

      let vatLogoData: string | null = null
      if (organisation?.logo) {
        try {
          const res = await tauriFetch(organisation.logo)
          const blob = await res.blob()
          vatLogoData = await new Promise<string>((resolve, reject) => {
            const r = new FileReader()
            r.onloadend = () => resolve(r.result as string)
            r.onerror = reject
            r.readAsDataURL(blob)
          })
        } catch { /* no logo */ }
      }

      const pFont = organisation?.company_name_font?.toLowerCase().includes('times') ||
        ['Georgia','Playfair Display','Merriweather','Lora','Libre Baskerville','EB Garamond',
         'Crimson Text','Cinzel','Cormorant Garamond','Spectral'].includes(organisation?.company_name_font ?? '')
        ? 'times'
        : ['courier','JetBrains Mono','Fira Code'].includes(organisation?.company_name_font ?? '')
        ? 'courier' : 'helvetica'
      const pBold   = organisation?.company_name_font_bold !== false
      const pItalic = organisation?.company_name_font_italic === true
      const pStyle  = pBold && pItalic ? 'bolditalic' : pBold ? 'bold' : pItalic ? 'italic' : 'normal'
      const pSize   = Math.max(8, Math.min(36, organisation?.company_name_font_size ?? 12))
      const nameColor: [number,number,number] = (() => {
        const c = organisation?.company_name_font_color
        if (!c || c === '#ffffff') return (tmpl === 'modern' || tmpl === 'minimal') ? DARK : COLORS.WHITE
        return toRgb(c)
      })()
      const showName    = organisation?.show_company_name_on_pdf ?? true
      const displayName = showName ? (organisation?.invoice_company_name?.trim() || organisation?.name || 'Company') : ''
      const dateRange   = `${period.date_from ?? ''} – ${period.date_to ?? ''}`

      const vatY = applyDocHeader(doc, {
        tmpl, pageW, BRAND, DARK, MUTED,
        logoData: vatLogoData,
        displayName,
        orgAddress: organisation?.address,
        orgEmail:   organisation?.email,
        orgPhone:   organisation?.phone,
        pdfFont: pFont,
        fontSize: pSize,
        pdfStyle: pStyle,
        nameColor,
        companyFontUnderline: organisation?.company_name_font_underline,
        showCompanyName: showName,
        docTitle: 'VAT RETURN REPORT',
        metaRows: [
          ['Organisation', organisation?.name ?? ''],
          ['Period',       dateRange],
          ['Generated',    new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })],
        ],
      })

      const netPayable = parseFloat(vatSummary.net_vat_payable)

      // ── VAT summary table ──────────────────────────────────────────────────
      const ts = buildTableStyle(BRAND, pFont)
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
        head: [['Description', 'Amount']],
        body: [
          ['Output VAT (collected on sales)',    formatCurrency(vatSummary.output_vat)],
          ['Input VAT (paid on approved bills)', `(${formatCurrency(vatSummary.input_vat)})`],
          ['Net VAT Payable to FIRS',            formatCurrency(vatSummary.net_vat_payable)],
        ],
        styles: { ...ts.styles, fontSize: 9, cellPadding: { top: 4, bottom: 4, left: 6, right: 6 } },
        columnStyles: {
          0: { cellWidth: 'auto' as const },
          1: { halign: 'right' as const, fontStyle: 'bold' as const, cellWidth: colW },
        },
        didParseCell: (data: any) => {
          if (data.row.index === 2) {
            data.cell.styles.textColor = netPayable >= 0 ? COLORS.RED : COLORS.GREEN
            data.cell.styles.fillColor = netPayable >= 0 ? [255, 240, 240] : [240, 255, 245]
            data.cell.styles.fontStyle = 'bold'
          }
        },
      })

      const afterY = (doc as any).lastAutoTable.finalY + 6

      // ── Formula note ───────────────────────────────────────────────────────
      doc.setFontSize(TYPE.BODY.size); doc.setFont(pFont, 'italic'); doc.setTextColor(...MUTED)
      doc.text(
        `Formula: Output VAT − Input VAT = Net VAT Payable  (${netPayable >= 0 ? 'Owed to FIRS' : 'VAT Credit / Refund'})`,
        14, afterY
      )

      // ── Disclaimer ─────────────────────────────────────────────────────────
      const disclaimerY = afterY + 10
      doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
      doc.roundedRect(14, disclaimerY, pageW - 28, 22, 2, 2, 'FD')
      doc.setFontSize(TYPE.SMALL.size); doc.setFont(pFont, 'bold'); doc.setTextColor(...MUTED)
      doc.text('DISCLAIMER', 17, disclaimerY + 5)
      doc.setFont(pFont, 'italic')
      const disclaimerText = 'This VAT Return Report is generated for informational purposes only. ' +
        'Figures are based on transactions recorded in Audity during the selected period. ' +
        'You are solely responsible for verifying accuracy and filing returns with FIRS via TaxPro-Max. ' +
        'Consult a qualified tax professional before submitting your official VAT return.'
      const disclaimerLines = doc.splitTextToSize(disclaimerText, pageW - 28 - 6)
      doc.text(disclaimerLines, 17, disclaimerY + 10)

      // ── Footer (every page, brand accent bar on last page) ─────────────────
      addDocFooter(doc, {
        orgName: organisation?.name ?? 'Company',
        docTitle: 'VAT RETURN REPORT',
        docRef: dateRange,
        BRAND,
        pdfFont: pFont,
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
    const params = periodToParams(period)
    const group_by = groupByForPeriod(period.period)
    try {
      const [pnlRes, salesRes, prodRes, custRes, expRes, arRes, apRes, cfRes, vatRes] =
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
        ])

      if (pnlRes.status === 'fulfilled')  setPnl(pnlRes.value.data)
      if (salesRes.status === 'fulfilled') setSalesTrend(salesRes.value.data.results ?? salesRes.value.data)
      if (prodRes.status === 'fulfilled')  setTopProducts(prodRes.value.data.results ?? prodRes.value.data)
      if (custRes.status === 'fulfilled')  setTopCustomers(custRes.value.data.results ?? custRes.value.data)
      if (expRes.status === 'fulfilled')   setExpenseBreakdown(expRes.value.data.results ?? expRes.value.data)
      if (arRes.status === 'fulfilled')    setArAging(arRes.value.data)
      if (apRes.status === 'fulfilled')    setApAging(apRes.value.data)
      if (cfRes.status === 'fulfilled')    setCashFlow(cfRes.value.data)
      if (vatRes.status === 'fulfilled')   setVatSummary(vatRes.value.data)
    } catch { toast.error('Failed to load reports') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [period])
  useDataRefresh(load)

  // ── Chart data ────────────────────────────────────────────────────────────────
  const chartData = salesTrend.map(s => ({
    period: s.period,
    Revenue: parseFloat(s.total_revenue),
    Tax: parseFloat(s.total_tax),
  }))

  const expensePieData = expenseBreakdown.map(e => ({
    name: e.category_name,
    value: parseFloat(e.total),
  }))

  const tooltipStyle = { backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '12px', color: '#f1f5f9', fontSize: 12 }
  const tooltipLabelStyle = { color: '#94a3b8' }
  const tooltipItemStyle  = { color: '#f1f5f9' }

  const exportParams = periodToParams(period)

  // ── P&L table rows ────────────────────────────────────────────────────────────
  const pnlRows: (string | number)[][] = pnl ? [
    ['Gross Sales',           formatCurrency(pnl.revenue.gross_sales)],
    ['Tax Collected',         formatCurrency(pnl.revenue.tax_collected)],
    ['Discounts',             formatCurrency(pnl.revenue.discounts)],
    ['Cost of Goods Sold',    formatCurrency(pnl.cost_of_goods_sold)],
    ['Gross Profit',          formatCurrency(pnl.gross_profit)],
    [`Gross Margin %`,        `${parseFloat(pnl.gross_margin_pct).toFixed(2)}%`],
    ['Operating Expenses',    formatCurrency(pnl.operating_expenses)],
    ['Misc. Income',          formatCurrency(pnl.miscellaneous_income ?? '0')],
    ['Net Profit',            formatCurrency(pnl.net_profit)],
    [`Net Margin %`,          `${parseFloat(pnl.net_margin_pct).toFixed(2)}%`],
  ] : []

  return (
    <div className="space-y-5">
      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-start gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Reports & Analytics</h1>
          <p className="text-slate-400 text-sm">Financial overview and performance metrics</p>
        </div>
        <div className="sm:ml-auto flex flex-wrap items-center gap-2">
          <PeriodSelector value={period} onChange={setPeriod} />
          <button
            onClick={() => { bypassNextGets(); load() }}
            disabled={loading}
            className="p-2 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors"
            title="Refresh"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* ── Tabs ────────────────────────────────────────────────────────────── */}
      <div className="flex overflow-x-auto gap-1 border-b border-surface-700 pb-0">
        {TABS.map(t => {
          const Icon = t.icon
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px
                ${tab === t.id
                  ? 'border-brand-400 text-brand-400'
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
          TAB: OVERVIEW
      ══════════════════════════════════════════════════════════════════════════ */}
      {tab === 'overview' && (
        <div className="space-y-6">
          {/* P&L KPI Cards */}
          {pnl ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {kpi('Gross Sales', formatCurrency(pnl.revenue.gross_sales))}
              {kpi('COGS', formatCurrency(pnl.cost_of_goods_sold), undefined, false)}
              {kpi('Gross Profit', formatCurrency(pnl.gross_profit),
                `${parseFloat(pnl.gross_margin_pct).toFixed(1)}% margin`,
                parseFloat(pnl.gross_profit) >= 0)}
              {kpi('Net Profit', formatCurrency(pnl.net_profit),
                `${parseFloat(pnl.net_margin_pct).toFixed(1)}% margin`,
                parseFloat(pnl.net_profit) >= 0)}
            </div>
          ) : loading ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="card p-5 h-24 animate-pulse bg-surface-800" />
              ))}
            </div>
          ) : null}

          {/* Revenue Trend */}
          <div className="card p-5">
            <div className="flex items-center gap-2 mb-5">
              <TrendingUp size={18} className="text-brand-400" />
              <h2 className="text-base font-semibold text-white">Revenue Trend</h2>
            </div>
            {loading ? (
              <div className="h-64 bg-surface-800 rounded-xl animate-pulse" />
            ) : chartData.length === 0 ? (
              <div className="h-64 flex items-center justify-center">
                <p className="text-slate-500 text-sm">No sales data for this period</p>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                  <defs>
                    <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#f97316" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#f97316" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="taxGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.2} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="period" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false}
                    tickFormatter={v => `${getCurrencySymbol()}${formatNumber(v)}`} />
                  <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle}
                    formatter={(v: number) => formatCurrency(v)} />
                  <Legend wrapperStyle={{ fontSize: 12, paddingTop: 16, color: '#94a3b8' }} />
                  <Area type="monotone" dataKey="Revenue" stroke="#f97316" strokeWidth={2} fill="url(#revGrad)" dot={false} />
                  <Area type="monotone" dataKey="Tax" stroke="#3b82f6" strokeWidth={1.5} fill="url(#taxGrad)" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Top Products bar + Expense Pie */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-5">
                <BarChart2 size={18} className="text-emerald-400" />
                <h2 className="text-base font-semibold text-white">Top Products</h2>
              </div>
              {loading ? <div className="h-52 bg-surface-800 rounded-xl animate-pulse" /> :
               topProducts.length === 0 ? (
                <div className="h-52 flex items-center justify-center">
                  <p className="text-slate-500 text-sm">No data</p>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart
                    data={topProducts.slice(0, 6).map(p => ({
                      name: (p.product_name ?? 'Unknown').length > 16
                        ? (p.product_name ?? 'Unknown').slice(0, 16) + '…'
                        : (p.product_name ?? 'Unknown'),
                      Revenue: parseFloat(p.revenue),
                    }))}
                    margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false}
                      tickFormatter={v => `${getCurrencySymbol()}${formatNumber(v)}`} />
                    <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle}
                      formatter={(v: number) => formatCurrency(v)} />
                    <Bar dataKey="Revenue" fill="#10b981" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className="card p-5">
              <div className="flex items-center gap-2 mb-5">
                <TrendingDown size={18} className="text-red-400" />
                <h2 className="text-base font-semibold text-white">Expense Breakdown</h2>
              </div>
              {loading ? <div className="h-52 bg-surface-800 rounded-xl animate-pulse" /> :
               expensePieData.length === 0 ? (
                <div className="h-52 flex items-center justify-center">
                  <p className="text-slate-500 text-sm">No expense data</p>
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={expensePieData} cx="50%" cy="50%"
                      innerRadius={55} outerRadius={90} paddingAngle={3} dataKey="value">
                      {expensePieData.map((_, i) => (
                        <Cell key={`cell-${i}`} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle}
                      formatter={(v: number) => formatCurrency(v)} />
                    <Legend
                      wrapperStyle={{ fontSize: 11, paddingTop: 12 }}
                      formatter={(value: string) => <span style={{ color: '#94a3b8' }}>{value}</span>}
                    />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* AR Aging + VAT Summary */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <AgingCard title="Accounts Receivable Aging" aging={arAging} loading={loading} iconColor="text-amber-400" />

            <div className="card p-5">
              <div className="flex items-center justify-between gap-2 mb-4">
                <div className="flex items-center gap-2">
                  <Receipt size={18} className="text-blue-400" />
                  <h2 className="text-base font-semibold text-white">VAT Summary</h2>
                </div>
                {vatSummary && (
                  <button onClick={downloadVATReport}
                    className="flex items-center gap-1.5 text-xs text-brand-400 hover:text-brand-300 transition-colors">
                    <Download size={13} /> Export PDF
                  </button>
                )}
              </div>
              {vatSummary ? (
                <div className="space-y-4">
                  <div className="grid grid-cols-3 gap-3">
                    <VATCard label="Output VAT" sub="Collected on sales" value={vatSummary.output_vat} />
                    <VATCard label="Input VAT" sub="Paid on bills" value={vatSummary.input_vat} />
                    <VATCard
                      label="Net VAT Payable" sub={parseFloat(vatSummary.net_vat_payable) >= 0 ? 'Owed to FIRS' : 'VAT credit'}
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
                <h2 className="text-base font-semibold text-white">Cash Flow Statement</h2>
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
                      {formatCurrency(Math.abs(parseFloat(cashFlow.net_cash_flow)))}
                    </span>
                  </div>
                  <p className="text-xs text-slate-600">Inflows: cash/bank/POS sales + misc income · Outflows: all expenses</p>
                </div>
              ) : (
                <div className="h-40 flex items-center justify-center text-slate-500 text-sm">
                  {loading ? 'Loading…' : 'No cash flow data for this period'}
                </div>
              )}
            </div>

            <AgingCard title="Accounts Payable Aging" aging={apAging} loading={loading} iconColor="text-red-400" payable />
          </div>

          {/* Top Customers summary table */}
          <div className="card p-0 overflow-hidden">
            <div className="px-5 py-4 border-b border-surface-700">
              <h2 className="text-base font-semibold text-white">Top Customers</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700">
                    {['#', 'Customer', 'Invoices', 'Revenue'].map(h => (
                      <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    Array.from({ length: 5 }).map((_, i) => (
                      <tr key={i}>
                        {Array.from({ length: 4 }).map((_, j) => (
                          <td key={j} className="px-5 py-3.5">
                            <div className="h-4 bg-surface-700 rounded animate-pulse w-24" />
                          </td>
                        ))}
                      </tr>
                    ))
                  ) : topCustomers.length === 0 ? (
                    <tr><td colSpan={4} className="px-5 py-10 text-center text-slate-500 text-sm">No customer data</td></tr>
                  ) : topCustomers.slice(0, 5).map((c, i) => (
                    <tr key={i} className="table-row">
                      <td className="px-5 py-3.5">
                        <span className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${
                          i === 0 ? 'bg-amber-500/20 text-amber-400' :
                          i === 1 ? 'bg-slate-500/20 text-slate-300' :
                          i === 2 ? 'bg-orange-700/20 text-orange-400' : 'bg-surface-700 text-slate-400'
                        }`}>{i + 1}</span>
                      </td>
                      <td className="px-5 py-3.5 text-white font-medium">{c.customer_name ?? 'Walk-in'}</td>
                      <td className="px-5 py-3.5 text-slate-400">{c.invoice_count}</td>
                      <td className="px-5 py-3.5 font-semibold text-brand-400">{formatCurrency(c.revenue)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          TAB: P&L STATEMENT
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
              {kpi('Gross Sales', formatCurrency(pnl.revenue.gross_sales))}
              {kpi('COGS', formatCurrency(pnl.cost_of_goods_sold), undefined, false)}
              {kpi('Gross Profit', formatCurrency(pnl.gross_profit),
                `${parseFloat(pnl.gross_margin_pct).toFixed(1)}% margin`,
                parseFloat(pnl.gross_profit) >= 0)}
              {kpi('Net Profit', formatCurrency(pnl.net_profit),
                `${parseFloat(pnl.net_margin_pct).toFixed(1)}% margin`,
                parseFloat(pnl.net_profit) >= 0)}
            </div>
          )}

          {/* Detailed table */}
          <ReportTable
            headers={['Line Item', 'Amount (₦)']}
            rows={pnlRows}
            loading={loading}
            emptyMessage="No P&L data for this period."
            rightAlignCols={[1]}
          />

          {/* Revenue vs Expenses visual */}
          {pnl && (
            <div className="card p-5">
              <h3 className="text-sm font-semibold text-slate-300 mb-4">Revenue vs Costs Breakdown</h3>
              <div className="space-y-3">
                {[
                  { label: 'Gross Sales', value: parseFloat(pnl.revenue.gross_sales), color: 'bg-brand-500' },
                  { label: 'Tax Collected', value: parseFloat(pnl.revenue.tax_collected), color: 'bg-blue-500' },
                  { label: 'Discounts', value: parseFloat(pnl.revenue.discounts), color: 'bg-yellow-500' },
                  { label: 'COGS', value: parseFloat(pnl.cost_of_goods_sold), color: 'bg-red-500' },
                  { label: 'Operating Expenses', value: parseFloat(pnl.operating_expenses), color: 'bg-orange-500' },
                  { label: 'Net Profit', value: parseFloat(pnl.net_profit), color: parseFloat(pnl.net_profit) >= 0 ? 'bg-emerald-500' : 'bg-red-600' },
                ].map(({ label, value, color }) => {
                  const gross = parseFloat(pnl.revenue.gross_sales) || 1
                  const pct = Math.min(100, Math.abs(Math.round((value / gross) * 100)))
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
          TAB: CASH FLOW
      ══════════════════════════════════════════════════════════════════════════ */}
      {tab === 'cashflow' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Cash Flow Statement</h2>
            <ExportBar endpoint="/reports/cash-flow/" params={exportParams} filenameBase="cash_flow" />
          </div>

          <ReportTable
            headers={['Line Item', 'Amount (₦)']}
            rows={cashFlow ? [
              ['Cash Inflows (sales + misc income)', formatCurrency(cashFlow.cash_inflows)],
              ['Cash Outflows (expenses)',           formatCurrency(cashFlow.cash_outflows)],
              ['Net Cash Flow',                      formatCurrency(cashFlow.net_cash_flow)],
            ] : []}
            loading={loading}
            emptyMessage="No cash flow data for this period."
            rightAlignCols={[1]}
          />

          {cashFlow && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <MetricCard
                label="Total Inflows" value={formatCurrency(cashFlow.cash_inflows)}
                sub="Sales + misc income" color="emerald"
                icon={<ArrowDownCircle size={20} className="text-emerald-400" />}
              />
              <MetricCard
                label="Total Outflows" value={formatCurrency(cashFlow.cash_outflows)}
                sub="All expenses" color="red"
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
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          TAB: TOP PRODUCTS
      ══════════════════════════════════════════════════════════════════════════ */}
      {tab === 'products' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Top Products by Revenue</h2>
            <ExportBar endpoint="/reports/top-products/" params={{ ...exportParams, limit: 50 }} filenameBase="top_products" />
          </div>
          <ReportTable
            headers={['Product', 'SKU', 'Units Sold', 'Revenue', 'COGS', 'Gross Profit']}
            rows={topProducts.map(p => [
              p.product_name ?? '—',
              p.product_sku ?? '—',
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
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          TAB: TOP CUSTOMERS
      ══════════════════════════════════════════════════════════════════════════ */}
      {tab === 'customers' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Top Customers by Revenue</h2>
            <ExportBar endpoint="/reports/top-customers/" params={{ ...exportParams, limit: 50 }} filenameBase="top_customers" />
          </div>
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
      )}

      {/* ═══════════════════════════════════════════════════════════════════════
          TAB: EXPENSES
      ══════════════════════════════════════════════════════════════════════════ */}
      {tab === 'expenses' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">Expense Breakdown by Category</h2>
            <ExportBar endpoint="/reports/expenses/" params={exportParams} filenameBase="expense_breakdown" />
          </div>
          <ReportTable
            headers={['Category', 'Total (₦)', 'Count']}
            rows={expenseBreakdown.map(e => [
              e.category_name,
              formatCurrency(e.total),
              e.count,
            ])}
            loading={loading}
            emptyMessage="No expense data for this period."
            rightAlignCols={[1, 2]}
          />

          {expenseBreakdown.length > 0 && !loading && (
            <div className="card p-5">
              <h3 className="text-sm font-semibold text-slate-300 mb-4">Category Distribution</h3>
              <div className="space-y-2.5">
                {expenseBreakdown.map((e, i) => {
                  const total = expenseBreakdown.reduce((s, x) => s + parseFloat(x.total), 0) || 1
                  const pct = Math.round((parseFloat(e.total) / total) * 100)
                  return (
                    <div key={e.category_name}>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-slate-400">{e.category_name}</span>
                        <span className="text-slate-300 tabular-nums">{formatCurrency(e.total)} ({pct}%)</span>
                      </div>
                      <div className="h-2 bg-surface-700 rounded-full">
                        <div
                          className="h-full rounded-full"
                          style={{ width: `${pct}%`, backgroundColor: COLORS[i % COLORS.length] }}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Small reusable sub-components ───────────────────────────────────────────

function AgingCard({
  title, aging, loading, iconColor, payable = false,
}: {
  title: string
  aging: ARAgingReport | null
  loading: boolean
  iconColor: string
  payable?: boolean
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
          {aging.invoices.slice(0, 4).length > 0 && (
            <div className="mt-3 pt-3 border-t border-surface-700">
              <p className="text-xs text-slate-500 mb-2">{payable ? 'Most Overdue Payables' : 'Most Overdue'}</p>
              {aging.invoices.slice(0, 4).map(inv => (
                <div key={inv.id} className="flex items-center justify-between py-1.5">
                  <div>
                    <p className="text-xs font-medium text-white">{inv.customer_name ?? (payable ? 'Supplier' : 'Walk-in')}</p>
                    <p className="text-xs text-slate-500">{inv.invoice_number} · {inv.days_overdue}d overdue</p>
                  </div>
                  <span className="text-xs font-semibold text-red-400">{formatCurrency(inv.amount_due)}</span>
                </div>
              ))}
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

function CashFlowRow({ icon, label, value, color }: { icon: React.ReactNode; label: string; value: string; color: 'green' | 'red' }) {
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
