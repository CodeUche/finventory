import { useEffect, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Scale, Loader2, RefreshCw, CheckCircle, AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react'
import toast from 'react-hot-toast'
import { accountingApi } from '@/services/api'
import { formatCurrency } from '@/lib/utils'

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
  { label: 'Current Assets', from: 1000, to: 1299 },
  { label: 'Fixed Assets', from: 1300, to: 1599 },
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

  const totalAssets = parseFloat(String(data?.total_assets ?? 0))
  const totalLiabEquity = parseFloat(String(data?.total_liabilities ?? 0)) + parseFloat(String(data?.total_equity ?? 0))
  const isBalanced = data ? Math.abs(totalAssets - totalLiabEquity) < 0.01 : false

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
          <button onClick={load} className="btn-ghost flex items-center gap-2 text-sm">
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
            <a href="/accounting/coa" className="btn-ghost">Manage Accounts</a>
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
