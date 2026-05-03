import { useEffect, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { BarChart2, RefreshCw, TrendingDown, TrendingUp, Clock, Receipt, Download, ArrowDownCircle, ArrowUpCircle, Landmark } from 'lucide-react'
import toast from 'react-hot-toast'
import { reportApi, tauriFetch, bypassNextGets } from '@/services/api'
import { formatCurrency, formatNumber, formatDate, getCurrencySymbol } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import { saveBlobFile } from '@/lib/saveBlobFile'
import type { PnL, SalesSummaryPoint, ARAgingReport, VATSummary } from '@/types'

const PERIOD_OPTIONS = [
  { label: '7 days', days: 7 },
  { label: '30 days', days: 30 },
  { label: '90 days', days: 90 },
  { label: '365 days', days: 365 },
]

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

interface TopProduct { product_name: string; revenue: string; units_sold: string }
interface TopCustomer { customer_name: string; revenue: string; invoice_count: number }
interface ExpenseBreakdown { category_name: string; total: string }

export default function ReportsPage() {
  const { organisation } = useAuthStore()
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(true)

  const [pnl, setPnl] = useState<PnL | null>(null)
  const [salesTrend, setSalesTrend] = useState<SalesSummaryPoint[]>([])
  const [topProducts, setTopProducts] = useState<TopProduct[]>([])
  const [topCustomers, setTopCustomers] = useState<TopCustomer[]>([])
  const [expenseBreakdown, setExpenseBreakdown] = useState<ExpenseBreakdown[]>([])
  const [arAging, setArAging] = useState<ARAgingReport | null>(null)
  const [apAging, setApAging] = useState<ARAgingReport | null>(null)
  const [cashFlow, setCashFlow] = useState<{ cash_inflows: string; cash_outflows: string; net_cash_flow: string } | null>(null)
  const [vatSummary, setVatSummary] = useState<VATSummary | null>(null)

  const downloadVATReport = async () => {
    if (!vatSummary) return
    try {
      const { jsPDF } = await import('jspdf')
      const { default: autoTable } = await import('jspdf-autotable')
      const doc = new jsPDF({ unit: 'mm', format: 'a4' })
      const pageW = doc.internal.pageSize.getWidth()
      const brandRgbVAT = (hex?: string): [number, number, number] => {
        const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
        if (!m) return [249, 115, 22]
        return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
      }
      const BRAND: [number,number,number] = brandRgbVAT(organisation?.brand_color)
      const DARK: [number,number,number] = [30, 30, 30]
      const MUTED: [number,number,number] = [100, 100, 100]
      const tmpl = organisation?.invoice_template ?? 'classic'

      // Pre-load logo (tauriFetch for Tauri compatibility)
      let vatLogoData: string | null = null
      if (organisation?.logo) {
        try {
          const res = await tauriFetch(organisation.logo)
          const blob = await res.blob()
          vatLogoData = await new Promise<string>((resolve, reject) => {
            const r = new FileReader(); r.onloadend = () => resolve(r.result as string); r.onerror = reject; r.readAsDataURL(blob)
          })
        } catch { /* no logo */ }
      }

      const range = buildDateRange()
      const vatHexToRgb = (hex?: string): [number, number, number] => {
        const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
        if (!m) return [30, 30, 30]
        return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
      }
      const vatPdfFont = organisation?.company_name_font?.toLowerCase().includes('times') ||
        ['Georgia','Playfair Display','Merriweather','Lora','Libre Baskerville','EB Garamond',
         'Crimson Text','Cinzel','Cormorant Garamond','Spectral'].includes(organisation?.company_name_font ?? '')
        ? 'times'
        : ['courier','JetBrains Mono','Fira Code'].includes(organisation?.company_name_font ?? '')
        ? 'courier' : 'helvetica'
      const vatBold   = organisation?.company_name_font_bold !== false
      const vatItalic = organisation?.company_name_font_italic === true
      const vatPdfStyle = vatBold && vatItalic ? 'bolditalic' : vatBold ? 'bold' : vatItalic ? 'italic' : 'normal'
      const vatFontSize = Math.max(8, Math.min(36, organisation?.company_name_font_size ?? 14))
      const vatNameColor: [number, number, number] = (() => {
        const c = organisation?.company_name_font_color
        if (!c || c === '#ffffff') return (tmpl === 'modern' || tmpl === 'minimal') ? DARK : [255, 255, 255]
        return vatHexToRgb(c)
      })()
      const vatShowName = organisation?.show_company_name_on_pdf ?? true
      const vatDisplayName = vatShowName
        ? (organisation?.invoice_company_name?.trim() || organisation?.name || 'Company') : ''
      const { applyDocHeader, templateHeadFill: vatHeadFill } = await import('@/lib/pdfUtils')
      let vatY = applyDocHeader(doc, {
        tmpl, pageW, BRAND, DARK, MUTED,
        logoData: vatLogoData,
        displayName: vatDisplayName,
        orgAddress: organisation?.address,
        orgEmail: organisation?.email,
        orgPhone: organisation?.phone,
        pdfFont: vatPdfFont,
        fontSize: vatFontSize,
        pdfStyle: vatPdfStyle,
        nameColor: vatNameColor,
        companyFontUnderline: organisation?.company_name_font_underline,
        showCompanyName: vatShowName,
        docTitle: 'VAT RETURN REPORT',
        metaRows: [
          ['Organisation', organisation?.name ?? ''],
          ['Period', `${range.date_from} to ${range.date_to}`],
          ['Generated', new Date().toLocaleDateString()],
        ],
      })

      // Summary table
      const netPayable = parseFloat(vatSummary.net_vat_payable)
      // Dynamic amount column width so large VAT figures always fit
      const vatAmounts = [
        formatCurrency(vatSummary.output_vat),
        `(${formatCurrency(vatSummary.input_vat)})`,
        formatCurrency(vatSummary.net_vat_payable),
        'Amount',
      ]
      doc.setFontSize(10)
      const vatAmtW = Math.min(70, Math.max(36, Math.max(...vatAmounts.map(s => doc.getTextWidth(s))) + 16))
      autoTable(doc, {
        startY: vatY,
        head: [['Description', 'Amount']],
        body: [
          ['Output VAT (collected on sales)', formatCurrency(vatSummary.output_vat)],
          ['Input VAT (paid on approved bills)', `(${formatCurrency(vatSummary.input_vat)})`],
          ['Net VAT Payable to FIRS', formatCurrency(vatSummary.net_vat_payable)],
        ],
        styles: { fontSize: 10, cellPadding: { top: 5, bottom: 5, left: 8, right: 8 } },
        headStyles: { fillColor: vatHeadFill(tmpl, BRAND), textColor: [255,255,255], fontStyle: 'bold' },
        bodyStyles: { textColor: DARK },
        columnStyles: {
          0: { cellWidth: 'auto' },
          1: { halign: 'right', fontStyle: 'bold', cellWidth: vatAmtW },
        },
        didParseCell: (data) => {
          if (data.row.index === 2) {
            data.cell.styles.textColor = netPayable >= 0 ? [220, 38, 38] : [22, 163, 74]
            data.cell.styles.fillColor = netPayable >= 0 ? [255, 240, 240] : [240, 255, 245]
          }
        },
        margin: { left: 14, right: 14 },
      })

      const afterY = (doc as any).lastAutoTable.finalY + 8
      doc.setFontSize(8)
      doc.setFont('helvetica', 'italic')
      doc.setTextColor(...MUTED)
      doc.text(
        `Formula: Output VAT − Input VAT = Net VAT Payable (${netPayable >= 0 ? 'Owed to FIRS' : 'VAT Credit'})`,
        14, afterY
      )

      // Footer
      const pageH = doc.internal.pageSize.getHeight()
      doc.setFillColor(...BRAND)
      doc.rect(0, pageH - 10, pageW, 10, 'F')
      doc.setFontSize(7)
      doc.setFont('helvetica', 'normal')
      doc.setTextColor(255, 255, 255)
      doc.text('Generated by Audity', pageW / 2, pageH - 3.5, { align: 'center' })

      await saveBlobFile(doc.output('blob'), `VAT-Return-${range.date_from}-to-${range.date_to}.pdf`)
      toast.success('VAT report downloaded')
    } catch {
      toast.error('Failed to generate PDF')
    }
  }

  const buildDateRange = () => {
    const end = new Date()
    const start = new Date()
    start.setDate(end.getDate() - days)
    return {
      date_from: start.toISOString().split('T')[0],
      date_to: end.toISOString().split('T')[0],
    }
  }

  const load = async () => {
    setLoading(true)
    const range = buildDateRange()
    const granularity = days <= 30 ? 'daily' : days <= 90 ? 'weekly' : 'monthly'
    try {
      const [pnlRes, salesRes, prodRes, custRes, expRes, arRes, apRes, cfRes, vatRes] = await Promise.allSettled([
        reportApi.pnl(range),
        reportApi.sales({ ...range, granularity }),
        reportApi.topProducts({ ...range, limit: 6 }),
        reportApi.topCustomers({ ...range, limit: 5 }),
        reportApi.expenses(range),
        reportApi.arAging(),
        reportApi.apAging(),
        reportApi.cashFlow(range),
        reportApi.vatSummary(range),
      ])

      if (pnlRes.status === 'fulfilled') setPnl(pnlRes.value.data)
      if (salesRes.status === 'fulfilled') setSalesTrend(salesRes.value.data.results ?? salesRes.value.data)
      if (prodRes.status === 'fulfilled') setTopProducts(prodRes.value.data.results ?? prodRes.value.data)
      if (custRes.status === 'fulfilled') setTopCustomers(custRes.value.data.results ?? custRes.value.data)
      if (expRes.status === 'fulfilled') setExpenseBreakdown(expRes.value.data.results ?? expRes.value.data)
      if (arRes.status === 'fulfilled') setArAging(arRes.value.data)
      if (apRes.status === 'fulfilled') setApAging(apRes.value.data)
      if (cfRes.status === 'fulfilled') setCashFlow(cfRes.value.data)
      if (vatRes.status === 'fulfilled') setVatSummary(vatRes.value.data)
    } catch { toast.error('Failed to load reports') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [days])
  useDataRefresh(load)

  const chartData = salesTrend.map((s) => ({
    period: s.period,
    Revenue: parseFloat(s.total_revenue),
    Invoices: s.invoice_count,
    Tax: parseFloat(s.total_tax),
  }))

  const expensePieData = expenseBreakdown.map((e) => ({
    name: e.category_name,
    value: parseFloat(e.total),
  }))

  const tooltipStyle = {
    backgroundColor: '#1e293b',
    border: '1px solid #334155',
    borderRadius: '12px',
    color: '#f1f5f9',
    fontSize: 12,
  }
  const tooltipLabelStyle = { color: '#94a3b8' }
  const tooltipItemStyle = { color: '#f1f5f9' }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Reports & Analytics</h1>
          <p className="text-slate-400 text-sm">Financial overview and performance metrics</p>
        </div>

        <div className="sm:ml-auto flex items-center gap-3">
          {/* Period selector */}
          <div className="flex rounded-xl border border-surface-600 overflow-hidden">
            {PERIOD_OPTIONS.map((opt) => (
              <button
                key={opt.days}
                onClick={() => setDays(opt.days)}
                className={`px-3 py-2 text-xs font-medium transition-colors ${
                  days === opt.days
                    ? 'bg-brand-500/20 text-brand-400'
                    : 'text-slate-400 hover:bg-surface-700'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => { bypassNextGets(); load() }}
            disabled={loading}
            className="p-2 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* P&L KPI Cards */}
      {pnl && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {kpi('Gross Sales', formatCurrency(pnl.revenue.gross_sales))}
          {kpi('COGS', formatCurrency(pnl.cost_of_goods_sold), undefined, false)}
          {kpi(
            'Gross Profit',
            formatCurrency(pnl.gross_profit),
            `${parseFloat(pnl.gross_margin_pct).toFixed(1)}% margin`,
            parseFloat(pnl.gross_profit) >= 0,
          )}
          {kpi(
            'Net Profit',
            formatCurrency(pnl.net_profit),
            `${parseFloat(pnl.net_margin_pct).toFixed(1)}% margin`,
            parseFloat(pnl.net_profit) >= 0,
          )}
        </div>
      )}

      {loading && !pnl && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="card p-5 h-24 animate-pulse bg-surface-800" />
          ))}
        </div>
      )}

      {/* Revenue trend chart */}
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
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => `${getCurrencySymbol()}${formatNumber(v)}`} />
              <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle} formatter={(v: number) => formatCurrency(v)} />
              <Legend wrapperStyle={{ fontSize: 12, paddingTop: 16, color: '#94a3b8' }} />
              <Area type="monotone" dataKey="Revenue" stroke="#f97316" strokeWidth={2} fill="url(#revGrad)" dot={false} />
              <Area type="monotone" dataKey="Tax" stroke="#3b82f6" strokeWidth={1.5} fill="url(#taxGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Bottom row: Top Products + Expense Pie */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top Products bar */}
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-5">
            <BarChart2 size={18} className="text-emerald-400" />
            <h2 className="text-base font-semibold text-white">Top Products</h2>
          </div>
          {loading ? (
            <div className="h-52 bg-surface-800 rounded-xl animate-pulse" />
          ) : topProducts.length === 0 ? (
            <div className="h-52 flex items-center justify-center">
              <p className="text-slate-500 text-sm">No data</p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart
                data={topProducts.map((p) => ({
                  name: (p.product_name ?? 'Unknown').length > 16 ? (p.product_name ?? 'Unknown').slice(0, 16) + '…' : (p.product_name ?? 'Unknown'),
                  Revenue: parseFloat(p.revenue),
                  Units: parseFloat(p.units_sold),
                }))}
                margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v) => `${getCurrencySymbol()}${formatNumber(v)}`} />
                <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle} formatter={(v: number, name: string) => name === 'Revenue' ? formatCurrency(v) : formatNumber(v)} />
                <Bar dataKey="Revenue" fill="#10b981" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Expense breakdown pie */}
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-5">
            <TrendingDown size={18} className="text-red-400" />
            <h2 className="text-base font-semibold text-white">Expense Breakdown</h2>
          </div>
          {loading ? (
            <div className="h-52 bg-surface-800 rounded-xl animate-pulse" />
          ) : expensePieData.length === 0 ? (
            <div className="h-52 flex items-center justify-center">
              <p className="text-slate-500 text-sm">No expense data</p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={expensePieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={55}
                  outerRadius={90}
                  paddingAngle={3}
                  dataKey="value"
                >
                  {expensePieData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle} formatter={(v: number) => formatCurrency(v)} />
                <Legend
                  wrapperStyle={{ fontSize: 11, paddingTop: 12 }}
                  formatter={(value: string) => <span style={{ color: '#94a3b8' }}>{value}</span>}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* AR Aging + VAT Summary row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* AR Aging */}
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <Clock size={18} className="text-amber-400" />
            <h2 className="text-base font-semibold text-white">Accounts Receivable Aging</h2>
          </div>
          {arAging ? (
            <div className="space-y-3">
              <p className="text-xs text-slate-500">As of {formatDate(arAging.as_of)} · Total Outstanding: <span className="text-white font-semibold">{formatCurrency(arAging.total_outstanding)}</span></p>
              {[
                { label: 'Current (not due)', key: 'current', color: 'text-green-400 bg-green-500/10' },
                { label: '1–30 days overdue', key: '1_30', color: 'text-yellow-400 bg-yellow-500/10' },
                { label: '31–60 days overdue', key: '31_60', color: 'text-orange-400 bg-orange-500/10' },
                { label: '61–90 days overdue', key: '61_90', color: 'text-red-400 bg-red-500/10' },
                { label: '90+ days overdue', key: 'over_90', color: 'text-red-600 bg-red-600/10' },
              ].map(({ label, key, color }) => {
                const amount = (arAging.buckets as any)[key] ?? 0
                const total = parseFloat(arAging.total_outstanding) || 1
                const pct = Math.round((parseFloat(amount) / total) * 100)
                return (
                  <div key={key}>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-slate-400">{label}</span>
                      <span className={`font-semibold ${color.split(' ')[0]}`}>{formatCurrency(amount)}</span>
                    </div>
                    <div className="h-1.5 bg-surface-700 rounded-full">
                      <div className={`h-full rounded-full ${color.split(' ')[1]}`} style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                )
              })}
              {arAging.invoices.slice(0, 4).length > 0 && (
                <div className="mt-3 pt-3 border-t border-surface-700">
                  <p className="text-xs text-slate-500 mb-2">Most Overdue</p>
                  {arAging.invoices.slice(0, 4).map((inv) => (
                    <div key={inv.id} className="flex items-center justify-between py-1.5">
                      <div>
                        <p className="text-xs font-medium text-white">{inv.customer_name ?? 'Walk-in'}</p>
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
              {loading ? 'Loading…' : 'No outstanding receivables'}
            </div>
          )}
        </div>

        {/* VAT Summary */}
        <div className="card p-5">
          <div className="flex items-center justify-between gap-2 mb-4">
            <div className="flex items-center gap-2">
              <Receipt size={18} className="text-blue-400" />
              <h2 className="text-base font-semibold text-white">VAT Summary</h2>
            </div>
            {vatSummary && (
              <button
                onClick={downloadVATReport}
                className="flex items-center gap-1.5 text-xs text-brand-400 hover:text-brand-300 transition-colors"
              >
                <Download size={13} /> Export PDF
              </button>
            )}
          </div>
          {vatSummary ? (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 rounded-xl bg-surface-800">
                  <p className="text-xs text-slate-500 mb-1">Output VAT</p>
                  <p className="text-base font-bold text-white">{formatCurrency(vatSummary.output_vat)}</p>
                  <p className="text-xs text-slate-500 mt-0.5">Collected on sales</p>
                </div>
                <div className="p-3 rounded-xl bg-surface-800">
                  <p className="text-xs text-slate-500 mb-1">Input VAT</p>
                  <p className="text-base font-bold text-white">{formatCurrency(vatSummary.input_vat)}</p>
                  <p className="text-xs text-slate-500 mt-0.5">Paid on bills</p>
                </div>
                <div className={`p-3 rounded-xl ${parseFloat(vatSummary.net_vat_payable) >= 0 ? 'bg-red-500/10' : 'bg-green-500/10'}`}>
                  <p className="text-xs text-slate-500 mb-1">Net VAT Payable</p>
                  <p className={`text-base font-bold ${parseFloat(vatSummary.net_vat_payable) >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                    {formatCurrency(vatSummary.net_vat_payable)}
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">{parseFloat(vatSummary.net_vat_payable) >= 0 ? 'Owed to FIRS' : 'VAT credit'}</p>
                </div>
              </div>
              <div className="p-3 rounded-xl bg-surface-800/50 border border-surface-700">
                <p className="text-xs text-slate-400">
                  <strong className="text-white">Formula:</strong> Output VAT ({formatCurrency(vatSummary.output_vat)}) − Input VAT ({formatCurrency(vatSummary.input_vat)}) = Net VAT Payable to FIRS
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

      {/* Cash Flow + AP Aging row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Cash Flow Statement */}
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <Landmark size={18} className="text-emerald-400" />
            <h2 className="text-base font-semibold text-white">Cash Flow Statement</h2>
          </div>
          {cashFlow ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 rounded-xl bg-green-500/8 border border-green-500/20">
                <div className="flex items-center gap-2">
                  <ArrowDownCircle size={16} className="text-green-400" />
                  <span className="text-sm text-slate-300">Cash Inflows</span>
                </div>
                <span className="font-bold text-green-400">{formatCurrency(cashFlow.cash_inflows)}</span>
              </div>
              <div className="flex items-center justify-between p-3 rounded-xl bg-red-500/8 border border-red-500/20">
                <div className="flex items-center gap-2">
                  <ArrowUpCircle size={16} className="text-red-400" />
                  <span className="text-sm text-slate-300">Cash Outflows</span>
                </div>
                <span className="font-bold text-red-400">({formatCurrency(cashFlow.cash_outflows)})</span>
              </div>
              <div className={`flex items-center justify-between p-4 rounded-xl border ${parseFloat(cashFlow.net_cash_flow) >= 0 ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-red-500/10 border-red-500/30'}`}>
                <span className="text-sm font-semibold text-white">Net Cash Flow</span>
                <span className={`text-lg font-bold ${parseFloat(cashFlow.net_cash_flow) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {parseFloat(cashFlow.net_cash_flow) >= 0 ? '' : '-'}{formatCurrency(Math.abs(parseFloat(cashFlow.net_cash_flow)))}
                </span>
              </div>
              <p className="text-xs text-slate-600 mt-1">Inflows: cash/bank/POS sales + misc income · Outflows: all expenses</p>
            </div>
          ) : (
            <div className="h-40 flex items-center justify-center text-slate-500 text-sm">
              {loading ? 'Loading…' : 'No cash flow data for this period'}
            </div>
          )}
        </div>

        {/* AP Aging */}
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <Clock size={18} className="text-red-400" />
            <h2 className="text-base font-semibold text-white">Accounts Payable Aging</h2>
          </div>
          {apAging ? (
            <div className="space-y-3">
              <p className="text-xs text-slate-500">As of {formatDate(apAging.as_of)} · Total Payable: <span className="text-white font-semibold">{formatCurrency(apAging.total_outstanding)}</span></p>
              {([
                { label: 'Current (not due)', key: 'current' as const, color: 'text-green-400 bg-green-500/10' },
                { label: '1–30 days overdue', key: '1_30' as const, color: 'text-yellow-400 bg-yellow-500/10' },
                { label: '31–60 days overdue', key: '31_60' as const, color: 'text-orange-400 bg-orange-500/10' },
                { label: '61–90 days overdue', key: '61_90' as const, color: 'text-red-400 bg-red-500/10' },
                { label: '90+ days overdue', key: 'over_90' as const, color: 'text-red-600 bg-red-600/10' },
              ] as const).map(({ label, key, color }) => {
                const amount = apAging.buckets[key] ?? 0
                const total = parseFloat(apAging.total_outstanding) || 1
                const pct = Math.round((Number(amount) / total) * 100)
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
              {apAging.invoices.slice(0, 4).length > 0 && (
                <div className="mt-3 pt-3 border-t border-surface-700">
                  <p className="text-xs text-slate-500 mb-2">Most Overdue Payables</p>
                  {apAging.invoices.slice(0, 4).map((item) => (
                    <div key={item.id} className="flex items-center justify-between py-1.5">
                      <div>
                        <p className="text-xs font-medium text-white">{item.customer_name ?? 'Supplier'}</p>
                        <p className="text-xs text-slate-500">{item.invoice_number} · {item.days_overdue}d overdue</p>
                      </div>
                      <span className="text-xs font-semibold text-red-400">{formatCurrency(item.amount_due)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="h-40 flex items-center justify-center text-slate-500 text-sm">
              {loading ? 'Loading…' : 'No outstanding payables'}
            </div>
          )}
        </div>
      </div>

      {/* Top Customers table */}
      <div className="card p-0 overflow-hidden">
        <div className="px-5 py-4 border-b border-surface-700">
          <h2 className="text-base font-semibold text-white">Top Customers</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['#', 'Customer', 'Invoices', 'Revenue'].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 4 }).map((_, j) => (
                      <td key={j} className="px-5 py-3.5">
                        <div className="h-4 bg-surface-700 rounded animate-pulse w-24" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : topCustomers.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-5 py-10 text-center text-slate-500 text-sm">No customer data</td>
                </tr>
              ) : (
                topCustomers.map((c, i) => (
                  <tr key={i} className="table-row">
                    <td className="px-5 py-3.5">
                      <span className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${
                        i === 0 ? 'bg-amber-500/20 text-amber-400' :
                        i === 1 ? 'bg-slate-500/20 text-slate-300' :
                        i === 2 ? 'bg-orange-700/20 text-orange-400' : 'bg-surface-700 text-slate-400'
                      }`}>
                        {i + 1}
                      </span>
                    </td>
                    <td className="px-5 py-3.5 text-white font-medium">{c.customer_name ?? 'Walk-in'}</td>
                    <td className="px-5 py-3.5 text-slate-400">{c.invoice_count}</td>
                    <td className="px-5 py-3.5 font-semibold text-brand-400">{formatCurrency(c.revenue)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
