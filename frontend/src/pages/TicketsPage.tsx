import { useEffect, useState, useCallback } from 'react'
import { HelpCircle, Plus, X, Loader2, Send } from 'lucide-react'
import toast from 'react-hot-toast'
import { helpdeskApi } from '@/services/api'
import { formatDate } from '@/lib/utils'

interface Comment { id: string; author_name: string; body: string; created_at: string }
interface Ticket {
  id: string; ticket_number: string; subject: string; description: string
  status: string; priority: string; category: string
  created_by_name: string; created_at: string; comments: Comment[]
}

const STATUS_BADGE: Record<string, string> = {
  open: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  in_progress: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  resolved: 'bg-green-500/15 text-green-400 border-green-500/30',
  closed: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
}
const PRIORITY_BADGE: Record<string, string> = {
  low: 'text-slate-400', normal: 'text-slate-300', high: 'text-amber-400', urgent: 'text-red-400',
}
const STATUSES = ['open', 'in_progress', 'resolved', 'closed']

export default function TicketsPage() {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [loading, setLoading] = useState(true)
  const [showNew, setShowNew] = useState(false)
  const [selected, setSelected] = useState<Ticket | null>(null)
  const [form, setForm] = useState({ subject: '', description: '', priority: 'normal', category: '' })
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await helpdeskApi.tickets()
      setTickets(data.results ?? data)
    } catch {
      toast.error('Failed to load tickets')
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { load() }, [load])

  const createTicket = async () => {
    if (!form.subject.trim()) { toast.error('Subject is required'); return }
    setBusy(true)
    try {
      await helpdeskApi.createTicket(form)
      toast.success('Ticket created')
      setShowNew(false); setForm({ subject: '', description: '', priority: 'normal', category: '' })
      load()
    } catch {
      toast.error('Failed to create ticket')
    } finally {
      setBusy(false)
    }
  }

  const refreshSelected = async (id: string) => {
    const { data } = await helpdeskApi.getTicket(id)
    setSelected(data)
    setTickets((prev) => prev.map((t) => (t.id === id ? data : t)))
  }

  const addComment = async () => {
    if (!selected || !comment.trim()) return
    setBusy(true)
    try {
      await helpdeskApi.addComment(selected.id, comment.trim())
      setComment('')
      await refreshSelected(selected.id)
    } catch {
      toast.error('Failed to add comment')
    } finally {
      setBusy(false)
    }
  }

  const changeStatus = async (status: string) => {
    if (!selected) return
    try {
      await helpdeskApi.setStatus(selected.id, status)
      await refreshSelected(selected.id)
      toast.success(`Marked ${status.replace('_', ' ')}`)
    } catch {
      toast.error('Failed to update status')
    }
  }

  return (
    <div className="p-4 sm:p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2"><HelpCircle size={20} /> Help Desk</h1>
          <p className="text-xs text-slate-400 mt-1">Raise and track support tickets</p>
        </div>
        <button onClick={() => setShowNew(true)} className="btn-primary flex items-center gap-2"><Plus size={16} /> New Ticket</button>
      </div>

      {loading ? (
        <div className="flex justify-center py-20 text-slate-400"><Loader2 className="animate-spin" /></div>
      ) : tickets.length === 0 ? (
        <div className="text-center py-16 text-slate-500 text-sm">No tickets yet.</div>
      ) : (
        <div className="space-y-2">
          {tickets.map((t) => (
            <button key={t.id} onClick={() => setSelected(t)}
              className="w-full text-left rounded-xl border border-surface-700 bg-surface-800/40 hover:bg-surface-800 px-4 py-3 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-slate-500">{t.ticket_number}</span>
                  <span className={`text-sm font-medium ${PRIORITY_BADGE[t.priority] ?? 'text-slate-300'}`}>{t.subject}</span>
                </div>
                <div className="text-[11px] text-slate-500 mt-0.5">{t.created_by_name} · {formatDate(t.created_at)}</div>
              </div>
              <span className={`text-[11px] px-2 py-1 rounded border shrink-0 ${STATUS_BADGE[t.status] ?? ''}`}>{t.status.replace('_', ' ')}</span>
            </button>
          ))}
        </div>
      )}

      {/* New ticket modal */}
      {showNew && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setShowNew(false)}>
          <div className="w-full max-w-md bg-surface-900 border border-surface-700 rounded-xl p-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-bold text-white">New Ticket</h2>
              <button onClick={() => setShowNew(false)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <div className="space-y-3">
              <input className="input w-full" placeholder="Subject" value={form.subject}
                onChange={(e) => setForm({ ...form, subject: e.target.value })} />
              <textarea className="input w-full h-24" placeholder="Describe the issue…" value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })} />
              <div className="grid grid-cols-2 gap-3">
                <select className="input w-full" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                  <option value="low">Low</option><option value="normal">Normal</option>
                  <option value="high">High</option><option value="urgent">Urgent</option>
                </select>
                <input className="input w-full" placeholder="Category (optional)" value={form.category}
                  onChange={(e) => setForm({ ...form, category: e.target.value })} />
              </div>
              <button onClick={createTicket} disabled={busy} className="btn-primary w-full">
                {busy ? <Loader2 size={15} className="animate-spin mx-auto" /> : 'Create Ticket'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Ticket detail drawer */}
      {selected && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={() => setSelected(null)}>
          <div className="w-full max-w-lg h-full bg-surface-900 border-l border-surface-700 overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="sticky top-0 bg-surface-900 border-b border-surface-700 px-5 py-4 flex items-start justify-between">
              <div>
                <div className="text-xs font-mono text-slate-500">{selected.ticket_number}</div>
                <h2 className="text-sm font-bold text-white">{selected.subject}</h2>
              </div>
              <button onClick={() => setSelected(null)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <div className="p-5 space-y-4">
              {selected.description && <p className="text-sm text-slate-300 whitespace-pre-wrap">{selected.description}</p>}
              <div className="flex flex-wrap gap-2">
                {STATUSES.map((s) => (
                  <button key={s} onClick={() => changeStatus(s)}
                    className={`text-[11px] px-2 py-1 rounded border ${selected.status === s ? STATUS_BADGE[s] : 'border-surface-600 text-slate-400 hover:text-white'}`}>
                    {s.replace('_', ' ')}
                  </button>
                ))}
              </div>
              <div className="border-t border-surface-700 pt-3 space-y-3">
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Comments</h3>
                {(selected.comments ?? []).map((c) => (
                  <div key={c.id} className="text-sm">
                    <span className="text-slate-300 font-medium">{c.author_name}</span>
                    <span className="text-[11px] text-slate-500 ml-2">{formatDate(c.created_at)}</span>
                    <p className="text-slate-300 mt-0.5 whitespace-pre-wrap">{c.body}</p>
                  </div>
                ))}
                {(selected.comments ?? []).length === 0 && <p className="text-xs text-slate-500">No comments yet.</p>}
                <div className="flex gap-2">
                  <input className="input flex-1" placeholder="Add a comment…" value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') addComment() }} />
                  <button onClick={addComment} disabled={busy} className="btn-primary px-3"><Send size={15} /></button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
