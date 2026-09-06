import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, X, CalendarClock, Loader2, ShieldCheck, RefreshCw, ArrowLeft } from 'lucide-react'
import toast from 'react-hot-toast'
import { budgetPeriodApi, bypassNextGets } from '@/services/api'
import DateInput from '@/components/DateInput'
import { useAuthStore } from '@/store/authStore'
import type { BudgetPeriod } from '@/types'

interface PeriodForm { name: string; financial_year: string; start_date: string; end_date: string }

const now = new Date()
const CURRENT_YEAR = now.getFullYear()
const MIN_YEAR = CURRENT_YEAR - 10
const MAX_YEAR = CURRENT_YEAR + 10
const BLANK_PERIOD: PeriodForm = { name: '', financial_year: String(CURRENT_YEAR), start_date: '', end_date: '' }

const STATUS_BADGE: Record<string, string> = { draft: 'badge-slate', active: 'badge-green', closed: 'badge-red' }

function isManagerOrAbove(memberRole: string | null, isSuperuser?: boolean): boolean {
  return !!isSuperuser || memberRole === 'owner' || memberRole === 'admin' || memberRole === 'manager'
}

export default function BudgetPeriodsPage() {
  const { memberRole, user } = useAuthStore()
  const [periods, setPeriods] = useState<BudgetPeriod[]>([])
  const [loading, setLoading] = useState(true)

  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState<PeriodForm>(BLANK_PERIOD)
  const [saving, setSaving] = useState(false)
  const [approving, setApproving] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await budgetPeriodApi.list()
      setPeriods(data.results ?? data)
    } catch { toast.error('Failed to load budget periods') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useDataRefresh(load)

  const handleCreate = async () => {
    if (!form.name.trim()) { toast.error('Period name is required'); return }
    const year = parseInt(form.financial_year)
    if (isNaN(year) || year < MIN_YEAR || year > MAX_YEAR) {
      toast.error(`Financial year must be between ${MIN_YEAR} and ${MAX_YEAR}`)
      return
    }
    if (!form.start_date || !form.end_date) { toast.error('Start and end dates are required'); return }
    if (form.end_date < form.start_date) { toast.error('End date must be after start date'); return }
    setSaving(true)
    try {
      await budgetPeriodApi.create({
        name: form.name, financial_year: year,
        start_date: form.start_date, end_date: form.end_date,
      })
      toast.success('Budget period created')
      setShowModal(false)
      setForm(BLANK_PERIOD)
      load()
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to create budget period')
      toast.error(msg)
    } finally { setSaving(false) }
  }

  const handleApprove = async (p: BudgetPeriod) => {
    setApproving(p.id)
    try {
      await budgetPeriodApi.approve(p.id)
      toast.success('Budget period approved')
      // approve's URL has a UUID mid-path (/budgets/periods/{id}/approve/), so
      // the axios write-through cache's list-invalidation heuristic can't
      // match it — same gap documented for BudgetPage's approve handler.
      bypassNextGets()
      load()
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? err?.response?.data?.detail ?? 'Failed to approve budget period')
      toast.error(msg)
    } finally { setApproving(null) }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Link to="/budgets" className="text-slate-400 hover:text-white"><ArrowLeft size={18} /></Link>
            <h1 className="text-2xl font-bold text-white">Budget Periods</h1>
          </div>
          <p className="text-slate-400 text-sm">{periods.length} period{periods.length !== 1 ? 's' : ''}</p>
        </div>
        <div className="flex items-center gap-2 sm:ml-auto">
          <button onClick={() => { bypassNextGets(); load() }} disabled={loading} className="btn-ghost p-2 text-slate-400 hover:text-white" title="Refresh">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <button className="btn-primary" onClick={() => setShowModal(true)}>
            <Plus size={16} /> New Period
          </button>
        </div>
      </div>

      <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl px-4 py-3 text-sm text-slate-300">
        A Budget Period is a named date range (e.g. "FY2026" or "Q1 2026") you can pin a Budget to.
        Once pinned, any <Link to="/budgets/allocations" className="text-brand-400 hover:underline">Budget Allocation</Link> on
        that Budget measures actual GL spend within this period's exact start/end dates instead of the whole calendar year.
      </div>

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="card p-5 animate-pulse">
              <div className="h-5 bg-surface-700 rounded w-48 mb-2" />
              <div className="h-3 bg-surface-700 rounded w-32" />
            </div>
          ))}
        </div>
      ) : periods.length === 0 ? (
        <div className="card p-12 text-center">
          <CalendarClock size={36} className="mx-auto mb-3 text-slate-600" />
          <p className="text-slate-400 font-medium">No budget periods yet</p>
          <p className="text-slate-500 text-sm mt-1 mb-4">Create a named period to pin your budgets to an exact date range</p>
          <button onClick={() => setShowModal(true)} className="btn-primary mt-2 inline-flex items-center gap-2 text-sm">
            <Plus size={14} /> Create First Period
          </button>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700 bg-surface-800/50">
                {['Name', 'Financial Year', 'Start Date', 'End Date', 'Status', 'Approved By', ''].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-700">
              {periods.map((p) => (
                <tr key={p.id} className="table-row">
                  <td className="px-4 py-3 text-white font-medium">{p.name}</td>
                  <td className="px-4 py-3 text-slate-400">{p.financial_year}</td>
                  <td className="px-4 py-3 text-slate-400">{p.start_date}</td>
                  <td className="px-4 py-3 text-slate-400">{p.end_date}</td>
                  <td className="px-4 py-3"><span className={STATUS_BADGE[p.status] ?? 'badge-slate'}>{p.status}</span></td>
                  <td className="px-4 py-3 text-slate-500">
                    {p.approved_by ? (
                      <span className="text-emerald-400/80 text-xs flex items-center gap-1">
                        <ShieldCheck size={11} /> {p.approved_by_name || 'a manager'}
                      </span>
                    ) : '—'}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {!p.approved_by && p.status !== 'closed' && isManagerOrAbove(memberRole, user?.is_superuser) && (
                      <button
                        onClick={() => handleApprove(p)}
                        disabled={approving === p.id}
                        className="text-xs px-2.5 py-1 rounded-lg bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition-colors inline-flex items-center gap-1 disabled:opacity-50"
                      >
                        {approving === p.id ? <Loader2 size={11} className="animate-spin" /> : <ShieldCheck size={11} />}
                        Approve
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative card w-full max-w-md p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">New Budget Period</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Period Name *</label>
                <input className="input" placeholder="e.g. FY2026 or Q1 2026" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Financial Year *</label>
                <input
                  type="number" className="input" min={MIN_YEAR} max={MAX_YEAR}
                  value={form.financial_year}
                  onChange={(e) => setForm({ ...form, financial_year: e.target.value })}
                />
              </div>
              <div />
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Start Date *</label>
                <DateInput value={form.start_date} onChange={(v) => setForm({ ...form, start_date: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">End Date *</label>
                <DateInput value={form.end_date} onChange={(v) => setForm({ ...form, end_date: v })} min={form.start_date || undefined} />
              </div>
            </div>
            <div className="flex gap-3">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleCreate} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : 'Create Period'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
