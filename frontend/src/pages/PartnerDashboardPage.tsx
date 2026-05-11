import { useEffect, useState } from 'react'
import {
  GraduationCap, Users, TrendingUp, Trash2, Loader2,
  Building2, DollarSign, CheckCircle, XCircle, RefreshCw,
  BarChart3, FileBarChart2, ExternalLink, Send, Clock,
  ShieldCheck, Key, ChevronRight, LockKeyhole,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { useNavigate } from 'react-router-dom'
import { partnerApi, orgApi, bypassNextGets } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import type { PartnerProfile, PartnerClientLink, PartnerAccessRequest, PartnerAccessRequestStatus } from '@/types'

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

const STATUS_STYLES: Record<PartnerAccessRequestStatus, { label: string; cls: string; Icon: React.ElementType }> = {
  pending:   { label: 'Pending',   cls: 'bg-amber-500/10 text-amber-400',  Icon: Clock },
  approved:  { label: 'Approved',  cls: 'bg-green-500/10 text-green-400',  Icon: CheckCircle },
  rejected:  { label: 'Rejected',  cls: 'bg-red-500/10 text-red-400',      Icon: XCircle },
  withdrawn: { label: 'Withdrawn', cls: 'bg-slate-500/10 text-slate-400',  Icon: XCircle },
}

function fmtMoney(v: string | number) {
  return '₦' + parseFloat(String(v)).toLocaleString('en-NG', { minimumFractionDigits: 2 })
}

function fmtDate(dt: string) {
  return new Date(dt).toLocaleDateString('en-NG', { day: '2-digit', month: 'short', year: 'numeric' })
}

type Tab = 'clients' | 'requests' | 'consolidated'

export default function PartnerDashboardPage() {
  const navigate = useNavigate()
  const { setOrganisation, setOrganisations } = useAuthStore()
  const [profile, setProfile] = useState<PartnerProfile | null>(null)
  const [clients, setClients] = useState<PartnerClientLink[]>([])
  const [accessRequests, setAccessRequests] = useState<PartnerAccessRequest[]>([])
  const [consolidated, setConsolidated] = useState<ConsolidatedData | null>(null)
  const [loading, setLoading] = useState(true)
  const [subscriptionExpired, setSubscriptionExpired] = useState(false)
  const [tab, setTab] = useState<Tab>('clients')
  const [managingBooks, setManagingBooks] = useState<string | null>(null)

  // Request access form
  const [reqOrgId, setReqOrgId] = useState('')
  const [reqMessage, setReqMessage] = useState('')
  const [requesting, setRequesting] = useState(false)

  // Accept invite token form
  const [inviteToken, setInviteToken] = useState('')
  const [acceptingToken, setAcceptingToken] = useState(false)

  const [removing, setRemoving] = useState<string | null>(null)
  const [withdrawing, setWithdrawing] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setSubscriptionExpired(false)
    try {
      const [profileRes, clientsRes, reqsRes] = await Promise.allSettled([
        partnerApi.profile(),
        partnerApi.clients(),
        partnerApi.listAccessRequests(),
      ])
      if (profileRes.status === 'fulfilled') setProfile(profileRes.value.data)
      if (clientsRes.status === 'fulfilled') {
        setClients(clientsRes.value.data.results ?? clientsRes.value.data)
      } else if (clientsRes.reason?.response?.status === 403) {
        setSubscriptionExpired(true)
      }
      if (reqsRes.status === 'fulfilled') {
        setAccessRequests(reqsRes.value.data.results ?? reqsRes.value.data)
      }
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

  const handleRequestAccess = async () => {
    if (subscriptionExpired) { navigate('/billing'); return }
    if (!reqOrgId.trim()) { toast.error('Enter an Organisation ID'); return }
    setRequesting(true)
    try {
      const res = await partnerApi.requestAccess({
        organisation_id: reqOrgId.trim(),
        message: reqMessage.trim() || undefined,
      })
      setAccessRequests((prev) => [res.data, ...prev.filter((r) => r.id !== res.data.id)])
      setReqOrgId('')
      setReqMessage('')
      toast.success('Access request sent — the organisation owner will be notified.')
      setTab('requests')
    } catch (err: any) {
      const msg = err?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Failed to send request')
    } finally {
      setRequesting(false)
    }
  }

  const handleAcceptToken = async () => {
    if (subscriptionExpired) { navigate('/billing'); return }
    if (!inviteToken.trim()) { toast.error('Paste the invite token'); return }
    setAcceptingToken(true)
    try {
      await partnerApi.acceptInvite(inviteToken.trim())
      toast.success('Invite accepted — you now have access to this organisation.')
      setInviteToken('')
      await load()
      setTab('clients')
    } catch (err: any) {
      const msg = err?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Invalid or expired token')
    } finally {
      setAcceptingToken(false)
    }
  }

  const handleManageBooks = async (c: PartnerClientLink) => {
    setManagingBooks(c.id)
    try {
      const { data } = await orgApi.list()
      const orgs: any[] = data.results ?? data
      const clientOrg = orgs.find((o: any) => o.id === c.organisation)
      if (!clientOrg) {
        toast.error('Organisation not found in your membership list — contact the client to check your access.')
        return
      }
      setOrganisations(orgs)
      setOrganisation(clientOrg)
      navigate('/dashboard')
    } catch {
      toast.error('Failed to switch to client organisation')
    } finally {
      setManagingBooks(null)
    }
  }

  const handleRemove = async (clientId: string) => {
    if (!confirm('Remove this client from your portfolio? This will also revoke your access to their organisation.')) return
    setRemoving(clientId)
    try {
      await partnerApi.removeClient(clientId)
      setClients((prev) => prev.filter((c) => c.id !== clientId))
      toast.success('Client removed and access revoked')
    } catch {
      toast.error('Failed to remove client')
    } finally {
      setRemoving(null)
    }
  }

  const handleWithdraw = async (reqId: string) => {
    if (!confirm('Withdraw this access request?')) return
    setWithdrawing(reqId)
    try {
      await partnerApi.withdrawRequest(reqId)
      setAccessRequests((prev) => prev.map((r) =>
        r.id === reqId ? { ...r, status: 'withdrawn' as PartnerAccessRequestStatus } : r
      ))
      toast.success('Request withdrawn')
    } catch (err: any) {
      const msg = err?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : 'Failed to withdraw request')
    } finally {
      setWithdrawing(null)
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

  const activeClients = clients.filter((c) => c.is_active)
  const maxClients = profile.max_clients >= 999999 ? null : profile.max_clients
  const pendingCount = accessRequests.filter((r) => r.status === 'pending').length

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
        <button onClick={() => { bypassNextGets(); load() }} className="btn-ghost text-xs flex items-center gap-1.5 text-slate-400">
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
            {activeClients.length}{maxClients ? <span className="text-slate-500 text-sm font-normal"> / {maxClients}</span> : null}
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
          >
            Referral Code: <span className="font-mono">{profile.referral_code}</span>
            <ExternalLink size={10} />
          </button>
        )}
      </div>

      {/* Subscription expired paywall */}
      {subscriptionExpired && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-6 flex flex-col sm:flex-row items-center gap-5">
          <div className="shrink-0 w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center">
            <LockKeyhole size={22} className="text-red-400" />
          </div>
          <div className="flex-1 text-center sm:text-left">
            <p className="text-white font-semibold text-sm">Your partner subscription has expired</p>
            <p className="text-slate-400 text-xs mt-1">
              Your free trial has ended or your subscription is no longer active. Subscribe to a Partner plan to continue
              managing client organisations and accessing the dashboard features.
            </p>
          </div>
          <button
            onClick={() => navigate('/billing')}
            className="btn-primary shrink-0 text-sm px-5"
          >
            Subscribe to Partner Plan
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-surface-700">
        {([
          ['clients', 'My Clients', Users, 0],
          ['requests', 'Access Requests', ShieldCheck, pendingCount],
          ['consolidated', 'Consolidated Report', BarChart3, 0],
        ] as const).map(([key, label, Icon, badge]) => (
          <button
            key={key}
            onClick={() => setTab(key as Tab)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === key ? 'border-brand-500 text-brand-400' : 'border-transparent text-slate-400 hover:text-white'
            }`}
          >
            <Icon size={14} /> {label}
            {badge > 0 && (
              <span className="ml-1 bg-amber-500 text-black text-[10px] font-bold px-1.5 py-0.5 rounded-full leading-none">
                {badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── My Clients tab ── */}
      {tab === 'clients' && (
        <div className="space-y-4">
          {/* Request access form */}
          <div className="card space-y-3">
            <p className="text-sm font-semibold text-white flex items-center gap-2"><Send size={14} /> Request Access to a Client Organisation</p>
            <p className="text-xs text-slate-400">
              Enter the Organisation ID of a client you want to manage. The owner will receive a notification and can approve or reject your request.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="sm:col-span-2">
                <label className="label">Organisation ID (UUID)</label>
                <input
                  className="input"
                  placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                  value={reqOrgId}
                  onChange={(e) => setReqOrgId(e.target.value)}
                />
              </div>
              <div>
                <label className="label">Message (optional)</label>
                <input
                  className="input"
                  placeholder="e.g. Referred by Ahmed"
                  value={reqMessage}
                  onChange={(e) => setReqMessage(e.target.value)}
                  maxLength={300}
                />
              </div>
            </div>
            <div className="flex items-center justify-between">
              <div className="text-xs text-slate-500">The client org owner must approve your request before you gain access.</div>
              <button onClick={handleRequestAccess} disabled={requesting} className="btn-primary text-sm flex items-center gap-1.5">
                {requesting ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />} Send Request
              </button>
            </div>
          </div>

          {/* Accept invite token */}
          <div className="card space-y-3 border border-purple-500/20 bg-purple-500/5">
            <p className="text-sm font-semibold text-purple-300 flex items-center gap-2"><Key size={14} /> Accept an Invite Token</p>
            <p className="text-xs text-slate-400">
              If a client sent you an invite token, paste it here to instantly gain access without waiting for approval.
            </p>
            <div className="flex gap-2">
              <input
                className="input flex-1"
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                value={inviteToken}
                onChange={(e) => setInviteToken(e.target.value)}
              />
              <button onClick={handleAcceptToken} disabled={acceptingToken} className="btn-primary text-sm flex items-center gap-1.5 shrink-0">
                {acceptingToken ? <Loader2 size={13} className="animate-spin" /> : <ChevronRight size={13} />} Accept
              </button>
            </div>
          </div>

          {/* Active client list */}
          {activeClients.length === 0 ? (
            <div className="card text-center py-10">
              <Building2 size={32} className="text-slate-600 mx-auto mb-2" />
              <p className="text-slate-400 text-sm">No approved clients yet.</p>
              <p className="text-slate-500 text-xs mt-1">Send an access request above or ask a client to generate an invite token for you.</p>
            </div>
          ) : (
            <div className="card overflow-hidden p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700">
                    <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Organisation</th>
                    <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Linked</th>
                    <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Commission Earned</th>
                    <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Notes</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {activeClients.map((c) => (
                    <tr key={c.id} className="border-b border-surface-700/50 last:border-0 hover:bg-surface-700/20">
                      <td className="px-4 py-3 text-white font-medium">{c.org_name || c.organisation}</td>
                      <td className="px-4 py-3 text-slate-400">{fmtDate(c.linked_at)}</td>
                      <td className="px-4 py-3 text-green-400 font-medium">{fmtMoney(c.commission_earned)}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs">{c.notes || '—'}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => handleManageBooks(c)}
                            disabled={managingBooks === c.id}
                            className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg text-purple-400 hover:bg-purple-400/10 transition-colors"
                          >
                            {managingBooks === c.id ? <Loader2 size={11} className="animate-spin" /> : <ExternalLink size={11} />}
                            Manage Books
                          </button>
                          <button
                            onClick={() => handleRemove(c.id)}
                            disabled={removing === c.id}
                            className="p-1.5 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-400/10 transition-colors"
                            title="Remove client and revoke access"
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

      {/* ── Access Requests tab ── */}
      {tab === 'requests' && (
        <div className="space-y-4">
          {accessRequests.length === 0 ? (
            <div className="card text-center py-10">
              <ShieldCheck size={32} className="text-slate-600 mx-auto mb-2" />
              <p className="text-slate-400 text-sm">No access requests yet.</p>
              <p className="text-slate-500 text-xs mt-1">Requests you send to client organisations will appear here.</p>
            </div>
          ) : (
            <div className="card overflow-hidden p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700">
                    <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Organisation</th>
                    <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Status</th>
                    <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Message</th>
                    <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Date</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {accessRequests.map((req) => {
                    const s = STATUS_STYLES[req.status] || STATUS_STYLES.pending
                    return (
                      <tr key={req.id} className="border-b border-surface-700/50 last:border-0 hover:bg-surface-700/20">
                        <td className="px-4 py-3 text-white font-medium">{req.org_name}</td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${s.cls}`}>
                            <s.Icon size={10} /> {s.label}
                          </span>
                          {req.status === 'rejected' && req.rejection_reason && (
                            <p className="text-xs text-red-400/70 mt-0.5 italic">{req.rejection_reason}</p>
                          )}
                        </td>
                        <td className="px-4 py-3 text-slate-400 text-xs max-w-[180px] truncate">
                          {req.request_message || '—'}
                        </td>
                        <td className="px-4 py-3 text-slate-400 text-xs">{fmtDate(req.created_at)}</td>
                        <td className="px-4 py-3">
                          {(req.status === 'pending' || req.status === 'approved') && (
                            <button
                              onClick={() => handleWithdraw(req.id)}
                              disabled={withdrawing === req.id}
                              className="text-xs px-2 py-1 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-400/10 transition-colors"
                            >
                              {withdrawing === req.id ? <Loader2 size={12} className="animate-spin" /> : 'Withdraw'}
                            </button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Consolidated Report tab ── */}
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
