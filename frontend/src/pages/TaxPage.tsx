import { useEffect, useState } from 'react'
import {
  Building2, Calculator, ChevronDown, ChevronUp, Edit2, ExternalLink, Plus, Receipt, Trash2, X, Zap, AlertCircle, Lock, Star,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { openExternal } from '@/lib/openExternal'
import { taxApi, exciseApi, whtApi } from '@/services/api'
import { formatCurrency } from '@/lib/utils'
import type { TaxClass, TaxConfig, ExciseDuty, WHTRate, WHTTransaction } from '@/types'
import DateInput from '@/components/DateInput'
import { useAuthStore } from '@/store/authStore'

// ── Types ──────────────────────────────────────────────────────────────────────

type Tab = 'vat' | 'income' | 'tools' | 'excise' | 'wht' | 'filing'

interface ClassForm { name: string; rate: string; description: string }
const EMPTY_CLASS: ClassForm = { name: '', rate: '', description: '' }

interface ConfigForm {
  name: string
  tax_type: string
  country: string
  tax_year: string
  is_progressive: boolean
  flat_rate: string
  personal_allowance: string
  notes: string
}
const EMPTY_CONFIG: ConfigForm = {
  name: '', tax_type: 'income', country: 'NG',
  tax_year: String(new Date().getFullYear()),
  is_progressive: true, flat_rate: '0', personal_allowance: '0', notes: '',
}

interface BracketRow { lower_bound: string; upper_bound: string; rate: string; cumulative_tax_below: string }
const EMPTY_BRACKET: BracketRow = { lower_bound: '', upper_bound: '', rate: '', cumulative_tax_below: '0' }

// ── Component ─────────────────────────────────────────────────────────────────

// Starter: all advanced tabs locked
const ADVANCED_TABS: Tab[] = ['income', 'tools', 'excise', 'wht', 'filing']
// Professional: WHT, Excise, Filing locked (Income Tax + Tools are available)
const PRO_LOCKED_TABS: Tab[] = ['wht', 'excise', 'filing']

export default function TaxPage() {
  const { planTaxEngine, planName, user } = useAuthStore()
  // vat_only = Starter plan; null = superuser / no restriction
  const vatOnly = !user?.is_superuser && (planTaxEngine === 'vat_only' || planTaxEngine === 'basic')
  // professional plan: Income Tax available, but WHT / Excise / Filing locked
  const proPlan = !user?.is_superuser && planName === 'professional'

  const [tab, setTab] = useState<Tab>('vat')

  // ── VAT Classes ─────────────────────────────────────────────────────────────
  const [classes, setClasses] = useState<TaxClass[]>([])
  const [loadingClasses, setLoadingClasses] = useState(true)
  const [showClassModal, setShowClassModal] = useState(false)
  const [editingClassId, setEditingClassId] = useState<string | null>(null)
  const [classForm, setClassForm] = useState<ClassForm>(EMPTY_CLASS)
  const [savingClass, setSavingClass] = useState(false)

  // ── Tax Configs ──────────────────────────────────────────────────────────────
  const [configs, setConfigs] = useState<TaxConfig[]>([])
  const [loadingConfigs, setLoadingConfigs] = useState(true)
  const [showConfigModal, setShowConfigModal] = useState(false)
  const [editingConfigId, setEditingConfigId] = useState<string | null>(null)
  const [configForm, setConfigForm] = useState<ConfigForm>(EMPTY_CONFIG)
  const [savingConfig, setSavingConfig] = useState(false)
  const [expandedConfig, setExpandedConfig] = useState<string | null>(null)

  // ── Brackets ─────────────────────────────────────────────────────────────────
  const [showBracketsModal, setShowBracketsModal] = useState(false)
  const [bracketsConfigId, setBracketsConfigId] = useState<string | null>(null)
  const [bracketsConfigName, setBracketsConfigName] = useState('')
  const [bracketRows, setBracketRows] = useState<BracketRow[]>([EMPTY_BRACKET])
  const [savingBrackets, setSavingBrackets] = useState(false)

  // ── Excise Duty ──────────────────────────────────────────────────────────────
  const [exciseDuties, setExciseDuties] = useState<ExciseDuty[]>([])
  const [loadingExcise, setLoadingExcise] = useState(true)
  const [showExciseModal, setShowExciseModal] = useState(false)
  const [editingExciseId, setEditingExciseId] = useState<string | null>(null)
  const [exciseForm, setExciseForm] = useState({ name: '', product_category: 'spirits', duty_type: 'specific', rate: '', effective_date: new Date().toISOString().slice(0, 10), notes: '' })
  const [savingExcise, setSavingExcise] = useState(false)

  // ── WHT ─────────────────────────────────────────────────────────────────────
  const [whtRates, setWhtRates] = useState<WHTRate[]>([])
  const [whtTransactions, setWhtTransactions] = useState<WHTTransaction[]>([])
  const [loadingWHT, setLoadingWHT] = useState(true)
  const [showWHTModal, setShowWHTModal] = useState(false)
  const [editingWHTId, setEditingWHTId] = useState<string | null>(null)
  const [whtForm, setWhtForm] = useState({ transaction_type: '', company_rate: '', individual_rate: '' })
  const [savingWHT, setSavingWHT] = useState(false)

  // ── Tools ────────────────────────────────────────────────────────────────────
  const [calcIncome, setCalcIncome] = useState('')
  const [calcYear, setCalcYear] = useState(String(new Date().getFullYear()))
  const [calcType, setCalcType] = useState<'income' | 'corporate'>('income')
  const [calcResult, setCalcResult] = useState<Record<string, unknown> | null>(null)
  const [calculating, setCalculating] = useState(false)

  const [vatStart, setVatStart] = useState('')
  const [vatEnd, setVatEnd] = useState('')
  const [vatResult, setVatResult] = useState<Record<string, unknown> | null>(null)
  const [vatLoading, setVatLoading] = useState(false)

  // ── Loaders ───────────────────────────────────────────────────────────────────

  const loadClasses = async () => {
    setLoadingClasses(true)
    try {
      const { data } = await taxApi.classes()
      setClasses(data.results ?? data)
    } catch { toast.error('Failed to load VAT classes') }
    finally { setLoadingClasses(false) }
  }

  const loadConfigs = async () => {
    setLoadingConfigs(true)
    try {
      const { data } = await taxApi.configs()
      setConfigs(data.results ?? data)
    } catch { toast.error('Failed to load tax configs') }
    finally { setLoadingConfigs(false) }
  }

  const loadExcise = async () => {
    setLoadingExcise(true)
    try { const { data } = await exciseApi.list(); setExciseDuties(data.results ?? data) }
    catch { toast.error('Failed to load excise duties') }
    finally { setLoadingExcise(false) }
  }

  const loadWHT = async () => {
    setLoadingWHT(true)
    try {
      const [ratesRes, txRes] = await Promise.all([whtApi.rates(), whtApi.transactions()])
      setWhtRates(ratesRes.data.results ?? ratesRes.data)
      setWhtTransactions(txRes.data.results ?? txRes.data)
    } catch { toast.error('Failed to load WHT data') }
    finally { setLoadingWHT(false) }
  }

  useEffect(() => { loadClasses(); loadConfigs(); loadExcise(); loadWHT() }, [])

  // ── VAT Class CRUD ────────────────────────────────────────────────────────────

  const openCreateClass = () => {
    setEditingClassId(null); setClassForm(EMPTY_CLASS); setShowClassModal(true)
  }
  const openEditClass = (c: TaxClass) => {
    setEditingClassId(c.id)
    setClassForm({ name: c.name, rate: c.rate, description: c.description })
    setShowClassModal(true)
  }
  const handleSaveClass = async () => {
    if (!classForm.name.trim()) { toast.error('Name is required'); return }
    if (!classForm.rate || parseFloat(classForm.rate) < 0) { toast.error('Enter a valid rate'); return }
    setSavingClass(true)
    try {
      if (editingClassId) {
        await taxApi.updateClass(editingClassId, classForm)
        toast.success('VAT class updated')
      } else {
        await taxApi.createClass(classForm)
        toast.success('VAT class created')
      }
      setShowClassModal(false); loadClasses()
    } catch { toast.error('Failed to save VAT class') }
    finally { setSavingClass(false) }
  }
  const handleDeleteClass = async (id: string, name: string) => {
    if (!confirm(`Delete VAT class "${name}"?`)) return
    try { await taxApi.deleteClass(id); toast.success('Deleted'); loadClasses() }
    catch { toast.error('Cannot delete VAT class — it may be assigned to products') }
  }

  // ── Tax Config CRUD ──────────────────────────────────────────────────────────

  const openCreateConfig = () => {
    setEditingConfigId(null); setConfigForm(EMPTY_CONFIG); setShowConfigModal(true)
  }
  const openEditConfig = (c: TaxConfig) => {
    setEditingConfigId(c.id)
    setConfigForm({
      name: c.name, tax_type: c.tax_type, country: c.country,
      tax_year: String(c.tax_year), is_progressive: c.is_progressive,
      flat_rate: c.flat_rate, personal_allowance: c.personal_allowance, notes: c.notes,
    })
    setShowConfigModal(true)
  }
  const handleSaveConfig = async () => {
    if (!configForm.name.trim()) { toast.error('Name is required'); return }
    if (!configForm.country.trim()) { toast.error('Country code is required'); return }
    setSavingConfig(true)
    try {
      const payload = {
        ...configForm,
        tax_year: parseInt(configForm.tax_year),
        flat_rate: parseFloat(configForm.flat_rate) || 0,
        personal_allowance: parseFloat(configForm.personal_allowance) || 0,
      }
      if (editingConfigId) {
        await taxApi.updateConfig(editingConfigId, payload)
        toast.success('Tax config updated')
      } else {
        await taxApi.createConfig(payload)
        toast.success('Tax config created')
      }
      setShowConfigModal(false); loadConfigs()
    } catch { toast.error('Failed to save tax config') }
    finally { setSavingConfig(false) }
  }
  const handleDeleteConfig = async (id: string, name: string) => {
    if (!confirm(`Delete tax config "${name}"? All brackets will be removed.`)) return
    try { await taxApi.deleteConfig(id); toast.success('Deleted'); loadConfigs() }
    catch { toast.error('Failed to delete tax config') }
  }

  // ── Bracket management ────────────────────────────────────────────────────────

  const openBracketsModal = (c: TaxConfig) => {
    setBracketsConfigId(c.id)
    setBracketsConfigName(c.name)
    setBracketRows(
      c.brackets.length > 0
        ? c.brackets.map((b) => ({
            lower_bound: b.lower_bound,
            upper_bound: b.upper_bound ?? '',
            rate: b.rate,
            cumulative_tax_below: b.cumulative_tax_below,
          }))
        : [EMPTY_BRACKET]
    )
    setShowBracketsModal(true)
  }
  const addBracketRow = () => setBracketRows([...bracketRows, { ...EMPTY_BRACKET }])
  const removeBracketRow = (i: number) => setBracketRows(bracketRows.filter((_, idx) => idx !== i))
  const updateBracketRow = (i: number, field: keyof BracketRow, value: string) => {
    setBracketRows(bracketRows.map((r, idx) => idx === i ? { ...r, [field]: value } : r))
  }
  const handleSaveBrackets = async () => {
    if (!bracketsConfigId) return
    const payload = bracketRows.map((r) => ({
      lower_bound: parseFloat(r.lower_bound) || 0,
      upper_bound: r.upper_bound ? parseFloat(r.upper_bound) : null,
      rate: parseFloat(r.rate) || 0,
      cumulative_tax_below: parseFloat(r.cumulative_tax_below) || 0,
    }))
    setSavingBrackets(true)
    try {
      await taxApi.setBrackets(bracketsConfigId, payload)
      toast.success('Tax brackets saved')
      setShowBracketsModal(false)
      loadConfigs()
    } catch { toast.error('Failed to save brackets') }
    finally { setSavingBrackets(false) }
  }

  // ── Tax Calculator ────────────────────────────────────────────────────────────

  const handleCalculate = async () => {
    if (!calcIncome || parseFloat(calcIncome) < 0) { toast.error('Enter a valid income'); return }
    setCalculating(true)
    try {
      const { data } = await taxApi.calculateIncomeTax({
        income: parseFloat(calcIncome),
        tax_year: parseInt(calcYear),
        tax_type: calcType,
      })
      setCalcResult(data)
    } catch { toast.error('No income tax config found for this year. Add one in the Income Tax tab.') }
    finally { setCalculating(false) }
  }

  const handleVatReport = async () => {
    if (!vatStart || !vatEnd) { toast.error('Select both start and end dates'); return }
    setVatLoading(true)
    try {
      const { data } = await taxApi.vatReport({ period_start: vatStart, period_end: vatEnd })
      setVatResult(data)
    } catch { toast.error('Failed to generate VAT report') }
    finally { setVatLoading(false) }
  }

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Tax Management</h1>
        <p className="text-slate-400 text-sm mt-0.5">Configure VAT rates, income tax brackets, and generate tax reports</p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-surface-800 rounded-xl w-fit overflow-x-auto">
        {([
          ['vat', 'VAT Classes'],
          ['income', 'Income Tax'],
          ['tools', 'Tax Tools'],
          ['excise', 'Excise Duty'],
          ['wht', 'WHT'],
          ['filing', 'Filing Guide'],
        ] as [Tab, string][]).map(([t, label]) => {
          const locked =
            (vatOnly && ADVANCED_TABS.includes(t)) ||
            (proPlan && PRO_LOCKED_TABS.includes(t))
          const lockTitle = vatOnly && ADVANCED_TABS.includes(t)
            ? 'Upgrade to Professional or Business to unlock'
            : 'Upgrade to Business to unlock'
          return (
            <button
              key={t}
              onClick={() => { if (!locked) setTab(t) }}
              title={locked ? lockTitle : undefined}
              className={
                locked
                  ? 'px-4 py-2 rounded-lg text-sm text-slate-600 flex items-center gap-1.5 cursor-not-allowed whitespace-nowrap'
                  : tab === t
                    ? 'px-4 py-2 rounded-lg text-sm font-semibold bg-brand-500 text-white whitespace-nowrap'
                    : 'px-4 py-2 rounded-lg text-sm text-slate-400 hover:text-white transition-colors whitespace-nowrap'
              }
            >
              {locked && <Lock size={11} />}
              {label}
            </button>
          )
        })}
      </div>

      {/* Starter plan VAT-only notice */}
      {vatOnly && (
        <div className="flex items-start gap-3 p-4 rounded-xl bg-brand-500/8 border border-brand-500/20">
          <Zap size={16} className="text-brand-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-brand-300">Starter Plan — VAT Automation included</p>
            <p className="text-xs text-slate-400 mt-0.5">
              Income Tax, Corporate Tax, Excise Duty and WHT are available on the{' '}
              <strong className="text-white">Professional</strong> and <strong className="text-white">Business</strong> plans.
            </p>
          </div>
        </div>
      )}

      {/* Professional plan partial-tax notice */}
      {proPlan && (
        <div className="flex items-start gap-3 p-4 rounded-xl bg-amber-500/8 border border-amber-500/20">
          <Star size={16} className="text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-300">Professional Plan — VAT &amp; Income Tax included</p>
            <p className="text-xs text-slate-400 mt-0.5">
              Excise Duty, WHT, and the Filing Guide are exclusive to the{' '}
              <strong className="text-white">Business</strong> plan.
            </p>
          </div>
        </div>
      )}

      {/* ── VAT Classes Tab ──────────────────────────────────────────────────── */}
      {tab === 'vat' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-white font-semibold">VAT / Sales Tax Classes</h2>
              <p className="text-slate-500 text-xs mt-0.5">Assign these to products. Auto-applied at point of sale.</p>
            </div>
            <button onClick={openCreateClass} className="btn-primary flex items-center gap-2">
              <Plus size={15} /> Add VAT Class
            </button>
          </div>

          <div className="card overflow-hidden">
            {loadingClasses ? (
              <div className="p-8 text-center text-slate-500">Loading…</div>
            ) : classes.length === 0 ? (
              <div className="p-12 text-center">
                <Receipt size={36} className="mx-auto text-slate-600 mb-3" />
                <p className="text-slate-400 font-medium">No VAT classes yet</p>
                <p className="text-slate-500 text-xs mt-1">e.g. "Standard Rate (7.5%)", "Zero Rated (0%)", "Exempt"</p>
                <button onClick={openCreateClass} className="btn-primary mt-4 inline-flex items-center gap-2 text-sm">
                  <Plus size={14} /> Add First VAT Class
                </button>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700">
                    {['Name', 'Rate (%)', 'Description', ''].map((h) => (
                      <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-700">
                  {classes.map((c) => (
                    <tr key={c.id} className="table-row">
                      <td className="px-5 py-3.5 font-medium text-white">{c.name}</td>
                      <td className="px-5 py-3.5">
                        <span className="badge-blue font-mono">{parseFloat(c.rate).toFixed(1)}%</span>
                      </td>
                      <td className="px-5 py-3.5 text-slate-400 text-sm">{c.description || '—'}</td>
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-2 justify-end">
                          <button onClick={() => openEditClass(c)}
                            className="p-1.5 text-slate-500 hover:text-white hover:bg-surface-600 rounded-lg transition-colors">
                            <Edit2 size={14} />
                          </button>
                          <button onClick={() => handleDeleteClass(c.id, c.name)}
                            className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors">
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* ── Income Tax Tab ───────────────────────────────────────────────────── */}
      {tab === 'income' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-white font-semibold">Income / Corporate Tax Configurations</h2>
              <p className="text-slate-500 text-xs mt-0.5">Define tax schedules and progressive brackets per year.</p>
            </div>
            <button onClick={openCreateConfig} className="btn-primary flex items-center gap-2">
              <Plus size={15} /> Add Tax Config
            </button>
          </div>

          {loadingConfigs ? (
            <div className="card p-8 text-center text-slate-500">Loading…</div>
          ) : configs.filter((c) => c.tax_type !== 'vat').length === 0 ? (
            <div className="card p-12 text-center">
              <Calculator size={36} className="mx-auto text-slate-600 mb-3" />
              <p className="text-slate-400 font-medium">No tax configurations yet</p>
              <p className="text-slate-500 text-xs mt-1">e.g. "Nigeria PIT 2024", "Corporate Tax 30%"</p>
              <button onClick={openCreateConfig} className="btn-primary mt-4 inline-flex items-center gap-2 text-sm">
                <Plus size={14} /> Add First Config
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {configs.filter((c) => c.tax_type !== 'vat').map((c) => (
                <div key={c.id} className="card overflow-hidden">
                  <div className="p-4 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => setExpandedConfig(expandedConfig === c.id ? null : c.id)}
                        className="text-slate-400 hover:text-white transition-colors"
                      >
                        {expandedConfig === c.id ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                      </button>
                      <div>
                        <p className="text-white font-medium">{c.name}</p>
                        <p className="text-slate-500 text-xs">
                          {c.tax_type.toUpperCase()} · {c.country} · {c.tax_year}
                          {c.is_progressive ? ` · Progressive (${c.brackets.length} brackets)` : ` · Flat ${c.flat_rate}%`}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => openBracketsModal(c)}
                        className="text-xs px-3 py-1.5 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 transition-colors"
                      >
                        Edit Brackets
                      </button>
                      <button onClick={() => openEditConfig(c)}
                        className="p-1.5 text-slate-500 hover:text-white hover:bg-surface-600 rounded-lg transition-colors">
                        <Edit2 size={14} />
                      </button>
                      <button onClick={() => handleDeleteConfig(c.id, c.name)}
                        className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>

                  {expandedConfig === c.id && c.brackets.length > 0 && (
                    <div className="border-t border-surface-700">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-surface-700 bg-surface-800/50">
                            {['Lower Bound', 'Upper Bound', 'Rate (%)', 'Cumulative Tax Below'].map((h) => (
                              <th key={h} className="px-4 py-2.5 text-left text-slate-500 font-medium uppercase tracking-wider">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-surface-700">
                          {c.brackets.map((b, i) => (
                            <tr key={i} className="table-row">
                              <td className="px-4 py-2.5 text-slate-300 font-mono">{formatCurrency(b.lower_bound)}</td>
                              <td className="px-4 py-2.5 text-slate-300 font-mono">{b.upper_bound ? formatCurrency(b.upper_bound) : '∞'}</td>
                              <td className="px-4 py-2.5"><span className="badge-orange">{b.rate}%</span></td>
                              <td className="px-4 py-2.5 text-slate-400 font-mono">{formatCurrency(b.cumulative_tax_below)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {expandedConfig === c.id && c.brackets.length === 0 && (
                    <div className="border-t border-surface-700 p-4 text-center text-slate-500 text-sm">
                      No brackets defined yet.{' '}
                      <button onClick={() => openBracketsModal(c)} className="text-brand-400 hover:underline">Add brackets</button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Tax Tools Tab ────────────────────────────────────────────────────── */}
      {tab === 'tools' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Income Tax Calculator */}
          <div className="card p-6 space-y-4">
            <div className="flex items-center gap-2 mb-1">
              <Calculator size={18} className="text-brand-400" />
              <h3 className="text-white font-semibold">
                {calcType === 'income' ? 'Personal Income Tax Calculator' : 'Corporate Income Tax Calculator'}
              </h3>
            </div>
            <div className="flex gap-2 p-3 rounded-xl bg-amber-500/10 border border-amber-500/20">
              <AlertCircle size={14} className="text-amber-400 shrink-0 mt-0.5" />
              <p className="text-xs text-amber-300">
                Requires a {calcType === 'income' ? 'Personal Income Tax' : 'Corporate Income Tax'} config with brackets set up in the{' '}
                <button onClick={() => setTab('income')} className="underline hover:text-amber-200">Income Tax tab</button> for the selected year.
              </p>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
                  Tax Type
                </label>
                <select
                  className="input"
                  value={calcType}
                  onChange={(e) => { setCalcType(e.target.value as 'income' | 'corporate'); setCalcResult(null) }}
                >
                  <option value="income">Personal Income Tax (PIT)</option>
                  <option value="corporate">Corporate Income Tax (CIT)</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
                  {calcType === 'income' ? 'Annual Gross Income' : 'Annual Taxable Profit'}
                </label>
                <input
                  type="number" className="input" placeholder="e.g. 5000000"
                  value={calcIncome} onChange={(e) => setCalcIncome(e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
                  Tax Year
                </label>
                <input
                  type="number" className="input" placeholder="e.g. 2024"
                  value={calcYear} onChange={(e) => setCalcYear(e.target.value)}
                />
              </div>
              <button
                onClick={handleCalculate} disabled={calculating}
                className="btn-primary w-full disabled:opacity-50"
              >
                {calculating ? 'Calculating…' : `Calculate ${calcType === 'income' ? 'Personal' : 'Corporate'} Tax`}
              </button>
            </div>

            {calcResult && (
              <div className="mt-4 border-t border-surface-700 pt-4 space-y-4">
                <div className="space-y-2">
                  {(['config', 'tax_year', 'gross_income', 'total_allowances', 'net_taxable_income', 'effective_rate', 'tax_payable'] as const).map((k) => {
                    const v = (calcResult as any)[k]
                    if (v === undefined) return null
                    const isMoney = ['gross_income', 'total_allowances', 'net_taxable_income', 'tax_payable'].includes(k)
                    const isRate = k === 'effective_rate'
                    return (
                      <div key={k} className={`flex justify-between text-sm ${k === 'tax_payable' ? 'border-t border-surface-700 pt-2' : ''}`}>
                        <span className="text-slate-400 capitalize">{k.replace(/_/g, ' ')}</span>
                        <span className={`font-mono font-medium ${k === 'tax_payable' ? 'text-brand-400 text-base' : 'text-white'}`}>
                          {isMoney ? formatCurrency(String(v)) : isRate ? `${parseFloat(String(v)).toFixed(2)}%` : String(v)}
                        </span>
                      </div>
                    )
                  })}
                </div>
                {Array.isArray((calcResult as any).brackets) && (calcResult as any).brackets.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Bracket Breakdown</p>
                    <div className="space-y-1">
                      {((calcResult as any).brackets as any[]).map((b: any, i: number) => (
                        <div key={i} className="flex justify-between text-xs p-2 rounded-lg bg-surface-700/30">
                          <span className="text-slate-400">{b.bracket} @ {b.rate}%</span>
                          <span className="font-mono text-white">{formatCurrency(String(b.tax))}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* VAT Report */}
          <div className="card p-6 space-y-4">
            <div className="flex items-center gap-2 mb-1">
              <Receipt size={18} className="text-emerald-400" />
              <h3 className="text-white font-semibold">VAT Report</h3>
            </div>
            <p className="text-slate-500 text-xs">Summarises VAT collected on sales for the chosen period.</p>

            <div className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
                  Period Start
                </label>
                <DateInput value={vatStart} onChange={setVatStart} />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
                  Period End
                </label>
                <DateInput value={vatEnd} onChange={setVatEnd} />
              </div>
              <button
                onClick={handleVatReport} disabled={vatLoading}
                className="btn-primary w-full disabled:opacity-50"
              >
                {vatLoading ? 'Generating…' : 'Generate VAT Report'}
              </button>
            </div>

            {vatResult && (
              <div className="mt-4 border-t border-surface-700 pt-4 space-y-2">
                {[
                  { key: 'period_start', label: 'Period Start', money: false },
                  { key: 'period_end', label: 'Period End', money: false },
                  { key: 'total_net_sales', label: 'Total Net Sales', money: true },
                  { key: 'vat_output', label: 'VAT Output (collected)', money: true },
                  { key: 'vat_input', label: 'VAT Input (on purchases)', money: true },
                  { key: 'net_vat_payable', label: 'Net VAT Payable', money: true },
                ].map(({ key, label, money }) => {
                  const v = (vatResult as any)[key]
                  if (v === undefined) return null
                  const isPayable = key === 'net_vat_payable'
                  return (
                    <div key={key} className={`flex justify-between text-sm ${isPayable ? 'border-t border-surface-700 pt-2' : ''}`}>
                      <span className="text-slate-400">{label}</span>
                      <span className={`font-mono font-medium ${isPayable ? 'text-brand-400 text-base' : 'text-white'}`}>
                        {money ? formatCurrency(String(v)) : String(v)}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Excise Duty Tab ──────────────────────────────────────────────────── */}
      {tab === 'excise' && (
        <div className="space-y-4">
          {/* Info banner */}
          <div className="flex gap-3 p-4 rounded-xl bg-amber-500/10 border border-amber-500/30">
            <AlertCircle size={18} className="text-amber-400 shrink-0 mt-0.5" />
            <div className="text-sm">
              <p className="text-amber-300 font-semibold">Nigeria Excise Duty (FIRS / Customs)</p>
              <p className="text-amber-400/80 mt-0.5">
                Specific duties are calculated per Litre of Pure Alcohol (LPA = ABV% × Volume in litres).
                Ad valorem duties are a percentage of the selling price.
                Current rate for spirits: ₦158.70/LPA.
              </p>
            </div>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-white font-semibold">Excise Duty Rates</h2>
              <p className="text-slate-500 text-xs mt-0.5">Configure excise duty for alcoholic beverages and other excisable goods.</p>
            </div>
            <button onClick={() => { setEditingExciseId(null); setExciseForm({ name: '', product_category: 'spirits', duty_type: 'specific', rate: '', effective_date: new Date().toISOString().slice(0, 10), notes: '' }); setShowExciseModal(true) }}
              className="btn-primary flex items-center gap-2">
              <Plus size={15} /> Add Excise Rate
            </button>
          </div>

          <div className="card overflow-hidden">
            {loadingExcise ? (
              <div className="p-8 text-center text-slate-500">Loading…</div>
            ) : exciseDuties.length === 0 ? (
              <div className="p-12 text-center">
                <Zap size={36} className="mx-auto text-slate-600 mb-3" />
                <p className="text-slate-400 font-medium">No excise duties configured</p>
                <p className="text-slate-500 text-xs mt-1">Add excise duty rates for spirits, wine, beer, or tobacco</p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700">
                    {['Name', 'Category', 'Type', 'Rate', 'Effective', 'Status', ''].map((h) => (
                      <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-700">
                  {exciseDuties.map((e) => (
                    <tr key={e.id} className="table-row">
                      <td className="px-5 py-3.5 font-medium text-white">{e.name}</td>
                      <td className="px-5 py-3.5"><span className="badge-blue capitalize">{e.product_category}</span></td>
                      <td className="px-5 py-3.5 text-slate-400 capitalize">{e.duty_type === 'specific' ? 'Per LPA' : 'Ad Valorem'}</td>
                      <td className="px-5 py-3.5 font-mono text-brand-400">
                        {e.duty_type === 'specific' ? `₦${parseFloat(e.rate).toFixed(2)}/LPA` : `${parseFloat(e.rate).toFixed(2)}%`}
                      </td>
                      <td className="px-5 py-3.5 text-slate-400">{e.effective_date}</td>
                      <td className="px-5 py-3.5">
                        <span className={e.is_active ? 'badge-green' : 'badge-slate'}>{e.is_active ? 'Active' : 'Inactive'}</span>
                      </td>
                      <td className="px-5 py-3.5">
                        <div className="flex gap-2 justify-end">
                          <button onClick={() => { setEditingExciseId(e.id); setExciseForm({ name: e.name, product_category: e.product_category, duty_type: e.duty_type, rate: e.rate, effective_date: e.effective_date, notes: e.notes }); setShowExciseModal(true) }}
                            className="p-1.5 text-slate-500 hover:text-white hover:bg-surface-600 rounded-lg transition-colors"><Edit2 size={14} /></button>
                          <button onClick={async () => { if (!confirm(`Delete excise duty "${e.name}"?`)) return; try { await exciseApi.delete(e.id); toast.success('Deleted'); loadExcise() } catch { toast.error('Failed to delete') } }}
                            className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"><Trash2 size={14} /></button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* ── WHT Tab ──────────────────────────────────────────────────────────── */}
      {tab === 'wht' && (
        <div className="space-y-6">
          {/* WHT Rates */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-white font-semibold">Withholding Tax Rates</h2>
                <p className="text-slate-500 text-xs mt-0.5">Configure WHT rates per transaction type (FIRS guidelines). Standard: 5% companies, 10% individuals for most categories.</p>
              </div>
              <button onClick={() => { setEditingWHTId(null); setWhtForm({ transaction_type: '', company_rate: '', individual_rate: '' }); setShowWHTModal(true) }}
                className="btn-primary flex items-center gap-2"><Plus size={15} /> Add WHT Rate</button>
            </div>
            <div className="card overflow-hidden">
              {loadingWHT ? (
                <div className="p-8 text-center text-slate-500">Loading…</div>
              ) : whtRates.length === 0 ? (
                <div className="p-10 text-center">
                  <Receipt size={32} className="mx-auto text-slate-600 mb-3" />
                  <p className="text-slate-400 font-medium">No WHT rates configured</p>
                  <p className="text-slate-500 text-xs mt-1">Add rates for Rent, Consultancy, Dividends, Interest, Contracts etc.</p>
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-700">
                      {['Transaction Type', 'Company Rate', 'Individual Rate', 'Status', ''].map((h) => (
                        <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-700">
                    {whtRates.map((r) => (
                      <tr key={r.id} className="table-row">
                        <td className="px-5 py-3.5 font-medium text-white">{r.transaction_type}</td>
                        <td className="px-5 py-3.5"><span className="badge-orange font-mono">{r.company_rate}%</span></td>
                        <td className="px-5 py-3.5"><span className="badge-blue font-mono">{r.individual_rate}%</span></td>
                        <td className="px-5 py-3.5"><span className={r.is_active ? 'badge-green' : 'badge-slate'}>{r.is_active ? 'Active' : 'Inactive'}</span></td>
                        <td className="px-5 py-3.5">
                          <div className="flex gap-2 justify-end">
                            <button onClick={() => { setEditingWHTId(r.id); setWhtForm({ transaction_type: r.transaction_type, company_rate: r.company_rate, individual_rate: r.individual_rate }); setShowWHTModal(true) }}
                              className="p-1.5 text-slate-500 hover:text-white hover:bg-surface-600 rounded-lg transition-colors"><Edit2 size={14} /></button>
                            <button onClick={async () => { if (!confirm(`Delete WHT rate "${r.transaction_type}"?`)) return; try { await whtApi.deleteRate(r.id); toast.success('Deleted'); loadWHT() } catch { toast.error('Failed to delete') } }}
                              className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"><Trash2 size={14} /></button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* WHT Transactions */}
          {whtTransactions.length > 0 && (
            <div className="space-y-4">
              <h2 className="text-white font-semibold">WHT Transactions</h2>
              <div className="card overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-700">
                      {['Date', 'Counterparty', 'Type', 'Gross', 'WHT Rate', 'WHT Amount', 'Net', 'Status'].map((h) => (
                        <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-700">
                    {whtTransactions.map((t) => (
                      <tr key={t.id} className="table-row">
                        <td className="px-5 py-3.5 text-slate-400">{t.transaction_date}</td>
                        <td className="px-5 py-3.5 text-white">{t.counterparty_name}</td>
                        <td className="px-5 py-3.5"><span className={t.transaction_type === 'sale' ? 'badge-green' : 'badge-blue'}>{t.transaction_type}</span></td>
                        <td className="px-5 py-3.5 font-mono text-white">{formatCurrency(t.gross_amount)}</td>
                        <td className="px-5 py-3.5"><span className="badge-orange">{t.wht_rate_percent}%</span></td>
                        <td className="px-5 py-3.5 font-mono text-red-400">{formatCurrency(t.wht_amount)}</td>
                        <td className="px-5 py-3.5 font-mono text-emerald-400">{formatCurrency(t.net_amount)}</td>
                        <td className="px-5 py-3.5"><span className={t.status === 'remitted' ? 'badge-green' : 'badge-yellow'}>{t.status}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── VAT Class Modal ──────────────────────────────────────────────────── */}
      {showClassModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-md shadow-2xl">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-bold text-white">{editingClassId ? 'Edit VAT Class' : 'Add VAT Class'}</h2>
              <button onClick={() => setShowClassModal(false)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Name *</label>
                <input className="input" placeholder="e.g. Standard Rate, Zero Rated, Exempt"
                  value={classForm.name} onChange={(e) => setClassForm({ ...classForm, name: e.target.value })} />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Rate (%) *</label>
                <input type="number" min="0" max="100" step="0.1" className="input" placeholder="e.g. 7.5"
                  value={classForm.rate} onChange={(e) => setClassForm({ ...classForm, rate: e.target.value })} />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Description</label>
                <input className="input" placeholder="Optional note"
                  value={classForm.description} onChange={(e) => setClassForm({ ...classForm, description: e.target.value })} />
              </div>
            </div>
            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowClassModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleSaveClass} disabled={savingClass} className="btn-primary flex-1 disabled:opacity-50">
                {savingClass ? 'Saving…' : editingClassId ? 'Save Changes' : 'Add Class'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Tax Config Modal ─────────────────────────────────────────────────── */}
      {showConfigModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-lg shadow-2xl overflow-y-auto max-h-[90vh]">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-bold text-white">{editingConfigId ? 'Edit Tax Config' : 'Add Tax Config'}</h2>
              <button onClick={() => setShowConfigModal(false)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Name *</label>
                <input className="input" placeholder="e.g. Nigeria Personal Income Tax 2024"
                  value={configForm.name} onChange={(e) => setConfigForm({ ...configForm, name: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Tax Type *</label>
                  <select className="input" value={configForm.tax_type}
                    onChange={(e) => setConfigForm({ ...configForm, tax_type: e.target.value })}>
                    <option value="income">Income Tax</option>
                    <option value="corporate">Corporate Tax</option>
                    <option value="withholding">Withholding Tax</option>
                    <option value="excise">Excise Duty</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Country Code *</label>
                  <input className="input" placeholder="e.g. NG, GH, GB" maxLength={2}
                    value={configForm.country} onChange={(e) => setConfigForm({ ...configForm, country: e.target.value.toUpperCase() })} />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Tax Year *</label>
                <input type="number" className="input" placeholder="e.g. 2024"
                  value={configForm.tax_year} onChange={(e) => setConfigForm({ ...configForm, tax_year: e.target.value })} />
              </div>
              <label className="flex items-center gap-3 cursor-pointer">
                <input type="checkbox" className="w-4 h-4 accent-orange-500"
                  checked={configForm.is_progressive}
                  onChange={(e) => setConfigForm({ ...configForm, is_progressive: e.target.checked })} />
                <span className="text-sm text-slate-300">Progressive (tiered brackets)</span>
              </label>
              {!configForm.is_progressive && (
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Flat Rate (%)</label>
                  <input type="number" min="0" max="100" step="0.1" className="input" placeholder="e.g. 30"
                    value={configForm.flat_rate} onChange={(e) => setConfigForm({ ...configForm, flat_rate: e.target.value })} />
                </div>
              )}
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Personal Allowance</label>
                <input type="number" min="0" className="input" placeholder="Tax-free income threshold"
                  value={configForm.personal_allowance} onChange={(e) => setConfigForm({ ...configForm, personal_allowance: e.target.value })} />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Notes</label>
                <textarea className="input resize-none" rows={2} placeholder="Any notes about this tax config"
                  value={configForm.notes} onChange={(e) => setConfigForm({ ...configForm, notes: e.target.value })} />
              </div>
            </div>
            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowConfigModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleSaveConfig} disabled={savingConfig} className="btn-primary flex-1 disabled:opacity-50">
                {savingConfig ? 'Saving…' : editingConfigId ? 'Save Changes' : 'Add Config'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Brackets Modal ───────────────────────────────────────────────────── */}
      {showBracketsModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-3xl shadow-2xl overflow-y-auto max-h-[90vh]">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-lg font-bold text-white">Tax Brackets</h2>
              <button onClick={() => setShowBracketsModal(false)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <p className="text-slate-500 text-xs mb-5">
              <strong className="text-slate-300">{bracketsConfigName}</strong> — Editing replaces all brackets. Leave upper bound empty for the highest bracket.
            </p>

            <div className="overflow-x-auto">
              <table className="w-full text-sm mb-3">
                <thead>
                  <tr className="border-b border-surface-700">
                    {['Lower Bound', 'Upper Bound', 'Rate (%)', 'Cumulative Tax Below', ''].map((h) => (
                      <th key={h} className="px-3 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-700">
                  {bracketRows.map((row, i) => (
                    <tr key={i}>
                      <td className="px-3 py-2">
                        <input type="number" min="0" className="input py-1.5 text-sm" placeholder="0"
                          value={row.lower_bound} onChange={(e) => updateBracketRow(i, 'lower_bound', e.target.value)} />
                      </td>
                      <td className="px-3 py-2">
                        <input type="number" min="0" className="input py-1.5 text-sm" placeholder="∞ (leave blank)"
                          value={row.upper_bound} onChange={(e) => updateBracketRow(i, 'upper_bound', e.target.value)} />
                      </td>
                      <td className="px-3 py-2">
                        <input type="number" min="0" max="100" step="0.1" className="input py-1.5 text-sm" placeholder="0"
                          value={row.rate} onChange={(e) => updateBracketRow(i, 'rate', e.target.value)} />
                      </td>
                      <td className="px-3 py-2">
                        <input type="number" min="0" className="input py-1.5 text-sm" placeholder="0"
                          value={row.cumulative_tax_below} onChange={(e) => updateBracketRow(i, 'cumulative_tax_below', e.target.value)} />
                      </td>
                      <td className="px-3 py-2">
                        <button onClick={() => removeBracketRow(i)}
                          className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors">
                          <Trash2 size={13} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <button onClick={addBracketRow} className="btn-ghost text-sm flex items-center gap-1.5 mb-5">
              <Plus size={13} /> Add Row
            </button>

            <div className="flex gap-3">
              <button onClick={() => setShowBracketsModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleSaveBrackets} disabled={savingBrackets} className="btn-primary flex-1 disabled:opacity-50">
                {savingBrackets ? 'Saving…' : 'Save All Brackets'}
              </button>
            </div>
          </div>
        </div>
      )}
      {/* ── Excise Duty Modal ────────────────────────────────────────────────── */}
      {showExciseModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-lg shadow-2xl">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-bold text-white">{editingExciseId ? 'Edit Excise Rate' : 'Add Excise Rate'}</h2>
              <button onClick={() => setShowExciseModal(false)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Name *</label>
                <input className="input" placeholder="e.g. Spirits Excise 2024" value={exciseForm.name} onChange={(e) => setExciseForm({ ...exciseForm, name: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Product Category</label>
                  <select className="input" value={exciseForm.product_category} onChange={(e) => setExciseForm({ ...exciseForm, product_category: e.target.value })}>
                    <option value="spirits">Spirits</option>
                    <option value="wine">Wine</option>
                    <option value="beer">Beer</option>
                    <option value="tobacco">Tobacco</option>
                    <option value="other">Other</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Duty Type</label>
                  <select className="input" value={exciseForm.duty_type} onChange={(e) => setExciseForm({ ...exciseForm, duty_type: e.target.value })}>
                    <option value="specific">Specific (per LPA)</option>
                    <option value="ad_valorem">Ad Valorem (%)</option>
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
                    Rate {exciseForm.duty_type === 'specific' ? '(₦ per LPA)' : '(%)'}
                  </label>
                  <input type="number" step="0.0001" className="input" placeholder={exciseForm.duty_type === 'specific' ? '158.70' : '5.00'} value={exciseForm.rate} onChange={(e) => setExciseForm({ ...exciseForm, rate: e.target.value })} />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Effective Date</label>
                  <DateInput value={exciseForm.effective_date} onChange={(v) => setExciseForm({ ...exciseForm, effective_date: v })} />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Notes (NAFDAC/Customs reference)</label>
                <input className="input" placeholder="e.g. FIRS Circular No. 2024/001" value={exciseForm.notes} onChange={(e) => setExciseForm({ ...exciseForm, notes: e.target.value })} />
              </div>
            </div>
            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowExciseModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button disabled={savingExcise} className="btn-primary flex-1 disabled:opacity-50" onClick={async () => {
                if (!exciseForm.name.trim() || !exciseForm.rate) { toast.error('Name and rate are required'); return }
                setSavingExcise(true)
                try {
                  const payload = { ...exciseForm, rate: parseFloat(exciseForm.rate) }
                  if (editingExciseId) { await exciseApi.update(editingExciseId, payload); toast.success('Updated') }
                  else { await exciseApi.create(payload); toast.success('Created') }
                  setShowExciseModal(false); loadExcise()
                } catch { toast.error('Failed to save') }
                finally { setSavingExcise(false) }
              }}>
                {savingExcise ? 'Saving…' : editingExciseId ? 'Save Changes' : 'Add Rate'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── WHT Rate Modal ───────────────────────────────────────────────────── */}
      {showWHTModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-md shadow-2xl">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-bold text-white">{editingWHTId ? 'Edit WHT Rate' : 'Add WHT Rate'}</h2>
              <button onClick={() => setShowWHTModal(false)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Transaction Type *</label>
                <input className="input" placeholder="e.g. Rent, Consultancy, Dividends" value={whtForm.transaction_type} onChange={(e) => setWhtForm({ ...whtForm, transaction_type: e.target.value })} list="wht-types" />
                <datalist id="wht-types">
                  {['Rent', 'Consultancy/Management Fees', 'Dividends', 'Interest', 'Contract/Supplies', 'Commission', 'Director Fees', 'Royalties'].map((v) => <option key={v} value={v} />)}
                </datalist>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Company Rate (%) *</label>
                  <input type="number" min="0" max="30" step="0.5" className="input" placeholder="5" value={whtForm.company_rate} onChange={(e) => setWhtForm({ ...whtForm, company_rate: e.target.value })} />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Individual Rate (%) *</label>
                  <input type="number" min="0" max="30" step="0.5" className="input" placeholder="10" value={whtForm.individual_rate} onChange={(e) => setWhtForm({ ...whtForm, individual_rate: e.target.value })} />
                </div>
              </div>
              <p className="text-xs text-slate-500">FIRS standard: 5% for companies, 10% for individuals (most categories)</p>
            </div>
            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowWHTModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button disabled={savingWHT} className="btn-primary flex-1 disabled:opacity-50" onClick={async () => {
                if (!whtForm.transaction_type.trim()) { toast.error('Transaction type is required'); return }
                setSavingWHT(true)
                try {
                  const payload = { transaction_type: whtForm.transaction_type, company_rate: parseFloat(whtForm.company_rate) || 5, individual_rate: parseFloat(whtForm.individual_rate) || 10 }
                  if (editingWHTId) { await whtApi.updateRate(editingWHTId, payload); toast.success('Updated') }
                  else { await whtApi.createRate(payload); toast.success('Created') }
                  setShowWHTModal(false); loadWHT()
                } catch { toast.error('Failed to save') }
                finally { setSavingWHT(false) }
              }}>
                {savingWHT ? 'Saving…' : editingWHTId ? 'Save Changes' : 'Add WHT Rate'}
              </button>
            </div>
          </div>
        </div>
      )}
      {/* ── Filing Guide Tab ─────────────────────────────────────────────────── */}
      {tab === 'filing' && (
        <div className="space-y-6 relative">
          {/* Business-plan upgrade gate: blur content for Pro users */}
          {proPlan && (
            <div className="absolute inset-0 z-20 flex flex-col items-center justify-center rounded-2xl bg-surface-900/60 backdrop-blur-md">
              <div className="text-center max-w-sm px-6">
                <div className="w-14 h-14 bg-amber-500/15 rounded-2xl flex items-center justify-center mx-auto mb-4">
                  <Lock size={28} className="text-amber-400" />
                </div>
                <p className="text-white font-bold text-lg">Business Plan Feature</p>
                <p className="text-slate-400 text-sm mt-2">
                  The full Nigerian Tax Filing Guide — PAYE, VAT returns, CIT, and WHT step-by-step walkthroughs — is available on the <strong className="text-amber-300">Business</strong> plan.
                </p>
                <a href="/billing" className="btn-primary mt-5 inline-flex items-center gap-2 text-sm">
                  <Star size={14} /> Upgrade to Business
                </a>
              </div>
            </div>
          )}
          <div className={proPlan ? 'blur-sm pointer-events-none select-none' : ''}>
          <div>
            <h2 className="text-white font-semibold">Nigerian Tax Filing Guide</h2>
            <p className="text-slate-500 text-xs mt-0.5">Step-by-step instructions for filing your taxes — simplified for business owners and employees.</p>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            {/* Personal Income Tax */}
            <div className="card space-y-4">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 bg-blue-500/15 rounded-xl flex items-center justify-center shrink-0">
                  <span className="text-blue-400 text-lg font-bold">₦</span>
                </div>
                <div>
                  <h3 className="text-white font-semibold">Personal Income Tax (PIT)</h3>
                  <p className="text-slate-400 text-xs mt-0.5">For individuals, sole traders, and employees — governed by PITA</p>
                </div>
              </div>

              <div className="space-y-3">
                {[
                  {
                    step: '1', title: 'Get your TIN',
                    detail: 'Register at any FIRS office or via JTB online portal to obtain your Tax Identification Number (TIN). Free and required for all filings.',
                    link: 'https://apps.jtb.gov.ng/TinSearch',
                    linkLabel: 'JTB TIN Portal',
                  },
                  {
                    step: '2', title: 'File annual return (Form A)',
                    detail: 'Employees: Your employer withholds PAYE monthly. At year end (by 31 March), file Form A via TaxPro MAX to confirm total income and deductions.',
                    link: 'https://taxpromax.firs.gov.ng/',
                    linkLabel: 'TaxPro MAX',
                  },
                  {
                    step: '3', title: 'Pay any tax balance',
                    detail: 'After filing, generate a payment reference from TaxPro MAX and pay at any bank, via bank transfer, or USSD. Deadline: 31 March every year.',
                    link: 'https://taxpromax.firs.gov.ng/',
                    linkLabel: 'Pay on TaxPro MAX',
                  },
                  {
                    step: '4', title: 'Keep your tax clearance',
                    detail: 'After payment, download your Tax Clearance Certificate (TCC) valid for 3 years. Required for government contracts, land purchases, and passports.',
                    link: 'https://taxpromax.firs.gov.ng/',
                    linkLabel: 'Download TCC',
                  },
                ].map((item) => (
                  <div key={item.step} className="flex gap-3">
                    <div className="w-6 h-6 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center text-xs font-bold shrink-0 mt-0.5">{item.step}</div>
                    <div>
                      <p className="text-sm font-medium text-white">{item.title}</p>
                      <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">{item.detail}</p>
                      <button
                        onClick={() => openExternal(item.link)}
                        className="inline-flex items-center gap-1 text-xs text-brand-400 hover:text-brand-300 mt-1"
                      >
                        <ExternalLink size={10} /> {item.linkLabel}
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              <div className="p-3 bg-blue-500/5 border border-blue-500/20 rounded-xl">
                <p className="text-xs font-semibold text-blue-400 mb-1">Quick Reference — PAYE Brackets (Annual)</p>
                <div className="grid grid-cols-2 gap-1 text-xs">
                  {[
                    ['First ₦300k', '7%'], ['Next ₦300k', '11%'],
                    ['Next ₦500k', '15%'], ['Next ₦500k', '19%'],
                    ['Next ₦1.6M', '21%'], ['Above ₦3.2M', '24%'],
                  ].map(([band, rate]) => (
                    <div key={band} className="flex justify-between">
                      <span className="text-slate-400">{band}</span>
                      <span className="text-white font-mono font-semibold">{rate}</span>
                    </div>
                  ))}
                </div>
                <p className="text-[10px] text-slate-500 mt-2">Minimum tax: 1% of gross income applies when computed PAYE is lower.</p>
              </div>
            </div>

            {/* Corporate Income Tax */}
            <div className="card space-y-4">
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 bg-emerald-500/15 rounded-xl flex items-center justify-center shrink-0">
                  <Building2 size={18} className="text-emerald-400" />
                </div>
                <div>
                  <h3 className="text-white font-semibold">Companies Income Tax (CIT)</h3>
                  <p className="text-slate-400 text-xs mt-0.5">For limited companies and other incorporated bodies — governed by CITA</p>
                </div>
              </div>

              <div className="space-y-3">
                {[
                  {
                    step: '1', title: 'Understand your rate',
                    detail: 'Small companies (turnover < ₦25M): 0% CIT. Medium (₦25M–₦100M): 20%. Large (above ₦100M): 30%. Assessed on profits after allowable deductions.',
                    link: 'https://www.firs.gov.ng/companies-income-tax/',
                    linkLabel: 'FIRS CIT Guide',
                  },
                  {
                    step: '2', title: 'File annual returns',
                    detail: 'File on TaxPro MAX within 6 months after your accounting year-end (e.g. if year ends Dec 31, file by Jun 30). Attach audited accounts and tax computations.',
                    link: 'https://taxpromax.firs.gov.ng/',
                    linkLabel: 'TaxPro MAX Filing',
                  },
                  {
                    step: '3', title: 'Pay in instalments (if applicable)',
                    detail: 'Large companies pay CIT in 3 instalments: 1st instalment (50%) by 6th month, 2nd (25%) by 9th month, final balance on filing. Minimum tax = 0.5% of turnover.',
                    link: 'https://taxpromax.firs.gov.ng/',
                    linkLabel: 'Pay CIT',
                  },
                  {
                    step: '4', title: 'Claim capital allowances',
                    detail: 'Reduce your tax by claiming capital allowances on qualifying assets (plant, machinery, buildings). Initial allowance + annual allowance deducted from assessable profits.',
                    link: 'https://www.firs.gov.ng/',
                    linkLabel: 'FIRS Official Portal',
                  },
                ].map((item) => (
                  <div key={item.step} className="flex gap-3">
                    <div className="w-6 h-6 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center text-xs font-bold shrink-0 mt-0.5">{item.step}</div>
                    <div>
                      <p className="text-sm font-medium text-white">{item.title}</p>
                      <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">{item.detail}</p>
                      <button
                        onClick={() => openExternal(item.link)}
                        className="inline-flex items-center gap-1 text-xs text-brand-400 hover:text-brand-300 mt-1"
                      >
                        <ExternalLink size={10} /> {item.linkLabel}
                      </button>
                    </div>
                  </div>
                ))}
              </div>

              <div className="p-3 bg-emerald-500/5 border border-emerald-500/20 rounded-xl space-y-1.5">
                <p className="text-xs font-semibold text-emerald-400">CIT Rates at a Glance</p>
                {[
                  ['Turnover < ₦25M', '0%', 'Exempt from CIT'],
                  ['Turnover ₦25M–₦100M', '20%', 'Medium company rate'],
                  ['Turnover > ₦100M', '30%', 'Large company rate'],
                  ['Minimum tax', '0.5%', 'Of gross turnover (floor)'],
                ].map(([cat, rate, note]) => (
                  <div key={cat} className="flex items-center justify-between text-xs">
                    <div>
                      <span className="text-slate-300">{cat}</span>
                      <span className="text-slate-500 ml-1.5">— {note}</span>
                    </div>
                    <span className="text-white font-mono font-bold">{rate}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* VAT Filing */}
          <div className="card space-y-3">
            <h3 className="text-white font-semibold">VAT Filing (Monthly)</h3>
            <p className="text-slate-400 text-xs">Nigerian VAT rate: 7.5%. Registered businesses must file monthly VAT returns by the 21st of the following month.</p>
            <div className="grid sm:grid-cols-3 gap-3">
              {[
                { step: '1', title: 'Register for VAT', detail: 'All businesses with annual turnover ≥ ₦25M must register for VAT on TaxPro MAX. Voluntary registration allowed below this threshold.' },
                { step: '2', title: 'Issue VAT invoices', detail: 'Charge 7.5% VAT on all taxable goods/services. Issue proper VAT invoices with your TIN, VAT registration number, and VAT amount clearly shown.' },
                { step: '3', title: 'File & remit monthly', detail: 'By the 21st of each month: log into TaxPro MAX → File VAT Return → Enter output VAT (collected) minus input VAT (paid) → Pay net VAT via bank.' },
              ].map((item) => (
                <div key={item.step} className="flex gap-3 p-3 bg-surface-900/50 rounded-xl border border-surface-700">
                  <div className="w-6 h-6 rounded-full bg-amber-500/20 text-amber-400 flex items-center justify-center text-xs font-bold shrink-0">{item.step}</div>
                  <div>
                    <p className="text-sm font-medium text-white">{item.title}</p>
                    <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">{item.detail}</p>
                  </div>
                </div>
              ))}
            </div>
            <button
              onClick={() => openExternal('https://taxpromax.firs.gov.ng/')}
              className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25"
            >
              <ExternalLink size={11} /> File VAT on TaxPro MAX
            </button>
          </div>

          {/* Key deadlines */}
          <div className="card">
            <h3 className="text-white font-semibold mb-3">Key Annual Tax Deadlines</h3>
            <div className="space-y-2">
              {[
                { deadline: '10th of each month', tax: 'PAYE Remittance', note: 'Employer remits employees\' PAYE withheld the previous month' },
                { deadline: '21st of each month', tax: 'VAT Return & Payment', note: 'Net VAT (output − input) for previous month' },
                { deadline: 'Within 7 days of salary', tax: 'Pension Contributions', note: 'Employee (8%) + employer (10%) to employee\'s PFA' },
                { deadline: '31 March', tax: 'Personal Income Tax Return', note: 'Annual income return for individuals (Form A)' },
                { deadline: '6 months after year-end', tax: 'Companies Income Tax Return', note: 'CIT return + audited accounts' },
              ].map((row) => (
                <div key={row.deadline} className="flex items-start gap-3 py-2 border-b border-surface-700 last:border-0">
                  <div className="w-28 shrink-0">
                    <span className="text-xs font-mono text-brand-400">{row.deadline}</span>
                  </div>
                  <div>
                    <p className="text-sm font-medium text-white">{row.tax}</p>
                    <p className="text-xs text-slate-400">{row.note}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
          </div>{/* end blur wrapper */}
        </div>
      )}
    </div>
  )
}
