import { Fragment, useEffect, useMemo, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { confirmDialog } from '@/lib/dialog'
import { Shield, Users, Building2, RefreshCw, Loader2, CheckCircle, XCircle, TrendingUp, BookOpen, Ban, RotateCcw, MessageSquare, Send, UserCheck } from 'lucide-react'
import toast from 'react-hot-toast'
import { platformAdminApi, orgApi, bypassNextGets } from '@/services/api'
import { formatCurrency } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import { useNavigate } from 'react-router-dom'

interface OrgRow {
  id: string; name: string; owner_email: string | null; currency: string; country: string
  plan: string; sub_status: string; member_count: number; invoice_count: number
  total_revenue: string; is_active: boolean; created_at: string
}
interface PlatformUser {
  id: string; email: string; first_name: string; last_name: string
  is_superuser: boolean; is_active: boolean; is_verified: boolean
  created_at: string; orgs: { name: string; role: string; owner_email: string | null }[]
}
interface Stats {
  total_orgs: number; active_orgs: number; total_users: number
  superusers: number; total_invoices: number; total_revenue: string
  plans: { name: string; price: string; is_active: boolean }[]
}
interface TicketComment { id: string; author_name: string; body: string; created_at: string }
interface PlatformTicket {
  id: string; ticket_number: string; subject: string; description: string
  status: string; priority: string; category: string
  created_by_name: string; created_by_email: string; organisation_name: string
  assigned_to_name: string | null; comments: TicketComment[]; created_at: string
}

const SUB_BADGE: Record<string, string> = {
  active: 'badge-green', trialing: 'badge-blue', canceled: 'badge-red',
  none: 'badge-slate', past_due: 'badge-red',
}
const TICKET_STATUS_BADGE: Record<string, string> = {
  open: 'badge-blue', in_progress: 'badge-orange', resolved: 'badge-green', closed: 'badge-slate',
}
const TICKET_PRIORITY_BADGE: Record<string, string> = {
  low: 'badge-slate', normal: 'badge-blue', high: 'badge-orange', urgent: 'badge-red',
}
const TICKET_STATUSES: { value: string; label: string }[] = [
  { value: 'open', label: 'Open' }, { value: 'in_progress', label: 'In Progress' },
  { value: 'resolved', label: 'Resolved' }, { value: 'closed', label: 'Closed' },
]

export default function PlatformAdminPage() {
  const { user } = useAuthStore()
  const navigate = useNavigate()
  const [stats, setStats] = useState<Stats | null>(null)
  const [orgs, setOrgs] = useState<OrgRow[]>([])
  const [users, setUsers] = useState<PlatformUser[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'overview' | 'orgs' | 'users' | 'support'>('overview')
  const [reseedingOrg, setReseedingOrg] = useState<string | null>(null)
  const [togglingUser, setTogglingUser] = useState<string | null>(null)
  // Support inbox (lazy-loaded when the tab is first opened)
  const [tickets, setTickets] = useState<PlatformTicket[]>([])
  const [ticketsLoaded, setTicketsLoaded] = useState(false)
  const [ticketsLoading, setTicketsLoading] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [reply, setReply] = useState('')
  const [replying, setReplying] = useState(false)
  const [ticketBusy, setTicketBusy] = useState(false)

  // Guard: redirect non-superusers
  useEffect(() => {
    if (user && !user.is_superuser) {
      toast.error('Access denied')
      navigate('/dashboard')
    }
  }, [user])

  const load = async () => {
    setLoading(true)
    try {
      const [statsRes, usersRes] = await Promise.all([
        platformAdminApi.stats(),
        platformAdminApi.users(),
      ])
      setStats(statsRes.data.summary)
      setOrgs(statsRes.data.organisations)
      // PlatformUsersView uses _AdminUserPagination so the response may be
      // { count, next, previous, results: [...] } — unwrap the results array.
      setUsers(usersRes.data.results ?? usersRes.data)
    } catch {
      toast.error('Failed to load platform data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])
  useDataRefresh(load)

  const handleReseedCoa = async (org: OrgRow) => {
    if (!(await confirmDialog(`Reseed chart of accounts for "${org.name}"?\n\nThis is safe and idempotent — it only adds missing accounts, never overwrites existing ones.`))) return
    setReseedingOrg(org.id)
    try {
      const { data } = await orgApi.reseedCoa(org.id)
      toast.success(`COA reseeded for ${org.name} — ${data.accounts_added} accounts added`)
    } catch {
      toast.error('Failed to reseed COA')
    } finally {
      setReseedingOrg(null)
    }
  }

  const handleToggleActive = async (target: PlatformUser) => {
    if (target.id === user?.id) { toast.error("You can't deactivate your own account."); return }
    const nextActive = !target.is_active
    const verb = nextActive ? 'reactivate' : 'deactivate'
    if (!(await confirmDialog(`${nextActive ? 'Reactivate' : 'Deactivate'} ${target.email}?${!nextActive && target.orgs.some(o => o.role === 'owner') ? '\n\nThis cascades to all sub-accounts in their organisation(s).' : ''}`))) return
    setTogglingUser(target.id)
    try {
      await platformAdminApi.setUserActive(target.id, nextActive)
      setUsers((prev) => prev.map((u) => u.id === target.id ? { ...u, is_active: nextActive } : u))
      toast.success(`${target.email} ${verb}d.`)
    } catch {
      toast.error(`Failed to ${verb} user`)
    } finally {
      setTogglingUser(null)
    }
  }

  const loadTickets = async () => {
    setTicketsLoading(true)
    try {
      const { data } = await platformAdminApi.tickets({ page_size: 100 })
      setTickets(data.results ?? data)
      setTicketsLoaded(true)
    } catch {
      toast.error('Failed to load support tickets')
    } finally {
      setTicketsLoading(false)
    }
  }

  // Lazy-load the inbox the first time the Support tab is opened.
  useEffect(() => {
    if (tab === 'support' && !ticketsLoaded && !ticketsLoading) loadTickets()
  }, [tab])

  const selectedTicket = tickets.find((t) => t.id === selectedId) ?? null

  const handleReply = async () => {
    if (!selectedTicket || !reply.trim()) return
    setReplying(true)
    try {
      const { data } = await platformAdminApi.ticketReply(selectedTicket.id, reply.trim())
      setTickets((prev) => prev.map((t) => t.id === selectedTicket.id
        ? { ...t, comments: [...t.comments, data] } : t))
      setReply('')
      toast.success('Reply sent — the customer has been emailed')
    } catch {
      toast.error('Failed to send reply')
    } finally {
      setReplying(false)
    }
  }

  const handleTicketStatus = async (status: string) => {
    if (!selectedTicket) return
    setTicketBusy(true)
    try {
      const { data } = await platformAdminApi.ticketStatus(selectedTicket.id, status)
      setTickets((prev) => prev.map((t) => t.id === selectedTicket.id ? { ...t, status: data.status } : t))
    } catch {
      toast.error('Failed to update status')
    } finally {
      setTicketBusy(false)
    }
  }

  const handleAssignSelf = async () => {
    if (!selectedTicket) return
    setTicketBusy(true)
    try {
      const { data } = await platformAdminApi.ticketAssign(selectedTicket.id)
      setTickets((prev) => prev.map((t) => t.id === selectedTicket.id ? { ...t, assigned_to_name: data.assigned_to_name } : t))
      toast.success('Assigned to you')
    } catch {
      toast.error('Failed to assign')
    } finally {
      setTicketBusy(false)
    }
  }

  const openTicketCount = useMemo(
    () => tickets.filter((t) => t.status === 'open' || t.status === 'in_progress').length,
    [tickets],
  )

  // Group sub-accounts under their organisation's owner so admins can tell
  // real (owner) accounts apart from staff/sub-accounts added by them.
  const userGroups = useMemo(() => {
    const byEmail = new Map(users.map((u) => [u.email, u]))
    const ownedIds = new Set(
      users.filter((u) => u.orgs.some((o) => o.role === 'owner')).map((u) => u.id),
    )
    const subsByOwnerId = new Map<string, PlatformUser[]>()
    const orphans: PlatformUser[] = []
    for (const u of users) {
      if (ownedIds.has(u.id)) continue
      const ownerEmail = u.orgs.find((o) => o.owner_email)?.owner_email
      const owner = ownerEmail ? byEmail.get(ownerEmail) : undefined
      if (owner && ownedIds.has(owner.id)) {
        const list = subsByOwnerId.get(owner.id) ?? []
        list.push(u)
        subsByOwnerId.set(owner.id, list)
      } else {
        orphans.push(u)
      }
    }
    const groups = users
      .filter((u) => ownedIds.has(u.id))
      .map((owner) => ({ owner, subs: subsByOwnerId.get(owner.id) ?? [] }))
    return { groups, orphans }
  }, [users])

  const renderUserRow = (u: PlatformUser, isSubAccount = false) => (
    <tr key={u.id} className="table-row">
      <td className="px-4 py-3.5">
        <div className={isSubAccount ? 'flex items-start gap-1.5 pl-5' : ''}>
          {isSubAccount && <span className="text-slate-600 text-sm mt-0.5 shrink-0">↳</span>}
          <div>
            <p className={isSubAccount ? 'text-slate-300 font-medium text-sm' : 'text-white font-medium'}>{u.first_name} {u.last_name}</p>
            <p className="text-xs text-slate-500">{u.email}</p>
          </div>
        </div>
      </td>
      <td className="px-4 py-3.5">
        {u.is_superuser ? <span className="badge-orange">Superuser</span> : <span className="text-slate-600">—</span>}
      </td>
      <td className="px-4 py-3.5">
        {u.is_verified ? <CheckCircle size={15} className="text-emerald-400" /> : <XCircle size={15} className="text-slate-600" />}
      </td>
      <td className="px-4 py-3.5">
        {u.is_active ? <CheckCircle size={15} className="text-emerald-400" /> : <XCircle size={15} className="text-red-400" />}
      </td>
      <td className="px-4 py-3.5">
        <div className="space-y-0.5">
          {u.orgs.map((o, i) => (
            <p key={i} className="text-xs text-slate-400">{o.name} <span className="badge-slate text-xs py-0">{o.role}</span></p>
          ))}
          {u.orgs.length === 0 && <span className="text-slate-600 text-xs">No orgs</span>}
        </div>
      </td>
      <td className="px-4 py-3.5 text-slate-400 text-xs">{new Date(u.created_at).toLocaleDateString()}</td>
      <td className="px-4 py-3.5">
        {u.id === user?.id ? (
          <span className="text-slate-600 text-xs">You</span>
        ) : (
          <button
            onClick={() => handleToggleActive(u)}
            disabled={togglingUser === u.id}
            title={u.is_active ? 'Deactivate this user' : 'Reactivate this user'}
            className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg transition-colors disabled:opacity-50 ${
              u.is_active
                ? 'bg-red-500/10 hover:bg-red-500/20 text-red-400'
                : 'bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400'
            }`}
          >
            {togglingUser === u.id
              ? <Loader2 size={11} className="animate-spin" />
              : u.is_active ? <Ban size={11} /> : <RotateCcw size={11} />}
            {u.is_active ? 'Deactivate' : 'Reactivate'}
          </button>
        )}
      </td>
    </tr>
  )

  if (!user?.is_superuser) return null

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-brand-500/20 border border-brand-500/30 rounded-xl flex items-center justify-center">
            <Shield size={20} className="text-brand-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Platform Admin</h1>
            <p className="text-slate-400 text-sm">Superuser view — all tenants &amp; users</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="px-3 py-1.5 bg-red-500/10 border border-red-500/30 rounded-lg text-xs text-red-400 font-semibold">
            SUPERUSER ONLY
          </div>
          <button onClick={() => { bypassNextGets(); load() }} disabled={loading} className="btn-ghost p-2.5">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-surface-800 rounded-xl w-fit">
        {(['overview', 'orgs', 'users', 'support'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={tab === t
              ? 'px-4 py-2 rounded-lg text-sm font-semibold bg-brand-500 text-white flex items-center gap-1.5'
              : 'px-4 py-2 rounded-lg text-sm text-slate-400 hover:text-white transition-colors capitalize flex items-center gap-1.5'}
          >
            {t === 'orgs' ? 'Organisations' : t === 'support' ? 'Support' : t.charAt(0).toUpperCase() + t.slice(1)}
            {t === 'support' && ticketsLoaded && openTicketCount > 0 && (
              <span className="bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full leading-none">{openTicketCount}</span>
            )}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="card p-16 flex justify-center"><Loader2 className="animate-spin text-slate-500" size={32} /></div>
      ) : (
        <>
          {/* Overview Tab */}
          {tab === 'overview' && stats && (
            <div className="space-y-6">
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                {[
                  { label: 'Total Organisations', value: stats.total_orgs, sub: `${stats.active_orgs} active`, icon: Building2, color: 'orange', tabTarget: 'orgs' as const },
                  { label: 'Total Users', value: stats.total_users, sub: `${stats.superusers} superuser(s)`, icon: Users, color: 'blue', tabTarget: 'users' as const },
                  { label: 'Total Platform Revenue', value: formatCurrency(stats.total_revenue), sub: `${stats.total_invoices} paid invoices`, icon: TrendingUp, color: 'green', tabTarget: null },
                ].map((c) => (
                  <button
                    key={c.label}
                    onClick={() => c.tabTarget && setTab(c.tabTarget)}
                    className={`card p-5 text-left transition-all ${c.tabTarget ? 'cursor-pointer hover:border-brand-500/40' : 'cursor-default'}`}
                  >
                    <div className={`w-10 h-10 rounded-xl flex items-center justify-center mb-3 ${
                      c.color === 'orange' ? 'bg-brand-500/15' : c.color === 'blue' ? 'bg-blue-500/15' : 'bg-emerald-500/15'
                    }`}>
                      <c.icon size={20} className={c.color === 'orange' ? 'text-brand-400' : c.color === 'blue' ? 'text-blue-400' : 'text-emerald-400'} />
                    </div>
                    <p className="text-2xl font-bold text-white">{c.value}</p>
                    <p className="text-sm text-slate-400 mt-0.5">{c.label}</p>
                    <p className="text-xs text-slate-500 mt-0.5">{c.sub}</p>
                    {c.tabTarget && <p className="text-xs text-slate-600 mt-1">Click to view →</p>}
                  </button>
                ))}
              </div>

              {/* Plans */}
              <div className="card p-5">
                <h2 className="font-semibold text-white mb-4">Subscription Plans</h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-surface-700">
                        {['Plan Name', 'Price', 'Status'].map((h) => (
                          <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {stats.plans.map((p) => (
                        <tr key={p.name} className="table-row">
                          <td className="px-4 py-3 text-white font-medium">{p.name}</td>
                          <td className="px-4 py-3 font-mono text-brand-400">{formatCurrency(p.price)}</td>
                          <td className="px-4 py-3">
                            {p.is_active ? <span className="badge-green">Active</span> : <span className="badge-slate">Inactive</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* Orgs Tab */}
          {tab === 'orgs' && (
            <div className="card p-0 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-700">
                      {['Organisation', 'Owner', 'Plan', 'Status', 'Members', 'Invoices', 'Revenue', 'Active', 'Actions'].map((h) => (
                        <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {orgs.map((org) => (
                      <tr key={org.id} className="table-row">
                        <td className="px-4 py-3.5">
                          <p className="text-white font-medium">{org.name}</p>
                          <p className="text-xs text-slate-500">{org.currency} · {org.country}</p>
                        </td>
                        <td className="px-4 py-3.5 text-slate-400 text-xs">{org.owner_email ?? '—'}</td>
                        <td className="px-4 py-3.5"><span className="badge-blue">{org.plan}</span></td>
                        <td className="px-4 py-3.5"><span className={SUB_BADGE[org.sub_status] ?? 'badge-slate'}>{org.sub_status}</span></td>
                        <td className="px-4 py-3.5 text-slate-300">{org.member_count}</td>
                        <td className="px-4 py-3.5 text-slate-300">{org.invoice_count}</td>
                        <td className="px-4 py-3.5 font-mono text-brand-400">{formatCurrency(org.total_revenue)}</td>
                        <td className="px-4 py-3.5">
                          {org.is_active
                            ? <CheckCircle size={16} className="text-emerald-400" />
                            : <XCircle size={16} className="text-red-400" />}
                        </td>
                        <td className="px-4 py-3.5">
                          <button
                            onClick={() => handleReseedCoa(org)}
                            disabled={reseedingOrg === org.id}
                            title="Re-seed chart of accounts (idempotent)"
                            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg bg-surface-700 hover:bg-surface-600 text-slate-400 hover:text-white transition-colors disabled:opacity-50"
                          >
                            {reseedingOrg === org.id
                              ? <Loader2 size={11} className="animate-spin" />
                              : <BookOpen size={11} />}
                            Reseed COA
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Users Tab */}
          {tab === 'users' && (
            <div className="card p-0 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-700">
                      {['User', 'Superuser', 'Verified', 'Active', 'Organisations', 'Joined', 'Actions'].map((h) => (
                        <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {userGroups.groups.map(({ owner, subs }) => (
                      <Fragment key={owner.id}>
                        {renderUserRow(owner)}
                        {subs.map((s) => renderUserRow(s, true))}
                      </Fragment>
                    ))}
                    {userGroups.orphans.map((u) => renderUserRow(u))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Support Tab — cross-org ticket inbox */}
          {tab === 'support' && (
            ticketsLoading ? (
              <div className="card p-16 flex justify-center"><Loader2 className="animate-spin text-slate-500" size={28} /></div>
            ) : tickets.length === 0 ? (
              <div className="card p-16 text-center">
                <MessageSquare size={36} className="text-slate-600 mx-auto mb-3" />
                <p className="text-slate-300 font-medium">No support tickets yet</p>
                <p className="text-slate-500 text-sm mt-1">Tickets raised by any organisation land here — and are emailed to support@auditytechnologies.com.</p>
              </div>
            ) : (
              <div className="grid lg:grid-cols-[minmax(0,380px)_1fr] gap-4">
                {/* Ticket list */}
                <div className="card p-0 overflow-hidden divide-y divide-surface-700 max-h-[70vh] overflow-y-auto">
                  {tickets.map((t) => (
                    <button
                      key={t.id}
                      onClick={() => setSelectedId(t.id)}
                      className={`w-full text-left px-4 py-3 transition-colors ${selectedId === t.id ? 'bg-surface-700' : 'hover:bg-surface-800'}`}
                    >
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="text-xs font-mono text-slate-500">{t.ticket_number}</span>
                        <span className={TICKET_STATUS_BADGE[t.status] ?? 'badge-slate'}>{(t.status ?? 'open').replace('_', ' ')}</span>
                      </div>
                      <p className="text-sm text-white font-medium truncate">{t.subject}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs text-slate-400 truncate">{t.organisation_name}</span>
                        <span className={`${TICKET_PRIORITY_BADGE[t.priority] ?? 'badge-slate'} shrink-0`}>{t.priority}</span>
                      </div>
                    </button>
                  ))}
                </div>

                {/* Ticket detail / thread */}
                {selectedTicket ? (
                  <div className="card p-5 flex flex-col max-h-[70vh]">
                    <div className="border-b border-surface-700 pb-3 mb-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <h2 className="text-lg font-semibold text-white">{selectedTicket.subject}</h2>
                          <p className="text-xs text-slate-500 mt-0.5">
                            {selectedTicket.ticket_number} · {selectedTicket.organisation_name} · {selectedTicket.created_by_name} &lt;{selectedTicket.created_by_email}&gt;
                          </p>
                        </div>
                        <button
                          onClick={handleAssignSelf}
                          disabled={ticketBusy}
                          className="btn-ghost text-xs flex items-center gap-1.5 shrink-0 disabled:opacity-50"
                          title="Assign this ticket to yourself"
                        >
                          <UserCheck size={13} /> {selectedTicket.assigned_to_name ? selectedTicket.assigned_to_name : 'Assign to me'}
                        </button>
                      </div>
                      <div className="flex items-center gap-1.5 mt-3 flex-wrap">
                        {TICKET_STATUSES.map((s) => (
                          <button
                            key={s.value}
                            onClick={() => handleTicketStatus(s.value)}
                            disabled={ticketBusy}
                            className={`text-xs px-2.5 py-1 rounded-lg transition-colors disabled:opacity-50 ${
                              selectedTicket.status === s.value ? 'bg-brand-500 text-white' : 'bg-surface-700 text-slate-400 hover:text-white'}`}
                          >
                            {s.label}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Thread */}
                    <div className="flex-1 overflow-y-auto space-y-3 pr-1">
                      <div className="bg-surface-800 border border-surface-700 rounded-lg p-3">
                        <p className="text-xs text-slate-500 mb-1">{selectedTicket.created_by_name} · {new Date(selectedTicket.created_at).toLocaleString()}</p>
                        <p className="text-sm text-slate-200 whitespace-pre-wrap">{selectedTicket.description || '(no description)'}</p>
                      </div>
                      {selectedTicket.comments.map((c) => (
                        <div key={c.id} className="bg-surface-800 border border-surface-700 rounded-lg p-3">
                          <p className="text-xs text-slate-500 mb-1">{c.author_name} · {new Date(c.created_at).toLocaleString()}</p>
                          <p className="text-sm text-slate-200 whitespace-pre-wrap">{c.body}</p>
                        </div>
                      ))}
                    </div>

                    {/* Reply */}
                    <div className="border-t border-surface-700 pt-3 mt-3">
                      <textarea
                        value={reply}
                        onChange={(e) => setReply(e.target.value)}
                        placeholder="Reply to the customer… (they'll be emailed)"
                        rows={3}
                        className="input w-full resize-none"
                      />
                      <div className="flex justify-end mt-2">
                        <button
                          onClick={handleReply}
                          disabled={replying || !reply.trim()}
                          className="btn-primary flex items-center gap-2 disabled:opacity-50"
                        >
                          {replying ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} Send reply
                        </button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="card p-16 flex flex-col items-center justify-center text-center">
                    <MessageSquare size={32} className="text-slate-600 mb-3" />
                    <p className="text-slate-400 text-sm">Select a ticket to view the conversation and reply.</p>
                  </div>
                )}
              </div>
            )
          )}
        </>
      )}
    </div>
  )
}
