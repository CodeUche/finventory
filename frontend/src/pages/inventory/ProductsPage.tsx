import { useEffect, useState } from 'react'
import { Plus, Search, Package, AlertTriangle, X, Pencil, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { inventoryApi, taxApi } from '@/services/api'
import { formatCurrency, formatAmountInput, stripCommas } from '@/lib/utils'
import type { Product, TaxClass } from '@/types'

const BLANK = {
  sku: '', name: '', brand: '', unit_of_measure: 'bottle',
  cost_price: '', selling_price: '', reorder_level: '10',
  alcohol_percentage: '', volume_ml: '',
  is_taxable: false, tax_class: '',
}

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [showModal, setShowModal] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({ ...BLANK })
  const [taxClasses, setTaxClasses] = useState<TaxClass[]>([])

  const fetchProducts = async () => {
    try {
      const { data } = await inventoryApi.products({ search })
      setProducts(data.results ?? data)
    } catch {
      toast.error('Failed to load products')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchProducts() }, [search])

  useEffect(() => {
    taxApi.classes().then(({ data }) => setTaxClasses(data.results ?? data)).catch(() => {})
  }, [])

  const openCreate = () => {
    setEditId(null)
    setForm({ ...BLANK })
    setShowModal(true)
  }

  const openEdit = (p: Product) => {
    setEditId(p.id)
    setForm({
      sku: p.sku,
      name: p.name,
      brand: p.brand ?? '',
      unit_of_measure: p.unit_of_measure,
      cost_price: formatAmountInput(p.cost_price),
      selling_price: formatAmountInput(p.selling_price),
      reorder_level: String(p.reorder_level),
      alcohol_percentage: String(p.alcohol_percentage ?? ''),
      volume_ml: String(p.volume_ml ?? ''),
      is_taxable: p.is_taxable,
      tax_class: p.tax_class ?? '',
    })
    setShowModal(true)
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    // Strip empty optional numeric fields — DRF rejects '' for DecimalField/IntegerField
    const payload: Record<string, unknown> = {
      ...form,
      cost_price: stripCommas(form.cost_price),
      selling_price: stripCommas(form.selling_price),
    }
    if (!payload.alcohol_percentage) delete payload.alcohol_percentage
    if (!payload.volume_ml) delete payload.volume_ml
    // Send null for tax_class when empty, or when is_taxable is false
    if (!payload.is_taxable) payload.tax_class = null
    else if (!payload.tax_class) payload.tax_class = null
    try {
      if (editId) {
        await inventoryApi.updateProduct(editId, payload)
        toast.success('Product updated')
      } else {
        await inventoryApi.createProduct(payload)
        toast.success('Product created')
      }
      setShowModal(false)
      fetchProducts()
    } catch {
      toast.error(editId ? 'Failed to update product' : 'Failed to create product')
    } finally {
      setSaving(false)
    }
  }

  const upd = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Products</h1>
          <p className="text-slate-400 text-sm">{products.length} SKUs in catalogue</p>
        </div>
        <button onClick={openCreate} className="btn-primary sm:ml-auto">
          <Plus size={16} /> Add Product
        </button>
      </div>

      <div className="relative max-w-sm">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input className="input pl-9" placeholder="Search by name or SKU…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['SKU', 'Product', 'Brand', 'Cost Price', 'Selling Price', 'Stock', 'Status', ''].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 8 }).map((_, j) => (
                      <td key={j} className="px-5 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-24" /></td>
                    ))}
                  </tr>
                ))
              ) : products.length === 0 ? (
                <tr><td colSpan={8} className="px-5 py-12 text-center">
                  <Package size={32} className="mx-auto mb-2 text-slate-600" />
                  <p className="text-slate-500">No products found</p>
                </td></tr>
              ) : (
                products.map((p) => (
                  <tr key={p.id} className="table-row">
                    <td className="px-5 py-3.5 font-mono text-xs text-brand-400">{p.sku}</td>
                    <td className="px-5 py-3.5">
                      <p className="font-medium text-white">{p.name}</p>
                      {p.volume_ml && <p className="text-xs text-slate-500">{p.volume_ml}ml · {p.alcohol_percentage}% ABV</p>}
                    </td>
                    <td className="px-5 py-3.5 text-slate-400">{p.brand || '—'}</td>
                    <td className="px-5 py-3.5 text-slate-300">{formatCurrency(p.cost_price)}</td>
                    <td className="px-5 py-3.5 font-semibold text-white">{formatCurrency(p.selling_price)}</td>
                    <td className="px-5 py-3.5">
                      <span className={p.total_stock <= p.reorder_level ? 'badge-red' : 'badge-green'}>
                        {p.total_stock <= p.reorder_level && <AlertTriangle size={11} />}
                        {p.total_stock} units
                      </span>
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex flex-col gap-1">
                        <span className={p.is_active ? 'badge-green' : 'badge-slate'}>
                          {p.is_active ? 'Active' : 'Inactive'}
                        </span>
                        {p.is_taxable && <span className="badge-orange text-[10px]">VAT</span>}
                      </div>
                    </td>
                    <td className="px-5 py-3.5">
                      <button onClick={() => openEdit(p)} className="btn-ghost p-1.5 text-slate-400 hover:text-white">
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

      {/* Create / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-lg shadow-2xl animate-slide-up max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-6 border-b border-surface-700">
              <h2 className="font-semibold text-white text-lg">{editId ? 'Edit Product' : 'New Product'}</h2>
              <button onClick={() => setShowModal(false)} className="btn-ghost p-1.5"><X size={18} /></button>
            </div>
            <form onSubmit={handleSave} className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">SKU *</label>
                  <input className="input" value={form.sku} onChange={upd('sku')} required disabled={!!editId} placeholder="LQR-001" />
                </div>
                <div>
                  <label className="label">Unit</label>
                  <select className="input" value={form.unit_of_measure} onChange={upd('unit_of_measure')}>
                    {['bottle', 'carton', 'case', 'litre', 'unit'].map((u) => <option key={u} value={u}>{u}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label className="label">Product Name *</label>
                <input className="input" value={form.name} onChange={upd('name')} required placeholder="Johnnie Walker Black 750ml" />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">Brand</label>
                  <input className="input" value={form.brand} onChange={upd('brand')} placeholder="Diageo" />
                </div>
                <div>
                  <label className="label">Reorder Level</label>
                  <input type="number" className="input" value={form.reorder_level} onChange={upd('reorder_level')} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">Cost Price *</label>
                  <input type="text" inputMode="decimal" className="input" value={form.cost_price} onChange={(e) => setForm((f) => ({ ...f, cost_price: formatAmountInput(e.target.value) }))} required placeholder="5,500.00" />
                </div>
                <div>
                  <label className="label">Selling Price *</label>
                  <input type="text" inputMode="decimal" className="input" value={form.selling_price} onChange={(e) => setForm((f) => ({ ...f, selling_price: formatAmountInput(e.target.value) }))} required placeholder="8,500.00" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">Volume (ml)</label>
                  <input type="number" className="input" value={form.volume_ml} onChange={upd('volume_ml')} placeholder="750" />
                </div>
                <div>
                  <label className="label">ABV (%)</label>
                  <input type="number" step="0.1" className="input" value={form.alcohol_percentage} onChange={upd('alcohol_percentage')} placeholder="40.0" />
                </div>
              </div>
              {/* VAT / Tax */}
              <div className="border-t border-surface-700 pt-4 space-y-3">
                <label className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.is_taxable}
                    onChange={(e) => setForm((f) => ({ ...f, is_taxable: e.target.checked, tax_class: e.target.checked ? f.tax_class : '' }))}
                    className="w-4 h-4 accent-orange-500"
                  />
                  <span className="text-sm text-slate-300">Taxable (apply VAT on sales)</span>
                </label>
                {form.is_taxable && (
                  <div>
                    <label className="label">VAT Class</label>
                    <select
                      className="input"
                      value={form.tax_class}
                      onChange={upd('tax_class')}
                    >
                      <option value="">— No VAT class —</option>
                      {taxClasses.map((tc) => (
                        <option key={tc.id} value={tc.id}>
                          {tc.name} ({parseFloat(tc.rate).toFixed(1)}%)
                        </option>
                      ))}
                    </select>
                    {taxClasses.length === 0 && (
                      <p className="text-xs text-slate-500 mt-1">
                        No VAT classes configured. Add them in Tax → VAT Classes.
                      </p>
                    )}
                  </div>
                )}
              </div>

              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowModal(false)} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button type="submit" disabled={saving} className="btn-primary flex-1 justify-center">
                  {saving ? <Loader2 size={16} className="animate-spin" /> : (editId ? 'Save Changes' : 'Create Product')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
