import { useEffect, useRef, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import {
  CheckSquare, Square, RefreshCw, CheckCircle2, Upload, FileText,
  Sparkles, Zap, ChevronDown, ChevronRight, AlertTriangle, XCircle, Check, X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { accountingApi, bypassNextGets } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import DateInput from '@/components/DateInput'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Account { id: string; code: string; name: string }

interface ReconLine {
  id: string
  description: string
  amount: string
  is_cleared: boolean
  reference: string
  transaction_date: string
}

interface Reconciliation {
  id: string
  account: string
  account_name?: string
  period_start: string
  period_end: string
  statement_closing_balance: string
  book_balance: string
  is_reconciled: boolean
  lines: ReconLine[]
  ai_matches: AIMatch[]
}

interface AIMatch {
  id: string
  bank_line: string
  book_line: string | null
  confidence: number
  match_type: 'exact' | 'fuzzy' | 'uncertain'
  status: 'proposed' | 'confirmed' | 'rejected'
  ai_reasoning: string
  ai_advice: string
  bank_line_description: string
  bank_line_date: string
  bank_line_amount: string
  book_line_description: string | null
  book_line_date: string | null
  book_line_debit: string | null
  book_line_credit: string | null
  book_line_reference: string | null
}

interface UnmatchedBook {
  book_line_id: string
  advice: string
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const today = new Date().toISOString().split('T')[0]
const firstOfMonth = new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().split('T')[0]

function confidenceBadge(c: number) {
  if (c >= 0.9) return <span className="badge-green text-xs">High Confidence</span>
  if (c >= 0.7) return <span className="badge-yellow text-xs">Medium</span>
  return <span className="badge-red text-xs">Low</span>
}

function matchTypeBadge(t: string) {
  const labels: Record<string, string> = { exact: 'Exact', fuzzy: 'Fuzzy', uncertain: 'Uncertain' }
  return <span className="text-xs text-slate-400">{labels[t] ?? t}</span>
}

// ─── Main Component ────────────────────────────────────────────────────────────

export default function BankReconciliationPage() {
  // ── Shared state ──
  const [accounts, setAccounts] = useState<Account[]>([])
  const [reconciliations, setReconciliations] = useState<Reconciliation[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'ai' | 'manual'>('ai')

  // ── Create form ──
  const [selectedAccountId, setSelectedAccountId] = useState('')
  const [periodStart, setPeriodStart] = useState(firstOfMonth)
  const [periodEnd, setPeriodEnd] = useState(today)
  const [statementBalance, setStatementBalance] = useState('')
  const [creating, setCreating] = useState(false)

  // ── Active reconciliation ──
  const [activeRecon, setActiveRecon] = useState<Reconciliation | null>(null)
  const [importing, setImporting] = useState(false)
  const csvInputRef = useRef<HTMLInputElement>(null)

  // ── AI tab state ──
  const [aiMatches, setAiMatches] = useState<AIMatch[]>([])
  const [unmatchedBook, setUnmatchedBook] = useState<UnmatchedBook[]>([])
  const [aiRunning, setAiRunning] = useState(false)
  const [autoRunning, setAutoRunning] = useState(false)
  const [aiRan, setAiRan] = useState(false)
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    matched: true,
    uncertain: true,
    unmatched: true,
  })
  const [confirming, setConfirming] = useState<Record<string, boolean>>({})

  // ── Manual tab state ──
  const [clearedIds, setClearedIds] = useState<Set<string>>(new Set())
  const [reconciling, setReconciling] = useState(false)

  // ── GL posting ──
  const [postingGL, setPostingGL] = useState(false)

  // ─── Data loading ──────────────────────────────────────────────────────────

  const load = async () => {
    setLoading(true)
    try {
      const [acRes, recRes] = await Promise.all([
        accountingApi.accounts(),
        accountingApi.reconciliations(),
      ])
      const allAccounts: Account[] = acRes.data.results ?? acRes.data
      setAccounts(allAccounts.filter((a) => a.code.startsWith('1')))
      const recs: Reconciliation[] = recRes.data.results ?? recRes.data
      setReconciliations(recs)
    } catch {
      toast.error('Failed to load reconciliation data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])
  useDataRefresh(load)

  // ─── Create reconciliation ─────────────────────────────────────────────────

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
      const recon = data as Reconciliation
      setActiveRecon(recon)
      setClearedIds(new Set(recon.lines.filter((l) => l.is_cleared).map((l) => l.id)))
      setAiMatches(recon.ai_matches ?? [])
      setAiRan(false)
      load()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { error?: unknown } } }
      const msg = e?.response?.data?.error ?? 'Failed to create reconciliation'
      toast.error(typeof msg === 'string' ? msg : 'Failed to create reconciliation')
    } finally {
      setCreating(false)
    }
  }

  // ─── CSV Import ────────────────────────────────────────────────────────────

  const handleImportCSV = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !activeRecon) return
    setImporting(true)
    try {
      const { data } = await accountingApi.importStatement(activeRecon.id, file)
      toast.success(`Imported ${data.lines_created} transaction${data.lines_created !== 1 ? 's' : ''}`)
      if (data.errors?.length) toast(`${data.errors.length} rows skipped`, { icon: '⚠️' })
      const recRes = await accountingApi.reconciliations()
      const recs: Reconciliation[] = recRes.data.results ?? recRes.data
      const updated = recs.find((r) => r.id === activeRecon.id)
      if (updated) {
        setActiveRecon(updated)
        setClearedIds(new Set(updated.lines.filter((l) => l.is_cleared).map((l) => l.id)))
        setAiMatches(updated.ai_matches ?? [])
      }
    } catch (err: unknown) {
      const e = err as { response?: { data?: { error?: unknown } } }
      const msg = e?.response?.data?.error ?? 'Import failed'
      toast.error(typeof msg === 'string' ? msg : 'Import failed')
    } finally {
      setImporting(false)
      if (csvInputRef.current) csvInputRef.current.value = ''
    }
  }

  // ─── Auto-Match (deterministic, instant, offline) ───────────────────────────

  const handleAutoMatch = async () => {
    if (!activeRecon) return
    setAutoRunning(true)
    try {
      const { data } = await accountingApi.autoMatch(activeRecon.id)
      setAiMatches(data.matches ?? [])
      setAiRan(true)
      const s = data.summary ?? {}
      toast.success(
        `Auto-matched ${s.matched ?? 0} for review, ${s.unmatched_bank ?? 0} unmatched — confirm to post`,
      )
    } catch (err: unknown) {
      const e = err as { response?: { data?: { error?: unknown } } }
      const apiErr = e?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Auto-match failed')
    } finally {
      setAutoRunning(false)
    }
  }

  // ─── AI Reconcile (assist — only the lines auto-match couldn't resolve) ──────

  const handleAiReconcile = async () => {
    if (!activeRecon) return
    setAiRunning(true)
    try {
      const { data } = await accountingApi.aiReconcile(activeRecon.id)
      const matches: AIMatch[] = data.matches ?? []
      setAiMatches(matches)
      setUnmatchedBook(data.unmatched_book ?? [])
      setAiRan(true)
      const s = data.summary ?? {}
      toast.success(`AI found ${matches.length} match${matches.length !== 1 ? 'es' : ''} from ${s.bank_lines_total ?? '?'} bank lines`)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { error?: unknown } } }
      const apiErr = e?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (typeof apiErr === 'object' && apiErr !== null && 'message' in apiErr ? (apiErr as { message: string }).message : 'AI reconciliation failed')
      toast.error(msg)
    } finally {
      setAiRunning(false)
    }
  }

  // ─── Post confirmed GL entries ────────────────────────────────────────────

  const handlePostConfirmedGL = async () => {
    if (!activeRecon) return
    setPostingGL(true)
    try {
      const { data } = await accountingApi.postConfirmedGL(activeRecon.id)
      toast.success(`${data.posted} GL entr${data.posted !== 1 ? 'ies' : 'y'} posted`)
      if (data.errors?.length) toast.error(`${data.errors.length} entries failed — check GL Health`)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { error?: unknown } } }
      const apiErr = e?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : 'Failed to post GL entries'
      toast.error(msg)
    } finally {
      setPostingGL(false)
    }
  }

  // ─── Confirm / Reject match ────────────────────────────────────────────────

  const handleMatchAction = async (matchId: string, action: 'confirm' | 'reject') => {
    if (!activeRecon) return
    setConfirming((prev) => ({ ...prev, [matchId]: true }))
    try {
      const { data } = await accountingApi.confirmMatch(activeRecon.id, { match_id: matchId, action })
      const updated = data as AIMatch
      setAiMatches((prev) => prev.map((m) => (m.id === matchId ? updated : m)))
      toast.success(action === 'confirm' ? 'Match confirmed' : 'Match rejected')
    } catch (err: unknown) {
      const e = err as { response?: { data?: { error?: unknown } } }
      const msg = e?.response?.data?.error ?? 'Action failed'
      toast.error(typeof msg === 'string' ? msg : 'Action failed')
    } finally {
      setConfirming((prev) => ({ ...prev, [matchId]: false }))
    }
  }

  // ─── Manual reconcile ──────────────────────────────────────────────────────

  const toggleLine = (lineId: string) => {
    setClearedIds((prev) => {
      const next = new Set(prev)
      if (next.has(lineId)) next.delete(lineId)
      else next.add(lineId)
      return next
    })
  }

  const handleManualReconcile = async () => {
    if (!activeRecon) return
    setReconciling(true)
    try {
      await Promise.all(
        activeRecon.lines.map((line) =>
          accountingApi.updateReconLine(activeRecon.id, { line_id: line.id, is_cleared: clearedIds.has(line.id) })
        )
      )
      await accountingApi.markReconciled(activeRecon.id)
      toast.success('Reconciliation completed!')
      setActiveRecon(null)
      load()
    } catch (err: unknown) {
      const e = err as { response?: { data?: { error?: unknown } } }
      const msg = e?.response?.data?.error ?? 'Failed to reconcile'
      toast.error(typeof msg === 'string' ? msg : 'Failed to reconcile')
    } finally {
      setReconciling(false)
    }
  }

  // ─── Derived values ────────────────────────────────────────────────────────

  const toggleSection = (key: string) =>
    setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }))

  const activeProposed = aiMatches.filter((m) => m.status === 'proposed' && m.book_line !== null)
  const exactMatches = activeProposed.filter((m) => m.match_type === 'exact' && m.confidence >= 0.85)
  const uncertainMatches = activeProposed.filter(
    (m) => m.match_type !== 'exact' || m.confidence < 0.85
  )
  const unmatchedBank = aiMatches.filter((m) => m.book_line === null && m.status !== 'rejected')
  const confirmedMatches = aiMatches.filter((m) => m.status === 'confirmed')

  const statementBal = parseFloat(activeRecon?.statement_closing_balance ?? '0')
  const confirmedTotal = confirmedMatches.reduce((s, m) => s + Math.abs(parseFloat(m.bank_line_amount)), 0)
  const aiDifference = statementBal - confirmedTotal
  const aiCanReconcile = Math.abs(aiDifference) < 0.01

  // Manual tab calcs
  const clearedTotal = activeRecon
    ? activeRecon.lines.filter((l) => clearedIds.has(l.id)).reduce((s, l) => s + parseFloat(l.amount), 0)
    : 0
  const manualDiff = statementBal - clearedTotal
  const manualCanReconcile = Math.abs(manualDiff) < 0.01

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Bank Reconciliation</h1>
        <p className="text-slate-400 text-sm">Match your book entries to your bank statement</p>
      </div>

      {/* ── Create form (shown when no active recon) ── */}
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

      {/* ── Active reconciliation workspace ── */}
      {activeRecon && (
        <div className="space-y-4">
          {/* Tab switcher + import + cancel */}
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex gap-1 bg-surface-800 rounded-lg p-1">
              <button
                className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${activeTab === 'ai' ? 'bg-brand-600 text-white' : 'text-slate-400 hover:text-white'}`}
                onClick={() => setActiveTab('ai')}
              >
                <Sparkles size={13} className="inline mr-1.5 -mt-0.5" />
                AI Reconcile
              </button>
              <button
                className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${activeTab === 'manual' ? 'bg-brand-600 text-white' : 'text-slate-400 hover:text-white'}`}
                onClick={() => setActiveTab('manual')}
              >
                Manual
              </button>
            </div>

            <div className="flex gap-2 items-center">
              <span className="text-sm text-slate-400">
                {activeRecon.account_name} &middot; {formatDate(activeRecon.period_start)} – {formatDate(activeRecon.period_end)}
              </span>
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
                onClick={() => { setActiveRecon(null); setAiMatches([]); setAiRan(false) }}
                className="btn-ghost text-sm px-3"
              >
                Close
              </button>
            </div>
          </div>

          {/* ══════════════════════════ AI TAB ══════════════════════════ */}
          {activeTab === 'ai' && (
            <div className="space-y-4">
              {/* Statement import prompt */}
              {activeRecon.lines.length === 0 ? (
                <div className="card p-8 text-center">
                  <FileText size={36} className="mx-auto mb-3 text-slate-600" />
                  <p className="text-white font-medium mb-1">No bank statement imported yet</p>
                  <p className="text-sm text-slate-400 mb-4">
                    Click <strong>Import CSV</strong> above to upload your bank statement before running AI matching.
                  </p>
                  <p className="text-xs text-slate-500">
                    Expected columns: <code className="bg-surface-700 px-1 rounded">date, description, debit, credit</code> or <code className="bg-surface-700 px-1 rounded">amount</code>
                  </p>
                </div>
              ) : (
                <>
                  {/* AI Match trigger card */}
                  <div className="card p-5 flex items-center justify-between gap-4">
                    <div>
                      <p className="text-white font-medium">
                        {activeRecon.lines.length} bank transaction{activeRecon.lines.length !== 1 ? 's' : ''} imported
                      </p>
                      <p className="text-sm text-slate-400">
                        {aiRan
                          ? `${aiMatches.length} match${aiMatches.length !== 1 ? 'es' : ''} found. Review below.`
                          : 'Auto-Match pairs lines instantly by exact amount + date (no waiting). Use AI Assist only for whatever’s left.'}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={handleAutoMatch}
                        disabled={autoRunning}
                        className="btn-primary flex items-center gap-2 disabled:opacity-50"
                        title="Deterministic exact-match — instant and offline"
                      >
                        <Zap size={15} />
                        {autoRunning ? 'Matching…' : 'Auto-Match'}
                      </button>
                      <button
                        onClick={handleAiReconcile}
                        disabled={aiRunning}
                        className="btn-ghost flex items-center gap-2 disabled:opacity-50"
                        title="AI assist for lines Auto-Match couldn’t resolve (needs a Groq key)"
                      >
                        <Sparkles size={15} />
                        {aiRunning ? 'Analyzing…' : 'AI Assist'}
                      </button>
                    </div>
                  </div>

                  {/* Post confirmed GL button */}
                  {aiRan && aiMatches.some((m) => m.status === 'confirmed') && (
                    <div className="card p-4 flex items-center justify-between gap-4">
                      <div>
                        <p className="text-white text-sm font-medium">
                          {aiMatches.filter((m) => m.status === 'confirmed').length} confirmed match{aiMatches.filter((m) => m.status === 'confirmed').length !== 1 ? 'es' : ''} ready to post
                        </p>
                        <p className="text-xs text-slate-400">Create journal entries for confirmed AI matches that have no existing GL entry</p>
                      </div>
                      <button
                        onClick={handlePostConfirmedGL}
                        disabled={postingGL}
                        className="btn-primary flex items-center gap-2 shrink-0 disabled:opacity-50"
                      >
                        <CheckSquare size={15} className={postingGL ? 'animate-pulse' : ''} />
                        {postingGL ? 'Posting…' : 'Post Confirmed GL'}
                      </button>
                    </div>
                  )}

                  {/* Results */}
                  {aiRan && (
                    <div className="space-y-3">

                      {/* ── Confirmed / High-confidence matches ── */}
                      <div className="card overflow-hidden">
                        <button
                          className="w-full px-5 py-3 flex items-center justify-between text-left hover:bg-surface-700/30"
                          onClick={() => toggleSection('matched')}
                        >
                          <span className="flex items-center gap-2 text-sm font-semibold text-emerald-400">
                            <CheckCircle2 size={16} />
                            Auto-Matched ({exactMatches.length})
                          </span>
                          {expandedSections.matched ? <ChevronDown size={16} className="text-slate-400" /> : <ChevronRight size={16} className="text-slate-400" />}
                        </button>
                        {expandedSections.matched && (
                          <div className="overflow-x-auto">
                            {exactMatches.length === 0 ? (
                              <p className="px-5 py-4 text-sm text-slate-400">No high-confidence matches found.</p>
                            ) : (
                              <table className="w-full text-sm">
                                <thead>
                                  <tr className="border-t border-surface-700 bg-surface-800/40">
                                    {['Bank Line', 'Amount', 'Date', 'Book Entry', 'Date', 'Confidence', 'Actions'].map((h) => (
                                      <th key={h} className="px-4 py-2 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider whitespace-nowrap">{h}</th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-surface-700">
                                  {exactMatches.map((m) => (
                                    <AIMatchRow key={m.id} match={m} confirming={confirming[m.id]} onAction={handleMatchAction} />
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </div>
                        )}
                      </div>

                      {/* ── Uncertain matches ── */}
                      <div className="card overflow-hidden">
                        <button
                          className="w-full px-5 py-3 flex items-center justify-between text-left hover:bg-surface-700/30"
                          onClick={() => toggleSection('uncertain')}
                        >
                          <span className="flex items-center gap-2 text-sm font-semibold text-amber-400">
                            <AlertTriangle size={16} />
                            Uncertain Matches ({uncertainMatches.length})
                          </span>
                          {expandedSections.uncertain ? <ChevronDown size={16} className="text-slate-400" /> : <ChevronRight size={16} className="text-slate-400" />}
                        </button>
                        {expandedSections.uncertain && (
                          <div className="overflow-x-auto">
                            {uncertainMatches.length === 0 ? (
                              <p className="px-5 py-4 text-sm text-slate-400">No uncertain matches.</p>
                            ) : (
                              <table className="w-full text-sm">
                                <thead>
                                  <tr className="border-t border-surface-700 bg-surface-800/40">
                                    {['Bank Line', 'Amount', 'Date', 'Possible Book Entry', 'Date', 'Type', 'Confidence', 'Reasoning', 'Actions'].map((h) => (
                                      <th key={h} className="px-4 py-2 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider whitespace-nowrap">{h}</th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-surface-700">
                                  {uncertainMatches.map((m) => (
                                    <AIMatchRow key={m.id} match={m} showReasoning confirming={confirming[m.id]} onAction={handleMatchAction} />
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </div>
                        )}
                      </div>

                      {/* ── Unmatched ── */}
                      <div className="card overflow-hidden">
                        <button
                          className="w-full px-5 py-3 flex items-center justify-between text-left hover:bg-surface-700/30"
                          onClick={() => toggleSection('unmatched')}
                        >
                          <span className="flex items-center gap-2 text-sm font-semibold text-red-400">
                            <XCircle size={16} />
                            Unmatched ({unmatchedBank.length + unmatchedBook.length})
                          </span>
                          {expandedSections.unmatched ? <ChevronDown size={16} className="text-slate-400" /> : <ChevronRight size={16} className="text-slate-400" />}
                        </button>
                        {expandedSections.unmatched && (
                          <div className="divide-y divide-surface-700">
                            {/* In bank but not in books */}
                            {unmatchedBank.length > 0 && (
                              <div>
                                <p className="px-5 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider bg-surface-800/40">
                                  In bank but not in books ({unmatchedBank.length})
                                </p>
                                {unmatchedBank.map((m) => (
                                  <div key={m.id} className="px-5 py-3 flex items-start gap-3">
                                    <div className="flex-1 min-w-0">
                                      <p className="text-sm text-white font-medium truncate">{m.bank_line_description}</p>
                                      <p className="text-xs text-slate-500">
                                        {formatDate(m.bank_line_date)} &middot; {formatCurrency(Math.abs(parseFloat(m.bank_line_amount)))}
                                      </p>
                                      {m.ai_advice && (
                                        <p className="text-xs text-amber-400 mt-1 flex items-start gap-1">
                                          <AlertTriangle size={11} className="shrink-0 mt-0.5" />
                                          {m.ai_advice}
                                        </p>
                                      )}
                                    </div>
                                    {m.status === 'proposed' && (
                                      <button
                                        onClick={() => handleMatchAction(m.id, 'reject')}
                                        disabled={confirming[m.id]}
                                        className="text-xs btn-ghost px-2 py-1 text-slate-400 hover:text-white shrink-0"
                                      >
                                        Mark Resolved
                                      </button>
                                    )}
                                    {m.status === 'rejected' && (
                                      <span className="badge-green text-xs shrink-0">Resolved</span>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}

                            {/* In books but not in bank */}
                            {unmatchedBook.length > 0 && (
                              <div>
                                <p className="px-5 py-2 text-xs font-semibold text-slate-400 uppercase tracking-wider bg-surface-800/40">
                                  In books but not in bank ({unmatchedBook.length})
                                </p>
                                {unmatchedBook.map((item, i) => (
                                  <div key={i} className="px-5 py-3">
                                    <p className="text-xs text-slate-500 font-mono">{item.book_line_id}</p>
                                    {item.advice && (
                                      <p className="text-xs text-amber-400 mt-1 flex items-start gap-1">
                                        <AlertTriangle size={11} className="shrink-0 mt-0.5" />
                                        {item.advice}
                                      </p>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}

                            {unmatchedBank.length === 0 && unmatchedBook.length === 0 && (
                              <p className="px-5 py-4 text-sm text-slate-400">All lines matched.</p>
                            )}
                          </div>
                        )}
                      </div>

                      {/* ── Summary card ── */}
                      <div className={`card p-5 border ${aiCanReconcile ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-surface-600'}`}>
                        <h3 className="text-sm font-semibold text-white mb-3">Reconciliation Summary</h3>
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm mb-4">
                          <div>
                            <p className="text-xs text-slate-400">Statement Balance</p>
                            <p className="text-white font-semibold">{formatCurrency(statementBal)}</p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-400">Bank lines total</p>
                            <p className="text-white font-semibold">{activeRecon.lines.length}</p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-400">Confirmed matches</p>
                            <p className="text-emerald-400 font-semibold">{confirmedMatches.length}</p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-400">Unresolved</p>
                            <p className={`font-semibold ${exactMatches.length + uncertainMatches.length + unmatchedBank.length > 0 ? 'text-amber-400' : 'text-emerald-400'}`}>
                              {exactMatches.length + uncertainMatches.length + unmatchedBank.length}
                            </p>
                          </div>
                        </div>
                        <button
                          onClick={handleManualReconcile}
                          disabled={!aiCanReconcile || reconciling}
                          className="btn-primary flex items-center gap-2 disabled:opacity-50"
                        >
                          <CheckCircle2 size={15} />
                          {reconciling ? 'Reconciling…' : 'Mark as Fully Reconciled'}
                        </button>
                        {!aiCanReconcile && (
                          <p className="text-xs text-slate-500 mt-2">
                            Confirm all matches and resolve unmatched items to enable reconciliation.
                          </p>
                        )}
                      </div>

                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* ══════════════════════════ MANUAL TAB ══════════════════════════ */}
          {activeTab === 'manual' && (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-4">
                <div className="card p-5">
                  <p className="text-xs text-slate-400">Statement Balance</p>
                  <p className="text-xl font-bold text-white mt-1">{formatCurrency(statementBal)}</p>
                </div>
                <div className="card p-5">
                  <p className="text-xs text-slate-400">Cleared Items Total</p>
                  <p className="text-xl font-bold text-brand-400 mt-1">{formatCurrency(clearedTotal)}</p>
                </div>
                <div className={`card p-5 border ${manualCanReconcile ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-red-500/30 bg-red-500/5'}`}>
                  <p className="text-xs text-slate-400">Difference</p>
                  <p className={`text-xl font-bold mt-1 ${manualCanReconcile ? 'text-emerald-400' : 'text-red-400'}`}>
                    {formatCurrency(Math.abs(manualDiff))}
                    {manualCanReconcile && <span className="text-sm font-normal ml-2">Balanced</span>}
                  </p>
                </div>
              </div>

              <div className="card p-0 overflow-hidden">
                <div className="px-5 py-4 border-b border-surface-700 flex items-center justify-between">
                  <h3 className="text-white font-semibold">
                    Transactions — {formatDate(activeRecon.period_start)} to {formatDate(activeRecon.period_end)}
                  </h3>
                  <button
                    onClick={handleManualReconcile}
                    disabled={reconciling || !manualCanReconcile}
                    className="btn-primary text-sm px-4 disabled:opacity-50 flex items-center gap-2"
                  >
                    <CheckCircle2 size={15} />
                    {reconciling ? 'Reconciling…' : 'Mark as Reconciled'}
                  </button>
                </div>
                <div className="divide-y divide-surface-700">
                  {activeRecon.lines.length === 0 ? (
                    <div className="px-5 py-10 text-center">
                      <FileText size={32} className="mx-auto mb-3 text-slate-600" />
                      <p className="text-sm text-slate-400 mb-1">No transactions yet</p>
                      <p className="text-xs text-slate-500">
                        Click <strong>Import CSV</strong> to upload your bank statement.
                      </p>
                    </div>
                  ) : (
                    activeRecon.lines.map((line) => {
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
                              {formatDate(line.transaction_date)}{line.reference ? ` · ${line.reference}` : ''}
                            </p>
                          </div>
                          <span className={`font-semibold text-sm ${parseFloat(line.amount) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {formatCurrency(Math.abs(parseFloat(line.amount)))}
                          </span>
                        </div>
                      )
                    })
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Past reconciliations ── */}
      {reconciliations.length > 0 && (
        <div className="card p-0 overflow-hidden">
          <div className="px-5 py-4 border-b border-surface-700 flex items-center justify-between">
            <h3 className="text-white font-semibold">Past Reconciliations</h3>
            <button onClick={() => { bypassNextGets(); load() }} className="btn-ghost p-2"><RefreshCw size={15} /></button>
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
              {loading
                ? Array.from({ length: 3 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 5 }).map((_, j) => (
                        <td key={j} className="px-5 py-3"><div className="h-4 bg-surface-700 rounded animate-pulse w-20" /></td>
                      ))}
                    </tr>
                  ))
                : reconciliations.map((r) => (
                    <tr
                      key={r.id}
                      className="table-row cursor-pointer"
                      onClick={() => {
                        setActiveRecon(r)
                        setClearedIds(new Set(r.lines.filter((l) => l.is_cleared).map((l) => l.id)))
                        setAiMatches(r.ai_matches ?? [])
                        setAiRan((r.ai_matches ?? []).length > 0)
                      }}
                    >
                      <td className="px-5 py-3 text-white font-medium">{r.account_name ?? r.account}</td>
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

// ─── AI Match Row sub-component ───────────────────────────────────────────────

interface AIMatchRowProps {
  match: AIMatch
  showReasoning?: boolean
  confirming?: boolean
  onAction: (matchId: string, action: 'confirm' | 'reject') => void
}

function AIMatchRow({ match, showReasoning, confirming, onAction }: AIMatchRowProps) {
  const isConfirmed = match.status === 'confirmed'
  const isRejected = match.status === 'rejected'
  const disabled = isConfirmed || isRejected || confirming

  return (
    <tr className={`${isConfirmed ? 'bg-emerald-500/5' : isRejected ? 'bg-red-500/5 opacity-60' : ''}`}>
      <td className="px-4 py-3 text-white max-w-[200px]">
        <p className="truncate text-sm">{match.bank_line_description}</p>
      </td>
      <td className="px-4 py-3 whitespace-nowrap">
        <span className={`text-sm font-semibold ${parseFloat(match.bank_line_amount) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
          {formatCurrency(Math.abs(parseFloat(match.bank_line_amount)))}
        </span>
      </td>
      <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">
        {match.bank_line_date ? formatDate(match.bank_line_date) : '—'}
      </td>
      <td className="px-4 py-3 text-white max-w-[200px]">
        <p className="truncate text-sm">{match.book_line_description ?? '—'}</p>
        {match.book_line_reference && (
          <p className="text-xs text-slate-500">{match.book_line_reference}</p>
        )}
      </td>
      <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">
        {match.book_line_date ? formatDate(match.book_line_date) : '—'}
      </td>
      {showReasoning ? (
        <>
          <td className="px-4 py-3">{matchTypeBadge(match.match_type)}</td>
          <td className="px-4 py-3">{confidenceBadge(match.confidence)}</td>
          <td className="px-4 py-3 text-xs text-slate-400 max-w-[200px]">
            <p className="line-clamp-2">{match.ai_reasoning}</p>
          </td>
        </>
      ) : (
        <td className="px-4 py-3">{confidenceBadge(match.confidence)}</td>
      )}
      <td className="px-4 py-3">
        {isConfirmed ? (
          <span className="badge-green text-xs">Confirmed</span>
        ) : isRejected ? (
          <span className="badge-red text-xs">Rejected</span>
        ) : (
          <div className="flex gap-1.5">
            <button
              onClick={() => onAction(match.id, 'confirm')}
              disabled={disabled}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-emerald-600/20 text-emerald-400 hover:bg-emerald-600/40 disabled:opacity-50 transition-colors"
            >
              <Check size={11} />
              Confirm
            </button>
            <button
              onClick={() => onAction(match.id, 'reject')}
              disabled={disabled}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-red-500/20 text-red-400 hover:bg-red-500/40 disabled:opacity-50 transition-colors"
            >
              <X size={11} />
              Reject
            </button>
          </div>
        )}
      </td>
    </tr>
  )
}
