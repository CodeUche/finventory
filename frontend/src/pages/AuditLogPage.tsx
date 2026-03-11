import { useEffect, useState } from 'react'
import { Shield } from 'lucide-react'
import { auditLogApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import DateInput from '@/components/DateInput'

interface AuditEntry {
  id: string
  timestamp: string
  user: string
  user_email: string
  action: 'create' | 'update' | 'delete' | 'login' | 'logout'
  model: string
  object_repr: string
  changes_summary: string
}

const ACTION_BADGE: Record<string, string> = {
  create: 'badge-green',
  update: 'badge-blue',
  delete: 'badge-red',
  login: 'badge-slate',
  logout: 'badge-slate',
}

export default function AuditLogPage() {
  const { user } = useAuthStore()
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [modelFilter, setModelFilter] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (modelFilter) params.model = modelFilter
      if (actionFilter) params.action = actionFilter
      if (dateFrom) params.date_from = dateFrom
      if (dateTo) params.date_to = dateTo
      const { data } = await auditLogApi.list(params)
      setEntries(data.results ?? data)
    } catch {
      // Endpoint may not exist yet — show empty state gracefully
      setEntries([])
    }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [modelFilter, actionFilter, dateFrom, dateTo])

  const formatTimestamp = (ts: string) => {
    try { return new Date(ts).toLocaleString('en-NG', { dateStyle: 'medium', timeStyle: 'short' }) }
    catch { return ts }
  }

  const MODEL_OPTIONS = ['Invoice', 'Product', 'Customer', 'Employee', 'Expense', 'PurchaseOrder', 'Bill', 'PayrollRun', 'FixedAsset', 'JournalEntry']

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Audit Log</h1>
        <p className="text-slate-400 text-sm">Complete trail of all system actions</p>
      </div>

      {/* Info banner */}
      {user?.is_superuser ? (
        <div className="flex items-start gap-3 p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-xl">
          <Shield size={18} className="text-emerald-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-emerald-400">Full Access — Superuser</p>
            <p className="text-xs text-slate-400 mt-0.5">You have full platform access. All create, update, delete, login, and logout actions across all organisations are tracked here.</p>
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-3 p-4 bg-blue-500/10 border border-blue-500/20 rounded-xl">
          <Shield size={18} className="text-blue-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-blue-400">Owner &amp; Admin Access</p>
            <p className="text-xs text-slate-400 mt-0.5">Audit log is visible to Owner and Admin roles only. All create, update, and delete actions are automatically tracked.</p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 flex-wrap">
        <select className="input max-w-xs" value={modelFilter} onChange={(e) => setModelFilter(e.target.value)}>
          <option value="">All Models</option>
          {MODEL_OPTIONS.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <select className="input max-w-xs" value={actionFilter} onChange={(e) => setActionFilter(e.target.value)}>
          <option value="">All Actions</option>
          {['create', 'update', 'delete', 'login', 'logout'].map((a) => <option key={a} value={a}>{a.charAt(0).toUpperCase() + a.slice(1)}</option>)}
        </select>
        <div className="flex items-center gap-2">
          <DateInput value={dateFrom} onChange={setDateFrom} placeholder="From" />
          <span className="text-slate-500 text-sm">to</span>
          <DateInput value={dateTo} onChange={setDateTo} placeholder="To" />
        </div>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Date / Time', 'User', 'Action', 'Model', 'Record', 'Summary'].map((h) => (
                  <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 6 }).map((_, j) => (
                      <td key={j} className="px-4 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-20" /></td>
                    ))}
                  </tr>
                ))
              ) : entries.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center">
                    <Shield size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500 mb-1">No audit log entries yet</p>
                    <p className="text-xs text-slate-600">The audit log API endpoint may not be configured yet. Entries will appear here once the backend audit logging is enabled.</p>
                  </td>
                </tr>
              ) : entries.map((e) => (
                <tr key={e.id} className="table-row">
                  <td className="px-4 py-3.5 text-slate-400 whitespace-nowrap text-xs">{formatTimestamp(e.timestamp)}</td>
                  <td className="px-4 py-3.5 text-slate-300">{e.user_email || e.user || '—'}</td>
                  <td className="px-4 py-3.5"><span className={ACTION_BADGE[e.action] ?? 'badge-slate'}>{e.action}</span></td>
                  <td className="px-4 py-3.5 text-slate-400">{e.model}</td>
                  <td className="px-4 py-3.5 text-slate-300 max-w-[150px] truncate">{e.object_repr}</td>
                  <td className="px-4 py-3.5 text-slate-500 text-xs max-w-xs truncate">{e.changes_summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
