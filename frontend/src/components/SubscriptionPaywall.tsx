import { useState, useEffect, useRef } from 'react'
import { Lock, RefreshCw, CheckCircle } from 'lucide-react'
import toast from 'react-hot-toast'
import { subscriptionApi, bypassNextGets } from '@/services/api'

// Paystack Inline JS type declaration (same as BillingPage)
declare global {
  interface Window {
    PaystackPop: {
      setup(opts: {
        key: string
        email: string
        amount: number
        ref: string
        currency?: string
        onClose: () => void
        callback: (response: { reference: string }) => void
      }): { openIframe(): void }
    }
  }
}

function loadPaystackScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.PaystackPop) { resolve(); return }
    const existing = document.getElementById('paystack-inline-js')
    if (existing) { existing.addEventListener('load', () => resolve()); return }
    const script = document.createElement('script')
    script.id = 'paystack-inline-js'
    script.src = 'https://js.paystack.co/v1/inline.js'
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Failed to load Paystack script'))
    document.head.appendChild(script)
  })
}

interface SubscriptionData {
  is_trial: boolean
  is_expired: boolean
  plan: {
    id: string
    name: string
    slug: string
    price: string
  }
}

interface Props {
  subscription: SubscriptionData | null
  onDismiss: () => void
}

export default function SubscriptionPaywall({ subscription, onDismiss }: Props) {
  const [loading, setLoading] = useState(false)
  const [verifying, setVerifying] = useState(false)
  const [polling, setPolling] = useState(false)
  const [reference, setReference] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
    setPolling(false)
  }

  /** Called after any successful payment — verify with backend, then dismiss. */
  const handlePaymentSuccess = async (ref: string) => {
    setVerifying(true)
    try {
      await subscriptionApi.verifyPayment(ref)
      stopPolling()
      // Bypass the 5-min GET cache so AppLayout re-fetches fresh subscription state
      bypassNextGets()
      window.dispatchEvent(new CustomEvent('audity:app-refresh'))
      toast.success('Subscription activated! Access restored.')
      onDismiss()
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Payment verification failed'
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Verification failed')
    } finally {
      setVerifying(false)
    }
  }

  /** Poll-based fallback: used after opening external URL (shouldn't normally happen). */
  const handlePollVerify = async (ref: string) => {
    try {
      const { data } = await subscriptionApi.checkPayment(ref)
      if (data.status === 'success') {
        stopPolling()
        bypassNextGets()
        window.dispatchEvent(new CustomEvent('audity:app-refresh'))
        toast.success('Subscription renewed! Access restored.')
        onDismiss()
      }
    } catch { /* keep polling */ }
  }

  const startPolling = (ref: string) => {
    setPolling(true)
    let attempts = 0
    pollRef.current = setInterval(async () => {
      attempts++
      if (attempts > 100) { stopPolling(); return }
      await handlePollVerify(ref)
    }, 3000)
  }

  const handleRenew = async () => {
    if (!subscription?.plan?.id) return
    setLoading(true)
    try {
      const { data } = await subscriptionApi.initiatePayment(subscription.plan.id)
      const { access_code, reference: ref, public_key, amount_kobo, email } = data

      if (!public_key) {
        toast.error('Paystack public key is not configured. Contact support.')
        return
      }

      // Use inline Paystack popup (same as BillingPage) so callback fires in-app
      await loadPaystackScript()
      setReference(ref)

      const handler = window.PaystackPop.setup({
        key: public_key,
        email,
        amount: amount_kobo,
        ref,
        ...(access_code ? { accessCode: access_code } as any : {}),
        currency: 'NGN',
        onClose: () => {
          toast('Payment cancelled.', { icon: '🚫' })
          startPolling(ref) // fall back to polling in case popup closed after payment
        },
        callback: (response) => {
          handlePaymentSuccess(response.reference)
        },
      })
      handler.openIframe()
    } catch (err: any) {
      const errData = err?.response?.data?.error
      if (!errData?.message) {
        const msg = typeof errData === 'string' ? errData : err?.message ?? 'Failed to initiate payment'
        toast.error(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  const planName = subscription?.plan?.name ?? 'your plan'
  const isTrial = subscription?.is_trial

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="w-full max-w-md mx-4 bg-surface-900 border border-surface-700 rounded-2xl shadow-2xl p-8 text-center space-y-6">
        <div className="flex justify-center">
          <div className="w-16 h-16 rounded-full bg-amber-500/10 border border-amber-500/30 flex items-center justify-center">
            <Lock size={28} className="text-amber-400" />
          </div>
        </div>

        <div className="space-y-2">
          <h2 className="text-xl font-bold text-white">
            {isTrial ? 'Free Trial Ended' : 'Subscription Expired'}
          </h2>
          <p className="text-slate-400 text-sm leading-relaxed">
            {isTrial
              ? `Your 14-day free trial on the ${planName} plan has ended.`
              : `Your ${planName} subscription has expired.`}
            {' '}Renew now to continue using all features.
          </p>
        </div>

        {verifying ? (
          <div className="flex items-center justify-center gap-3 py-3 bg-surface-800 rounded-xl border border-surface-600">
            <RefreshCw size={16} className="text-brand-400 animate-spin" />
            <span className="text-sm text-slate-300">Confirming payment…</span>
          </div>
        ) : !polling ? (
          <button
            onClick={handleRenew}
            disabled={loading}
            className="btn-primary w-full py-3 text-base disabled:opacity-50"
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <RefreshCw size={16} className="animate-spin" /> Opening payment…
              </span>
            ) : (
              'Renew Subscription'
            )}
          </button>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-center gap-3 py-3 bg-surface-800 rounded-xl border border-surface-600">
              <RefreshCw size={16} className="text-brand-400 animate-spin" />
              <span className="text-sm text-slate-300">Waiting for payment confirmation…</span>
            </div>
            <button
              onClick={() => reference && handlePaymentSuccess(reference)}
              disabled={verifying}
              className="w-full py-2.5 text-sm text-brand-400 border border-brand-500/30 rounded-xl hover:bg-brand-500/10 transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
            >
              <CheckCircle size={15} />
              I&apos;ve completed payment
            </button>
          </div>
        )}

        <p className="text-xs text-slate-600">
          Payment is processed securely by Paystack. Your access will be restored instantly after confirmation.
        </p>
      </div>
    </div>
  )
}
