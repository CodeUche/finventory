import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, X, Wallet, Loader2, RefreshCw, ArrowLeft, Pencil, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { budgetApi, budgetAllocationApi, bypassNextGets } from '@/services/api'
import { formatCurrency, stripCommas } from '@/lib/utils'
import { confirmDialog } from '@/lib/dialog'
import AmountInput from '@/components/AmountInput'
import GLAccountSelect from '@/components/GLAccountSelect'
import type { Budget, BudgetAllocation } from '@/types'

interface AllocationForm { account: string; allocated_amount: string; notes: string }
const BLANK_FORM: AllocationForm = { account: '', allocated_amount: '', notes: '' }

export default function BudgetAllocationsPage() {
  const [budgets, setBudgets] = useState<Budget[]>([])
  const [selectedBudgetId, setSelectedBudgetId] = useState<string>('')
  const [allocations, setAllocations] = useState<BudgetAllocation[]>([])
  const [loadingBudgets, setLoadingBudgets] = useState(true)
  const [loadingAllocations, setLoadingAllocations] = useState(false)

  const [showModal, setShowModal] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<AllocationForm>(BLANK_FORM)
  const [saving, setSaving] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const loadBudgets = async () => {
    setLoadingBudgets(true)
    try {
      const { data } = await budgetApi.list()
      const list: Budget[] = data.results ?? data
      setBudgets(list)
      if (!selectedBudgetId && list.length > 0) setSelectedBudgetId(list[0].id)
    } catch { toast.error('Failed to load budgets') }
    finally { setLoadingBudgets(false) }
  }

  const loadAllocations = async (budgetId: string) => {
    if (!budgetId) { setAllocations([]); return }
    setLoadingAllocations(true)
    try {
      const { data } = await budgetAllocationApi.list({ budget: budgetId })
      setAllocations(data.results ?? data)
    } catch { toast.error('Failed to load budget allocations') }
    finally { setLoadingAllocations(false) }
  }

  useEffect(() => { loadBudgets() }, [])
  useEffect(() => { loadAllocations(selectedBudgetId) }, [selectedBudgetId])
  useDataRefresh(() => loadAllocations(selectedBudgetId))

  const selectedBudget = budgets.find((b) => b.id === selectedBudgetId) ?? null

  const openCreate = () => {
    setEditingId(null)
    setForm(BLANK_FORM)
    setShowModal(true)
  }

  const openEdit = (a: BudgetAllocation) => {
    setEditingId(a.id)
    setForm({ account: a.account, allocated_amount: a.allocated_amount, notes: a.notes ?? '' })
    setShowModal(true)
  }

  const handleSave = async () => {
    if (!selectedBudgetId) { toast.error('Select a budget first'); return }
    if (!form.account) { toast.error('Select a GL account'); return }
    if (!form.allocated_amount) { toast.error('Enter an allocated amount'); return }
    setSaving(true)
    try {
      const payload = {
        budget: selectedBudgetId,
        account: form.account,
        allocated_amount: parseFloat(stripCommas(form.allocated_amount)),
        notes: form.notes,
      }
      if (editingId) {
        await budgetAllocationApi.update(editingId, payload)
        toast.success('Allocation updated')
      } else {
        await budgetAllocationApi.create(payload)
        toast.success('Allocation created')
      }
      setShowModal(false)
      setForm(BLANK_FORM)
      setEditingId(null)
      bypassNextGets()
      loadAllocations(selectedBudgetId)
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to save allocation')
      toast.error(msg)
    } finally { setSaving(false) }
  }

  const handleDelete = async (a: BudgetAllocation) => {
    const ok = await confirmDialog(`Delete this allocation for ${a.account_code ?? ''} ${a.account_name ?? ''}?`, { danger: true })
    if (!ok) return
    setDeletingId(a.id)
    try {
      await budgetAllocationApi.delete(a.id)
      toast.success('Allocation deleted')
      bypassNextGets()
      loadAllocations(selectedBudgetId)
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to delete allocation')
      toast.error(msg)
    } finally { setDeletingId(null) }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Link to="/budgets" className="text-slate-400 hover:text-white"><ArrowLeft size={18} /></Link>
            <h1 className="text-2xl font-bold text-white">Budget Allocations</h1>
          </div>
          <p className="text-slate-400 text-sm">{allocations.length} allocation{allocations.length !== 1 ? 's' : ''}</p>
        </div>
        <div className="flex items-center gap-2 sm:ml-auto">
          <button onClick={() => { bypassNextGets(); loadAllocations(selectedBudgetId) }} disabled={loadingAllocations} className="btn-ghost p-2 text-slate-400 hover:text-white" title="Refresh">
            <RefreshCw size={16} className={loadingAllocations ? 'animate-spin' : ''} />
          </button>
          <button className="btn-primary" onClick={openCreate} disabled={!selectedBudgetId}>
            <Plus size={16} /> New Allocation
          </button>
        </div>
      </div>

      <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl px-4 py-3 text-sm text-slate-300">
        A Budget Allocation sets aside an amount against a specific Chart-of-Accounts account.
        Spent and Remaining are computed automatically from posted Journal Entries for that account —
        within the budget's <Link to="/budgets/periods" className="text-brand-400 hover:underline">Budget Period</Link> dates
        if one is pinned, otherwise the whole fiscal year.
      </div>

      <div className="card p-4">
        <label className="text-xs text-slate-400 mb-1 block">Budget</label>
        {loadingBudgets ? (
          <div className="h-9 bg-surface-700 rounded animate-pulse w-64" />
        ) : (
          <select className="input max-w-md" value={selectedBudgetId} onChange={(e) => setSelectedBudgetId(e.target.value)}>
            <option value="">— Select a budget —</option>
            {budgets.map((b) => (
              <option key={b.id} value={b.id}>{b.name} ({b.fiscal_year})</option>
            ))}
          </select>
        )}
        {selectedBudget?.period_name && (
          <p className="text-xs text-slate-500 mt-2">Pinned to period: {selectedBudget.period_name}</p>
        )}
      </div>

      {!selectedBudgetId ? (
        <div className="card p-12 text-center">
          <Wallet size={36} className="mx-auto mb-3 text-slate-600" />
          <p className="text-slate-400 font-medium">Select a budget above to see its allocations</p>
        </div>
      ) : loadingAllocations ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="card p-5 animate-pulse">
              <div className="h-5 bg-surface-700 rounded w-48 mb-2" />
              <div className="h-3 bg-surface-700 rounded w-32" />
            </div>
          ))}
        </div>
      ) : allocations.length === 0 ? (
        <div className="card p-12 text-center">
          <Wallet size={36} className="mx-auto mb-3 text-slate-600" />
          <p className="text-slate-400 font-medium">No allocations yet for this budget</p>
          <p className="text-slate-500 text-sm mt-1 mb-4">Set aside an amount against a GL account to track spend against it</p>
          <button onClick={openCreate} className="btn-primary mt-2 inline-flex items-center gap-2 text-sm">
            <Plus size={14} /> Add First Allocation
          </button>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700 bg-surface-800/50">
                {['Account', 'Allocated', 'Spent', 'Remaining', 'Notes', ''].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-700">
              {allocations.map((a) => {
                const remaining = a.remaining_amount ? parseFloat(a.remaining_amount) : 0
                return (
                  <tr key={a.id} className="table-row">
                    <td className="px-4 py-3 text-slate-300">{a.account_code ? `${a.account_code} · ` : ''}{a.account_name ?? '—'}</td>
                    <td className="px-4 py-3 font-mono text-white">{formatCurrency(a.allocated_amount)}</td>
                    <td className="px-4 py-3 font-mono text-slate-300">{a.spent_amount ? formatCurrency(a.spent_amount) : '—'}</td>
                    <td className={`px-4 py-3 font-mono ${remaining < 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                      {a.remaining_amount ? formatCurrency(a.remaining_amount) : '—'}
                    </td>
                    <td className="px-4 py-3 text-slate-500">{a.notes || '—'}</td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button onClick={() => openEdit(a)} className="text-slate-400 hover:text-white" title="Edit">
                          <Pencil size={14} />
                        </button>
                        <button
                          onClick={() => handleDelete(a)}
                          disabled={deletingId === a.id}
                          className="text-slate-400 hover:text-red-400 disabled:opacity-50"
                          title="Delete"
                        >
                          {deletingId === a.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative card w-full max-w-md p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">{editingId ? 'Edit Allocation' : 'New Allocation'}</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">GL Account *</label>
                <GLAccountSelect value={form.account} onChange={(v) => setForm({ ...form, account: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Allocated Amount *</label>
                <AmountInput
                  className="input"
                  placeholder="e.g. 500,000"
                  value={form.allocated_amount}
                  onChange={(v) => setForm({ ...form, allocated_amount: v })}
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Notes <span className="text-slate-600 font-normal">(optional)</span></label>
                <input
                  className="input"
                  placeholder="Brief note about this allocation"
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                />
              </div>
            </div>
            <div className="flex gap-3">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleSave} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : editingId ? 'Save Changes' : 'Create Allocation'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
