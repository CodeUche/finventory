import { useEffect, useState } from 'react'
import {
  Calculator, ChevronDown, ChevronUp, Edit2, Plus, Receipt, Trash2, X, Zap, AlertCircle,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { taxApi, exciseApi, whtApi } from '@/services/api'
import { formatCurrency } from '@/lib/utils'
import type { TaxClass, TaxConfig, ExciseDuty, WHTRate, WHTTransaction } from '@/types'

// ── Types ──────────────────────────────────────────────────────────────────────

type Tab = 'vat' | 'income' | 'tools' | 'excise' | 'wht'

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

export default function TaxPage() {
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
        ] as [Tab, string][]).map(([t, label]) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={tab === t
              ? 'px-4 py-2 rounded-lg text-sm font-semibold bg-brand-500 text-white whitespace-nowrap'
              : 'px-4 py-2 rounded-lg text-sm text-slate-400 hover:text-white transition-colors whitespace-nowrap'}
          >
            {label}
          </button>
        ))}
      </div>

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
              <h3 className="text-white font-semibold">Income Tax Calculator</h3>
            </div>
            <p className="text-slate-500 text-xs">Uses the tax brackets you configured above.</p>

            <div className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
                  Annual Income
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
                {calculating ? 'Calculating…' : 'Calculate Tax'}
              </button>
            </div>

            {calcResult && (
              <div className="mt-4 space-y-2 border-t border-surface-700 pt-4">
                {Object.entries(calcResult).map(([k, v]) => (
                  <div key={k} className="flex justify-between text-sm">
                    <span className="text-slate-400 capitalize">{k.replace(/_/g, ' ')}</span>
                    <span className="text-white font-medium font-mono">
                      {typeof v === 'number' || (typeof v === 'string' && !isNaN(+v))
                        ? formatCurrency(String(v))
                        : String(v)}
                    </span>
                  </div>
                ))}
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
                <input
                  type="date" className="input"
                  value={vatStart} onChange={(e) => setVatStart(e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
                  Period End
                </label>
                <input
                  type="date" className="input"
                  value={vatEnd} onChange={(e) => setVatEnd(e.target.value)}
                />
              </div>
              <button
                onClick={handleVatReport} disabled={vatLoading}
                className="btn-primary w-full disabled:opacity-50"
              >
                {vatLoading ? 'Generating…' : 'Generate VAT Report'}
              </button>
            </div>

            {vatResult && (
              <div className="mt-4 space-y-2 border-t border-surface-700 pt-4">
                {Object.entries(vatResult).map(([k, v]) => (
                  <div key={k} className="flex justify-between text-sm">
                    <span className="text-slate-400 capitalize">{k.replace(/_/g, ' ')}</span>
                    <span className="text-white font-medium font-mono">
                      {typeof v === 'number' || (typeof v === 'string' && !isNaN(+v))
                        ? formatCurrency(String(v))
                        : String(v)}
                    </span>
                  </div>
                ))}
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
                  <input type="date" className="input" value={exciseForm.effective_date} onChange={(e) => setExciseForm({ ...exciseForm, effective_date: e.target.value })} />
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
    </div>
  )
}
