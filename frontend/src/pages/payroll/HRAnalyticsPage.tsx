import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { BarChart3, Loader2, TrendingDown, TrendingUp, Users, Building2, AlertTriangle } from 'lucide-react'
import toast from 'react-hot-toast'

import { hrApi } from '@/services/hrApi'
import { formatCurrency } from '@/lib/utils'
import YearFilter from '@/components/YearFilter'

const CURRENT_YEAR = new Date().getFullYear()

interface HeadcountTurnover {
  year: number
  headcount_start_of_year: number
  joiners_by_month: { month: string; count: number }[]
  leavers_by_month: { month: string; count: number }[]
  total_joiners: number
  total_leavers: number
  attrition_percent: number
}

interface DeptCost {
  department: string
  total_gross: string
  total_net: string
  headcount: number
}

interface TenureDemographics {
  gender: Record<string, number | null>
  marital_status: Record<string, number | null>
  tenure_buckets: Record<string, number | null>
}

interface ExpiringDocument {
  id: string
  employee: string
  name: string
  document_type: string
  expiry_date: string
}

const COLORS = ['#6366f1', '#22d3ee', '#f59e0b', '#ef4444', '#10b981', '#a855f7']

const tooltipStyle = {
  backgroundColor: '#161b26', border: '1px solid rgba(255,255,255,0.1)',
  borderRadius: 8, fontSize: 12,
}

function StatTile({ label, value, icon: Icon, tone = 'default' }: {
  label: string; value: string | number; icon: React.ElementType; tone?: 'default' | 'up' | 'down'
}) {
  const toneClass = tone === 'up' ? 'text-emerald-400' : tone === 'down' ? 'text-red-400' : 'text-white'
  return (
    <div className="card p-4 flex items-center gap-3">
      <div className="w-10 h-10 rounded-xl bg-brand-500/10 flex items-center justify-center shrink-0">
        <Icon className="w-5 h-5 text-brand-400" />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-slate-400">{label}</p>
        <p className={`text-lg font-bold font-mono ${toneClass}`}>{value}</p>
      </div>
    </div>
  )
}

export default function HRAnalyticsPage() {
  const [loading, setLoading] = useState(true)
  const [selectedYear, setSelectedYear] = useState<number | null>(null)
  const year = selectedYear ?? CURRENT_YEAR
  const [headcount, setHeadcount] = useState<HeadcountTurnover | null>(null)
  const [deptCosts, setDeptCosts] = useState<DeptCost[]>([])
  const [absence, setAbsence] = useState<Record<string, number>>({})
  const [demographics, setDemographics] = useState<TenureDemographics | null>(null)
  const [expiringDocs, setExpiringDocs] = useState<ExpiringDocument[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [hcRes, deptRes, absRes, demoRes, docsRes] = await Promise.all([
        hrApi.headcountTurnover(year),
        hrApi.costByDepartment(year),
        hrApi.absenceSummary(year),
        hrApi.tenureDemographics(),
        hrApi.expiringDocuments(60),
      ])
      setHeadcount(hcRes.data)
      setDeptCosts(deptRes.data)
      setAbsence(absRes.data)
      setDemographics(demoRes.data)
      setExpiringDocs(docsRes.data)
    } catch {
      toast.error('Could not load HR analytics')
    } finally {
      setLoading(false)
    }
  }, [year])

  useEffect(() => { void load() }, [load])

  const deptChartData = useMemo(
    () => deptCosts.map((d) => ({ name: d.department, gross: parseFloat(d.total_gross || '0') })),
    [deptCosts],
  )

  const monthlyTrend = useMemo(() => {
    if (!headcount) return []
    const byMonth: Record<string, { month: string; joiners: number; leavers: number }> = {}
    for (const j of headcount.joiners_by_month) {
      byMonth[j.month] ??= { month: j.month, joiners: 0, leavers: 0 }
      byMonth[j.month].joiners = j.count
    }
    for (const l of headcount.leavers_by_month) {
      byMonth[l.month] ??= { month: l.month, joiners: 0, leavers: 0 }
      byMonth[l.month].leavers = l.count
    }
    return Object.values(byMonth).sort((a, b) => a.month.localeCompare(b.month))
  }, [headcount])

  const tenureChartData = useMemo(() => {
    if (!demographics) return []
    return Object.entries(demographics.tenure_buckets)
      .filter(([, v]) => v !== null)
      .map(([name, value]) => ({ name, value: value as number }))
  }, [demographics])

  // NDPR: buckets under 5 people are suppressed server-side (returned as
  // null) — surfaced here rather than silently omitted, so the reader knows
  // data was withheld for privacy, not that it doesn't exist.
  const suppressedGenderBuckets = demographics
    ? Object.entries(demographics.gender).filter(([, v]) => v === null).map(([k]) => k)
    : []

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-brand-400" />
            HR Analytics
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">Headcount, turnover, cost and demographics</p>
        </div>
        <YearFilter selectedYear={selectedYear} onChange={setSelectedYear} />
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 animate-spin text-brand-400" />
        </div>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Headcount (start of year)" value={headcount?.headcount_start_of_year ?? 0} icon={Users} />
            <StatTile label="Joiners" value={headcount?.total_joiners ?? 0} icon={TrendingUp} tone="up" />
            <StatTile label="Leavers" value={headcount?.total_leavers ?? 0} icon={TrendingDown} tone="down" />
            <StatTile
              label="Attrition rate"
              value={`${headcount?.attrition_percent ?? 0}%`}
              icon={BarChart3}
              tone={(headcount?.attrition_percent ?? 0) > 15 ? 'down' : 'default'}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="card p-4">
              <p className="text-xs uppercase tracking-wider text-slate-400 mb-3">Joiners vs leavers by month</p>
              {monthlyTrend.length === 0 ? (
                <p className="text-sm text-slate-400 py-12 text-center">No movement recorded for {year}.</p>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={monthlyTrend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="month" tick={{ fontSize: 10, fill: '#94a3b8' }} />
                    <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} allowDecimals={false} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Bar dataKey="joiners" fill="#10b981" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="leavers" fill="#ef4444" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </div>

            <div className="card p-4">
              <p className="text-xs uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
                <Building2 className="w-3.5 h-3.5" /> Cost by department
              </p>
              {deptChartData.length === 0 ? (
                <p className="text-sm text-slate-400 py-12 text-center">No payroll data for {year}.</p>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <PieChart>
                    <Pie data={deptChartData} cx="50%" cy="45%" innerRadius={55} outerRadius={90} paddingAngle={3} dataKey="gross">
                      {deptChartData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                    </Pie>
                    <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => formatCurrency(v)} />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="card p-4">
              <p className="text-xs uppercase tracking-wider text-slate-400 mb-3">Absence summary</p>
              <div className="grid grid-cols-2 gap-2 text-sm">
                {Object.entries(absence).length === 0 ? (
                  <p className="text-slate-400 col-span-2 text-center py-6">No attendance recorded for {year}.</p>
                ) : (
                  Object.entries(absence).map(([status, count]) => (
                    <div key={status} className="flex items-center justify-between px-3 py-2 rounded-lg bg-white/[0.03]">
                      <span className="text-slate-300 capitalize">{status.replace(/_/g, ' ')}</span>
                      <span className="font-mono text-white">{count}</span>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="card p-4">
              <p className="text-xs uppercase tracking-wider text-slate-400 mb-3">Tenure distribution</p>
              {tenureChartData.length === 0 ? (
                <p className="text-sm text-slate-400 py-12 text-center">No tenure data to show.</p>
              ) : (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={tenureChartData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis type="number" tick={{ fontSize: 10, fill: '#94a3b8' }} allowDecimals={false} />
                    <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: '#94a3b8' }} width={60} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Bar dataKey="value" fill="#6366f1" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
              {suppressedGenderBuckets.length > 0 && (
                <p className="text-[10px] text-slate-500 mt-3">
                  Some demographic breakdowns are withheld because the group has fewer than 5 people (NDPR).
                </p>
              )}
            </div>
          </div>

          <div className="card p-4">
            <p className="text-xs uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5" /> Documents expiring soon (60 days)
            </p>
            {expiringDocs.length === 0 ? (
              <p className="text-sm text-slate-400 py-6 text-center">No employee documents expiring soon.</p>
            ) : (
              <div className="divide-y divide-white/5">
                {expiringDocs.map((doc) => (
                  <div key={doc.id} className="flex items-center justify-between py-2 text-sm">
                    <span className="text-slate-300">{doc.name}</span>
                    <span className="font-mono text-xs text-amber-400">{doc.expiry_date}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
