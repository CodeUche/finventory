import { useEffect, useState, useCallback } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, Trash2, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { posApi } from '@/services/api'
import { confirmDialog } from '@/lib/dialog'

interface Table { id: string; name: string; capacity: number; section: string; status: string; is_active: boolean }

// Kit badge colours (see .badge-* in styles/ds.css)
const STATUS_BADGE: Record<string, string> = {
  available: 'badge-green',
  occupied: 'badge-red',
  reserved: 'badge-yellow',
}

export default function TablesPage() {
  const [tables, setTables] = useState<Table[]>([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState({ name: '', capacity: '4', section: '' })
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await posApi.tables()
      setTables(data.results ?? data)
    } catch { toast.error('Failed to load tables') } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])
  useDataRefresh(load)

  const add = async () => {
    if (!form.name.trim()) { toast.error('Table name required'); return }
    setBusy(true)
    try {
      await posApi.createTable({ name: form.name, capacity: parseInt(form.capacity) || 4, section: form.section })
      setForm({ name: '', capacity: '4', section: '' }); load(); toast.success('Table added')
    } catch { toast.error('Failed to add table') } finally { setBusy(false) }
  }

  const cycleStatus = async (t: Table) => {
    const next = t.status === 'available' ? 'reserved' : t.status === 'reserved' ? 'occupied' : 'available'
    try { await posApi.updateTable(t.id, { status: next }); load() } catch { toast.error('Failed to update') }
  }

  const remove = async (t: Table) => {
    if (!(await confirmDialog(`Delete table ${t.name}?`, { danger: true, confirmText: 'Delete' }))) return
    try { await posApi.deleteTable(t.id); load() } catch { toast.error('Failed to delete') }
  }

  return (
    <div className="ds">
      <header className="ds-head">
        <div>
          <h1>Tables</h1>
          <p>{tables.length} {tables.length === 1 ? 'table' : 'tables'}</p>
        </div>
      </header>
      <div className="card p-4 mb-5 flex flex-wrap gap-3 items-end">
        <label className="label flex flex-col gap-1">Name<input className="input w-40" placeholder="e.g. Table 1" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label className="label flex flex-col gap-1">Seats<input className="input w-24" placeholder="4" value={form.capacity} onChange={(e) => setForm({ ...form, capacity: e.target.value })} inputMode="numeric" /></label>
        <label className="label flex flex-col gap-1">Section<input className="input w-40" placeholder="e.g. Patio" value={form.section} onChange={(e) => setForm({ ...form, section: e.target.value })} /></label>
        <button onClick={add} disabled={busy} className="btn-primary flex items-center gap-1"><Plus size={15} /> Add table</button>
      </div>
      {loading ? (
        <div className="flex justify-center py-16 text-slate-400"><Loader2 className="animate-spin" /></div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
          {tables.map((t) => (
            <div key={t.id} className="card p-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-base font-semibold text-white">{t.name}</div>
                  <div className="text-xs text-slate-500">{t.capacity} seats{t.section ? ` · ${t.section}` : ''}</div>
                </div>
                <button onClick={() => remove(t)} aria-label={`Delete ${t.name}`} className="ds-icon-btn" data-tone="bad"><Trash2 size={16} /></button>
              </div>
              <button onClick={() => cycleStatus(t)} className={`badge ${STATUS_BADGE[t.status] ?? 'badge-slate'} mt-3 w-full justify-center capitalize`}>
                {t.status}
              </button>
            </div>
          ))}
          {tables.length === 0 && <div className="col-span-full text-center text-slate-500 text-sm py-10">No tables yet. Add your first table above.</div>}
        </div>
      )}
    </div>
  )
}
