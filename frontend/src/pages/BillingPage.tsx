import { useEffect, useState, useCallback } from 'react'
import { CheckCircle, X as XIcon, Loader2, CreditCard, Zap, Building2, Star, ExternalLink, RefreshCw, Package, ShoppingCart, FileText, Receipt, Users, Truck, BarChart3, Calculator, Briefcase, Wallet, Clock, DollarSign, Shield, ChevronDown, ChevronUp } from 'lucide-react'
import toast from 'react-hot-toast'
import { subscriptionApi } from '@/services/api'
import type { Plan, Subscription, SubscriptionPayment } from '@/types'

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
  starter: Zap,
  professional: Star,
  business: Building2,
}

// Hardcoded per-plan module details for clear comparison
// Each entry: [icon, label, tooltip description, starter, professional, business]
type ModuleRow = {
  icon: React.ElementType
  label: string
  tip: string
  starter: boolean | string
  professional: boolean | string
  business: boolean | string
}

const MODULE_ROWS: ModuleRow[] = [
  { icon: ShoppingCart,  label: 'Sales & Invoicing',       tip: 'Create invoices, record payments, manage your sales pipeline',                          starter: true,      professional: true,       business: true },
  { icon: FileText,      label: 'Quotes & Estimates',      tip: 'Send price quotes to customers before converting them to invoices',                      starter: true,      professional: true,       business: true },
  { icon: Clock,         label: 'Recurring Invoices',      tip: 'Auto-generate invoices on a schedule for subscription or retainer clients',              starter: true,      professional: true,       business: true },
  { icon: Truck,         label: 'Purchase Orders',         tip: 'Raise purchase orders to suppliers and track delivery and receipt',                      starter: true,      professional: true,       business: true },
  { icon: Receipt,       label: 'Bills & Payables',        tip: 'Track bills owed to suppliers, schedule payments, manage folders',                       starter: true,      professional: true,       business: true },
  { icon: Wallet,        label: 'Expense Tracking',        tip: 'Record business expenses and income, group by category, track savings',                  starter: true,      professional: true,       business: true },
  { icon: Package,       label: 'Inventory Management',   tip: 'Manage products, track stock levels, set reorder alerts, handle batches and lots',        starter: true,      professional: true,       business: true },
  { icon: Users,         label: 'Customer Management',    tip: 'Maintain a full customer database, view statement, track credits and balances',           starter: true,      professional: true,       business: true },
  { icon: Truck,         label: 'Supplier Management',    tip: 'Manage your supplier contacts and link them to purchases and bills',                      starter: true,      professional: true,       business: true },
  { icon: DollarSign,    label: 'Budget Planning',         tip: 'Set spending budgets per category, compare actual vs planned spend',                     starter: true,      professional: true,       business: true },
  { icon: Calculator,    label: 'Tax Engine',              tip: 'Starter: VAT only. Professional: VAT + Income Tax + Tools. Business: Full (adds Excise Duty, WHT, Filing Guide)', starter: 'VAT only', professional: 'VAT + Income Tax', business: 'Full' },
  { icon: BarChart3,     label: 'Reports & Analytics',    tip: 'P&L, revenue trends, top products, top customers, expense breakdown and balance sheet',  starter: 'Basic',   professional: 'Advanced', business: 'Advanced' },
  { icon: Briefcase,     label: 'Payroll',                 tip: 'Manage employees, run payroll, compute PAYE and pension deductions',                     starter: false,     professional: false,      business: true },
  { icon: Calculator,    label: 'Accounting Ledger',      tip: 'Full chart of accounts, journal entries, fixed assets, bank reconciliation',              starter: false,     professional: false,      business: true },
  { icon: Shield,        label: 'Owner Analytics',         tip: 'Private profit view using your personal cost price — only you can see this',             starter: false,     professional: false,      business: true },
  { icon: FileText,      label: 'Audit Log',               tip: 'Full trail of every action taken in the system — who did what and when',                 starter: false,     professional: true,       business: true },
  { icon: Users,         label: 'Team & Permissions',     tip: 'Invite staff with custom access levels per module (e.g. view-only, write, full edit)',    starter: false,     professional: true,       business: true },
  { icon: Package,       label: 'API Access',              tip: 'Connect Audity to your own tools and integrations via REST API',                         starter: false,     professional: false,      business: true },
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

export default function BillingPage() {
  const [plans, setPlans] = useState<Plan[]>([])
  const [subscription, setSubscription] = useState<Subscription | null>(null)
  const [payments, setPayments] = useState<SubscriptionPayment[]>([])
  const [loading, setLoading] = useState(true)
  const [subscribing, setSubscribing] = useState<string | null>(null) // plan id being processed
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

  const handlePaymentSuccess = useCallback(async (reference: string) => {
    toast.loading('Confirming payment…', { id: 'pay-verify' })
    try {
      const res = await subscriptionApi.verifyPayment(reference)
      setSubscription(res.data)
      toast.success('Payment confirmed! Your subscription is now active.', { id: 'pay-verify' })
      load()
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Payment verification failed'
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Verification failed', { id: 'pay-verify' })
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubscribe = async (plan: Plan) => {
    if (plan.price === '0.00' || parseFloat(plan.price) === 0) return
    setSubscribing(plan.id)
    try {
      // Step 1: initialise transaction on backend (creates pending PaymentHistory record)
      const res = await subscriptionApi.initiatePayment(plan.id)
      const { access_code, reference, public_key, amount_kobo, email } = res.data

      if (!public_key) {
        toast.error('Paystack public key is not configured. Contact support.')
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
      const msg = err?.response?.data?.error ?? err?.message ?? 'Failed to initiate payment'
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Failed to initiate payment')
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
          <div className="flex items-center gap-3 flex-wrap">
            {currentPlanSlug !== 'business' && (
              <a
                href="#plans"
                className="btn-primary text-sm flex items-center gap-1.5"
                onClick={(e) => { e.preventDefault(); document.getElementById('plans-section')?.scrollIntoView({ behavior: 'smooth' }) }}
              >
                <Zap size={14} /> Upgrade Plan
              </a>
            )}
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
        </div>
      )}

      {/* Plan cards */}
      <div id="plans-section">
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

                {/* Limits row */}
                <div className="grid grid-cols-3 gap-2 text-center">
                  {[
                    { val: plan.features.max_products === 999999 ? '∞' : plan.features.max_products, sub: 'products' },
                    { val: plan.features.max_users === 999999 ? '∞' : plan.features.max_users, sub: 'users' },
                    { val: plan.features.max_warehouses === 999999 ? '∞' : plan.features.max_warehouses, sub: 'locations' },
                  ].map(({ val, sub }) => (
                    <div key={sub} className="rounded-lg bg-surface-700/40 border border-surface-600 py-2">
                      <p className="text-white font-bold text-lg leading-none">{val}</p>
                      <p className="text-xs text-slate-500 mt-0.5">{sub}</p>
                    </div>
                  ))}
                </div>

                {/* Module list */}
                <PlanModuleList slug={plan.slug} />

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

      {/* Fallback: paid but not activated (e.g. closed popup before callback fired) */}
      <div className="card border-dashed">
        <div className="flex items-center gap-3">
          <RefreshCw size={16} className="text-slate-500" />
          <p className="text-sm text-slate-400 flex-1">Paid but plan not activated?</p>
          <button onClick={load} className="btn-ghost text-xs text-brand-400">
            <RefreshCw size={13} /> Refresh status
          </button>
        </div>
      </div>
    </div>
  )
}

function PlanModuleList({ slug }: { slug: string }) {
  const [expanded, setExpanded] = useState(false)
  const key = slug as keyof Pick<ModuleRow, 'starter' | 'professional' | 'business'>
  const validKey = ['starter', 'professional', 'business'].includes(key) ? key : 'starter'

  const SHOW_INITIAL = 8
  const visible = expanded ? MODULE_ROWS : MODULE_ROWS.slice(0, SHOW_INITIAL)

  return (
    <div className="space-y-1 flex-1">
      {visible.map((row) => {
        const val = row[validKey as 'starter' | 'professional' | 'business']
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
