import { useEffect, useState } from 'react'
import { Layers, Plus, Search, Trash2, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { inventoryApi } from '@/services/api'
import { formatDate } from '@/lib/utils'
import DateInput from '@/components/DateInput'
import type { Product, Warehouse } from '@/types'

interface BatchItem {
  id: string
  batch_number: string
  product: string
  product_name: string
  product_sku: string
  warehouse: string
  warehouse_name: string
  quantity: string
  unit_cost: string
  manufacture_date: string | null
  expiry_date: string | null
  days_to_expiry: number | null
}

interface BatchForm {
  product_id: string
  warehouse_id: string
  batch_number: string
  quantity: string
  unit_cost: string
  manufacture_date: string
  expiry_date: string
}

type ExpiryFilter = 'all' | 'expiring' | 'expired' | 'ok'

function getExpiryStatus(batch: BatchItem): { label: string; badge: string; daysLeft: number | null } {
  if (!batch.expiry_date) return { label: 'No expiry', badge: 'badge-slate', daysLeft: null }
  const days = batch.days_to_expiry ?? Math.floor((new Date(batch.expiry_date).getTime() - Date.now()) / 86400000)
  if (days < 0) return { label: 'Expired', badge: 'badge-red', daysLeft: days }
  if (days < 30) return { label: `Expiring (${days}d)`, badge: 'badge-orange', daysLeft: days }
  return { label: 'OK', badge: 'badge-green', daysLeft: days }
}

const BLANK_FORM: BatchForm = {
  product_id: '', warehouse_id: '', batch_number: '',
  quantity: '', unit_cost: '', manufacture_date: '', expiry_date: '',
}

export default function BatchesPage() {
  const [batches, setBatches] = useState<BatchItem[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [warehouseFilter, setWarehouseFilter] = useState('')
  const [expiryFilter, setExpiryFilter] = useState<ExpiryFilter>('all')

  // ── Create modal ──────────────────────────────────────────────────────────
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState<BatchForm>(BLANK_FORM)
  const [saving, setSaving] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (search) params.search = search
      if (warehouseFilter) params.warehouse = warehouseFilter
      if (expiryFilter !== 'all') params.expiry_status = expiryFilter
      const [bRes, wRes] = await Promise.all([inventoryApi.batches(params), inventoryApi.warehouses()])
      setBatches(bRes.data.results ?? bRes.data)
      setWarehouses(wRes.data.results ?? wRes.data)
    } catch {
      setBatches([])
      toast.error('Failed to load batches')
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [search, warehouseFilter, expiryFilter])

  const openCreate = async () => {
    try {
      const pRes = await inventoryApi.products({ page_size: 200, is_active: true })
      const pList: Product[] = pRes.data.results ?? pRes.data
      setProducts(pList)
      const defaultWarehouse = warehouses.find((w) => w.is_default) ?? warehouses[0]
      setForm({
        ...BLANK_FORM,
        product_id: pList[0]?.id ?? '',
        warehouse_id: defaultWarehouse?.id ?? '',
      })
      setShowCreate(true)
    } catch { toast.error('Failed to load products') }
  }

  const handleCreate = async () => {
    if (!form.product_id) { toast.error('Select a product'); return }
    if (!form.warehouse_id) { toast.error('Select a location'); return }
    if (!form.batch_number.trim()) { toast.error('Enter a batch / lot number'); return }
    if (!form.quantity || parseFloat(form.quantity) <= 0) { toast.error('Enter a valid quantity'); return }

    setSaving(true)
    try {
      await inventoryApi.createBatch({
        product: form.product_id,
        warehouse: form.warehouse_id,
        batch_number: form.batch_number.trim(),
        quantity: parseFloat(form.quantity),
        unit_cost: form.unit_cost ? parseFloat(form.unit_cost) : 0,
        manufacture_date: form.manufacture_date || null,
        expiry_date: form.expiry_date || null,
      })
      toast.success('Batch created')
      setShowCreate(false)
      load()
    } catch (err: any) {
      const apiErr = err?.response?.data
      const msg = apiErr?.batch_number?.[0] ?? apiErr?.non_field_errors?.[0]
        ?? apiErr?.error?.message ?? apiErr?.error ?? 'Failed to create batch'
      toast.error(typeof msg === 'string' ? msg : JSON.stringify(msg))
    } finally { setSaving(false) }
  }

  const handleDelete = async (id: string, batchNum: string) => {
    if (!confirm(`Delete batch "${batchNum}"? This cannot be undone.`)) return
    try {
      await inventoryApi.deleteBatch(id)
      toast.success('Batch deleted')
      setBatches((prev) => prev.filter((b) => b.id !== id))
    } catch (err: any) {
      toast.error(err?.response?.data?.error ?? 'Failed to delete batch')
    }
  }

  // Summary stats
  const expiring = batches.filter((b) => {
    if (!b.expiry_date) return false
    const days = Math.floor((new Date(b.expiry_date).getTime() - Date.now()) / 86400000)
    return days >= 0 && days < 30
  }).length
  const expired = batches.filter((b) => {
    if (!b.expiry_date) return false
    return new Date(b.expiry_date).getTime() < Date.now()
  }).length
  const adequate = batches.filter((b) => {
    if (!b.expiry_date) return true
    const days = Math.floor((new Date(b.expiry_date).getTime() - Date.now()) / 86400000)
    return days >= 30
  }).length

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-white">Batches & Lots</h1>
          <p className="text-slate-400 text-sm">Track batch numbers, lot codes, and expiry dates per product and location.</p>
        </div>
        <button onClick={openCreate} className="btn-primary flex items-center gap-2">
          <Plus size={15} />
          New Batch / Lot
        </button>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card p-5"><p className="text-xs text-slate-400">Total Batches</p><p className="text-xl font-bold text-white mt-1">{batches.length}</p></div>
        <div className="card p-5 border-orange-500/20"><p className="text-xs text-slate-400">Expiring Soon</p><p className="text-xl font-bold text-orange-400 mt-1">{expiring}</p></div>
        <div className="card p-5 border-red-500/20"><p className="text-xs text-slate-400">Expired</p><p className="text-xl font-bold text-red-400 mt-1">{expired}</p></div>
        <div className="card p-5 border-emerald-500/20"><p className="text-xs text-slate-400">Adequate Stock</p><p className="text-xl font-bold text-emerald-400 mt-1">{adequate}</p></div>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 flex-wrap">
        <div className="relative flex-1 max-w-xs">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input className="input pl-9" placeholder="Search product or batch…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <select className="input max-w-xs" value={warehouseFilter} onChange={(e) => setWarehouseFilter(e.target.value)}>
          <option value="">All Locations</option>
          {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
        </select>
        <div className="flex gap-1 p-1 bg-surface-800 rounded-xl">
          {(['all', 'expiring', 'expired', 'ok'] as ExpiryFilter[]).map((f) => (
            <button key={f} onClick={() => setExpiryFilter(f)}
              className={`px-3 py-1.5 rounded-lg text-sm transition-colors capitalize ${expiryFilter === f ? 'bg-brand-500 text-white' : 'text-slate-400 hover:text-white'}`}>
              {f}
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
                {['Batch #', 'Product', 'SKU', 'Location', 'Qty', 'Unit Cost', 'Manufacture Date', 'Expiry Date', 'Status', ''].map((h) => (
                  <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 7 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 10 }).map((_, j) => (
                      <td key={j} className="px-4 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-16" /></td>
                    ))}
                  </tr>
                ))
              ) : batches.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-4 py-12 text-center">
                    <Layers size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No batch records found</p>
                    <p className="text-xs text-slate-600 mt-1 mb-4">Create batches manually or they are auto-created when you receive purchase orders.</p>
                    <button onClick={openCreate} className="btn-primary inline-flex items-center gap-2 text-sm">
                      <Plus size={14} /> New Batch / Lot
                    </button>
                  </td>
                </tr>
              ) : batches.map((b) => {
                const { label, badge } = getExpiryStatus(b)
                return (
                  <tr key={b.id} className="table-row">
                    <td className="px-4 py-3.5 font-mono text-brand-400">{b.batch_number}</td>
                    <td className="px-4 py-3.5 text-white">{b.product_name}</td>
                    <td className="px-4 py-3.5 font-mono text-slate-500 text-xs">{b.product_sku}</td>
                    <td className="px-4 py-3.5 text-slate-400">{b.warehouse_name}</td>
                    <td className="px-4 py-3.5 text-white font-semibold">{parseFloat(b.quantity).toFixed(0)}</td>
                    <td className="px-4 py-3.5 text-slate-400">{b.unit_cost ? `${parseFloat(b.unit_cost).toLocaleString()}` : '—'}</td>
                    <td className="px-4 py-3.5 text-slate-400">{b.manufacture_date ? formatDate(b.manufacture_date) : '—'}</td>
                    <td className="px-4 py-3.5 text-slate-400">{b.expiry_date ? formatDate(b.expiry_date) : '—'}</td>
                    <td className="px-4 py-3.5"><span className={badge}>{label}</span></td>
                    <td className="px-4 py-3.5">
                      <button
                        onClick={() => handleDelete(b.id, b.batch_number)}
                        className="p-1.5 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                        title="Delete batch"
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* New Batch Modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-lg shadow-2xl">
            <div className="flex items-center justify-between mb-1">
              <h2 className="text-lg font-bold text-white">New Batch / Lot</h2>
              <button onClick={() => setShowCreate(false)} className="btn-ghost p-1"><X size={18} /></button>
            </div>
            <p className="text-xs text-slate-400 mb-5">
              Associate a batch or lot number with a product and location. Use this for items with expiry dates, recall tracking, or FEFO management.
            </p>

            <div className="space-y-4">
              {/* Product */}
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Product *</label>
                <select className="input" value={form.product_id}
                  onChange={(e) => setForm({ ...form, product_id: e.target.value })}>
                  <option value="">Select product…</option>
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>
                  ))}
                </select>
              </div>

              {/* Location */}
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Location *</label>
                <select className="input" value={form.warehouse_id}
                  onChange={(e) => setForm({ ...form, warehouse_id: e.target.value })}>
                  <option value="">Select location…</option>
                  {warehouses.map((w) => (
                    <option key={w.id} value={w.id}>{w.name}{w.is_default ? ' (default)' : ''}</option>
                  ))}
                </select>
              </div>

              {/* Batch number + Quantity */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Batch / Lot Number *</label>
                  <input className="input" placeholder="e.g. LOT-2024-001"
                    value={form.batch_number}
                    onChange={(e) => setForm({ ...form, batch_number: e.target.value })} />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Quantity *</label>
                  <input type="text" inputMode="decimal" className="input" placeholder="0"
                    value={form.quantity}
                    onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
                </div>
              </div>

              {/* Unit cost */}
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Unit Cost <span className="font-normal text-slate-500 normal-case">(optional)</span></label>
                <input type="text" inputMode="decimal" className="input" placeholder="0.00"
                  value={form.unit_cost}
                  onChange={(e) => setForm({ ...form, unit_cost: e.target.value })} />
              </div>

              {/* Dates */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Manufacture Date</label>
                  <DateInput value={form.manufacture_date}
                    onChange={(v) => setForm({ ...form, manufacture_date: v })} />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Expiry Date</label>
                  <DateInput value={form.expiry_date}
                    onChange={(v) => setForm({ ...form, expiry_date: v })} />
                </div>
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowCreate(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleCreate} disabled={saving} className="btn-primary flex-1 disabled:opacity-50">
                {saving ? 'Creating…' : 'Create Batch'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
