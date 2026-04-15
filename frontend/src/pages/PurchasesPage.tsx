import { useEffect, useRef, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { useSearchParams } from 'react-router-dom'
import { Plus, Search, Truck, X, Loader2, UploadCloud, FileText, Edit2, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { purchaseApi, supplierApi, inventoryApi } from '@/services/api'
import { formatCurrency, formatDate, formatAmountInput, stripCommas } from '@/lib/utils'
import type { Product, PurchaseOrder } from '@/types'
import DateInput from '@/components/DateInput'
import YearFilter, { yearToDateParams } from '@/components/YearFilter'
import ExportButton from '@/components/ExportButton'
import { FieldTooltip } from '@/components/FieldTooltip'

interface Supplier { id: string; name: string }
interface Warehouse { id: string; name: string }
interface POItem { product_id: string; quantity: string; unit_cost: string }

const BLANK_ITEM: POItem = { product_id: '', quantity: '', unit_cost: '' }

const STATUS_COLORS: Record<string, string> = {
  draft: 'badge-slate',
  sent: 'badge-blue',
  partially_received: 'badge-yellow',
  received: 'badge-green',
  closed: 'badge-slate',
  canceled: 'badge-red',
}

const today = new Date().toISOString().split('T')[0]

function inferMime(url: string): string {
  const ext = url.split('?')[0].split('.').pop()?.toLowerCase() ?? ''
  const map: Record<string, string> = {
    jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png',
    gif: 'image/gif', webp: 'image/webp', pdf: 'application/pdf',
  }
  return map[ext] ?? 'application/octet-stream'
}

const DELIVERY_TYPES = [
  { value: 'self_collection', label: 'Self Collection' },
  { value: 'haulage', label: 'Haulage / Courier' },
  { value: 'other', label: 'Other / Custom' },
]

const BLANK = {
  supplier: '',
  warehouse: '',
  order_date: today,
  expected_date: '',
  delivery_type: 'self_collection',
  delivery_notes: '',
  notes: '',
}

export default function PurchasesPage() {
  const [searchParams] = useSearchParams()
  const [orders, setOrders] = useState<PurchaseOrder[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [archiveYear, setArchiveYear] = useState<number | null>(null)

  const [showModal, setShowModal] = useState(false)
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [form, setForm] = useState({ ...BLANK })
  const [items, setItems] = useState<POItem[]>([])
  const [receiptFile, setReceiptFile] = useState<File | null>(null)
  const [saving, setSaving] = useState(false)
  const [dragging, setDragging] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  // Receipt viewer
  const [receiptViewUrl, setReceiptViewUrl] = useState<string | null>(null)
  const [receiptMime, setReceiptMime] = useState<string>('')

  // Delete PO
  const [deletingId, setDeletingId] = useState<string | null>(null)

  // Edit PO
  const [editOrder, setEditOrder] = useState<PurchaseOrder | null>(null)
  const [editForm, setEditForm] = useState({ status: '', expected_date: '', notes: '' })
  const [editReceiptFile, setEditReceiptFile] = useState<File | null>(null)
  const [editSaving, setEditSaving] = useState(false)
  const [editDragging, setEditDragging] = useState(false)
  const editFileRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, unknown> = { ...yearToDateParams(archiveYear) }
      if (search) params.search = search
      if (statusFilter) params.status = statusFilter
      const { data } = await purchaseApi.list(params)
      setOrders(data.results ?? data)
    } catch {
      toast.error('Failed to load purchase orders')
    } finally {
      setLoading(false)
    }
  }

  const loadSelectData = async () => {
    try {
      const [supRes, whRes, pRes] = await Promise.all([
        supplierApi.list(),
        inventoryApi.warehouses(),
        inventoryApi.products({ page_size: 500, is_active: true }),
      ])
      setSuppliers(supRes.data.results ?? supRes.data)
      setWarehouses(whRes.data.results ?? whRes.data)
      setProducts(pRes.data.results ?? pRes.data)
    } catch { /* ignore */ }
  }

  useEffect(() => { load() }, [search, statusFilter, archiveYear])
  useDataRefresh(load)

  // Auto-open create modal when navigated from low-stock banner
  useEffect(() => {
    if (searchParams.get('create') === '1') {
      openModal()
    }
  }, [])

  const openModal = () => {
    setForm({ ...BLANK })
    setItems([])
    setReceiptFile(null)
    setShowModal(true)
    if (suppliers.length === 0) loadSelectData()
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) setReceiptFile(file)
  }

  const addItem = () => setItems((prev) => [...prev, { ...BLANK_ITEM }])
  const removeItem = (i: number) => setItems((prev) => prev.filter((_, idx) => idx !== i))
  const updateItem = (i: number, field: keyof POItem, value: string) =>
    setItems((prev) => prev.map((item, idx) => {
      if (idx !== i) return item
      const updated = { ...item, [field]: value }
      if (field === 'product_id' && value) {
        const product = products.find((p) => p.id === value)
        if (product) updated.unit_cost = formatAmountInput(String(product.cost_price))
      }
      return updated
    }))
  const poSubtotal = items.reduce((sum, item) => {
    return sum + (parseFloat(item.quantity) || 0) * (parseFloat(stripCommas(item.unit_cost)) || 0)
  }, 0)

  const handleCreate = async () => {
    if (!form.warehouse) { toast.error('Select a warehouse'); return }
    setSaving(true)
    try {
      const validItems = items
        .filter((i) => i.product_id && parseFloat(i.quantity) > 0 && parseFloat(stripCommas(i.unit_cost)) > 0)
        .map((i) => ({
          product: i.product_id,
          quantity_ordered: parseFloat(i.quantity),
          unit_cost: parseFloat(stripCommas(i.unit_cost)),
        }))
      const payload: Record<string, unknown> = {
        supplier: form.supplier || null,
        warehouse: form.warehouse,
        order_date: form.order_date,
        delivery_type: form.delivery_type,
        delivery_notes: form.delivery_notes,
        notes: form.notes,
        items: validItems,
      }
      if (form.expected_date) payload.expected_date = form.expected_date
      const { data: created } = await purchaseApi.create(payload)
      if (receiptFile) {
        const fd = new FormData()
        fd.append('receipt', receiptFile)
        await purchaseApi.patch(created.id, fd)
      }
      toast.success('Purchase order created')
      setShowModal(false)
      load()
    } catch (err: any) {
      const msg = err?.response?.data?.error?.message
        || err?.response?.data?.detail
        || 'Failed to create purchase order'
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  const viewReceipt = async (url: string) => {
    try {
      const { fetch: tauriFetch } = await import('@tauri-apps/plugin-http')
      const resp = await tauriFetch(url)
      // Extract MIME type from response headers so the blob is typed correctly
      const ct: string = (resp.headers as any)?.get?.('content-type')
        ?? (resp.headers as any)?.['content-type']
        ?? ''
      const mimeType = ct.split(';')[0].trim() || inferMime(url)
      const raw = await resp.blob()
      const typed = new Blob([raw], { type: mimeType })
      setReceiptMime(mimeType)
      setReceiptViewUrl(URL.createObjectURL(typed))
    } catch {
      window.open(url, '_blank')
    }
  }

  const closeReceiptViewer = () => {
    if (receiptViewUrl) URL.revokeObjectURL(receiptViewUrl)
    setReceiptViewUrl(null)
    setReceiptMime('')
  }

  const handleDelete = async (id: string) => {
    if (!window.confirm('Delete this purchase order? This cannot be undone.')) return
    setDeletingId(id)
    try {
      await purchaseApi.delete(id)
      toast.success('Purchase order deleted')
      setOrders((prev) => prev.filter((o) => o.id !== id))
    } catch (err: any) {
      const msg = err?.response?.data?.error?.message
        || err?.response?.data?.detail
        || 'Failed to delete purchase order'
      toast.error(msg)
    } finally {
      setDeletingId(null)
    }
  }

  const handleRemoveReceipt = async () => {
    if (!editOrder) return
    if (!window.confirm('Remove the attached receipt?')) return
    try {
      await purchaseApi.removeReceipt(editOrder.id)
      setEditOrder({ ...editOrder, receipt: null })
      toast.success('Receipt removed')
    } catch {
      toast.error('Failed to remove receipt')
    }
  }

  const openEditOrder = (order: PurchaseOrder) => {
    setEditOrder(order)
    setEditForm({
      status: order.status,
      expected_date: order.expected_date ?? '',
      notes: order.notes ?? '',
    })
    setEditReceiptFile(null)
  }

  const handleEditSave = async () => {
    if (!editOrder) return
    setEditSaving(true)
    try {
      const payload: Record<string, unknown> = {
        status: editForm.status,
        notes: editForm.notes,
      }
      if (editForm.expected_date) payload.expected_date = editForm.expected_date
      await purchaseApi.patch(editOrder.id, payload)
      if (editReceiptFile) {
        const fd = new FormData()
        fd.append('receipt', editReceiptFile)
        await purchaseApi.patch(editOrder.id, fd)
      }
      toast.success('Purchase order updated')
      setEditOrder(null)
      load()
    } catch (err: any) {
      const msg = err?.response?.data?.error?.message
        || err?.response?.data?.detail
        || 'Failed to update purchase order'
      toast.error(msg)
    } finally {
      setEditSaving(false)
    }
  }

  const upd = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Purchases</h1>
          <p className="text-slate-400 text-sm">{orders.length} purchase orders</p>
        </div>
        <button className="btn-primary sm:ml-auto" onClick={openModal}>
          <Plus size={16} /> New PO
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input className="input pl-9" placeholder="Search PO number…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <select className="input max-w-xs" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          {['draft', 'sent', 'partially_received', 'received', 'closed', 'canceled'].map((s) => (
            <option key={s} value={s}>{s.replace('_', ' ')}</option>
          ))}
        </select>
        <YearFilter selectedYear={archiveYear} onChange={setArchiveYear} />
        <ExportButton endpoint="/purchases/" filename="purchase_orders" params={yearToDateParams(archiveYear)} />
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['PO Number', 'Supplier', 'Location', 'Order Date', 'Expected', 'Total', 'Status', 'Actions'].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 8 }).map((_, j) => (
                      <td key={j} className="px-5 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-20" /></td>
                    ))}
                  </tr>
                ))
              ) : orders.length === 0 ? (
                <tr><td colSpan={8} className="px-5 py-12 text-center">
                  <Truck size={32} className="mx-auto mb-2 text-slate-600" />
                  <p className="text-slate-500">No purchase orders yet</p>
                </td></tr>
              ) : (
                orders.map((o) => (
                  <tr key={o.id} className="table-row">
                    <td className="px-5 py-3.5 font-mono text-brand-400 text-xs font-medium">{o.po_number}</td>
                    <td className="px-5 py-3.5 text-white">{o.supplier_name}</td>
                    <td className="px-5 py-3.5 text-slate-300">{o.warehouse_name ?? '—'}</td>
                    <td className="px-5 py-3.5 text-slate-400">{formatDate(o.order_date)}</td>
                    <td className="px-5 py-3.5 text-slate-400">{o.expected_date ? formatDate(o.expected_date) : '—'}</td>
                    <td className="px-5 py-3.5 font-semibold text-white">{formatCurrency(o.total_amount)}</td>
                    <td className="px-5 py-3.5">
                      <span className={STATUS_COLORS[o.status] ?? 'badge-slate'}>{o.status.replace('_', ' ')}</span>
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => openEditOrder(o)}
                          className="text-slate-400 hover:text-white transition-colors"
                          title="Edit PO"
                        >
                          <Edit2 size={14} />
                        </button>
                        <button
                          onClick={() => handleDelete(o.id)}
                          disabled={deletingId === o.id}
                          className="text-slate-500 hover:text-red-400 transition-colors disabled:opacity-40"
                          title="Delete PO"
                        >
                          {deletingId === o.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                        </button>
                        {o.receipt ? (
                          <button
                            onClick={() => viewReceipt(o.receipt!)}
                            className="flex items-center gap-1 text-xs text-brand-400 hover:text-brand-300 font-medium transition-colors"
                            title="View receipt"
                          >
                            <FileText size={13} /> View
                          </button>
                        ) : (
                          <span className="text-slate-600 text-xs">—</span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Receipt viewer modal */}
      {receiptViewUrl && (
        <div className="fixed inset-0 z-50 flex flex-col bg-black/95">
          <div className="flex items-center justify-between px-6 py-3 border-b border-surface-700 bg-surface-800 shrink-0">
            <h2 className="font-semibold text-white text-sm">Receipt / Invoice</h2>
            <button onClick={closeReceiptViewer} className="btn-ghost p-1.5"><X size={18} /></button>
          </div>
          {receiptMime.startsWith('image/') ? (
            <div className="flex-1 flex items-center justify-center overflow-auto p-4">
              <img
                src={receiptViewUrl}
                alt="Receipt"
                className="max-w-full max-h-full object-contain rounded"
              />
            </div>
          ) : (
            <iframe
              src={receiptViewUrl}
              className="flex-1 w-full border-0"
              title="Receipt"
            />
          )}
        </div>
      )}

      {/* Edit PO modal */}
      {editOrder && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-lg shadow-2xl animate-slide-up max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-6 border-b border-surface-700">
              <div>
                <h2 className="font-semibold text-white text-lg">Edit Purchase Order</h2>
                <p className="text-xs text-slate-400 mt-0.5 font-mono">{editOrder.po_number}</p>
              </div>
              <button onClick={() => setEditOrder(null)} className="btn-ghost p-1.5"><X size={18} /></button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="label">Status</label>
                <select
                  className="input"
                  value={editForm.status}
                  onChange={(e) => setEditForm((f) => ({ ...f, status: e.target.value }))}
                >
                  {['draft', 'sent', 'partially_received', 'received', 'closed', 'canceled'].map((s) => (
                    <option key={s} value={s}>{s.replace('_', ' ')}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Expected Delivery <FieldTooltip text="When you expect the goods to arrive. Helps you plan stock levels and production schedules." /></label>
                <DateInput value={editForm.expected_date} onChange={(v) => setEditForm((f) => ({ ...f, expected_date: v }))} />
              </div>
              <div>
                <label className="label">Notes <FieldTooltip text="Any special instructions for this order — e.g. delivery terms, packaging requirements, or contact details." /></label>
                <textarea
                  className="input resize-none" rows={3}
                  value={editForm.notes}
                  onChange={(e) => setEditForm((f) => ({ ...f, notes: e.target.value }))}
                  placeholder="Optional notes…"
                />
              </div>

              {/* Replace receipt */}
              <div>
                <label className="label">
                  {editOrder.receipt ? 'Replace Receipt / Invoice' : 'Attach Receipt / Invoice'}
                </label>
                <div
                  onDragOver={(e) => { e.preventDefault(); setEditDragging(true) }}
                  onDragLeave={() => setEditDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault()
                    setEditDragging(false)
                    const file = e.dataTransfer.files?.[0]
                    if (file) setEditReceiptFile(file)
                  }}
                  onClick={() => editFileRef.current?.click()}
                  className={`border-2 border-dashed rounded-xl p-5 text-center cursor-pointer transition-colors ${
                    editDragging ? 'border-brand-500 bg-brand-500/5' : 'border-surface-600 hover:border-surface-500'
                  }`}
                >
                  {editReceiptFile ? (
                    <div className="flex items-center justify-center gap-2 text-sm text-emerald-400">
                      <FileText size={16} />
                      <span>{editReceiptFile.name}</span>
                      <button
                        className="text-slate-400 hover:text-red-400 ml-2"
                        onClick={(e) => { e.stopPropagation(); setEditReceiptFile(null) }}
                      >
                        <X size={14} />
                      </button>
                    </div>
                  ) : editOrder.receipt ? (
                    <div className="text-slate-400 text-sm">
                      <FileText size={20} className="mx-auto mb-1" />
                      <p>Receipt attached — drop a new file to replace</p>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); handleRemoveReceipt() }}
                        className="mt-2 text-xs text-red-400 hover:text-red-300 flex items-center gap-1 mx-auto"
                      >
                        <Trash2 size={12} /> Remove receipt
                      </button>
                    </div>
                  ) : (
                    <div className="text-slate-500">
                      <UploadCloud size={24} className="mx-auto mb-2" />
                      <p className="text-sm">Drop a file here or click to browse</p>
                      <p className="text-xs mt-1">PDF, PNG, JPG accepted</p>
                    </div>
                  )}
                  <input
                    ref={editFileRef} type="file" accept=".pdf,image/*" className="hidden"
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) setEditReceiptFile(f) }}
                  />
                </div>
              </div>

              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setEditOrder(null)} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button type="button" onClick={handleEditSave} disabled={editSaving} className="btn-primary flex-1 justify-center">
                  {editSaving ? <Loader2 size={16} className="animate-spin" /> : 'Save Changes'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Create PO modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-2xl shadow-2xl animate-slide-up max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-6 border-b border-surface-700">
              <h2 className="font-semibold text-white text-lg">New Purchase Order</h2>
              <button onClick={() => setShowModal(false)} className="btn-ghost p-1.5"><X size={18} /></button>
            </div>

            <div className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2">
                  <label className="label">Supplier <FieldTooltip text="The company you are buying from. Must be added to your suppliers list first." /></label>
                  <select className="input" value={form.supplier} onChange={upd('supplier')}>
                    <option value="">Walk-in / No supplier</option>
                    {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </div>
                <div className="col-span-2">
                  <label className="label">Location * <FieldTooltip text="Where the ordered goods will be delivered and stored. Important for tracking stock at the right location." /></label>
                  <select className="input" value={form.warehouse} onChange={upd('warehouse')}>
                    <option value="">— Select location —</option>
                    {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label">Order Date <FieldTooltip text="The date you placed this purchase order. Used to track how long orders take to arrive." /></label>
                  <DateInput value={form.order_date} onChange={(v) => setForm((f) => ({ ...f, order_date: v }))} />
                </div>
                <div>
                  <label className="label">Expected Delivery <FieldTooltip text="When you expect the goods to arrive. Helps you plan stock levels and production schedules." /></label>
                  <DateInput value={form.expected_date} onChange={(v) => setForm((f) => ({ ...f, expected_date: v }))} />
                </div>
                <div>
                  <label className="label">Delivery Type</label>
                  <select className="input" value={form.delivery_type} onChange={upd('delivery_type')}>
                    {DELIVERY_TYPES.map((d) => (
                      <option key={d.value} value={d.value}>{d.label}</option>
                    ))}
                  </select>
                </div>
                {(form.delivery_type === 'haulage' || form.delivery_type === 'other') && (
                  <div>
                    <label className="label">Delivery Details</label>
                    <input className="input" placeholder="e.g. courier name, tracking, address…"
                      value={form.delivery_notes}
                      onChange={(e) => setForm((f) => ({ ...f, delivery_notes: e.target.value }))} />
                  </div>
                )}
                <div className="col-span-2">
                  <label className="label">Notes <FieldTooltip text="Any special instructions for this order — e.g. delivery terms, packaging requirements, or contact details." /></label>
                  <textarea className="input resize-none" rows={2} value={form.notes}
                    onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} placeholder="Optional notes…" />
                </div>
              </div>

              {/* Line items */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="label mb-0">Line Items</label>
                  <button type="button" onClick={addItem}
                    className="flex items-center gap-1 text-xs text-brand-400 hover:text-brand-300 font-medium transition-colors">
                    <Plus size={13} /> Add Item
                  </button>
                </div>
                {items.length === 0 ? (
                  <p className="text-xs text-slate-500 italic py-2">No items yet — click "Add Item" to begin.</p>
                ) : (
                  <div className="space-y-2">
                    <div className="grid grid-cols-[1fr_72px_96px_76px_20px] gap-2 px-1 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      <span>Product</span><span>Qty</span><span>Unit Cost</span><span>Total</span><span />
                    </div>
                    {items.map((item, idx) => {
                      return (
                        <div key={idx} className="grid grid-cols-[1fr_72px_96px_76px_20px] gap-2 items-center">
                          <select
                            className="input text-xs py-1.5"
                            value={item.product_id}
                            onChange={(e) => updateItem(idx, 'product_id', e.target.value)}
                          >
                            <option value="">— product —</option>
                            {products.map((p) => (
                              <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>
                            ))}
                          </select>
                          <input
                            type="number" min="0" step="0.01" placeholder="0"
                            className="input text-xs py-1.5"
                            value={item.quantity}
                            onChange={(e) => updateItem(idx, 'quantity', e.target.value)}
                          />
                          <input
                            type="text" inputMode="decimal" placeholder="0.00"
                            className="input text-xs py-1.5"
                            value={item.unit_cost}
                            onChange={(e) => updateItem(idx, 'unit_cost', formatAmountInput(e.target.value))}
                          />
                          <span className="text-xs text-slate-300 font-mono truncate">
                            {(parseFloat(item.quantity) || 0) * (parseFloat(stripCommas(item.unit_cost)) || 0) > 0
                              ? formatCurrency(String((parseFloat(item.quantity) || 0) * (parseFloat(stripCommas(item.unit_cost)) || 0)))
                              : '—'}
                          </span>
                          <button type="button" onClick={() => removeItem(idx)}
                            className="text-slate-600 hover:text-red-400 transition-colors">
                            <X size={13} />
                          </button>
                        </div>
                      )
                    })}
                    <div className="flex justify-end pt-2 border-t border-surface-700">
                      <div className="text-right">
                        <p className="text-xs text-slate-400">Subtotal</p>
                        <p className="text-sm font-bold text-white">{formatCurrency(String(poSubtotal))}</p>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Receipt upload */}
              <div>
                <label className="label">Receipt / Invoice (optional)</label>
                <div
                  onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={handleDrop}
                  onClick={() => fileRef.current?.click()}
                  className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors ${
                    dragging ? 'border-brand-500 bg-brand-500/5' : 'border-surface-600 hover:border-surface-500'
                  }`}
                >
                  {receiptFile ? (
                    <div className="flex items-center justify-center gap-2 text-sm text-emerald-400">
                      <FileText size={16} />
                      <span>{receiptFile.name}</span>
                      <button className="text-slate-400 hover:text-red-400 ml-2" onClick={(e) => { e.stopPropagation(); setReceiptFile(null) }}>
                        <X size={14} />
                      </button>
                    </div>
                  ) : (
                    <div className="text-slate-500">
                      <UploadCloud size={24} className="mx-auto mb-2" />
                      <p className="text-sm">Drop a file here or click to browse</p>
                      <p className="text-xs mt-1">PDF, PNG, JPG accepted</p>
                    </div>
                  )}
                  <input ref={fileRef} type="file" accept=".pdf,image/*" className="hidden"
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) setReceiptFile(f) }} />
                </div>
              </div>

              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowModal(false)} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button type="button" onClick={handleCreate} disabled={saving} className="btn-primary flex-1 justify-center">
                  {saving ? <Loader2 size={16} className="animate-spin" /> : 'Create PO'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
