/**
 * CollectPaymentModal — take money for an invoice.
 *
 * Offers only what the merchant has actually set up:
 *   • One-time account  — a fresh account number per sale, confirmed by the
 *     provider within seconds, from any bank. Ends the "fake alert" argument.
 *   • Card / online     — the provider's hosted checkout page.
 *   • Bank transfer     — the merchant's own account. No provider means no
 *     webhook, so a person confirms it; the screen says so plainly.
 *
 * Used by the counter, the storefront checkout and the invoice screen.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { X, Landmark, CreditCard, Building2, Copy, Check, Loader2, Clock, AlertTriangle } from 'lucide-react'
import toast from 'react-hot-toast'
import { paymentGatewayApi } from '@/services/api'
import { formatCurrency } from '@/lib/utils'

interface BankAccount {
  id: string
  bank_name: string
  account_number: string
  account_name: string
  is_default: boolean
  instructions?: string
}

interface Options {
  card: boolean
  virtual_account: boolean
  bank_transfer: boolean
  provider: string
  bank_accounts: BankAccount[]
}

interface VirtualAccount {
  id: string
  account_number: string
  bank_name: string
  account_name: string
  amount: string
  expires_at: string | null
  status: string
}

type Method = 'virtual_account' | 'card' | 'bank_transfer'

interface Props {
  invoiceId: string
  invoiceNumber: string
  amountDue: number | string
  onClose: () => void
  /** Fired once the invoice is actually settled. */
  onPaid: () => void
}

/** Counts down to `iso`, returning mm:ss — or null once it has lapsed. */
function useCountdown(iso: string | null): string | null {
  const [left, setLeft] = useState<number>(0)
  useEffect(() => {
    if (!iso) return
    const tick = () => setLeft(Math.max(0, Math.floor((new Date(iso).getTime() - Date.now()) / 1000)))
    tick()
    const id = window.setInterval(tick, 1000)
    return () => window.clearInterval(id)
  }, [iso])
  if (!iso || left <= 0) return null
  const m = Math.floor(left / 60)
  const s = left % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function CollectPaymentModal({
  invoiceId, invoiceNumber, amountDue, onClose, onPaid,
}: Props) {
  const [options, setOptions] = useState<Options | null>(null)
  const [method, setMethod] = useState<Method | null>(null)
  const [busy, setBusy] = useState(false)
  const [account, setAccount] = useState<VirtualAccount | null>(null)
  const [copied, setCopied] = useState(false)
  const [payerName, setPayerName] = useState('')
  const [claimed, setClaimed] = useState(false)
  const pollRef = useRef<number | null>(null)

  const countdown = useCountdown(account?.expires_at ?? null)

  useEffect(() => {
    paymentGatewayApi.options()
      .then(({ data }) => {
        setOptions(data)
        // Pre-select the strongest method the merchant actually offers.
        setMethod(
          data.virtual_account ? 'virtual_account'
            : data.card ? 'card'
            : data.bank_transfer ? 'bank_transfer'
            : null,
        )
      })
      .catch(() => toast.error('Could not load payment methods'))
  }, [])

  // Stop polling when the modal closes, or it keeps running in the background.
  useEffect(() => () => { if (pollRef.current) window.clearInterval(pollRef.current) }, [])

  const startPolling = useCallback((id: string) => {
    if (pollRef.current) window.clearInterval(pollRef.current)
    pollRef.current = window.setInterval(async () => {
      try {
        const { data } = await paymentGatewayApi.virtualAccountStatus(id)
        if (data.status === 'paid') {
          if (pollRef.current) window.clearInterval(pollRef.current)
          toast.success('Payment received')
          onPaid()
        } else if (data.status === 'expired') {
          if (pollRef.current) window.clearInterval(pollRef.current)
        }
      } catch { /* a dropped poll is not worth a toast — the next one retries */ }
    }, 4000)
  }, [onPaid])

  const issueAccount = async () => {
    setBusy(true)
    try {
      const { data } = await paymentGatewayApi.issueVirtualAccount(invoiceId)
      setAccount(data)
      startPolling(data.id)
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Could not create an account number')
    } finally { setBusy(false) }
  }

  const openCheckout = async () => {
    setBusy(true)
    try {
      const { data } = await paymentGatewayApi.createLink(invoiceId)
      window.open(data.link_url, '_blank', 'noopener')
      toast.success('Payment page opened')
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Could not create a payment link')
    } finally { setBusy(false) }
  }

  const claimTransfer = async () => {
    setBusy(true)
    try {
      await paymentGatewayApi.claimTransfer({
        invoice: invoiceId, amount: String(amountDue), payer_name: payerName,
        narration: invoiceNumber,
      })
      setClaimed(true)
      toast.success('Sent for confirmation')
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Could not record the transfer')
    } finally { setBusy(false) }
  }

  const copy = (text: string) => {
    navigator.clipboard?.writeText(text)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1800)
  }

  const bank = options?.bank_accounts?.[0]
  const nothingConfigured =
    options && !options.card && !options.virtual_account && !options.bank_transfer

  const TABS: { key: Method; label: string; icon: typeof Landmark; on: boolean }[] = [
    { key: 'virtual_account', label: 'One-time account', icon: Landmark, on: !!options?.virtual_account },
    { key: 'card', label: 'Card / online', icon: CreditCard, on: !!options?.card },
    { key: 'bank_transfer', label: 'Bank transfer', icon: Building2, on: !!options?.bank_transfer },
  ]

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative card w-full max-w-md p-6 space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-white">Collect payment</h2>
            <p className="text-xs text-slate-400">{invoiceNumber}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white" aria-label="Close">
            <X size={20} />
          </button>
        </div>

        <div className="text-center py-2">
          <p className="text-xs text-slate-400">Amount due</p>
          <p className="text-3xl font-bold text-white font-mono">{formatCurrency(amountDue)}</p>
        </div>

        {!options ? (
          <div className="flex justify-center py-6"><Loader2 size={20} className="animate-spin text-slate-500" /></div>
        ) : nothingConfigured ? (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200/90 flex gap-3">
            <AlertTriangle size={16} className="shrink-0 mt-0.5" />
            <span>
              No online payment method is set up yet. Add your bank account or your gateway keys in
              <strong> Settings → Payment Gateways</strong>, or take this payment in cash.
            </span>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-2">
              {TABS.filter((t) => t.on).map((t) => (
                <button
                  key={t.key}
                  onClick={() => setMethod(t.key)}
                  className={`rounded-xl border p-2.5 text-center transition-colors ${
                    method === t.key
                      ? 'border-brand-500 bg-brand-500/15 text-white'
                      : 'border-surface-600 text-slate-400 hover:text-white'
                  }`}
                >
                  <t.icon size={16} className="mx-auto mb-1" />
                  <span className="text-[11px] leading-tight block">{t.label}</span>
                </button>
              ))}
            </div>

            {/* ── One-time account ─────────────────────────────────────── */}
            {method === 'virtual_account' && (
              account ? (
                <div className="space-y-3">
                  <div className="rounded-xl border border-dashed border-amber-500/40 bg-surface-800 p-4 text-center">
                    <p className="text-[10px] uppercase tracking-widest text-slate-500">
                      Transfer exactly this amount to
                    </p>
                    <p className="text-2xl font-mono text-white tracking-wider my-2">
                      {account.account_number}
                    </p>
                    <p className="text-sm text-slate-300">
                      {account.bank_name} · {account.account_name}
                    </p>
                    <button
                      onClick={() => copy(account.account_number)}
                      className="btn-ghost mt-3 text-xs inline-flex items-center gap-1.5"
                    >
                      {copied ? <Check size={12} /> : <Copy size={12} />}
                      {copied ? 'Copied' : 'Copy number'}
                    </button>
                  </div>
                  <p className="text-center text-xs text-amber-400 flex items-center justify-center gap-1.5">
                    <Clock size={12} />
                    {countdown ? `Account expires in ${countdown}` : 'This account has expired'}
                  </p>
                  <p className="text-center text-xs text-slate-400 flex items-center justify-center gap-2">
                    <Loader2 size={12} className="animate-spin" />
                    Waiting for the transfer — confirms automatically
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-sm text-slate-400">
                    Issues a fresh account number for this sale only. The customer can transfer from
                    any bank and it confirms here within seconds — no screenshot needed.
                  </p>
                  <button onClick={issueAccount} disabled={busy} className="btn-primary w-full py-2.5 justify-center">
                    {busy ? <Loader2 size={16} className="animate-spin" /> : 'Get account number'}
                  </button>
                </div>
              )
            )}

            {/* ── Hosted checkout ──────────────────────────────────────── */}
            {method === 'card' && (
              <div className="space-y-3">
                <p className="text-sm text-slate-400">
                  Opens a secure payment page where the customer can pay by card. The sale is marked
                  paid as soon as the payment clears.
                </p>
                <button onClick={openCheckout} disabled={busy} className="btn-primary w-full py-2.5 justify-center">
                  {busy ? <Loader2 size={16} className="animate-spin" /> : 'Open payment page'}
                </button>
              </div>
            )}

            {/* ── Merchant's own account ───────────────────────────────── */}
            {method === 'bank_transfer' && bank && (
              claimed ? (
                <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200/90">
                  Recorded. This sale stays unpaid until someone confirms the money has landed in
                  your bank — check <strong>Payments → Transfers to confirm</strong>.
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="rounded-xl border border-surface-600 bg-surface-800 p-4 text-center">
                    <p className="text-[10px] uppercase tracking-widest text-slate-500">Transfer to</p>
                    <p className="text-2xl font-mono text-white tracking-wider my-2">{bank.account_number}</p>
                    <p className="text-sm text-slate-300">{bank.bank_name} · {bank.account_name}</p>
                    <button
                      onClick={() => copy(bank.account_number)}
                      className="btn-ghost mt-3 text-xs inline-flex items-center gap-1.5"
                    >
                      {copied ? <Check size={12} /> : <Copy size={12} />}
                      {copied ? 'Copied' : 'Copy number'}
                    </button>
                    {bank.instructions && (
                      <p className="text-[11px] text-slate-500 mt-2">{bank.instructions}</p>
                    )}
                  </div>
                  <input
                    className="input"
                    placeholder="Who is sending it? (optional)"
                    value={payerName}
                    onChange={(e) => setPayerName(e.target.value)}
                  />
                  <p className="text-[11px] text-amber-400/90 flex gap-1.5">
                    <AlertTriangle size={12} className="shrink-0 mt-0.5" />
                    This account has no automatic confirmation. Someone must check the bank before the
                    sale counts as paid.
                  </p>
                  <button onClick={claimTransfer} disabled={busy} className="btn-primary w-full py-2.5 justify-center">
                    {busy ? <Loader2 size={16} className="animate-spin" /> : 'Customer has transferred'}
                  </button>
                </div>
              )
            )}
          </>
        )}
      </div>
    </div>
  )
}
