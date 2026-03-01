import { useEffect, useState } from 'react'
import { Shield, Users, Building2, RefreshCw, Loader2, CheckCircle, XCircle, TrendingUp } from 'lucide-react'
import toast from 'react-hot-toast'
import { platformAdminApi } from '@/services/api'
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
  created_at: string; orgs: { name: string; role: string }[]
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
      setUsers(usersRes.data)
    } catch {
      toast.error('Failed to load platform data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

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
          <button onClick={load} disabled={loading} className="btn-ghost p-2.5">
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
                  { label: 'Total Organisations', value: stats.total_orgs, sub: `${stats.active_orgs} active`, icon: Building2, color: 'orange' },
                  { label: 'Total Users', value: stats.total_users, sub: `${stats.superusers} superuser(s)`, icon: Users, color: 'blue' },
                  { label: 'Total Platform Revenue', value: formatCurrency(stats.total_revenue), sub: `${stats.total_invoices} paid invoices`, icon: TrendingUp, color: 'green' },
                ].map((c) => (
                  <div key={c.label} className="card p-5">
                    <div className={`w-10 h-10 rounded-xl flex items-center justify-center mb-3 ${
                      c.color === 'orange' ? 'bg-brand-500/15' : c.color === 'blue' ? 'bg-blue-500/15' : 'bg-emerald-500/15'
                    }`}>
                      <c.icon size={20} className={c.color === 'orange' ? 'text-brand-400' : c.color === 'blue' ? 'text-blue-400' : 'text-emerald-400'} />
                    </div>
                    <p className="text-2xl font-bold text-white">{c.value}</p>
                    <p className="text-sm text-slate-400 mt-0.5">{c.label}</p>
                    <p className="text-xs text-slate-500 mt-0.5">{c.sub}</p>
                  </div>
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
                      {['Organisation', 'Owner', 'Plan', 'Status', 'Members', 'Invoices', 'Revenue', 'Active'].map((h) => (
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
                      {['User', 'Superuser', 'Verified', 'Active', 'Organisations', 'Joined'].map((h) => (
                        <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={u.id} className="table-row">
                        <td className="px-4 py-3.5">
                          <p className="text-white font-medium">{u.first_name} {u.last_name}</p>
                          <p className="text-xs text-slate-500">{u.email}</p>
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
                      </tr>
                    ))}
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
