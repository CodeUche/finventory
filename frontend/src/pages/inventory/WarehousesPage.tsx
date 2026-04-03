import { useEffect, useState, useCallback } from 'react'
import { Edit2, Plus, Trash2, Warehouse, ChevronDown, ChevronUp, Package, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { inventoryApi } from '@/services/api'
import type { Warehouse as WarehouseType, StockItem } from '@/types'

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
    if (!form.name.trim()) { toast.error('Warehouse name is required'); return }
    setSaving(true)
    try {
      if (editingId) {
        await inventoryApi.updateWarehouse(editingId, form)
        toast.success('Warehouse updated')
      } else {
        await inventoryApi.createWarehouse(form)
        toast.success('Warehouse created')
      }
      setShowModal(false)
      load()
    } catch {
      toast.error('Failed to save warehouse')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string, name: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(`Delete warehouse "${name}"? This cannot be undone.`)) return
    try {
      await inventoryApi.deleteWarehouse(id)
      toast.success('Warehouse deleted')
      load()
    } catch {
      toast.error('Cannot delete warehouse — it may have stock or orders linked to it')
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Warehouses</h1>
          <p className="text-slate-400 text-sm mt-0.5">Click a warehouse to view its products</p>
        </div>
        <button onClick={openCreate} className="btn-primary flex items-center gap-2">
          <Plus size={16} /> Add Warehouse
        </button>
      </div>

      {loading ? (
        <div className="card p-8 text-center text-slate-500">
          <Loader2 size={24} className="animate-spin mx-auto" />
        </div>
      ) : warehouses.length === 0 ? (
        <div className="card p-12 text-center">
          <Warehouse size={40} className="mx-auto text-slate-600 mb-3" />
          <p className="text-slate-400 font-medium">No warehouses yet</p>
          <p className="text-slate-500 text-sm mt-1">Add a warehouse to start tracking stock</p>
          <button onClick={openCreate} className="btn-primary mt-4 inline-flex items-center gap-2">
            <Plus size={15} /> Add First Warehouse
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
                        <p className="text-slate-500 text-sm">No products in this warehouse</p>
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

      {/* Create / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-md shadow-2xl">
            <h2 className="text-lg font-bold text-white mb-5">
              {editingId ? 'Edit Warehouse' : 'Add Warehouse'}
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
                <span className="text-sm text-slate-300">Set as default warehouse</span>
              </label>
            </div>

            <div className="flex gap-3 mt-6">
              <button onClick={() => setShowModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleSave} disabled={saving} className="btn-primary flex-1 disabled:opacity-50">
                {saving ? <Loader2 size={15} className="animate-spin mx-auto" /> : editingId ? 'Save Changes' : 'Add Warehouse'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
