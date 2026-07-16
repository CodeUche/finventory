import { Fragment, useEffect, useState, useCallback, useMemo } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Shield, ChevronDown, ChevronRight, ChevronUp, ChevronLeft, Search, X, Globe, RefreshCw, FileDown } from 'lucide-react'
import { auditLogApi, bypassNextGets } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import DateInput from '@/components/DateInput'

interface ChangeItem { field: string; old: unknown; new: unknown }

interface AuditEntry {
  id: string
  timestamp: string
  user_email: string
  action: 'create' | 'update' | 'delete' | 'login' | 'logout' | 'export' | 'other' | 'support_access'
  model: string
  object_id: string
  object_repr: string
  changes: ChangeItem[]
  ip_address: string | null
  user_agent: string | null
  actor_label: string
  is_owner_action: boolean
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
  support_access: { label: 'Support Access', dot: 'bg-red-500', badge: 'badge-red' },
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

function absoluteTime(iso: string) {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  return String(v)
}

function deviceLabel(ua: string | null): string {
  if (!ua) return '—'
  let browser = 'Unknown'
  if (ua.includes('Edg/')) browser = 'Edge'
  else if (ua.includes('Chrome/')) browser = 'Chrome'
  else if (ua.includes('Firefox/')) browser = 'Firefox'
  else if (ua.includes('Safari/')) browser = 'Safari'

  let os = ''
  if (ua.includes('Windows')) os = 'Windows'
  else if (ua.includes('Mac OS') || ua.includes('Macintosh')) os = 'Mac'
  else if (ua.includes('Android')) os = 'Android'
  else if (ua.includes('iPhone') || ua.includes('iPad') || ua.includes('iOS')) os = 'iOS'
  else if (ua.includes('Linux')) os = 'Linux'

  return os ? `${browser} / ${os}` : browser
}

function renderActorLabel(label: string) {
  const match = label.match(/^(.*?)(\s*\(Owner\))$/)
  if (match) {
    return (
      <>
        <span>{match[1]}</span>
        <span className="text-amber-400 font-semibold">{match[2]}</span>
      </>
    )
  }
  return <span>{label}</span>
}

type SortKey = 'timestamp' | 'actor_label'
type SortDir = 'asc' | 'desc'

// ── Page ─────────────────────────────────────────────────────────────────────

const MODEL_OPTIONS = [
  'Invoice', 'Quote', 'Product', 'Customer', 'Employee',
  'Expense', 'PurchaseOrder', 'Bill', 'PayrollRun',
  'FixedAsset', 'JournalEntry', 'Budget', 'Organisation',
]

export default function AuditLogPage() {
  const { user } = useAuthStore()
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [count, setCount] = useState(0)
  const [exporting, setExporting] = useState(false)
  const [loading, setLoading] = useState(true)

  const [userSearch, setUserSearch]   = useState('')
  const [modelFilter, setModelFilter] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo]     = useState('')
  const [ipSearch, setIpSearch] = useState('')
  const [authOnly, setAuthOnly] = useState(false)

  const [sortKey, setSortKey] = useState<SortKey>('timestamp')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (userSearch)   params.user      = userSearch
      if (modelFilter)  params.model     = modelFilter
      if (actionFilter) params.action    = actionFilter
      if (dateFrom)     params.date_from = dateFrom
      if (dateTo)       params.date_to   = dateTo
      if (ipSearch)     params.ip        = ipSearch
      params.page = String(page)
      params.page_size = '50'
      const { data } = await auditLogApi.list(params)
      setEntries(data.results ?? data)
      setPages(data.pages ?? 1)
      setCount(data.count ?? (data.results ?? data).length)
    } catch {
      setEntries([])
    } finally {
      setLoading(false)
    }
  }, [userSearch, modelFilter, actionFilter, dateFrom, dateTo, ipSearch, page])

  // Any filter change returns to page 1
  useEffect(() => { setPage(1) }, [userSearch, modelFilter, actionFilter, dateFrom, dateTo, ipSearch])

  const handleExport = async () => {
    setExporting(true)
    try {
      const params: Record<string, string> = { export: 'csv' }
      if (userSearch)   params.user      = userSearch
      if (modelFilter)  params.model     = modelFilter
      if (actionFilter) params.action    = actionFilter
      if (dateFrom)     params.date_from = dateFrom
      if (dateTo)       params.date_to   = dateTo
      if (ipSearch)     params.ip        = ipSearch
      const { data } = await auditLogApi.list(params)
      // CSV arrives as text — normalise to a Blob for the save dialog/download
      const blob = data instanceof Blob ? data : new Blob([typeof data === 'string' ? data : String(data)], { type: 'text/csv' })
      const { saveBlobFile } = await import('@/lib/saveBlobFile')
      await saveBlobFile(blob, `audit-log-${new Date().toISOString().slice(0, 10)}.csv`)
    } catch {
      const { default: toast } = await import('react-hot-toast')
      toast.error('Export failed. Please try again.')
    } finally {
      setExporting(false)
    }
  }

  useEffect(() => { load() }, [load])
  useDataRefresh(load)

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const visibleEntries = useMemo(() => {
    let list = entries
    if (authOnly) {
      list = list.filter((e) => e.action === 'login' || e.action === 'logout')
    }
    const sorted = [...list].sort((a, b) => {
      let cmp = 0
      if (sortKey === 'timestamp') {
        cmp = new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
      } else {
        cmp = (a.actor_label || '').localeCompare(b.actor_label || '')
      }
      return sortDir === 'asc' ? cmp : -cmp
    })
    return sorted
  }, [entries, authOnly, sortKey, sortDir])

  const hasFilters = userSearch || modelFilter || actionFilter || dateFrom || dateTo || ipSearch || authOnly

  const clearFilters = () => {
    setUserSearch(''); setModelFilter(''); setActionFilter(''); setDateFrom(''); setDateTo(''); setIpSearch(''); setAuthOnly(false)
  }

  const sortIcon = (key: SortKey) => {
    if (sortKey !== key) return null
    return sortDir === 'asc' ? <ChevronUp size={11} className="inline ml-1" /> : <ChevronDown size={11} className="inline ml-1" />
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">Audit Log</h1>
          <p className="text-slate-400 text-sm mt-0.5">Every action in your workspace — who did what, when, and what changed</p>
        </div>
        <div className="flex items-center gap-2 self-start">
          {count > 0 && (
            <span className="text-xs text-slate-500">{count.toLocaleString()} event{count !== 1 ? 's' : ''}</span>
          )}
          <button
            onClick={handleExport}
            disabled={exporting || loading}
            className="btn-ghost px-3 py-2 text-slate-400 hover:text-white text-xs flex items-center gap-1.5 disabled:opacity-50"
            title="Export the filtered log as CSV"
          >
            <FileDown size={14} className={exporting ? 'animate-pulse' : ''} />
            {exporting ? 'Exporting…' : 'Export CSV'}
          </button>
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

        {/* IP search */}
        <div className="relative">
          <Globe size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            className="input pl-8 w-40 font-mono"
            placeholder="IP address…"
            value={ipSearch}
            onChange={(e) => setIpSearch(e.target.value)}
          />
        </div>

        <select className="input w-40" value={modelFilter} onChange={(e) => setModelFilter(e.target.value)}>
          <option value="">All modules</option>
          {MODEL_OPTIONS.map((m) => <option key={m} value={m}>{prettyModel(m)}</option>)}
        </select>

        <select className="input w-36" value={actionFilter} onChange={(e) => setActionFilter(e.target.value)}>
          <option value="">All actions</option>
          {(['create','update','delete','login','logout','export','support_access'] as const).map((a) => (
            <option key={a} value={a}>{ACTION_CONFIG[a].label}</option>
          ))}
        </select>

        <div className="flex items-center gap-2">
          <DateInput value={dateFrom} onChange={setDateFrom} placeholder="From" />
          <span className="text-slate-500 text-sm">—</span>
          <DateInput value={dateTo} onChange={setDateTo} placeholder="To" />
        </div>

        <button
          onClick={() => setAuthOnly((p) => !p)}
          className={`text-xs px-3 py-2 rounded-lg border transition-colors ${
            authOnly
              ? 'bg-brand-500/15 border-brand-500/40 text-brand-300'
              : 'border-surface-700 text-slate-400 hover:text-white hover:border-surface-600'
          }`}
        >
          Login/Logout only
        </button>

        {hasFilters && (
          <button
            onClick={clearFilters}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors"
          >
            <X size={13} /> Clear
          </button>
        )}
      </div>

      {/* Table */}
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
        ) : visibleEntries.length === 0 ? (
          <div className="px-5 py-16 text-center">
            <Shield size={32} className="mx-auto mb-3 text-slate-600" />
            <p className="text-slate-400 font-medium">No events found</p>
            <p className="text-xs text-slate-600 mt-1">
              {hasFilters ? 'Try adjusting your filters.' : 'Events will appear here as your team uses the app.'}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-surface-800 border-b border-surface-700">
                  <th
                    className="px-3 py-2 text-left text-slate-400 font-semibold uppercase tracking-wider cursor-pointer hover:text-white select-none whitespace-nowrap"
                    onClick={() => toggleSort('timestamp')}
                  >
                    Timestamp{sortIcon('timestamp')}
                  </th>
                  <th
                    className="px-3 py-2 text-left text-slate-400 font-semibold uppercase tracking-wider cursor-pointer hover:text-white select-none whitespace-nowrap"
                    onClick={() => toggleSort('actor_label')}
                  >
                    User{sortIcon('actor_label')}
                  </th>
                  <th className="px-3 py-2 text-left text-slate-400 font-semibold uppercase tracking-wider whitespace-nowrap">Action</th>
                  <th className="px-3 py-2 text-left text-slate-400 font-semibold uppercase tracking-wider whitespace-nowrap">Model</th>
                  <th className="px-3 py-2 text-left text-slate-400 font-semibold uppercase tracking-wider">Object</th>
                  <th className="px-3 py-2 text-left text-slate-400 font-semibold uppercase tracking-wider whitespace-nowrap">IP Address</th>
                  <th className="px-3 py-2 text-left text-slate-400 font-semibold uppercase tracking-wider whitespace-nowrap">Device</th>
                  <th className="px-3 py-2 w-6"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-700">
                {visibleEntries.map((entry) => {
                  const cfg = ACTION_CONFIG[entry.action] ?? ACTION_CONFIG.other
                  const hasChanges = entry.changes?.length > 0
                  const isExpanded = expandedId === entry.id
                  const isExpandable = hasChanges || !!entry.user_agent || !!entry.ip_address
                  return (
                    <Fragment key={entry.id}>
                      <tr
                        className={`transition-colors ${isExpandable ? 'cursor-pointer' : ''} ${isExpanded ? 'bg-brand-500/10' : 'hover:bg-surface-800/60'}`}
                        onClick={() => isExpandable && setExpandedId((p) => (p === entry.id ? null : entry.id))}
                      >
                        <td className="px-3 py-2 font-mono text-slate-300 whitespace-nowrap">{absoluteTime(entry.timestamp)}</td>
                        <td className="px-3 py-2 text-slate-200 whitespace-nowrap">{renderActorLabel(entry.actor_label || entry.user_email || 'System')}</td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          <span className={`text-xs px-1.5 py-0.5 rounded font-semibold ${cfg.badge}`}>{cfg.label}</span>
                        </td>
                        <td className="px-3 py-2 text-slate-400 whitespace-nowrap">{prettyModel(entry.model)}</td>
                        <td className="px-3 py-2 font-mono text-slate-300 truncate max-w-[220px]">{entry.object_repr || '—'}</td>
                        <td className="px-3 py-2 font-mono text-slate-400 whitespace-nowrap">{entry.ip_address || '—'}</td>
                        <td className="px-3 py-2 text-slate-400 whitespace-nowrap" title={entry.user_agent || undefined}>
                          {deviceLabel(entry.user_agent)}
                        </td>
                        <td className="px-3 py-2 text-slate-500">
                          {isExpandable && (isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />)}
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr className="bg-surface-900/40">
                          <td colSpan={8} className="px-6 py-4">
                            <div className="space-y-3">
                              {hasChanges && (
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
                              )}
                              <div className="flex flex-wrap gap-x-8 gap-y-1 text-xs text-slate-400">
                                <div>
                                  <span className="text-slate-500 uppercase tracking-wider mr-2">IP Address</span>
                                  <span className="font-mono text-slate-300">{entry.ip_address || '—'}</span>
                                </div>
                                <div className="min-w-0">
                                  <span className="text-slate-500 uppercase tracking-wider mr-2">User Agent</span>
                                  <span className="font-mono text-slate-300 break-all">{entry.user_agent || '—'}</span>
                                </div>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {pages > 1 && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-surface-700 text-xs text-slate-400">
            <span>Page {page} of {pages} · {count.toLocaleString()} events</span>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1 || loading}
                className="btn-ghost px-2.5 py-1.5 disabled:opacity-40 flex items-center gap-1"
              >
                <ChevronLeft size={13} /> Prev
              </button>
              <button
                onClick={() => setPage((p) => Math.min(pages, p + 1))}
                disabled={page >= pages || loading}
                className="btn-ghost px-2.5 py-1.5 disabled:opacity-40 flex items-center gap-1"
              >
                Next <ChevronRight size={13} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
