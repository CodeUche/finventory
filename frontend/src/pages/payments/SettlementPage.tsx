/**
 * Card settlement — tie terminal payouts to the sales they belong to.
 *
 * Audity cannot drive a Moniepoint or OPay terminal (that needs a signed
 * partnership), so it reconciles instead: upload the day's export and each
 * payout is matched to its sale. Anything the matcher isn't certain about is
 * listed here for a person — it never guesses.
 */

import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle, Check, CreditCard, GitBranch, Loader2, RefreshCw, Upload, X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { settlementApi, bypassNextGets } from '@/services/api'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { confirmDialog } from '@/lib/dialog'
import { formatCurrency, formatDate } from '@/lib/utils'

interface Line {
  id: string
  provider_reference: string
  paid_at: string | null
  amount: string
  fee: string
  terminal_id: string
  card_last4: string
  narration: string
  status: 'unmatched' | 'matched' | 'other_income' | 'ignored'
  status_label: string
  payment: string | null
  invoice_number: string
  matched_automatically: boolean
  review_note: string
}

interface Candidate {
  id: string
  amount: string
  received_at: string
  method: string
  reference: string
  invoice_number: string
}

const BADGE: Record<Line['status'], string> = {
  unmatched: 'badge-yellow',
  matched: 'badge-green',
  other_income: 'badge-blue',
  ignored: 'badge-slate',
}

export default function SettlementPage() {
  const [lines, setLines] = useState<Line[]>([])
  const [summary, setSummary] = useState<{ needs_review: number; needs_review_total: string; matched: number } | null>(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [filter, setFilter] = useState<'unmatched' | 'all'>('unmatched')
  const [assigning, setAssigning] = useState<Line | null>(null)
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const fileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [l, s] = await Promise.all([
        settlementApi.lines({ page_size: 300 }),
        settlementApi.summary(),
      ])
      setLines(l.data.results ?? l.data)
      setSummary(s.data)
    } catch { toast.error('Could not load settlements') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useDataRefresh(load)

  const upload = async (file: File) => {
    setUploading(true)
    try {
      const csv = await file.text()
      const { data } = await settlementApi.upload(csv, file.name)
      toast.success(
        `${data.line_count} payout${data.line_count === 1 ? '' : 's'} imported — ` +
        `${data.matched} matched automatically`,
      )
      bypassNextGets(); load()
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Could not read that file')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const openAssign = async (line: Line) => {
    setAssigning(line)
    try {
      const { data } = await settlementApi.candidates()
      setCandidates(data.results)
    } catch { toast.error('Could not load card sales') }
  }

  const assign = async (paymentId: string) => {
    if (!assigning) return
    setBusyId(assigning.id)
    try {
      await settlementApi.assign(assigning.id, paymentId)
      toast.success('Payout matched')
      setAssigning(null)
      bypassNextGets(); load()
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Could not match that payout')
    } finally { setBusyId(null) }
  }

  const bookAsIncome = async (line: Line) => {
    const ok = await confirmDialog(
      `Record ${formatCurrency(line.amount)} as other income? Use this when the ` +
      `money was taken on the terminal without going through Audity.`,
    )
    if (!ok) return
    setBusyId(line.id)
    try {
      await settlementApi.otherIncome(line.id)
      toast.success('Recorded as other income')
      bypassNextGets(); load()
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Could not record that')
    } finally { setBusyId(null) }
  }

  const unmatch = async (line: Line) => {
    setBusyId(line.id)
    try {
      await settlementApi.unmatch(line.id)
      bypassNextGets(); load()
    } catch { toast.error('Could not unmatch') }
    finally { setBusyId(null) }
  }

  const shown = filter === 'unmatched'
    ? lines.filter((l) => l.status === 'unmatched')
    : lines

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-bold text-white">Card settlement</h1>
          <p className="text-sm text-slate-400">
            {summary?.needs_review
              ? `${summary.needs_review} payout${summary.needs_review === 1 ? '' : 's'} need review · ${formatCurrency(summary.needs_review_total)}`
              : 'Every payout is accounted for'}
          </p>
        </div>
        <div className="flex gap-2 sm:ml-auto">
          <input
            ref={fileRef} type="file" accept=".csv,.txt,text/csv" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f) }}
          />
          <button
            onClick={() => fileRef.current?.click()} disabled={uploading}
            className="btn-primary flex items-center gap-2 text-sm"
          >
            {uploading ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />}
            Import terminal export
          </button>
          <button
            onClick={() => setFilter(filter === 'unmatched' ? 'all' : 'unmatched')}
            className="btn-ghost text-sm"
          >
            {filter === 'unmatched' ? 'Show all' : 'Only unmatched'}
          </button>
          <button
            onClick={() => { bypassNextGets(); load() }}
            className="btn-ghost p-2 text-slate-400 hover:text-white" title="Refresh"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-surface-600 bg-surface-800/50 p-4 text-sm text-slate-300">
        Export the day&rsquo;s transactions from your Moniepoint or OPay dashboard and drop the
        file here. Each payout is matched to the sale it settles, by exact amount and time.
        Anything we can&rsquo;t be sure about is listed below rather than guessed.
      </div>

      <div className="card overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Paid', 'Reference', 'Terminal', 'Amount', 'Matched to', 'Status', ''].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && lines.length === 0 ? (
                Array.from({ length: 4 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 7 }).map((__, j) => (
                      <td key={j} className="px-5 py-3.5">
                        <div className="h-4 w-20 animate-pulse rounded bg-surface-700" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : shown.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-5 py-12 text-center">
                    <CreditCard size={28} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">
                      {filter === 'unmatched' ? 'Nothing needs review' : 'No payouts imported yet'}
                    </p>
                  </td>
                </tr>
              ) : shown.map((l) => (
                <tr key={l.id} className="table-row">
                  <td className="px-5 py-3.5 text-slate-400">
                    {l.paid_at ? formatDate(l.paid_at) : '—'}
                  </td>
                  <td className="px-5 py-3.5 font-mono text-xs text-white">{l.provider_reference}</td>
                  <td className="px-5 py-3.5 text-slate-400">
                    {l.terminal_id || '—'}
                    {l.card_last4 && <span className="block text-[11px] text-slate-500">•••• {l.card_last4}</span>}
                  </td>
                  <td className="px-5 py-3.5 text-right font-mono text-white">
                    {formatCurrency(l.amount)}
                    {Number(l.fee) > 0 && (
                      <span className="block text-[11px] text-slate-500">fee {formatCurrency(l.fee)}</span>
                    )}
                  </td>
                  <td className="px-5 py-3.5 text-slate-300">
                    {l.invoice_number || '—'}
                    {l.status === 'matched' && (
                      <span className="block text-[11px] text-slate-500">
                        {l.matched_automatically ? 'matched automatically' : 'matched by hand'}
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-3.5">
                    <span className={BADGE[l.status]}>{l.status_label}</span>
                  </td>
                  <td className="px-5 py-3.5">
                    <div className="flex items-center gap-1.5">
                      {l.status === 'unmatched' && (
                        <>
                          <button
                            onClick={() => openAssign(l)} disabled={busyId === l.id}
                            className="btn-ghost inline-flex items-center gap-1.5 px-2.5 py-1 text-xs text-brand-400"
                          >
                            <GitBranch size={12} /> Match
                          </button>
                          <button
                            onClick={() => bookAsIncome(l)} disabled={busyId === l.id}
                            className="btn-ghost px-2.5 py-1 text-xs"
                          >
                            Other income
                          </button>
                        </>
                      )}
                      {l.status === 'matched' && (
                        <button
                          onClick={() => unmatch(l)} disabled={busyId === l.id}
                          className="btn-ghost p-1.5 text-slate-500 hover:text-amber-400" title="Unmatch"
                        >
                          <X size={13} />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Match by hand ────────────────────────────────────────────────── */}
      {assigning && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setAssigning(null)} />
          <div className="card relative w-full max-w-lg space-y-4 p-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold text-white">Match this payout</h2>
                <p className="text-xs text-slate-400">
                  {formatCurrency(assigning.amount)} · {assigning.provider_reference}
                </p>
              </div>
              <button onClick={() => setAssigning(null)} className="text-slate-400 hover:text-white">
                <X size={18} />
              </button>
            </div>

            <p className="text-sm text-slate-400">
              Pick the card sale this payout settles. Only sales without a payout are shown.
            </p>

            <div className="max-h-72 space-y-1.5 overflow-y-auto">
              {candidates.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-500">
                  No unsettled card sales. The sale may not have been entered yet.
                </p>
              ) : candidates.map((c) => {
                const same = Number(c.amount) === Number(assigning.amount)
                return (
                  <button
                    key={c.id} onClick={() => assign(c.id)} disabled={busyId === assigning.id}
                    className="flex w-full items-center gap-3 rounded-lg border border-surface-600 p-3 text-left hover:border-brand-500"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-white">{c.invoice_number || 'Sale'}</p>
                      <p className="text-[11px] text-slate-500">{formatDate(c.received_at)}</p>
                    </div>
                    <span className={`font-mono text-sm ${same ? 'text-emerald-400' : 'text-slate-300'}`}>
                      {formatCurrency(c.amount)}
                    </span>
                    {same && <Check size={13} className="text-emerald-400" />}
                  </button>
                )
              })}
            </div>

            <p className="flex gap-2 text-[11px] text-amber-400/90">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              Matching a payout to the wrong sale is hard to spot later. Check the amount and
              time before you confirm.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
