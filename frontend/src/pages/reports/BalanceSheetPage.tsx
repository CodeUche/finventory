import { useEffect, useState } from 'react'
import { Scale, Loader2, RefreshCw, CheckCircle, AlertTriangle } from 'lucide-react'
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

export default function BalanceSheetPage() {
  const [data, setData] = useState<BalanceSheetData | null>(null)
  const [loading, setLoading] = useState(true)
  const [noAccounts, setNoAccounts] = useState(false)
  const [seeding, setSeeding] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const { data: d } = await accountingApi.balanceSheet()
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

  useEffect(() => { load() }, [])

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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Balance Sheet</h1>
          <p className="text-slate-400 text-sm mt-0.5">Statement of financial position</p>
        </div>
        <button onClick={load} className="btn-ghost flex items-center gap-2 text-sm">
          <RefreshCw size={15} /> Refresh
        </button>
      </div>

      {loading ? (
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
              total={data.total_assets}
              totalLabel="TOTAL ASSETS"
            />
            {/* Liabilities */}
            <BSSection
              title="LIABILITIES"
              headerColor="text-red-400 border-red-500/30 bg-red-500/10"
              accounts={data.liabilities}
              total={data.total_liabilities}
              totalLabel="TOTAL LIABILITIES"
            />
            {/* Equity */}
            <BSSection
              title="EQUITY"
              headerColor="text-blue-400 border-blue-500/30 bg-blue-500/10"
              accounts={data.equity}
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
  title, headerColor, accounts, total, totalLabel
}: {
  title: string
  headerColor: string
  accounts: BSAccount[]
  total: string | number
  totalLabel: string
}) {
  return (
    <div className="card overflow-hidden">
      <div className={`px-5 py-3 border-b ${headerColor}`}>
        <p className="text-xs font-bold uppercase tracking-widest">{title}</p>
      </div>
      <div className="divide-y divide-surface-700">
        {accounts.filter((a) => parseFloat(String(a.balance)) !== 0).map((a) => (
          <div key={a.code} className="flex items-center justify-between px-5 py-3">
            <div>
              <span className="text-xs text-slate-500 font-mono mr-2">{a.code}</span>
              <span className="text-slate-300 text-sm">{a.name}</span>
            </div>
            <span className="text-white font-medium text-sm font-mono">{formatCurrency(String(a.balance))}</span>
          </div>
        ))}
        {accounts.filter((a) => parseFloat(String(a.balance)) !== 0).length === 0 && (
          <div className="px-5 py-6 text-center text-slate-500 text-sm">No balances</div>
        )}
      </div>
      <div className="px-5 py-3 border-t border-surface-700 bg-surface-800/50 flex justify-between">
        <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">{totalLabel}</span>
        <span className="text-white font-bold font-mono">{formatCurrency(String(total))}</span>
      </div>
    </div>
  )
}
