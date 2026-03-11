import { useEffect, useState } from 'react'
import { Plus, Search, Package, AlertTriangle, X, Pencil, Loader2, TrendingUp, TrendingDown, History, Maximize2, Minimize2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { inventoryApi, taxApi, salesApi } from '@/services/api'
import { formatCurrency, formatAmountInput, stripCommas, formatDate } from '@/lib/utils'
import type { Product, TaxClass } from '@/types'
import SortSelect from '@/components/SortSelect'

const BLANK = {
  sku: '', name: '', brand: '', unit_of_measure: 'unit',
  product_type: 'physical',
  cost_price: '', selling_price: '', reorder_level: '10',
  alcohol_percentage: '', volume_ml: '',
  is_taxable: false, tax_class: '',
}

const BLANK_BATCH = {
  enabled: false,
  quantity: '',
  warehouse: '',
}

const PRODUCT_TYPES = [
  { value: 'physical', label: 'Physical (tracked inventory)' },
  { value: 'service', label: 'Service (no inventory)' },
  { value: 'digital', label: 'Digital (no inventory)' },
]

const UNITS_OF_MEASURE = [
  'bottle', 'carton', 'case', 'litre', 'unit', 'hour', 'day', 'kg', 'piece',
]

interface SalesHistoryItem {
  invoice_id: string
  invoice_number: string
  issue_date: string
  customer_name: string
  sold_by: string
  warehouse: string
  payment_method: string
  quantity: string
  unit_price: string
  line_total: string
  status: string
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
  const [sortBy, setSortBy] = useState('name')
  const [historySort, setHistorySort] = useState('-issue_date')
  const [historyProduct, setHistoryProduct] = useState<Product | null>(null)
  const [historyItems, setHistoryItems] = useState<SalesHistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historySearch, setHistorySearch] = useState('')
  const [historyFullscreen, setHistoryFullscreen] = useState(false)
  const [batchForm, setBatchForm] = useState({ ...BLANK_BATCH })
  const [warehouses, setWarehouses] = useState<{ id: string; name: string }[]>([])

  const fetchProducts = async () => {
    try {
      const { data } = await inventoryApi.products({ search, ordering: sortBy })
      setProducts(data.results ?? data)
    } catch {
      toast.error('Failed to load products')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchProducts() }, [search, sortBy])

  useEffect(() => {
    taxApi.classes().then(({ data }) => setTaxClasses(data.results ?? data)).catch(() => {})
  }, [])

  const openCreate = () => {
    setEditId(null)
    setForm({ ...BLANK })
    setBatchForm({ ...BLANK_BATCH })
    if (warehouses.length === 0) {
      inventoryApi.warehouses().then(({ data }) => setWarehouses(data.results ?? data)).catch(() => {})
    }
    setShowModal(true)
  }

  const openEdit = (p: Product) => {
    setEditId(p.id)
    setForm({
      sku: p.sku,
      name: p.name,
      brand: p.brand ?? '',
      unit_of_measure: p.unit_of_measure,
      product_type: (p as any).product_type ?? 'physical',
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
        const { data: newProduct } = await inventoryApi.createProduct(payload)
        // Set opening stock if requested
        if (batchForm.enabled && batchForm.quantity && batchForm.warehouse && form.product_type === 'physical') {
          try {
            await inventoryApi.adjustStock({
              product_id: newProduct.id,
              warehouse_id: batchForm.warehouse,
              quantity: parseFloat(batchForm.quantity),
              reason: 'Opening stock',
            })
            toast.success('Product created with opening stock')
          } catch {
            toast.success('Product created')
            toast.error('Opening stock could not be saved — add it from the Stock page')
          }
        } else {
          toast.success('Product created')
        }
      }
      setShowModal(false)
      fetchProducts()
    } catch {
      toast.error(editId ? 'Failed to update product' : 'Failed to create product')
    } finally {
      setSaving(false)
    }
  }

  const openHistory = async (p: Product) => {
    setHistoryProduct(p)
    setHistoryItems([])
    setHistoryLoading(true)
    try {
      const { data } = await salesApi.productHistory(p.id)
      setHistoryItems(data.results ?? [])
    } catch {
      toast.error('Failed to load sales history')
    } finally {
      setHistoryLoading(false)
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

      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative max-w-sm">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input className="input pl-9" placeholder="Search by name or SKU…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <SortSelect
          value={sortBy}
          onChange={setSortBy}
          options={[
            { label: 'Name A→Z', value: 'name' },
            { label: 'Name Z→A', value: '-name' },
            { label: 'Newest first', value: '-created_at' },
            { label: 'Oldest first', value: 'created_at' },
            { label: 'Cost ↑', value: 'cost_price' },
            { label: 'Cost ↓', value: '-cost_price' },
            { label: 'Selling Price ↑', value: 'selling_price' },
            { label: 'Selling Price ↓', value: '-selling_price' },
          ]}
        />
      </div>

      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['SKU', 'Product', 'Type', 'Cost Price', 'Selling Price', 'Profit / Margin', 'Stock', 'Status', ''].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 9 }).map((_, j) => (
                      <td key={j} className="px-5 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-24" /></td>
                    ))}
                  </tr>
                ))
              ) : products.length === 0 ? (
                <tr><td colSpan={9} className="px-5 py-12 text-center">
                  <Package size={32} className="mx-auto mb-2 text-slate-600" />
                  <p className="text-slate-500">No products found</p>
                </td></tr>
              ) : (
                products.map((p) => {
                  const cost = parseFloat(p.cost_price) || 0
                  const sell = parseFloat(p.selling_price) || 0
                  const profit = sell - cost
                  const margin = sell > 0 ? ((profit / sell) * 100).toFixed(1) : '0.0'
                  const isProfit = profit >= 0
                  return (
                  <tr key={p.id} className="table-row">
                    <td className="px-5 py-3.5 font-mono text-xs text-brand-400">{p.sku}</td>
                    <td className="px-5 py-3.5">
                      <p className="font-medium text-white">{p.name}</p>
                      {p.volume_ml && <p className="text-xs text-slate-500">{p.volume_ml}ml · {p.alcohol_percentage}% ABV</p>}
                    </td>
                    <td className="px-5 py-3.5">
                      {(p as any).product_type === 'service' ? <span className="badge-blue">Service</span>
                        : (p as any).product_type === 'digital' ? <span className="badge-orange">Digital</span>
                        : <span className="badge-slate">Physical</span>}
                    </td>
                    <td className="px-5 py-3.5 text-slate-300">{formatCurrency(p.cost_price)}</td>
                    <td className="px-5 py-3.5 font-semibold text-white">{formatCurrency(p.selling_price)}</td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-1.5">
                        {isProfit
                          ? <TrendingUp size={13} className="text-emerald-400 shrink-0" />
                          : <TrendingDown size={13} className="text-red-400 shrink-0" />}
                        <div>
                          <p className={`text-sm font-semibold ${isProfit ? 'text-emerald-400' : 'text-red-400'}`}>
                            {formatCurrency(profit.toFixed(2))}
                          </p>
                          <p className="text-xs text-slate-500">{margin}% margin</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3.5">
                      {(p as any).product_type === 'service' || (p as any).product_type === 'digital' ? (
                        <span className="badge-slate">N/A</span>
                      ) : (
                        <span className={p.total_stock <= p.reorder_level ? 'badge-red' : 'badge-green'}>
                          {p.total_stock <= p.reorder_level && <AlertTriangle size={11} />}
                          {p.total_stock} units
                        </span>
                      )}
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
                      <div className="flex items-center gap-1">
                        <button onClick={() => openEdit(p)} className="btn-ghost p-1.5 text-slate-400 hover:text-white" title="Edit">
                          <Pencil size={14} />
                        </button>
                        <button onClick={() => openHistory(p)} className="btn-ghost p-1.5 text-slate-400 hover:text-brand-400" title="Sales History">
                          <History size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                  )
                })
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
              {/* Product Type */}
              <div>
                <label className="label">Product Type *</label>
                <select className="input" value={form.product_type} onChange={upd('product_type')}>
                  {PRODUCT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">SKU *</label>
                  <input className="input" value={form.sku} onChange={upd('sku')} required disabled={!!editId} placeholder="SVC-001" />
                </div>
                <div>
                  <label className="label">Unit</label>
                  <select className="input" value={form.unit_of_measure} onChange={upd('unit_of_measure')}>
                    {UNITS_OF_MEASURE.map((u) => <option key={u} value={u}>{u}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label className="label">Product / Service Name *</label>
                <input className="input" value={form.name} onChange={upd('name')} required placeholder="e.g. Consulting, Delivery, Software License" />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">Brand / Vendor</label>
                  <input className="input" value={form.brand} onChange={upd('brand')} placeholder="Optional" />
                </div>
                {form.product_type === 'physical' && (
                  <div>
                    <label className="label">Reorder Level</label>
                    <input type="number" className="input" value={form.reorder_level} onChange={upd('reorder_level')} />
                  </div>
                )}
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
              {/* Physical-only fields */}
              {form.product_type === 'physical' && (
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
              )}
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

              {/* Opening stock (create only, physical only) */}
              {!editId && form.product_type === 'physical' && (
                <div className="border-t border-surface-700 pt-4 space-y-3">
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={batchForm.enabled}
                      onChange={(e) => setBatchForm((b) => ({ ...b, enabled: e.target.checked }))}
                      className="w-4 h-4 accent-orange-500"
                    />
                    <span className="text-sm text-slate-300">Set opening stock quantity</span>
                  </label>
                  {batchForm.enabled && (
                    <div className="grid grid-cols-2 gap-3 pl-1">
                      <div>
                        <label className="label">Warehouse *</label>
                        <select className="input" value={batchForm.warehouse}
                          onChange={(e) => setBatchForm((b) => ({ ...b, warehouse: e.target.value }))}>
                          <option value="">— Select warehouse —</option>
                          {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="label">Quantity *</label>
                        <input type="number" className="input" placeholder="0" min="0"
                          value={batchForm.quantity}
                          onChange={(e) => setBatchForm((b) => ({ ...b, quantity: e.target.value }))} />
                      </div>
                    </div>
                  )}
                </div>
              )}

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

      {/* Sales History Modal */}
      {historyProduct && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className={`bg-surface-800 border border-surface-700 rounded-2xl w-full shadow-2xl animate-slide-up flex flex-col ${historyFullscreen ? 'max-w-full max-h-full h-full' : 'max-w-5xl max-h-[90vh]'}`}>
            <div className="flex items-center justify-between p-5 border-b border-surface-700 shrink-0">
              <div>
                <h2 className="font-semibold text-white text-lg">Sales History</h2>
                <p className="text-xs text-slate-400 mt-0.5">{historyProduct.name} · {historyProduct.sku}</p>
              </div>
              <div className="flex items-center gap-2">
                <SortSelect
                  value={historySort}
                  onChange={setHistorySort}
                  options={[
                    { label: 'Newest first', value: '-issue_date' },
                    { label: 'Oldest first', value: 'issue_date' },
                    { label: 'Amount ↓', value: '-line_total' },
                    { label: 'Amount ↑', value: 'line_total' },
                    { label: 'Qty ↓', value: '-quantity' },
                    { label: 'Qty ↑', value: 'quantity' },
                  ]}
                />
                <button onClick={() => setHistoryFullscreen(f => !f)} className="btn-ghost p-1.5" title={historyFullscreen ? 'Exit fullscreen' : 'Fullscreen'}>
                  {historyFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
                </button>
                <button onClick={() => { setHistoryProduct(null); setHistorySearch(''); setHistoryFullscreen(false) }} className="btn-ghost p-1.5"><X size={18} /></button>
              </div>
            </div>
            {/* Search bar */}
            <div className="px-5 py-3 border-b border-surface-700 shrink-0">
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  type="text"
                  placeholder="Search by date, customer, sold by..."
                  value={historySearch}
                  onChange={e => setHistorySearch(e.target.value)}
                  className="input pl-8 py-1.5 text-sm w-full"
                />
              </div>
            </div>
            <div className="overflow-auto flex-1">
              {historyLoading ? (
                <div className="py-16 text-center"><Loader2 size={24} className="animate-spin mx-auto text-brand-400" /></div>
              ) : historyItems.length === 0 ? (
                <div className="py-16 text-center">
                  <History size={32} className="mx-auto mb-2 text-slate-600" />
                  <p className="text-slate-500">No sales recorded for this product</p>
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-700">
                      {['Invoice', 'Date', 'Customer', 'Sold By', 'Warehouse', 'Payment', 'Qty', 'Unit Price', 'Total', 'Status'].map((h) => (
                        <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[...historyItems].filter(item => {
                      if (!historySearch) return true
                      const q = historySearch.toLowerCase()
                      return (
                        item.invoice_number.toLowerCase().includes(q) ||
                        item.issue_date.includes(q) ||
                        (item.customer_name ?? '').toLowerCase().includes(q) ||
                        (item.sold_by ?? '').toLowerCase().includes(q)
                      )
                    }).sort((a, b) => {
                      const asc = !historySort.startsWith('-')
                      const field = historySort.replace(/^-/, '')
                      let av: number | string = 0, bv: number | string = 0
                      if (field === 'issue_date') { av = a.issue_date; bv = b.issue_date }
                      else if (field === 'line_total') { av = parseFloat(a.line_total); bv = parseFloat(b.line_total) }
                      else if (field === 'quantity') { av = parseFloat(a.quantity); bv = parseFloat(b.quantity) }
                      if (av < bv) return asc ? -1 : 1
                      if (av > bv) return asc ? 1 : -1
                      return 0
                    }).map((item, idx) => (
                      <tr key={idx} className="table-row">
                        <td className="px-4 py-3 font-mono text-xs text-brand-400">{item.invoice_number}</td>
                        <td className="px-4 py-3 text-slate-300 whitespace-nowrap">{formatDate(item.issue_date)}</td>
                        <td className="px-4 py-3 text-white">{item.customer_name}</td>
                        <td className="px-4 py-3 text-slate-300">{item.sold_by}</td>
                        <td className="px-4 py-3 text-slate-300">{item.warehouse}</td>
                        <td className="px-4 py-3 capitalize text-slate-300">{item.payment_method.replace('_', ' ')}</td>
                        <td className="px-4 py-3 text-white font-medium">{item.quantity}</td>
                        <td className="px-4 py-3 text-slate-300">{formatCurrency(item.unit_price)}</td>
                        <td className="px-4 py-3 font-semibold text-white">{formatCurrency(item.line_total)}</td>
                        <td className="px-4 py-3">
                          <span className={`badge-${item.status === 'paid' ? 'green' : item.status === 'voided' ? 'red' : 'slate'}`}>
                            {item.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
