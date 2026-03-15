import { useEffect, useRef, useState } from 'react'
import { CheckSquare, Square, RefreshCw, CheckCircle2, Upload, FileText } from 'lucide-react'
import toast from 'react-hot-toast'
import { accountingApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import DateInput from '@/components/DateInput'

interface Account { id: string; code: string; name: string }
interface Reconciliation {
  id: string
  account: string
  account_name?: string
  period_start: string
  period_end: string
  statement_closing_balance: string
  book_balance: string
  is_reconciled: boolean
  lines: { id: string; description: string; amount: string; is_cleared: boolean; reference: string; transaction_date: string }[]
}

const today = new Date().toISOString().split('T')[0]
const firstOfMonth = new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0]

export default function BankReconciliationPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [reconciliations, setReconciliations] = useState<Reconciliation[]>([])
  const [loading, setLoading] = useState(true)

  const [selectedAccountId, setSelectedAccountId] = useState('')
  const [periodStart, setPeriodStart] = useState(firstOfMonth)
  const [periodEnd, setPeriodEnd] = useState(today)
  const [statementBalance, setStatementBalance] = useState('')
  const [creating, setCreating] = useState(false)

  const [activeRecon, setActiveRecon] = useState<Reconciliation | null>(null)
  const [clearedIds, setClearedIds] = useState<Set<string>>(new Set())
  const [reconciling, setReconciling] = useState(false)
  const [importing, setImporting] = useState(false)
  const csvInputRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [acRes, recRes] = await Promise.all([
        accountingApi.accounts(),
        accountingApi.reconciliations(),
      ])
      const allAccounts: Account[] = acRes.data.results ?? acRes.data
      // Only show bank/cash accounts (codes starting with 1)
      setAccounts(allAccounts.filter((a) => a.code.startsWith('1')))
      setReconciliations(recRes.data.results ?? recRes.data)
    } catch { toast.error('Failed to load reconciliation data') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const handleCreate = async () => {
    if (!selectedAccountId) { toast.error('Select an account'); return }
    if (!statementBalance) { toast.error('Enter statement closing balance'); return }
    setCreating(true)
    try {
      const { data } = await accountingApi.createReconciliation({
        account: selectedAccountId,
        period_start: periodStart,
        period_end: periodEnd,
        statement_closing_balance: parseFloat(statementBalance.replace(/,/g, '')),
      })
      toast.success('Reconciliation started')
      setActiveRecon(data)
      setClearedIds(new Set(data.lines.filter((l: any) => l.is_cleared).map((l: any) => l.id)))
      load()
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Failed to create reconciliation'
      toast.error(typeof msg === 'string' ? msg : 'Failed to create reconciliation')
    } finally { setCreating(false) }
  }

  const toggleLine = (lineId: string) => {
    setClearedIds((prev) => {
      const next = new Set(prev)
      if (next.has(lineId)) next.delete(lineId)
      else next.add(lineId)
      return next
    })
  }

  const handleReconcile = async () => {
    if (!activeRecon) return
    setReconciling(true)
    try {
      // Update cleared status for each line
      await Promise.all(
        activeRecon.lines.map((line) =>
          accountingApi.updateReconLine(activeRecon.id, { line_id: line.id, is_cleared: clearedIds.has(line.id) })
        )
      )
      await accountingApi.markReconciled(activeRecon.id)
      toast.success('Reconciliation completed!')
      setActiveRecon(null)
      load()
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Failed to reconcile'
      toast.error(typeof msg === 'string' ? msg : 'Failed to reconcile')
    } finally { setReconciling(false) }
  }

  const handleImportCSV = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !activeRecon) return
    setImporting(true)
    try {
      const { data } = await accountingApi.importStatement(activeRecon.id, file)
      toast.success(`Imported ${data.lines_created} transaction${data.lines_created !== 1 ? 's' : ''}`)
      if (data.errors?.length) toast(`${data.errors.length} rows skipped`, { icon: '⚠️' })
      // Reload reconciliation to get new lines
      const recRes = await accountingApi.reconciliations()
      const recs: Reconciliation[] = recRes.data.results ?? recRes.data
      const updated = recs.find((r) => r.id === activeRecon.id)
      if (updated) {
        setActiveRecon(updated)
        setClearedIds(new Set(updated.lines.filter((l) => l.is_cleared).map((l) => l.id)))
      }
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Import failed'
      toast.error(typeof msg === 'string' ? msg : 'Import failed')
    } finally {
      setImporting(false)
      if (csvInputRef.current) csvInputRef.current.value = ''
    }
  }

  const clearedTotal = activeRecon
    ? activeRecon.lines
        .filter((l) => clearedIds.has(l.id))
        .reduce((s, l) => s + parseFloat(l.amount), 0)
    : 0

  const statementBal = parseFloat(activeRecon?.statement_closing_balance ?? '0')
  const difference = statementBal - clearedTotal
  const canReconcile = Math.abs(difference) < 0.01

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Bank Reconciliation</h1>
        <p className="text-slate-400 text-sm">Match your book entries to your bank statement</p>
      </div>

      {/* Create new reconciliation form */}
      {!activeRecon && (
        <div className="card p-6">
          <h2 className="text-base font-semibold text-white mb-4">Start New Reconciliation</h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Account *</label>
              <select
                className="input"
                value={selectedAccountId}
                onChange={(e) => setSelectedAccountId(e.target.value)}
              >
                <option value="">— Select Account —</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.code} — {a.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Period Start</label>
              <DateInput value={periodStart} onChange={setPeriodStart} />
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Period End</label>
              <DateInput value={periodEnd} onChange={setPeriodEnd} />
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Statement Closing Balance *</label>
              <input
                type="text"
                inputMode="decimal"
                className="input"
                placeholder="e.g. 250,000"
                value={statementBalance}
                onChange={(e) => setStatementBalance(e.target.value)}
              />
            </div>
          </div>
          <button
            onClick={handleCreate}
            disabled={creating}
            className="btn-primary mt-4 disabled:opacity-50"
          >
            {creating ? 'Starting…' : 'Start Reconciliation'}
          </button>
        </div>
      )}

      {/* Active reconciliation workspace */}
      {activeRecon && (
        <div className="space-y-4">
          {/* Balance summary */}
          <div className="grid grid-cols-3 gap-4">
            <div className="card p-5">
              <p className="text-xs text-slate-400">Statement Balance</p>
              <p className="text-xl font-bold text-white mt-1">{formatCurrency(statementBal)}</p>
            </div>
            <div className="card p-5">
              <p className="text-xs text-slate-400">Cleared Items Total</p>
              <p className="text-xl font-bold text-brand-400 mt-1">{formatCurrency(clearedTotal)}</p>
            </div>
            <div className={`card p-5 border ${canReconcile ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-red-500/30 bg-red-500/5'}`}>
              <p className="text-xs text-slate-400">Difference</p>
              <p className={`text-xl font-bold mt-1 ${canReconcile ? 'text-emerald-400' : 'text-red-400'}`}>
                {formatCurrency(Math.abs(difference))}
                {canReconcile && <span className="text-sm font-normal ml-2">✓ Balanced</span>}
              </p>
            </div>
          </div>

          {/* Transactions to clear */}
          <div className="card p-0 overflow-hidden">
            <div className="px-5 py-4 border-b border-surface-700 flex items-center justify-between">
              <h3 className="text-white font-semibold">
                Transactions — {activeRecon.period_start} to {activeRecon.period_end}
              </h3>
              <div className="flex gap-2">
                <input ref={csvInputRef} type="file" accept=".csv" className="hidden" onChange={handleImportCSV} />
                <button
                  onClick={() => csvInputRef.current?.click()}
                  disabled={importing}
                  className="btn-ghost text-sm px-3 flex items-center gap-2 disabled:opacity-50"
                  title="Import bank statement CSV (columns: date, description, debit, credit)"
                >
                  <Upload size={14} />
                  {importing ? 'Importing…' : 'Import CSV'}
                </button>
                <button
                  onClick={() => setActiveRecon(null)}
                  className="btn-ghost text-sm px-3"
                >
                  Cancel
                </button>
                <button
                  onClick={handleReconcile}
                  disabled={reconciling || !canReconcile}
                  className="btn-primary text-sm px-4 disabled:opacity-50 flex items-center gap-2"
                >
                  <CheckCircle2 size={15} />
                  {reconciling ? 'Reconciling…' : 'Mark as Reconciled'}
                </button>
              </div>
            </div>
            <div className="divide-y divide-surface-700">
              {activeRecon.lines.length === 0 ? (
                <div className="px-5 py-10 text-center">
                  <FileText size={32} className="mx-auto mb-3 text-slate-600" />
                  <p className="text-sm text-slate-400 mb-1">No transactions yet</p>
                  <p className="text-xs text-slate-500">Click <strong>Import CSV</strong> to upload your bank statement.<br />Expected columns: <code className="bg-surface-700 px-1 rounded">date, description, debit, credit</code> (or <code className="bg-surface-700 px-1 rounded">amount</code>).</p>
                </div>
              ) : activeRecon.lines.map((line) => {
                const isCleared = clearedIds.has(line.id)
                return (
                  <div
                    key={line.id}
                    className={`flex items-center gap-4 px-5 py-3.5 cursor-pointer transition-colors ${isCleared ? 'bg-emerald-500/5' : 'hover:bg-surface-700/30'}`}
                    onClick={() => toggleLine(line.id)}
                  >
                    <div className={`shrink-0 ${isCleared ? 'text-emerald-400' : 'text-slate-600'}`}>
                      {isCleared ? <CheckSquare size={18} /> : <Square size={18} />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className={`text-sm font-medium truncate ${isCleared ? 'text-white' : 'text-slate-300'}`}>
                        {line.description}
                      </p>
                      <p className="text-xs text-slate-500">
                        {formatDate(line.transaction_date)} {line.reference ? `· ${line.reference}` : ''}
                      </p>
                    </div>
                    <span className={`font-semibold text-sm ${parseFloat(line.amount) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {formatCurrency(Math.abs(parseFloat(line.amount)))}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {/* Past Reconciliations */}
      {reconciliations.length > 0 && (
        <div className="card p-0 overflow-hidden">
          <div className="px-5 py-4 border-b border-surface-700 flex items-center justify-between">
            <h3 className="text-white font-semibold">Past Reconciliations</h3>
            <button onClick={load} className="btn-ghost p-2"><RefreshCw size={15} /></button>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Account', 'Period', 'Statement Bal', 'Book Bal', 'Status'].map((h) => (
                  <th key={h} className="px-5 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-700">
              {loading ? (
                Array.from({ length: 3 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 5 }).map((_, j) => (
                      <td key={j} className="px-5 py-3"><div className="h-4 bg-surface-700 rounded animate-pulse w-20" /></td>
                    ))}
                  </tr>
                ))
              ) : reconciliations.map((r) => (
                <tr key={r.id} className="table-row">
                  <td className="px-5 py-3 text-white font-medium">{(r as any).account_name ?? r.account}</td>
                  <td className="px-5 py-3 text-slate-400">{formatDate(r.period_start)} – {formatDate(r.period_end)}</td>
                  <td className="px-5 py-3 text-white">{formatCurrency(parseFloat(r.statement_closing_balance))}</td>
                  <td className="px-5 py-3 text-slate-400">{formatCurrency(parseFloat(r.book_balance))}</td>
                  <td className="px-5 py-3">
                    {r.is_reconciled
                      ? <span className="badge-green">Reconciled</span>
                      : <span className="badge-yellow">In Progress</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
