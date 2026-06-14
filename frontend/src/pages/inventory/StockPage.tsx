import { useEffect, useRef, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { usePagination } from '@/hooks/usePagination'
import Pagination from '@/components/Pagination'
import { AlertTriangle, Boxes, Plus, RefreshCw, ArrowLeftRight, Pencil, Trash2, Loader2, CheckSquare, Search } from 'lucide-react'
import toast from 'react-hot-toast'
import { inventoryApi, bypassNextGets } from '@/services/api'
import { stripCommas } from '@/lib/utils'
import AmountInput from '@/components/AmountInput'
import SortSelect from '@/components/SortSelect'
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
  const [filter, setFilter] = useState<'all' | 'medium' | 'low'>(
    searchParams.get('filter') === 'low' ? 'low' : 'all'
  )
  const [warehouseFilter, setWarehouseFilter] = useState<string>('all')
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState('name')

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

  // ── Multi-select + bulk add to warehouse ────────────────────────────────
  const [selectedItems, setSelectedItems] = useState<StockItem[]>([])
  const [bulkWarehouse, setBulkWarehouse] = useState('')
  const [bulkQty, setBulkQty] = useState('')
  const [bulkAdding, setBulkAdding] = useState(false)
  const bulkInProgress = useRef(false)

  // ── Stock transfer modal ─────────────────────────────────────────────────
  const [showTransfer, setShowTransfer] = useState(false)
  const [transferForm, setTransferForm] = useState<TransferForm>({
    product_id: '', from_warehouse_id: '', to_warehouse_id: '', quantity: '', notes: ''
  })
  const [transferSaving, setTransferSaving] = useState(false)

  const loadStock = async (whId: string, silent = false) => {
    if (!silent) setLoading(true)
    try {
      const params = whId === 'all' ? undefined : { warehouse: whId }
      const stockRes = await inventoryApi.stock(params)
      const data: StockItem[] = stockRes.data.results ?? stockRes.data
      setItems(data)
    } catch { if (!silent) toast.error('Failed to load stock') }
    finally { if (!silent) setLoading(false) }
  }

  const load = async () => {
    if (bulkInProgress.current) return
    try {
      const wRes = await inventoryApi.warehouses()
      const wList: Warehouse[] = wRes.data.results ?? wRes.data
      setWarehouses(wList)
    } catch { toast.error('Failed to load warehouses') }
    await loadStock(warehouseFilter)
    // Fetch low stock count independently so a failure doesn't break the main load
    try {
      const lowRes = await inventoryApi.lowStock()
      const lowData = lowRes.data
      setLowStockTotal(Array.isArray(lowData) ? lowData.length : (lowData.count ?? 0))
    } catch { /* fall back to client-side count */ }
  }

  const handleWarehouseChange = async (whId: string) => {
    setWarehouseFilter(whId)
    await loadStock(whId)
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
    const defaultWarehouse = warehouses.find((w) => w.is_default)?.id ?? warehouses[0]?.id ?? ''
    const warehouseId = s.warehouse || defaultWarehouse
    setAdjustRowLabel(`${s.product_name} @ ${s.warehouse_name === '—' ? (warehouses.find((w) => w.id === warehouseId)?.name ?? 'Default') : s.warehouse_name}`)
    setAdjustForm({ product_id: s.product, warehouse_id: warehouseId, quantity: '', reason: '' })
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

  const toggleSelectItem = (item: StockItem) =>
    setSelectedItems((prev) =>
      prev.some((s) => s.id === item.id)
        ? prev.filter((s) => s.id !== item.id)
        : [...prev, item]
    )

  const toggleSelectAll = (list: StockItem[]) =>
    setSelectedItems(selectedItems.length === list.length ? [] : [...list])

  const handleBulkAddToWarehouse = async () => {
    if (!bulkWarehouse) { toast.error('Select a destination warehouse'); return }
    const qty = bulkQty.trim() ? parseFloat(bulkQty) : 0
    if (bulkQty.trim() && isNaN(qty)) { toast.error('Enter a valid quantity'); return }

    // Capture before clearing so the loop still has access
    const itemsToProcess = [...selectedItems]
    const targetWarehouse = bulkWarehouse

    // Clear UI immediately — prevents glitch from bar/checkboxes re-rendering during async ops
    setSelectedItems([])
    setBulkWarehouse('')
    setBulkQty('')
    setBulkAdding(true)
    bulkInProgress.current = true  // block useDataRefresh from re-running load() per call

    // Fire all calls simultaneously instead of sequentially
    const results = await Promise.allSettled(
      itemsToProcess.map((item) =>
        inventoryApi.adjustStock({
          product_id: item.product,
          warehouse_id: targetWarehouse,
          quantity: qty,
          reason: qty === 0 ? 'Registered to warehouse' : 'Bulk stock entry',
        })
      )
    )
    bulkInProgress.current = false

    const done = results.filter((r) => r.status === 'fulfilled').length
    const failed = results.filter((r) => r.status === 'rejected').length
    const msg = failed
      ? `Done: ${done} product${done !== 1 ? 's' : ''}, ${failed} failed`
      : `${done} product${done !== 1 ? 's' : ''} added to warehouse`
    toast.success(msg, { duration: 5000 })
    setBulkAdding(false)
    // Silent refresh — update table data without flashing the loading skeleton
    await loadStock(warehouseFilter, true)
  }

  // lowStockTotal from the dedicated endpoint (includes products with no stock movements)
  const lowCount = lowStockTotal || items.filter((i) => i.stock_level === 'low' || i.is_low_stock).length
  const mediumCount = items.filter((i) => i.stock_level === 'medium').length

  const displayed = items
    .filter((i) => {
      if (filter === 'low') return i.stock_level === 'low' || i.is_low_stock
      if (filter === 'medium') return i.stock_level === 'medium'
      return true
    })
    .filter((i) => {
      if (!search.trim()) return true
      const q = search.toLowerCase()
      return (
        i.product_name?.toLowerCase().includes(q) ||
        i.warehouse_name?.toLowerCase().includes(q) ||
        i.product_sku?.toLowerCase().includes(q)
      )
    })
    .sort((a, b) => {
      switch (sortBy) {
        case 'name':    return (a.product_name ?? '').localeCompare(b.product_name ?? '')
        case '-name':   return (b.product_name ?? '').localeCompare(a.product_name ?? '')
        case 'qty':     return parseFloat(a.quantity_on_hand ?? '0') - parseFloat(b.quantity_on_hand ?? '0')
        case '-qty':    return parseFloat(b.quantity_on_hand ?? '0') - parseFloat(a.quantity_on_hand ?? '0')
        case 'level':   return (a.stock_level ?? 'ok').localeCompare(b.stock_level ?? 'ok')
        default:        return 0
      }
    })
  const { page, setPage, pageSize, setPageSize, totalPages, paged: pagedStock, total: stockTotal } = usePagination(displayed)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Stock Levels</h1>
          <p className="text-slate-400 text-sm">{stockTotal} product{stockTotal !== 1 ? 's' : ''}{warehouseFilter !== 'all' ? ` in ${warehouses.find(w => w.id === warehouseFilter)?.name ?? 'warehouse'}` : ' across all warehouses'}</p>
        </div>
        <div className="flex items-center gap-2 ml-auto flex-wrap">
          <button onClick={() => { bypassNextGets(); load() }} className="btn-ghost p-2.5" title="Refresh"><RefreshCw size={16} /></button>
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

      {/* Search + filter + sort bar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            className="input pl-9"
            placeholder="Search by product name or SKU…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select
          className="input py-2 pr-8 text-sm"
          value={warehouseFilter}
          onChange={(e) => handleWarehouseChange(e.target.value)}
        >
          <option value="all">All Warehouses</option>
          {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}{w.is_default ? ' (default)' : ''}</option>)}
        </select>
        <SortSelect
          value={sortBy}
          onChange={setSortBy}
          options={[
            { label: 'Name A→Z', value: 'name' },
            { label: 'Name Z→A', value: '-name' },
            { label: 'Qty ↑', value: 'qty' },
            { label: 'Qty ↓', value: '-qty' },
            { label: 'Stock level', value: 'level' },
          ]}
        />
        <div className="flex items-center gap-2">
          <button onClick={() => setFilter('all')} className={filter === 'all' ? 'btn-primary py-2 px-4' : 'btn-secondary py-2 px-4'}>All</button>
          <button onClick={() => setFilter('medium')} className={filter === 'medium' ? 'bg-amber-500/20 border border-amber-500/50 text-amber-300 py-2 px-4 rounded-xl text-sm font-medium' : 'btn-secondary py-2 px-4'}>
            Medium {mediumCount > 0 && `(${mediumCount})`}
          </button>
          <button onClick={() => setFilter('low')} className={filter === 'low' ? 'btn-danger py-2 px-4' : 'btn-secondary py-2 px-4'}>
            <AlertTriangle size={14} /> Low {lowCount > 0 && `(${lowCount})`}
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

      {selectedItems.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 bg-brand-500/10 border border-brand-500/30 rounded-xl px-4 py-3">
          <CheckSquare size={16} className="text-brand-400 shrink-0" />
          <span className="text-sm text-brand-300 font-medium">{selectedItems.length} item{selectedItems.length !== 1 ? 's' : ''} selected</span>
          <div className="flex flex-wrap items-center gap-2 ml-auto">
            <select
              className="input py-1.5 text-sm"
              value={bulkWarehouse}
              onChange={(e) => setBulkWarehouse(e.target.value)}
            >
              <option value="">Select warehouse…</option>
              {warehouses.map((w) => (
                <option key={w.id} value={w.id}>{w.name}{w.is_default ? ' (default)' : ''}</option>
              ))}
            </select>
            <input
              type="number"
              className="input py-1.5 text-sm w-32"
              placeholder="Qty (optional)"
              value={bulkQty}
              onChange={(e) => setBulkQty(e.target.value)}
            />
            <button
              onClick={handleBulkAddToWarehouse}
              disabled={bulkAdding}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-emerald-400 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 rounded-lg transition-colors disabled:opacity-50"
            >
              {bulkAdding ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
              Add to Warehouse
            </button>
            <button onClick={() => setSelectedItems([])} className="btn-ghost px-3 py-1.5 text-xs text-slate-400">Clear</button>
          </div>
        </div>
      )}

      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                <th className="pl-5 pr-2 py-3.5 w-8">
                  <input
                    type="checkbox"
                    className="accent-orange-500 w-4 h-4 cursor-pointer"
                    checked={pagedStock.length > 0 && pagedStock.every((s) => selectedItems.some((x) => x.id === s.id))}
                    onChange={() => toggleSelectAll(pagedStock)}
                  />
                </th>
                {['Product', 'SKU', 'Warehouse', 'On Hand', 'Incoming', 'ETA', 'Available', 'Status', ''].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 9 }).map((_, j) => (
                      <td key={j} className="px-5 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-20" /></td>
                    ))}
                  </tr>
                ))
              ) : stockTotal === 0 ? (
                <tr><td colSpan={9} className="px-5 py-12 text-center">
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
                pagedStock.map((s) => (
                  <tr key={s.id ?? `phantom-${s.product}`} className={`table-row ${selectedItems.some((x) => x.id === s.id) ? 'bg-brand-500/5' : ''}`}>
                    <td className="pl-5 pr-2 py-3.5 w-8">
                      <input
                        type="checkbox"
                        className="accent-orange-500 w-4 h-4 cursor-pointer"
                        checked={selectedItems.some((x) => x.id === s.id)}
                        onChange={() => toggleSelectItem(s)}
                      />
                    </td>
                    <td className="px-5 py-3.5 font-medium text-white">{s.product_name}</td>
                    <td className="px-5 py-3.5 font-mono text-xs text-brand-400">{s.product_sku}</td>
                    <td className="px-5 py-3.5 text-slate-400">{s.warehouse_name}</td>
                    <td className="px-5 py-3.5 font-semibold text-white">{parseFloat(s.quantity_on_hand).toFixed(0)}</td>
                    <td className="px-5 py-3.5">
                      {s.quantity_incoming > 0
                        ? <span className="text-blue-400 font-medium">+{s.quantity_incoming}</span>
                        : <span className="text-slate-600">—</span>}
                    </td>
                    <td className="px-5 py-3.5 text-slate-400 text-xs">
                      {s.incoming_eta
                        ? new Date(s.incoming_eta + 'T00:00:00').toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
                        : <span className="text-slate-600">—</span>}
                    </td>
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
                        {s.id && (
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
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <Pagination page={page} totalPages={totalPages} pageSize={pageSize} total={stockTotal}
          onPage={setPage} onPageSize={setPageSize} />
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
                      <AmountInput className="input py-2 text-sm" placeholder="0.00"
                        value={newProduct.cost_price}
                        onChange={(v) => setNewProduct((p) => ({ ...p, cost_price: v }))} />
                    </div>
                    <div>
                      <label className="text-xs text-slate-400 block mb-1">Selling Price</label>
                      <AmountInput className="input py-2 text-sm" placeholder="0.00"
                        value={newProduct.selling_price}
                        onChange={(v) => setNewProduct((p) => ({ ...p, selling_price: v }))} />
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
