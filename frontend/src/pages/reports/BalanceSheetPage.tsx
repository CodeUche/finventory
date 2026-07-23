/**
 * BalanceSheetPage — Phase 4 enhancements:
 *  1. Asset mix donut  — Current Assets vs Fixed Assets vs Other Assets.
 *  2. Liabilities & Equity donut — shows the capital structure at a glance.
 *  3. Financial ratios strip — Working Capital, Current Ratio, D/E Ratio.
 *     These three numbers are what a banker or board member asks for first.
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import {
  Scale, Loader2, RefreshCw, CheckCircle, AlertTriangle,
  ChevronDown, ChevronUp,
} from 'lucide-react'
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import toast from 'react-hot-toast'
import { accountingApi, bypassNextGets } from '@/services/api'
import { formatCurrency } from '@/lib/utils'
import { useThemeAccent } from '@/hooks/useTheme'

const tooltipStyle = { backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '12px', color: '#f1f5f9', fontSize: 12 }

interface BSAccount { code: string; name: string; balance: string | number }
interface BalanceSheetData {
  assets: BSAccount[]
  liabilities: BSAccount[]
  equity: BSAccount[]
  total_assets: string | number
  total_liabilities: string | number
  total_equity: string | number
}

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

// Account code groupings for display
const ASSET_GROUPS: { label: string; from: number; to: number }[] = [
  // Current assets run 1000–1499 (cash, bank, AR, inventory, prepaids, VAT
  // receivable). Fixed assets are 1500–1599; everything else is "other".
  { label: 'Current Assets', from: 1000, to: 1499 },
  { label: 'Fixed Assets', from: 1500, to: 1599 },
  { label: 'Other Assets', from: 1600, to: 1999 },
]
const LIABILITY_GROUPS: { label: string; from: number; to: number }[] = [
  { label: 'Current Liabilities', from: 2000, to: 2499 },
  { label: 'Long-term Liabilities', from: 2500, to: 2999 },
]
const EQUITY_GROUPS: { label: string; from: number; to: number }[] = [
  { label: 'Share Capital & Reserves', from: 3000, to: 3099 },
  { label: 'Retained Earnings', from: 3100, to: 3999 },
]

function groupAccounts(accounts: BSAccount[], groups: { label: string; from: number; to: number }[]) {
  const result: { label: string; accounts: BSAccount[] }[] = []
  const ungrouped: BSAccount[] = []

  for (const acct of accounts) {
    const code = parseInt(acct.code, 10)
    const grp = groups.find(g => code >= g.from && code <= g.to)
    if (grp) {
      const existing = result.find(r => r.label === grp.label)
      if (existing) existing.accounts.push(acct)
      else result.push({ label: grp.label, accounts: [acct] })
    } else {
      ungrouped.push(acct)
    }
  }

  if (ungrouped.length) result.push({ label: 'Other', accounts: ungrouped })
  return result
}

export default function BalanceSheetPage() {
  const navigate = useNavigate()
  const accent   = useThemeAccent()
  const now = new Date()
  const [selectedYear, setSelectedYear] = useState(now.getFullYear())
  const [selectedMonth, setSelectedMonth] = useState(now.getMonth() + 1)
  const [data, setData] = useState<BalanceSheetData | null>(null)
  const [loading, setLoading] = useState(true)
  const [noAccounts, setNoAccounts] = useState(false)
  const [seeding, setSeeding] = useState(false)

  // Last day of the selected month as the as_of date
  const asOf = (() => {
    const lastDay = new Date(selectedYear, selectedMonth, 0).getDate()
    return `${selectedYear}-${String(selectedMonth).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`
  })()

  // True if the selected period is strictly in the future (after current month)
  const isFuturePeriod =
    selectedYear > now.getFullYear() ||
    (selectedYear === now.getFullYear() && selectedMonth > now.getMonth() + 1)

  const load = async () => {
    if (isFuturePeriod) {
      setData(null)
      setNoAccounts(false)
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const { data: d } = await accountingApi.balanceSheet({ as_of: asOf })
      if (!d.assets?.length && !d.liabilities?.length && !d.equity?.length) {
        setNoAccounts(true)
      } else {
        setData(d)
        setNoAccounts(false)
      }
    } catch {
      toast.error('Failed to load balance sheet')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [selectedYear, selectedMonth])
  useDataRefresh(load)

  const handleSeed = async () => {
    setSeeding(true)
    try {
      await accountingApi.seedCoa()
      toast.success('Chart of accounts seeded')
      load()
    } catch {
      toast.error('Failed to seed chart of accounts')
    } finally {
      setSeeding(false)
    }
  }

  const totalAssets     = parseFloat(String(data?.total_assets     ?? 0))
  const totalLiab       = parseFloat(String(data?.total_liabilities ?? 0))
  const totalEquity     = parseFloat(String(data?.total_equity     ?? 0))
  const totalLiabEquity = totalLiab + totalEquity
  const isBalanced      = data ? Math.abs(totalAssets - totalLiabEquity) < 0.01 : false

  /**
   * Phase 4: Derived ratios and donut data — computed once whenever `data` changes.
   */
  const { assetDonut, structureDonut, ratios } = useMemo(() => {
    if (!data) return { assetDonut: [], structureDonut: [], ratios: null }

    // Bucket assets by code range for the donut
    const sumGroup = (accts: BSAccount[], from: number, to: number) =>
      accts
        .filter(a => { const c = parseInt(a.code, 10); return c >= from && c <= to })
        .reduce((s, a) => s + parseFloat(String(a.balance)), 0)

    const currentAssets = sumGroup(data.assets, 1000, 1499)
    const fixedAssets   = sumGroup(data.assets, 1500, 1599)
    const otherAssets   = sumGroup(data.assets, 1600, 1999)

    // Current liabilities (codes 2000–2499) for Current Ratio
    const currentLiab = sumGroup(data.liabilities, 2000, 2499)

    const assetDonut = [
      { name: 'Current Assets', value: Math.abs(currentAssets) },
      { name: 'Fixed Assets',   value: Math.abs(fixedAssets)   },
      { name: 'Other Assets',   value: Math.abs(otherAssets)   },
    ].filter(d => d.value > 0)

    const structureDonut = [
      { name: 'Liabilities', value: Math.abs(totalLiab)   },
      { name: 'Equity',      value: Math.abs(totalEquity) },
    ].filter(d => d.value > 0)

    const workingCapital  = currentAssets - currentLiab
    const currentRatio    = currentLiab > 0 ? currentAssets / currentLiab : null
    const debtEquityRatio = totalEquity  > 0 ? totalLiab / totalEquity     : null

    return {
      assetDonut,
      structureDonut,
      ratios: { workingCapital, currentRatio, debtEquityRatio },
    }
  }, [data, totalLiab, totalEquity])

  const yearOptions = Array.from({ length: 6 }, (_, i) => now.getFullYear() - i)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Balance Sheet</h1>
          <p className="text-slate-400 text-sm mt-0.5">Statement of financial position</p>
        </div>
        <div className="flex items-center gap-2">
          {/* Month selector */}
          <select
            value={selectedMonth}
            onChange={e => setSelectedMonth(Number(e.target.value))}
            className="input text-sm py-1.5"
          >
            {MONTHS.map((m, i) => (
              <option key={m} value={i + 1}>{m}</option>
            ))}
          </select>
          {/* Year selector */}
          <select
            value={selectedYear}
            onChange={e => setSelectedYear(Number(e.target.value))}
            className="input text-sm py-1.5"
          >
            {yearOptions.map(y => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
          <button onClick={() => { bypassNextGets(); load() }} className="btn-ghost flex items-center gap-2 text-sm">
            <RefreshCw size={15} /> Refresh
          </button>
        </div>
      </div>

      {/* As-of label */}
      <p className="text-xs text-slate-500">As of {MONTHS[selectedMonth - 1]} {selectedYear} (end of month)</p>

      {isFuturePeriod ? (
        <div className="card p-12 text-center">
          <Scale size={40} className="mx-auto text-slate-600 mb-4" />
          <p className="text-white font-semibold mb-2">No data for this period</p>
          <p className="text-slate-400 text-sm">{MONTHS[selectedMonth - 1]} {selectedYear} is in the future — no transactions have been recorded yet.</p>
        </div>
      ) : loading ? (
        <div className="card p-16 flex justify-center">
          <Loader2 className="animate-spin text-slate-500" size={32} />
        </div>
      ) : noAccounts ? (
        <div className="card p-12 text-center">
          <Scale size={40} className="mx-auto text-slate-600 mb-4" />
          <p className="text-white font-semibold mb-2">No chart of accounts found</p>
          <p className="text-slate-400 text-sm mb-6">Seed the default Nigerian chart of accounts to get started, or create accounts manually.</p>
          <div className="flex justify-center gap-3">
            <button onClick={handleSeed} disabled={seeding} className="btn-primary disabled:opacity-50">
              {seeding ? <><Loader2 size={14} className="animate-spin" /> Seeding…</> : 'Seed Default COA'}
            </button>
            <button onClick={() => navigate('/accounting/coa')} className="btn-ghost">Manage Accounts</button>
          </div>
        </div>
      ) : data ? (
        <>
          {/* Balance indicator */}
          <div className={`flex items-center gap-3 p-4 rounded-xl border ${
            isBalanced
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
              : 'bg-red-500/10 border-red-500/30 text-red-400'
          }`}>
            {isBalanced
              ? <><CheckCircle size={18} /> <span className="font-semibold">Balanced — Assets equal Liabilities + Equity</span></>
              : <><AlertTriangle size={18} /> <span className="font-semibold">Not balanced — difference: {formatCurrency(String(Math.abs(totalAssets - totalLiabEquity)))}</span></>
            }
          </div>

          {/* Phase 4: Composition donuts + financial ratios */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

            {/* Asset mix donut */}
            <div className="card p-5">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Asset Mix</p>
              {assetDonut.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie data={assetDonut} cx="50%" cy="45%"
                      innerRadius={50} outerRadius={72} paddingAngle={3} dataKey="value">
                      {assetDonut.map((_, i) => (
                        <Cell key={i} fill={[accent, '#3b82f6', '#a855f7'][i % 3]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={tooltipStyle}
                      labelStyle={{ color: '#94a3b8' }} itemStyle={{ color: '#f1f5f9' }}
                      formatter={(v: number) => formatCurrency(String(v))} />
                    <Legend
                      wrapperStyle={{ fontSize: 10, paddingTop: 4 }}
                      formatter={(v: string) => <span style={{ color: '#94a3b8' }}>{v}</span>}
                    />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-40 flex items-center justify-center">
                  <p className="text-slate-500 text-xs text-center">No asset balances recorded.<br/>Post transactions to see asset mix.</p>
                </div>
              )}
              <p className="text-center text-xs text-slate-500 mt-1">
                Total: <span className="text-white font-semibold">{formatCurrency(String(totalAssets))}</span>
              </p>
            </div>

            {/* Liabilities & Equity structure donut */}
            <div className="card p-5">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Capital Structure</p>
              {structureDonut.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie data={structureDonut} cx="50%" cy="45%"
                      innerRadius={50} outerRadius={72} paddingAngle={3} dataKey="value">
                      {structureDonut.map((_, i) => (
                        <Cell key={i} fill={['#ef4444', '#10b981'][i % 2]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={tooltipStyle}
                      labelStyle={{ color: '#94a3b8' }} itemStyle={{ color: '#f1f5f9' }}
                      formatter={(v: number) => formatCurrency(String(v))} />
                    <Legend
                      wrapperStyle={{ fontSize: 10, paddingTop: 4 }}
                      formatter={(v: string) => <span style={{ color: '#94a3b8' }}>{v}</span>}
                    />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-40 flex items-center justify-center">
                  <p className="text-slate-500 text-xs text-center">No liability or equity balances.<br/>Capital structure shows once accounts are seeded.</p>
                </div>
              )}
              <p className="text-center text-xs text-slate-500 mt-1">
                Total: <span className="text-white font-semibold">{formatCurrency(String(totalLiabEquity))}</span>
              </p>
            </div>

            {/* Financial ratios */}
            <div className="card p-5 space-y-4">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Financial Ratios</p>
              {ratios ? (
                <>
                  <RatioRow
                    label="Working Capital"
                    value={formatCurrency(String(ratios.workingCapital))}
                    sub="Current Assets − Current Liabilities"
                    status={ratios.workingCapital > 0 ? 'good' : 'bad'}
                  />
                  <RatioRow
                    label="Current Ratio"
                    value={ratios.currentRatio !== null ? `${ratios.currentRatio.toFixed(2)}×` : 'N/A'}
                    sub="Current Assets ÷ Current Liabilities"
                    status={
                      ratios.currentRatio === null ? 'neutral'
                      : ratios.currentRatio >= 2   ? 'good'
                      : ratios.currentRatio >= 1   ? 'warn'
                      : 'bad'
                    }
                    hint={
                      ratios.currentRatio === null ? undefined
                      : ratios.currentRatio >= 2   ? 'Healthy liquidity'
                      : ratios.currentRatio >= 1   ? 'Acceptable — watch closely'
                      : 'Risk — may not cover short-term obligations'
                    }
                  />
                  <RatioRow
                    label="D/E Ratio"
                    value={ratios.debtEquityRatio !== null ? ratios.debtEquityRatio.toFixed(2) : 'N/A'}
                    sub="Total Liabilities ÷ Total Equity"
                    status={
                      ratios.debtEquityRatio === null ? 'neutral'
                      : ratios.debtEquityRatio <= 1   ? 'good'
                      : ratios.debtEquityRatio <= 2   ? 'warn'
                      : 'bad'
                    }
                    hint={
                      ratios.debtEquityRatio === null ? undefined
                      : ratios.debtEquityRatio <= 1   ? 'Low leverage — conservative'
                      : ratios.debtEquityRatio <= 2   ? 'Moderate leverage'
                      : 'High leverage — review debt obligations'
                    }
                  />
                </>
              ) : (
                <p className="text-slate-500 text-xs">No data</p>
              )}
            </div>
          </div>

          {/* 3-column account detail */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Assets */}
            <BSSection
              title="ASSETS"
              headerColor="text-emerald-400 border-emerald-500/30 bg-emerald-500/10"
              accounts={data.assets}
              groups={ASSET_GROUPS}
              total={data.total_assets}
              totalLabel="TOTAL ASSETS"
            />
            {/* Liabilities */}
            <BSSection
              title="LIABILITIES"
              headerColor="text-red-400 border-red-500/30 bg-red-500/10"
              accounts={data.liabilities}
              groups={LIABILITY_GROUPS}
              total={data.total_liabilities}
              totalLabel="TOTAL LIABILITIES"
            />
            {/* Equity */}
            <BSSection
              title="EQUITY"
              headerColor="text-blue-400 border-blue-500/30 bg-blue-500/10"
              accounts={data.equity}
              groups={EQUITY_GROUPS}
              total={data.total_equity}
              totalLabel="TOTAL EQUITY"
            />
          </div>

          {/* Net position */}
          <div className="card p-5">
            <div className="flex items-center justify-between">
              <p className="text-slate-400 font-semibold">Liabilities + Equity</p>
              <p className="text-white font-bold text-xl font-mono">{formatCurrency(String(totalLiabEquity))}</p>
            </div>
            <div className="flex items-center justify-between mt-2 pt-2 border-t border-surface-700">
              <p className="text-slate-400 font-semibold">Total Assets</p>
              <p className="text-white font-bold text-xl font-mono">{formatCurrency(String(totalAssets))}</p>
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}

/** Phase 4: Colour-coded ratio row with traffic-light status indicator. */
function RatioRow({
  label, value, sub, status, hint,
}: {
  label: string; value: string; sub: string
  status: 'good' | 'warn' | 'bad' | 'neutral'; hint?: string
}) {
  const color = status === 'good' ? 'text-emerald-400' : status === 'warn' ? 'text-amber-400' : status === 'bad' ? 'text-red-400' : 'text-slate-300'
  const dot   = status === 'good' ? 'bg-emerald-500' : status === 'warn' ? 'bg-amber-500' : status === 'bad' ? 'bg-red-500' : 'bg-slate-500'
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full shrink-0 ${dot}`} />
          <span className="text-xs text-slate-400">{label}</span>
        </div>
        <span className={`text-sm font-bold font-mono ${color}`}>{value}</span>
      </div>
      <p className="text-xs text-slate-600 pl-3.5">{sub}</p>
      {hint && <p className={`text-xs pl-3.5 ${color} opacity-75`}>{hint}</p>}
    </div>
  )
}

function BSSection({
  title, headerColor, accounts, groups, total, totalLabel
}: {
  title: string
  headerColor: string
  accounts: BSAccount[]
  groups: { label: string; from: number; to: number }[]
  total: string | number
  totalLabel: string
}) {
  const grouped = groupAccounts(accounts, groups)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

  const toggle = (label: string) =>
    setCollapsed(prev => ({ ...prev, [label]: !prev[label] }))

  return (
    <div className="card overflow-hidden">
      <div className={`px-5 py-3 border-b ${headerColor}`}>
        <p className="text-xs font-bold uppercase tracking-widest">{title}</p>
      </div>
      {grouped.map(grp => {
        const visibleAccounts = grp.accounts.filter(a => parseFloat(String(a.balance)) !== 0)
        if (visibleAccounts.length === 0) return null
        const groupTotal = visibleAccounts.reduce((s, a) => s + parseFloat(String(a.balance)), 0)
        const isCollapsed = collapsed[grp.label]
        return (
          <div key={grp.label}>
            {/* Group header */}
            <button
              onClick={() => toggle(grp.label)}
              className="w-full flex items-center justify-between px-5 py-2 bg-surface-700/40 hover:bg-surface-700/60 transition-colors text-xs font-semibold text-slate-400 uppercase tracking-wider"
            >
              <span>{grp.label}</span>
              <div className="flex items-center gap-2">
                <span className="font-mono text-slate-300 normal-case text-xs">{formatCurrency(String(groupTotal))}</span>
                {isCollapsed ? <ChevronDown size={13} /> : <ChevronUp size={13} />}
              </div>
            </button>
            {!isCollapsed && (
              <div className="divide-y divide-surface-700">
                {visibleAccounts.map(a => (
                  <div key={a.code} className="flex items-center justify-between px-5 py-3">
                    <div>
                      <span className="text-xs text-slate-500 font-mono mr-2">{a.code}</span>
                      <span className="text-slate-300 text-sm">{a.name}</span>
                    </div>
                    <span className="text-white font-medium text-sm font-mono">{formatCurrency(String(a.balance))}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
      {grouped.every(g => g.accounts.filter(a => parseFloat(String(a.balance)) !== 0).length === 0) && (
        <div className="px-5 py-6 text-center text-slate-500 text-sm">No balances</div>
      )}
      <div className="px-5 py-3 border-t border-surface-700 bg-surface-800/50 flex justify-between">
        <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">{totalLabel}</span>
        <span className="text-white font-bold font-mono">{formatCurrency(String(total))}</span>
      </div>
    </div>
  )
}
