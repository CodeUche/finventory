import { useState, useEffect, useRef } from 'react'
import { Lock, RefreshCw, CheckCircle } from 'lucide-react'
import toast from 'react-hot-toast'
import { subscriptionApi } from '@/services/api'
import { openExternal } from '@/lib/openExternal'
import { formatCurrency } from '@/lib/utils'

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
  const [polling, setPolling] = useState(false)
  const [reference, setReference] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Clear polling on unmount
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
    setPolling(false)
  }

  const handleVerify = async (ref: string) => {
    try {
      const { data } = await subscriptionApi.checkPayment(ref)
      if (data.status === 'success') {
        stopPolling()
        toast.success('Subscription renewed! Access restored.')
        onDismiss()
      }
    } catch { /* still polling */ }
  }

  const startPolling = (ref: string) => {
    setPolling(true)
    let attempts = 0
    pollRef.current = setInterval(async () => {
      attempts++
      if (attempts > 100) { stopPolling(); return }
      await handleVerify(ref)
    }, 3000)
  }

  const handleRenew = async () => {
    if (!subscription?.plan?.id) return
    setLoading(true)
    try {
      const { data } = await subscriptionApi.initiatePayment(subscription.plan.id)
      setReference(data.reference)
      await openExternal(data.authorization_url)
      startPolling(data.reference)
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Failed to initiate payment'
      toast.error(typeof msg === 'string' ? msg : msg.message ?? 'Failed to initiate payment')
    } finally {
      setLoading(false)
    }
  }

  const planName = subscription?.plan?.name ?? 'your plan'
  const planPrice = subscription?.plan?.price ? formatCurrency(subscription.plan.price) : ''
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

        {planPrice && (
          <div className="bg-brand-500/10 border border-brand-500/20 rounded-xl px-5 py-3">
            <p className="text-xs text-slate-400 mb-0.5">Renewal price</p>
            <p className="text-2xl font-bold text-brand-400">{planPrice}</p>
            <p className="text-xs text-slate-500">per month · {planName} plan</p>
          </div>
        )}

        {!polling ? (
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
              onClick={() => reference && handleVerify(reference)}
              className="w-full py-2.5 text-sm text-brand-400 border border-brand-500/30 rounded-xl hover:bg-brand-500/10 transition-colors flex items-center justify-center gap-2"
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
