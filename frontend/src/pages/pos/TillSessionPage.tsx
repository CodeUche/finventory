/**
 * Till session — open a shift, close it against a blind count.
 *
 * The count is blind on purpose: the cashier types what is physically in the
 * drawer BEFORE the screen shows what the system expected. Revealing the
 * expected figure first turns a control into a formality.
 */

import { useEffect, useState } from 'react'
import {
  Wallet, Lock, Unlock, Loader2, AlertTriangle, CheckCircle, Printer, RefreshCw,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { tillApi, bypassNextGets } from '@/services/api'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { formatCurrency, formatDate, formatAmountInput, stripCommas } from '@/lib/utils'

interface TenderRow { method: string; expected: string; counted: string; variance: string; transaction_count: number }
interface Current {
  open: boolean
  id?: string
  opened_at?: string
  opening_float?: string
  expected_cash?: string
  sales_total?: string
  transaction_count?: number
  by_tender?: Record<string, { expected: string; count: number }>
}
interface ZReport {
  session_id: string
  cashier: string
  location: string
  opened_at: string
  closed_at: string
  opening_float: string
  sales_total: string
  cash_variance: string
  variance_reason: string
  tenders: TenderRow[]
}

const TENDER_LABEL: Record<string, string> = {
  cash: 'Cash',
  pos: 'Card — terminal',
  card: 'Card',
  bank_transfer: 'Bank transfer',
  cheque: 'Cheque',
  credit_applied: 'On account',
}
const tenderLabel = (m: string) => TENDER_LABEL[m] ?? m

export default function TillSessionPage() {
  const [current, setCurrent] = useState<Current | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const [openingFloat, setOpeningFloat] = useState('')
  const [counted, setCounted] = useState<Record<string, string>>({})
  const [reason, setReason] = useState('')
  const [report, setReport] = useState<ZReport | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await tillApi.current()
      setCurrent(data)
      if (!data.open) setCounted({})
    } catch { toast.error('Could not load the till') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useDataRefresh(load)

  const openTill = async () => {
    setBusy(true)
    try {
      await tillApi.open({ opening_float: stripCommas(openingFloat || '0') })
      toast.success('Till open')
      setOpeningFloat(''); setReport(null)
      bypassNextGets(); load()
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Could not open the till')
    } finally { setBusy(false) }
  }

  const closeTill = async () => {
    if (!current?.id) return
    if (!counted.cash?.trim()) { toast.error('Enter the cash you counted'); return }
    setBusy(true)
    try {
      const payload: Record<string, string> = {}
      Object.entries(counted).forEach(([m, v]) => { if (v.trim()) payload[m] = stripCommas(v) })
      const { data } = await tillApi.close(current.id, { counted: payload, reason })
      setReport(data)
      toast.success('Till closed')
      setReason(''); setCounted({})
      bypassNextGets(); load()
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Could not close the till')
    } finally { setBusy(false) }
  }

  // Tenders to count: whatever passed through the till, always including cash.
  const tenders = Array.from(
    new Set(['cash', ...Object.keys(current?.by_tender ?? {})]),
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Till</h1>
          <p className="text-slate-400 text-sm">
            {current?.open
              ? `Open since ${formatDate(current.opened_at ?? '')}`
              : 'No till open — start a shift to take cash'}
          </p>
        </div>
        <button
          onClick={() => { bypassNextGets(); load() }}
          disabled={loading}
          className="sm:ml-auto btn-ghost p-2 text-slate-400 hover:text-white"
          title="Refresh"
        >
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {loading ? (
        <div className="card p-10 flex justify-center">
          <Loader2 size={20} className="animate-spin text-slate-500" />
        </div>
      ) : !current?.open ? (
        /* ── Open a shift ─────────────────────────────────────────────── */
        <div className="card p-6 space-y-4 max-w-md">
          <div className="flex items-center gap-2">
            <Unlock size={16} className="text-brand-400" />
            <h2 className="text-base font-semibold text-white">Open the till</h2>
          </div>
          <p className="text-sm text-slate-400">
            Count the cash you are starting with. Everything taken from now until you
            close is measured against it.
          </p>
          <div>
            <label className="label">Opening float</label>
            <input
              className="input" inputMode="decimal" placeholder="0.00"
              value={openingFloat}
              onChange={(e) => setOpeningFloat(formatAmountInput(e.target.value))}
            />
          </div>
          <button onClick={openTill} disabled={busy} className="btn-primary w-full py-2.5 justify-center">
            {busy ? <Loader2 size={16} className="animate-spin" /> : 'Open till'}
          </button>
        </div>
      ) : (
        /* ── Close the shift ──────────────────────────────────────────── */
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {[
              { k: 'Opening float', v: current.opening_float, s: 'Set at open' },
              { k: 'Sales this shift', v: current.sales_total, s: `${current.transaction_count ?? 0} transactions` },
              { k: 'Cash expected', v: current.expected_cash, s: 'Float plus cash taken' },
              { k: 'Non-cash', v: String(
                  Number(current.sales_total ?? 0) -
                  Number(current.by_tender?.cash?.expected ?? 0),
                ), s: 'Card and transfer' },
            ].map(({ k, v, s }) => (
              <div key={k} className="card p-4">
                <p className="text-[10px] uppercase tracking-widest text-slate-500">{k}</p>
                <p className="text-xl font-bold text-white font-mono mt-1">{formatCurrency(v ?? 0)}</p>
                <p className="text-[11px] text-slate-500 mt-0.5">{s}</p>
              </div>
            ))}
          </div>

          <div className="card p-6 space-y-4 max-w-2xl">
            <div className="flex items-center gap-2">
              <Wallet size={16} className="text-brand-400" />
              <h2 className="text-base font-semibold text-white">Count the drawer</h2>
            </div>
            <p className="text-sm text-slate-400">
              Enter what you have physically counted. The difference against what the
              system expected is worked out when you close, and is posted to your accounts.
            </p>

            <div className="space-y-2">
              {tenders.map((m) => (
                <div key={m} className="grid grid-cols-12 gap-3 items-center">
                  <span className="col-span-5 text-sm text-slate-300">{tenderLabel(m)}</span>
                  <span className="col-span-3 text-xs text-slate-500">
                    {current.by_tender?.[m]?.count ?? 0} txn
                  </span>
                  <input
                    className="input col-span-4" inputMode="decimal"
                    placeholder={m === 'cash' ? 'Counted (required)' : 'Counted (optional)'}
                    value={counted[m] ?? ''}
                    onChange={(e) => setCounted({ ...counted, [m]: formatAmountInput(e.target.value) })}
                  />
                </div>
              ))}
            </div>

            <input
              className="input" placeholder="Reason for any difference (optional)"
              value={reason} onChange={(e) => setReason(e.target.value)}
            />

            <button onClick={closeTill} disabled={busy} className="btn-primary w-full py-2.5 justify-center">
              {busy ? <Loader2 size={16} className="animate-spin" /> : <><Lock size={15} /> Close till &amp; count</>}
            </button>
          </div>
        </>
      )}

      {/* ── Z-report ───────────────────────────────────────────────────── */}
      {report && (
        <div className="card p-6 space-y-4 max-w-2xl print:shadow-none" id="z-report">
          <div className="flex items-center gap-2">
            {Number(report.cash_variance) === 0
              ? <CheckCircle size={16} className="text-emerald-400" />
              : <AlertTriangle size={16} className="text-amber-400" />}
            <h2 className="text-base font-semibold text-white">End of shift</h2>
            <button
              onClick={() => window.print()}
              className="ml-auto btn-ghost text-xs flex items-center gap-1.5 print:hidden"
            >
              <Printer size={13} /> Print
            </button>
          </div>

          <div className="text-sm text-slate-400">
            {report.cashier}{report.location ? ` · ${report.location}` : ''} ·{' '}
            {formatDate(report.opened_at)} → {formatDate(report.closed_at)}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-700">
                  {['Tender', 'Txns', 'Expected', 'Counted', 'Difference'].map((h) => (
                    <th key={h} className="px-3 py-2 text-left text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {report.tenders.map((t) => (
                  <tr key={t.method} className="border-b border-surface-800">
                    <td className="px-3 py-2 text-white">{tenderLabel(t.method)}</td>
                    <td className="px-3 py-2 text-slate-400 font-mono">{t.transaction_count}</td>
                    <td className="px-3 py-2 text-right font-mono text-slate-300">{formatCurrency(t.expected)}</td>
                    <td className="px-3 py-2 text-right font-mono text-white">{formatCurrency(t.counted)}</td>
                    <td className={`px-3 py-2 text-right font-mono ${
                      Number(t.variance) === 0 ? 'text-slate-500'
                        : Number(t.variance) < 0 ? 'text-red-400' : 'text-emerald-400'
                    }`}>
                      {Number(t.variance) === 0 ? '—' : formatCurrency(t.variance)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {Number(report.cash_variance) !== 0 && (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200/90 flex gap-3">
              <AlertTriangle size={16} className="shrink-0 mt-0.5" />
              <span>
                Cash is {formatCurrency(Math.abs(Number(report.cash_variance)))}{' '}
                <strong>{Number(report.cash_variance) < 0 ? 'short' : 'over'}</strong>.
                It has been posted to Cash Over &amp; Short in your accounts
                {report.variance_reason ? ` — "${report.variance_reason}"` : ''}.
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
