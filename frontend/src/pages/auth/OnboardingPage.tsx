import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import AudityLogo from '@/components/AudityLogo'
import {
  ChevronRight, Sparkles, Check, Loader2,
  Clock, ArrowLeft, Package, Users, Receipt,
  BarChart3, Calculator, Briefcase, Shield, CheckCircle2,
  Zap,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { orgApi, subscriptionApi } from '@/services/api'
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

// Focused set of questions — only what's needed for a good recommendation
const QUESTIONS = [
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
  const { user, organisation, setOrganisation } = useAuthStore()
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (user?.is_sub_account) navigate('/dashboard', { replace: true })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.is_sub_account])

  // Step 0: workspace, 1: questionnaire (one-at-a-time), 2: plan selection
  const [step, setStep] = useState(0)
  const [qIndex, setQIndex] = useState(0)   // which question we're on in step 1

  // Step 0
  const [orgForm, setOrgForm] = useState({ name: '', account_type: 'business', country: 'NG', currency: 'NGN' })
  const [orgSaving, setOrgSaving] = useState(false)

  // Step 1
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({})

  // Step 2
  const [loadingRec, setLoadingRec] = useState(false)
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null)
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null)
  const [initiatingPay, setInitiatingPay] = useState(false)
  const [billing, setBilling] = useState<'monthly' | 'annual'>('monthly')

  // If org already exists skip to plan step
  useEffect(() => {
    if (organisation?.id) {
      setStep(2)
      setLoadingRec(true)
      subscriptionApi.plans()
        .then(({ data }) => {
          const plans = data.results ?? data
          setRecommendation({ recommended_plan_slug: '', confidence: '', reasons: [], alternative_plan_slug: '', alternative_reasons: [], plans })
          setSelectedPlan(plans.find((p: Plan) => p.slug === 'professional') ?? plans[0] ?? null)
        })
        .catch(() => toast.error('Could not load plans.'))
        .finally(() => setLoadingRec(false))
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Step 0 ──────────────────────────────────────────────────────────────────
  const handleCreateOrg = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!orgForm.name.trim()) { toast.error('Organisation name is required'); return }
    setOrgSaving(true)
    try {
      const { data } = await orgApi.create(orgForm)
      setOrganisation(data)
      setStep(1)
    } catch (err: any) {
      if (!err.response) { toast.error('Cannot connect to server.'); return }
      const detail = err.response?.data?.error?.detail
      const msg = typeof detail === 'object' && detail
        ? Object.values(detail).flat().join(' ')
        : (err.response?.data?.error?.message ?? 'Failed to create organisation.')
      toast.error(msg)
    } finally {
      setOrgSaving(false)
    }
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

  // ── Start trial ─────────────────────────────────────────────────────────────
  const markOnboardingComplete = async () => {
    const orgId = organisation?.id
    if (!orgId) return
    try {
      const updated = await orgApi.update(orgId, { onboarding_completed: true })
      setOrganisation(updated.data)
    } catch { /* non-fatal */ }
  }

  const handleSelectAndPay = async (plan: Plan) => {
    setSelectedPlan(plan)
    setInitiatingPay(true)
    try {
      await subscriptionApi.startTrial(plan.id)
      await markOnboardingComplete()
      if (plan.is_free) {
        toast.success('Welcome to Audity! No card needed.')
      } else {
        toast.success(`${plan.name} trial started — 14 days free!`)
      }
      navigate('/dashboard')
    } catch (err: any) {
      const msg = err?.response?.data?.error?.message ?? err?.response?.data?.error ?? 'Could not start. Please try again.'
      toast.error(typeof msg === 'string' ? msg : 'Could not start. Please try again.')
    } finally {
      setInitiatingPay(false)
    }
  }

  // ─── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-surface-950 flex items-center justify-center p-6">
      <div className="w-full max-w-2xl space-y-6">

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
            </form>
          </div>
        )}

        {/* ── Step 1: One question at a time ── */}
        {step === 1 && (
          <div className="card space-y-6">
            {/* Progress */}
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
                {qIndex < QUESTIONS.length - 1
                  ? <span className="flex items-center gap-2">Next <ChevronRight size={16} /></span>
                  : <span className="flex items-center gap-2"><Sparkles size={16} /> Get my recommendation</span>
                }
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
          // Build a slug → plan map for quick lookup
          const bySlug = Object.fromEntries(recommendation.plans.map(p => [p.slug, p]))

          // The four columns we always show
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

              {/* Plan cards — always 4 columns */}
              <div className="grid grid-cols-4 gap-3">
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

                  // Per-month equivalent for annual plans
                  const price = parseFloat(activePlan.price)
                  const isAnnualVariant = billing === 'annual' && !!annualPlan && !activePlan.is_free
                  const perMonth = isAnnualVariant ? Math.round(price / 12) : price

                  return (
                    <div
                      key={slug}
                      onClick={() => setSelectedPlan(activePlan)}
                      className={`relative flex flex-col rounded-2xl border p-4 gap-3 cursor-pointer transition-all ${meta.color.border} ${
                        isSel ? `${meta.color.ring} bg-white/5` : 'hover:bg-white/[0.03] bg-surface-800/40'
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
                      <div className="space-y-2 flex-1">
                        {meta.highlights.map(({ icon: Icon, text }) => (
                          <div key={text} className="flex items-center gap-2 text-xs text-slate-300">
                            <Icon size={11} className="text-brand-400 shrink-0" />
                            {text}
                          </div>
                        ))}
                      </div>

                      {/* Plan badge */}
                      <div className={`text-xs font-medium px-3 py-1.5 rounded-lg text-center ${meta.color.pill}`}>
                        {activePlan.is_free ? 'No card needed' : '14-day free trial'}
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
                ) : (
                  <span className="flex items-center gap-2"><Clock size={17} /> Start my 14-day free trial</span>
                )}
              </button>

              {!selectedPlan?.is_free && (
                <p className="text-center text-xs text-slate-500">
                  Full access for 14 days. No card required upfront. Cancel anytime.
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

        <p className="text-center text-xs text-slate-600">
          You can switch plans or invite team members any time from Settings.
        </p>
      </div>
    </div>
  )
}
