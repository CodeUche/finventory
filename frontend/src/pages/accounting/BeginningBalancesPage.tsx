import { useEffect, useState, useCallback } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Scale, RefreshCw, Loader2, AlertTriangle, CheckCircle2, Users, Truck, Package, BookOpen } from 'lucide-react'
import toast from 'react-hot-toast'
import { accountingApi } from '@/services/api'
import { formatCurrency } from '@/lib/utils'
import type { Account } from '@/types'
import { OpeningBalancesModal } from './ChartOfAccountsPage'

interface SuspenseSource { source_type: string; balance: number }
interface BeginningBalancesSummary {
  suspense: { balance: number; by_source: SuspenseSource[]; is_zero: boolean }
  accounts_with_opening: number
  opening_total: number
  controls: { accounts_receivable: number; accounts_payable: number; inventory: number }
  has_takeon: boolean
  balanced: boolean
}

const SOURCE_LABELS: Record<string, string> = {
  opening_balance: 'Opening balances (take-on)',
  sale: 'Sales', bill: 'Bills', expense: 'Expenses', payroll: 'Payroll',
  '(manual)': 'Manual journals',
}

export default function BeginningBalancesPage() {
  const [summary, setSummary] = useState<BeginningBalancesSummary | null>(null)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [sumRes, acctRes] = await Promise.all([
        accountingApi.beginningBalancesSummary(),
        accountingApi.accounts(),
      ])
      setSummary(sumRes.data)
      setAccounts((acctRes.data as { results?: Account[] }).results ?? acctRes.data)
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Failed to load beginning balances')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])
  useDataRefresh(load)

  const suspense = summary?.suspense
  const balanced = summary?.balanced

  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Scale size={20} /> Beginning Balances
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Enter your opening balances when migrating into Audity. Every take-on posts a
            balanced journal; any difference plugs to Take-On Suspense until you clear it.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={load} className="btn-ghost" title="Refresh">
            <RefreshCw size={16} />
          </button>
          <button onClick={() => setShowModal(true)} className="btn-primary flex items-center gap-2">
            <BookOpen size={16} /> Enter / Edit Opening Balances
          </button>
        </div>
      </div>

      {loading || !summary ? (
        <div className="flex items-center justify-center py-20 text-slate-400">
          <Loader2 size={22} className="animate-spin" />
        </div>
      ) : (
        <>
          {/* Suspense banner — the #1 onboarding error is a non-zero suspense */}
          {balanced ? (
            <div className="rounded-xl border border-green-700/50 bg-green-900/20 px-4 py-3 mb-5 flex items-start gap-3">
              <CheckCircle2 size={20} className="text-green-400 mt-0.5 shrink-0" />
              <div>
                <div className="text-sm font-semibold text-green-300">Take-on balanced</div>
                <div className="text-xs text-green-400/80">
                  Take-On Suspense (3900) is zero — your opening balances are complete and balanced.
                </div>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-red-700/50 bg-red-900/20 px-4 py-3 mb-5 flex items-start gap-3">
              <AlertTriangle size={20} className="text-red-400 mt-0.5 shrink-0" />
              <div className="flex-1">
                <div className="text-sm font-semibold text-red-300">
                  Take-On Suspense is not zero: {formatCurrency(Math.abs(suspense?.balance ?? 0))}
                </div>
                <div className="text-xs text-red-400/80 mb-2">
                  A non-zero suspense means your opening balances are incomplete or don&apos;t balance.
                  Finish entering them (and reclassify the plug to real equity) before go-live.
                </div>
                {(suspense?.by_source?.length ?? 0) > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {suspense!.by_source.map((s) => (
                      <span key={s.source_type} className="text-[11px] px-2 py-1 rounded bg-red-950/50 border border-red-800/40 text-red-200">
                        {SOURCE_LABELS[s.source_type] ?? s.source_type}: {formatCurrency(s.balance)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Status tiles */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
            <Tile icon={<BookOpen size={16} />} label="Accounts with opening balances"
              value={String(summary.accounts_with_opening)}
              sub={summary.opening_total ? formatCurrency(summary.opening_total) : undefined} />
            <Tile icon={<Users size={16} />} label="Accounts Receivable (control)"
              value={formatCurrency(summary.controls.accounts_receivable)} />
            <Tile icon={<Truck size={16} />} label="Accounts Payable (control)"
              value={formatCurrency(summary.controls.accounts_payable)} />
            <Tile icon={<Package size={16} />} label="Inventory (control)"
              value={formatCurrency(summary.controls.inventory)} />
          </div>

          <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 px-4 py-3 text-xs text-slate-400">
            <p className="mb-1">
              <strong className="text-slate-300">How take-on works.</strong> Use{' '}
              <em>Enter / Edit Opening Balances</em> to record GL account balances and sub-ledger
              detail (customers → AR, suppliers → AP, items → Inventory). Sub-ledger totals must
              equal their control-account balances above.
            </p>
            <p>
              {summary.has_takeon
                ? 'A take-on has been posted. Re-running for the same date safely replaces the prior take-on.'
                : 'No take-on has been posted yet.'}
            </p>
          </div>
        </>
      )}

      {showModal && (
        <OpeningBalancesModal
          accounts={accounts}
          onClose={() => setShowModal(false)}
          onDone={() => { setShowModal(false); load() }}
        />
      )}
    </div>
  )
}

function Tile({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 px-4 py-3">
      <div className="flex items-center gap-2 text-slate-400 text-[11px] mb-1">{icon}<span>{label}</span></div>
      <div className="text-lg font-bold text-white">{value}</div>
      {sub && <div className="text-[11px] text-slate-500 mt-0.5">{sub}</div>}
    </div>
  )
}
