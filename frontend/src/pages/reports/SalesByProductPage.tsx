/**
 * SalesByProductPage — Phase 3 enhancements:
 *  1. Horizontal grouped bar chart — Revenue vs Gross Profit for the top 10 products.
 *  2. Margin scatter chart — revenue (X) vs gross margin % (Y), bubble size = units sold.
 *     Reveals which products are high-volume low-margin vs niche high-margin.
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import { ChevronDown, ChevronRight, Loader2, Package, BarChart2, TrendingUp } from 'lucide-react'
import {
  BarChart, Bar, ScatterChart, Scatter, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { reportApi } from '@/services/api'
import { formatCurrency, formatDate, formatNumber, getCurrencySymbol } from '@/lib/utils'
import { useThemeAccent, getStoredTheme } from '@/hooks/useTheme'
import PeriodSelector, { type PeriodValue } from '@/components/PeriodSelector'
import ExportBar from '@/components/ExportBar'
import type { SalesByProductRow, ProductSaleLine } from '@/types'

function useTooltipStyle() {
  const [isLight, setIsLight] = useState(() => getStoredTheme() === 'light')
  useEffect(() => {
    const h = (e: Event) => setIsLight((e as CustomEvent).detail === 'light')
    window.addEventListener('themechange', h)
    return () => window.removeEventListener('themechange', h)
  }, [])
  return isLight
    ? { backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px', color: '#1e293b', fontSize: 12 }
    : { backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '12px', color: '#f1f5f9', fontSize: 12 }
}

const axisTickStyle = { fill: '#94a3b8', fontSize: 11 }
const trunc = (s: string, n = 14) => s?.length > n ? s.slice(0, n) + '…' : (s ?? '—')

function periodToParams(p: PeriodValue): Record<string, string> {
  const out: Record<string, string> = { period: p.period }
  if (p.date_from) out.date_from = p.date_from
  if (p.date_to)   out.date_to   = p.date_to
  return out
}

export default function SalesByProductPage() {
  const accent = useThemeAccent()
  const tooltipStyle = useTooltipStyle()
  const isLight = getStoredTheme() === 'light'
  const ttLabel = isLight ? '#64748b' : '#94a3b8'
  const ttText  = isLight ? '#1e293b' : '#f1f5f9'
  const [period, setPeriod] = useState<PeriodValue>({ period: 'all' })
  const [rows, setRows]     = useState<SalesByProductRow[]>([])
  const [loading, setLoading] = useState(false)

  const [expandedId, setExpandedId]       = useState<string | null>(null)
  const [detail, setDetail]               = useState<Record<string, ProductSaleLine[]>>({})
  const [loadingDetail, setLoadingDetail] = useState<string | null>(null)

  const params = periodToParams(period)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await reportApi.salesByProduct(params)
      setRows(resp.data)
      setExpandedId(null)
    } catch {
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [period]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load() }, [load])

  const toggleRow = async (productId: string) => {
    if (expandedId === productId) { setExpandedId(null); return }
    setExpandedId(productId)
    if (!detail[productId]) {
      setLoadingDetail(productId)
      try {
        const resp = await reportApi.salesByProduct({ ...params, product_id: productId })
        setDetail(d => ({ ...d, [productId]: resp.data as ProductSaleLine[] }))
      } catch {
        setDetail(d => ({ ...d, [productId]: [] }))
      } finally {
        setLoadingDetail(null)
      }
    }
  }

  const totalRevenue  = rows.reduce((s, r) => s + parseFloat(r.revenue  || '0'), 0)
  const totalProfit   = rows.reduce((s, r) => s + parseFloat(r.gross_profit || '0'), 0)
  const totalUnits    = rows.reduce((s, r) => s + Number(r.units_sold || 0), 0)

  /**
   * Phase 3: Horizontal grouped bar data — top 10 products by revenue.
   * Shows Revenue and Gross Profit side-by-side so profitability is visible
   * without requiring the user to open each row's detail.
   */
  const barChartData = useMemo(() =>
    [...rows]
      .sort((a, b) => parseFloat(b.revenue || '0') - parseFloat(a.revenue || '0'))
      .slice(0, 10)
      .map(r => ({
        name:        trunc(r.product_name, 16),
        Revenue:     parseFloat(r.revenue || '0'),
        GrossProfit: parseFloat(r.gross_profit || '0'),
      })),
  [rows])

  /**
   * Phase 3: Margin scatter data — each point is one product.
   * X = revenue (size of opportunity), Y = gross margin %
   * z = units sold (bubble size — larger bubble = more volume)
   */
  const scatterData = useMemo(() =>
    rows.map(r => {
      const rev    = parseFloat(r.revenue || '0')
      const gp     = parseFloat(r.gross_profit || '0')
      const margin = rev > 0 ? (gp / rev) * 100 : 0
      return {
        name:     r.product_name,
        revenue:  rev,
        margin:   parseFloat(margin.toFixed(1)),
        units:    Number(r.units_sold || 0),
      }
    }).filter(d => d.revenue > 0),
  [rows])

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-0.5">
            <Package size={18} className="text-brand-400" />
            <h1 className="text-xl font-semibold text-white">Sales by Product</h1>
          </div>
          <p className="text-sm text-slate-400">Revenue and profitability per product for the selected period</p>
        </div>
        <ExportBar
          endpoint="/reports/sales-by-product/"
          params={params}
          filenameBase="sales_by_product"
        />
      </div>

      {/* Period selector */}
      <PeriodSelector value={period} onChange={setPeriod} />

      {/* Summary strip */}
      {!loading && rows.length > 0 && (
        <div className="flex gap-4 flex-wrap">
          <div className="bg-surface-800 border border-surface-700 rounded-xl px-4 py-3">
            <p className="text-xs text-slate-500 mb-0.5">Products</p>
            <p className="text-lg font-semibold text-white">{rows.length}</p>
          </div>
          <div className="bg-surface-800 border border-surface-700 rounded-xl px-4 py-3">
            <p className="text-xs text-slate-500 mb-0.5">Units Sold</p>
            <p className="text-lg font-semibold text-white">{totalUnits.toLocaleString()}</p>
          </div>
          <div className="bg-surface-800 border border-surface-700 rounded-xl px-4 py-3">
            <p className="text-xs text-slate-500 mb-0.5">Total Revenue</p>
            <p className="text-lg font-semibold text-emerald-400">{formatCurrency(totalRevenue)}</p>
          </div>
          <div className="bg-surface-800 border border-surface-700 rounded-xl px-4 py-3">
            <p className="text-xs text-slate-500 mb-0.5">Gross Profit</p>
            <p className={`text-lg font-semibold ${totalProfit >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {formatCurrency(totalProfit)}
            </p>
          </div>
        </div>
      )}

      {/* Phase 3: Charts — only shown when data is available */}
      {!loading && rows.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Horizontal grouped bar — Revenue vs Gross Profit (top 10) */}
          <div className="card p-5">
            <div className="flex items-center gap-2 mb-4">
              <BarChart2 size={17} className="text-brand-400" />
              <h2 className="text-sm font-semibold text-white">Top 10 Products: Revenue vs Gross Profit</h2>
            </div>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart
                layout="vertical"
                data={barChartData}
                margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis type="number" tick={axisTickStyle} axisLine={false} tickLine={false}
                  tickFormatter={v => `${getCurrencySymbol()}${formatNumber(v)}`} />
                <YAxis type="category" dataKey="name" tick={axisTickStyle}
                  axisLine={false} tickLine={false} width={100} />
                <Tooltip
                  contentStyle={tooltipStyle}
                  labelStyle={{ color: ttLabel }}
                  itemStyle={{ color: ttText }}
                  formatter={(v: number) => formatCurrency(String(v))}
                />
                <Legend
                  wrapperStyle={{ fontSize: 11, paddingTop: 12, color: '#94a3b8' }}
                  formatter={(val: string) => <span style={{ color: '#94a3b8' }}>{val}</span>}
                />
                <Bar dataKey="Revenue"     fill={accent}    radius={[0, 4, 4, 0]} />
                <Bar dataKey="GrossProfit" fill="#10b981"   radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Margin scatter — Revenue vs Margin%, bubble size = units */}
          <div className="card p-5">
            <div className="flex items-center gap-2 mb-1">
              <TrendingUp size={17} className="text-emerald-400" />
              <h2 className="text-sm font-semibold text-white">Margin Map: Revenue vs Gross Margin %</h2>
            </div>
            <p className="text-xs text-slate-500 mb-4">
              Each dot = one product. Right = more revenue. Up = higher margin. Ideal = top-right.
            </p>
            <ResponsiveContainer width="100%" height={250}>
              <ScatterChart margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis
                  type="number" dataKey="revenue" name="Revenue"
                  tick={axisTickStyle} axisLine={false} tickLine={false}
                  tickFormatter={v => `${getCurrencySymbol()}${formatNumber(v)}`}
                  label={{ value: 'Revenue', position: 'insideBottom', offset: -2, fill: '#64748b', fontSize: 10 }}
                />
                <YAxis
                  type="number" dataKey="margin" name="Margin %"
                  tick={axisTickStyle} axisLine={false} tickLine={false}
                  tickFormatter={v => `${v}%`}
                  label={{ value: 'GP %', angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 10 }}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  cursor={{ strokeDasharray: '3 3', stroke: '#475569' }}
                  content={({ payload }) => {
                    if (!payload?.length) return null
                    const d = payload[0]?.payload as { name: string; revenue: number; margin: number; units: number }
                    return (
                      <div style={{ ...tooltipStyle, padding: '10px 12px' }} className="text-xs space-y-1">
                        <p style={{ color: ttText }} className="font-semibold">{d.name}</p>
                        <p style={{ color: ttLabel }}>Revenue: <span className="text-emerald-400">{formatCurrency(String(d.revenue))}</span></p>
                        <p style={{ color: ttLabel }}>Gross Margin: <span className="text-blue-400">{d.margin}%</span></p>
                        <p style={{ color: ttLabel }}>Units Sold: <span style={{ color: ttText }}>{d.units.toLocaleString()}</span></p>
                      </div>
                    )
                  }}
                />
                <Scatter
                  data={scatterData}
                  name="Products"
                  // Render each point as a circle; r scales with unit volume (min 6 px, max 18 px)
                  shape={(props: any) => {
                    const { cx, cy, payload } = props
                    const maxUnits = Math.max(...scatterData.map(d => d.units), 1)
                    const r = Math.max(6, Math.min(18, 6 + (payload.units / maxUnits) * 12))
                    const fill = payload.margin >= 30 ? '#10b981' : payload.margin >= 15 ? accent : '#ef4444'
                    return <circle cx={cx} cy={cy} r={r} fill={fill} fillOpacity={0.7} stroke={fill} strokeWidth={1} />
                  }}
                />
              </ScatterChart>
            </ResponsiveContainer>
            <div className="flex items-center gap-4 mt-2 text-xs text-slate-500">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> ≥30% margin</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: accent }} /> 15–30%</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500 inline-block" /> &lt;15%</span>
            </div>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-xl border border-surface-700">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-surface-800 border-b border-surface-700">
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wide w-8" />
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wide">Product</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wide">SKU</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-slate-400 uppercase tracking-wide">Units Sold</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-slate-400 uppercase tracking-wide">Revenue</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-slate-400 uppercase tracking-wide">COGS</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-slate-400 uppercase tracking-wide">Gross Profit</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-slate-400 uppercase tracking-wide">Margin</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center">
                  <Loader2 size={22} className="animate-spin mx-auto text-slate-500" />
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-4 py-10 text-center text-slate-500">
                  No sales for the selected period.
                </td>
              </tr>
            ) : (
              rows.map((row, ri) => {
                const key   = row.product_id ?? 'unknown'
                const open  = expandedId === key
                const rev   = parseFloat(row.revenue || '0')
                const gp    = parseFloat(row.gross_profit || '0')
                const margin = rev > 0 ? ((gp / rev) * 100).toFixed(1) : '0.0'
                return (
                  <>
                    <tr
                      key={key}
                      onClick={() => row.product_id && toggleRow(row.product_id)}
                      className={`border-b border-surface-700 transition-colors
                        ${row.product_id ? 'cursor-pointer' : ''}
                        ${ri % 2 === 0 ? 'bg-transparent' : 'bg-surface-900/40'}
                        hover:bg-surface-700/60
                        ${open ? 'bg-surface-700/40' : ''}`}
                    >
                      <td className="px-4 py-3 text-slate-400">
                        {!row.product_id ? null : loadingDetail === key
                          ? <Loader2 size={14} className="animate-spin" />
                          : open
                            ? <ChevronDown size={14} />
                            : <ChevronRight size={14} />
                        }
                      </td>
                      <td className="px-4 py-3 text-slate-200 font-medium">{row.product_name}</td>
                      <td className="px-4 py-3 text-slate-400 font-mono text-xs">
                        {row.product_sku || <span className="text-slate-600">—</span>}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-300">
                        {Number(row.units_sold).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-emerald-400 font-medium">
                        {formatCurrency(row.revenue)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-300">
                        {formatCurrency(row.cogs)}
                      </td>
                      <td className={`px-4 py-3 text-right tabular-nums font-medium
                        ${gp >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {formatCurrency(row.gross_profit)}
                      </td>
                      <td className={`px-4 py-3 text-right tabular-nums text-xs
                        ${parseFloat(margin) >= 0 ? 'text-slate-300' : 'text-red-400'}`}>
                        {margin}%
                      </td>
                    </tr>

                    {open && (
                      <tr key={`${key}-detail`} className="border-b border-surface-700 bg-surface-900/60">
                        <td colSpan={8} className="px-6 py-3">
                          {loadingDetail === key ? (
                            <div className="py-4 text-center">
                              <Loader2 size={18} className="animate-spin mx-auto text-slate-500" />
                            </div>
                          ) : (detail[key] ?? []).length === 0 ? (
                            <p className="text-slate-500 text-xs py-2">No sale lines found.</p>
                          ) : (
                            <table className="w-full text-xs">
                              <thead>
                                <tr className="border-b border-surface-600">
                                  <th className="pb-1.5 text-left text-slate-500 font-medium">Invoice #</th>
                                  <th className="pb-1.5 text-left text-slate-500 font-medium">Date</th>
                                  <th className="pb-1.5 text-left text-slate-500 font-medium">Customer</th>
                                  <th className="pb-1.5 text-right text-slate-500 font-medium">Qty</th>
                                  <th className="pb-1.5 text-right text-slate-500 font-medium">Unit Price</th>
                                  <th className="pb-1.5 text-right text-slate-500 font-medium">Line Total</th>
                                </tr>
                              </thead>
                              <tbody>
                                {(detail[key] ?? []).map((line, li) => (
                                  <tr key={li} className="border-b border-surface-700/50 last:border-0">
                                    <td className="py-1.5 pr-4 text-brand-400 font-mono">{line.invoice_number}</td>
                                    <td className="py-1.5 pr-4 text-slate-300">{formatDate(line.issue_date)}</td>
                                    <td className="py-1.5 pr-4 text-slate-300">{line.customer_name}</td>
                                    <td className="py-1.5 pr-4 text-right tabular-nums text-slate-200">
                                      {Number(line.quantity).toLocaleString()}
                                    </td>
                                    <td className="py-1.5 pr-4 text-right tabular-nums text-slate-300">
                                      {formatCurrency(line.unit_price)}
                                    </td>
                                    <td className="py-1.5 text-right tabular-nums text-emerald-400">
                                      {formatCurrency(line.line_total)}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          )}
                        </td>
                      </tr>
                    )}
                  </>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
