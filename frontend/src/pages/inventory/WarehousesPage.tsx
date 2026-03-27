import { useEffect, useState, useCallback } from 'react'
import { Edit2, Plus, Trash2, Warehouse, ChevronDown, ChevronUp, Package, Loader2, TrendingUp, BarChart3 } from 'lucide-react'
import toast from 'react-hot-toast'
import { inventoryApi, salesApi } from '@/services/api'
import { formatCurrency } from '@/lib/utils'
import type { Warehouse as WarehouseType, StockItem, WarehouseSalesRow } from '@/types'

interface WarehouseForm {
  name: string
  address: string
  is_default: boolean
}

const EMPTY: WarehouseForm = { name: '', address: '', is_default: false }
const PRESETS = ['Main Store', 'Retail Shop', 'Cold Room / Freezer', 'Bonded Warehouse', 'Transit Bay']

export default function WarehousesPage() {
  const [warehouses, setWarehouses] = useState<WarehouseType[]>([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<WarehouseForm>(EMPTY)
  const [saving, setSaving] = useState(false)

  // Expanded warehouse → stock items
  const [expanded, setExpanded] = useState<string | null>(null)
  const [warehouseStock, setWarehouseStock] = useState<Record<string, StockItem[]>>({})
  const [loadingStock, setLoadingStock] = useState<string | null>(null)

  // Sales analytics
  const [salesPeriod, setSalesPeriod] = useState<string>('month')
  const [warehouseSales, setWarehouseSales] = useState<WarehouseSalesRow[]>([])
  const [loadingSales, setLoadingSales] = useState(false)
  const [expandedSales, setExpandedSales] = useState<string | null>(null)

  const load = async () => {
    try {
      const { data } = await inventoryApi.warehouses()
      setWarehouses(data.results ?? data)
    } catch {
      toast.error('Failed to load warehouses')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const loadSales = useCallback(async (period: string) => {
    setLoadingSales(true)
    try {
      const { data } = await salesApi.warehouseSales(period)
      setWarehouseSales(data.results ?? [])
    } catch {
      toast.error('Failed to load sales data')
    } finally {
      setLoadingSales(false)
    }
  }, [])

  useEffect(() => { loadSales(salesPeriod) }, [salesPeriod, loadSales])

  const toggleExpand = useCallback(async (warehouseId: string) => {
    if (expanded === warehouseId) {
      setExpanded(null)
      return
    }
    setExpanded(warehouseId)
    if (warehouseStock[warehouseId]) return // already loaded
    setLoadingStock(warehouseId)
    try {
      const { data } = await inventoryApi.stock({ warehouse: warehouseId, page_size: 200 })
      setWarehouseStock(prev => ({ ...prev, [warehouseId]: data.results ?? data }))
    } catch {
      toast.error('Failed to load warehouse stock')
    } finally {
      setLoadingStock(null)
    }
  }, [expanded, warehouseStock])

  const openCreate = () => {
    setEditingId(null)
    setForm(EMPTY)
    setShowModal(true)
  }

  const openEdit = (w: WarehouseType, e: React.MouseEvent) => {
    e.stopPropagation()
    setEditingId(w.id)
    setForm({ name: w.name, address: w.address, is_default: w.is_default })
    setShowModal(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) { toast.error('Location name is required'); return }
    setSaving(true)
    try {
      if (editingId) {
        await inventoryApi.updateWarehouse(editingId, form)
        toast.success('Location updated')
      } else {
        await inventoryApi.createWarehouse(form)
        toast.success('Location created')
      }
      setShowModal(false)
      load()
    } catch {
      toast.error('Failed to save location')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string, name: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(`Delete location "${name}"? This cannot be undone.`)) return
    try {
      await inventoryApi.deleteWarehouse(id)
      toast.success('Location deleted')
      load()
    } catch {
      toast.error('Cannot delete location — it may have stock or orders linked to it')
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Locations</h1>
          <p className="text-slate-400 text-sm mt-0.5">Click a location to view its products</p>
        </div>
        <button onClick={openCreate} className="btn-primary flex items-center gap-2">
          <Plus size={16} /> Add Location
        </button>
      </div>

      {loading ? (
        <div className="card p-8 text-center text-slate-500">
          <Loader2 size={24} className="animate-spin mx-auto" />
        </div>
      ) : warehouses.length === 0 ? (
        <div className="card p-12 text-center">
          <Warehouse size={40} className="mx-auto text-slate-600 mb-3" />
          <p className="text-slate-400 font-medium">No locations yet</p>
          <p className="text-slate-500 text-sm mt-1">Add a location to start tracking stock</p>
          <button onClick={openCreate} className="btn-primary mt-4 inline-flex items-center gap-2">
            <Plus size={15} /> Add First Location
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {warehouses.map((w) => {
            const isExpanded = expanded === w.id
            const stock = warehouseStock[w.id] ?? []
            const isLoadingStock = loadingStock === w.id
            return (
              <div key={w.id} className="card overflow-hidden">
                {/* Warehouse header row — clickable to expand */}
                <button
                  onClick={() => toggleExpand(w.id)}
                  className="w-full flex items-center gap-4 px-5 py-4 text-left hover:bg-surface-700/30 transition-colors"
                >
                  <div className="w-10 h-10 rounded-xl bg-brand-500/10 flex items-center justify-center shrink-0">
                    <Warehouse size={18} className="text-brand-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-semibold text-white">{w.name}</p>
                      {w.is_default && (
                        <span className="text-xs bg-emerald-500/15 text-emerald-400 px-2 py-0.5 rounded-full">Default</span>
                      )}
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5">{w.address || 'No address'}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    {isExpanded && stock.length > 0 && (
                      <span className="text-xs text-slate-500">{stock.length} SKU{stock.length !== 1 ? 's' : ''}</span>
                    )}
                    <button
                      onClick={(e) => openEdit(w, e)}
                      className="p-1.5 text-slate-500 hover:text-white hover:bg-surface-600 rounded-lg transition-colors"
                    >
                      <Edit2 size={13} />
                    </button>
                    <button
                      onClick={(e) => handleDelete(w.id, w.name, e)}
                      className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                    >
                      <Trash2 size={13} />
                    </button>
                    {isExpanded ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
                  </div>
                </button>

                {/* Expandable product list */}
                {isExpanded && (
                  <div className="border-t border-surface-700">
                    {isLoadingStock ? (
                      <div className="py-8 text-center">
                        <Loader2 size={20} className="animate-spin mx-auto text-brand-400" />
                      </div>
                    ) : stock.length === 0 ? (
                      <div className="py-8 text-center">
                        <Package size={28} className="mx-auto mb-2 text-slate-600" />
                        <p className="text-slate-500 text-sm">No products in this location</p>
                      </div>
                    ) : (
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="bg-surface-700/30">
                            {['SKU', 'Product', 'On Hand', 'Available', 'Status'].map(h => (
                              <th key={h} className="px-5 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-surface-700/50">
                          {stock.map(item => (
                            <tr key={item.id} className="hover:bg-surface-700/20 transition-colors">
                              <td className="px-5 py-3 font-mono text-xs text-brand-400">{item.product_sku}</td>
                              <td className="px-5 py-3 text-white font-medium">{item.product_name}</td>
                              <td className="px-5 py-3 text-slate-300 font-mono">{parseFloat(item.quantity_on_hand).toLocaleString()}</td>
                              <td className="px-5 py-3 text-slate-300 font-mono">{parseFloat(item.quantity_available).toLocaleString()}</td>
                              <td className="px-5 py-3">
                                {item.is_low_stock
                                  ? <span className="badge-red text-xs">Low</span>
                                  : <span className="badge-green text-xs">OK</span>
                                }
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Sales Analytics */}
      <div className="card p-5 space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-2">
            <BarChart3 size={18} className="text-brand-400" />
            <h2 className="text-base font-semibold text-white">Sales by Location</h2>
          </div>
          <select
            className="input w-auto text-sm py-1.5"
            value={salesPeriod}
            onChange={(e) => setSalesPeriod(e.target.value)}
          >
            <option value="today">Today</option>
            <option value="week">Last 7 days</option>
            <option value="month">Last 30 days</option>
            <option value="year">Last 12 months</option>
            <option value="all">All time</option>
          </select>
        </div>

        {loadingSales ? (
          <div className="py-6 text-center"><Loader2 size={20} className="animate-spin mx-auto text-brand-400" /></div>
        ) : warehouseSales.length === 0 ? (
          <div className="py-6 text-center text-slate-500 text-sm">No sales recorded for this period.</div>
        ) : (
          <div className="space-y-2">
            {warehouseSales.map((row) => {
              const isOpen = expandedSales === row.warehouse_id
              return (
                <div key={row.warehouse_id} className="rounded-xl border border-surface-700 overflow-hidden">
                  <button
                    className="w-full flex items-center gap-3 px-4 py-3 hover:bg-surface-700/30 transition-colors text-left"
                    onClick={() => setExpandedSales(isOpen ? null : row.warehouse_id)}
                  >
                    <div className="w-8 h-8 rounded-lg bg-brand-500/10 flex items-center justify-center shrink-0">
                      <Warehouse size={14} className="text-brand-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-white text-sm">{row.warehouse_name}</p>
                      <p className="text-xs text-slate-500">{row.invoice_count} invoice{row.invoice_count !== 1 ? 's' : ''}</p>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="font-mono font-bold text-brand-400 text-sm">{formatCurrency(row.total_revenue)}</span>
                      {isOpen ? <ChevronUp size={14} className="text-slate-400" /> : <ChevronDown size={14} className="text-slate-400" />}
                    </div>
                  </button>
                  {isOpen && row.top_products.length > 0 && (
                    <div className="border-t border-surface-700 bg-surface-900/30">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-surface-700/50">
                            <th className="px-4 py-2 text-left text-slate-500 font-medium">Product</th>
                            <th className="px-4 py-2 text-right text-slate-500 font-medium">Units Sold</th>
                            <th className="px-4 py-2 text-right text-slate-500 font-medium">Revenue</th>
                          </tr>
                        </thead>
                        <tbody>
                          {row.top_products.map((p, i) => (
                            <tr key={i} className="border-b border-surface-700/30 last:border-0">
                              <td className="px-4 py-2 text-slate-300 flex items-center gap-1.5">
                                <TrendingUp size={11} className="text-brand-400 shrink-0" />
                                {p.product_name}
                              </td>
                              <td className="px-4 py-2 text-right text-slate-400 font-mono">{parseFloat(p.units_sold).toLocaleString()}</td>
                              <td className="px-4 py-2 text-right font-mono text-white">{formatCurrency(p.revenue)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Create / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-md shadow-2xl">
            <h2 className="text-lg font-bold text-white mb-5">
              {editingId ? 'Edit Location' : 'Add Location'}
            </h2>

            <div className="space-y-4">
              {!editingId && (
                <div>
                  <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Quick Presets</p>
                  <div className="flex flex-wrap gap-2">
                    {PRESETS.map((preset) => (
                      <button
                        key={preset}
                        type="button"
                        onClick={() => setForm({ ...form, name: preset })}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${form.name === preset ? 'bg-brand-500/20 border-brand-500/40 text-brand-300' : 'border-surface-600 text-slate-400 hover:border-slate-500 hover:text-slate-300'}`}
                      >
                        {preset}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div>
                <label className="label">Name *</label>
                <input
                  className="input"
                  placeholder="e.g. Main Store, Lagos Branch"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>
              <div>
                <label className="label">Address</label>
                <input
                  className="input"
                  placeholder="Physical address"
                  value={form.address}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
                />
              </div>
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  className="w-4 h-4 accent-orange-500"
                  checked={form.is_default}
                  onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
                />
                <span className="text-sm text-slate-300">Set as default location</span>
              </label>
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleSave} disabled={saving} className="btn-primary flex-1 disabled:opacity-50">
                {saving ? <Loader2 size={15} className="animate-spin mx-auto" /> : editingId ? 'Save Changes' : 'Add Location'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
