import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Building2, ChevronRight, Sparkles, Check, Loader2,
  Clock, Star, ArrowLeft,
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

const QUESTIONS = [
  {
    key: 'business_type',
    label: 'What type of business do you run?',
    options: ['Retail / Shop', 'Wholesale / Distribution', 'Services', 'Manufacturing', 'E-commerce', 'Other'],
  },
  {
    key: 'monthly_transactions',
    label: 'How many transactions do you process per month?',
    options: ['Under 50', '50–200', '200–500', '500–2,000', 'Over 2,000'],
  },
  {
    key: 'team_size',
    label: 'How many people will use Audity?',
    options: ['Just me', '2–3 people', '4–10 people', '11–25 people', 'Over 25 people'],
  },
  {
    key: 'has_inventory',
    label: 'Do you manage physical inventory / stock?',
    options: ['Yes, actively', 'Sometimes', 'No, services only'],
  },
  {
    key: 'locations',
    label: 'How many locations or branches do you operate?',
    options: ['1 location', '2–3 locations', '4–10 locations', 'More than 10'],
  },
  {
    key: 'priority_feature',
    label: 'What is your top priority right now?',
    options: ['Invoicing & Sales', 'Expense Tracking', 'Inventory Management', 'Payroll', 'Financial Reports', 'Tax Compliance'],
    multi: true,
  },
  {
    key: 'business_stage',
    label: 'What stage is your business at?',
    options: ['Just starting out', 'Growing steadily', 'Established & scaling', 'Large enterprise'],
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

// ─── Step indicators ──────────────────────────────────────────────────────────

function StepDots({ step, total }: { step: number; total: number }) {
  return (
    <div className="flex items-center gap-2 justify-center mb-6">
      {Array.from({ length: total }).map((_, i) => (
        <div
          key={i}
          className={`rounded-full transition-all duration-300 ${
            i < step ? 'w-6 h-2 bg-brand-500' : i === step ? 'w-6 h-2 bg-brand-400' : 'w-2 h-2 bg-surface-600'
          }`}
        />
      ))}
    </div>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function OnboardingPage() {
  const navigate = useNavigate()
  const { user, organisation, setOrganisation } = useAuthStore()
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Step 0: workspace, 1: questionnaire, 2: recommendation, 3: payment
  const [step, setStep] = useState(0)

  // Step 0
  const [orgForm, setOrgForm] = useState({ name: '', account_type: 'business', country: 'NG', currency: 'NGN' })
  const [orgSaving, setOrgSaving] = useState(false)
  const [_createdOrg, setCreatedOrg] = useState<{ id: string; name: string } | null>(null)

  // Step 1 — answers: string for single-select, string[] for multi-select
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({})

  // Step 2
  const [loadingRec, setLoadingRec] = useState(false)
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null)
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null)

  // Step 3 (kept for success screen)
  const [initiatingPay, setInitiatingPay] = useState(false)

  // If org already exists (user returning mid-onboarding), skip to plan selection
  useEffect(() => {
    if (organisation?.id) {
      // Org exists but onboarding not complete — jump to step 2, load plans
      setStep(2)
      setLoadingRec(true)
      subscriptionApi.plans()
        .then(({ data }) => {
          const plans = data.results ?? data
          setRecommendation({
            recommended_plan_slug: '',
            confidence: '',
            reasons: [],
            alternative_plan_slug: '',
            alternative_reasons: [],
            plans,
          })
          setSelectedPlan(plans[0] ?? null)
        })
        .catch(() => toast.error('Could not load plans. Please try again.'))
        .finally(() => setLoadingRec(false))
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Step 0: Create workspace ────────────────────────────────────────────────

  const handleCreateOrg = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!orgForm.name.trim()) { toast.error('Organisation name is required'); return }
    setOrgSaving(true)
    try {
      const { data } = await orgApi.create(orgForm)
      setCreatedOrg(data)
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

  // ── Step 1: Questionnaire → get recommendation ──────────────────────────────

  const allAnswered = QUESTIONS.every((q) => {
    const val = answers[q.key]
    return Array.isArray(val) ? val.length > 0 : !!val
  })

  const toggleAnswer = (key: string, opt: string, multi?: boolean) => {
    if (!multi) {
      setAnswers((a) => ({ ...a, [key]: opt }))
      return
    }
    setAnswers((a) => {
      const current = (a[key] as string[] | undefined) ?? []
      const next = current.includes(opt)
        ? current.filter((v) => v !== opt)
        : [...current, opt]
      return { ...a, [key]: next }
    })
  }

  const isSelected = (key: string, opt: string) => {
    const val = answers[key]
    return Array.isArray(val) ? val.includes(opt) : val === opt
  }

  // Serialize answers to strings for API (multi → comma-joined)
  const serializedAnswers = Object.fromEntries(
    Object.entries(answers).map(([k, v]) => [k, Array.isArray(v) ? v.join(', ') : v])
  )

  const handleGetRecommendation = async () => {
    setLoadingRec(true)
    setStep(2)
    try {
      const { data } = await subscriptionApi.recommendPlan(serializedAnswers)
      setRecommendation(data)
      // Pre-select recommended plan
      const rec = data.plans.find((p: Plan) => p.slug === data.recommended_plan_slug) ?? data.plans[0]
      setSelectedPlan(rec)
    } catch (err: any) {
      toast.error('Could not load plan recommendation. Please select a plan manually.')
      // Still show step 2 with plans if available
      try {
        const { data } = await subscriptionApi.plans()
        setRecommendation({ recommended_plan_slug: '', confidence: '', reasons: [], alternative_plan_slug: '', alternative_reasons: [], plans: data })
        setSelectedPlan(data[0] ?? null)
      } catch {
        toast.error('Failed to load plans.')
        setStep(1)
      }
    } finally {
      setLoadingRec(false)
    }
  }

  // ── Helpers ─────────────────────────────────────────────────────────────────

  const markOnboardingComplete = async () => {
    const orgId = organisation?.id
    if (!orgId) return
    try {
      const updated = await orgApi.update(orgId, { onboarding_completed: true })
      setOrganisation(updated.data)
    } catch {
      // Non-fatal — the user is in the app; flag can be fixed on next login
    }
  }

  // ── Step 2: Select plan → start trial ──────────────────────────────────────

  const handleSelectAndPay = async (plan: Plan) => {
    setSelectedPlan(plan)
    if (plan.is_free) {
      await markOnboardingComplete()
      toast.success(`You're on the ${plan.name} plan!`)
      navigate('/dashboard')
      return
    }
    setInitiatingPay(true)
    try {
      await subscriptionApi.startTrial(plan.id)
      toast.success(`${plan.name} trial started! You have 14 days free.`)
      navigate('/dashboard')
    } catch (err: any) {
      const msg = err?.response?.data?.error?.message ?? err?.response?.data?.error ?? 'Could not start trial.'
      toast.error(typeof msg === 'string' ? msg : 'Could not start trial.')
    } finally {
      setInitiatingPay(false)
    }
  }

  // ── Helpers ──────────────────────────────────────────────────────────────────

  const formatPlanPrice = (price: string) => {
    const num = parseFloat(price)
    if (isNaN(num)) return price
    return num.toLocaleString('en-NG', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }

  const FEATURE_LABELS: Record<string, string> = {
    max_products: 'products',
    max_users: 'team members',
    multi_warehouse: 'Multi-warehouse',
    advanced_reports: 'Advanced reports',
    api_access: 'API access',
    tax_engine: 'Tax engine',
    max_invoices: 'invoices/month',
  }

  const renderFeatures = (features: Record<string, unknown>) => {
    const items: string[] = []
    for (const [key, val] of Object.entries(features)) {
      const label = FEATURE_LABELS[key]
      if (!label) continue
      if (typeof val === 'boolean') {
        if (val) items.push(label)
      } else if (val === null || val === -1 || val === 0) {
        items.push(`Unlimited ${label}`)
      } else {
        items.push(`Up to ${Number(val).toLocaleString()} ${label}`)
      }
    }
    return items
  }

  const getPlanBadge = (plan: Plan) => {
    if (!recommendation) return null
    if (plan.slug === recommendation.recommended_plan_slug) return { label: 'Recommended', color: 'bg-brand-500' }
    if (plan.slug === recommendation.alternative_plan_slug) return { label: 'Alternative', color: 'bg-amber-500' }
    return null
  }

  // ─── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-surface-950 flex items-center justify-center p-6">
      <div className="w-full max-w-2xl space-y-6">
        {/* Logo */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-white overflow-hidden flex items-center justify-center flex-shrink-0">
            <img src="/audity-logo.png" alt="Audity" className="w-8 h-8 object-contain" />
          </div>
          <h1 className="text-xl font-bold text-white">Audity</h1>
        </div>

        <StepDots step={step} total={4} />

        {/* ── Step 0: Workspace setup ── */}
        {step === 0 && (
          <div className="card">
            <div className="flex items-center gap-3 mb-1">
              <div className="w-10 h-10 bg-brand-500/15 rounded-xl flex items-center justify-center">
                <Building2 size={20} className="text-brand-400" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-white">Set up your workspace</h2>
                <p className="text-slate-400 text-sm">
                  {user?.first_name ? `Hey ${user.first_name}! ` : ''}Create your organisation to get started.
                </p>
              </div>
            </div>

            <form onSubmit={handleCreateOrg} className="mt-6 space-y-5">
              <div>
                <label className="label">Organisation name *</label>
                <input
                  className="input"
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
                <label className="label">Country & Currency</label>
                <div className="grid grid-cols-3 gap-2">
                  {PRESETS.map((p) => (
                    <button
                      key={p.country}
                      type="button"
                      onClick={() => setOrgForm((f) => ({ ...f, country: p.country, currency: p.currency }))}
                      className={`py-2 px-3 rounded-xl border text-xs font-medium flex items-center gap-2 transition-all ${
                        orgForm.country === p.country
                          ? 'bg-brand-500/15 border-brand-500 text-white'
                          : 'border-surface-600 text-slate-400 hover:border-surface-500'
                      }`}
                    >
                      <span>{p.flag}</span>
                      <span className="truncate">{p.label}</span>
                    </button>
                  ))}
                </div>
                <p className="text-xs text-slate-500 mt-2">
                  Currency: <span className="text-slate-400 font-mono">{orgForm.currency}</span>
                  {' · '}Country: <span className="text-slate-400 font-mono">{orgForm.country}</span>
                </p>
              </div>

              <button
                type="submit"
                disabled={orgSaving}
                className="btn-primary w-full justify-center py-3 mt-2 disabled:opacity-50"
              >
                {orgSaving ? 'Creating workspace…' : (
                  <span className="flex items-center gap-2">Continue <ChevronRight size={16} /></span>
                )}
              </button>
            </form>
          </div>
        )}

        {/* ── Step 1: Questionnaire ── */}
        {step === 1 && (
          <div className="card space-y-6">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-brand-500/15 rounded-xl flex items-center justify-center">
                <Sparkles size={20} className="text-brand-400" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-white">Tell us about your business</h2>
                <p className="text-slate-400 text-sm">We'll use AI to recommend the best plan for you.</p>
              </div>
            </div>

            <div className="space-y-5">
              {QUESTIONS.map((q) => (
                <div key={q.key}>
                  <div className="flex items-center gap-2 mb-1">
                    <label className="label mb-0">{q.label}</label>
                    {q.multi && (
                      <span className="text-xs text-slate-500 italic">select all that apply</span>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2 mt-1">
                    {q.options.map((opt) => {
                      const selected = isSelected(q.key, opt)
                      return (
                        <button
                          key={opt}
                          type="button"
                          onClick={() => toggleAnswer(q.key, opt, q.multi)}
                          className={`px-3 py-1.5 rounded-lg border text-sm transition-all ${
                            selected
                              ? 'bg-brand-500/20 border-brand-500 text-brand-300'
                              : 'border-surface-600 text-slate-400 hover:border-surface-500'
                          }`}
                        >
                          {selected && <Check size={12} className="inline mr-1" />}
                          {opt}
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>

            <button
              disabled={!allAnswered}
              onClick={handleGetRecommendation}
              className="btn-primary w-full justify-center py-3 disabled:opacity-40"
            >
              <span className="flex items-center gap-2">
                <Sparkles size={16} />
                Get AI recommendation
              </span>
            </button>
          </div>
        )}

        {/* ── Step 2: Recommendation + plan selection ── */}
        {step === 2 && (
          <div className="space-y-4">
            {loadingRec ? (
              <div className="card flex flex-col items-center gap-4 py-12">
                <div className="w-14 h-14 bg-brand-500/15 rounded-full flex items-center justify-center">
                  <Sparkles size={24} className="text-brand-400 animate-pulse" />
                </div>
                <p className="text-white font-semibold">Analysing your business…</p>
                <p className="text-slate-400 text-sm">Our AI is finding the best plan for you.</p>
                <Loader2 size={20} className="text-brand-400 animate-spin mt-2" />
              </div>
            ) : recommendation ? (
              <>
                {/* Recommendation summary */}
                {recommendation.reasons.length > 0 && (
                  <div className="card border border-brand-500/30 bg-brand-500/5">
                    <div className="flex items-center gap-2 mb-3">
                      <Sparkles size={16} className="text-brand-400" />
                      <span className="text-brand-300 font-semibold text-sm">AI Recommendation</span>
                      {recommendation.confidence && (
                        <span className="ml-auto text-xs text-slate-500 capitalize">{recommendation.confidence} confidence</span>
                      )}
                    </div>
                    <ul className="space-y-1">
                      {recommendation.reasons.map((r, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-slate-300">
                          <Check size={14} className="text-brand-400 mt-0.5 flex-shrink-0" />
                          {r}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Plan cards */}
                <div className="grid gap-3">
                  {recommendation.plans.map((plan) => {
                    const badge = getPlanBadge(plan)
                    const isSelected = selectedPlan?.id === plan.id
                    return (
                      <div
                        key={plan.id}
                        onClick={() => setSelectedPlan(plan)}
                        className={`card cursor-pointer transition-all border-2 ${
                          isSelected ? 'border-brand-500 bg-brand-500/5' : 'border-surface-600 hover:border-surface-500'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex-1">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-white font-bold">{plan.name}</span>
                              {badge && (
                                <span className={`text-xs px-2 py-0.5 rounded-full text-white font-medium ${badge.color}`}>
                                  {badge.label}
                                </span>
                              )}
                              {plan.is_free && (
                                <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 font-medium">
                                  Free
                                </span>
                              )}
                            </div>
                            <p className="text-slate-400 text-sm mt-0.5">
                              {plan.is_free
                                ? 'No payment required'
                                : `14 days free, then ₦${formatPlanPrice(plan.price)}/month`}
                            </p>
                            {/* Feature list */}
                            {Object.keys(plan.features).length > 0 && (
                              <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5">
                                {renderFeatures(plan.features).map((f, i) => (
                                  <li key={i} className="text-xs text-slate-400 flex items-center gap-1">
                                    <Check size={10} className="text-emerald-400 flex-shrink-0" />
                                    {f}
                                  </li>
                                ))}
                              </ul>
                            )}
                            {plan.description && (
                              <p className="text-xs text-slate-500 mt-1.5 italic">{plan.description}</p>
                            )}
                            {/* Show alternative reasons if this is the alt plan */}
                            {plan.slug === recommendation.alternative_plan_slug && recommendation.alternative_reasons.length > 0 && (
                              <ul className="mt-2 space-y-0.5">
                                {recommendation.alternative_reasons.map((r, i) => (
                                  <li key={i} className="text-xs text-slate-400 flex items-start gap-1.5">
                                    <Star size={11} className="text-amber-400 mt-0.5 flex-shrink-0" />
                                    {r}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                          <div className={`w-5 h-5 rounded-full border-2 flex-shrink-0 mt-0.5 transition-all ${
                            isSelected ? 'bg-brand-500 border-brand-500' : 'border-surface-500'
                          }`}>
                            {isSelected && <Check size={12} className="text-white m-auto" style={{ marginTop: '2px', marginLeft: '2px' }} />}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>

                <button
                  disabled={!selectedPlan || initiatingPay}
                  onClick={() => selectedPlan && handleSelectAndPay(selectedPlan)}
                  className="btn-primary w-full justify-center py-3 disabled:opacity-40"
                >
                  <span className="flex items-center gap-2">
                    {initiatingPay ? (
                      <><Loader2 size={16} className="animate-spin" /> Starting trial…</>
                    ) : selectedPlan?.is_free ? (
                      <>Get started for free <ChevronRight size={16} /></>
                    ) : (
                      <><Clock size={16} /> Start 14-Day Free Trial</>
                    )}
                  </span>
                </button>

                <button
                  onClick={() => setStep(1)}
                  className="w-full text-center text-sm text-slate-500 hover:text-slate-400 flex items-center justify-center gap-1"
                >
                  <ArrowLeft size={14} /> Change my answers
                </button>
              </>
            ) : null}
          </div>
        )}


        <p className="text-center text-xs text-slate-600">
          You can add more organisations and invite team members after setup.
        </p>
      </div>
    </div>
  )
}
