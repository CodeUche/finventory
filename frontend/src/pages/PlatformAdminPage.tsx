import { Fragment, useEffect, useMemo, useState } from 'react'
import { Shield, Users, Building2, RefreshCw, Loader2, CheckCircle, XCircle, TrendingUp, BookOpen, Ban, RotateCcw } from 'lucide-react'
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

const SUB_BADGE: Record<string, string> = {
  active: 'badge-green', trialing: 'badge-blue', canceled: 'badge-red',
  none: 'badge-slate', past_due: 'badge-red',
}

export default function PlatformAdminPage() {
  const { user } = useAuthStore()
  const navigate = useNavigate()
  const [stats, setStats] = useState<Stats | null>(null)
  const [orgs, setOrgs] = useState<OrgRow[]>([])
  const [users, setUsers] = useState<PlatformUser[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'overview' | 'orgs' | 'users'>('overview')
  const [reseedingOrg, setReseedingOrg] = useState<string | null>(null)
  const [togglingUser, setTogglingUser] = useState<string | null>(null)

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

  const handleReseedCoa = async (org: OrgRow) => {
    if (!confirm(`Reseed chart of accounts for "${org.name}"?\n\nThis is safe and idempotent — it only adds missing accounts, never overwrites existing ones.`)) return
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
    if (!confirm(`${nextActive ? 'Reactivate' : 'Deactivate'} ${target.email}?${!nextActive && target.orgs.some(o => o.role === 'owner') ? '\n\nThis cascades to all sub-accounts in their organisation(s).' : ''}`)) return
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
        {(['overview', 'orgs', 'users'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={tab === t
              ? 'px-4 py-2 rounded-lg text-sm font-semibold bg-brand-500 text-white'
              : 'px-4 py-2 rounded-lg text-sm text-slate-400 hover:text-white transition-colors capitalize'}
          >
            {t === 'orgs' ? 'Organisations' : t.charAt(0).toUpperCase() + t.slice(1)}
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
        </>
      )}
    </div>
  )
}
