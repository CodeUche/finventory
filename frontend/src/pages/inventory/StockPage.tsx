import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, Boxes, Plus, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import { inventoryApi } from '@/services/api'
import type { Product, StockItem, Warehouse } from '@/types'

interface AdjustForm {
  product_id: string
  warehouse_id: string
  quantity: string
  reason: string
}

export default function StockPage() {
  const [searchParams] = useSearchParams()
  const [items, setItems] = useState<StockItem[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'low'>(
    searchParams.get('filter') === 'low' ? 'low' : 'all'
  )
  const [warehouseFilter, setWarehouseFilter] = useState<string>('all')

  // ── Stock adjustment modal ──────────────────────────────────────────────
  const [showAdjust, setShowAdjust] = useState(false)
  const [products, setProducts] = useState<Product[]>([])
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [adjustForm, setAdjustForm] = useState<AdjustForm>({
    product_id: '', warehouse_id: '', quantity: '', reason: ''
  })
  const [saving, setSaving] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [stockRes, wRes] = await Promise.all([
        inventoryApi.stock(),
        inventoryApi.warehouses(),
      ])
      setItems(stockRes.data.results ?? stockRes.data)
      const wList: Warehouse[] = wRes.data.results ?? wRes.data
      // Merge into existing warehouses state (used by adjust modal too)
      setWarehouses(wList)
    } catch { toast.error('Failed to load stock') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const openAdjust = async () => {
    try {
      const pRes = await inventoryApi.products({ page_size: 200, is_active: true })
      const pList: Product[] = pRes.data.results ?? pRes.data
      setProducts(pList)
      setAdjustForm({
        product_id: pList[0]?.id ?? '',
        warehouse_id: warehouses[0]?.id ?? '',
        quantity: '',
        reason: 'Opening stock',
      })
      setShowAdjust(true)
    } catch { toast.error('Failed to load products') }
  }

  const handleAdjust = async () => {
    if (!adjustForm.product_id) { toast.error('Select a product'); return }
    if (!adjustForm.warehouse_id) { toast.error('Select a warehouse'); return }
    if (!adjustForm.quantity || parseFloat(adjustForm.quantity) === 0) {
      toast.error('Enter a non-zero quantity'); return
    }
    if (!adjustForm.reason.trim()) { toast.error('Enter a reason'); return }
    setSaving(true)
    try {
      await inventoryApi.adjustStock({
        product_id: adjustForm.product_id,
        warehouse_id: adjustForm.warehouse_id,
        quantity: parseFloat(adjustForm.quantity),
        reason: adjustForm.reason,
      })
      toast.success('Stock updated')
      setShowAdjust(false)
      load()
    } catch (err: any) {
      const msg = err?.response?.data?.error || 'Failed to adjust stock'
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  const lowCount = items.filter((i) => i.is_low_stock).length
  const displayed = items
    .filter((i) => filter === 'low' ? i.is_low_stock : true)
    .filter((i) => warehouseFilter === 'all' ? true : i.warehouse_name === warehouseFilter)

  // Unique warehouse names for the filter dropdown
  const warehouseNames = Array.from(new Set(items.map((i) => i.warehouse_name))).sort()

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Stock Levels</h1>
          <p className="text-slate-400 text-sm">{displayed.length} of {items.length} product-warehouse pairs</p>
        </div>
        <div className="flex items-center gap-2 ml-auto flex-wrap">
          {/* Warehouse filter */}
          <select
            className="input py-2 pr-8 text-sm"
            value={warehouseFilter}
            onChange={(e) => setWarehouseFilter(e.target.value)}
          >
            <option value="all">All Warehouses</option>
            {warehouseNames.map((w) => <option key={w} value={w}>{w}</option>)}
          </select>
          <button onClick={() => setFilter('all')} className={filter === 'all' ? 'btn-primary py-2 px-4' : 'btn-secondary py-2 px-4'}>All</button>
          <button onClick={() => setFilter('low')} className={filter === 'low' ? 'btn-danger py-2 px-4' : 'btn-secondary py-2 px-4'}>
            <AlertTriangle size={14} /> Low Stock {lowCount > 0 && `(${lowCount})`}
          </button>
          <button onClick={load} className="btn-ghost p-2.5"><RefreshCw size={16} /></button>
          <button onClick={openAdjust} className="btn-primary flex items-center gap-2 py-2 px-4">
            <Plus size={15} />
            Add / Adjust Stock
          </button>
        </div>
      </div>

      {lowCount > 0 && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 flex items-center gap-3">
          <AlertTriangle size={18} className="text-red-400 shrink-0" />
          <p className="text-sm text-red-300">
            <strong>{lowCount} product{lowCount !== 1 ? 's' : ''}</strong> below reorder level. Consider creating purchase orders.
          </p>
        </div>
      )}

      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Product', 'SKU', 'Warehouse', 'On Hand', 'Reserved', 'Available', 'Status'].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 7 }).map((_, j) => (
                      <td key={j} className="px-5 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-20" /></td>
                    ))}
                  </tr>
                ))
              ) : displayed.length === 0 ? (
                <tr><td colSpan={7} className="px-5 py-12 text-center">
                  <Boxes size={32} className="mx-auto mb-2 text-slate-600" />
                  <p className="text-slate-500 mb-3">
                    {filter === 'low' ? 'No low stock items' : 'No stock data yet'}
                  </p>
                  {filter === 'all' && (
                    <button onClick={openAdjust} className="btn-primary inline-flex items-center gap-2 text-sm">
                      <Plus size={14} />
                      Add Opening Stock
                    </button>
                  )}
                </td></tr>
              ) : (
                displayed.map((s) => (
                  <tr key={s.id} className="table-row">
                    <td className="px-5 py-3.5 font-medium text-white">{s.product_name}</td>
                    <td className="px-5 py-3.5 font-mono text-xs text-brand-400">{s.product_sku}</td>
                    <td className="px-5 py-3.5 text-slate-400">{s.warehouse_name}</td>
                    <td className="px-5 py-3.5 font-semibold text-white">{parseFloat(s.quantity_on_hand).toFixed(0)}</td>
                    <td className="px-5 py-3.5 text-slate-400">0</td>
                    <td className="px-5 py-3.5 text-white">{parseFloat(s.quantity_available).toFixed(0)}</td>
                    <td className="px-5 py-3.5">
                      <span className={s.is_low_stock ? 'badge-red' : 'badge-green'}>
                        {s.is_low_stock ? <><AlertTriangle size={11} /> Low</> : 'OK'}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add / Adjust Stock Modal */}
      {showAdjust && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-md shadow-2xl">
            <h2 className="text-lg font-bold text-white mb-1">Add / Adjust Stock</h2>
            <p className="text-xs text-slate-400 mb-5">
              Use this to enter opening stock for new products or correct quantities.
              Positive quantity adds stock; negative removes it.
            </p>

            <div className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Product *</label>
                <select
                  className="input"
                  value={adjustForm.product_id}
                  onChange={(e) => setAdjustForm({ ...adjustForm, product_id: e.target.value })}
                >
                  <option value="">Select product…</option>
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Warehouse *</label>
                <select
                  className="input"
                  value={adjustForm.warehouse_id}
                  onChange={(e) => setAdjustForm({ ...adjustForm, warehouse_id: e.target.value })}
                >
                  <option value="">Select warehouse…</option>
                  {warehouses.map((w) => (
                    <option key={w.id} value={w.id}>{w.name}{w.is_default ? ' (default)' : ''}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
                  Quantity * <span className="text-slate-500 normal-case font-normal">(use negative to reduce)</span>
                </label>
                <input
                  type="number"
                  className="input"
                  placeholder="e.g. 50 or -5"
                  step="1"
                  value={adjustForm.quantity}
                  onChange={(e) => setAdjustForm({ ...adjustForm, quantity: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Reason *</label>
                <input
                  className="input"
                  placeholder="e.g. Opening stock, Damaged goods, Recount"
                  value={adjustForm.reason}
                  onChange={(e) => setAdjustForm({ ...adjustForm, reason: e.target.value })}
                />
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowAdjust(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleAdjust} disabled={saving} className="btn-primary flex-1 disabled:opacity-50">
                {saving ? 'Saving…' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
