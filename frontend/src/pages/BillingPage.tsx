import { useEffect, useState } from 'react'
import { CheckCircle, Loader2, CreditCard, Zap, Building2, Star, AlertCircle, ExternalLink, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import { subscriptionApi } from '@/services/api'
import type { Plan, Subscription, SubscriptionPayment } from '@/types'

const PLAN_ICONS: Record<string, React.ElementType> = {
  starter: Zap,
  professional: Star,
  business: Building2,
}

const STATUS_COLORS: Record<string, string> = {
  active: 'text-green-400 bg-green-400/10',
  trialing: 'text-blue-400 bg-blue-400/10',
  past_due: 'text-amber-400 bg-amber-400/10',
  canceled: 'text-red-400 bg-red-400/10',
  unpaid: 'text-red-400 bg-red-400/10',
  incomplete: 'text-slate-400 bg-slate-400/10',
}

function fmt(amount: string) {
  return '₦' + parseFloat(amount).toLocaleString('en-NG', { minimumFractionDigits: 2 })
}

function fmtDate(dt: string | null) {
  if (!dt) return '—'
  return new Date(dt).toLocaleDateString('en-NG', { day: '2-digit', month: 'short', year: 'numeric' })
}

export default function BillingPage() {
  const [plans, setPlans] = useState<Plan[]>([])
  const [subscription, setSubscription] = useState<Subscription | null>(null)
  const [payments, setPayments] = useState<SubscriptionPayment[]>([])
  const [loading, setLoading] = useState(true)
  const [subscribing, setSubscribing] = useState<string | null>(null) // plan id being processed
  const [verifyRef, setVerifyRef] = useState('')
  const [verifying, setVerifying] = useState(false)
  const [canceling, setCanceling] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [plansRes, subRes, paymentsRes] = await Promise.allSettled([
        subscriptionApi.plans(),
        subscriptionApi.current(),
        subscriptionApi.payments(),
      ])
      if (plansRes.status === 'fulfilled') setPlans(plansRes.value.data.results ?? plansRes.value.data)
      if (subRes.status === 'fulfilled') setSubscription(subRes.value.data)
      if (paymentsRes.status === 'fulfilled') setPayments(paymentsRes.value.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleSubscribe = async (plan: Plan) => {
    if (plan.price === '0.00' || parseFloat(plan.price) === 0) return
    setSubscribing(plan.id)
    try {
      const res = await subscriptionApi.initiatePayment(plan.id)
      const { authorization_url, reference } = res.data
      // Open Paystack checkout in the system browser
      window.open(authorization_url, '_blank')
      // Store reference so user can paste it back to verify
      setVerifyRef(reference)
      toast.success('Complete payment in the browser window that just opened, then click "Verify Payment" below.')
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Failed to initiate payment'
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Failed to initiate payment')
    } finally {
      setSubscribing(null)
    }
  }

  const handleVerify = async () => {
    if (!verifyRef.trim()) { toast.error('Enter the payment reference'); return }
    setVerifying(true)
    try {
      const res = await subscriptionApi.verifyPayment(verifyRef.trim())
      setSubscription(res.data)
      setVerifyRef('')
      toast.success('Payment verified! Your subscription is now active.')
      load()
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Verification failed'
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Verification failed')
    } finally {
      setVerifying(false)
    }
  }

  const handleCancel = async () => {
    if (!confirm('Cancel your subscription? You will retain access until the end of your current billing period.')) return
    setCanceling(true)
    try {
      const res = await subscriptionApi.cancel()
      setSubscription(res.data)
      toast.success('Subscription canceled. Access continues until period end.')
    } catch {
      toast.error('Failed to cancel subscription')
    } finally {
      setCanceling(false)
    }
  }

  const currentPlanSlug = subscription?.plan?.slug

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={24} className="animate-spin text-brand-400" />
      </div>
    )
  }

  return (
    <div className="space-y-8 max-w-5xl">
      <div>
        <h1 className="text-2xl font-bold text-white">Billing & Plans</h1>
        <p className="text-slate-400 text-sm mt-1">Manage your subscription and payment history.</p>
      </div>

      {/* Current plan status */}
      {subscription && (
        <div className="card flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="flex-1 space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-white font-semibold text-lg">{subscription.plan.name} Plan</span>
              <span className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize ${STATUS_COLORS[subscription.status] ?? 'text-slate-400 bg-slate-400/10'}`}>
                {subscription.status.replace('_', ' ')}
              </span>
            </div>
            <div className="text-sm text-slate-400 space-x-4">
              {subscription.current_period_end && (
                <span>
                  {subscription.status === 'canceled' ? 'Access until' : 'Renews'}{' '}
                  {fmtDate(subscription.current_period_end)}
                </span>
              )}
              {subscription.status === 'trialing' && subscription.trial_end && (
                <span className="text-blue-400">Trial ends {fmtDate(subscription.trial_end)}</span>
              )}
            </div>
          </div>
          {subscription.status !== 'canceled' && currentPlanSlug !== 'free' && (
            <button
              onClick={handleCancel}
              disabled={canceling}
              className="btn-ghost text-sm text-red-400 hover:text-red-300 flex items-center gap-1.5"
            >
              {canceling ? <Loader2 size={14} className="animate-spin" /> : null}
              Cancel subscription
            </button>
          )}
        </div>
      )}

      {/* Pending payment verification */}
      {verifyRef && (
        <div className="card border border-amber-500/30 bg-amber-500/5">
          <div className="flex items-start gap-3">
            <AlertCircle size={18} className="text-amber-400 mt-0.5 shrink-0" />
            <div className="flex-1">
              <p className="text-white text-sm font-medium">Complete your payment</p>
              <p className="text-slate-400 text-xs mt-0.5 mb-3">
                After paying in the browser, click "Verify Payment" to activate your subscription.
              </p>
              <div className="flex gap-2 flex-wrap">
                <input
                  type="text"
                  value={verifyRef}
                  onChange={(e) => setVerifyRef(e.target.value)}
                  placeholder="Payment reference (SUB-...)"
                  className="input text-sm flex-1 min-w-48"
                />
                <button
                  onClick={handleVerify}
                  disabled={verifying}
                  className="btn-primary flex items-center gap-1.5 text-sm"
                >
                  {verifying ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
                  Verify Payment
                </button>
                <button
                  onClick={() => setVerifyRef('')}
                  className="btn-ghost text-sm text-slate-400"
                >
                  Dismiss
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Plan cards */}
      <div>
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-4">Available Plans</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {plans.map((plan) => {
            const Icon = PLAN_ICONS[plan.slug] ?? CreditCard
            const isCurrent = plan.slug === currentPlanSlug
            const isPopular = plan.slug === 'professional'
            const price = parseFloat(plan.price)

            return (
              <div
                key={plan.id}
                className={`card relative flex flex-col gap-4 ${isPopular ? 'border-brand-500/50 ring-1 ring-brand-500/30' : ''} ${isCurrent ? 'border-green-500/40' : ''}`}
              >
                {isPopular && (
                  <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-brand-500 text-white text-xs font-semibold px-3 py-0.5 rounded-full">
                    Most Popular
                  </span>
                )}
                {isCurrent && (
                  <span className="absolute -top-3 right-4 bg-green-500 text-white text-xs font-semibold px-3 py-0.5 rounded-full flex items-center gap-1">
                    <CheckCircle size={10} /> Current
                  </span>
                )}

                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-brand-500/10 flex items-center justify-center">
                    <Icon size={18} className="text-brand-400" />
                  </div>
                  <div>
                    <p className="text-white font-semibold">{plan.name}</p>
                    <p className="text-xs text-slate-500">{plan.description}</p>
                  </div>
                </div>

                <div>
                  <span className="text-3xl font-bold text-white">
                    {price === 0 ? 'Free' : `₦${price.toLocaleString()}`}
                  </span>
                  {price > 0 && <span className="text-slate-400 text-sm">/{plan.interval}</span>}
                </div>

                {/* Feature list */}
                <ul className="space-y-2 text-sm flex-1">
                  <FeatureLine label={`${plan.features.max_products === 999999 ? 'Unlimited' : plan.features.max_products} products`} />
                  <FeatureLine label={`${plan.features.max_users === 999999 ? 'Unlimited' : plan.features.max_users} team members`} />
                  <FeatureLine label={`${plan.features.max_warehouses === 999999 ? 'Unlimited' : plan.features.max_warehouses} location(s)`} />
                  <FeatureLine label="Advanced reports" enabled={!!plan.features.advanced_reports} />
                  <FeatureLine label="Multi-location" enabled={!!plan.features.multi_warehouse} />
                  <FeatureLine label="API access" enabled={!!plan.features.api_access} />
                  <FeatureLine label={`Tax engine: ${plan.features.tax_engine}`} />
                </ul>

                {plan.trial_days > 0 && !isCurrent && (
                  <p className="text-xs text-brand-400 text-center">{plan.trial_days}-day free trial</p>
                )}

                <button
                  onClick={() => handleSubscribe(plan)}
                  disabled={isCurrent || subscribing === plan.id || price === 0}
                  className={`w-full flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-semibold transition-colors ${
                    isCurrent
                      ? 'bg-green-500/10 text-green-400 cursor-default'
                      : price === 0
                      ? 'bg-slate-700/40 text-slate-500 cursor-default'
                      : 'btn-primary'
                  }`}
                >
                  {subscribing === plan.id ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : isCurrent ? (
                    <><CheckCircle size={14} /> Current plan</>
                  ) : price === 0 ? (
                    'Free plan'
                  ) : (
                    <><ExternalLink size={14} /> Subscribe — {fmt(plan.price)}/{plan.interval}</>
                  )}
                </button>
              </div>
            )
          })}
        </div>
      </div>

      {/* Payment history */}
      {payments.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide mb-4">Payment History</h2>
          <div className="card overflow-hidden p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-700">
                  <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Date</th>
                  <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Description</th>
                  <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Amount</th>
                  <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {payments.map((p) => (
                  <tr key={p.id} className="border-b border-surface-700/50 last:border-0 hover:bg-surface-700/20">
                    <td className="px-4 py-3 text-slate-400">{fmtDate(p.created_at)}</td>
                    <td className="px-4 py-3 text-white">{p.description}</td>
                    <td className="px-4 py-3 text-white font-medium">{fmt(p.amount)}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium capitalize ${
                        p.status === 'succeeded' ? 'bg-green-500/10 text-green-400' :
                        p.status === 'failed' ? 'bg-red-500/10 text-red-400' :
                        'bg-slate-500/10 text-slate-400'
                      }`}>
                        {p.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Manual verify section (if user lost the reference) */}
      {!verifyRef && (
        <div className="card border-dashed">
          <div className="flex items-center gap-3">
            <RefreshCw size={16} className="text-slate-500" />
            <div className="flex-1">
              <p className="text-sm text-slate-400">Already paid but plan not activated?</p>
            </div>
            <button
              onClick={() => setVerifyRef(' ')}
              className="btn-ghost text-xs text-brand-400"
            >
              Verify payment
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function FeatureLine({ label, enabled }: { label: string; enabled?: boolean }) {
  const show = enabled === undefined ? true : enabled
  return (
    <li className={`flex items-center gap-2 ${show ? 'text-slate-300' : 'text-slate-600 line-through'}`}>
      <CheckCircle size={13} className={show ? 'text-green-400 shrink-0' : 'text-slate-700 shrink-0'} />
      {label}
    </li>
  )
}
