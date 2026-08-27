import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import AudityLogo from '@/components/AudityLogo'
import {
  ChevronRight, Sparkles, Check, Loader2,
  Clock, ArrowLeft, Package, Users, Receipt,
  BarChart3, Calculator, Briefcase, Shield, CheckCircle2,
  Zap, GraduationCap, Building2, Star, ExternalLink,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { api, orgApi, subscriptionApi, partnerApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'

// ─── Constants ────────────────────────────────────────────────────────────────

const ACCOUNT_TYPES = [
  { value: 'business', label: 'Business', desc: 'Company, distributor, or retailer' },
  { value: 'personal', label: 'Personal', desc: 'Sole trader or individual' },
]

const PRESETS = [
  { country: 'NG', currency: 'NGN', flag: '🇳🇬', label: 'Nigeria' },
  { country: 'GH', currency: 'GHS', flag: '🇬🇭', label: 'Ghana' },
  { country: 'KE', currency: 'KES', flag: '🇰🇪', label: 'Kenya' },
  { country: 'ZA', currency: 'ZAR', flag: '🇿🇦', label: 'South Africa' },
  { country: 'US', currency: 'USD', flag: '🇺🇸', label: 'United States' },
  { country: 'GB', currency: 'GBP', flag: '🇬🇧', label: 'United Kingdom' },
]

// Questionnaire — includes partner routing question at position 0
const QUESTIONS = [
  {
    key: 'manages_clients',
    emoji: '🏢',
    label: 'Do you manage accounting or finances for other businesses?',
    sub: 'As an accountant, bookkeeper, or financial consultant.',
    options: [
      'Yes — I manage accounts for multiple clients',
      'No — I manage my own business only',
    ],
  },
  {
    key: 'business_type',
    emoji: '🏪',
    label: 'What kind of business do you run?',
    sub: 'This helps us tailor your experience.',
    options: ['Retail / Shop', 'Wholesale / Distribution', 'Services', 'Manufacturing', 'E-commerce', 'Other'],
  },
  {
    key: 'has_inventory',
    emoji: '📦',
    label: 'Do you manage physical stock or inventory?',
    sub: 'Products you buy, store, and sell.',
    options: ['Yes — I track stock levels', 'Sometimes', 'No — I sell services only'],
  },
  {
    key: 'team_size',
    emoji: '👥',
    label: 'How many people will use Audity?',
    sub: 'You can always add more later.',
    options: ['Just me', '2–5 people', '6–15 people', 'More than 15'],
  },
  {
    key: 'monthly_transactions',
    emoji: '📊',
    label: 'How many sales or invoices do you process monthly?',
    sub: 'Rough estimate is fine.',
    options: ['Under 20', '20–100', '100–500', 'Over 500'],
  },
  {
    key: 'priority_feature',
    emoji: '🎯',
    label: 'What matters most to you right now?',
    sub: 'Pick everything that applies.',
    options: ['Invoicing & Sales', 'Inventory & Stock', 'Payroll & HR', 'Accounting & Ledger', 'Tax & Compliance', 'Financial Reports'],
    multi: true,
  },
]

const PARTNER_TIERS = [
  {
    slug: 'starter',
    name: 'Starter Partner',
    icon: Star,
    color: 'border-slate-500/50',
    ring: 'ring-slate-500/30',
    pill: 'bg-slate-500/15 text-slate-300',
    tagline: 'Perfect for solo bookkeepers and new firms.',
    perks: [
      'Manage up to 5 client accounts',
      '20% commission on client subscriptions',
      'Partner portal & client dashboard',
      'Standard support',
    ],
  },
  {
    slug: 'pro',
    name: 'Pro Partner',
    icon: GraduationCap,
    color: 'border-brand-500/60',
    ring: 'ring-brand-500/30',
    pill: 'bg-brand-500/15 text-brand-300',
    tagline: 'For growing accounting practices.',
    perks: [
      'Manage up to 25 client accounts',
      '30% commission on client subscriptions',
      'White-label client reports',
      'Dedicated partner manager',
      'Priority support',
    ],
    recommended: true,
  },
  {
    slug: 'agency',
    name: 'Agency Partner',
    icon: Building2,
    color: 'border-purple-500/40',
    ring: 'ring-purple-500/30',
    pill: 'bg-purple-500/15 text-purple-300',
    tagline: 'For large firms managing many clients.',
    perks: [
      'Unlimited client accounts',
      '35% commission on client subscriptions',
      'Custom white-label branding',
      'API access for integrations',
      'SLA + dedicated support',
    ],
  },
]

interface Plan {
  id: string
  name: string
  slug: string
  description: string
  price: string
  interval: string
  features: Record<string, unknown>
  is_free: boolean
}

interface Recommendation {
  recommended_plan_slug: string
  confidence: string
  reasons: string[]
  alternative_plan_slug: string
  alternative_reasons: string[]
  plans: Plan[]
}

const PLAN_META: Record<string, {
  highlights: { icon: React.ElementType; text: string }[]
  color: { border: string; ring: string; pill: string }
  tagline: string
}> = {
  free: {
    tagline: 'Get a feel for Audity. No card needed.',
    highlights: [
      { icon: Receipt, text: '10 invoices / month' },
      { icon: Package, text: 'Up to 20 products & customers' },
      { icon: Users, text: 'Solo use only' },
      { icon: BarChart3, text: 'Basic reports + VAT only' },
    ],
    color: { border: 'border-surface-600', ring: '', pill: 'bg-emerald-500/15 text-emerald-400' },
  },
  professional: {
    tagline: 'Everything a growing business needs.',
    highlights: [
      { icon: Receipt, text: 'Unlimited invoicing, quotes & POs' },
      { icon: Package, text: 'Up to 500 products' },
      { icon: Users, text: 'Up to 5 team members' },
      { icon: BarChart3, text: 'Advanced reports + audit log' },
      { icon: Calculator, text: 'VAT + Income Tax engine' },
      { icon: Shield, text: 'Budget planning + recurring invoices' },
    ],
    color: { border: 'border-brand-500/60', ring: 'ring-2 ring-brand-500/30', pill: 'bg-brand-500/15 text-brand-300' },
  },
  business: {
    tagline: 'Full operations suite for established businesses.',
    highlights: [
      { icon: Receipt, text: 'Unlimited invoicing, quotes & POs' },
      { icon: Package, text: 'Unlimited products & warehouses' },
      { icon: Users, text: 'Unlimited team members' },
      { icon: Briefcase, text: 'Payroll, HR & full accounting ledger' },
      { icon: Calculator, text: 'Full tax engine (WHT, Excise, Filing)' },
      { icon: Shield, text: 'Owner analytics + API access (read)' },
    ],
    color: { border: 'border-purple-500/40', ring: '', pill: 'bg-purple-500/15 text-purple-300' },
  },
  enterprise: {
    tagline: 'Custom scale — white-label, API & multi-entity.',
    highlights: [
      { icon: Receipt, text: 'Everything in Business' },
      { icon: Zap, text: 'Full read/write API + webhooks' },
      { icon: Shield, text: 'White-label branding & custom domain' },
      { icon: Briefcase, text: 'Multi-entity management' },
      { icon: Users, text: 'Custom roles + SSO' },
      { icon: BarChart3, text: 'Dedicated support & onboarding' },
    ],
    color: { border: 'border-amber-500/40', ring: '', pill: 'bg-amber-500/15 text-amber-300' },
  },
}

// ─── Progress bar ──────────────────────────────────────────────────────────────
function ProgressBar({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-surface-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-brand-500 rounded-full transition-all duration-500"
          style={{ width: `${((current + 1) / total) * 100}%` }}
        />
      </div>
      <span className="text-xs text-slate-500 shrink-0">{current + 1} / {total}</span>
    </div>
  )
}

// ─── Main Component ────────────────────────────────────────────────────────────
export default function OnboardingPage() {
  const navigate = useNavigate()
  const { user, organisation, orgInitialized, setOrganisation } = useAuthStore()
  const [trialUsed, setTrialUsed] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Snapshot whether the user already had an org when this page first mounted.
  // Used to distinguish "existing user landed here erroneously" (had org at mount →
  // redirect to dashboard) from "new user created org in step 0" (no org at mount →
  // must not redirect mid-flow when the org is created in handleCreateOrg).
  const hadOrgAtMount = useRef(!!organisation?.id)

  // Escape hatch: redirect to dashboard if:
  //   1. User is a sub-account (they never need onboarding), OR
  //   2. Org was present at mount AND orgInitialized — covers both:
  //      a) Normal: onboarding_completed=true after completing the flow
  //      b) Pre-migration users stuck with onboarding_completed=false but a real org
  // Does NOT fire when the org is freshly created in step 0 (hadOrgAtMount=false).
  useEffect(() => {
    if (user?.is_sub_account) { navigate('/dashboard', { replace: true }); return }
    if (orgInitialized && hadOrgAtMount.current) { navigate('/dashboard', { replace: true }); return }
  }, [user?.is_sub_account, orgInitialized])

  // Step 0: workspace, 1: questionnaire, 2: plan selection, 3: partner enrollment
  const [step, setStep] = useState(0)
  const [qIndex, setQIndex] = useState(0)

  // Step 0
  const [orgForm, setOrgForm] = useState({ name: '', account_type: 'business', country: 'NG', currency: 'NGN' })
  const [orgSaving, setOrgSaving] = useState(false)

  // Step 1
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({})

  // Step 2 (plan selection)
  const [loadingRec, setLoadingRec] = useState(false)
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null)
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null)
  const [initiatingPay, setInitiatingPay] = useState(false)
  const [billing, setBilling] = useState<'monthly' | 'annual'>('monthly')

  // Step 3 (partner enrollment)
  const [selectedPartnerTier, setSelectedPartnerTier] = useState<string>('pro')
  const [firmName, setFirmName] = useState('')
  const [partnerSaving, setPartnerSaving] = useState(false)

  const isPartnerFlow = answers['manages_clients'] === 'Yes — I manage accounts for multiple clients'

  // If org already exists (resumed session), show questionnaire rather than
  // jumping to plan selection — users should always go through the AI matching
  // questions to get a meaningful recommendation.
  useEffect(() => {
    if (organisation?.id) {
      setStep(1)
      // Check if org already used a trial (trial_end set on existing subscription)
      subscriptionApi.current().then(({ data }) => {
        if (data?.trial_end) setTrialUsed(true)
      }).catch(() => {})
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  // ── Step 0 ──────────────────────────────────────────────────────────────────
  const handleCreateOrg = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!orgForm.name.trim()) { toast.error('Organisation name is required'); return }
    setOrgSaving(true)
    try {
      const { data } = await orgApi.create(orgForm)
      setOrganisation(data)
      api.defaults.headers.common['X-Organisation-ID'] = data.id
      setStep(1)
    } catch (err: any) {
      if (!err.response) { toast.error('Cannot connect to server. Check your connection.'); return }
      const apiErr = err.response?.data?.error
      const detail = apiErr?.detail
      const msg = typeof detail === 'object' && detail
        ? Object.values(detail).flat().join(' ')
        : (typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? `Server error (${err.response.status}). Please try again.`))
      toast.error(msg)
    } finally {
      setOrgSaving(false)
    }
  }

  const handleBackFromOnboarding = () => {
    useAuthStore.getState().logout()
    navigate('/login')
  }

  // ── Step 1: One question at a time ──────────────────────────────────────────
  const currentQ = QUESTIONS[qIndex]

  const toggleAnswer = (key: string, opt: string, multi?: boolean) => {
    if (!multi) {
      setAnswers((a) => ({ ...a, [key]: opt }))
    } else {
      setAnswers((a) => {
        const current = (a[key] as string[] | undefined) ?? []
        const next = current.includes(opt) ? current.filter((v) => v !== opt) : [...current, opt]
        return { ...a, [key]: next }
      })
    }
  }

  const isSelected = (key: string, opt: string) => {
    const val = answers[key]
    return Array.isArray(val) ? val.includes(opt) : val === opt
  }

  const currentAnswered = () => {
    const val = answers[currentQ.key]
    return Array.isArray(val) ? val.length > 0 : !!val
  }

  const handleNext = () => {
    // After the first question (manages_clients), if they are a partner flow,
    // skip the remaining business questions and go straight to the partner step.
    if (currentQ.key === 'manages_clients' && isPartnerFlow) {
      setStep(3)
      return
    }
    if (qIndex < QUESTIONS.length - 1) {
      setQIndex((i) => i + 1)
    } else {
      handleGetRecommendation()
    }
  }

  const handleBack = () => {
    if (qIndex > 0) setQIndex((i) => i - 1)
    else setStep(0)
  }

  // ── Get recommendation ──────────────────────────────────────────────────────
  const handleGetRecommendation = async () => {
    setLoadingRec(true)
    setStep(2)
    const serialized = Object.fromEntries(
      Object.entries(answers).map(([k, v]) => [k, Array.isArray(v) ? v.join(', ') : v])
    )
    try {
      const { data } = await subscriptionApi.recommendPlan(serialized)
      setRecommendation(data)
      const rec = data.plans.find((p: Plan) => p.slug === data.recommended_plan_slug) ?? data.plans[0]
      setSelectedPlan(rec)
    } catch {
      try {
        const { data } = await subscriptionApi.plans()
        const plans = data.results ?? data
        setRecommendation({ recommended_plan_slug: '', confidence: '', reasons: [], alternative_plan_slug: '', alternative_reasons: [], plans })
        setSelectedPlan(plans.find((p: Plan) => p.slug === 'professional') ?? plans[0] ?? null)
      } catch {
        toast.error('Failed to load plans.')
        setStep(1)
      }
    } finally {
      setLoadingRec(false)
    }
  }

  // ── Mark onboarding complete ─────────────────────────────────────────────────
  const markOnboardingComplete = async () => {
    const orgId = organisation?.id
    if (!orgId) return
    try {
      const updated = await orgApi.update(orgId, { onboarding_completed: true })
      setOrganisation(updated.data)
    } catch { /* non-fatal */ }
  }

  // ── Start trial ─────────────────────────────────────────────────────────────
  const handleSelectAndPay = async (plan: Plan) => {
    setSelectedPlan(plan)
    setInitiatingPay(true)
    let trialStarted = false
    try {
      await subscriptionApi.startTrial(plan.id, organisation?.id)
      trialStarted = true
    } catch (err: any) {
      // Trial start failure is non-fatal — the user can select a plan from Settings later.
      // We still mark onboarding complete so they aren't stuck in this loop forever.
      const msg = err?.response?.data?.error?.message ?? err?.response?.data?.error ?? null
      if (msg && typeof msg === 'string') toast.error(msg)
    }
    // Always mark onboarding complete regardless of whether trial start succeeded.
    // This is the only call that breaks the onboarding loop.
    await markOnboardingComplete()
    if (trialStarted) {
      toast.success(plan.is_free ? 'Welcome to Audity! No card needed.' : `${plan.name} trial started — 30 days free!`)
    } else if (!trialStarted) {
      toast.success('Welcome to Audity! Set up your plan from Settings any time.')
    }
    navigate('/dashboard')
    setInitiatingPay(false)
  }

  // ── Partner enrollment ───────────────────────────────────────────────────────
  // Maps partner tier slug → the plan the partner gets for their own workspace
  const PARTNER_TIER_PLANS: Record<string, string> = {
    starter: 'partner-starter',
    pro: 'partner-pro',
    agency: 'partner-agency',
  }

  const handlePartnerEnroll = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!firmName.trim()) { toast.error('Please enter your firm or practice name.'); return }
    setPartnerSaving(true)
    try {
      await partnerApi.updateProfile({ tier: selectedPartnerTier, firm_name: firmName })

      // Assign the plan that matches the selected partner tier
      const targetSlug = PARTNER_TIER_PLANS[selectedPartnerTier] ?? 'professional'
      try {
        const { data } = await subscriptionApi.plans()
        const plans: Plan[] = data.results ?? data
        const targetPlan = plans.find((p) => p.slug === targetSlug)
        if (targetPlan) {
          await subscriptionApi.startTrial(targetPlan.id, organisation?.id)
        }
      } catch {
        // Non-fatal — user can set plan from Settings
      }

      await markOnboardingComplete()
      toast.success('Welcome to the Audity Partner Program! 🎉')
      navigate('/partner')
    } catch (err: any) {
      // If partner profile endpoint doesn't exist yet, fall through gracefully
      const status = err?.response?.status
      if (status === 404 || status === 405) {
        await markOnboardingComplete()
        toast.success('Welcome to Audity! Your partner application has been noted.')
        navigate('/dashboard')
      } else {
        const msg = err?.response?.data?.error?.message ?? err?.response?.data?.error ?? 'Could not enroll. Please try again.'
        toast.error(typeof msg === 'string' ? msg : 'Could not enroll. Please try again.')
      }
    } finally {
      setPartnerSaving(false)
    }
  }

  // ── Dynamic container width ─────────────────────────────────────────────────
  // Step 2 plan cards need a wide layout; all other steps are narrow (max-w-2xl)
  const containerWidth = (step === 2 && !loadingRec && recommendation)
    ? 'max-w-5xl'
    : (step === 3 ? 'max-w-4xl' : 'max-w-2xl')

  // ─── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-surface-950 flex items-center justify-center p-6">
      <div className={`w-full ${containerWidth} space-y-6 transition-all duration-300`}>

        {/* Logo */}
        <AudityLogo className="h-10 w-auto" />

        {/* ── Step 0: Workspace setup ── */}
        {step === 0 && (
          <div className="card space-y-6">
            <div className="space-y-1">
              <h2 className="text-2xl font-bold text-white">
                {user?.first_name ? `Welcome, ${user.first_name}! 👋` : 'Welcome! 👋'}
              </h2>
              <p className="text-slate-400 text-sm">Let's get your workspace ready in under a minute.</p>
            </div>

            <form onSubmit={handleCreateOrg} className="space-y-5">
              <div>
                <label className="label">What's your business called?</label>
                <input
                  className="input text-base"
                  placeholder="e.g., Ola Liquor Distributors Ltd"
                  value={orgForm.name}
                  onChange={(e) => setOrgForm((f) => ({ ...f, name: e.target.value }))}
                  required
                  autoFocus
                />
              </div>

              <div>
                <label className="label">Account type</label>
                <div className="grid grid-cols-2 gap-3">
                  {ACCOUNT_TYPES.map((t) => (
                    <button
                      key={t.value}
                      type="button"
                      onClick={() => setOrgForm((f) => ({ ...f, account_type: t.value }))}
                      className={`p-3.5 rounded-xl border text-left transition-all ${
                        orgForm.account_type === t.value
                          ? 'bg-brand-500/15 border-brand-500 text-white'
                          : 'border-surface-600 text-slate-400 hover:border-surface-500'
                      }`}
                    >
                      <p className="font-semibold text-sm">{t.label}</p>
                      <p className="text-xs mt-0.5 opacity-75">{t.desc}</p>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="label">Where are you based?</label>
                <div className="grid grid-cols-3 gap-2">
                  {PRESETS.map((p) => (
                    <button
                      key={p.country}
                      type="button"
                      onClick={() => setOrgForm((f) => ({ ...f, country: p.country, currency: p.currency }))}
                      className={`py-2.5 px-3 rounded-xl border text-xs font-medium flex items-center gap-2 transition-all ${
                        orgForm.country === p.country
                          ? 'bg-brand-500/15 border-brand-500 text-white'
                          : 'border-surface-600 text-slate-400 hover:border-surface-500'
                      }`}
                    >
                      <span className="text-base">{p.flag}</span>
                      <span className="truncate">{p.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              <button
                type="submit"
                disabled={orgSaving || !orgForm.name.trim()}
                className="btn-primary w-full justify-center py-3 disabled:opacity-50"
              >
                {orgSaving
                  ? <><Loader2 size={16} className="animate-spin" /> Creating workspace…</>
                  : <span className="flex items-center gap-2">Continue <ChevronRight size={16} /></span>
                }
              </button>

              <button
                type="button"
                onClick={handleBackFromOnboarding}
                className="flex items-center justify-center gap-1.5 w-full text-sm text-slate-500 hover:text-slate-300 transition-colors pt-1"
              >
                <ArrowLeft size={14} /> Sign out / use a different account
              </button>
            </form>
          </div>
        )}

        {/* ── Step 1: One question at a time ── */}
        {step === 1 && (
          <div className="card space-y-6">
            {/* Progress — only count non-partner questions if in partner flow */}
            <ProgressBar current={qIndex} total={QUESTIONS.length} />

            {/* Question */}
            <div className="space-y-2 text-center py-2">
              <span className="text-4xl">{currentQ.emoji}</span>
              <h2 className="text-xl font-bold text-white mt-2">{currentQ.label}</h2>
              <p className="text-slate-400 text-sm">{currentQ.sub}</p>
              {currentQ.multi && <p className="text-xs text-brand-400">Select all that apply</p>}
            </div>

            {/* Options */}
            <div className="grid grid-cols-2 gap-2.5">
              {currentQ.options.map((opt) => {
                const sel = isSelected(currentQ.key, opt)
                return (
                  <button
                    key={opt}
                    type="button"
                    onClick={() => toggleAnswer(currentQ.key, opt, currentQ.multi)}
                    className={`p-3.5 rounded-xl border text-sm font-medium text-left transition-all flex items-center gap-2 ${
                      sel
                        ? 'bg-brand-500/20 border-brand-500 text-white'
                        : 'border-surface-600 text-slate-300 hover:border-surface-500 hover:text-white'
                    }`}
                  >
                    <span className={`w-4 h-4 rounded-full border-2 flex-shrink-0 flex items-center justify-center transition-all ${
                      sel ? 'bg-brand-500 border-brand-500' : 'border-slate-600'
                    }`}>
                      {sel && <Check size={10} className="text-white" />}
                    </span>
                    {opt}
                  </button>
                )
              })}
            </div>

            {/* Nav */}
            <div className="flex items-center gap-3 pt-1">
              <button
                onClick={handleBack}
                className="flex items-center gap-1 text-sm text-slate-500 hover:text-slate-300 transition-colors"
              >
                <ArrowLeft size={14} /> Back
              </button>
              <button
                onClick={handleNext}
                disabled={!currentAnswered()}
                className="btn-primary flex-1 justify-center py-3 disabled:opacity-40"
              >
                {/* If partner question answered "Yes", show partner CTA */}
                {currentQ.key === 'manages_clients' && isPartnerFlow ? (
                  <span className="flex items-center gap-2"><GraduationCap size={16} /> Set up partner account</span>
                ) : qIndex < QUESTIONS.length - 1 ? (
                  <span className="flex items-center gap-2">Next <ChevronRight size={16} /></span>
                ) : (
                  <span className="flex items-center gap-2"><Sparkles size={16} /> Get my recommendation</span>
                )}
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: Loading ── */}
        {step === 2 && loadingRec && (
          <div className="card flex flex-col items-center gap-5 py-16 text-center">
            <div className="w-16 h-16 bg-brand-500/15 rounded-full flex items-center justify-center">
              <Sparkles size={28} className="text-brand-400 animate-pulse" />
            </div>
            <p className="text-white font-bold text-lg">Finding the right plan for you…</p>
            <Loader2 size={22} className="text-brand-400 animate-spin" />
          </div>
        )}

        {/* ── Step 2: Plan selection ── */}
        {step === 2 && !loadingRec && recommendation && (() => {
          const bySlug = Object.fromEntries(recommendation.plans.map(p => [p.slug, p]))

          const columns: Array<{ slug: string; annualSlug: string | null }> = [
            { slug: 'free',         annualSlug: null },
            { slug: 'professional', annualSlug: 'professional-annual' },
            { slug: 'business',     annualSlug: 'business-annual' },
            { slug: 'enterprise',   annualSlug: 'enterprise-annual' },
          ]

          return (
            <div className="space-y-6 w-full">
              {/* AI summary */}
              {recommendation.reasons.length > 0 && (
                <div className="rounded-2xl border border-brand-500/30 bg-brand-500/5 px-5 py-4 space-y-2">
                  <div className="flex items-center gap-2">
                    <Sparkles size={14} className="text-brand-400" />
                    <span className="text-brand-300 font-semibold text-sm">AI recommendation</span>
                    {recommendation.confidence && (
                      <span className="ml-auto text-xs text-slate-500 capitalize">{recommendation.confidence} confidence</span>
                    )}
                  </div>
                  <ul className="space-y-1">
                    {recommendation.reasons.map((r, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-slate-300">
                        <CheckCircle2 size={13} className="text-brand-400 mt-0.5 shrink-0" />
                        {r}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Billing toggle */}
              <div className="flex items-center justify-center gap-1 p-1 bg-surface-800 rounded-xl w-fit mx-auto">
                <button
                  onClick={() => setBilling('monthly')}
                  className={`px-5 py-2 rounded-lg text-sm font-medium transition-all ${
                    billing === 'monthly' ? 'bg-surface-600 text-white shadow' : 'text-slate-400 hover:text-white'
                  }`}
                >Monthly</button>
                <button
                  onClick={() => setBilling('annual')}
                  className={`px-5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 ${
                    billing === 'annual' ? 'bg-surface-600 text-white shadow' : 'text-slate-400 hover:text-white'
                  }`}
                >
                  Annual
                  <span className="text-xs bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded-full font-semibold">1 month free</span>
                </button>
              </div>

              {/* Plan cards — 4 equal columns filling the available width */}
              <div className="grid grid-cols-4 gap-4">
                {columns.map(({ slug, annualSlug }) => {
                  const annualPlan = annualSlug ? bySlug[annualSlug] : null
                  const monthlyPlan = bySlug[slug]
                  if (!monthlyPlan && !annualPlan) return null

                  const activePlan = (billing === 'annual' && annualPlan) ? annualPlan : (monthlyPlan ?? annualPlan!)
                  const metaKey = slug.replace('-annual', '')
                  const meta = PLAN_META[metaKey] ?? PLAN_META.free
                  const isSel = selectedPlan?.id === activePlan.id
                  const isRec = activePlan.slug === recommendation.recommended_plan_slug ||
                                monthlyPlan?.slug === recommendation.recommended_plan_slug

                  const price = parseFloat(activePlan.price)
                  const isAnnualVariant = billing === 'annual' && !!annualPlan && !activePlan.is_free
                  const perMonth = isAnnualVariant ? Math.round(price / 12) : price

                  return (
                    <div
                      key={slug}
                      onClick={() => setSelectedPlan(activePlan)}
                      className={`relative flex flex-col rounded-2xl border p-5 gap-4 cursor-pointer transition-all ${meta.color.border} ${
                        isSel ? `${meta.color.ring} ring-2 bg-white/5` : 'hover:bg-white/[0.03] bg-surface-800/40'
                      }`}
                    >
                      {isRec && (
                        <span className="absolute -top-3 left-1/2 -translate-x-1/2 whitespace-nowrap text-xs font-bold px-3 py-1 rounded-full text-white bg-brand-500">
                          ⭐ Recommended
                        </span>
                      )}

                      {/* Header */}
                      <div className="flex items-start justify-between mt-1 gap-2">
                        <div>
                          <p className="text-white font-bold text-base leading-tight">{monthlyPlan?.name ?? activePlan.name}</p>
                          <p className="text-slate-500 text-xs mt-1 leading-snug">{meta.tagline}</p>
                        </div>
                        <div className={`w-5 h-5 rounded-full border-2 flex-shrink-0 flex items-center justify-center transition-all mt-0.5 ${
                          isSel ? 'bg-brand-500 border-brand-500' : 'border-slate-600'
                        }`}>
                          {isSel && <Check size={10} className="text-white" />}
                        </div>
                      </div>

                      {/* Price */}
                      <div>
                        {activePlan.is_free ? (
                          <div className="flex items-end gap-1">
                            <span className="text-3xl font-extrabold text-white">Free</span>
                            <span className="text-emerald-400 text-xs pb-1 font-medium">forever</span>
                          </div>
                        ) : (
                          <>
                            <div className="flex items-end gap-1">
                              <span className="text-3xl font-extrabold text-white">
                                ₦{perMonth.toLocaleString('en-NG')}
                              </span>
                              <span className="text-slate-400 text-sm pb-1">/mo</span>
                            </div>
                            {isAnnualVariant && (
                              <p className="text-xs text-emerald-400 mt-0.5">
                                ₦{price.toLocaleString('en-NG')} billed annually
                              </p>
                            )}
                          </>
                        )}
                      </div>

                      {/* Features */}
                      <div className="space-y-2.5 flex-1">
                        {meta.highlights.map(({ icon: Icon, text }) => (
                          <div key={text} className="flex items-center gap-2 text-xs text-slate-300">
                            <Icon size={12} className="text-brand-400 shrink-0" />
                            {text}
                          </div>
                        ))}
                      </div>

                      {/* Plan badge */}
                      <div className={`text-xs font-medium px-3 py-1.5 rounded-lg text-center ${meta.color.pill}`}>
                        {activePlan.is_free ? 'No card needed' : trialUsed ? 'Subscribe directly' : '30-day free trial'}
                      </div>
                    </div>
                  )
                })}
              </div>

              {/* CTA */}
              <button
                disabled={!selectedPlan || initiatingPay}
                onClick={() => selectedPlan && handleSelectAndPay(selectedPlan)}
                className="btn-primary w-full justify-center py-3.5 text-base disabled:opacity-40"
              >
                {initiatingPay ? (
                  <><Loader2 size={16} className="animate-spin" /> Setting things up…</>
                ) : selectedPlan?.is_free ? (
                  <span className="flex items-center gap-2"><Zap size={17} /> Start for free — no card needed</span>
                ) : trialUsed ? (
                  <span className="flex items-center gap-2"><ExternalLink size={17} /> Subscribe to {selectedPlan?.name ?? 'plan'}</span>
                ) : (
                  <span className="flex items-center gap-2"><Clock size={17} /> Start my 30-day free trial</span>
                )}
              </button>

              {!selectedPlan?.is_free && (
                <p className="text-center text-xs text-slate-500">
                  {trialUsed
                    ? 'You have already used your free trial. Subscribe to continue.'
                    : 'Full access for 30 days. No card required upfront. Cancel anytime.'}
                </p>
              )}

              <div className="flex items-center justify-between text-sm">
                <button
                  onClick={() => { setStep(1); setQIndex(QUESTIONS.length - 1) }}
                  className="text-slate-500 hover:text-slate-400 flex items-center gap-1"
                >
                  <ArrowLeft size={13} /> Change answers
                </button>
                <button
                  onClick={async () => { await markOnboardingComplete(); navigate('/dashboard') }}
                  className="text-slate-600 hover:text-slate-400"
                >
                  Skip for now →
                </button>
              </div>
            </div>
          )
        })()}

        {/* ── Step 3: Partner enrollment ── */}
        {step === 3 && (
          <div className="space-y-6 w-full">
            {/* Header */}
            <div className="text-center space-y-2">
              <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-brand-500/15 mb-2">
                <GraduationCap size={28} className="text-brand-400" />
              </div>
              <h2 className="text-2xl font-bold text-white">Join the Audity Partner Program</h2>
              <p className="text-slate-400 text-sm max-w-lg mx-auto">
                Manage your clients' books in one place. Earn commissions. Grow your practice with white-label reports and a dedicated partner portal.
              </p>
            </div>

            {/* Partner tier cards */}
            <div className="grid grid-cols-3 gap-4">
              {PARTNER_TIERS.map((tier) => {
                const isSel = selectedPartnerTier === tier.slug
                const Icon = tier.icon
                return (
                  <div
                    key={tier.slug}
                    onClick={() => setSelectedPartnerTier(tier.slug)}
                    className={`relative flex flex-col rounded-2xl border p-5 gap-4 cursor-pointer transition-all ${tier.color} ${
                      isSel ? `ring-2 ${tier.ring} bg-white/5` : 'hover:bg-white/[0.03] bg-surface-800/40'
                    }`}
                  >
                    {tier.recommended && (
                      <span className="absolute -top-3 left-1/2 -translate-x-1/2 whitespace-nowrap text-xs font-bold px-3 py-1 rounded-full text-white bg-brand-500">
                        Most popular
                      </span>
                    )}

                    <div className="flex items-start justify-between mt-1">
                      <div className="flex items-center gap-2.5">
                        <div className="w-9 h-9 bg-surface-700 rounded-xl flex items-center justify-center shrink-0">
                          <Icon size={18} className="text-brand-400" />
                        </div>
                        <div>
                          <p className="text-white font-bold text-sm">{tier.name}</p>
                          <p className="text-slate-500 text-xs mt-0.5">{tier.tagline}</p>
                        </div>
                      </div>
                      <div className={`w-5 h-5 rounded-full border-2 flex-shrink-0 flex items-center justify-center transition-all ${
                        isSel ? 'bg-brand-500 border-brand-500' : 'border-slate-600'
                      }`}>
                        {isSel && <Check size={10} className="text-white" />}
                      </div>
                    </div>

                    <div className="space-y-2 flex-1">
                      {tier.perks.map((perk) => (
                        <div key={perk} className="flex items-start gap-2 text-xs text-slate-300">
                          <CheckCircle2 size={12} className="text-brand-400 mt-0.5 shrink-0" />
                          {perk}
                        </div>
                      ))}
                    </div>

                    <div className={`text-xs font-medium px-3 py-1.5 rounded-lg text-center ${tier.pill}`}>
                      Free to join
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Firm name + CTA */}
            <form onSubmit={handlePartnerEnroll} className="max-w-md mx-auto space-y-4">
              <div>
                <label className="label">Your firm or practice name</label>
                <input
                  className="input"
                  placeholder="e.g., Bright Accounts & Tax Services"
                  value={firmName}
                  onChange={(e) => setFirmName(e.target.value)}
                  required
                  autoFocus
                />
              </div>

              <button
                type="submit"
                disabled={partnerSaving || !firmName.trim()}
                className="btn-primary w-full justify-center py-3 disabled:opacity-50"
              >
                {partnerSaving
                  ? <><Loader2 size={16} className="animate-spin" /> Enrolling…</>
                  : <span className="flex items-center gap-2"><GraduationCap size={16} /> Enroll as Partner</span>
                }
              </button>
            </form>

            <div className="flex items-center justify-between text-sm max-w-md mx-auto">
              <button
                onClick={() => { setStep(1); setQIndex(0) }}
                className="text-slate-500 hover:text-slate-400 flex items-center gap-1"
              >
                <ArrowLeft size={13} /> Back
              </button>
              <button
                onClick={async () => { await markOnboardingComplete(); navigate('/dashboard') }}
                className="text-slate-600 hover:text-slate-400"
              >
                Skip for now →
              </button>
            </div>
          </div>
        )}

        <p className="text-center text-xs text-slate-600">
          You can switch plans or invite team members any time from Settings.
        </p>
      </div>
    </div>
  )
}
