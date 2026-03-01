import { useEffect, useState } from 'react'
import { Layers, Search } from 'lucide-react'
import toast from 'react-hot-toast'
import { inventoryApi } from '@/services/api'
import { formatDate } from '@/lib/utils'

interface BatchItem {
  id: string
  batch_number: string
  product: string
  product_name: string
  product_sku: string
  warehouse: string
  warehouse_name: string
  quantity: string
  manufacture_date: string | null
  expiry_date: string | null
  days_to_expiry: number | null
}

type ExpiryFilter = 'all' | 'expiring' | 'expired' | 'ok'

function getExpiryStatus(batch: BatchItem): { label: string; badge: string; daysLeft: number | null } {
  if (!batch.expiry_date) return { label: 'No expiry', badge: 'badge-slate', daysLeft: null }
  const days = batch.days_to_expiry ?? Math.floor((new Date(batch.expiry_date).getTime() - Date.now()) / 86400000)
  if (days < 0) return { label: 'Expired', badge: 'badge-red', daysLeft: days }
  if (days < 30) return { label: `Expiring (${days}d)`, badge: 'badge-orange', daysLeft: days }
  return { label: 'OK', badge: 'badge-green', daysLeft: days }
}

export default function BatchesPage() {
  const [batches, setBatches] = useState<BatchItem[]>([])
  const [warehouses, setWarehouses] = useState<{ id: string; name: string }[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [warehouseFilter, setWarehouseFilter] = useState('')
  const [expiryFilter, setExpiryFilter] = useState<ExpiryFilter>('all')

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (search) params.search = search
      if (warehouseFilter) params.warehouse = warehouseFilter
      if (expiryFilter !== 'all') params.expiry_status = expiryFilter
      const [bRes, wRes] = await Promise.all([inventoryApi.batches(params), inventoryApi.warehouses()])
      setBatches(bRes.data.results ?? bRes.data)
      setWarehouses(wRes.data.results ?? wRes.data)
    } catch {
      setBatches([])
      toast.error('Failed to load batches')
    }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [search, warehouseFilter, expiryFilter])

  // Summary stats
  const expiring = batches.filter((b) => {
    if (!b.expiry_date) return false
    const days = Math.floor((new Date(b.expiry_date).getTime() - Date.now()) / 86400000)
    return days >= 0 && days < 30
  }).length
  const expired = batches.filter((b) => {
    if (!b.expiry_date) return false
    return new Date(b.expiry_date).getTime() < Date.now()
  }).length
  const adequate = batches.filter((b) => {
    if (!b.expiry_date) return true
    const days = Math.floor((new Date(b.expiry_date).getTime() - Date.now()) / 86400000)
    return days >= 30
  }).length

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Batches & Lots</h1>
        <p className="text-slate-400 text-sm">Track batch expiry dates and lot numbers. Batches are created via purchase receiving.</p>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card p-5"><p className="text-xs text-slate-400">Total Batches</p><p className="text-xl font-bold text-white mt-1">{batches.length}</p></div>
        <div className="card p-5 border-orange-500/20"><p className="text-xs text-slate-400">Expiring Soon</p><p className="text-xl font-bold text-orange-400 mt-1">{expiring}</p></div>
        <div className="card p-5 border-red-500/20"><p className="text-xs text-slate-400">Expired</p><p className="text-xl font-bold text-red-400 mt-1">{expired}</p></div>
        <div className="card p-5 border-emerald-500/20"><p className="text-xs text-slate-400">Adequate Stock</p><p className="text-xl font-bold text-emerald-400 mt-1">{adequate}</p></div>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 flex-wrap">
        <div className="relative flex-1 max-w-xs">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input className="input pl-9" placeholder="Search product or batch…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <select className="input max-w-xs" value={warehouseFilter} onChange={(e) => setWarehouseFilter(e.target.value)}>
          <option value="">All Warehouses</option>
          {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
        </select>
        <div className="flex gap-1 p-1 bg-surface-800 rounded-xl">
          {(['all', 'expiring', 'expired', 'ok'] as ExpiryFilter[]).map((f) => (
            <button key={f} onClick={() => setExpiryFilter(f)}
              className={`px-3 py-1.5 rounded-lg text-sm transition-colors capitalize ${expiryFilter === f ? 'bg-brand-500 text-white' : 'text-slate-400 hover:text-white'}`}>
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Batch #', 'Product', 'SKU', 'Warehouse', 'Qty', 'Manufacture Date', 'Expiry Date', 'Status'].map((h) => (
                  <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 7 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 8 }).map((_, j) => (
                      <td key={j} className="px-4 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-16" /></td>
                    ))}
                  </tr>
                ))
              ) : batches.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center">
                    <Layers size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No batch records found</p>
                    <p className="text-xs text-slate-600 mt-1">Batches are created automatically when you receive purchase orders with batch/lot information.</p>
                  </td>
                </tr>
              ) : batches.map((b) => {
                const { label, badge } = getExpiryStatus(b)
                return (
                  <tr key={b.id} className="table-row">
                    <td className="px-4 py-3.5 font-mono text-brand-400">{b.batch_number}</td>
                    <td className="px-4 py-3.5 text-white">{b.product_name}</td>
                    <td className="px-4 py-3.5 font-mono text-slate-500 text-xs">{b.product_sku}</td>
                    <td className="px-4 py-3.5 text-slate-400">{b.warehouse_name}</td>
                    <td className="px-4 py-3.5 text-white font-semibold">{b.quantity}</td>
                    <td className="px-4 py-3.5 text-slate-400">{b.manufacture_date ? formatDate(b.manufacture_date) : '—'}</td>
                    <td className="px-4 py-3.5 text-slate-400">{b.expiry_date ? formatDate(b.expiry_date) : '—'}</td>
                    <td className="px-4 py-3.5"><span className={badge}>{label}</span></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
