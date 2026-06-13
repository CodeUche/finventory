import { useEffect, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, Search, Truck, X, Pencil, Loader2, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { supplierApi } from '@/services/api'
import { usePagination } from '@/hooks/usePagination'
import Pagination from '@/components/Pagination'

interface Supplier {
  id: string
  code: string
  name: string
  contact_person: string
  email: string
  phone: string
  address: string
  tax_id: string
  payment_terms_days: number
  notes: string
  is_active: boolean
}

const BLANK = {
  name: '',
  contact_person: '',
  email: '',
  phone: '',
  address: '',
  tax_id: '',
  payment_terms_days: '30',
  notes: '',
}

export default function SuppliersPage() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  const [showModal, setShowModal] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState({ ...BLANK })
  const [saving, setSaving] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await supplierApi.list({ search: search || undefined, page_size: 5000 })
      setSuppliers(data.results ?? data)
    } catch {
      toast.error('Failed to load suppliers')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [search])
  useDataRefresh(load)

  const openCreate = () => {
    setEditId(null)
    setForm({ ...BLANK })
    setShowModal(true)
  }

  const openEdit = (s: Supplier) => {
    setEditId(s.id)
    setForm({
      name: s.name,
      contact_person: s.contact_person ?? '',
      email: s.email ?? '',
      phone: s.phone ?? '',
      address: s.address ?? '',
      tax_id: s.tax_id ?? '',
      payment_terms_days: String(s.payment_terms_days ?? 30),
      notes: s.notes ?? '',
    })
    setShowModal(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) { toast.error('Supplier name is required'); return }
    setSaving(true)
    try {
      if (editId) {
        await supplierApi.update(editId, form)
        toast.success('Supplier updated')
      } else {
        await supplierApi.create(form)
        toast.success('Supplier added')
      }
      setShowModal(false)
      load()
    } catch {
      toast.error(editId ? 'Failed to update supplier' : 'Failed to create supplier')
    } finally {
      setSaving(false)
    }
  }

  const upd = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  const { page, setPage, pageSize, setPageSize, totalPages, paged, total } = usePagination(suppliers)

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Suppliers</h1>
          <p className="text-slate-400 text-sm">{total} supplier{total !== 1 ? 's' : ''}</p>
        </div>
        <button className="btn-primary sm:ml-auto" onClick={openCreate}>
          <Plus size={16} /> Add Supplier
        </button>
      </div>

      <div className="relative max-w-sm">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input className="input pl-9" placeholder="Search by name or code…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Code', 'Name', 'Contact', 'Phone', 'Email', 'Payment Terms', ''].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 7 }).map((_, j) => (
                      <td key={j} className="px-5 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-20" /></td>
                    ))}
                  </tr>
                ))
              ) : total === 0 ? (
                <tr><td colSpan={7} className="px-5 py-12 text-center">
                  <Truck size={32} className="mx-auto mb-2 text-slate-600" />
                  <p className="text-slate-500">No suppliers yet</p>
                </td></tr>
              ) : (
                paged.map((s) => (
                  <tr key={s.id} className="table-row">
                    <td className="px-5 py-3.5 font-mono text-xs text-brand-400">{s.code}</td>
                    <td className="px-5 py-3.5 font-medium text-white">{s.name}</td>
                    <td className="px-5 py-3.5 text-slate-400">{s.contact_person || '—'}</td>
                    <td className="px-5 py-3.5 text-slate-400">{s.phone || '—'}</td>
                    <td className="px-5 py-3.5 text-slate-400">{s.email || '—'}</td>
                    <td className="px-5 py-3.5 text-slate-400">
                      {s.payment_terms_days === 0 ? 'COD' : `Net ${s.payment_terms_days}d`}
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-1">
                        <button onClick={() => openEdit(s)} className="btn-ghost p-1.5 text-slate-400 hover:text-white">
                          <Pencil size={14} />
                        </button>
                        <button
                          onClick={async () => {
                            if (!confirm(`Delete supplier "${s.name}"?`)) return
                            try { await supplierApi.delete(s.id); toast.success('Supplier deleted'); load() }
                            catch { toast.error('Cannot delete supplier — may have linked purchase orders') }
                          }}
                          className="btn-ghost p-1.5 text-slate-400 hover:text-red-400"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <Pagination page={page} totalPages={totalPages} pageSize={pageSize} total={total} onPage={setPage} onPageSize={setPageSize} />
      </div>

      {/* Create / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-lg shadow-2xl animate-slide-up max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-6 border-b border-surface-700">
              <h2 className="font-semibold text-white text-lg">{editId ? 'Edit Supplier' : 'New Supplier'}</h2>
              <button onClick={() => setShowModal(false)} className="btn-ghost p-1.5"><X size={18} /></button>
            </div>
            <div className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2">
                  <label className="label">Supplier Name *</label>
                  <input className="input" value={form.name} onChange={upd('name')} placeholder="e.g., ABC Distributors Ltd" />
                </div>
                <div>
                  <label className="label">Contact Person</label>
                  <input className="input" value={form.contact_person} onChange={upd('contact_person')} placeholder="Mr. John Doe" />
                </div>
                <div>
                  <label className="label">Payment Terms (days)</label>
                  <input type="number" className="input" value={form.payment_terms_days} onChange={upd('payment_terms_days')} min="0" />
                </div>
                <div>
                  <label className="label">Phone</label>
                  <input className="input" value={form.phone} onChange={upd('phone')} placeholder="+234…" />
                </div>
                <div>
                  <label className="label">Email</label>
                  <input type="email" className="input" value={form.email} onChange={upd('email')} placeholder="supplier@example.com" />
                </div>
                <div>
                  <label className="label">Tax ID / VAT Number</label>
                  <input className="input" value={form.tax_id} onChange={upd('tax_id')} />
                </div>
                <div className="col-span-2">
                  <label className="label">Address</label>
                  <textarea className="input resize-none" rows={2} value={form.address} onChange={upd('address')} />
                </div>
                <div className="col-span-2">
                  <label className="label">Notes</label>
                  <textarea className="input resize-none" rows={2} value={form.notes} onChange={upd('notes')} placeholder="Any additional notes…" />
                </div>
              </div>
              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowModal(false)} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button type="button" onClick={handleSave} disabled={saving} className="btn-primary flex-1 justify-center">
                  {saving ? <Loader2 size={16} className="animate-spin" /> : (editId ? 'Save Changes' : 'Add Supplier')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
