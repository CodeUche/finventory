import { useEffect, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, X, PieChart, Loader2, ChevronDown, ChevronUp, HelpCircle, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import { budgetApi, bypassNextGets } from '@/services/api'
import { formatCurrency, formatAmountInput, stripCommas } from '@/lib/utils'
import { EXPENSE_CATEGORIES, INCOME_CATEGORIES } from '@/lib/categories'
import type { Budget, BudgetLine } from '@/types'

interface BudgetForm { name: string; fiscal_year: string; period_type: string; notes: string }
interface LineForm { category_name: string; custom_name: string; category_type: string; period_month: string; budgeted_amount: string; unit_price: string; quantity: string; description: string }

const now = new Date()
const CURRENT_YEAR = now.getFullYear()
const BLANK_BUDGET: BudgetForm = { name: '', fiscal_year: String(CURRENT_YEAR), period_type: 'monthly', notes: '' }
const BLANK_LINE: LineForm = { category_name: '', custom_name: '', category_type: 'expense', period_month: '', budgeted_amount: '', unit_price: '', quantity: '1', description: '' }

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const STATUS_BADGE: Record<string, string> = { draft: 'badge-slate', active: 'badge-green', closed: 'badge-red' }

export default function BudgetPage() {
  const [budgets, setBudgets] = useState<Budget[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedBudget, setExpandedBudget] = useState<string | null>(null)
  const [varianceData, setVarianceData] = useState<Record<string, BudgetLine[]>>({})

  const [showBudgetModal, setShowBudgetModal] = useState(false)
  const [budgetForm, setBudgetForm] = useState<BudgetForm>(BLANK_BUDGET)
  const [savingBudget, setSavingBudget] = useState(false)

  const [addLineBudgetId, setAddLineBudgetId] = useState<string | null>(null)
  const [lineForm, setLineForm] = useState<LineForm>(BLANK_LINE)
  const [savingLine, setSavingLine] = useState(false)

  const [loadingVariance, setLoadingVariance] = useState<string | null>(null)
  const [activatingBudget, setActivatingBudget] = useState<string | null>(null)
  const [showVarianceHelp, setShowVarianceHelp] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const bRes = await budgetApi.list()
      setBudgets(bRes.data.results ?? bRes.data)
    } catch { toast.error('Failed to load budgets') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useDataRefresh(load)

  const handleCreateBudget = async () => {
    if (!budgetForm.name.trim()) { toast.error('Budget name is required'); return }
    const year = parseInt(budgetForm.fiscal_year)
    if (isNaN(year) || year < CURRENT_YEAR) {
      toast.error(`Fiscal year must be ${CURRENT_YEAR} or later — you cannot create budgets for past years`)
      return
    }
    setSavingBudget(true)
    try {
      await budgetApi.create({ ...budgetForm, fiscal_year: year })
      toast.success('Budget created')
      setShowBudgetModal(false)
      setBudgetForm(BLANK_BUDGET)
      load()
    } catch { toast.error('Failed to create budget') }
    finally { setSavingBudget(false) }
  }

  const handleActivate = async (b: Budget) => {
    const newStatus = b.status === 'draft' ? 'active' : b.status === 'active' ? 'closed' : 'active'
    setActivatingBudget(b.id)
    try {
      await budgetApi.update(b.id, { status: newStatus })
      toast.success(`Budget ${newStatus === 'active' ? 'activated' : newStatus === 'closed' ? 'closed' : 'reopened'}`)
      load()
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.response?.data?.status?.[0] || 'Failed to update status'
      toast.error(msg)
    } finally {
      setActivatingBudget(null)
    }
  }

  // Resolve the final category_name (use custom if "Other" selected)
  const resolvedCategoryName = () => {
    if (lineForm.category_name === 'Other (Custom)') return lineForm.custom_name.trim()
    return lineForm.category_name
  }

  const handleAddLine = async () => {
    if (!addLineBudgetId) return
    const catName = resolvedCategoryName()
    if (!catName) { toast.error('Enter or select a category'); return }
    if (!lineForm.budgeted_amount) { toast.error('Enter a budgeted amount'); return }
    setSavingLine(true)
    try {
      await budgetApi.addLine(addLineBudgetId, {
        category_name: catName,
        category_type: lineForm.category_type,
        period_month: lineForm.period_month ? parseInt(lineForm.period_month) : null,
        budgeted_amount: parseFloat(stripCommas(lineForm.budgeted_amount)),
        ...(lineForm.unit_price ? { unit_price: parseFloat(stripCommas(lineForm.unit_price)) } : {}),
        quantity: parseFloat(lineForm.quantity) || 1,
        description: lineForm.description,
      })
      toast.success('Budget line added')
      setAddLineBudgetId(null)
      setLineForm(BLANK_LINE)
      load()
    } catch { toast.error('Failed to add budget line') }
    finally { setSavingLine(false) }
  }

  const handleLoadVariance = async (budgetId: string) => {
    setLoadingVariance(budgetId)
    try {
      const { data } = await budgetApi.variance(budgetId)
      setVarianceData({ ...varianceData, [budgetId]: data.lines ?? data })
    } catch { toast.error('Failed to load variance data') }
    finally { setLoadingVariance(null) }
  }

  const getLinesForBudget = (b: Budget): BudgetLine[] => varianceData[b.id] ?? b.lines
  const categoryOptions = lineForm.category_type === 'revenue' ? INCOME_CATEGORIES : EXPENSE_CATEGORIES

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Budgets</h1>
          <p className="text-slate-400 text-sm">{budgets.length} budgets</p>
        </div>
        <div className="flex items-center gap-2 sm:ml-auto">
          <button onClick={() => { bypassNextGets(); load() }} disabled={loading} className="btn-ghost p-2 text-slate-400 hover:text-white" title="Refresh">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <button className="btn-primary" onClick={() => setShowBudgetModal(true)}>
            <Plus size={16} /> New Budget
          </button>
        </div>
      </div>

      {/* What is variance? help card */}
      <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl px-4 py-3">
        <button
          onClick={() => setShowVarianceHelp(!showVarianceHelp)}
          className="flex items-center gap-2 text-blue-400 text-sm font-medium w-full text-left"
        >
          <HelpCircle size={16} />
          What is a Budget Line and what does Variance mean?
          {showVarianceHelp ? <ChevronUp size={14} className="ml-auto" /> : <ChevronDown size={14} className="ml-auto" />}
        </button>
        {showVarianceHelp && (
          <div className="mt-3 space-y-2 text-sm text-slate-300">
            <p><strong className="text-white">Budget Line:</strong> A single planned spending (or income) target for a specific category. For example: "₦500,000 for Salaries in January". Think of it like a spending promise you make to yourself for your business.</p>
            <p><strong className="text-white">Variance:</strong> The difference between what you planned to spend and what you actually spent. A <span className="text-emerald-400">green/positive variance</span> means you spent less than planned (good!). A <span className="text-red-400">red/negative variance</span> means you exceeded your budget (over budget — needs attention).</p>
            <p><strong className="text-white">Actual Amount:</strong> You do <em>not</em> enter actual amounts manually. They are automatically pulled from your recorded expenses and income in the <strong>Expenses &amp; Income</strong> section that match the budget line's category. Record your real transactions there, then click "Variance" to see how you're tracking.</p>
            <p className="text-slate-400 text-xs">Click "Variance" on any budget to compare planned vs actual figures from your recorded expenses and income.</p>
          </div>
        )}
      </div>

      {/* Budget list */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="card p-5 animate-pulse">
              <div className="h-5 bg-surface-700 rounded w-48 mb-2" />
              <div className="h-3 bg-surface-700 rounded w-32" />
            </div>
          ))}
        </div>
      ) : budgets.length === 0 ? (
        <div className="card p-12 text-center">
          <PieChart size={36} className="mx-auto mb-3 text-slate-600" />
          <p className="text-slate-400 font-medium">No budgets yet</p>
          <p className="text-slate-500 text-sm mt-1 mb-4">Create your first budget to plan and track your business spending</p>
          <button onClick={() => setShowBudgetModal(true)} className="btn-primary mt-2 inline-flex items-center gap-2 text-sm">
            <Plus size={14} /> Create First Budget
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          {budgets.map((b) => (
            <div key={b.id} className="card overflow-hidden">
              <div className="p-5 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <button onClick={() => setExpandedBudget(expandedBudget === b.id ? null : b.id)} className="text-slate-400 hover:text-white">
                    {expandedBudget === b.id ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </button>
                  <div>
                    <p className="text-white font-semibold">{b.name}</p>
                    <p className="text-slate-500 text-xs">{b.fiscal_year} · {b.period_type} · {b.lines.length} line{b.lines.length !== 1 ? 's' : ''}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={STATUS_BADGE[b.status] ?? 'badge-slate'}>{b.status}</span>
                  <button onClick={() => { setAddLineBudgetId(b.id); setLineForm(BLANK_LINE) }} className="text-xs px-2.5 py-1 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 transition-colors">
                    + Line
                  </button>
                  {!varianceData[b.id] && (
                    <button onClick={() => handleLoadVariance(b.id)} disabled={loadingVariance === b.id} className="text-xs px-2.5 py-1 rounded-lg bg-surface-700 text-slate-400 hover:text-white transition-colors flex items-center gap-1">
                      {loadingVariance === b.id ? <Loader2 size={11} className="animate-spin" /> : null}
                      Variance
                    </button>
                  )}
                  <button
                    onClick={() => handleActivate(b)}
                    disabled={activatingBudget === b.id}
                    className={`text-xs px-2.5 py-1 rounded-lg transition-colors flex items-center gap-1 disabled:opacity-50 ${b.status === 'active' ? 'bg-red-500/10 text-red-400 hover:bg-red-500/20' : 'bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20'}`}
                  >
                    {activatingBudget === b.id ? <Loader2 size={11} className="animate-spin" /> : null}
                    {b.status === 'active' ? 'Close' : b.status === 'draft' ? 'Activate' : 'Reopen'}
                  </button>
                </div>
              </div>

              {expandedBudget === b.id && (
                <div className="border-t border-surface-700">
                  {getLinesForBudget(b).length === 0 ? (
                    <div className="p-6 text-center text-slate-500 text-sm">
                      No budget lines yet.{' '}
                      <button onClick={() => { setAddLineBudgetId(b.id); setLineForm(BLANK_LINE) }} className="text-brand-400 hover:underline">Add a line</button>
                    </div>
                  ) : (
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-surface-700 bg-surface-800/50">
                          {['Category', 'Type', 'Month', 'Budgeted', 'Actual', 'Variance', ''].map((h) => (
                            <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-surface-700">
                        {getLinesForBudget(b).map((line) => {
                          const variance = line.variance ? parseFloat(String(line.variance)) : null
                          const isOver = variance !== null && variance < 0
                          return (
                            <tr key={line.id} className="table-row">
                              <td className="px-4 py-3 text-slate-300">{line.category_name || 'Uncategorized'}</td>
                              <td className="px-4 py-3"><span className={line.category_type === 'revenue' ? 'badge-green' : 'badge-red'}>{line.category_type}</span></td>
                              <td className="px-4 py-3 text-slate-400">{line.period_month ? MONTH_NAMES[line.period_month - 1] : 'All'}</td>
                              <td className="px-4 py-3 font-mono text-white">{formatCurrency(line.budgeted_amount)}</td>
                              <td className="px-4 py-3 font-mono text-slate-400">{line.actual_amount ? formatCurrency(String(line.actual_amount)) : '—'}</td>
                              <td className="px-4 py-3 font-mono">
                                {variance !== null ? (
                                  <span className={isOver ? 'text-red-400' : 'text-emerald-400'}>
                                    {isOver ? '-' : '+'}{formatCurrency(String(Math.abs(variance)))}
                                  </span>
                                ) : '—'}
                              </td>
                              <td className="px-4 py-3">
                                {isOver && <span className="badge-red text-xs">Over Budget</span>}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* New Budget Modal */}
      {showBudgetModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowBudgetModal(false)} />
          <div className="relative card w-full max-w-md p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">New Budget</h2>
              <button onClick={() => setShowBudgetModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Budget Name *</label>
                <input className="input" placeholder="e.g. 2026 Operating Budget" value={budgetForm.name} onChange={(e) => setBudgetForm({ ...budgetForm, name: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Fiscal Year *</label>
                <input
                  type="number"
                  className="input"
                  min={CURRENT_YEAR}
                  max={CURRENT_YEAR + 10}
                  value={budgetForm.fiscal_year}
                  onChange={(e) => setBudgetForm({ ...budgetForm, fiscal_year: e.target.value })}
                />
                <p className="text-xs text-slate-600 mt-1">Min: {CURRENT_YEAR} (cannot create past budgets)</p>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Period Type</label>
                <select className="input" value={budgetForm.period_type} onChange={(e) => setBudgetForm({ ...budgetForm, period_type: e.target.value })}>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                  <option value="quarterly">Quarterly</option>
                  <option value="annual">Annual</option>
                </select>
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Notes</label>
                <textarea className="input resize-none" rows={2} value={budgetForm.notes} onChange={(e) => setBudgetForm({ ...budgetForm, notes: e.target.value })} />
              </div>
            </div>
            <div className="flex gap-3">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowBudgetModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleCreateBudget} disabled={savingBudget}>
                {savingBudget ? <Loader2 size={16} className="animate-spin" /> : 'Create Budget'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Budget Line Modal */}
      {addLineBudgetId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setAddLineBudgetId(null)} />
          <div className="relative card w-full max-w-md p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Add Budget Line</h2>
              <button onClick={() => setAddLineBudgetId(null)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <p className="text-xs text-slate-500 -mt-2">A budget line is one planned spending or income target for a specific category.</p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Type *</label>
                <select className="input" value={lineForm.category_type} onChange={(e) => setLineForm({ ...lineForm, category_type: e.target.value, category_name: '' })}>
                  <option value="expense">Expense (Money Out)</option>
                  <option value="revenue">Revenue (Money In)</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Month (leave blank for full year)</label>
                <select className="input" value={lineForm.period_month} onChange={(e) => setLineForm({ ...lineForm, period_month: e.target.value })}>
                  <option value="">All Periods / Full Year</option>
                  {MONTH_NAMES.map((m, i) => <option key={i} value={String(i + 1)}>{m}</option>)}
                </select>
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Category *</label>
                <select
                  className="input"
                  value={lineForm.category_name}
                  onChange={(e) => setLineForm({ ...lineForm, category_name: e.target.value, custom_name: '' })}
                >
                  <option value="">— Select a category —</option>
                  {categoryOptions.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              {lineForm.category_name === 'Other (Custom)' && (
                <div className="col-span-2">
                  <label className="text-xs text-slate-400 mb-1 block">Custom Category Name *</label>
                  <input
                    className="input"
                    placeholder="e.g. Vehicle Maintenance, Packaging Materials…"
                    value={lineForm.custom_name}
                    onChange={(e) => setLineForm({ ...lineForm, custom_name: e.target.value })}
                  />
                </div>
              )}
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Unit Price</label>
                <input
                  type="text"
                  inputMode="decimal"
                  className="input"
                  placeholder="e.g. 5,000"
                  value={lineForm.unit_price}
                  onChange={(e) => {
                    const up = formatAmountInput(e.target.value)
                    const qty = parseFloat(lineForm.quantity) || 1
                    const total = parseFloat(stripCommas(up)) * qty
                    setLineForm({ ...lineForm, unit_price: up, budgeted_amount: total > 0 ? formatAmountInput(String(total)) : lineForm.budgeted_amount })
                  }}
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Quantity</label>
                <input
                  type="number"
                  min="1"
                  className="input"
                  placeholder="1"
                  value={lineForm.quantity}
                  onChange={(e) => {
                    const qty = parseFloat(e.target.value) || 1
                    const up = parseFloat(stripCommas(lineForm.unit_price)) || 0
                    const total = up * qty
                    setLineForm({ ...lineForm, quantity: e.target.value, budgeted_amount: total > 0 ? formatAmountInput(String(total)) : lineForm.budgeted_amount })
                  }}
                />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Budgeted Amount *</label>
                <input
                  type="text"
                  inputMode="decimal"
                  className="input"
                  placeholder="e.g. 500,000"
                  value={lineForm.budgeted_amount}
                  onChange={(e) => setLineForm({ ...lineForm, budgeted_amount: formatAmountInput(e.target.value) })}
                />
                {lineForm.unit_price && lineForm.quantity && (
                  <p className="text-xs text-slate-500 mt-1">
                    {formatAmountInput(lineForm.unit_price)} × {lineForm.quantity} = calculated above
                  </p>
                )}
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Description <span className="text-slate-600 font-normal">(optional)</span></label>
                <input
                  className="input"
                  placeholder="Brief note about this budget line"
                  value={lineForm.description}
                  onChange={(e) => setLineForm({ ...lineForm, description: e.target.value })}
                />
              </div>
            </div>
            <div className="flex gap-3">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setAddLineBudgetId(null)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleAddLine} disabled={savingLine}>
                {savingLine ? <Loader2 size={16} className="animate-spin" /> : 'Add Line'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
