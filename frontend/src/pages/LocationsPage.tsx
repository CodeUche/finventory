import { useEffect, useState, useCallback } from 'react'
import { MapPin, Plus, Pencil, Trash2, Phone, Building2, CheckCircle, XCircle, BarChart3, TrendingUp, ChevronDown, ChevronUp, Loader2 } from 'lucide-react'
import { locationApi } from '@/services/api'
import { formatCurrency } from '@/lib/utils'
import toast from 'react-hot-toast'

interface Location {
  id: string
  name: string
  address: string
  phone: string
  manager: string | null
  manager_name: string | null
  is_active: boolean
  created_at: string
}

const EMPTY_FORM = { name: '', address: '', phone: '', is_active: true }

interface SalesRow {
  location_id: string | null
  location_name: string
  total_revenue: string
  invoice_count: number
  top_products: { product_name: string; units_sold: string; revenue: string }[]
}

export default function LocationsPage() {
  const [locations, setLocations] = useState<Location[]>([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editing, setEditing] = useState<Location | null>(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)

  // Sales analytics
  const [salesPeriod, setSalesPeriod] = useState('month')
  const [salesRows, setSalesRows] = useState<SalesRow[]>([])
  const [loadingSales, setLoadingSales] = useState(false)
  const [expandedSales, setExpandedSales] = useState<string | null>(null)

  const loadSales = useCallback(async (period: string) => {
    setLoadingSales(true)
    try {
      const { data } = await locationApi.salesAnalytics(period)
      setSalesRows(data.results ?? [])
    } catch {
      toast.error('Failed to load sales data')
    } finally {
      setLoadingSales(false)
    }
  }, [])

  useEffect(() => { loadSales(salesPeriod) }, [salesPeriod, loadSales])

  const load = () => {
    setLoading(true)
    locationApi.list().then(({ data }) => {
      setLocations(data.results ?? data)
    }).catch(() => toast.error('Failed to load locations')).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const openCreate = () => {
    setEditing(null)
    setForm(EMPTY_FORM)
    setShowModal(true)
  }

  const openEdit = (loc: Location) => {
    setEditing(loc)
    setForm({ name: loc.name, address: loc.address, phone: loc.phone, is_active: loc.is_active })
    setShowModal(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) { toast.error('Location name is required'); return }
    setSaving(true)
    try {
      if (editing) {
        await locationApi.update(editing.id, form)
        toast.success('Location updated')
      } else {
        await locationApi.create(form)
        toast.success('Location created')
      }
      setShowModal(false)
      load()
    } catch (err: any) {
      const msg = err?.response?.data?.name?.[0] ?? err?.response?.data?.error ?? 'Failed to save'
      toast.error(typeof msg === 'string' ? msg : 'Failed to save location')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string) => {
    setDeleting(id)
    try {
      await locationApi.delete(id)
      toast.success('Location deleted')
      load()
    } catch {
      toast.error('Failed to delete location')
    } finally {
      setDeleting(null)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <MapPin size={20} className="text-brand-400" />
            Sales Locations
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Branches and stores where sales are recorded. Separate from warehouses (storage only).
          </p>
        </div>
        <button onClick={openCreate} className="btn-primary flex items-center gap-2">
          <Plus size={16} /> Add Location
        </button>
      </div>

      {/* List */}
      {loading ? (
        <div className="text-slate-400 text-sm py-8 text-center">Loading…</div>
      ) : locations.length === 0 ? (
        <div className="card text-center py-12">
          <MapPin size={40} className="mx-auto text-slate-600 mb-3" />
          <p className="text-slate-400 font-medium">No locations yet</p>
          <p className="text-slate-500 text-sm mt-1">Add your first sales location to track where transactions happen.</p>
          <button onClick={openCreate} className="btn-primary mt-4 mx-auto flex items-center gap-2">
            <Plus size={16} /> Add Location
          </button>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {locations.map((loc) => (
            <div key={loc.id} className="card flex flex-col gap-3">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2 min-w-0">
                  <div className="w-9 h-9 rounded-xl bg-brand-500/15 flex items-center justify-center shrink-0">
                    <MapPin size={16} className="text-brand-400" />
                  </div>
                  <div className="min-w-0">
                    <p className="font-semibold text-white truncate">{loc.name}</p>
                    {loc.is_active ? (
                      <span className="badge-green text-[10px] flex items-center gap-1 w-fit">
                        <CheckCircle size={10} /> Active
                      </span>
                    ) : (
                      <span className="badge-red text-[10px] flex items-center gap-1 w-fit">
                        <XCircle size={10} /> Inactive
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex gap-1 shrink-0">
                  <button onClick={() => openEdit(loc)} className="btn-ghost p-1.5" title="Edit">
                    <Pencil size={14} />
                  </button>
                  <button
                    onClick={() => handleDelete(loc.id)}
                    disabled={deleting === loc.id}
                    className="btn-ghost p-1.5 text-red-400 hover:text-red-300"
                    title="Delete"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>

              {loc.address && (
                <div className="flex items-start gap-2 text-sm text-slate-400">
                  <Building2 size={13} className="mt-0.5 shrink-0" />
                  <span>{loc.address}</span>
                </div>
              )}
              {loc.phone && (
                <div className="flex items-center gap-2 text-sm text-slate-400">
                  <Phone size={13} className="shrink-0" />
                  <span>{loc.phone}</span>
                </div>
              )}
              {loc.manager_name && (
                <p className="text-xs text-slate-500">Manager: {loc.manager_name}</p>
              )}
            </div>
          ))}
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
        ) : salesRows.length === 0 ? (
          <div className="py-6 text-center text-slate-500 text-sm">No sales recorded for this period.</div>
        ) : (
          <div className="space-y-2">
            {salesRows.map((row) => {
              const key = row.location_id ?? 'none'
              const isOpen = expandedSales === key
              return (
                <div key={key} className="rounded-xl border border-surface-700 overflow-hidden">
                  <button
                    className="w-full flex items-center gap-3 px-4 py-3 hover:bg-surface-700/30 transition-colors text-left"
                    onClick={() => setExpandedSales(isOpen ? null : key)}
                  >
                    <div className="w-8 h-8 rounded-lg bg-brand-500/10 flex items-center justify-center shrink-0">
                      <MapPin size={14} className="text-brand-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-white text-sm">{row.location_name}</p>
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

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="bg-surface-800 rounded-2xl border border-surface-700 w-full max-w-md p-6 space-y-4">
            <h2 className="text-lg font-bold text-white">
              {editing ? 'Edit Location' : 'New Location'}
            </h2>

            <div className="space-y-3">
              <div>
                <label className="label">Name *</label>
                <input
                  className="input"
                  placeholder="e.g. Victoria Island Branch"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>
              <div>
                <label className="label">Address</label>
                <textarea
                  className="input resize-none h-20"
                  placeholder="Full address…"
                  value={form.address}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
                />
              </div>
              <div>
                <label className="label">Phone</label>
                <input
                  className="input"
                  placeholder="+234 800 000 0000"
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                  className="w-4 h-4 rounded accent-brand-500"
                />
                <span className="text-sm text-slate-300">Active</span>
              </label>
            </div>

            <div className="flex gap-3 pt-2">
              <button onClick={() => setShowModal(false)} className="btn-ghost flex-1">Cancel</button>
              <button onClick={handleSave} disabled={saving} className="btn-primary flex-1">
                {saving ? 'Saving…' : editing ? 'Save Changes' : 'Create Location'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
