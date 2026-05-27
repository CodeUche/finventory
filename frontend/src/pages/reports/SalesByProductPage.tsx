import { useState, useEffect, useCallback } from 'react'
import { ChevronDown, ChevronRight, Loader2, Package } from 'lucide-react'
import { reportApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import PeriodSelector, { type PeriodValue } from '@/components/PeriodSelector'
import ExportBar from '@/components/ExportBar'
import type { SalesByProductRow, ProductSaleLine } from '@/types'

function periodToParams(p: PeriodValue): Record<string, string> {
  const out: Record<string, string> = { period: p.period }
  if (p.date_from) out.date_from = p.date_from
  if (p.date_to)   out.date_to   = p.date_to
  return out
}

export default function SalesByProductPage() {
  const [period, setPeriod] = useState<PeriodValue>({ period: 'month' })
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
