import { useState, useEffect, useCallback } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { ChevronDown, ChevronRight, Loader2, Users } from 'lucide-react'
import { reportApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import PeriodSelector, { type PeriodValue } from '@/components/PeriodSelector'
import ExportBar from '@/components/ExportBar'
import type { SalesByCustomerRow, CustomerInvoiceDetail } from '@/types'

function periodToParams(p: PeriodValue): Record<string, string> {
  const out: Record<string, string> = { period: p.period }
  if (p.date_from) out.date_from = p.date_from
  if (p.date_to)   out.date_to   = p.date_to
  return out
}

const STATUS_COLOR: Record<string, string> = {
  paid:           'text-emerald-400',
  confirmed:      'text-blue-400',
  partially_paid: 'text-amber-400',
}

export default function SalesByCustomerPage() {
  const [period, setPeriod] = useState<PeriodValue>({ period: 'all' })
  const [rows, setRows]     = useState<SalesByCustomerRow[]>([])
  const [loading, setLoading] = useState(false)

  const [expandedId, setExpandedId]   = useState<string | null>(null)
  const [detail, setDetail]           = useState<Record<string, CustomerInvoiceDetail[]>>({})
  const [loadingDetail, setLoadingDetail] = useState<string | null>(null)

  const params = periodToParams(period)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await reportApi.salesByCustomer(params)
      setRows(resp.data)
      setExpandedId(null)
    } catch {
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [period]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load() }, [load])
  useDataRefresh(load)

  const toggleRow = async (key: string) => {
    if (expandedId === key) { setExpandedId(null); return }
    setExpandedId(key)
    if (!detail[key]) {
      setLoadingDetail(key)
      try {
        const resp = await reportApi.salesByCustomer({ ...params, customer_id: key })
        setDetail(d => ({ ...d, [key]: resp.data as CustomerInvoiceDetail[] }))
      } catch {
        setDetail(d => ({ ...d, [key]: [] }))
      } finally {
        setLoadingDetail(null)
      }
    }
  }

  const rowKey = (r: SalesByCustomerRow) => r.customer_id ?? 'walk-in'

  const totalRevenue = rows.reduce((s, r) => s + parseFloat(r.revenue || '0'), 0)

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-0.5">
            <Users size={18} className="text-brand-400" />
            <h1 className="text-xl font-semibold text-white">Sales by Customer</h1>
          </div>
          <p className="text-sm text-slate-400">Revenue breakdown per customer for the selected period</p>
        </div>
        <ExportBar
          endpoint="/reports/sales-by-customer/"
          params={params}
          filenameBase="sales_by_customer"
        />
      </div>

      {/* Period selector */}
      <PeriodSelector value={period} onChange={setPeriod} />

      {/* Summary strip */}
      {!loading && rows.length > 0 && (
        <div className="flex gap-4 flex-wrap">
          <div className="bg-surface-800 border border-surface-700 rounded-xl px-4 py-3">
            <p className="text-xs text-slate-500 mb-0.5">Customers</p>
            <p className="text-lg font-semibold text-white">{rows.length}</p>
          </div>
          <div className="bg-surface-800 border border-surface-700 rounded-xl px-4 py-3">
            <p className="text-xs text-slate-500 mb-0.5">Total Revenue</p>
            <p className="text-lg font-semibold text-emerald-400">{formatCurrency(totalRevenue)}</p>
          </div>
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-xl border border-surface-700">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-surface-800 border-b border-surface-700">
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wide w-8" />
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wide">Customer</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wide">Code</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-slate-400 uppercase tracking-wide">Invoices</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-slate-400 uppercase tracking-wide">Revenue</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-slate-400 uppercase tracking-wide">Paid</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-slate-400 uppercase tracking-wide">Outstanding</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center">
                  <Loader2 size={22} className="animate-spin mx-auto text-slate-500" />
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center text-slate-500">
                  No sales for the selected period.
                </td>
              </tr>
            ) : (
              rows.map((row, ri) => {
                const key  = rowKey(row)
                const open = expandedId === key
                return (
                  <>
                    <tr
                      key={key}
                      onClick={() => toggleRow(key)}
                      className={`border-b border-surface-700 cursor-pointer transition-colors
                        ${ri % 2 === 0 ? 'bg-transparent' : 'bg-surface-900/40'}
                        hover:bg-surface-700/60
                        ${open ? 'bg-surface-700/40' : ''}`}
                    >
                      <td className="px-4 py-3 text-slate-400">
                        {loadingDetail === key
                          ? <Loader2 size={14} className="animate-spin" />
                          : open
                            ? <ChevronDown size={14} />
                            : <ChevronRight size={14} />
                        }
                      </td>
                      <td className="px-4 py-3 text-slate-200 font-medium">{row.customer_name}</td>
                      <td className="px-4 py-3 text-slate-400">{row.customer_code || <span className="text-slate-600">—</span>}</td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-300">{row.invoice_count}</td>
                      <td className="px-4 py-3 text-right tabular-nums text-emerald-400 font-medium">{formatCurrency(row.revenue)}</td>
                      <td className="px-4 py-3 text-right tabular-nums text-slate-300">{formatCurrency(row.amount_paid)}</td>
                      <td className="px-4 py-3 text-right tabular-nums text-amber-400">{formatCurrency(row.amount_outstanding)}</td>
                    </tr>

                    {open && (
                      <tr key={`${key}-detail`} className="border-b border-surface-700 bg-surface-900/60">
                        <td colSpan={7} className="px-6 py-3">
                          {loadingDetail === key ? (
                            <div className="py-4 text-center">
                              <Loader2 size={18} className="animate-spin mx-auto text-slate-500" />
                            </div>
                          ) : (detail[key] ?? []).length === 0 ? (
                            <p className="text-slate-500 text-xs py-2">No invoices found.</p>
                          ) : (
                            <table className="w-full text-xs">
                              <thead>
                                <tr className="border-b border-surface-600">
                                  <th className="pb-1.5 text-left text-slate-500 font-medium">Invoice #</th>
                                  <th className="pb-1.5 text-left text-slate-500 font-medium">Date</th>
                                  <th className="pb-1.5 text-left text-slate-500 font-medium">Status</th>
                                  <th className="pb-1.5 text-right text-slate-500 font-medium">Total</th>
                                  <th className="pb-1.5 text-right text-slate-500 font-medium">Paid</th>
                                  <th className="pb-1.5 text-right text-slate-500 font-medium">Due</th>
                                </tr>
                              </thead>
                              <tbody>
                                {(detail[key] ?? []).map(inv => (
                                  <tr key={inv.id} className="border-b border-surface-700/50 last:border-0">
                                    <td className="py-1.5 pr-4 text-brand-400 font-mono">{inv.invoice_number}</td>
                                    <td className="py-1.5 pr-4 text-slate-300">{formatDate(inv.issue_date)}</td>
                                    <td className={`py-1.5 pr-4 capitalize ${STATUS_COLOR[inv.status] ?? 'text-slate-400'}`}>
                                      {inv.status.replace('_', ' ')}
                                    </td>
                                    <td className="py-1.5 pr-4 text-right tabular-nums text-slate-200">{formatCurrency(inv.total_amount)}</td>
                                    <td className="py-1.5 pr-4 text-right tabular-nums text-slate-300">{formatCurrency(inv.amount_paid)}</td>
                                    <td className="py-1.5 text-right tabular-nums text-amber-400">{formatCurrency(inv.amount_due)}</td>
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
