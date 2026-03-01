import { useEffect, useState } from 'react'
import { Plus, X, RefreshCw, Loader2, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { recurringApi, customerApi, inventoryApi } from '@/services/api'
import { formatDate } from '@/lib/utils'
import type { RecurringInvoice, Customer, Warehouse, Product } from '@/types'

interface RecurringForm {
  template_name: string
  customer: string
  warehouse: string
  frequency: string
  interval: string
  next_run_date: string
  end_date: string
  notes: string
  payment_method: string
}

interface RecurringLineForm { product: string; quantity: string; unit_price: string }
const BLANK_LINE: RecurringLineForm = { product: '', quantity: '1', unit_price: '' }

const today = new Date().toISOString().split('T')[0]
const BLANK: RecurringForm = {
  template_name: '', customer: '', warehouse: '', frequency: 'monthly', interval: '1',
  next_run_date: today, end_date: '', notes: '', payment_method: 'cash',
}

const FREQ_BADGE: Record<string, string> = {
  daily: 'badge-red', weekly: 'badge-orange', monthly: 'badge-blue',
  quarterly: 'badge-green', annual: 'badge-slate',
}

export default function RecurringInvoicesPage() {
  const [items, setItems] = useState<RecurringInvoice[]>([])
  const [customers, setCustomers] = useState<Customer[]>([])
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)

  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState<RecurringForm>(BLANK)
  const [lines, setLines] = useState<RecurringLineForm[]>([{ ...BLANK_LINE }])
  const [saving, setSaving] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [rRes, cRes, wRes, pRes] = await Promise.all([
        recurringApi.list(), customerApi.list(), inventoryApi.warehouses(), inventoryApi.products(),
      ])
      setItems(rRes.data.results ?? rRes.data)
      setCustomers(cRes.data.results ?? cRes.data)
      setWarehouses(wRes.data.results ?? wRes.data)
      setProducts(pRes.data.results ?? pRes.data)
    } catch { toast.error('Failed to load recurring invoices') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const handleCreate = async () => {
    if (!form.template_name.trim()) { toast.error('Template name is required'); return }
    if (!form.warehouse) { toast.error('Warehouse is required'); return }
    setSaving(true)
    try {
      await recurringApi.create({
        ...form,
        customer: form.customer || null,
        interval: parseInt(form.interval) || 1,
        end_date: form.end_date || null,
        items: lines.filter((l) => l.product).map((l) => ({
          product: l.product,
          quantity: parseFloat(l.quantity) || 1,
          unit_price: parseFloat(l.unit_price) || 0,
        })),
      })
      toast.success('Recurring invoice created')
      setShowModal(false)
      setForm(BLANK)
      setLines([{ ...BLANK_LINE }])
      load()
    } catch { toast.error('Failed to create recurring invoice') }
    finally { setSaving(false) }
  }

  const handleToggle = async (r: RecurringInvoice) => {
    try {
      await recurringApi.update(r.id, { is_active: !r.is_active })
      toast.success(r.is_active ? 'Disabled' : 'Enabled')
      load()
    } catch { toast.error('Failed to update') }
  }

  const handleDelete = async (r: RecurringInvoice) => {
    if (!confirm(`Delete "${r.template_name}"?`)) return
    try { await recurringApi.delete(r.id); toast.success('Deleted'); load() }
    catch { toast.error('Failed to delete') }
  }

  const updateLine = (i: number, field: keyof RecurringLineForm, value: string) => {
    setLines(lines.map((l, idx) => {
      if (idx !== i) return l
      const updated = { ...l, [field]: value }
      if (field === 'product') {
        const p = products.find((pr) => pr.id === value)
        if (p) updated.unit_price = p.selling_price
      }
      return updated
    }))
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Recurring Invoices</h1>
          <p className="text-slate-400 text-sm">{items.length} templates</p>
        </div>
        <button className="btn-primary sm:ml-auto" onClick={() => setShowModal(true)}>
          <Plus size={16} /> New Recurring Invoice
        </button>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Template Name', 'Customer', 'Frequency', 'Next Run', 'Occurrences', 'Status', 'Actions'].map((h) => (
                  <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 4 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 7 }).map((_, j) => (
                      <td key={j} className="px-4 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-16" /></td>
                    ))}
                  </tr>
                ))
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center">
                    <RefreshCw size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No recurring invoices yet</p>
                  </td>
                </tr>
              ) : items.map((r) => (
                <tr key={r.id} className="table-row">
                  <td className="px-4 py-3.5 text-white font-medium">{r.template_name}</td>
                  <td className="px-4 py-3.5 text-slate-400">{r.customer_name ?? <span className="italic text-slate-600">Walk-in</span>}</td>
                  <td className="px-4 py-3.5">
                    <span className={FREQ_BADGE[r.frequency] ?? 'badge-slate'}>
                      {r.interval > 1 ? `Every ${r.interval} ` : ''}{r.frequency}
                    </span>
                  </td>
                  <td className="px-4 py-3.5 text-slate-400">{formatDate(r.next_run_date)}</td>
                  <td className="px-4 py-3.5 text-slate-400">{r.occurrences_count}{r.max_occurrences ? ` / ${r.max_occurrences}` : ''}</td>
                  <td className="px-4 py-3.5">
                    <button
                      onClick={() => handleToggle(r)}
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${r.is_active ? 'bg-brand-500' : 'bg-surface-600'}`}
                    >
                      <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${r.is_active ? 'translate-x-4.5' : 'translate-x-0.5'}`} />
                    </button>
                  </td>
                  <td className="px-4 py-3.5">
                    <button onClick={() => handleDelete(r)} className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors">
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* New Recurring Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative card w-full max-w-2xl p-6 space-y-5 overflow-y-auto max-h-[90vh]">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">New Recurring Invoice</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Template Name *</label>
                <input className="input" placeholder="e.g. Monthly Maintenance Fee" value={form.template_name} onChange={(e) => setForm({ ...form, template_name: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Customer</label>
                <select className="input" value={form.customer} onChange={(e) => setForm({ ...form, customer: e.target.value })}>
                  <option value="">Walk-in</option>
                  {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Warehouse *</label>
                <select className="input" value={form.warehouse} onChange={(e) => setForm({ ...form, warehouse: e.target.value })}>
                  <option value="">— Select —</option>
                  {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Frequency</label>
                <select className="input" value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value })}>
                  {['daily', 'weekly', 'monthly', 'quarterly', 'annual'].map((f) => <option key={f} value={f}>{f.charAt(0).toUpperCase() + f.slice(1)}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Interval (every X periods)</label>
                <input type="number" min="1" className="input" value={form.interval} onChange={(e) => setForm({ ...form, interval: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Next Run Date</label>
                <input type="date" className="input" value={form.next_run_date} onChange={(e) => setForm({ ...form, next_run_date: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">End Date (optional)</label>
                <input type="date" className="input" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Payment Method</label>
                <select className="input" value={form.payment_method} onChange={(e) => setForm({ ...form, payment_method: e.target.value })}>
                  {['cash', 'bank_transfer', 'card', 'cheque'].map((m) => <option key={m} value={m}>{m.replace('_', ' ')}</option>)}
                </select>
              </div>
            </div>

            {/* Line items */}
            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Products</p>
              <div className="space-y-2">
                {lines.map((line, i) => (
                  <div key={i} className="grid grid-cols-12 gap-2 items-center">
                    <div className="col-span-5">
                      <select className="input py-1.5 text-sm" value={line.product} onChange={(e) => updateLine(i, 'product', e.target.value)}>
                        <option value="">— Product —</option>
                        {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                    </div>
                    <div className="col-span-3">
                      <input type="number" min="1" className="input py-1.5 text-sm" placeholder="Qty" value={line.quantity} onChange={(e) => updateLine(i, 'quantity', e.target.value)} />
                    </div>
                    <div className="col-span-3">
                      <input type="number" min="0" step="0.01" className="input py-1.5 text-sm" placeholder="Price" value={line.unit_price} onChange={(e) => updateLine(i, 'unit_price', e.target.value)} />
                    </div>
                    <div className="col-span-1 flex justify-center">
                      <button onClick={() => setLines(lines.filter((_, idx) => idx !== i))} className="p-1 text-slate-500 hover:text-red-400 transition-colors"><Trash2 size={14} /></button>
                    </div>
                  </div>
                ))}
              </div>
              <button onClick={() => setLines([...lines, { ...BLANK_LINE }])} className="btn-ghost text-sm mt-2 flex items-center gap-1">
                <Plus size={13} /> Add Product
              </button>
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">Notes</label>
              <textarea className="input resize-none" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </div>

            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleCreate} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : 'Create Recurring Invoice'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
