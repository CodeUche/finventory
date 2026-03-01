import { useEffect, useState } from 'react'
import { ArrowDownCircle, ArrowUpCircle, Plus, Search, X, Pencil, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { expenseApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import { EXPENSE_CATEGORIES, INCOME_CATEGORIES } from '@/lib/categories'
import type { Expense } from '@/types'

const PAYMENT_METHODS: { value: string; label: string }[] = [
  { value: 'cash', label: 'Cash' },
  { value: 'bank', label: 'Bank Transfer' },
  { value: 'card', label: 'Card' },
  { value: 'cheque', label: 'Cheque' },
]

function formatAmountInput(raw: string): string {
  const clean = raw.replace(/[^0-9.]/g, '')
  const parts = clean.split('.')
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return parts.slice(0, 2).join('.')
}
function stripCommas(v: string): string { return v.replace(/,/g, '') }

interface ExpenseForm {
  category_label: string
  amount: string
  is_income: boolean
  description: string
  expense_date: string
  payment_method: string
}

const today = new Date().toISOString().split('T')[0]

const BLANK: ExpenseForm = {
  category_label: '',
  amount: '',
  is_income: false,
  description: '',
  expense_date: today,
  payment_method: 'cash',
}

export default function ExpensesPage() {
  const [expenses, setExpenses] = useState<Expense[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<'expense' | 'income' | ''>('')

  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState<ExpenseForm>(BLANK)
  const [saving, setSaving] = useState(false)

  const [editId, setEditId] = useState<string | null>(null)
  const [showEditModal, setShowEditModal] = useState(false)
  const [editForm, setEditForm] = useState<ExpenseForm>(BLANK)

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, unknown> = { search: search || undefined }
      if (typeFilter === 'income') params.is_income = true
      if (typeFilter === 'expense') params.is_income = false
      const expRes = await expenseApi.list(params)
      setExpenses(expRes.data.results ?? expRes.data)
    } catch { toast.error('Failed to load expenses') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [search, typeFilter])

  const handleCreate = async () => {
    const rawAmount = stripCommas(form.amount)
    if (!rawAmount || parseFloat(rawAmount) <= 0) { toast.error('Enter a valid amount'); return }
    if (!form.expense_date) { toast.error('Select a date'); return }
    setSaving(true)
    try {
      await expenseApi.create({ ...form, amount: rawAmount })
      toast.success(form.is_income ? 'Income recorded' : 'Expense recorded')
      setShowModal(false)
      setForm(BLANK)
      load()
    } catch { toast.error('Failed to save') }
    finally { setSaving(false) }
  }

  const openEdit = (e: Expense) => {
    setEditId(e.id)
    setEditForm({
      category_label: e.category_name ?? '',
      amount: formatAmountInput(String(e.amount)),
      is_income: e.is_income,
      description: e.description ?? '',
      expense_date: e.expense_date,
      payment_method: e.payment_method,
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
      load()
    } catch { toast.error('Failed to update') }
    finally { setSaving(false) }
  }

  const totalExpenses = expenses
    .filter((e) => !e.is_income)
    .reduce((s, e) => s + parseFloat(e.amount), 0)

  const totalIncome = expenses
    .filter((e) => e.is_income)
    .reduce((s, e) => s + parseFloat(e.amount), 0)

  const net = totalIncome - totalExpenses

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Expenses & Income</h1>
          <p className="text-slate-400 text-sm">{expenses.length} entries</p>
        </div>
        <button className="btn-primary sm:ml-auto" onClick={() => setShowModal(true)}>
          <Plus size={16} /> Add Entry
        </button>
      </div>

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
        <div className="flex gap-2">
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
        </div>
      </div>

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

      {/* Edit modal */}
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
                <label className="text-xs text-slate-400 mb-1 block">Amount (₦) *</label>
                <input type="text" inputMode="decimal" className="input" placeholder="0.00"
                  value={editForm.amount}
                  onChange={(e) => setEditForm({ ...editForm, amount: formatAmountInput(e.target.value) })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Date *</label>
                <input type="date" className="input" value={editForm.expense_date}
                  onChange={(e) => setEditForm({ ...editForm, expense_date: e.target.value })} />
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

      {/* Add modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative card w-full max-w-lg p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Add Entry</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white">
                <X size={20} />
              </button>
            </div>

            {/* Type toggle */}
            <div className="flex rounded-xl overflow-hidden border border-surface-600">
              <button
                className={`flex-1 py-2.5 text-sm font-medium transition-colors ${
                  !form.is_income ? 'bg-red-500/20 text-red-400' : 'text-slate-400 hover:bg-surface-700'
                }`}
                onClick={() => setForm({ ...form, is_income: false })}
              >
                Expense
              </button>
              <button
                className={`flex-1 py-2.5 text-sm font-medium transition-colors ${
                  form.is_income ? 'bg-emerald-500/20 text-emerald-400' : 'text-slate-400 hover:bg-surface-700'
                }`}
                onClick={() => setForm({ ...form, is_income: true })}
              >
                Income
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Amount (₦) *</label>
                <input
                  type="text"
                  inputMode="decimal"
                  className="input"
                  placeholder="0.00"
                  value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: formatAmountInput(e.target.value) })}
                />
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Date *</label>
                <input
                  type="date"
                  className="input"
                  value={form.expense_date}
                  onChange={(e) => setForm({ ...form, expense_date: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Category</label>
                <select
                  className="input"
                  value={form.category_label}
                  onChange={(e) => setForm({ ...form, category_label: e.target.value })}
                >
                  <option value="">— Select —</option>
                  {(form.is_income ? INCOME_CATEGORIES : EXPENSE_CATEGORIES).map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Payment Method</label>
                <select
                  className="input"
                  value={form.payment_method}
                  onChange={(e) => setForm({ ...form, payment_method: e.target.value })}
                >
                  {PAYMENT_METHODS.map((m) => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                </select>
              </div>

              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Description</label>
                <textarea
                  className="input resize-none"
                  rows={2}
                  placeholder="What was this for?"
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                />
              </div>
            </div>

            <div className="flex gap-3 pt-1">
              <button
                className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm"
                onClick={() => setShowModal(false)}
              >
                Cancel
              </button>
              <button
                className="btn-primary flex-1 py-2.5 disabled:opacity-50"
                onClick={handleCreate}
                disabled={saving}
              >
                {saving ? 'Saving…' : `Record ${form.is_income ? 'Income' : 'Expense'}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
