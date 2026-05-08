import { useEffect, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { AlertTriangle, Boxes, Plus, RefreshCw, ArrowLeftRight, Pencil, Trash2, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { inventoryApi, bypassNextGets } from '@/services/api'
import { formatAmountInput, stripCommas } from '@/lib/utils'
import type { Product, StockItem, Warehouse } from '@/types'

interface TransferForm {
  product_id: string
  from_warehouse_id: string
  to_warehouse_id: string
  quantity: string
  notes: string
}

interface AdjustForm {
  product_id: string
  warehouse_id: string
  quantity: string
  reason: string
}

interface NewProductMini {
  name: string
  sku: string
  cost_price: string
  selling_price: string
}

export default function StockPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [items, setItems] = useState<StockItem[]>([])
  const [loading, setLoading] = useState(true)
  const [lowStockTotal, setLowStockTotal] = useState(0)
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
  const [newProduct, setNewProduct] = useState<NewProductMini>({ name: '', sku: '', cost_price: '', selling_price: '' })
  const [creatingProduct, setCreatingProduct] = useState(false)

  // ── Row-level edit / delete ──────────────────────────────────────────────
  const [adjustRowLocked, setAdjustRowLocked] = useState(false)
  const [adjustRowLabel, setAdjustRowLabel] = useState('')
  const [deletingStockId, setDeletingStockId] = useState<string | null>(null)

  // ── Stock transfer modal ─────────────────────────────────────────────────
  const [showTransfer, setShowTransfer] = useState(false)
  const [transferForm, setTransferForm] = useState<TransferForm>({
    product_id: '', from_warehouse_id: '', to_warehouse_id: '', quantity: '', notes: ''
  })
  const [transferSaving, setTransferSaving] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [stockRes, wRes] = await Promise.all([
        inventoryApi.stock(),
        inventoryApi.warehouses(),
      ])
      setItems(stockRes.data.results ?? stockRes.data)
      setWarehouses(wRes.data.results ?? wRes.data)
    } catch { toast.error('Failed to load stock') }
    finally { setLoading(false) }
    // Fetch low stock count independently so a failure doesn't break the main load
    try {
      const lowRes = await inventoryApi.lowStock()
      const lowData = lowRes.data
      setLowStockTotal(Array.isArray(lowData) ? lowData.length : (lowData.count ?? 0))
    } catch { /* fall back to client-side count */ }
  }

  useEffect(() => { load() }, [])
  useDataRefresh(load)

  const openAdjust = async () => {
    setAdjustRowLocked(false)
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
      setNewProduct({ name: '', sku: '', cost_price: '', selling_price: '' })
      setCreatingProduct(false)
      setShowAdjust(true)
    } catch { toast.error('Failed to load products') }
  }

  const openEditRow = async (s: StockItem) => {
    setAdjustRowLocked(true)
    setAdjustRowLabel(`${s.product_name} @ ${s.warehouse_name}`)
    setAdjustForm({ product_id: s.product, warehouse_id: s.warehouse, quantity: '', reason: '' })
    setNewProduct({ name: '', sku: '', cost_price: '', selling_price: '' })
    setCreatingProduct(false)
    setShowAdjust(true)
  }

  const handleDeleteStockItem = async (s: StockItem) => {
    const qty = parseFloat(s.quantity_on_hand)
    const qtyText = qty > 0 ? `\n\nCurrent quantity (${qty.toFixed(0)} units) will be zeroed out and the record removed.` : '\n\nThis record has 0 units on hand.'
    if (!confirm(`Remove stock record for "${s.product_name}" at ${s.warehouse_name}?${qtyText}`)) return
    setDeletingStockId(s.id)
    try {
      await inventoryApi.deleteStockItem(s.id)
      toast.success(`Stock record for "${s.product_name}" removed`)
      load()
    } catch (err: any) {
      const msg = err?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : 'Failed to remove stock record')
    } finally {
      setDeletingStockId(null)
    }
  }

  const handleAdjust = async () => {
    if (!adjustForm.warehouse_id) { toast.error('Select a warehouse'); return }
    if (!adjustForm.quantity || parseFloat(adjustForm.quantity) === 0) {
      toast.error('Enter a non-zero quantity'); return
    }
    if (!adjustForm.reason.trim()) { toast.error('Enter a reason'); return }

    let productId = adjustForm.product_id

    // If creating a new product inline
    if (adjustForm.product_id === '__new__') {
      if (!newProduct.name.trim()) { toast.error('Enter a product name'); return }
      if (!newProduct.sku.trim()) { toast.error('Enter a SKU'); return }
      setCreatingProduct(true)
      try {
        const { data: created } = await inventoryApi.createProduct({
          name: newProduct.name.trim(),
          sku: newProduct.sku.trim(),
          cost_price: stripCommas(newProduct.cost_price) || '0',
          selling_price: stripCommas(newProduct.selling_price) || '0',
          product_type: 'physical',
          unit_of_measure: 'unit',
          reorder_level: 10,
        })
        productId = created.id
        toast.success(`Product "${created.name}" created`)
      } catch (err: any) {
        const msg = err?.response?.data?.name?.[0] || err?.response?.data?.sku?.[0] || err?.response?.data?.error || 'Failed to create product'
        toast.error(msg)
        setCreatingProduct(false)
        return
      } finally {
        setCreatingProduct(false)
      }
    } else if (!productId) {
      toast.error('Select a product'); return
    }

    setSaving(true)
    try {
      await inventoryApi.adjustStock({
        product_id: productId,
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

  const openTransfer = async () => {
    try {
      const pRes = await inventoryApi.products({ page_size: 200, is_active: true })
      const pList: Product[] = pRes.data.results ?? pRes.data
      setProducts(pList)
      setTransferForm({
        product_id: pList[0]?.id ?? '',
        from_warehouse_id: warehouses[0]?.id ?? '',
        to_warehouse_id: warehouses[1]?.id ?? warehouses[0]?.id ?? '',
        quantity: '',
        notes: '',
      })
      setShowTransfer(true)
    } catch { toast.error('Failed to load products') }
  }

  const handleTransfer = async () => {
    if (!transferForm.product_id) { toast.error('Select a product'); return }
    if (!transferForm.from_warehouse_id) { toast.error('Select a source warehouse'); return }
    if (!transferForm.to_warehouse_id) { toast.error('Select a destination warehouse'); return }
    if (transferForm.from_warehouse_id === transferForm.to_warehouse_id) {
      toast.error('Source and destination must be different warehouses'); return
    }
    const qty = parseFloat(transferForm.quantity)
    if (!transferForm.quantity || isNaN(qty) || qty <= 0) {
      toast.error('Enter a positive quantity'); return
    }
    setTransferSaving(true)
    try {
      const result = await inventoryApi.transferStock({
        product_id: transferForm.product_id,
        from_warehouse_id: transferForm.from_warehouse_id,
        to_warehouse_id: transferForm.to_warehouse_id,
        quantity: qty,
        notes: transferForm.notes,
      })
      toast.success(`Stock transferred · Ref: ${result.data.reference}`)
      setShowTransfer(false)
      load()
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Transfer failed'))
    } finally {
      setTransferSaving(false)
    }
  }

  // lowStockTotal from the dedicated endpoint (includes products with no stock movements)
  const lowCount = lowStockTotal || items.filter((i) => i.stock_level === 'low' || i.is_low_stock).length
  const displayed = items
    .filter((i) => {
      if (filter === 'low') return i.stock_level === 'low' || i.is_low_stock
      return true
    })
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
          <button onClick={() => { bypassNextGets(); load() }} className="btn-ghost p-2.5"><RefreshCw size={16} /></button>
          <button onClick={openTransfer} className="btn-secondary flex items-center gap-2 py-2 px-4" title="Transfer stock between locations">
            <ArrowLeftRight size={15} />
            Transfer
          </button>
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
            <strong>{lowCount} product{lowCount !== 1 ? 's' : ''}</strong> below reorder level. Consider creating{' '}
            <button
              onClick={() => navigate('/purchases?create=1')}
              className="underline underline-offset-2 font-semibold hover:text-white transition-colors"
            >
              purchase orders
            </button>.
          </p>
        </div>
      )}

      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Product', 'SKU', 'Warehouse', 'On Hand', 'Reserved', 'Available', 'Status', ''].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 8 }).map((_, j) => (
                      <td key={j} className="px-5 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-20" /></td>
                    ))}
                  </tr>
                ))
              ) : displayed.length === 0 ? (
                <tr><td colSpan={8} className="px-5 py-12 text-center">
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
                      {(s.stock_level === 'low' || s.is_low_stock) ? (
                        <span className="badge-red"><AlertTriangle size={11} /> Low</span>
                      ) : (
                        <span className="badge-green">OK</span>
                      )}
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => openEditRow(s)}
                          title="Adjust quantity"
                          className="btn-ghost p-1.5 text-slate-400 hover:text-white"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          onClick={() => handleDeleteStockItem(s)}
                          disabled={deletingStockId === s.id}
                          title="Remove stock record"
                          className="btn-ghost p-1.5 text-slate-400 hover:text-red-400"
                        >
                          {deletingStockId === s.id
                            ? <Loader2 size={14} className="animate-spin" />
                            : <Trash2 size={14} />}
                        </button>
                      </div>
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
            <h2 className="text-lg font-bold text-white mb-1">
              {adjustRowLocked ? 'Adjust Stock' : 'Add / Adjust Stock'}
            </h2>
            <p className="text-xs text-slate-400 mb-5">
              {adjustRowLocked
                ? `Adjusting: ${adjustRowLabel}. Enter a positive quantity to add stock or negative to remove.`
                : 'Use this to enter opening stock for new products or correct quantities. Positive quantity adds stock; negative removes it.'}
            </p>

            <div className="space-y-4">
              {adjustRowLocked ? (
                /* Locked row-edit mode: show product + warehouse as read-only */
                <div className="bg-surface-700/50 border border-surface-600 rounded-xl px-4 py-3 flex items-center gap-2">
                  <Pencil size={13} className="text-brand-400 shrink-0" />
                  <span className="text-sm text-white font-medium">{adjustRowLabel}</span>
                </div>
              ) : (
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Product *</label>
                  <select
                    className="input"
                    value={adjustForm.product_id}
                    onChange={(e) => setAdjustForm({ ...adjustForm, product_id: e.target.value })}
                  >
                    <option value="">Select product…</option>
                    <option value="__new__">+ Create New Product…</option>
                    {products.map((p) => (
                      <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>
                    ))}
                  </select>
                </div>
              )}

              {/* Inline new product form */}
              {adjustForm.product_id === '__new__' && (
                <div className="bg-surface-700/50 border border-surface-600 rounded-xl p-4 space-y-3">
                  <p className="text-xs font-semibold text-brand-400 uppercase tracking-wider">New Product Details</p>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs text-slate-400 block mb-1">Product Name *</label>
                      <input className="input py-2 text-sm" placeholder="e.g. Mineral Water"
                        value={newProduct.name}
                        onChange={(e) => setNewProduct((p) => ({ ...p, name: e.target.value }))} />
                    </div>
                    <div>
                      <label className="text-xs text-slate-400 block mb-1">SKU *</label>
                      <input className="input py-2 text-sm" placeholder="e.g. MIN-001"
                        value={newProduct.sku}
                        onChange={(e) => setNewProduct((p) => ({ ...p, sku: e.target.value.toUpperCase() }))} />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs text-slate-400 block mb-1">Cost Price</label>
                      <input type="text" inputMode="decimal" className="input py-2 text-sm" placeholder="0.00"
                        value={newProduct.cost_price}
                        onChange={(e) => setNewProduct((p) => ({ ...p, cost_price: formatAmountInput(e.target.value) }))} />
                    </div>
                    <div>
                      <label className="text-xs text-slate-400 block mb-1">Selling Price</label>
                      <input type="text" inputMode="decimal" className="input py-2 text-sm" placeholder="0.00"
                        value={newProduct.selling_price}
                        onChange={(e) => setNewProduct((p) => ({ ...p, selling_price: formatAmountInput(e.target.value) }))} />
                    </div>
                  </div>
                </div>
              )}

              {!adjustRowLocked && (
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
              )}

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
              <button onClick={handleAdjust} disabled={saving || creatingProduct} className="btn-primary flex-1 disabled:opacity-50">
                {creatingProduct ? 'Creating product…' : saving ? 'Saving…' : adjustForm.product_id === '__new__' ? 'Create & Add Stock' : 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Transfer Stock Modal */}
      {showTransfer && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-md shadow-2xl">
            <div className="flex items-center gap-3 mb-1">
              <div className="w-9 h-9 rounded-xl bg-brand-500/15 flex items-center justify-center">
                <ArrowLeftRight size={18} className="text-brand-400" />
              </div>
              <h2 className="text-lg font-bold text-white">Transfer Stock</h2>
            </div>
            <p className="text-xs text-slate-400 mb-5">
              Move stock between locations. Stock is deducted from the source and added to the destination atomically.
            </p>

            <div className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Product *</label>
                <select className="input" value={transferForm.product_id}
                  onChange={(e) => setTransferForm({ ...transferForm, product_id: e.target.value })}>
                  <option value="">Select product…</option>
                  {products.map((p) => (
                    <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">From *</label>
                  <select className="input" value={transferForm.from_warehouse_id}
                    onChange={(e) => setTransferForm({ ...transferForm, from_warehouse_id: e.target.value })}>
                    <option value="">Source warehouse…</option>
                    {warehouses.map((w) => (
                      <option key={w.id} value={w.id}>{w.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">To *</label>
                  <select className="input" value={transferForm.to_warehouse_id}
                    onChange={(e) => setTransferForm({ ...transferForm, to_warehouse_id: e.target.value })}>
                    <option value="">Destination…</option>
                    {warehouses
                      .filter((w) => w.id !== transferForm.from_warehouse_id)
                      .map((w) => (
                        <option key={w.id} value={w.id}>{w.name}</option>
                      ))}
                  </select>
                </div>
              </div>

              {/* Arrow indicator */}
              {transferForm.from_warehouse_id && transferForm.to_warehouse_id && (
                <div className="flex items-center gap-2 text-xs text-slate-500 bg-surface-700/50 rounded-xl px-3 py-2">
                  <span className="text-white font-medium">
                    {warehouses.find((w) => w.id === transferForm.from_warehouse_id)?.name}
                  </span>
                  <ArrowLeftRight size={12} className="text-brand-400 shrink-0" />
                  <span className="text-white font-medium">
                    {warehouses.find((w) => w.id === transferForm.to_warehouse_id)?.name}
                  </span>
                </div>
              )}

              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Quantity *</label>
                <input
                  type="text" inputMode="decimal" className="input"
                  placeholder="e.g. 50"
                  value={transferForm.quantity}
                  onChange={(e) => setTransferForm({ ...transferForm, quantity: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">Notes <span className="font-normal text-slate-500 normal-case">(optional)</span></label>
                <input className="input" placeholder="e.g. Replenishing branch stock"
                  value={transferForm.notes}
                  onChange={(e) => setTransferForm({ ...transferForm, notes: e.target.value })}
                />
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowTransfer(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleTransfer} disabled={transferSaving} className="btn-primary flex-1 disabled:opacity-50 flex items-center justify-center gap-2">
                {transferSaving ? 'Transferring…' : <><ArrowLeftRight size={14} /> Transfer Stock</>}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
