import { useEffect, useState } from 'react'
import { Plus, X, Receipt, Loader2, Search, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { billApi, supplierApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import type { Bill } from '@/types'

interface Supplier { id: string; name: string }

const STATUS_BADGE: Record<string, string> = {
  draft: 'badge-slate',
  received: 'badge-yellow',
  approved: 'badge-orange',
  paid: 'badge-green',
  partially_paid: 'badge-blue',
  overdue: 'badge-red',
  voided: 'badge-slate',
}

interface BillLineForm { description: string; quantity: string; unit_cost: string }
const BLANK_LINE: BillLineForm = { description: '', quantity: '1', unit_cost: '' }

interface BillForm {
  supplier: string
  reference: string
  issue_date: string
  due_date: string
  tax_amount: string
  notes: string
}

interface PayForm {
  amount: string
  payment_date: string
  method: string
  reference: string
  notes: string
}

const today = new Date().toISOString().split('T')[0]
const inThirtyDays = new Date(Date.now() + 30 * 86400000).toISOString().split('T')[0]

const BLANK_BILL: BillForm = { supplier: '', reference: '', issue_date: today, due_date: inThirtyDays, tax_amount: '0', notes: '' }
const BLANK_PAY: PayForm = { amount: '', payment_date: today, method: 'bank', reference: '', notes: '' }

function agingBucket(dueDate: string): '0-30' | '31-60' | '61-90' | '90+' {
  const days = Math.floor((Date.now() - new Date(dueDate).getTime()) / 86400000)
  if (days <= 30) return '0-30'
  if (days <= 60) return '31-60'
  if (days <= 90) return '61-90'
  return '90+'
}

export default function BillsPage() {
  const [bills, setBills] = useState<Bill[]>([])
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState('')
  const [search, setSearch] = useState('')

  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState<BillForm>(BLANK_BILL)
  const [lines, setLines] = useState<BillLineForm[]>([{ ...BLANK_LINE }])
  const [saving, setSaving] = useState(false)

  const [payBillId, setPayBillId] = useState<string | null>(null)
  const [payForm, setPayForm] = useState<PayForm>(BLANK_PAY)
  const [paying, setPaying] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (statusFilter) params.status = statusFilter
      if (search) params.search = search
      const [bRes, sRes] = await Promise.all([billApi.list(params), supplierApi.list()])
      setBills(bRes.data.results ?? bRes.data)
      setSuppliers(sRes.data.results ?? sRes.data)
    } catch { toast.error('Failed to load bills') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [statusFilter, search])

  const handleCreate = async () => {
    if (!form.supplier) { toast.error('Select a supplier'); return }
    if (lines.some((l) => !l.description || !l.unit_cost)) { toast.error('Fill all line items'); return }
    setSaving(true)
    try {
      await billApi.create({
        ...form,
        tax_amount: parseFloat(form.tax_amount) || 0,
        items: lines.map((l) => ({
          description: l.description,
          quantity: parseFloat(l.quantity) || 1,
          unit_cost: parseFloat(l.unit_cost) || 0,
        })),
      })
      toast.success('Bill created')
      setShowModal(false)
      setForm(BLANK_BILL)
      setLines([{ ...BLANK_LINE }])
      load()
    } catch { toast.error('Failed to create bill') }
    finally { setSaving(false) }
  }

  const handleApprove = async (id: string) => {
    try { await billApi.approve(id); toast.success('Bill approved'); load() }
    catch { toast.error('Failed to approve bill') }
  }

  const handleVoid = async (id: string) => {
    if (!confirm('Void this bill?')) return
    try { await billApi.void(id); toast.success('Bill voided'); load() }
    catch { toast.error('Failed to void bill') }
  }

  const handlePay = async () => {
    if (!payBillId || !payForm.amount) { toast.error('Enter amount'); return }
    setPaying(true)
    try {
      await billApi.pay(payBillId, { ...payForm, amount: parseFloat(payForm.amount) })
      toast.success('Payment recorded')
      setPayBillId(null)
      setPayForm(BLANK_PAY)
      load()
    } catch { toast.error('Failed to record payment') }
    finally { setPaying(false) }
  }

  const updateLine = (i: number, field: keyof BillLineForm, value: string) => {
    setLines(lines.map((l, idx) => idx === i ? { ...l, [field]: value } : l))
  }

  // Summary
  const totalPayable = bills.filter((b) => b.status !== 'voided' && b.status !== 'paid').reduce((s, b) => s + parseFloat(b.amount_due), 0)
  const overdue = bills.filter((b) => b.status === 'overdue').reduce((s, b) => s + parseFloat(b.amount_due), 0)
  const now = new Date()
  const nextWeek = new Date(Date.now() + 7 * 86400000)
  const dueThisWeek = bills.filter((b) => {
    const d = new Date(b.due_date)
    return d >= now && d <= nextWeek && b.status !== 'paid' && b.status !== 'voided'
  }).reduce((s, b) => s + parseFloat(b.amount_due), 0)
  const paidThisMonth = bills.filter((b) => {
    const d = new Date(b.issue_date)
    return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear() && b.status === 'paid'
  }).reduce((s, b) => s + parseFloat(b.total_amount), 0)

  // AP Aging
  const unpaid = bills.filter((b) => b.status !== 'paid' && b.status !== 'voided' && b.status !== 'draft')
  const aging: Record<string, number> = { '0-30': 0, '31-60': 0, '61-90': 0, '90+': 0 }
  unpaid.forEach((b) => { aging[agingBucket(b.due_date)] += parseFloat(b.amount_due) })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Bills (Accounts Payable)</h1>
          <p className="text-slate-400 text-sm">{bills.length} total bills</p>
        </div>
        <button className="btn-primary sm:ml-auto" onClick={() => setShowModal(true)}>
          <Plus size={16} /> New Bill
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card p-5"><p className="text-xs text-slate-400">Total Payable</p><p className="text-xl font-bold text-white mt-1">{formatCurrency(totalPayable)}</p></div>
        <div className="card p-5"><p className="text-xs text-slate-400">Overdue</p><p className="text-xl font-bold text-red-400 mt-1">{formatCurrency(overdue)}</p></div>
        <div className="card p-5"><p className="text-xs text-slate-400">Due This Week</p><p className="text-xl font-bold text-orange-400 mt-1">{formatCurrency(dueThisWeek)}</p></div>
        <div className="card p-5"><p className="text-xs text-slate-400">Paid This Month</p><p className="text-xl font-bold text-emerald-400 mt-1">{formatCurrency(paidThisMonth)}</p></div>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input className="input pl-9" placeholder="Search supplier…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <select className="input max-w-xs" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All Statuses</option>
          {['draft', 'received', 'approved', 'paid', 'partially_paid', 'overdue', 'voided'].map((s) => (
            <option key={s} value={s}>{s.replace('_', ' ')}</option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Bill #', 'Supplier', 'Ref', 'Issue Date', 'Due Date', 'Total', 'Paid', 'Due', 'Status', 'Actions'].map((h) => (
                  <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 10 }).map((_, j) => (
                      <td key={j} className="px-4 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-16" /></td>
                    ))}
                  </tr>
                ))
              ) : bills.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-4 py-12 text-center">
                    <Receipt size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No bills found</p>
                  </td>
                </tr>
              ) : bills.map((b) => (
                <tr key={b.id} className="table-row">
                  <td className="px-4 py-3.5 font-mono text-brand-400">{b.bill_number}</td>
                  <td className="px-4 py-3.5 text-slate-300">{b.supplier_name}</td>
                  <td className="px-4 py-3.5 text-slate-400">{b.reference || '—'}</td>
                  <td className="px-4 py-3.5 text-slate-400">{formatDate(b.issue_date)}</td>
                  <td className="px-4 py-3.5 text-slate-400">{formatDate(b.due_date)}</td>
                  <td className="px-4 py-3.5 text-white font-semibold">{formatCurrency(b.total_amount)}</td>
                  <td className="px-4 py-3.5 text-emerald-400">{formatCurrency(b.amount_paid)}</td>
                  <td className="px-4 py-3.5 text-red-400">{formatCurrency(b.amount_due)}</td>
                  <td className="px-4 py-3.5"><span className={STATUS_BADGE[b.status] ?? 'badge-slate'}>{b.status.replace('_', ' ')}</span></td>
                  <td className="px-4 py-3.5">
                    <div className="flex items-center gap-1.5">
                      {b.status === 'received' && (
                        <button onClick={() => handleApprove(b.id)} className="text-xs px-2.5 py-1 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 transition-colors">Approve</button>
                      )}
                      {(b.status === 'approved' || b.status === 'partially_paid' || b.status === 'overdue') && (
                        <button onClick={() => { setPayBillId(b.id); setPayForm({ ...BLANK_PAY, amount: b.amount_due }) }} className="text-xs px-2.5 py-1 rounded-lg bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors">Pay</button>
                      )}
                      {b.status !== 'voided' && b.status !== 'paid' && (
                        <button onClick={() => handleVoid(b.id)} className="p-1 text-slate-500 hover:text-red-400 transition-colors"><Trash2 size={13} /></button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* AP Aging */}
      <div className="card p-6">
        <h3 className="text-white font-semibold mb-4">AP Aging Analysis</h3>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {(['0-30', '31-60', '61-90', '90+'] as const).map((bucket, i) => (
            <div key={bucket} className={`p-4 rounded-xl border ${i === 0 ? 'border-emerald-500/30 bg-emerald-500/5' : i === 1 ? 'border-yellow-500/30 bg-yellow-500/5' : i === 2 ? 'border-orange-500/30 bg-orange-500/5' : 'border-red-500/30 bg-red-500/5'}`}>
              <p className="text-xs text-slate-400">{bucket} days</p>
              <p className={`text-lg font-bold mt-1 ${i === 0 ? 'text-emerald-400' : i === 1 ? 'text-yellow-400' : i === 2 ? 'text-orange-400' : 'text-red-400'}`}>
                {formatCurrency(aging[bucket])}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* New Bill Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative card w-full max-w-2xl p-6 space-y-5 overflow-y-auto max-h-[90vh]">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">New Bill</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Supplier *</label>
                <select className="input" value={form.supplier} onChange={(e) => setForm({ ...form, supplier: e.target.value })}>
                  <option value="">— Select Supplier —</option>
                  {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Reference</label>
                <input className="input" placeholder="Invoice/PO ref" value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Tax Amount</label>
                <input type="number" min="0" step="0.01" className="input" value={form.tax_amount} onChange={(e) => setForm({ ...form, tax_amount: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Issue Date</label>
                <input type="date" className="input" value={form.issue_date} onChange={(e) => setForm({ ...form, issue_date: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Due Date</label>
                <input type="date" className="input" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
              </div>
            </div>

            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Line Items</p>
              <div className="space-y-2">
                {lines.map((line, i) => (
                  <div key={i} className="grid grid-cols-12 gap-2 items-center">
                    <div className="col-span-6">
                      <input className="input py-1.5 text-sm" placeholder="Description" value={line.description} onChange={(e) => updateLine(i, 'description', e.target.value)} />
                    </div>
                    <div className="col-span-2">
                      <input type="number" min="1" className="input py-1.5 text-sm" placeholder="Qty" value={line.quantity} onChange={(e) => updateLine(i, 'quantity', e.target.value)} />
                    </div>
                    <div className="col-span-3">
                      <input type="number" min="0" step="0.01" className="input py-1.5 text-sm" placeholder="Unit Cost" value={line.unit_cost} onChange={(e) => updateLine(i, 'unit_cost', e.target.value)} />
                    </div>
                    <div className="col-span-1 flex justify-center">
                      <button onClick={() => setLines(lines.filter((_, idx) => idx !== i))} className="p-1 text-slate-500 hover:text-red-400 transition-colors"><Trash2 size={14} /></button>
                    </div>
                  </div>
                ))}
              </div>
              <button onClick={() => setLines([...lines, { ...BLANK_LINE }])} className="btn-ghost text-sm mt-2 flex items-center gap-1">
                <Plus size={13} /> Add Line
              </button>
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">Notes</label>
              <textarea className="input resize-none" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </div>

            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleCreate} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : 'Create Bill'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Record Payment Modal */}
      {payBillId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setPayBillId(null)} />
          <div className="relative card w-full max-w-md p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Record Payment</h2>
              <button onClick={() => setPayBillId(null)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Amount *</label>
                <input type="number" min="0" step="0.01" className="input" value={payForm.amount} onChange={(e) => setPayForm({ ...payForm, amount: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Date</label>
                <input type="date" className="input" value={payForm.payment_date} onChange={(e) => setPayForm({ ...payForm, payment_date: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Method</label>
                <select className="input" value={payForm.method} onChange={(e) => setPayForm({ ...payForm, method: e.target.value })}>
                  {['cash', 'bank', 'cheque', 'transfer'].map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Reference</label>
                <input className="input" value={payForm.reference} onChange={(e) => setPayForm({ ...payForm, reference: e.target.value })} />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Notes</label>
                <input className="input" value={payForm.notes} onChange={(e) => setPayForm({ ...payForm, notes: e.target.value })} />
              </div>
            </div>
            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setPayBillId(null)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handlePay} disabled={paying}>
                {paying ? <Loader2 size={16} className="animate-spin" /> : 'Record Payment'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
