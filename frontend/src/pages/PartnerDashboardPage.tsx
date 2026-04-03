import { useEffect, useState } from 'react'
import {
  GraduationCap, Users, TrendingUp, Plus, Trash2, Loader2,
  Building2, DollarSign, CheckCircle, XCircle, RefreshCw,
  BarChart3, FileBarChart2, ExternalLink,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useNavigate } from 'react-router-dom'
import { partnerApi, orgApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'

interface PartnerProfile {
  id: string
  tier: 'starter' | 'pro' | 'agency'
  firm_name: string
  max_clients: number
  commission_rate: string
  total_commission_earned: string
  white_label_reports: boolean
  consolidated_reporting: boolean
  is_active: boolean
  referral_code: string
}

interface ClientLink {
  id: string
  organisation: string
  org_name: string
  org_currency: string
  is_referred: boolean
  commission_earned: string
  notes: string
  is_active: boolean
  linked_at: string
}

interface ConsolidatedClient {
  link_id: string
  org_id: string
  org_name: string
  org_currency: string
  plan: string
  revenue_this_month: number
  outstanding_balance: number
  overdue_count: number
  total_customers: number
  total_products: number
  linked_at: string
}

interface ConsolidatedData {
  clients: ConsolidatedClient[]
  totals: {
    total_revenue: number
    total_outstanding: number
    total_customers: number
    total_products: number
    client_count: number
  }
}

const TIER_LABELS: Record<string, string> = {
  starter: 'Partner Starter',
  pro: 'Partner Pro',
  agency: 'Partner Agency',
}

const TIER_COLORS: Record<string, string> = {
  starter: 'text-slate-300 bg-slate-500/10',
  pro: 'text-brand-300 bg-brand-500/10',
  agency: 'text-purple-300 bg-purple-500/10',
}

function fmtMoney(v: string | number) {
  return '₦' + parseFloat(String(v)).toLocaleString('en-NG', { minimumFractionDigits: 2 })
}

function fmtDate(dt: string) {
  return new Date(dt).toLocaleDateString('en-NG', { day: '2-digit', month: 'short', year: 'numeric' })
}

export default function PartnerDashboardPage() {
  const navigate = useNavigate()
  const { setOrganisation, setOrganisations } = useAuthStore()
  const [profile, setProfile] = useState<PartnerProfile | null>(null)
  const [clients, setClients] = useState<ClientLink[]>([])
  const [consolidated, setConsolidated] = useState<ConsolidatedData | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'clients' | 'consolidated'>('clients')
  const [managingBooks, setManagingBooks] = useState<string | null>(null)

  // Add client form
  const [orgId, setOrgId] = useState('')
  const [notes, setNotes] = useState('')
  const [isReferred, setIsReferred] = useState(true)
  const [adding, setAdding] = useState(false)
  const [removing, setRemoving] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [profileRes, clientsRes] = await Promise.allSettled([
        partnerApi.profile(),
        partnerApi.clients(),
      ])
      if (profileRes.status === 'fulfilled') setProfile(profileRes.value.data)
      if (clientsRes.status === 'fulfilled') setClients(clientsRes.value.data.results ?? clientsRes.value.data)
    } finally {
      setLoading(false)
    }
  }

  const loadConsolidated = async () => {
    try {
      const res = await partnerApi.consolidated()
      setConsolidated(res.data)
    } catch {
      toast.error('Failed to load consolidated report')
    }
  }

  useEffect(() => { load() }, [])

  useEffect(() => {
    if (tab === 'consolidated' && !consolidated) loadConsolidated()
  }, [tab]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleAddClient = async () => {
    if (!orgId.trim()) { toast.error('Enter an Organisation ID'); return }
    setAdding(true)
    try {
      const res = await partnerApi.addClient({ organisation_id: orgId.trim(), notes, is_referred: isReferred })
      setClients((prev) => [res.data, ...prev])
      setOrgId('')
      setNotes('')
      toast.success('Client linked successfully')
    } catch (err: any) {
      const msg = err?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Failed to add client')
    } finally {
      setAdding(false)
    }
  }

  const handleManageBooks = async (c: ClientLink) => {
    setManagingBooks(c.id)
    try {
      const { data } = await orgApi.list()
      const orgs: any[] = data.results ?? data
      const clientOrg = orgs.find((o: any) => o.id === c.organisation)
      if (!clientOrg) { toast.error('Client organisation not found — ensure you have been provisioned as a member'); return }
      setOrganisations(orgs)   // keep store fresh so "Exit Client View" can find partner's own org
      setOrganisation(clientOrg)
      navigate('/dashboard')
    } catch {
      toast.error('Failed to switch to client organisation')
    } finally {
      setManagingBooks(null)
    }
  }

  const handleRemove = async (clientId: string) => {
    if (!confirm('Remove this client from your portfolio?')) return
    setRemoving(clientId)
    try {
      await partnerApi.removeClient(clientId)
      setClients((prev) => prev.filter((c) => c.id !== clientId))
      toast.success('Client removed')
    } catch {
      toast.error('Failed to remove client')
    } finally {
      setRemoving(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={24} className="animate-spin text-brand-400" />
      </div>
    )
  }

  if (!profile) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <GraduationCap size={40} className="text-slate-600" />
        <p className="text-slate-400 text-sm">No partner profile found. Subscribe to a Partner plan to get started.</p>
      </div>
    )
  }

  const usedClients = clients.filter((c) => c.is_active).length
  const maxClients = profile.max_clients >= 999999 ? null : profile.max_clients

  return (
    <div className="space-y-6 max-w-5xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <GraduationCap size={22} className="text-purple-400" />
            Partner Dashboard
          </h1>
          <p className="text-slate-400 text-sm mt-0.5">Manage your SMB client portfolio and track commissions.</p>
        </div>
        <button onClick={load} className="btn-ghost text-xs flex items-center gap-1.5 text-slate-400">
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {/* Profile summary tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="card space-y-1">
          <p className="text-xs text-slate-500">Tier</p>
          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${TIER_COLORS[profile.tier]}`}>
            {TIER_LABELS[profile.tier]}
          </span>
        </div>
        <div className="card space-y-1">
          <p className="text-xs text-slate-500 flex items-center gap-1"><Users size={11} /> Clients</p>
          <p className="text-xl font-bold text-white">
            {usedClients}{maxClients ? <span className="text-slate-500 text-sm font-normal"> / {maxClients}</span> : null}
          </p>
        </div>
        <div className="card space-y-1">
          <p className="text-xs text-slate-500 flex items-center gap-1"><DollarSign size={11} /> Commission Rate</p>
          <p className="text-xl font-bold text-white">{profile.commission_rate}%</p>
        </div>
        <div className="card space-y-1">
          <p className="text-xs text-slate-500 flex items-center gap-1"><TrendingUp size={11} /> Total Earned</p>
          <p className="text-xl font-bold text-white">{fmtMoney(profile.total_commission_earned)}</p>
        </div>
      </div>

      {/* Feature flags + referral code */}
      <div className="flex flex-wrap items-center gap-2">
        <span className={`flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full ${profile.white_label_reports ? 'bg-green-500/10 text-green-400' : 'bg-slate-700/50 text-slate-500'}`}>
          {profile.white_label_reports ? <CheckCircle size={11} /> : <XCircle size={11} />} White-label Reports
        </span>
        <span className={`flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full ${profile.consolidated_reporting ? 'bg-green-500/10 text-green-400' : 'bg-slate-700/50 text-slate-500'}`}>
          {profile.consolidated_reporting ? <CheckCircle size={11} /> : <XCircle size={11} />} Consolidated Reporting
        </span>
        {profile.referral_code && (
          <button
            onClick={() => { navigator.clipboard.writeText(profile.referral_code); toast.success('Referral code copied!') }}
            className="flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 transition-colors"
            title="Share this code with clients when they register — proves they were referred by you"
          >
            Referral Code: <span className="font-mono">{profile.referral_code}</span>
            <ExternalLink size={10} />
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-surface-700">
        {([['clients', 'My Clients', Users], ['consolidated', 'Consolidated Report', BarChart3]] as const).map(([key, label, Icon]) => (
          <button
            key={key}
            onClick={() => setTab(key as 'clients' | 'consolidated')}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === key ? 'border-brand-500 text-brand-400' : 'border-transparent text-slate-400 hover:text-white'
            }`}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {tab === 'clients' && (
        <div className="space-y-4">
          {/* Add client form */}
          <div className="card space-y-3">
            <p className="text-sm font-semibold text-white flex items-center gap-2"><Plus size={14} /> Link a Client Organisation</p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="sm:col-span-2">
                <label className="label">Organisation ID (UUID)</label>
                <input
                  className="input"
                  placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                  value={orgId}
                  onChange={(e) => setOrgId(e.target.value)}
                />
              </div>
              <div>
                <label className="label">Notes (optional)</label>
                <input
                  className="input"
                  placeholder="e.g. Lagos retail client"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                />
              </div>
            </div>
            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={isReferred}
                  onChange={(e) => setIsReferred(e.target.checked)}
                  className="rounded border-surface-600 bg-surface-800 text-brand-500 focus:ring-brand-500"
                />
                Mark as referred (earn commission)
              </label>
              <button onClick={handleAddClient} disabled={adding} className="btn-primary text-sm flex items-center gap-1.5">
                {adding ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />} Add Client
              </button>
            </div>
          </div>

          {/* Client list */}
          {clients.length === 0 ? (
            <div className="card text-center py-10">
              <Building2 size={32} className="text-slate-600 mx-auto mb-2" />
              <p className="text-slate-400 text-sm">No clients linked yet. Add your first client above.</p>
            </div>
          ) : (
            <div className="card overflow-hidden p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700">
                    <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Organisation</th>
                    <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Linked</th>
                    <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Commission Earned</th>
                    <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Status</th>
                    <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Notes</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {clients.map((c) => (
                    <tr key={c.id} className="border-b border-surface-700/50 last:border-0 hover:bg-surface-700/20">
                      <td className="px-4 py-3 text-white font-medium">{c.org_name || c.organisation}</td>
                      <td className="px-4 py-3 text-slate-400">{fmtDate(c.linked_at)}</td>
                      <td className="px-4 py-3 text-green-400 font-medium">{fmtMoney(c.commission_earned)}</td>
                      <td className="px-4 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${c.is_active ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
                          {c.is_active ? 'Active' : 'Inactive'}
                        </span>
                        {c.is_referred && (
                          <span className="ml-1.5 text-xs px-2 py-0.5 rounded-full bg-brand-500/10 text-brand-400">Referred</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-400 text-xs">{c.notes || '—'}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          {c.is_active && (
                            <button
                              onClick={() => handleManageBooks(c)}
                              disabled={managingBooks === c.id}
                              className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg text-purple-400 hover:bg-purple-400/10 transition-colors"
                              title="Switch to this client's books"
                            >
                              {managingBooks === c.id ? <Loader2 size={11} className="animate-spin" /> : <ExternalLink size={11} />}
                              Manage Books
                            </button>
                          )}
                          <button
                            onClick={() => handleRemove(c.id)}
                            disabled={removing === c.id}
                            className="p-1.5 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-400/10 transition-colors"
                          >
                            {removing === c.id ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === 'consolidated' && (
        <div className="space-y-4">
          {!profile.consolidated_reporting ? (
            <div className="card text-center py-10">
              <FileBarChart2 size={32} className="text-slate-600 mx-auto mb-2" />
              <p className="text-slate-400 text-sm">Consolidated reporting is available on Partner Pro and Agency plans.</p>
            </div>
          ) : !consolidated ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 size={22} className="animate-spin text-brand-400" />
            </div>
          ) : (
            <div className="space-y-4">
              {/* Summary tiles */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="card space-y-1">
                  <p className="text-xs text-slate-500">Total Clients</p>
                  <p className="text-2xl font-bold text-white">{consolidated.totals.client_count}</p>
                </div>
                <div className="card space-y-1">
                  <p className="text-xs text-slate-500">Revenue This Month</p>
                  <p className="text-2xl font-bold text-white">{fmtMoney(consolidated.totals.total_revenue)}</p>
                </div>
                <div className="card space-y-1">
                  <p className="text-xs text-slate-500">Outstanding Balance</p>
                  <p className="text-2xl font-bold text-red-400">{fmtMoney(consolidated.totals.total_outstanding)}</p>
                </div>
                <div className="card space-y-1">
                  <p className="text-xs text-slate-500">Total Customers</p>
                  <p className="text-2xl font-bold text-white">{consolidated.totals.total_customers}</p>
                </div>
              </div>

              {/* Per-client breakdown */}
              <div className="card overflow-hidden p-0">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-700">
                      <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Organisation</th>
                      <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Plan</th>
                      <th className="text-right text-xs text-slate-500 font-medium px-4 py-3">Revenue (Month)</th>
                      <th className="text-right text-xs text-slate-500 font-medium px-4 py-3">Outstanding</th>
                      <th className="text-right text-xs text-slate-500 font-medium px-4 py-3">Overdue</th>
                      <th className="text-right text-xs text-slate-500 font-medium px-4 py-3">Customers</th>
                      <th className="text-right text-xs text-slate-500 font-medium px-4 py-3">Products</th>
                    </tr>
                  </thead>
                  <tbody>
                    {consolidated.clients.map((c) => (
                      <tr key={c.link_id} className="border-b border-surface-700/50 last:border-0 hover:bg-surface-700/20">
                        <td className="px-4 py-3">
                          <p className="text-white font-medium">{c.org_name}</p>
                          <p className="text-xs text-slate-500">{fmtDate(c.linked_at)}</p>
                        </td>
                        <td className="px-4 py-3 text-slate-300 text-xs">{c.plan || '—'}</td>
                        <td className="px-4 py-3 text-right text-green-400 font-medium">{fmtMoney(c.revenue_this_month)}</td>
                        <td className="px-4 py-3 text-right">
                          <span className={c.outstanding_balance > 0 ? 'text-red-400 font-medium' : 'text-slate-500'}>
                            {fmtMoney(c.outstanding_balance)}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right">
                          {c.overdue_count > 0
                            ? <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 font-medium">{c.overdue_count}</span>
                            : <span className="text-slate-600">—</span>
                          }
                        </td>
                        <td className="px-4 py-3 text-right text-slate-300">{c.total_customers}</td>
                        <td className="px-4 py-3 text-right text-slate-300">{c.total_products}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
