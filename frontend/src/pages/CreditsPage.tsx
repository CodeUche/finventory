import { useEffect, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { CreditCard, Search, Plus, X, Loader2, TrendingDown, TrendingUp, AlertCircle } from 'lucide-react'
import toast from 'react-hot-toast'
import { creditApi, customerApi } from '@/services/api'
import { formatCurrency, formatDate, stripCommas } from '@/lib/utils'
import AmountInput from '@/components/AmountInput'
import type { CreditTransaction, Customer } from '@/types'
import DateInput from '@/components/DateInput'

const TYPE_COLORS: Record<string, string> = {
  debit: 'badge-red',
  credit: 'badge-green',
  adjustment: 'badge-blue',
  write_off: 'badge-slate',
}

interface AgingBucket {
  label: string
  count: number
  total: string
}

export default function CreditsPage() {
  const [transactions, setTransactions] = useState<CreditTransaction[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('')

  const [showPayModal, setShowPayModal] = useState(false)
  const [customers, setCustomers] = useState<Customer[]>([])
  const [payForm, setPayForm] = useState({ customer_id: '', amount: '', description: '', due_date: '' })
  const [saving, setSaving] = useState(false)

  const [aging, setAging] = useState<AgingBucket[] | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, unknown> = {}
      if (search) params.search = search
      if (typeFilter) params.transaction_type = typeFilter
      const { data } = await creditApi.list(params)
      setTransactions(data.results ?? data)
    } catch {
      toast.error('Failed to load credit transactions')
    } finally {
      setLoading(false)
    }
  }

  const loadAging = async () => {
    try {
      const { data } = await creditApi.agingReport()
      setAging(data)
    } catch {
      // non-critical
    }
  }

  useEffect(() => { load() }, [search, typeFilter])
  useEffect(() => { loadAging() }, [])
  useDataRefresh(load)

  const openPayModal = async () => {
    setShowPayModal(true)
    if (customers.length === 0) {
      try {
        const { data } = await customerApi.list()
        setCustomers(data.results ?? data)
      } catch { /* ignore */ }
    }
  }

  const handleRecordPayment = async () => {
    if (!payForm.customer_id) { toast.error('Select a customer'); return }
    if (!payForm.amount || parseFloat(stripCommas(payForm.amount)) <= 0) { toast.error('Enter a valid amount'); return }
    setSaving(true)
    try {
      await creditApi.recordPayment({
        ...payForm,
        amount: stripCommas(payForm.amount),
        due_date: payForm.due_date || undefined,
      })
      toast.success('Payment recorded')
      setShowPayModal(false)
      setPayForm({ customer_id: '', amount: '', description: '', due_date: '' })
      load()
    } catch {
      toast.error('Failed to record payment')
    } finally {
      setSaving(false)
    }
  }

  const totalOutstanding = transactions
    .filter((t) => t.transaction_type === 'debit')
    .reduce((s, t) => s + parseFloat(t.amount), 0)

  const totalPaid = transactions
    .filter((t) => t.transaction_type === 'credit')
    .reduce((s, t) => s + parseFloat(t.amount), 0)

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Credits</h1>
          <p className="text-slate-400 text-sm">{transactions.length} transactions</p>
        </div>
        <button className="btn-primary sm:ml-auto" onClick={openPayModal}>
          <Plus size={16} /> Record Payment
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="card p-5 flex items-center gap-4">
          <div className="w-11 h-11 rounded-xl bg-red-500/15 flex items-center justify-center">
            <TrendingDown size={22} className="text-red-400" />
          </div>
          <div>
            <p className="text-xs text-slate-400">Total Outstanding</p>
            <p className="text-xl font-bold text-red-400">{formatCurrency(totalOutstanding)}</p>
          </div>
        </div>
        <div className="card p-5 flex items-center gap-4">
          <div className="w-11 h-11 rounded-xl bg-emerald-500/15 flex items-center justify-center">
            <TrendingUp size={22} className="text-emerald-400" />
          </div>
          <div>
            <p className="text-xs text-slate-400">Total Payments</p>
            <p className="text-xl font-bold text-emerald-400">{formatCurrency(totalPaid)}</p>
          </div>
        </div>
        <div className="card p-5 flex items-center gap-4">
          <div className="w-11 h-11 rounded-xl bg-brand-500/15 flex items-center justify-center">
            <CreditCard size={22} className="text-brand-400" />
          </div>
          <div>
            <p className="text-xs text-slate-400">Net Balance</p>
            <p className={`text-xl font-bold ${totalOutstanding - totalPaid > 0 ? 'text-red-400' : 'text-emerald-400'}`}>
              {formatCurrency(Math.abs(totalOutstanding - totalPaid))}
            </p>
          </div>
        </div>
      </div>

      {/* Aging report */}
      {aging && aging.length > 0 && (
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <AlertCircle size={16} className="text-amber-400" />
            <h3 className="text-sm font-semibold text-white">Aging Report</h3>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {aging.map((bucket) => (
              <div key={bucket.label} className="bg-surface-800 rounded-xl p-3">
                <p className="text-xs text-slate-500 mb-1">{bucket.label}</p>
                <p className="text-sm font-bold text-white">{formatCurrency(bucket.total)}</p>
                <p className="text-xs text-slate-500">{bucket.count} customer{bucket.count !== 1 ? 's' : ''}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input className="input pl-9" placeholder="Search customer…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <select className="input max-w-xs" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="">All types</option>
          {['debit', 'credit', 'adjustment', 'write_off'].map((t) => (
            <option key={t} value={t}>{t.replace('_', ' ').toUpperCase()}</option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Date', 'Customer', 'Type', 'Amount', 'Balance After', 'Due Date', 'Description'].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 7 }).map((_, j) => (
                      <td key={j} className="px-5 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-20" /></td>
                    ))}
                  </tr>
                ))
              ) : transactions.length === 0 ? (
                <tr><td colSpan={7} className="px-5 py-12 text-center">
                  <CreditCard size={32} className="mx-auto mb-2 text-slate-600" />
                  <p className="text-slate-500">No credit transactions</p>
                </td></tr>
              ) : (
                transactions.map((t) => (
                  <tr key={t.id} className="table-row">
                    <td className="px-5 py-3.5 text-slate-400 whitespace-nowrap">{formatDate(t.created_at)}</td>
                    <td className="px-5 py-3.5 text-white font-medium">{t.customer_name}</td>
                    <td className="px-5 py-3.5">
                      <span className={TYPE_COLORS[t.transaction_type] ?? 'badge-slate'}>{t.transaction_type.replace('_', ' ').toUpperCase()}</span>
                    </td>
                    <td className={`px-5 py-3.5 font-semibold ${t.transaction_type === 'credit' ? 'text-emerald-400' : 'text-red-400'}`}>
                      {t.transaction_type === 'credit' ? '+' : '−'} {formatCurrency(t.amount)}
                    </td>
                    <td className="px-5 py-3.5 text-slate-300">{formatCurrency(t.balance_after)}</td>
                    <td className="px-5 py-3.5 text-slate-400">{t.due_date ? formatDate(t.due_date) : '—'}</td>
                    <td className="px-5 py-3.5 text-slate-400 max-w-xs truncate">{t.description || '—'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Record Payment modal */}
      {showPayModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowPayModal(false)} />
          <div className="relative card w-full max-w-md p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Record Payment</h2>
              <button onClick={() => setShowPayModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="label">Customer *</label>
                <select className="input" value={payForm.customer_id} onChange={(e) => setPayForm({ ...payForm, customer_id: e.target.value })}>
                  <option value="">— Select customer —</option>
                  {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <label className="label">Amount *</label>
                <AmountInput className="input" placeholder="0.00"
                  value={payForm.amount} onChange={(v) => setPayForm({ ...payForm, amount: v })} />
              </div>
              <div>
                <label className="label">Due Date <span className="text-slate-500 font-normal">(optional)</span></label>
                <DateInput
                  value={payForm.due_date}
                  onChange={(v) => setPayForm({ ...payForm, due_date: v })}
                  placeholder="DD/MM/YYYY"
                />
              </div>
              <div>
                <label className="label">Description</label>
                <textarea className="input resize-none" rows={2} placeholder="Payment reference or note"
                  value={payForm.description} onChange={(e) => setPayForm({ ...payForm, description: e.target.value })} />
              </div>
            </div>

            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white transition-colors text-sm"
                onClick={() => setShowPayModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 justify-center disabled:opacity-50" onClick={handleRecordPayment} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : 'Record Payment'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
