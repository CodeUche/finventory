import { useEffect, useState } from 'react'
import { Plus, Search, Users, X, Pencil, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { customerApi } from '@/services/api'
import { formatCurrency, getStatusColor } from '@/lib/utils'
import type { Customer } from '@/types'

const CUSTOMER_TYPES = ['retail', 'wholesale', 'distributor']

interface NewCustomerForm {
  name: string
  customer_type: string
  email: string
  phone: string
  address: string
  credit_limit: string
}

const BLANK: NewCustomerForm = {
  name: '',
  customer_type: 'retail',
  email: '',
  phone: '',
  address: '',
  credit_limit: '0',
}

export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('')

  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState<NewCustomerForm>(BLANK)
  const [saving, setSaving] = useState(false)

  const [selected, setSelected] = useState<Customer | null>(null)
  const [showEditModal, setShowEditModal] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<NewCustomerForm>(BLANK)

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await customerApi.list({ search, customer_type: typeFilter || undefined })
      setCustomers(data.results ?? data)
    } catch { toast.error('Failed to load customers') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [search, typeFilter])

  const handleCreate = async () => {
    if (!form.name.trim()) { toast.error('Customer name required'); return }
    setSaving(true)
    try {
      await customerApi.create(form)
      toast.success('Customer added')
      setShowModal(false)
      setForm(BLANK)
      load()
    } catch { toast.error('Failed to create customer') }
    finally { setSaving(false) }
  }

  const openEdit = (c: Customer) => {
    setEditId(c.id)
    setEditForm({
      name: c.name,
      customer_type: c.customer_type,
      email: c.email ?? '',
      phone: c.phone ?? '',
      address: c.address ?? '',
      credit_limit: c.credit_limit,
    })
    setShowEditModal(true)
  }

  const handleUpdate = async () => {
    if (!editForm.name.trim() || !editId) { toast.error('Customer name required'); return }
    setSaving(true)
    try {
      const updated = await customerApi.update(editId, editForm)
      toast.success('Customer updated')
      setShowEditModal(false)
      if (selected?.id === editId) setSelected({ ...selected, ...updated.data })
      load()
    } catch { toast.error('Failed to update customer') }
    finally { setSaving(false) }
  }

  const creditUtilPct = (c: Customer) => {
    const limit = parseFloat(c.credit_limit)
    const used = parseFloat(c.outstanding_balance)
    if (!limit) return 0
    return Math.min(100, (used / limit) * 100)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Customers</h1>
          <p className="text-slate-400 text-sm">{customers.length} customer{customers.length !== 1 ? 's' : ''}</p>
        </div>
        <button className="btn-primary sm:ml-auto" onClick={() => setShowModal(true)}>
          <Plus size={16} /> New Customer
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            className="input pl-9"
            placeholder="Search name, email, phone…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select className="input max-w-xs" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="">All types</option>
          {CUSTOMER_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Customer', 'Type', 'Phone', 'Credit Limit', 'Outstanding', 'Available', 'Credit Usage', ''].map((h) => (
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
                    {Array.from({ length: 8 }).map((_, j) => (
                      <td key={j} className="px-5 py-3.5">
                        <div className="h-4 bg-surface-700 rounded animate-pulse w-20" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : customers.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-5 py-12 text-center">
                    <Users size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No customers yet</p>
                  </td>
                </tr>
              ) : (
                customers.map((c) => {
                  const pct = creditUtilPct(c)
                  return (
                    <tr key={c.id} className="table-row cursor-pointer" onClick={() => setSelected(c)}>
                      <td className="px-5 py-3.5">
                        <p className="font-medium text-white">{c.name}</p>
                        <p className="text-xs text-slate-500">{c.code}</p>
                      </td>
                      <td className="px-5 py-3.5">
                        <span className={getStatusColor(c.customer_type === 'retail' ? 'confirmed' : c.customer_type === 'wholesale' ? 'partially_paid' : 'credit')}>
                          {c.customer_type}
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-slate-400">{c.phone || '—'}</td>
                      <td className="px-5 py-3.5 text-slate-300">{formatCurrency(c.credit_limit)}</td>
                      <td className="px-5 py-3.5 text-red-400">{formatCurrency(c.outstanding_balance)}</td>
                      <td className="px-5 py-3.5 text-emerald-400">{formatCurrency(c.available_credit)}</td>
                      <td className="px-5 py-3.5 min-w-[120px]">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-1.5 bg-surface-700 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all ${
                                pct > 80 ? 'bg-red-500' : pct > 50 ? 'bg-amber-500' : 'bg-emerald-500'
                              }`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className="text-xs text-slate-500 w-8">{pct.toFixed(0)}%</span>
                        </div>
                      </td>
                      <td className="px-5 py-3.5">
                        {c.is_credit_blocked && (
                          <span className="badge-red text-[10px]">Blocked</span>
                        )}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Detail drawer */}
      {selected && (
        <div
          className="fixed inset-0 z-40 flex justify-end"
          onClick={() => setSelected(null)}
        >
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
          <aside
            className="relative w-full max-w-md bg-surface-900 border-l border-surface-700 shadow-2xl overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 space-y-5">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-xl font-bold text-white">{selected.name}</h2>
                  <p className="text-slate-400 text-sm">{selected.code} · {selected.customer_type}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => openEdit(selected)} className="btn-ghost p-1.5 text-slate-400 hover:text-white" title="Edit">
                    <Pencil size={15} />
                  </button>
                  <button onClick={() => setSelected(null)} className="btn-ghost p-1.5 text-slate-400 hover:text-white">
                    <X size={18} />
                  </button>
                </div>
              </div>

              {/* Stats */}
              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: 'Credit Limit', value: formatCurrency(selected.credit_limit), color: 'text-white' },
                  { label: 'Outstanding', value: formatCurrency(selected.outstanding_balance), color: 'text-red-400' },
                  { label: 'Available', value: formatCurrency(selected.available_credit), color: 'text-emerald-400' },
                  { label: 'Credit %', value: `${creditUtilPct(selected).toFixed(1)}%`, color: creditUtilPct(selected) > 80 ? 'text-red-400' : 'text-amber-400' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="bg-surface-800 rounded-xl p-4">
                    <p className="text-xs text-slate-500 mb-1">{label}</p>
                    <p className={`text-lg font-bold ${color}`}>{value}</p>
                  </div>
                ))}
              </div>

              {/* Info */}
              <div className="space-y-2 text-sm">
                {[
                  { label: 'Email', value: selected.email || '—' },
                  { label: 'Phone', value: selected.phone || '—' },
                  { label: 'Status', value: selected.is_credit_blocked ? 'Credit Blocked' : 'Active' },
                ].map(({ label, value }) => (
                  <div key={label} className="flex justify-between py-2 border-b border-surface-700">
                    <span className="text-slate-400">{label}</span>
                    <span className="text-white font-medium">{value}</span>
                  </div>
                ))}
              </div>
            </div>
          </aside>
        </div>
      )}

      {/* Edit modal */}
      {showEditModal && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowEditModal(false)} />
          <div className="relative card w-full max-w-lg p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Edit Customer</h2>
              <button onClick={() => setShowEditModal(false)} className="text-slate-400 hover:text-white">
                <X size={20} />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Full Name *</label>
                <input className="input" value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Type</label>
                <select className="input" value={editForm.customer_type} onChange={(e) => setEditForm({ ...editForm, customer_type: e.target.value })}>
                  {CUSTOMER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Credit Limit (₦)</label>
                <input type="number" className="input" value={editForm.credit_limit} min="0"
                  onChange={(e) => setEditForm({ ...editForm, credit_limit: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Phone</label>
                <input className="input" value={editForm.phone} onChange={(e) => setEditForm({ ...editForm, phone: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Email</label>
                <input type="email" className="input" value={editForm.email} onChange={(e) => setEditForm({ ...editForm, email: e.target.value })} />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Address</label>
                <textarea className="input resize-none" rows={2} value={editForm.address}
                  onChange={(e) => setEditForm({ ...editForm, address: e.target.value })} />
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

      {/* Create modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative card w-full max-w-lg p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">New Customer</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white">
                <X size={20} />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Full Name *</label>
                <input
                  className="input"
                  placeholder="e.g., Aisha Musa"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Type</label>
                <select className="input" value={form.customer_type} onChange={(e) => setForm({ ...form, customer_type: e.target.value })}>
                  {CUSTOMER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Credit Limit (₦)</label>
                <input
                  type="number"
                  className="input"
                  placeholder="0"
                  value={form.credit_limit}
                  onChange={(e) => setForm({ ...form, credit_limit: e.target.value })}
                  min="0"
                />
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Phone</label>
                <input
                  className="input"
                  placeholder="+234…"
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Email</label>
                <input
                  type="email"
                  className="input"
                  placeholder="customer@email.com"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </div>

              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Address</label>
                <textarea
                  className="input resize-none"
                  rows={2}
                  placeholder="Street, City, State"
                  value={form.address}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
                />
              </div>
            </div>

            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowModal(false)}>
                Cancel
              </button>
              <button className="btn-primary flex-1 py-2.5 disabled:opacity-50" onClick={handleCreate} disabled={saving}>
                {saving ? 'Saving…' : 'Create Customer'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
