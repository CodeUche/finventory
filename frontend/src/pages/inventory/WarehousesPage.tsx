import { useEffect, useState } from 'react'
import { Edit2, Plus, Trash2, Warehouse } from 'lucide-react'
import toast from 'react-hot-toast'
import { inventoryApi } from '@/services/api'
import type { Warehouse as WarehouseType } from '@/types'

interface WarehouseForm {
  name: string
  address: string
  is_default: boolean
}

const EMPTY: WarehouseForm = { name: '', address: '', is_default: false }

export default function WarehousesPage() {
  const [warehouses, setWarehouses] = useState<WarehouseType[]>([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<WarehouseForm>(EMPTY)
  const [saving, setSaving] = useState(false)

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

  const openCreate = () => {
    setEditingId(null)
    setForm(EMPTY)
    setShowModal(true)
  }

  const openEdit = (w: WarehouseType) => {
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

  const handleDelete = async (id: string, name: string) => {
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
          <p className="text-slate-400 text-sm mt-0.5">Manage storage locations for stock</p>
        </div>
        <button onClick={openCreate} className="btn-primary flex items-center gap-2">
          <Plus size={16} />
          Add Warehouse
        </button>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-slate-500">Loading…</div>
        ) : warehouses.length === 0 ? (
          <div className="p-12 text-center">
            <Warehouse size={40} className="mx-auto text-slate-600 mb-3" />
            <p className="text-slate-400 font-medium">No warehouses yet</p>
            <p className="text-slate-500 text-sm mt-1">Add a warehouse to start tracking stock locations</p>
            <button onClick={openCreate} className="btn-primary mt-4 inline-flex items-center gap-2">
              <Plus size={15} />
              Add First Warehouse
            </button>
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-surface-700">
                <th className="text-left px-5 py-3.5 text-xs font-semibold text-slate-400 uppercase tracking-wider">Name</th>
                <th className="text-left px-5 py-3.5 text-xs font-semibold text-slate-400 uppercase tracking-wider">Address</th>
                <th className="text-left px-5 py-3.5 text-xs font-semibold text-slate-400 uppercase tracking-wider">Default</th>
                <th className="px-5 py-3.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-700">
              {warehouses.map((w) => (
                <tr key={w.id} className="table-row">
                  <td className="px-5 py-3.5">
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-lg bg-brand-500/10 flex items-center justify-center">
                        <Warehouse size={15} className="text-brand-400" />
                      </div>
                      <span className="font-medium text-white">{w.name}</span>
                    </div>
                  </td>
                  <td className="px-5 py-3.5 text-slate-400 text-sm">{w.address || '—'}</td>
                  <td className="px-5 py-3.5">
                    {w.is_default ? (
                      <span className="badge-green text-xs px-2 py-0.5 rounded-full">Default</span>
                    ) : (
                      <span className="text-slate-600 text-xs">—</span>
                    )}
                  </td>
                  <td className="px-5 py-3.5">
                    <div className="flex items-center gap-2 justify-end">
                      <button
                        onClick={() => openEdit(w)}
                        className="p-1.5 text-slate-500 hover:text-white hover:bg-surface-600 rounded-lg transition-colors"
                      >
                        <Edit2 size={14} />
                      </button>
                      <button
                        onClick={() => handleDelete(w.id, w.name)}
                        className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Create / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-600 rounded-2xl p-6 w-full max-w-md shadow-2xl">
            <h2 className="text-lg font-bold text-white mb-5">
              {editingId ? 'Edit Warehouse' : 'Add Warehouse'}
            </h2>

            <div className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
                  Name *
                </label>
                <input
                  className="input"
                  placeholder="e.g. Main Store, Lagos Branch"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-1.5">
                  Address
                </label>
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
              <button onClick={() => setShowModal(false)} className="btn-ghost flex-1">
                Cancel
              </button>
              <button onClick={handleSave} disabled={saving} className="btn-primary flex-1 disabled:opacity-50">
                {saving ? 'Saving…' : editingId ? 'Save Changes' : 'Add Warehouse'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
