import { useEffect, useState, useCallback } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Shield, ChevronDown, ChevronRight, Search, X, Globe, RefreshCw } from 'lucide-react'
import { auditLogApi, bypassNextGets } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import DateInput from '@/components/DateInput'

interface ChangeItem { field: string; old: unknown; new: unknown }

interface AuditEntry {
  id: string
  timestamp: string
  user_email: string
  action: 'create' | 'update' | 'delete' | 'login' | 'logout' | 'export' | 'other'
  model: string
  object_id: string
  object_repr: string
  changes: ChangeItem[]
  ip_address: string | null
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const ACTION_CONFIG: Record<string, { label: string; dot: string; badge: string }> = {
  create:  { label: 'Created',  dot: 'bg-emerald-400', badge: 'badge-green'  },
  update:  { label: 'Updated',  dot: 'bg-blue-400',    badge: 'badge-blue'   },
  delete:  { label: 'Deleted',  dot: 'bg-red-400',     badge: 'badge-red'    },
  login:   { label: 'Logged in',dot: 'bg-slate-400',   badge: 'badge-slate'  },
  logout:  { label: 'Logged out',dot:'bg-slate-400',   badge: 'badge-slate'  },
  export:  { label: 'Exported', dot: 'bg-amber-400',   badge: 'badge-orange' },
  other:   { label: 'Action',   dot: 'bg-slate-500',   badge: 'badge-slate'  },
}

const MODEL_LABELS: Record<string, string> = {
  invoice: 'Invoice', product: 'Product', customer: 'Customer',
  employee: 'Employee', expense: 'Expense', purchaseorder: 'Purchase Order',
  bill: 'Bill', payrollrun: 'Payroll Run', fixedasset: 'Fixed Asset',
  journalentry: 'Journal Entry', quote: 'Quote', budget: 'Budget',
  organisation: 'Organisation', user: 'User', membership: 'Team Member',
}

function prettyModel(raw: string) {
  return MODEL_LABELS[raw.toLowerCase()] ?? raw
}

function userInitials(email: string) {
  const parts = email.split('@')[0].split(/[\._-]/)
  return parts.slice(0, 2).map((p) => p[0]?.toUpperCase() ?? '').join('') || '?'
}

function relativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1)  return 'Just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24)  return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 7)  return `${days}d ago`
  return new Date(iso).toLocaleDateString('en-NG', { day: '2-digit', month: 'short', year: 'numeric' })
}

function absoluteTime(iso: string) {
  return new Date(iso).toLocaleString('en-NG', { dateStyle: 'medium', timeStyle: 'short' })
}

function dayLabel(iso: string) {
  const d = new Date(iso)
  const today = new Date()
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return 'Today'
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return d.toLocaleDateString('en-NG', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' })
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  return String(v)
}

// ── Entry row ─────────────────────────────────────────────────────────────────

function EntryRow({ entry }: { entry: AuditEntry }) {
  const [expanded, setExpanded] = useState(false)
  const cfg = ACTION_CONFIG[entry.action] ?? ACTION_CONFIG.other
  const hasChanges = entry.changes?.length > 0

  return (
    <div className="border-b border-surface-700 last:border-0">
      <div
        className={`flex items-start gap-3 px-5 py-3.5 ${hasChanges ? 'cursor-pointer hover:bg-surface-800/60' : ''} transition-colors`}
        onClick={() => hasChanges && setExpanded((p) => !p)}
      >
        {/* Actor avatar */}
        <div className="w-8 h-8 rounded-full bg-brand-500/20 flex items-center justify-center shrink-0 mt-0.5">
          <span className="text-xs font-bold text-brand-300">{userInitials(entry.user_email || '?')}</span>
        </div>

        {/* Main content */}
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
            <span className="text-sm font-medium text-white">{entry.user_email || 'System'}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded font-semibold ${cfg.badge}`}>{cfg.label}</span>
            <span className="text-sm text-slate-400">{prettyModel(entry.model)}</span>
            {entry.object_repr && (
              <span className="text-sm font-medium text-slate-300 truncate max-w-[220px]">"{entry.object_repr}"</span>
            )}
          </div>
          <div className="flex items-center gap-3 mt-1 flex-wrap">
            <span className="text-xs text-slate-500" title={absoluteTime(entry.timestamp)}>
              {relativeTime(entry.timestamp)} · {absoluteTime(entry.timestamp)}
            </span>
            {entry.ip_address && (
              <span className="flex items-center gap-1 text-xs text-slate-600">
                <Globe size={10} /> {entry.ip_address}
              </span>
            )}
            {hasChanges && (
              <span className="text-xs text-slate-600">{entry.changes.length} field{entry.changes.length !== 1 ? 's' : ''} changed</span>
            )}
          </div>
        </div>

        {/* Expand toggle */}
        {hasChanges && (
          <div className="text-slate-500 shrink-0 mt-1">
            {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          </div>
        )}
      </div>

      {/* Change diff */}
      {expanded && hasChanges && (
        <div className="px-16 pb-4">
          <table className="w-full text-xs border border-surface-700 rounded-lg overflow-hidden">
            <thead>
              <tr className="bg-surface-800">
                <th className="px-3 py-2 text-left text-slate-400 font-semibold uppercase tracking-wider w-1/4">Field</th>
                <th className="px-3 py-2 text-left text-slate-400 font-semibold uppercase tracking-wider w-[37.5%]">Before</th>
                <th className="px-3 py-2 text-left text-slate-400 font-semibold uppercase tracking-wider w-[37.5%]">After</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-700">
              {entry.changes.map((c, i) => (
                <tr key={i} className="bg-surface-900/40">
                  <td className="px-3 py-2 font-mono text-slate-400 capitalize">{c.field.replace(/_/g, ' ')}</td>
                  <td className="px-3 py-2 text-red-400/80 line-through">{formatValue(c.old)}</td>
                  <td className="px-3 py-2 text-emerald-400">{formatValue(c.new)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────

const MODEL_OPTIONS = [
  'Invoice', 'Quote', 'Product', 'Customer', 'Employee',
  'Expense', 'PurchaseOrder', 'Bill', 'PayrollRun',
  'FixedAsset', 'JournalEntry', 'Budget', 'Organisation',
]

export default function AuditLogPage() {
  const { user } = useAuthStore()
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)

  const [userSearch, setUserSearch]   = useState('')
  const [modelFilter, setModelFilter] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo]     = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (userSearch)   params.user      = userSearch
      if (modelFilter)  params.model     = modelFilter
      if (actionFilter) params.action    = actionFilter
      if (dateFrom)     params.date_from = dateFrom
      if (dateTo)       params.date_to   = dateTo
      const { data } = await auditLogApi.list(params)
      setEntries(data.results ?? data)
    } catch {
      setEntries([])
    } finally {
      setLoading(false)
    }
  }, [userSearch, modelFilter, actionFilter, dateFrom, dateTo])

  useEffect(() => { load() }, [load])
  useDataRefresh(load)

  // Group entries by calendar day
  const grouped: { day: string; items: AuditEntry[] }[] = []
  for (const entry of entries) {
    const day = dayLabel(entry.timestamp)
    const last = grouped[grouped.length - 1]
    if (last?.day === day) { last.items.push(entry) }
    else { grouped.push({ day, items: [entry] }) }
  }

  const hasFilters = userSearch || modelFilter || actionFilter || dateFrom || dateTo

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Audit Log</h1>
          <p className="text-slate-400 text-sm mt-0.5">Every action in your workspace — who did what, when, and what changed</p>
        </div>
        <div className="flex items-center gap-2 self-start">
          {entries.length > 0 && (
            <span className="text-xs text-slate-500">{entries.length} event{entries.length !== 1 ? 's' : ''}</span>
          )}
          <button onClick={() => { bypassNextGets(); load() }} disabled={loading} className="btn-ghost p-2 text-slate-400 hover:text-white" title="Refresh">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* Access banner */}
      {user?.is_superuser ? (
        <div className="flex items-center gap-3 p-3.5 bg-emerald-500/8 border border-emerald-500/20 rounded-xl">
          <Shield size={15} className="text-emerald-400 shrink-0" />
          <p className="text-xs text-emerald-300">Superuser — full cross-organisation access</p>
        </div>
      ) : (
        <div className="flex items-center gap-3 p-3.5 bg-blue-500/8 border border-blue-500/20 rounded-xl">
          <Shield size={15} className="text-blue-400 shrink-0" />
          <p className="text-xs text-blue-300">Owner &amp; Admin view — scoped to your workspace. All actions are tracked automatically and cannot be modified.</p>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 flex-wrap items-center">
        {/* User search */}
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            className="input pl-8 w-52"
            placeholder="Search by user email…"
            value={userSearch}
            onChange={(e) => setUserSearch(e.target.value)}
          />
        </div>

        <select className="input w-40" value={modelFilter} onChange={(e) => setModelFilter(e.target.value)}>
          <option value="">All modules</option>
          {MODEL_OPTIONS.map((m) => <option key={m} value={m}>{prettyModel(m)}</option>)}
        </select>

        <select className="input w-36" value={actionFilter} onChange={(e) => setActionFilter(e.target.value)}>
          <option value="">All actions</option>
          {(['create','update','delete','login','logout','export'] as const).map((a) => (
            <option key={a} value={a}>{ACTION_CONFIG[a].label}</option>
          ))}
        </select>

        <div className="flex items-center gap-2">
          <DateInput value={dateFrom} onChange={setDateFrom} placeholder="From" />
          <span className="text-slate-500 text-sm">—</span>
          <DateInput value={dateTo} onChange={setDateTo} placeholder="To" />
        </div>

        {hasFilters && (
          <button
            onClick={() => { setUserSearch(''); setModelFilter(''); setActionFilter(''); setDateFrom(''); setDateTo('') }}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors"
          >
            <X size={13} /> Clear
          </button>
        )}
      </div>

      {/* Feed */}
      <div className="card p-0 overflow-hidden">
        {loading ? (
          <div className="divide-y divide-surface-700">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3 px-5 py-3.5">
                <div className="w-8 h-8 rounded-full bg-surface-700 animate-pulse shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="h-3.5 bg-surface-700 rounded animate-pulse w-64" />
                  <div className="h-3 bg-surface-700 rounded animate-pulse w-40" />
                </div>
              </div>
            ))}
          </div>
        ) : entries.length === 0 ? (
          <div className="px-5 py-16 text-center">
            <Shield size={32} className="mx-auto mb-3 text-slate-600" />
            <p className="text-slate-400 font-medium">No events found</p>
            <p className="text-xs text-slate-600 mt-1">
              {hasFilters ? 'Try adjusting your filters.' : 'Events will appear here as your team uses the app.'}
            </p>
          </div>
        ) : (
          grouped.map(({ day, items }) => (
            <div key={day}>
              {/* Day divider */}
              <div className="px-5 py-2 bg-surface-800/60 border-b border-surface-700">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">{day}</span>
              </div>
              {items.map((entry) => <EntryRow key={entry.id} entry={entry} />)}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
