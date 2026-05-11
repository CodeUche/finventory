import { useEffect, useState, useCallback } from 'react'
import { CheckCircle, X as XIcon, Loader2, CreditCard, Zap, Building2, Star, ExternalLink, RefreshCw, Package, ShoppingCart, FileText, Receipt, Users, Truck, BarChart3, Calculator, Briefcase, Wallet, Clock, DollarSign, Shield, ChevronDown, ChevronUp, GraduationCap, LayoutDashboard, FileBarChart2, Layers, Coins } from 'lucide-react'
import toast from 'react-hot-toast'
import { useNavigate } from 'react-router-dom'
import { subscriptionApi, orgApi, bypassNextGets, partnerApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import type { Plan, Subscription, SubscriptionPayment } from '@/types'
import { FEATURES } from '@/lib/featureFlags'

// Paystack Inline JS type declaration
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

/** Dynamically load the Paystack Inline JS once per session. */
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

const PLAN_ICONS: Record<string, React.ElementType> = {
  free: Zap,
  starter: Zap,
  professional: Star,
  'professional-annual': Star,
  business: Building2,
  'business-annual': Building2,
  enterprise: Layers,
  'enterprise-annual': Layers,
}

// Hardcoded per-plan module details for clear comparison
type ModuleRow = {
  icon: React.ElementType
  label: string
  tip: string
  free: boolean | string
  professional: boolean | string
  business: boolean | string
  enterprise: boolean | string
}

const MODULE_ROWS: ModuleRow[] = [
  { icon: ShoppingCart,    label: 'Sales & Invoicing',          tip: 'Create invoices, record payments, manage your sales pipeline',                                                free: '10/month',   professional: true,               business: true,               enterprise: true },
  { icon: Users,           label: 'Customer Management',        tip: 'Full customer database, statements, credits and balances',                                                    free: 'Up to 20',   professional: true,               business: true,               enterprise: true },
  { icon: Package,         label: 'Inventory Management',       tip: 'Products, stock levels, reorder alerts, batches and lots',                                                    free: 'Up to 20',   professional: true,               business: true,               enterprise: true },
  { icon: Wallet,          label: 'Expense Tracking',           tip: 'Record expenses by category, track savings vs prior period',                                                  free: '10/month',   professional: true,               business: true,               enterprise: true },
  { icon: Calculator,      label: 'Tax Engine',                 tip: 'Free: VAT only. Professional: VAT + Income Tax. Business & Enterprise: Full (WHT, Excise, Filing Guide)',   free: 'VAT only',   professional: 'VAT + Income Tax', business: 'Full',             enterprise: 'Full' },
  { icon: BarChart3,       label: 'Reports & Analytics',        tip: 'P&L, revenue trends, top products, top customers, expense breakdown and balance sheet',                       free: 'Basic',      professional: 'Advanced',         business: 'Advanced',         enterprise: 'Advanced + Custom' },
  { icon: FileText,        label: 'Quotes & Estimates',         tip: 'Send price quotes before converting to invoices',                                                             free: false,        professional: true,               business: true,               enterprise: true },
  { icon: Clock,           label: 'Recurring Invoices',         tip: 'Auto-generate invoices on a schedule for retainer clients',                                                   free: false,        professional: true,               business: true,               enterprise: true },
  { icon: Truck,           label: 'Purchase Orders',            tip: 'Raise POs to suppliers and track delivery and receipt',                                                       free: false,        professional: true,               business: true,               enterprise: true },
  { icon: Receipt,         label: 'Bills & Payables',           tip: 'Track bills owed, schedule payments, manage folders',                                                         free: false,        professional: true,               business: true,               enterprise: true },
  { icon: DollarSign,      label: 'Budget Planning',            tip: 'Set spending budgets per category, compare actual vs planned',                                                free: false,        professional: true,               business: true,               enterprise: true },
  { icon: Shield,          label: 'Audit Log',                  tip: 'Full trail of every action — who did what and when',                                                          free: false,        professional: true,               business: true,               enterprise: true },
  { icon: Users,           label: 'Team & Permissions',         tip: 'Invite staff with per-module access levels',                                                                  free: false,        professional: 'Up to 3 users',    business: 'Up to 5 users',    enterprise: 'Unlimited + Custom roles' },
  { icon: Briefcase,       label: 'Payroll & HR',               tip: 'Manage employees, run payroll, compute PAYE and pension',                                                     free: false,        professional: false,              business: true,               enterprise: true },
  { icon: Calculator,      label: 'Accounting Ledger',          tip: 'Full chart of accounts, journal entries, fixed assets, bank reconciliation',                                  free: false,        professional: false,              business: true,               enterprise: true },
  { icon: Shield,          label: 'Owner Analytics',            tip: 'Private profit view using personal cost price — only you see this',                                           free: false,        professional: false,              business: true,               enterprise: true },
  { icon: Package,         label: 'API Access',                 tip: 'Business: Read-only API. Enterprise: Full read/write REST API + webhooks',                                    free: false,        professional: false,              business: 'Read-only',        enterprise: 'Full + Webhooks' },
  { icon: Layers,          label: 'Multi-Entity Management',    tip: 'Create branches, subsidiaries or business units — each with its own data and team, managed from one account', free: false,        professional: false,              business: false,              enterprise: true },
  { icon: LayoutDashboard, label: 'White-Label Branding',       tip: 'Custom logo, brand colours and domain — your clients see your brand, not Audity\'s',                         free: false,        professional: false,              business: false,              enterprise: true },
  { icon: GraduationCap,   label: 'Dedicated Support & SLA',   tip: 'Named account manager, <4hr priority response, and a guided onboarding session',                              free: false,        professional: false,              business: false,              enterprise: true },
  { icon: FileBarChart2,   label: 'Bulk Export & Scheduled Reports', tip: 'Automated report delivery on a schedule and bulk data exports across all entities',                     free: false,        professional: false,              business: false,              enterprise: true },
]

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

// Map annual slug → base plan slug for feature column lookup
function basePlanSlug(slug: string): 'free' | 'professional' | 'business' | 'enterprise' {
  if (slug === 'professional' || slug === 'professional-annual') return 'professional'
  if (slug === 'business' || slug === 'business-annual') return 'business'
  if (slug === 'enterprise' || slug === 'enterprise-annual') return 'enterprise'
  return 'free'
}

export default function BillingPage() {
  const navigate = useNavigate()
  const { organisation, setOrganisation, setSubscriptionExpired } = useAuthStore()
  const [plans, setPlans] = useState<Plan[]>([])
  const [subscription, setSubscription] = useState<Subscription | null>(null)
  const [payments, setPayments] = useState<SubscriptionPayment[]>([])
  const [loading, setLoading] = useState(true)
  const [subscribing, setSubscribing] = useState<string | null>(null)
  const [canceling, setCanceling] = useState(false)
  const [billingInterval, setBillingInterval] = useState<'monthly' | 'annual'>('monthly')
  const [commissionBalance, setCommissionBalance] = useState<number>(0)
  const [applyingCredit, setApplyingCredit] = useState(false)
  const [useCredits, setUseCredits] = useState(true)

  const isPartner = useAuthStore((s) => s.planName)?.startsWith('partner') ?? false

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

  const loadCommission = async () => {
    if (!isPartner) return
    try {
      const res = await partnerApi.commission()
      setCommissionBalance(res.data.available_balance ?? 0)
    } catch { /* non-fatal */ }
  }

  useEffect(() => { load(); loadCommission() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handlePaymentSuccess = useCallback(async (reference: string) => {
    toast.loading('Confirming payment…', { id: 'pay-verify' })
    try {
      const res = await subscriptionApi.verifyPayment(reference)
      setSubscription(res.data)
      toast.success('Payment confirmed! Your subscription is now active.', { id: 'pay-verify' })

      // Clear paywall and force AppLayout to re-check subscription via the
      // audity:app-refresh event (increments _appRefreshTick → re-runs the
      // subscription useEffect → confirms active from fresh DB data).
      setSubscriptionExpired(false)
      window.dispatchEvent(new CustomEvent('audity:app-refresh'))

      if (organisation?.id) {
        try {
          const orgRes = await orgApi.list()
          const orgs: any[] = orgRes.data.results ?? orgRes.data
          const fresh = orgs.find((o: any) => o.id === organisation.id) ?? null
          if (fresh) setOrganisation(fresh)
        } catch { /* non-fatal */ }
      }

      load()
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Payment verification failed'
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Verification failed', { id: 'pay-verify' })
    }
  }, [organisation?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubscribe = async (plan: Plan) => {
    if (plan.price === '0.00' || parseFloat(plan.price) === 0) return
    setSubscribing(plan.id)
    try {
      // Step 1: initialise transaction on backend (creates pending PaymentHistory record)
      const res = await subscriptionApi.initiatePayment(plan.id)
      const { access_code, reference, public_key, amount_kobo, email, authorization_url } = res.data

      if (!public_key) {
        toast.error('Paystack public key is not configured. Contact support.')
        return
      }

      // For partner plans the Paystack iframe doesn't load in the desktop WebView2.
      // Open the hosted checkout page in the system browser instead.
      if (plan.slug?.startsWith('partner-')) {
        window.open(authorization_url, '_blank')
        toast('Payment page opened in your browser. Return here and click "Refresh status" once done.', { duration: 8000 })
        return
      }

      // Step 2: load Paystack Inline JS (cached after first load)
      await loadPaystackScript()

      // Step 3: open the in-app Paystack payment modal
      const handler = window.PaystackPop.setup({
        key: public_key,
        email,
        amount: amount_kobo,
        ref: reference,
        // access_code pre-populates the checkout — faster and already tied to this transaction
        ...(access_code ? { accessCode: access_code } : {}),
        currency: 'NGN',
        onClose: () => {
          toast('Payment cancelled.', { icon: '🚫' })
        },
        callback: (response) => {
          handlePaymentSuccess(response.reference)
        },
      })
      handler.openIframe()
    } catch (err: any) {
      // The Axios interceptor already shows a toast when errData.message is set (envelope errors).
      // Only show a component-level toast for non-envelope errors to avoid duplicates.
      const errData = err?.response?.data?.error
      if (!errData?.message) {
        const msg = typeof errData === 'string' ? errData : err?.message ?? 'Failed to initiate payment'
        toast.error(msg)
      }
    } finally {
      setSubscribing(null)
    }
  }

  const handleRenewWithCredits = async (plan: Plan) => {
    if (!subscription?.id) return
    const price = parseFloat(plan.price)
    const applyAmount = Math.min(commissionBalance, price)
    setApplyingCredit(true)
    try {
      const res = await partnerApi.applyCredit({
        subscription_id: subscription.id,
        amount_to_apply: applyAmount.toFixed(2),
      })
      toast.success(res.data.message ?? 'Credits applied!')
      setCommissionBalance(res.data.new_balance)
      if (res.data.path === 'A') {
        // Fully covered — refresh subscription state
        window.dispatchEvent(new CustomEvent('audity:app-refresh'))
        load()
      } else {
        // Partial — remaining goes to Paystack
        await handleSubscribeWithRemainder(plan, res.data.remainder)
      }
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Failed to apply credits'
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Failed to apply credits')
    } finally {
      setApplyingCredit(false)
    }
  }

  const handleSubscribeWithRemainder = async (plan: Plan, remainder: number) => {
    if (remainder <= 0) return
    setSubscribing(plan.id)
    try {
      const res = await subscriptionApi.initiatePayment(plan.id)
      const { public_key, reference, amount_kobo: _orig, email, authorization_url } = res.data
      const adjustedKobo = Math.round(remainder * 100)
      if (!public_key) { toast.error('Paystack public key not configured.'); return }
      if (plan.slug?.startsWith('partner-')) {
        window.open(authorization_url, '_blank')
        toast('Payment page opened in your browser.', { duration: 8000 })
        return
      }
      await loadPaystackScript()
      const handler = window.PaystackPop.setup({
        key: public_key, email, amount: adjustedKobo, ref: reference, currency: 'NGN',
        onClose: () => toast('Payment cancelled.', { icon: '🚫' }),
        callback: (response) => handlePaymentSuccess(response.reference),
      })
      handler.openIframe()
    } catch {
      toast.error('Failed to initiate payment for remaining amount')
    } finally {
      setSubscribing(null)
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

  const handlePartnerTrial = async (plan: Plan) => {
    setSubscribing(plan.id)
    try {
      await subscriptionApi.startTrial(plan.id, organisation?.id)
      setSubscriptionExpired(false)
      window.dispatchEvent(new CustomEvent('audity:app-refresh'))
      toast.success(`${plan.name} trial started — 30 days free!`)
      navigate('/partner')
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to start trial')
      toast.error(msg)
    } finally {
      setSubscribing(null)
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
    <div className="space-y-8 w-full">
      <div>
        <h1 className="text-2xl font-bold text-white">Billing & Plans</h1>
        <p className="text-slate-400 text-sm mt-1">Manage your subscription and payment history.</p>
      </div>

      {/* Current plan status */}
      {subscription && (
        <div className="card flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="flex-1 space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-white font-semibold text-lg">{subscription.plan?.name ?? 'Current'} Plan</span>
              <span className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize ${STATUS_COLORS[subscription.status] ?? 'text-slate-400 bg-slate-400/10'}`}>
                {subscription.status.replace('_', ' ')}
              </span>
            </div>
            <div className="text-sm text-slate-400 space-x-4">
              {subscription.current_period_end && currentPlanSlug !== 'free' && (
                <span>
                  {subscription.status === 'canceled'
                    ? 'Access until'
                    : subscription.status === 'trialing'
                    ? 'Trial expires'
                    : 'Renews'}{' '}
                  {fmtDate(subscription.current_period_end)}
                </span>
              )}
              {subscription.status === 'trialing' && subscription.trial_end && (
                <span className="text-blue-400">Trial ends {fmtDate(subscription.trial_end)}</span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            {currentPlanSlug !== 'business' && currentPlanSlug !== 'business-annual' && (
              <a
                href="#plans"
                className="btn-primary text-sm flex items-center gap-1.5"
                onClick={(e) => { e.preventDefault(); document.getElementById('plans-section')?.scrollIntoView({ behavior: 'smooth' }) }}
              >
                <Zap size={14} /> Upgrade Plan
              </a>
            )}
            {subscription.status !== 'canceled' && currentPlanSlug !== 'free' && currentPlanSlug !== 'starter' && (
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
        </div>
      )}

      {/* Plan cards */}
      <div id="plans-section">
        <div className="flex flex-col sm:flex-row sm:items-center gap-4 mb-5">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wide">Available Plans</h2>
          {/* Monthly / Annual toggle */}
          <div className="flex items-center gap-1 bg-surface-800 border border-surface-700 rounded-xl p-1">
            <button
              onClick={() => setBillingInterval('monthly')}
              className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-colors ${billingInterval === 'monthly' ? 'bg-brand-500 text-white' : 'text-slate-400 hover:text-white'}`}
            >
              Monthly
            </button>
            <button
              onClick={() => setBillingInterval('annual')}
              className={`flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold transition-colors ${billingInterval === 'annual' ? 'bg-brand-500 text-white' : 'text-slate-400 hover:text-white'}`}
            >
              Annual
              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${billingInterval === 'annual' ? 'bg-white/20 text-white' : 'bg-green-500/20 text-green-400'}`}>
                1 month free
              </span>
            </button>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-5">
          {plans.filter((p) => {
            if (p.slug.startsWith('partner-')) return false
            const isFree = parseFloat(p.price) === 0
            if (isFree) return billingInterval === 'monthly'  // free only in monthly view
            return p.interval === billingInterval
          }).map((plan) => {
            const Icon = PLAN_ICONS[plan.slug] ?? CreditCard
            const isCurrent = plan.slug === currentPlanSlug
            const isPopular = plan.slug === 'professional'
            const isAnnual = plan.interval === 'annual'
            const price = parseFloat(plan.price)
            const isFree = price === 0

            return (
              <div
                key={plan.id}
                className={`card relative flex flex-col gap-4 ${isPopular ? 'border-brand-500/50 ring-1 ring-brand-500/30' : ''} ${isCurrent ? 'border-green-500/40' : ''}`}
              >
                {isPopular && !isAnnual && (
                  <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-brand-500 text-white text-xs font-semibold px-3 py-0.5 rounded-full">
                    Most Popular
                  </span>
                )}
                {isAnnual && (
                  <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-green-500 text-white text-xs font-semibold px-3 py-0.5 rounded-full flex items-center gap-1">
                    <CheckCircle size={10} /> 1 Month Free
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
                    <p className="text-white font-semibold">{plan.name.replace(' Annual', '')}</p>
                    <p className="text-xs text-slate-500">{plan.description}</p>
                  </div>
                </div>

                <div>
                  <span className="text-3xl font-bold text-white">
                    {isFree ? 'Free' : `₦${price.toLocaleString()}`}
                  </span>
                  {!isFree && (
                    <span className="text-slate-400 text-sm">/{isAnnual ? 'year' : 'month'}</span>
                  )}
                  {isAnnual && (
                    <p className="text-xs text-green-400 mt-0.5">
                      ₦{Math.round(price / 12).toLocaleString()}/mo · save ₦{Math.round(price / 11).toLocaleString()}
                    </p>
                  )}
                </div>

                {/* Limits tiles */}
                <div className="grid grid-cols-3 gap-2 text-center">
                  {isFree ? (
                    <>
                      <div className="rounded-lg bg-surface-700/40 border border-surface-600 py-2">
                        <p className="text-white font-bold text-base leading-none">10</p>
                        <p className="text-xs text-slate-500 mt-0.5">inv/month</p>
                      </div>
                      <div className="rounded-lg bg-surface-700/40 border border-surface-600 py-2">
                        <p className="text-white font-bold text-base leading-none">20</p>
                        <p className="text-xs text-slate-500 mt-0.5">customers</p>
                      </div>
                      <div className="rounded-lg bg-surface-700/40 border border-surface-600 py-2">
                        <p className="text-white font-bold text-base leading-none">20</p>
                        <p className="text-xs text-slate-500 mt-0.5">products</p>
                      </div>
                    </>
                  ) : (
                    [
                      { val: (plan.features as any).max_products >= 999999 ? '∞' : (plan.features as any).max_products, sub: 'products' },
                      { val: (plan.features as any).max_users >= 999999 ? '∞' : (plan.features as any).max_users, sub: 'users' },
                      { val: (plan.features as any).max_warehouses >= 999999 ? '∞' : (plan.features as any).max_warehouses, sub: 'locations' },
                    ].map(({ val, sub }) => (
                      <div key={sub} className="rounded-lg bg-surface-700/40 border border-surface-600 py-2">
                        <p className="text-white font-bold text-lg leading-none">{val}</p>
                        <p className="text-xs text-slate-500 mt-0.5">{sub}</p>
                      </div>
                    ))
                  )}
                </div>

                {/* Module list */}
                <PlanModuleList slug={plan.slug} />

                {plan.trial_days > 0 && !isCurrent && (
                  <p className="text-xs text-brand-400 text-center">{plan.trial_days}-day free trial</p>
                )}

                {/* Commission credits banner — shown when partner has a balance */}
                {isPartner && !isCurrent && !isFree && commissionBalance > 0 && useCredits && (
                  <div className="rounded-lg bg-green-500/10 border border-green-500/20 px-3 py-2 text-xs text-green-400 space-y-0.5">
                    <div className="flex items-center gap-1.5 font-medium">
                      <Coins size={12} />
                      ₦{commissionBalance.toLocaleString()} credits available
                    </div>
                    <p className="text-green-500/70">
                      {commissionBalance >= price
                        ? 'Renew free — fully covered by credits'
                        : `Pay only ₦${(price - commissionBalance).toLocaleString()} after credits`}
                    </p>
                  </div>
                )}

                {isPartner && !isCurrent && !isFree && commissionBalance > 0 && (
                  <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={useCredits}
                      onChange={(e) => setUseCredits(e.target.checked)}
                      className="accent-brand-500"
                    />
                    Apply commission credits
                  </label>
                )}

                <button
                  onClick={() => {
                    if (isPartner && !isCurrent && !isFree && commissionBalance > 0 && useCredits) {
                      handleRenewWithCredits(plan)
                    } else {
                      handleSubscribe(plan)
                    }
                  }}
                  disabled={isCurrent || subscribing === plan.id || applyingCredit || isFree}
                  className={`w-full flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-semibold transition-colors ${
                    isCurrent
                      ? 'bg-green-500/10 text-green-400 cursor-default'
                      : isFree
                      ? 'bg-surface-700/40 text-slate-400 cursor-default'
                      : 'btn-primary'
                  }`}
                >
                  {(subscribing === plan.id || applyingCredit) ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : isCurrent ? (
                    <><CheckCircle size={14} /> Current plan</>
                  ) : isFree ? (
                    'Always free'
                  ) : isPartner && commissionBalance >= price && useCredits ? (
                    <><Coins size={14} /> Renew Free with Credits</>
                  ) : (
                    <><ExternalLink size={14} /> Subscribe — {fmt(plan.price)}/{isAnnual ? 'yr' : 'mo'}</>
                  )}
                </button>
              </div>
            )
          })}
        </div>
      </div>

      {/* ── Partner / Accountant Channel — hidden until PARTNER_CHANNEL feature enabled ── */}
      {FEATURES.PARTNER_CHANNEL && (
        <PartnerChannelSection plans={plans} currentPlanSlug={currentPlanSlug} onSubscribe={handleSubscribe} onStartTrial={handlePartnerTrial} subscribing={subscribing} />
      )}

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

      {/* Fallback: paid but not activated (e.g. closed popup before callback fired) */}
      <div className="card border-dashed">
        <div className="flex items-center gap-3">
          <RefreshCw size={16} className="text-slate-500" />
          <p className="text-sm text-slate-400 flex-1">Paid but plan not activated?</p>
          <button onClick={() => { bypassNextGets(); load() }} className="btn-ghost text-xs text-brand-400">
            <RefreshCw size={13} /> Refresh status
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Partner / Accountant Channel ──────────────────────────────────────────────

const PARTNER_TIERS = [
  {
    slug: 'partner-starter',
    name: 'Partner Starter',
    price: 30000,
    clients: '10 clients',
    badge: null,
    features: [
      'Your own full Business-tier account',
      'Multi-client dashboard (up to 10 SMBs)',
      'Per-client seat billing',
      'Referral commission tracking',
      '14-day free trial',
    ],
  },
  {
    slug: 'partner-pro',
    name: 'Partner Pro',
    price: 75000,
    clients: '30 clients',
    badge: 'Popular',
    features: [
      'Everything in Partner Starter',
      'Up to 30 SMB clients',
      'White-label reports (your logo)',
      'Consolidated cross-client reporting',
      'Volume pricing as your base grows',
    ],
  },
  {
    slug: 'partner-agency',
    name: 'Partner Agency',
    price: 150000,
    clients: 'Unlimited clients',
    badge: 'Enterprise',
    features: [
      'Everything in Partner Pro',
      'Unlimited SMB clients',
      'Full custom branding',
      'Client health dashboard',
      'Dedicated support + SLA',
    ],
  },
]

const PARTNER_COLOR: Record<string, { border: string; badge: string; icon: string }> = {
  'partner-starter': { border: 'border-slate-600/50', badge: '', icon: 'text-slate-400' },
  'partner-pro':     { border: 'border-amber-500/50 ring-1 ring-amber-500/20', badge: 'bg-amber-500 text-white', icon: 'text-amber-400' },
  'partner-agency':  { border: 'border-purple-500/40 ring-1 ring-purple-500/20', badge: 'bg-purple-500 text-white', icon: 'text-purple-400' },
}

function PartnerChannelSection({
  plans,
  currentPlanSlug,
  onSubscribe,
  onStartTrial,
  subscribing,
}: {
  plans: Plan[]
  currentPlanSlug: string | undefined
  onSubscribe: (plan: Plan) => void
  onStartTrial: (plan: Plan) => void
  subscribing: string | null
}) {
  const [open, setOpen] = useState(true)
  const [partnerInterval, setPartnerInterval] = useState<'monthly' | 'annual'>('monthly')

  const partnerPlanBySlug = (slug: string) => plans.find((p) => p.slug === slug)

  return (
    <div className="space-y-4">
      {/* Collapsible header */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between p-4 card hover:border-brand-500/30 transition-colors"
      >
        <div className="flex items-center gap-3 text-left">
          <div className="w-9 h-9 rounded-xl bg-purple-500/10 flex items-center justify-center shrink-0">
            <GraduationCap size={18} className="text-purple-400" />
          </div>
          <div>
            <p className="text-white font-semibold text-sm">Partner / Accountant Channel</p>
            <p className="text-xs text-slate-400">
              Resell Audity to your SMB clients — your licence fee + per-client seats + referral commissions
            </p>
          </div>
        </div>
        {open ? <ChevronUp size={16} className="text-slate-400 shrink-0" /> : <ChevronDown size={16} className="text-slate-400 shrink-0" />}
      </button>

      {open && (
        <div className="space-y-6">
          {/* Monthly / Annual toggle */}
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-xs text-slate-400">Billing interval:</span>
            <div className="flex items-center gap-1 bg-surface-800 border border-surface-700 rounded-xl p-1">
              <button
                onClick={() => setPartnerInterval('monthly')}
                className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-colors ${partnerInterval === 'monthly' ? 'bg-purple-500 text-white' : 'text-slate-400 hover:text-white'}`}
              >
                Monthly
              </button>
              <button
                onClick={() => setPartnerInterval('annual')}
                className={`flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold transition-colors ${partnerInterval === 'annual' ? 'bg-purple-500 text-white' : 'text-slate-400 hover:text-white'}`}
              >
                Annual
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${partnerInterval === 'annual' ? 'bg-white/20 text-white' : 'bg-green-500/20 text-green-400'}`}>
                  1 month free
                </span>
              </button>
            </div>
          </div>

          {/* Tier cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {PARTNER_TIERS.map((tier) => {
              const plan = partnerPlanBySlug(tier.slug)
              const isCurrent = tier.slug === currentPlanSlug
              const colors = PARTNER_COLOR[tier.slug]
              const isSubscribing = plan && subscribing === plan.id
              const displayPrice = partnerInterval === 'annual' ? tier.price * 11 : tier.price
              const isAnnual = partnerInterval === 'annual'
              const hasTrial = plan && plan.trial_days > 0 && !isCurrent

              return (
                <div key={tier.slug} className={`card relative flex flex-col gap-4 ${colors.border}`}>
                  {tier.badge && (
                    <span className={`absolute -top-3 left-1/2 -translate-x-1/2 text-xs font-semibold px-3 py-0.5 rounded-full ${colors.badge}`}>
                      {tier.badge}
                    </span>
                  )}
                  {isCurrent && (
                    <span className="absolute -top-3 right-4 bg-green-500 text-white text-xs font-semibold px-3 py-0.5 rounded-full flex items-center gap-1">
                      <CheckCircle size={10} /> Current
                    </span>
                  )}

                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-xl bg-purple-500/10 flex items-center justify-center shrink-0">
                      <GraduationCap size={16} className={colors.icon} />
                    </div>
                    <div>
                      <p className="text-white font-semibold text-sm">{tier.name}</p>
                      <p className="text-xs text-slate-500">{tier.clients}</p>
                    </div>
                  </div>

                  <div>
                    <span className="text-3xl font-bold text-white">₦{displayPrice.toLocaleString()}</span>
                    <span className="text-slate-400 text-sm">/{isAnnual ? 'year' : 'month'}</span>
                    {isAnnual && (
                      <p className="text-xs text-green-400 mt-0.5">
                        ₦{Math.round(displayPrice / 12).toLocaleString()}/mo · save ₦{tier.price.toLocaleString()}
                      </p>
                    )}
                  </div>

                  {/* Tiles row */}
                  <div className="grid grid-cols-2 gap-2 text-center">
                    <div className="rounded-lg bg-surface-700/40 border border-surface-600 py-2">
                      <LayoutDashboard size={14} className="text-purple-400 mx-auto mb-0.5" />
                      <p className="text-xs text-slate-400">Multi-client</p>
                    </div>
                    <div className="rounded-lg bg-surface-700/40 border border-surface-600 py-2">
                      <FileBarChart2 size={14} className="text-purple-400 mx-auto mb-0.5" />
                      <p className="text-xs text-slate-400">
                        {tier.slug === 'partner-starter' ? 'Standard reports' : 'White-label'}
                      </p>
                    </div>
                  </div>

                  {/* Feature list */}
                  <div className="space-y-1 flex-1">
                    {tier.features.map((f) => (
                      <div key={f} className="flex items-center gap-2">
                        <CheckCircle size={12} className="text-green-400 shrink-0" />
                        <span className="text-xs text-slate-300">{f}</span>
                      </div>
                    ))}
                  </div>

                  <button
                    onClick={() => {
                      if (!plan) return
                      if (hasTrial) onStartTrial(plan)
                      else onSubscribe(plan)
                    }}
                    disabled={isCurrent || !!isSubscribing || !plan}
                    className={`w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold transition-colors ${
                      isCurrent
                        ? 'bg-green-500/10 text-green-400 cursor-default'
                        : tier.slug === 'partner-pro'
                        ? 'bg-amber-500 hover:bg-amber-400 text-white disabled:opacity-50'
                        : 'bg-purple-500 hover:bg-purple-400 text-white disabled:opacity-50'
                    }`}
                  >
                    {isSubscribing ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : isCurrent ? (
                      <><CheckCircle size={14} /> Current plan</>
                    ) : hasTrial ? (
                      <><Zap size={14} /> Start 30-day free trial</>
                    ) : (
                      <><ExternalLink size={14} /> Subscribe — ₦{displayPrice.toLocaleString()}/{isAnnual ? 'yr' : 'mo'}</>
                    )}
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

function PlanModuleList({ slug }: { slug: string }) {
  const [expanded, setExpanded] = useState(false)
  const validKey = basePlanSlug(slug)

  const SHOW_INITIAL = 8
  const visible = expanded ? MODULE_ROWS : MODULE_ROWS.slice(0, SHOW_INITIAL)

  return (
    <div className="space-y-1 flex-1">
      {visible.map((row) => {
        const val = row[validKey as 'free' | 'professional' | 'business' | 'enterprise']
        const included = val !== false
        const badge = typeof val === 'string' ? val : null
        const Icon = row.icon
        return (
          <div key={row.label} className="group/mod relative flex items-center gap-2 py-1">
            {included
              ? <CheckCircle size={13} className="text-green-400 shrink-0" />
              : <XIcon size={13} className="text-slate-700 shrink-0" />}
            <Icon size={13} className={included ? 'text-slate-400 shrink-0' : 'text-slate-700 shrink-0'} />
            <span className={`text-xs ${included ? 'text-slate-300' : 'text-slate-600'}`}>{row.label}</span>
            {badge && (
              <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-brand-500/15 text-brand-400 ml-auto shrink-0">{badge}</span>
            )}
            {/* Tooltip */}
            <span className="pointer-events-none absolute left-0 bottom-full mb-1.5 w-56 rounded-xl bg-surface-800 border border-surface-600 px-3 py-2 text-xs text-slate-300 leading-relaxed opacity-0 group-hover/mod:opacity-100 transition-opacity duration-150 z-[9999] shadow-xl">
              {row.tip}
              <span className="absolute top-full left-4 border-[5px] border-transparent border-t-surface-600" />
            </span>
          </div>
        )
      })}
      {MODULE_ROWS.length > SHOW_INITIAL && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-1 text-xs text-brand-400 hover:text-brand-300 mt-1 transition-colors"
        >
          {expanded ? <><ChevronUp size={12} /> Show less</> : <><ChevronDown size={12} /> Show all {MODULE_ROWS.length} features</>}
        </button>
      )}
    </div>
  )
}
