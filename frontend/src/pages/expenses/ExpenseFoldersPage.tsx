import { useEffect, useState, useCallback } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { useSearchParams } from 'react-router-dom'
import {
  Folder, FolderOpen, FolderPlus, Plus, ChevronRight, Home,
  Trash2, Edit2, ArrowUpCircle, ArrowDownCircle, Loader2, X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { expenseApi } from '@/services/api'
import { formatCurrency, formatDate, formatAmountInput, stripCommas } from '@/lib/utils'
import { EXPENSE_CATEGORIES, INCOME_CATEGORIES } from '@/lib/categories'
import { useAuthStore } from '@/store/authStore'
import type { Expense, ExpenseGroup } from '@/types'
import DateInput from '@/components/DateInput'

const PAYMENT_METHODS = [
  { value: 'cash', label: 'Cash' },
  { value: 'bank', label: 'Bank Transfer' },
  { value: 'card', label: 'Card' },
  { value: 'cheque', label: 'Cheque' },
]

interface GroupForm { name: string; description: string; group_date: string }
interface ExpenseForm {
  category_label: string; amount: string; is_income: boolean
  description: string; expense_date: string; payment_method: string
}

const today = new Date().toISOString().split('T')[0]
const BLANK_GROUP: GroupForm = { name: '', description: '', group_date: today }
const BLANK_EXP: ExpenseForm = {
  category_label: '', amount: '', is_income: false,
  description: '', expense_date: today, payment_method: 'cash',
}

export default function ExpenseFoldersPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { organisation } = useAuthStore()
  const currency = organisation?.currency ?? 'NGN'

  // Current folder state
  const currentGroupId = searchParams.get('group') ?? null
  const [currentGroup, setCurrentGroup] = useState<ExpenseGroup | null>(null)
  const [children, setChildren] = useState<ExpenseGroup[]>([])
  const [expenses, setExpenses] = useState<Expense[]>([])
  const [loading, setLoading] = useState(true)

  // Folder modal
  const [showFolderModal, setShowFolderModal] = useState(false)
  const [editingGroup, setEditingGroup] = useState<ExpenseGroup | null>(null)
  const [groupForm, setGroupForm] = useState<GroupForm>(BLANK_GROUP)
  const [savingGroup, setSavingGroup] = useState(false)

  // Expense modal
  const [showExpModal, setShowExpModal] = useState(false)
  const [expForm, setExpForm] = useState<ExpenseForm>(BLANK_EXP)
  const [savingExp, setSavingExp] = useState(false)

  // Entry type filter for folder contents: 'all' | 'expense' | 'income'
  const [entryFilter, setEntryFilter] = useState<'all' | 'expense' | 'income'>('all')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      if (currentGroupId) {
        const { data } = await expenseApi.groupContents(currentGroupId)
        setCurrentGroup(data.group)
        setChildren(data.children)
        setExpenses(data.expenses)
      } else {
        setCurrentGroup(null)
        const { data } = await expenseApi.groups({ parent: 'null' })
        setChildren(data.results ?? data)
        setExpenses([])
      }
    } catch {
      toast.error('Failed to load folder contents')
    } finally {
      setLoading(false)
    }
  }, [currentGroupId])

  useEffect(() => { load() }, [load])
  useDataRefresh(load)

  // Navigate into a folder
  const openFolder = (id: string) => setSearchParams({ group: id })

  // Navigate up to parent
  const goUp = () => {
    if (currentGroup?.parent) {
      setSearchParams({ group: currentGroup.parent })
    } else {
      setSearchParams({})
    }
  }

  // ── Folder CRUD ─────────────────────────────────────────────────────────────
  const openNewFolder = () => {
    setEditingGroup(null)
    setGroupForm(BLANK_GROUP)
    setShowFolderModal(true)
  }

  const openEditFolder = (g: ExpenseGroup) => {
    setEditingGroup(g)
    setGroupForm({ name: g.name, description: g.description, group_date: g.group_date ?? today })
    setShowFolderModal(true)
  }

  const handleSaveFolder = async () => {
    if (!groupForm.name.trim()) { toast.error('Folder name is required'); return }
    setSavingGroup(true)
    try {
      const payload = {
        name: groupForm.name.trim(),
        description: groupForm.description,
        group_date: groupForm.group_date || null,
        parent: currentGroupId ?? null,
      }
      if (editingGroup) {
        await expenseApi.updateGroup(editingGroup.id, payload)
        toast.success('Folder updated')
      } else {
        await expenseApi.createGroup(payload)
        toast.success('Folder created')
      }
      setShowFolderModal(false)
      load()
    } catch {
      toast.error('Failed to save folder')
    } finally {
      setSavingGroup(false) }
  }

  const handleDeleteFolder = async (g: ExpenseGroup) => {
    const hasContent = g.children_count > 0 || g.expense_count > 0
    const warn = hasContent ? ` It contains ${g.children_count} sub-folder(s) and ${g.expense_count} item(s) which will also be deleted.` : ''
    if (!confirm(`Delete folder "${g.name}"?${warn}`)) return
    try {
      await expenseApi.deleteGroup(g.id)
      toast.success('Folder deleted')
      load()
    } catch {
      toast.error('Cannot delete folder')
    }
  }

  // ── Expense CRUD ─────────────────────────────────────────────────────────────
  const handleSaveExpense = async () => {
    if (!expForm.amount) { toast.error('Amount is required'); return }
    setSavingExp(true)
    try {
      await expenseApi.create({
        category_label: expForm.category_label || (expForm.is_income ? 'Miscellaneous Income' : 'Uncategorized'),
        amount: stripCommas(expForm.amount),
        is_income: expForm.is_income,
        description: expForm.description,
        expense_date: expForm.expense_date,
        payment_method: expForm.payment_method,
        group: currentGroupId,
      })
      toast.success(`${expForm.is_income ? 'Income' : 'Expense'} added`)
      setShowExpModal(false)
      setExpForm(BLANK_EXP)
      load()
    } catch {
      toast.error('Failed to save entry')
    } finally {
      setSavingExp(false)
    }
  }

  // ── Breadcrumb ────────────────────────────────────────────────────────────────
  const ancestors = currentGroup?.ancestors ?? []

  const totalExpenses = expenses.filter(e => !e.is_income).reduce((s, e) => s + parseFloat(e.amount), 0)
  const totalIncome = expenses.filter(e => e.is_income).reduce((s, e) => s + parseFloat(e.amount), 0)

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Income &amp; Expenses</h1>
          <p className="text-slate-400 text-sm mt-0.5">Organise your expenses and income into folders</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={openNewFolder} className="btn-ghost flex items-center gap-2">
            <FolderPlus size={15} />
            New Folder
          </button>
          {currentGroupId && (
            <button onClick={() => setShowExpModal(true)} className="btn-primary flex items-center gap-2">
              <Plus size={15} />
              Add Entry
            </button>
          )}
        </div>
      </div>

      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 text-sm flex-wrap">
        <button
          onClick={() => setSearchParams({})}
          className="flex items-center gap-1 text-slate-400 hover:text-white transition-colors"
        >
          <Home size={13} />
          <span>Root</span>
        </button>
        {ancestors.map((a) => (
          <span key={a.id} className="flex items-center gap-1.5">
            <ChevronRight size={12} className="text-slate-600" />
            <button
              onClick={() => setSearchParams({ group: a.id })}
              className="text-slate-400 hover:text-white transition-colors"
            >
              {a.name}
            </button>
          </span>
        ))}
        {currentGroup && (
          <span className="flex items-center gap-1.5">
            <ChevronRight size={12} className="text-slate-600" />
            <span className="text-white font-medium">{currentGroup.name}</span>
          </span>
        )}
      </div>

      {/* Up button + folder info */}
      {currentGroup && (
        <div className="flex items-center gap-4">
          <button onClick={goUp} className="btn-ghost text-sm flex items-center gap-1.5 py-1.5">
            <ChevronRight size={14} className="rotate-180" />
            Up to {currentGroup.parent_name ?? 'Root'}
          </button>
          {currentGroup.group_date && (
            <span className="text-slate-500 text-sm">{formatDate(currentGroup.group_date)}</span>
          )}
          {currentGroup.description && (
            <span className="text-slate-400 text-sm italic">{currentGroup.description}</span>
          )}
        </div>
      )}

      {loading ? (
        <div className="card p-12 text-center text-slate-500">Loading…</div>
      ) : (
        <div className="space-y-4">
          {/* Sub-folders */}
          {children.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
                Folders ({children.length})
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                {children.map((g) => (
                  <div
                    key={g.id}
                    className="card p-4 cursor-pointer hover:border-brand-500/40 transition-colors group"
                    onClick={() => openFolder(g.id)}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-10 h-10 rounded-xl bg-brand-500/10 flex items-center justify-center shrink-0">
                          <Folder size={18} className="text-brand-400" />
                        </div>
                        <div className="min-w-0">
                          <p className="font-semibold text-white text-sm truncate">{g.name}</p>
                          {g.group_date && (
                            <p className="text-xs text-slate-500 mt-0.5">{formatDate(g.group_date)}</p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0 ml-2">
                        <button
                          onClick={(e) => { e.stopPropagation(); openEditFolder(g) }}
                          className="p-1 text-slate-500 hover:text-white hover:bg-surface-600 rounded transition-colors"
                        >
                          <Edit2 size={12} />
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDeleteFolder(g) }}
                          className="p-1 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>
                    <div className="mt-3 flex items-center gap-3 text-xs text-slate-500">
                      {g.children_count > 0 && (
                        <span className="flex items-center gap-1">
                          <Folder size={11} />
                          {g.children_count} folder{g.children_count !== 1 ? 's' : ''}
                        </span>
                      )}
                      {g.expense_count > 0 && (
                        <span>{g.expense_count} item{g.expense_count !== 1 ? 's' : ''}</span>
                      )}
                      {g.expense_count === 0 && g.children_count === 0 && (
                        <span className="italic">Empty</span>
                      )}
                    </div>
                    {parseFloat(g.total_amount) > 0 && (
                      <p className="mt-2 text-xs font-semibold text-brand-400">
                        {formatCurrency(parseFloat(g.total_amount), currency)}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Expenses / Income items in this folder */}
          {currentGroupId && (
            <div>
              <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  {(['all', 'expense', 'income'] as const).map((f) => (
                    <button
                      key={f}
                      onClick={() => setEntryFilter(f)}
                      className={`text-xs px-3 py-1 rounded-lg border transition-colors capitalize ${
                        entryFilter === f
                          ? f === 'income' ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-400'
                            : f === 'expense' ? 'bg-red-500/15 border-red-500/40 text-red-400'
                            : 'bg-brand-500/15 border-brand-500/40 text-brand-400'
                          : 'border-surface-600 text-slate-500 hover:text-slate-300'
                      }`}
                    >
                      {f === 'all' ? `All (${expenses.length})` : f === 'income' ? `Income (${expenses.filter(e => e.is_income).length})` : `Expenses (${expenses.filter(e => !e.is_income).length})`}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-4 text-xs">
                  <span className="text-red-400">Exp: {formatCurrency(totalExpenses, currency)}</span>
                  <span className="text-emerald-400">Inc: {formatCurrency(totalIncome, currency)}</span>
                </div>
              </div>

              {expenses.length === 0 ? (
                <div className="card p-8 text-center">
                  <p className="text-slate-400">No entries yet in this folder</p>
                  <button
                    onClick={() => setShowExpModal(true)}
                    className="btn-primary mt-4 inline-flex items-center gap-2"
                  >
                    <Plus size={14} />
                    Add First Entry
                  </button>
                </div>
              ) : (
                <div className="card overflow-hidden">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-surface-700">
                        <th className="text-left px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Date</th>
                        <th className="text-left px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Category</th>
                        <th className="text-left px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Description</th>
                        <th className="text-right px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Amount</th>
                        <th className="px-5 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Method</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-surface-700">
                      {expenses.filter(e => entryFilter === 'all' || (entryFilter === 'income' ? e.is_income : !e.is_income)).map((e) => (
                        <tr key={e.id} className="table-row">
                          <td className="px-5 py-3 text-slate-400 text-sm">{formatDate(e.expense_date)}</td>
                          <td className="px-5 py-3">
                            <div className="flex items-center gap-2">
                              {e.is_income
                                ? <ArrowUpCircle size={14} className="text-emerald-400 shrink-0" />
                                : <ArrowDownCircle size={14} className="text-red-400 shrink-0" />
                              }
                              <span className="text-sm text-slate-300">{e.category_name}</span>
                            </div>
                          </td>
                          <td className="px-5 py-3 text-slate-400 text-sm max-w-xs truncate">{e.description || '—'}</td>
                          <td className={`px-5 py-3 text-right font-semibold text-sm ${e.is_income ? 'text-emerald-400' : 'text-white'}`}>
                            {e.is_income ? '+' : '-'}{formatCurrency(parseFloat(e.amount), currency)}
                          </td>
                          <td className="px-5 py-3 text-center">
                            <span className="text-xs text-slate-500 capitalize">{e.payment_method}</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* Empty root state */}
          {!currentGroupId && children.length === 0 && (
            <div className="card p-16 text-center">
              <FolderOpen size={48} className="mx-auto text-slate-600 mb-4" />
              <p className="text-slate-300 font-semibold text-lg">No folders yet</p>
              <p className="text-slate-500 text-sm mt-1 mb-5">
                Create folders to organise expenses by event, trip, month, or project
              </p>
              <button onClick={openNewFolder} className="btn-primary inline-flex items-center gap-2">
                <FolderPlus size={15} />
                Create First Folder
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── New / Edit Folder Modal ────────────────────────────────────────── */}
      {showFolderModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-md shadow-2xl">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-bold text-white">
                {editingGroup ? 'Edit Folder' : 'New Folder'}
              </h2>
              <button onClick={() => setShowFolderModal(false)} className="text-slate-500 hover:text-white">
                <X size={18} />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="label">Folder Name *</label>
                <input
                  className="input"
                  placeholder="e.g., January 2026 Market Run"
                  value={groupForm.name}
                  onChange={(e) => setGroupForm({ ...groupForm, name: e.target.value })}
                  autoFocus
                />
              </div>
              <div>
                <label className="label">Date (optional)</label>
                <DateInput
                  value={groupForm.group_date}
                  onChange={(v) => setGroupForm({ ...groupForm, group_date: v })}
                />
              </div>
              <div>
                <label className="label">Description (optional)</label>
                <input
                  className="input"
                  placeholder="Brief note about this folder"
                  value={groupForm.description}
                  onChange={(e) => setGroupForm({ ...groupForm, description: e.target.value })}
                />
              </div>
              {currentGroup && (
                <p className="text-xs text-slate-500">
                  Will be created inside: <span className="text-slate-400 font-medium">{currentGroup.name}</span>
                </p>
              )}
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowFolderModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleSaveFolder} disabled={savingGroup} className="btn-primary flex-1 disabled:opacity-50">
                {savingGroup ? <Loader2 size={15} className="animate-spin mx-auto" /> : editingGroup ? 'Save Changes' : 'Create Folder'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── New Expense / Income Modal ────────────────────────────────────── */}
      {showExpModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-lg shadow-2xl">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-bold text-white">Add Entry</h2>
              <button onClick={() => setShowExpModal(false)} className="text-slate-500 hover:text-white">
                <X size={18} />
              </button>
            </div>

            {/* Income / Expense toggle */}
            <div className="grid grid-cols-2 gap-3 mb-5">
              {[{ v: false, label: 'Expense', icon: ArrowDownCircle, color: 'text-red-400' }, { v: true, label: 'Income', icon: ArrowUpCircle, color: 'text-emerald-400' }].map(({ v, label, icon: Icon, color }) => (
                <button
                  key={String(v)}
                  type="button"
                  onClick={() => setExpForm({ ...expForm, is_income: v, category_label: '' })}
                  className={`p-3 rounded-xl border text-sm font-medium flex items-center justify-center gap-2 transition-all ${expForm.is_income === v ? 'bg-brand-500/15 border-brand-500 text-white' : 'border-surface-600 text-slate-400 hover:border-surface-500'}`}
                >
                  <Icon size={15} className={color} />
                  {label}
                </button>
              ))}
            </div>

            <div className="space-y-4">
              <div>
                <label className="label">Category</label>
                <select
                  className="input"
                  value={expForm.category_label}
                  onChange={(e) => setExpForm({ ...expForm, category_label: e.target.value })}
                >
                  <option value="">— Select category —</option>
                  {(expForm.is_income ? INCOME_CATEGORIES : EXPENSE_CATEGORIES).map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Amount *</label>
                <input
                  className="input"
                  placeholder="0.00"
                  value={expForm.amount}
                  onChange={(e) => setExpForm({ ...expForm, amount: formatAmountInput(e.target.value) })}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Date</label>
                  <DateInput
                    value={expForm.expense_date}
                    onChange={(v) => setExpForm({ ...expForm, expense_date: v })}
                  />
                </div>
                <div>
                  <label className="label">Payment Method</label>
                  <select
                    className="input"
                    value={expForm.payment_method}
                    onChange={(e) => setExpForm({ ...expForm, payment_method: e.target.value })}
                  >
                    {PAYMENT_METHODS.map((m) => (
                      <option key={m.value} value={m.value}>{m.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label className="label">Description (optional)</label>
                <input
                  className="input"
                  placeholder="Notes or reference"
                  value={expForm.description}
                  onChange={(e) => setExpForm({ ...expForm, description: e.target.value })}
                />
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowExpModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleSaveExpense} disabled={savingExp} className="btn-primary flex-1 disabled:opacity-50">
                {savingExp ? <Loader2 size={15} className="animate-spin mx-auto" /> : 'Add Entry'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
