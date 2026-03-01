import { useEffect, useState } from 'react'
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
import { BarChart2, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react'
import toast from 'react-hot-toast'
import { reportApi } from '@/services/api'
import { formatCurrency, formatNumber } from '@/lib/utils'
import type { PnL, SalesSummaryPoint } from '@/types'

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
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(true)

  const [pnl, setPnl] = useState<PnL | null>(null)
  const [salesTrend, setSalesTrend] = useState<SalesSummaryPoint[]>([])
  const [topProducts, setTopProducts] = useState<TopProduct[]>([])
  const [topCustomers, setTopCustomers] = useState<TopCustomer[]>([])
  const [expenseBreakdown, setExpenseBreakdown] = useState<ExpenseBreakdown[]>([])

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
      const [pnlRes, salesRes, prodRes, custRes, expRes] = await Promise.allSettled([
        reportApi.pnl(range),
        reportApi.sales({ ...range, granularity }),
        reportApi.topProducts({ ...range, limit: 6 }),
        reportApi.topCustomers({ ...range, limit: 5 }),
        reportApi.expenses(range),
      ])

      if (pnlRes.status === 'fulfilled') setPnl(pnlRes.value.data)
      if (salesRes.status === 'fulfilled') setSalesTrend(salesRes.value.data.results ?? salesRes.value.data)
      if (prodRes.status === 'fulfilled') setTopProducts(prodRes.value.data.results ?? prodRes.value.data)
      if (custRes.status === 'fulfilled') setTopCustomers(custRes.value.data.results ?? custRes.value.data)
      if (expRes.status === 'fulfilled') setExpenseBreakdown(expRes.value.data.results ?? expRes.value.data)
    } catch { toast.error('Failed to load reports') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [days])

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
            onClick={load}
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
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => `₦${formatNumber(v)}`} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => formatCurrency(v)} />
              <Legend wrapperStyle={{ fontSize: 12, paddingTop: 16 }} />
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
                  name: p.product_name.length > 16 ? p.product_name.slice(0, 16) + '…' : p.product_name,
                  Revenue: parseFloat(p.revenue),
                  Units: parseFloat(p.units_sold),
                }))}
                margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v) => `₦${formatNumber(v)}`} />
                <Tooltip contentStyle={tooltipStyle} formatter={(v: number, name: string) => name === 'Revenue' ? formatCurrency(v) : formatNumber(v)} />
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
                <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => formatCurrency(v)} />
                <Legend
                  wrapperStyle={{ fontSize: 11, paddingTop: 12 }}
                  formatter={(value: string) => <span style={{ color: '#94a3b8' }}>{value}</span>}
                />
              </PieChart>
            </ResponsiveContainer>
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
