/**
 * Transfers to confirm.
 *
 * Only for money sent to the merchant's own bank account, where no provider can
 * tell us it arrived. Nothing here is posted until someone checks the bank and
 * confirms — which is exactly the manual step a one-time account number removes.
 */

import { useEffect, useState } from 'react'
import { Banknote, Check, X, Loader2, RefreshCw, ExternalLink } from 'lucide-react'
import toast from 'react-hot-toast'
import { paymentGatewayApi, bypassNextGets } from '@/services/api'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { confirmDialog, promptDialog } from '@/lib/dialog'
import { formatCurrency, formatDate } from '@/lib/utils'

interface Claim {
  id: string
  invoice: string
  invoice_number: string
  bank_name: string
  account_number: string
  amount: string
  payer_name: string
  narration: string
  status: 'awaiting' | 'confirmed' | 'rejected'
  reviewed_by_name?: string
  reviewed_at?: string | null
  review_note?: string
  created_at: string
}

const STATUS_BADGE: Record<Claim['status'], string> = {
  awaiting: 'badge-yellow',
  confirmed: 'badge-green',
  rejected: 'badge-red',
}

export default function TransferConfirmationsPage() {
  const [claims, setClaims] = useState<Claim[]>([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [filter, setFilter] = useState<'awaiting' | 'all'>('awaiting')

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await paymentGatewayApi.transferClaims({ page_size: 200 })
      setClaims(data.results ?? data)
    } catch { toast.error('Could not load transfers') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useDataRefresh(load)

  const confirm = async (claim: Claim) => {
    const ok = await confirmDialog(
      `Confirm ${formatCurrency(claim.amount)} received for ${claim.invoice_number}? ` +
      `Only do this once you can see the money in your bank.`,
    )
    if (!ok) return
    setBusyId(claim.id)
    try {
      await paymentGatewayApi.confirmTransfer(claim.id)
      toast.success('Payment recorded')
      bypassNextGets(); load()
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Could not confirm the transfer')
    } finally { setBusyId(null) }
  }

  const reject = async (claim: Claim) => {
    const note = await promptDialog('Why is this being rejected?', {
      placeholder: 'e.g. nothing showed up in the bank', optional: true,
    })
    if (note === null) return
    setBusyId(claim.id)
    try {
      await paymentGatewayApi.rejectTransfer(claim.id, note)
      toast.success('Transfer rejected')
      bypassNextGets(); load()
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Could not reject the transfer')
    } finally { setBusyId(null) }
  }

  const shown = filter === 'awaiting' ? claims.filter((c) => c.status === 'awaiting') : claims
  const awaitingCount = claims.filter((c) => c.status === 'awaiting').length

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Transfers to confirm</h1>
          <p className="text-slate-400 text-sm">
            {awaitingCount === 0
              ? 'Nothing waiting on you'
              : `${awaitingCount} transfer${awaitingCount === 1 ? '' : 's'} waiting to be checked`}
          </p>
        </div>
        <div className="sm:ml-auto flex gap-2">
          <button
            onClick={() => setFilter(filter === 'awaiting' ? 'all' : 'awaiting')}
            className="btn-ghost text-sm"
          >
            {filter === 'awaiting' ? 'Show all' : 'Show only waiting'}
          </button>
          <button
            onClick={() => { bypassNextGets(); load() }}
            disabled={loading}
            className="btn-ghost p-2 text-slate-400 hover:text-white"
            title="Refresh"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-amber-500/25 bg-amber-500/5 p-4 text-sm text-slate-300">
        These are transfers into your own bank account, so Audity cannot see them arrive.
        Check your bank first — confirming here records the payment and posts it to your accounts.
        To skip this step entirely, use a one-time account number at checkout instead.
      </div>

      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Received', 'Invoice', 'From', 'Into', 'Amount', 'Status', ''].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
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
                    <Banknote size={30} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">
                      {filter === 'awaiting' ? 'No transfers waiting' : 'No transfers yet'}
                    </p>
                  </td>
                </tr>
              ) : shown.map((c) => (
                <tr key={c.id} className="table-row">
                  <td className="px-5 py-3.5 text-slate-400">{formatDate(c.created_at)}</td>
                  <td className="px-5 py-3.5">
                    <a
                      href={`/sales?invoice=${c.invoice}`}
                      className="text-brand-400 hover:underline inline-flex items-center gap-1"
                    >
                      {c.invoice_number} <ExternalLink size={11} />
                    </a>
                  </td>
                  <td className="px-5 py-3.5 text-white">{c.payer_name || '—'}</td>
                  <td className="px-5 py-3.5 text-slate-400">
                    {c.bank_name ? `${c.bank_name} · ${c.account_number}` : '—'}
                  </td>
                  <td className="px-5 py-3.5 text-right font-mono text-white">
                    {formatCurrency(c.amount)}
                  </td>
                  <td className="px-5 py-3.5">
                    <span className={STATUS_BADGE[c.status]}>{c.status}</span>
                    {c.review_note && (
                      <span className="block text-[10px] text-slate-500 mt-0.5">{c.review_note}</span>
                    )}
                  </td>
                  <td className="px-5 py-3.5">
                    {c.status === 'awaiting' && (
                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() => confirm(c)}
                          disabled={busyId === c.id}
                          className="btn-primary px-3 py-1.5 text-xs inline-flex items-center gap-1.5"
                        >
                          {busyId === c.id
                            ? <Loader2 size={12} className="animate-spin" />
                            : <Check size={12} />}
                          Confirm
                        </button>
                        <button
                          onClick={() => reject(c)}
                          disabled={busyId === c.id}
                          className="btn-ghost p-1.5 text-slate-400 hover:text-red-400"
                          title="Reject"
                        >
                          <X size={14} />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
