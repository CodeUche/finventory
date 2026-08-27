import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { X, Plus, Trash2, Copy, Loader2, Grid3x3 } from 'lucide-react'
import toast from 'react-hot-toast'
import { budgetApi } from '@/services/api'
import { formatAmountInput, stripCommas } from '@/lib/utils'
import { EXPENSE_CATEGORIES, INCOME_CATEGORIES } from '@/lib/categories'
import { applyCopyForward, buildBulkLinesPayload, type GridRow } from '@/lib/budgetGrid'
import type { Budget, Account } from '@/types'

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const EXPENSE_SUGGESTIONS = EXPENSE_CATEGORIES.filter((c) => c !== 'Other (Custom)')
const INCOME_SUGGESTIONS = INCOME_CATEGORIES.filter((c) => c !== 'Other (Custom)')

function blankRow(): GridRow {
  return {
    key: `new-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    category_name: '', category_type: 'expense', account: '', months: Array(12).fill(''),
  }
}

/** Groups the budget's existing monthly lines (period_month set — annual
 * lines with no month don't fit a 12-column grid and are left to the
 * existing single-line "Add Budget Line" modal) into grid rows keyed by
 * category_name + category_type + account, one column per month. */
function rowsFromBudget(budget: Budget): GridRow[] {
  const map = new Map<string, GridRow>()
  for (const line of budget.lines) {
    if (!line.period_month) continue
    const acct = line.account ?? ''
    const key = `${line.category_name}||${line.category_type}||${acct}`
    let row = map.get(key)
    if (!row) {
      row = { key, category_name: line.category_name, category_type: line.category_type, account: acct, months: Array(12).fill('') }
      map.set(key, row)
    }
    row.months[line.period_month - 1] = String(line.budgeted_amount)
  }
  const rows = Array.from(map.values())
  return rows.length ? rows : [blankRow()]
}

interface Props {
  budget: Budget
  accounts: Account[]
  onClose: () => void
  onSaved: () => void
}

export default function BudgetGridEditor({ budget, accounts, onClose, onSaved }: Props) {
  const [rows, setRows] = useState<GridRow[]>(() => rowsFromBudget(budget))
  const [saving, setSaving] = useState(false)
  const [copyTarget, setCopyTarget] = useState<{ rowKey: string; monthIdx: number; x: number; y: number } | null>(null)
  const [copyPercent, setCopyPercent] = useState('')

  useEffect(() => { setRows(rowsFromBudget(budget)) }, [budget.id])

  const updateRow = (key: string, patch: Partial<GridRow>) =>
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)))

  const updateCell = (key: string, monthIdx: number, formattedValue: string) => {
    const raw = stripCommas(formattedValue)
    setRows((prev) => prev.map((r) => (
      r.key === key ? { ...r, months: r.months.map((m, i) => (i === monthIdx ? raw : m)) } : r
    )))
  }

  const addRow = () => setRows((prev) => [...prev, blankRow()])
  const removeRow = (key: string) => setRows((prev) => prev.filter((r) => r.key !== key))

  const openCopyMenu = (e: React.MouseEvent, rowKey: string, monthIdx: number) => {
    e.preventDefault()
    e.stopPropagation()
    setCopyPercent('')
    setCopyTarget({ rowKey, monthIdx, x: e.clientX, y: e.clientY })
  }

  const applyCopy = () => {
    if (!copyTarget) return
    const pct = copyPercent.trim() ? parseFloat(copyPercent) : 0
    setRows((prev) => prev.map((r) => (
      r.key === copyTarget.rowKey
        ? { ...r, months: applyCopyForward(r.months, copyTarget.monthIdx, isNaN(pct) ? 0 : pct) }
        : r
    )))
    setCopyTarget(null)
  }

  const handleSave = async () => {
    const hasNamelessAmount = rows.some((r) => !r.category_name.trim() && r.months.some((m) => m !== ''))
    if (hasNamelessAmount) { toast.error('Every row with an amount needs a category name'); return }
    const payload = buildBulkLinesPayload(rows)
    if (payload.length === 0) { toast.error('Enter at least one amount before saving'); return }
    setSaving(true)
    try {
      await budgetApi.bulkLines(budget.id, payload)
      toast.success(`Saved ${payload.length} budget line${payload.length !== 1 ? 's' : ''}`)
      onSaved()
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? err?.response?.data?.detail ?? 'Failed to save the grid')
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  // Rendered via a portal to document.body: this modal is wide (max-w-6xl)
  // enough to overlap the sidebar's screen region at common desktop widths
  // (~1280-1440px). If mounted in place, it inherits the "main content"
  // wrapper's z-10 stacking context (see AppLayout.tsx), which caps every
  // descendant below the sidebar's z-30 regardless of this component's own
  // z-50 — clicks on the left portion of the grid silently land on the
  // sidebar instead. A portal escapes that ceiling so z-50 is compared
  // directly against the sidebar at the root level, where it correctly
  // wins. (The pre-existing single-line "Add Budget Line" modal never hit
  // this because it's narrow enough to stay clear of the sidebar's width.)
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative card w-full max-w-6xl p-6 space-y-4 max-h-[92vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2"><Grid3x3 size={18} /> Monthly Grid — {budget.name}</h2>
            <p className="text-xs text-slate-500 mt-0.5">Build a whole year's budget lines at once. Right-click (or use the <Copy size={11} className="inline" /> icon) on a filled cell to copy it across the rest of the row, with an optional % adjustment.</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={20} /></button>
        </div>

        <datalist id="grid-expense-cats">
          {EXPENSE_SUGGESTIONS.map((c) => <option key={c} value={c} />)}
        </datalist>
        <datalist id="grid-income-cats">
          {INCOME_SUGGESTIONS.map((c) => <option key={c} value={c} />)}
        </datalist>

        <div className="overflow-x-auto border border-surface-700 rounded-xl">
          <table className="text-sm border-collapse w-full">
            <thead>
              <tr className="bg-surface-800/60 border-b border-surface-700">
                <th className="px-2 py-2 text-left text-xs font-semibold text-slate-400 uppercase sticky left-0 bg-surface-800/95 min-w-[180px]">Category</th>
                <th className="px-2 py-2 text-left text-xs font-semibold text-slate-400 uppercase min-w-[90px]">Type</th>
                <th className="px-2 py-2 text-left text-xs font-semibold text-slate-400 uppercase min-w-[160px]">Account</th>
                {MONTH_NAMES.map((m) => (
                  <th key={m} className="px-1 py-2 text-center text-xs font-semibold text-slate-400 uppercase min-w-[110px]">{m}</th>
                ))}
                <th className="px-2 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-700">
              {rows.map((row) => (
                <tr key={row.key}>
                  <td className="px-2 py-1.5 sticky left-0 bg-surface-900/95">
                    <input
                      className="input py-1 text-xs"
                      list={row.category_type === 'revenue' ? 'grid-income-cats' : 'grid-expense-cats'}
                      placeholder="Category name"
                      value={row.category_name}
                      onChange={(e) => updateRow(row.key, { category_name: e.target.value })}
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <select
                      className="input py-1 text-xs"
                      value={row.category_type}
                      onChange={(e) => updateRow(row.key, { category_type: e.target.value as GridRow['category_type'] })}
                    >
                      <option value="expense">Expense</option>
                      <option value="revenue">Revenue</option>
                    </select>
                  </td>
                  <td className="px-2 py-1.5">
                    <select
                      className="input py-1 text-xs"
                      value={row.account}
                      onChange={(e) => updateRow(row.key, { account: e.target.value })}
                    >
                      <option value="">— No account —</option>
                      {accounts.map((a) => <option key={a.id} value={a.id}>{a.code} · {a.name}</option>)}
                    </select>
                  </td>
                  {row.months.map((val, idx) => (
                    <td key={idx} className="px-1 py-1.5">
                      <div className="relative group">
                        <input
                          type="text"
                          inputMode="decimal"
                          className="input py-1 text-xs text-right font-mono pr-5"
                          placeholder="—"
                          value={val ? formatAmountInput(val) : ''}
                          onChange={(e) => updateCell(row.key, idx, e.target.value)}
                          onContextMenu={(e) => { if (val) openCopyMenu(e, row.key, idx) }}
                        />
                        {val && idx < 11 && (
                          <button
                            type="button"
                            title="Copy forward to remaining months"
                            onClick={(e) => openCopyMenu(e, row.key, idx)}
                            className="absolute right-0.5 top-1/2 -translate-y-1/2 text-slate-600 hover:text-brand-400 opacity-0 group-hover:opacity-100 transition-opacity"
                          >
                            <Copy size={11} />
                          </button>
                        )}
                      </div>
                    </td>
                  ))}
                  <td className="px-2 py-1.5">
                    <button onClick={() => removeRow(row.key)} className="text-slate-500 hover:text-red-400" title="Remove row">
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <button onClick={addRow} className="text-xs px-2.5 py-1.5 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 transition-colors inline-flex items-center gap-1">
          <Plus size={13} /> Add Row
        </button>

        <div className="flex gap-3 pt-2 border-t border-surface-700">
          <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={onClose}>Cancel</button>
          <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleSave} disabled={saving}>
            {saving ? <Loader2 size={16} className="animate-spin" /> : 'Save Grid'}
          </button>
        </div>
      </div>

      {copyTarget && (
        <>
          <div className="fixed inset-0 z-[60]" onClick={() => setCopyTarget(null)} />
          <div
            className="fixed z-[61] card p-4 w-64 space-y-3 shadow-xl"
            style={{
              top: Math.min(copyTarget.y, window.innerHeight - 180),
              left: Math.min(copyTarget.x, window.innerWidth - 270),
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <p className="text-xs text-slate-300 font-medium">Copy this value to the remaining months</p>
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Adjust by % <span className="text-slate-600">(optional, e.g. 10 or -5)</span></label>
              <input
                type="text"
                inputMode="decimal"
                className="input py-1.5 text-xs"
                placeholder="0"
                value={copyPercent}
                onChange={(e) => setCopyPercent(e.target.value)}
              />
            </div>
            <div className="flex gap-2">
              <button className="flex-1 py-1.5 rounded-lg border border-surface-600 text-slate-400 hover:text-white text-xs" onClick={() => setCopyTarget(null)}>Cancel</button>
              <button className="flex-1 py-1.5 rounded-lg bg-brand-500 text-white text-xs hover:bg-brand-600" onClick={applyCopy}>Apply</button>
            </div>
          </div>
        </>
      )}
    </div>,
    document.body,
  )
}
