import { useEffect, useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  ArrowDownCircle, ArrowUpCircle, Plus, Search, X, Pencil, Loader2, Layers,
  Folder, FolderOpen, FolderPlus, ChevronRight, Home, Trash2, Edit2,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { expenseApi, budgetApi } from '@/services/api'
import { formatCurrency, formatDate, formatAmountInput, stripCommas } from '@/lib/utils'
import { EXPENSE_CATEGORIES, INCOME_CATEGORIES } from '@/lib/categories'
import { useAuthStore } from '@/store/authStore'
import type { Expense, ExpenseGroup } from '@/types'
import DateInput from '@/components/DateInput'
import YearFilter, { yearToDateParams } from '@/components/YearFilter'
import ExportButton from '@/components/ExportButton'

const PAYMENT_METHODS: { value: string; label: string }[] = [
  { value: 'cash', label: 'Cash' },
  { value: 'bank', label: 'Bank Transfer' },
  { value: 'card', label: 'Card' },
  { value: 'cheque', label: 'Cheque' },
]

interface ExpenseForm {
  category_label: string
  amount: string
  previous_price: string
  is_income: boolean
  description: string
  expense_date: string
  payment_method: string
  budget: string | null
}

interface GroupForm { name: string; description: string; group_date: string }

interface FolderExpenseForm {
  category_label: string; amount: string; previous_price: string; is_income: boolean
  description: string; expense_date: string; payment_method: string; budget: string | null
}

const today = new Date().toISOString().split('T')[0]

const BLANK: ExpenseForm = {
  category_label: '',
  amount: '',
  previous_price: '',
  is_income: false,
  description: '',
  expense_date: today,
  payment_method: 'cash',
  budget: null,
}

const BLANK_GROUP: GroupForm = { name: '', description: '', group_date: today }
const BLANK_FOLDER_EXP: FolderExpenseForm = {
  category_label: '', amount: '', previous_price: '', is_income: false,
  description: '', expense_date: today, payment_method: 'cash', budget: null,
}

export default function ExpensesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { organisation } = useAuthStore()
  const currency = organisation?.currency ?? 'NGN'

  // Active tab
  const activeTab = (searchParams.get('tab') as 'entries' | 'folders') ?? 'entries'
  const setTab = (t: 'entries' | 'folders') => {
    setSearchParams(t === 'entries' ? {} : { tab: 'folders' })
  }

  // ── ENTRIES TAB ─────────────────────────────────────────────────────────────
  const [expenses, setExpenses] = useState<Expense[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<'expense' | 'income' | ''>('')
  const [archiveYear, setArchiveYear] = useState<number | null>(null)
  const [groupByCategory, setGroupByCategory] = useState(false)

  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState<ExpenseForm>(BLANK)
  const [saving, setSaving] = useState(false)

  const [editId, setEditId] = useState<string | null>(null)
  const [showEditModal, setShowEditModal] = useState(false)
  const [editForm, setEditForm] = useState<ExpenseForm>(BLANK)

  const [budgets, setBudgets] = useState<{ id: string; name: string; status: string }[]>([])

  const loadExpenses = async () => {
    setLoading(true)
    try {
      const params: Record<string, unknown> = { search: search || undefined, ...yearToDateParams(archiveYear) }
      if (typeFilter === 'income') params.is_income = true
      if (typeFilter === 'expense') params.is_income = false
      const expRes = await expenseApi.list(params)
      setExpenses(expRes.data.results ?? expRes.data)
    } catch { toast.error('Failed to load expenses') }
    finally { setLoading(false) }
  }

  useEffect(() => { loadExpenses() }, [search, typeFilter, archiveYear])

  useEffect(() => {
    budgetApi.list().then(({ data }) => {
      const list = data.results ?? data
      setBudgets(list.filter((b: any) => b.status === 'active'))
    }).catch(() => {})
  }, [])

  const handleCreate = async () => {
    const rawAmount = stripCommas(form.amount)
    if (!rawAmount || parseFloat(rawAmount) <= 0) { toast.error('Enter a valid amount'); return }
    if (!form.expense_date) { toast.error('Select a date'); return }
    setSaving(true)
    try {
      await expenseApi.create({ ...form, amount: rawAmount, previous_price: form.previous_price ? stripCommas(form.previous_price) : null })
      toast.success(form.is_income ? 'Income recorded' : 'Expense recorded')
      setShowModal(false)
      setForm(BLANK)
      loadExpenses()
    } catch { toast.error('Failed to save') }
    finally { setSaving(false) }
  }

  const openEdit = (e: Expense) => {
    setEditId(e.id)
    setEditForm({
      category_label: e.category_name ?? '',
      amount: formatAmountInput(String(e.amount)),
      previous_price: (e as any).previous_price ? formatAmountInput(String((e as any).previous_price)) : '',
      is_income: e.is_income,
      description: e.description ?? '',
      expense_date: e.expense_date,
      payment_method: e.payment_method,
      budget: (e as any).budget ?? null,
    })
    setShowEditModal(true)
  }

  const handleUpdate = async () => {
    const rawAmount = stripCommas(editForm.amount)
    if (!rawAmount || parseFloat(rawAmount) <= 0) { toast.error('Enter a valid amount'); return }
    if (!editId) return
    setSaving(true)
    try {
      await expenseApi.update(editId, { ...editForm, amount: rawAmount })
      toast.success('Entry updated')
      setShowEditModal(false)
      loadExpenses()
    } catch { toast.error('Failed to update') }
    finally { setSaving(false) }
  }

  const totalExpenses = expenses.filter((e) => !e.is_income).reduce((s, e) => s + parseFloat(e.amount), 0)
  const totalIncome = expenses.filter((e) => e.is_income).reduce((s, e) => s + parseFloat(e.amount), 0)
  const net = totalIncome - totalExpenses

  const grouped: Record<string, { label: string; total: number; count: number; is_income: boolean }> = {}
  expenses.forEach((e) => {
    const key = `${e.is_income ? 'income' : 'expense'}__${e.category_name ?? 'Uncategorized'}`
    if (!grouped[key]) grouped[key] = { label: e.category_name ?? 'Uncategorized', total: 0, count: 0, is_income: e.is_income }
    grouped[key].total += parseFloat(String(e.amount))
    grouped[key].count += 1
  })
  const groupedEntries = Object.values(grouped).sort((a, b) => b.total - a.total)

  // ── FOLDERS TAB ─────────────────────────────────────────────────────────────
  const currentGroupId = activeTab === 'folders' ? (searchParams.get('group') ?? null) : null
  const [currentGroup, setCurrentGroup] = useState<ExpenseGroup | null>(null)
  const [children, setChildren] = useState<ExpenseGroup[]>([])
  const [folderExpenses, setFolderExpenses] = useState<Expense[]>([])
  const [folderLoading, setFolderLoading] = useState(false)

  const [showFolderModal, setShowFolderModal] = useState(false)
  const [editingGroup, setEditingGroup] = useState<ExpenseGroup | null>(null)
  const [groupForm, setGroupForm] = useState<GroupForm>(BLANK_GROUP)
  const [savingGroup, setSavingGroup] = useState(false)

  const [showFolderExpModal, setShowFolderExpModal] = useState(false)
  const [folderExpForm, setFolderExpForm] = useState<FolderExpenseForm>(BLANK_FOLDER_EXP)
  const [savingFolderExp, setSavingFolderExp] = useState(false)

  const loadFolder = useCallback(async () => {
    if (activeTab !== 'folders') return
    setFolderLoading(true)
    try {
      if (currentGroupId) {
        const { data } = await expenseApi.groupContents(currentGroupId)
        setCurrentGroup(data.group)
        setChildren(data.children)
        setFolderExpenses(data.expenses)
      } else {
        setCurrentGroup(null)
        const { data } = await expenseApi.groups({ parent: 'null' })
        setChildren(data.results ?? data)
        setFolderExpenses([])
      }
    } catch {
      toast.error('Failed to load folder contents')
    } finally {
      setFolderLoading(false)
    }
  }, [activeTab, currentGroupId])

  useEffect(() => { loadFolder() }, [loadFolder])

  const openFolder = (id: string) => setSearchParams({ tab: 'folders', group: id })

  const goUp = () => {
    if (currentGroup?.parent) {
      setSearchParams({ tab: 'folders', group: String(currentGroup.parent) })
    } else {
      setSearchParams({ tab: 'folders' })
    }
  }

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
      loadFolder()
    } catch {
      toast.error('Failed to save folder')
    } finally {
      setSavingGroup(false)
    }
  }

  const handleDeleteFolder = async (g: ExpenseGroup) => {
    const hasContent = g.children_count > 0 || g.expense_count > 0
    const warn = hasContent ? ` It contains ${g.children_count} sub-folder(s) and ${g.expense_count} item(s) which will also be deleted.` : ''
    if (!confirm(`Delete folder "${g.name}"?${warn}`)) return
    try {
      await expenseApi.deleteGroup(g.id)
      toast.success('Folder deleted')
      loadFolder()
    } catch {
      toast.error('Cannot delete folder')
    }
  }

  const handleSaveFolderExpense = async () => {
    if (!folderExpForm.amount) { toast.error('Amount is required'); return }
    setSavingFolderExp(true)
    try {
      await expenseApi.create({
        category_label: folderExpForm.category_label || (folderExpForm.is_income ? 'Miscellaneous Income' : 'Uncategorized'),
        amount: stripCommas(folderExpForm.amount),
        previous_price: folderExpForm.previous_price ? stripCommas(folderExpForm.previous_price) : null,
        is_income: folderExpForm.is_income,
        description: folderExpForm.description,
        expense_date: folderExpForm.expense_date,
        payment_method: folderExpForm.payment_method,
        budget: folderExpForm.budget || null,
        group: currentGroupId,
      })
      toast.success(`${folderExpForm.is_income ? 'Income' : 'Expense'} added`)
      setShowFolderExpModal(false)
      setFolderExpForm(BLANK_FOLDER_EXP)
      loadFolder()
    } catch {
      toast.error('Failed to save entry')
    } finally {
      setSavingFolderExp(false)
    }
  }

  const ancestors = currentGroup?.ancestors ?? []
  const folderTotalExpenses = folderExpenses.filter(e => !e.is_income).reduce((s, e) => s + parseFloat(e.amount), 0)
  const folderTotalIncome = folderExpenses.filter(e => e.is_income).reduce((s, e) => s + parseFloat(e.amount), 0)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Income & Expenses</h1>
          <p className="text-slate-400 text-sm">{activeTab === 'entries' ? `${expenses.length} entries` : 'Organise by folder'}</p>
        </div>
        <div className="sm:ml-auto flex items-center gap-2">
          {activeTab === 'entries' && (
            <button className="btn-primary" onClick={() => setShowModal(true)}>
              <Plus size={16} /> Add Entry
            </button>
          )}
          {activeTab === 'folders' && (
            <>
              <button onClick={openNewFolder} className="btn-ghost flex items-center gap-2">
                <FolderPlus size={15} />
                New Folder
              </button>
              {currentGroupId && (
                <button onClick={() => setShowFolderExpModal(true)} className="btn-primary flex items-center gap-2">
                  <Plus size={15} />
                  Add Entry
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-surface-800 border border-surface-700 rounded-xl p-1 w-fit">
        <button
          onClick={() => setTab('entries')}
          className={`px-5 py-2 rounded-lg text-sm font-medium transition-all ${
            activeTab === 'entries'
              ? 'bg-brand-500 text-white shadow'
              : 'text-slate-400 hover:text-white'
          }`}
        >
          All Entries
        </button>
        <button
          onClick={() => setTab('folders')}
          className={`px-5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-1.5 ${
            activeTab === 'folders'
              ? 'bg-brand-500 text-white shadow'
              : 'text-slate-400 hover:text-white'
          }`}
        >
          <Folder size={14} />
          Folders
        </button>
      </div>

      {/* ── ALL ENTRIES TAB ───────────────────────────────────────────────── */}
      {activeTab === 'entries' && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="card p-5 flex items-center gap-4">
              <div className="w-11 h-11 rounded-xl bg-red-500/15 flex items-center justify-center">
                <ArrowDownCircle size={22} className="text-red-400" />
              </div>
              <div>
                <p className="text-xs text-slate-400">Total Expenses</p>
                <p className="text-xl font-bold text-red-400">{formatCurrency(totalExpenses)}</p>
              </div>
            </div>

            <div className="card p-5 flex items-center gap-4">
              <div className="w-11 h-11 rounded-xl bg-emerald-500/15 flex items-center justify-center">
                <ArrowUpCircle size={22} className="text-emerald-400" />
              </div>
              <div>
                <p className="text-xs text-slate-400">Total Income</p>
                <p className="text-xl font-bold text-emerald-400">{formatCurrency(totalIncome)}</p>
              </div>
            </div>

            <div className={`card p-5 flex items-center gap-4 ${net >= 0 ? 'border-emerald-500/30' : 'border-red-500/30'}`}>
              <div className={`w-11 h-11 rounded-xl flex items-center justify-center ${net >= 0 ? 'bg-emerald-500/15' : 'bg-red-500/15'}`}>
                <span className={`text-lg font-bold ${net >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {net >= 0 ? '+' : '−'}
                </span>
              </div>
              <div>
                <p className="text-xs text-slate-400">Net</p>
                <p className={`text-xl font-bold ${net >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {formatCurrency(Math.abs(net))}
                </p>
              </div>
            </div>
          </div>

          {/* Filters */}
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                className="input pl-9"
                placeholder="Search description…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="flex gap-2 flex-wrap items-center">
              {(['', 'expense', 'income'] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTypeFilter(t)}
                  className={`px-4 py-2 rounded-xl text-sm font-medium transition-all border ${
                    typeFilter === t
                      ? 'bg-brand-500/20 border-brand-500 text-brand-400'
                      : 'border-surface-600 text-slate-400 hover:border-surface-500'
                  }`}
                >
                  {t === '' ? 'All' : t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
              <button
                onClick={() => setGroupByCategory((v) => !v)}
                className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium transition-all border ${
                  groupByCategory
                    ? 'bg-purple-500/20 border-purple-500/50 text-purple-300'
                    : 'border-surface-600 text-slate-400 hover:border-surface-500'
                }`}
              >
                <Layers size={14} />
                Group by Category
              </button>
              <YearFilter selectedYear={archiveYear} onChange={setArchiveYear} />
              <ExportButton endpoint="/expenses/" filename="expenses" params={yearToDateParams(archiveYear)} />
            </div>
          </div>

          {/* Grouped view */}
          {groupByCategory && (
            <div className="card p-0 overflow-hidden">
              <div className="px-5 py-3.5 border-b border-surface-700">
                <p className="text-sm font-semibold text-white">Category Summary</p>
              </div>
              <div className="divide-y divide-surface-700">
                {groupedEntries.length === 0 ? (
                  <p className="px-5 py-8 text-center text-slate-500">No entries</p>
                ) : groupedEntries.map((g) => (
                  <div key={`${g.is_income}-${g.label}`} className="flex items-center gap-4 px-5 py-3.5">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${g.is_income ? 'bg-emerald-500/15' : 'bg-red-500/15'}`}>
                      {g.is_income ? <ArrowUpCircle size={16} className="text-emerald-400" /> : <ArrowDownCircle size={16} className="text-red-400" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-white truncate">{g.label}</p>
                      <p className="text-xs text-slate-500">{g.count} {g.count === 1 ? 'entry' : 'entries'} · {g.is_income ? 'Income' : 'Expense'}</p>
                    </div>
                    <span className={`font-semibold text-sm ${g.is_income ? 'text-emerald-400' : 'text-red-400'}`}>
                      {g.is_income ? '+' : '−'} {formatCurrency(g.total)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Table */}
          <div className="card p-0 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700">
                    {['Date', 'Type', 'Category', 'Description', 'Payment', 'Amount', ''].map((h) => (
                      <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    Array.from({ length: 6 }).map((_, i) => (
                      <tr key={i} className="table-row">
                        {Array.from({ length: 6 }).map((_, j) => (
                          <td key={j} className="px-5 py-3.5">
                            <div className="h-4 bg-surface-700 rounded animate-pulse w-20" />
                          </td>
                        ))}
                      </tr>
                    ))
                  ) : expenses.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="px-5 py-12 text-center">
                        <ArrowDownCircle size={32} className="mx-auto mb-2 text-slate-600" />
                        <p className="text-slate-500">No entries yet</p>
                      </td>
                    </tr>
                  ) : (
                    expenses.map((e) => (
                      <tr key={e.id} className="table-row">
                        <td className="px-5 py-3.5 text-slate-400 whitespace-nowrap">{formatDate(e.expense_date)}</td>
                        <td className="px-5 py-3.5">
                          <span className={e.is_income ? 'badge-green' : 'badge-red'}>
                            {e.is_income ? 'Income' : 'Expense'}
                          </span>
                        </td>
                        <td className="px-5 py-3.5 text-slate-300">{e.category_name}</td>
                        <td className="px-5 py-3.5 text-slate-400 max-w-xs truncate">{e.description || '—'}</td>
                        <td className="px-5 py-3.5 text-slate-400">{PAYMENT_METHODS.find(m => m.value === e.payment_method)?.label ?? e.payment_method}</td>
                        <td className={`px-5 py-3.5 font-semibold ${e.is_income ? 'text-emerald-400' : 'text-red-400'}`}>
                          {e.is_income ? '+' : '−'} {formatCurrency(e.amount)}
                        </td>
                        <td className="px-5 py-3.5">
                          <button onClick={() => openEdit(e)} className="btn-ghost p-1.5 text-slate-400 hover:text-white">
                            <Pencil size={14} />
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* ── FOLDERS TAB ──────────────────────────────────────────────────── */}
      {activeTab === 'folders' && (
        <div className="space-y-4">
          {/* Breadcrumb */}
          <div className="flex items-center gap-1.5 text-sm flex-wrap">
            <button
              onClick={() => setSearchParams({ tab: 'folders' })}
              className="flex items-center gap-1 text-slate-400 hover:text-white transition-colors"
            >
              <Home size={13} />
              <span>Root</span>
            </button>
            {ancestors.map((a: { id: string; name: string }) => (
              <span key={a.id} className="flex items-center gap-1.5">
                <ChevronRight size={12} className="text-slate-600" />
                <button
                  onClick={() => setSearchParams({ tab: 'folders', group: a.id })}
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

          {/* Up button */}
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

          {folderLoading ? (
            <div className="card p-12 text-center text-slate-500">Loading…</div>
          ) : (
            <>
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

              {/* Entries inside folder */}
              {currentGroupId && (
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      Entries ({folderExpenses.length})
                    </p>
                    {folderExpenses.length > 0 && (
                      <div className="flex items-center gap-4 text-xs">
                        <span className="text-red-400">Expenses: {formatCurrency(folderTotalExpenses, currency)}</span>
                        {folderTotalIncome > 0 && (
                          <span className="text-emerald-400">Income: {formatCurrency(folderTotalIncome, currency)}</span>
                        )}
                      </div>
                    )}
                  </div>

                  {folderExpenses.length === 0 ? (
                    <div className="card p-8 text-center">
                      <p className="text-slate-400">No entries yet in this folder</p>
                      <button
                        onClick={() => setShowFolderExpModal(true)}
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
                          {folderExpenses.map((e) => (
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
            </>
          )}
        </div>
      )}

      {/* ── Edit Entry Modal ────────────────────────────────────────────────── */}
      {showEditModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowEditModal(false)} />
          <div className="relative card w-full max-w-lg p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Edit Entry</h2>
              <button onClick={() => setShowEditModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>

            <div className="flex rounded-xl overflow-hidden border border-surface-600">
              <button className={`flex-1 py-2.5 text-sm font-medium transition-colors ${!editForm.is_income ? 'bg-red-500/20 text-red-400' : 'text-slate-400 hover:bg-surface-700'}`}
                onClick={() => setEditForm({ ...editForm, is_income: false })}>Expense</button>
              <button className={`flex-1 py-2.5 text-sm font-medium transition-colors ${editForm.is_income ? 'bg-emerald-500/20 text-emerald-400' : 'text-slate-400 hover:bg-surface-700'}`}
                onClick={() => setEditForm({ ...editForm, is_income: true })}>Income</button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Amount *</label>
                <input type="text" inputMode="decimal" className="input" placeholder="0.00"
                  value={editForm.amount}
                  onChange={(e) => setEditForm({ ...editForm, amount: formatAmountInput(e.target.value) })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Date *</label>
                <DateInput value={editForm.expense_date} onChange={(v) => setEditForm({ ...editForm, expense_date: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Category</label>
                <select className="input" value={editForm.category_label}
                  onChange={(e) => setEditForm({ ...editForm, category_label: e.target.value })}>
                  <option value="">— Select —</option>
                  {(editForm.is_income ? INCOME_CATEGORIES : EXPENSE_CATEGORIES).map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Payment Method</label>
                <select className="input" value={editForm.payment_method} onChange={(e) => setEditForm({ ...editForm, payment_method: e.target.value })}>
                  {PAYMENT_METHODS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                </select>
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Description</label>
                <textarea className="input resize-none" rows={2} value={editForm.description}
                  onChange={(e) => setEditForm({ ...editForm, description: e.target.value })} />
              </div>
            </div>

            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm"
                onClick={() => setShowEditModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleUpdate} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Add Entry Modal (All Entries tab) ──────────────────────────────── */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative card w-full max-w-lg p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Income & Expenses</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white">
                <X size={20} />
              </button>
            </div>

            <div className="flex rounded-xl overflow-hidden border border-surface-600">
              <button
                className={`flex-1 py-2.5 text-sm font-medium transition-colors ${!form.is_income ? 'bg-red-500/20 text-red-400' : 'text-slate-400 hover:bg-surface-700'}`}
                onClick={() => setForm({ ...form, is_income: false })}
              >
                Expense
              </button>
              <button
                className={`flex-1 py-2.5 text-sm font-medium transition-colors ${form.is_income ? 'bg-emerald-500/20 text-emerald-400' : 'text-slate-400 hover:bg-surface-700'}`}
                onClick={() => setForm({ ...form, is_income: true })}
              >
                Income
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Amount *</label>
                <input type="text" inputMode="decimal" className="input" placeholder="0.00"
                  value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: formatAmountInput(e.target.value) })} />
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">
                  Previous Price <span className="text-slate-600 font-normal normal-case">(optional)</span>
                </label>
                <input type="text" inputMode="decimal" className="input" placeholder="Old price"
                  value={form.previous_price}
                  onChange={(e) => setForm({ ...form, previous_price: formatAmountInput(e.target.value) })} />
                {form.previous_price && form.amount && parseFloat(stripCommas(form.previous_price)) > 0 && (
                  <p className={`text-xs mt-1 ${parseFloat(stripCommas(form.amount)) < parseFloat(stripCommas(form.previous_price)) ? 'text-emerald-400' : 'text-red-400'}`}>
                    {parseFloat(stripCommas(form.amount)) < parseFloat(stripCommas(form.previous_price))
                      ? `Saved ${formatCurrency(parseFloat(stripCommas(form.previous_price)) - parseFloat(stripCommas(form.amount)))} vs old price`
                      : `Increased by ${formatCurrency(parseFloat(stripCommas(form.amount)) - parseFloat(stripCommas(form.previous_price)))}`}
                  </p>
                )}
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Date *</label>
                <DateInput value={form.expense_date} onChange={(v) => setForm({ ...form, expense_date: v })} />
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Category</label>
                <select className="input" value={form.category_label}
                  onChange={(e) => setForm({ ...form, category_label: e.target.value })}>
                  <option value="">— Select —</option>
                  {(form.is_income ? INCOME_CATEGORIES : EXPENSE_CATEGORIES).map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Payment Method</label>
                <select className="input" value={form.payment_method}
                  onChange={(e) => setForm({ ...form, payment_method: e.target.value })}>
                  {PAYMENT_METHODS.map((m) => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                </select>
              </div>

              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Description</label>
                <textarea className="input resize-none" rows={2} placeholder="What was this for?"
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </div>

              {!form.is_income && budgets.length > 0 && (
                <div className="col-span-2">
                  <label className="text-xs text-slate-400 mb-1 block">Link to Budget <span className="text-slate-600">(optional)</span></label>
                  <select className="input" value={form.budget ?? ''}
                    onChange={(e) => setForm({ ...form, budget: e.target.value || null })}>
                    <option value="">— No budget —</option>
                    {budgets.map((b) => (
                      <option key={b.id} value={b.id}>{b.name}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm"
                onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 disabled:opacity-50" onClick={handleCreate} disabled={saving}>
                {saving ? 'Saving…' : `Record ${form.is_income ? 'Income' : 'Expense'}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── New / Edit Folder Modal ─────────────────────────────────────────── */}
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
                <input className="input" placeholder="e.g., January 2026 Market Run"
                  value={groupForm.name}
                  onChange={(e) => setGroupForm({ ...groupForm, name: e.target.value })}
                  autoFocus />
              </div>
              <div>
                <label className="label">Date (optional)</label>
                <DateInput value={groupForm.group_date} onChange={(v) => setGroupForm({ ...groupForm, group_date: v })} />
              </div>
              <div>
                <label className="label">Description (optional)</label>
                <input className="input" placeholder="Brief note about this folder"
                  value={groupForm.description}
                  onChange={(e) => setGroupForm({ ...groupForm, description: e.target.value })} />
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

      {/* ── Add Entry in Folder Modal ───────────────────────────────────────── */}
      {showFolderExpModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-lg shadow-2xl">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-bold text-white">Add Entry</h2>
              <button onClick={() => setShowFolderExpModal(false)} className="text-slate-500 hover:text-white">
                <X size={18} />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-3 mb-5">
              {[{ v: false, label: 'Expense', icon: ArrowDownCircle, color: 'text-red-400' }, { v: true, label: 'Income', icon: ArrowUpCircle, color: 'text-emerald-400' }].map(({ v, label, icon: Icon, color }) => (
                <button key={String(v)} type="button"
                  onClick={() => setFolderExpForm({ ...folderExpForm, is_income: v, category_label: '' })}
                  className={`p-3 rounded-xl border text-sm font-medium flex items-center justify-center gap-2 transition-all ${folderExpForm.is_income === v ? 'bg-brand-500/15 border-brand-500 text-white' : 'border-surface-600 text-slate-400 hover:border-surface-500'}`}
                >
                  <Icon size={15} className={color} />
                  {label}
                </button>
              ))}
            </div>

            <div className="space-y-4">
              <div>
                <label className="label">Category</label>
                <select className="input" value={folderExpForm.category_label}
                  onChange={(e) => setFolderExpForm({ ...folderExpForm, category_label: e.target.value })}>
                  <option value="">— Select category —</option>
                  {(folderExpForm.is_income ? INCOME_CATEGORIES : EXPENSE_CATEGORIES).map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Amount *</label>
                  <input className="input" placeholder="0.00"
                    value={folderExpForm.amount}
                    onChange={(e) => setFolderExpForm({ ...folderExpForm, amount: formatAmountInput(e.target.value) })} />
                </div>
                <div>
                  <label className="label">Old Price (optional)</label>
                  <input className="input" placeholder="Previous amount"
                    value={folderExpForm.previous_price}
                    onChange={(e) => setFolderExpForm({ ...folderExpForm, previous_price: formatAmountInput(e.target.value) })} />
                  {folderExpForm.previous_price && folderExpForm.amount && parseFloat(stripCommas(folderExpForm.previous_price)) > 0 && (
                    <p className={`text-xs mt-1 ${parseFloat(stripCommas(folderExpForm.amount)) < parseFloat(stripCommas(folderExpForm.previous_price)) ? 'text-emerald-400' : 'text-red-400'}`}>
                      {parseFloat(stripCommas(folderExpForm.amount)) < parseFloat(stripCommas(folderExpForm.previous_price))
                        ? `Saved ${formatCurrency(parseFloat(stripCommas(folderExpForm.previous_price)) - parseFloat(stripCommas(folderExpForm.amount)))}`
                        : `Up by ${formatCurrency(parseFloat(stripCommas(folderExpForm.amount)) - parseFloat(stripCommas(folderExpForm.previous_price)))}`}
                    </p>
                  )}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Date</label>
                  <DateInput value={folderExpForm.expense_date} onChange={(v) => setFolderExpForm({ ...folderExpForm, expense_date: v })} />
                </div>
                <div>
                  <label className="label">Payment Method</label>
                  <select className="input" value={folderExpForm.payment_method}
                    onChange={(e) => setFolderExpForm({ ...folderExpForm, payment_method: e.target.value })}>
                    {PAYMENT_METHODS.map((m) => (
                      <option key={m.value} value={m.value}>{m.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              {!folderExpForm.is_income && budgets.length > 0 && (
                <div>
                  <label className="label">Budget (optional)</label>
                  <select className="input" value={folderExpForm.budget ?? ''}
                    onChange={(e) => setFolderExpForm({ ...folderExpForm, budget: e.target.value || null })}>
                    <option value="">— No budget —</option>
                    {budgets.map((b) => (
                      <option key={b.id} value={b.id}>{b.name}</option>
                    ))}
                  </select>
                </div>
              )}
              <div>
                <label className="label">Description (optional)</label>
                <input className="input" placeholder="Notes or reference"
                  value={folderExpForm.description}
                  onChange={(e) => setFolderExpForm({ ...folderExpForm, description: e.target.value })} />
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowFolderExpModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleSaveFolderExpense} disabled={savingFolderExp} className="btn-primary flex-1 disabled:opacity-50">
                {savingFolderExp ? <Loader2 size={15} className="animate-spin mx-auto" /> : 'Add Entry'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
