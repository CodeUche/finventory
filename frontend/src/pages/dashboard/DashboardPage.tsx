import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts'
import {
  TrendingUp, TrendingDown, Package,
  AlertTriangle, DollarSign, Zap, ArrowUpRight,
} from 'lucide-react'
import { reportApi, inventoryApi } from '@/services/api'
import { formatCurrency } from '@/lib/utils'
import { format, subDays } from 'date-fns'

const COLORS = ['#f97316', '#3b82f6', '#22c55e', '#a855f7', '#f59e0b']

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  trend,
  trendValue,
  color = 'orange',
  onClick,
}: {
  label: string
  value: string
  sub?: string
  icon: React.ElementType
  trend?: 'up' | 'down'
  trendValue?: string
  color?: 'orange' | 'green' | 'blue' | 'red'
  onClick?: () => void
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
        {onClick && <ArrowUpRight size={14} className="text-slate-600" />}
      </div>
      <div>
        <p className="text-2xl font-bold text-white">{value}</p>
        <p className="text-sm text-slate-400 mt-0.5">{label}</p>
        {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
      </div>
    </div>
  )
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const [pnl, setPnl] = useState<any>(null)
  const [salesData, setSalesData] = useState<any[]>([])
  const [topProducts, setTopProducts] = useState<any[]>([])
  const [lowStock, setLowStock] = useState<any[]>([])
  const [lowStockTotal, setLowStockTotal] = useState(0)
  const [loading, setLoading] = useState(true)

  const today = format(new Date(), 'yyyy-MM-dd')
  const thirtyDaysAgo = format(subDays(new Date(), 30), 'yyyy-MM-dd')
  const firstOfYear = `${new Date().getFullYear()}-01-01`

  useEffect(() => {
    const fetchAll = async () => {
      // Use allSettled so individual failures don't zero out everything
      const [pnlRes, salesRes, topProdRes, lowRes] = await Promise.allSettled([
        reportApi.pnl({ date_from: firstOfYear, date_to: today }),
        reportApi.sales({ date_from: thirtyDaysAgo, date_to: today, group_by: 'day' }),
        reportApi.topProducts({ date_from: thirtyDaysAgo, date_to: today, limit: 5 }),
        inventoryApi.lowStock(),
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
      if (lowRes.status === 'fulfilled') {
        const d = lowRes.value.data
        const items = Array.isArray(d) ? d : (d.results ?? [])
        setLowStockTotal(items.length)
        setLowStock(items.slice(0, 5))
      }
      setLoading(false)
    }
    fetchAll()
  }, [])

  const chartData = salesData.map((d) => ({
    date: format(new Date(d.period), 'MMM d'),
    revenue: parseFloat(d.total_revenue),
    invoices: d.invoice_count,
  }))

  const pieData = topProducts.map((p) => ({
    name: p.product__name?.split(' ').slice(0, 2).join(' ') ?? 'Other',
    value: parseFloat(p.total_revenue),
  }))

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="text-slate-400 text-sm mt-0.5">
            {format(new Date(), 'EEEE, MMMM d yyyy')} · Year-to-date overview
          </p>
        </div>
        <div className="flex items-center gap-2 px-3 py-2 bg-green-500/10 border border-green-500/30 rounded-xl">
          <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
          <span className="text-xs text-green-400 font-medium">Live</span>
        </div>
      </div>

      {/* KPI Cards — all clickable */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard
          label="Total Revenue (YTD)"
          value={formatCurrency(pnl?.revenue?.gross_sales ?? 0)}
          sub="Click to view full report"
          icon={DollarSign}
          color="orange"
          onClick={() => navigate('/reports')}
        />
        <StatCard
          label="Gross Profit"
          value={formatCurrency(pnl?.gross_profit ?? 0)}
          sub={pnl ? `${pnl.gross_margin_pct}% margin` : 'No data yet'}
          icon={TrendingUp}
          color="green"
          onClick={() => navigate('/reports')}
        />
        <StatCard
          label="Net Profit"
          value={formatCurrency(pnl?.net_profit ?? 0)}
          sub={pnl ? `${pnl.net_margin_pct}% net margin` : 'No data yet'}
          icon={Zap}
          color="blue"
          onClick={() => navigate('/reports')}
        />
        <StatCard
          label="Low Stock Alerts"
          value={String(lowStockTotal)}
          sub="Click to view low-stock items"
          icon={AlertTriangle}
          color="red"
          onClick={() => navigate('/inventory/stock?filter=low')}
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Revenue trend */}
        <div className="card xl:col-span-2">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="font-semibold text-white">Revenue Trend</h2>
              <p className="text-sm text-slate-400">Last 30 days</p>
            </div>
          </div>
          {loading ? (
            <div className="h-56 flex items-center justify-center">
              <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : chartData.length === 0 ? (
            <div className="h-56 flex flex-col items-center justify-center text-slate-500">
              <TrendingUp size={28} className="mb-2 opacity-30" />
              <p className="text-sm">Revenue data will appear here after your first sale</p>
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
                  tickFormatter={(v) => `₦${(v / 1000).toFixed(0)}k`} />
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
        </div>

        {/* Top products pie */}
        <div className="card">
          <h2 className="font-semibold text-white mb-1">Top Products</h2>
          <p className="text-sm text-slate-400 mb-4">By revenue, last 30 days</p>
          {loading ? (
            <div className="h-48 flex items-center justify-center">
              <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : pieData.length === 0 ? (
            <div className="h-48 flex flex-col items-center justify-center text-slate-500">
              <Package size={24} className="mb-2 opacity-30" />
              <p className="text-sm text-center">Top products will appear after sales are recorded</p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={55} outerRadius={85}
                  paddingAngle={3} dataKey="value">
                  {pieData.map((_, index) => (
                    <Cell key={index} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: '12px', fontSize: '13px' }}
                  formatter={(v: number) => [formatCurrency(v), 'Revenue']}
                />
                <Legend iconType="circle" iconSize={8}
                  formatter={(value) => <span style={{ color: '#94a3b8', fontSize: '11px' }}>{value}</span>} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Bottom row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top products table */}
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-white">Best Sellers</h2>
            <button onClick={() => navigate('/inventory/products')} className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1">
              View all <ArrowUpRight size={12} />
            </button>
          </div>
          {topProducts.length === 0 ? (
            <div className="flex flex-col items-center py-8 text-slate-500">
              <Package size={28} className="mb-2 opacity-40" />
              <p className="text-sm">No sales data yet</p>
            </div>
          ) : (
            <div className="space-y-2">
              {topProducts.map((p, i) => (
                <div key={i} className="flex items-center gap-3 py-2.5 border-b border-surface-700 last:border-0">
                  <span className="w-6 h-6 bg-surface-700 rounded-lg flex items-center justify-center text-xs font-mono text-slate-400 shrink-0">
                    {i + 1}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-white truncate">{p.product__name}</p>
                    <p className="text-xs text-slate-500">{parseFloat(p.total_quantity).toFixed(0)} units sold</p>
                  </div>
                  <p className="text-sm font-semibold text-brand-400 shrink-0">
                    {formatCurrency(p.total_revenue)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Low stock alerts — clickable rows */}
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
                  className="w-full flex items-center gap-3 py-2.5 border-b border-surface-700 last:border-0 hover:bg-surface-700/30 rounded-lg px-2 -mx-2 transition-colors text-left"
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
