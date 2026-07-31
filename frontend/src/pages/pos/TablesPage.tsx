import { useEffect, useState, useCallback } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { LayoutGrid, Plus, Trash2, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { posApi } from '@/services/api'
import { confirmDialog } from '@/lib/dialog'

interface Table { id: string; name: string; capacity: number; section: string; status: string; is_active: boolean }

const STATUS_BADGE: Record<string, string> = {
  available: 'bg-green-500/15 text-green-400 border-green-500/30',
  occupied: 'bg-red-500/15 text-red-400 border-red-500/30',
  reserved: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
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
    <div className="p-4 sm:p-6 max-w-4xl mx-auto">
      <h1 className="text-xl font-bold text-white flex items-center gap-2 mb-4"><LayoutGrid size={20} /> Tables</h1>
      <div className="rounded-xl border border-surface-700 bg-surface-800/40 p-3 mb-5 flex flex-wrap gap-2 items-end">
        <label className="text-xs text-slate-400">Name<input className="input mt-0.5 w-32" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label className="text-xs text-slate-400">Capacity<input className="input mt-0.5 w-20" value={form.capacity} onChange={(e) => setForm({ ...form, capacity: e.target.value })} inputMode="numeric" /></label>
        <label className="text-xs text-slate-400">Section<input className="input mt-0.5 w-32" value={form.section} onChange={(e) => setForm({ ...form, section: e.target.value })} /></label>
        <button onClick={add} disabled={busy} className="btn-primary flex items-center gap-1"><Plus size={15} /> Add</button>
      </div>
      {loading ? (
        <div className="flex justify-center py-16 text-slate-400"><Loader2 className="animate-spin" /></div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
          {tables.map((t) => (
            <div key={t.id} className="rounded-xl border border-surface-700 bg-surface-800/40 p-3">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-sm font-semibold text-white">{t.name}</div>
                  <div className="text-[11px] text-slate-500">{t.capacity} seats{t.section ? ` · ${t.section}` : ''}</div>
                </div>
                <button onClick={() => remove(t)} className="text-slate-500 hover:text-red-400"><Trash2 size={14} /></button>
              </div>
              <button onClick={() => cycleStatus(t)} className={`mt-2 w-full text-[11px] px-2 py-1 rounded border ${STATUS_BADGE[t.status] ?? ''}`}>
                {t.status}
              </button>
            </div>
          ))}
          {tables.length === 0 && <div className="col-span-full text-center text-slate-500 text-sm py-10">No tables yet.</div>}
        </div>
      )}
    </div>
  )
}
