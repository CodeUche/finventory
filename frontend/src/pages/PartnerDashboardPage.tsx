import { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  GraduationCap, Users, TrendingUp, Trash2, Loader2, Building2,
  DollarSign, CheckCircle, XCircle, RefreshCw, ExternalLink, Send,
  Clock, ShieldCheck, Key, ChevronRight, ChevronDown, ChevronUp,
  LockKeyhole, Search, UserPlus, BarChart3, X, Copy,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { partnerApi, orgApi, bypassNextGets } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import type {
  PartnerProfile, PartnerClientLink, PartnerAccessRequest, PartnerAccessRequestStatus,
} from '@/types'

// ── Types ────────────────────────────────────────────────────────────────────

interface ConsolidatedClient {
  link_id: string
  org_id: string
  org_name: string
  plan: string
  revenue_this_month: number
  outstanding_balance: number
  overdue_count: number
}

interface ConsolidatedData {
  clients: ConsolidatedClient[]
  totals: { total_revenue: number; total_outstanding: number; total_customers: number; client_count: number }
}

// ── Constants ────────────────────────────────────────────────────────────────

const TIER_META: Record<string, { label: string; cls: string }> = {
  starter: { label: 'Starter',  cls: 'bg-slate-500/15 text-slate-300' },
  pro:     { label: 'Pro',      cls: 'bg-brand-500/15 text-brand-300' },
  agency:  { label: 'Agency',   cls: 'bg-purple-500/15 text-purple-300' },
}

const STATUS_META: Record<PartnerAccessRequestStatus, { label: string; cls: string; Icon: React.ElementType }> = {
  pending:   { label: 'Pending',   cls: 'bg-amber-500/10 text-amber-400',  Icon: Clock },
  approved:  { label: 'Approved',  cls: 'bg-green-500/10 text-green-400',  Icon: CheckCircle },
  rejected:  { label: 'Rejected',  cls: 'bg-red-500/10 text-red-400',      Icon: XCircle },
  withdrawn: { label: 'Withdrawn', cls: 'bg-slate-500/10 text-slate-400',  Icon: XCircle },
}

function fmtMoney(v: string | number) {
  const n = parseFloat(String(v))
  if (isNaN(n)) return '₦—'
  return '₦' + n.toLocaleString('en-NG', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function fmtDate(dt: string) {
  return new Date(dt).toLocaleDateString('en-NG', { day: '2-digit', month: 'short', year: 'numeric' })
}

// ── KPI Tile ─────────────────────────────────────────────────────────────────

function KpiTile({
  label, value, sub, icon: Icon, accent,
}: { label: string; value: string | number; sub?: string; icon: React.ElementType; accent?: string }) {
  return (
    <div className="card space-y-2 py-4">
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        <Icon size={12} />
        <span>{label}</span>
      </div>
      <p className={`text-2xl font-bold leading-none ${accent ?? 'text-white'}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500">{sub}</p>}
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function PartnerDashboardPage() {
  const navigate = useNavigate()
  const { setOrganisation, setOrganisations } = useAuthStore()

  const [profile, setProfile]               = useState<PartnerProfile | null>(null)
  const [clients, setClients]               = useState<PartnerClientLink[]>([])
  const [accessRequests, setAccessRequests] = useState<PartnerAccessRequest[]>([])
  const [consolidated, setConsolidated]     = useState<ConsolidatedData | null>(null)
  const [commission, setCommission]         = useState<{ available_balance: number; pending_balance: number } | null>(null)

  const [loading, setLoading]                     = useState(true)
  const [subscriptionExpired, setSubscriptionExpired] = useState(false)

  // UI state
  const [search, setSearch]           = useState('')
  const [reqPanelOpen, setReqPanelOpen] = useState(true)
  const [showAllReqs, setShowAllReqs] = useState(false)
  const [addClientOpen, setAddClientOpen] = useState(false)
  const [addClientTab, setAddClientTab]   = useState<'request' | 'token'>('request')

  // Form state
  const [reqOrgId, setReqOrgId]     = useState('')
  const [reqMessage, setReqMessage] = useState('')
  const [requesting, setRequesting] = useState(false)
  const [inviteToken, setInviteToken]   = useState('')
  const [acceptingToken, setAcceptingToken] = useState(false)

  // Row actions
  const [removing, setRemoving]       = useState<string | null>(null)
  const [withdrawing, setWithdrawing] = useState<string | null>(null)
  const [managingBooks, setManagingBooks] = useState<string | null>(null)

  // ── Load ──────────────────────────────────────────────────────────────────

  const load = async () => {
    setLoading(true)
    setSubscriptionExpired(false)
    try {
      const [profileRes, clientsRes, reqsRes, consolidatedRes, commissionRes] = await Promise.allSettled([
        partnerApi.profile(),
        partnerApi.clients(),
        partnerApi.listAccessRequests(),
        partnerApi.consolidated(),
        partnerApi.commission(),
      ])
      if (profileRes.status === 'fulfilled')
        setProfile(profileRes.value.data)
      if (clientsRes.status === 'fulfilled')
        setClients(clientsRes.value.data.results ?? clientsRes.value.data)
      else if (clientsRes.reason?.response?.status === 403)
        setSubscriptionExpired(true)
      if (reqsRes.status === 'fulfilled')
        setAccessRequests(reqsRes.value.data.results ?? reqsRes.value.data)
      if (consolidatedRes.status === 'fulfilled')
        setConsolidated(consolidatedRes.value.data)
      if (commissionRes.status === 'fulfilled')
        setCommission(commissionRes.value.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // Restore partner's own org context if we navigated back from managing a client's books.
    // handleManageBooks saves the own org to sessionStorage before switching X-Organisation-ID.
    const saved = sessionStorage.getItem('audity_partner_own_org')
    if (saved) {
      try {
        const ownOrg = JSON.parse(saved)
        setOrganisation(ownOrg)
      } catch {}
      sessionStorage.removeItem('audity_partner_own_org')
    }
    load()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Derived data ──────────────────────────────────────────────────────────

  const activeClients = useMemo(() => clients.filter((c) => c.is_active), [clients])

  const filteredClients = useMemo(() => {
    if (!search.trim()) return activeClients
    const q = search.toLowerCase()
    return activeClients.filter((c) => (c.org_name || '').toLowerCase().includes(q))
  }, [activeClients, search])

  const consolidatedByOrgId = useMemo(() => {
    const map: Record<string, ConsolidatedClient> = {}
    consolidated?.clients.forEach((cc) => { map[cc.org_id] = cc })
    return map
  }, [consolidated])

  const pendingRequests  = useMemo(() => accessRequests.filter((r) => r.status === 'pending'), [accessRequests])
  const resolvedRequests = useMemo(() => accessRequests.filter((r) => r.status !== 'pending'), [accessRequests])

  // ── Handlers ─────────────────────────────────────────────────────────────

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
      setAddClientOpen(false)
      toast.success('Access request sent — the organisation owner will be notified.')
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
      setInviteToken('')
      setAddClientOpen(false)
      await load()
      toast.success('Invite accepted — you now have access to this organisation.')
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
        toast.error('Organisation not found — ask your client to check your membership.')
        return
      }
      // Save own org before switching context so PartnerDashboardPage can
      // restore it when the partner navigates back from the client's dashboard.
      const ownOrg = useAuthStore.getState().organisation
      if (ownOrg) sessionStorage.setItem('audity_partner_own_org', JSON.stringify(ownOrg))
      setOrganisations(orgs)
      setOrganisation(clientOrg)
      navigate('/dashboard')
    } catch {
      toast.error('Failed to switch to client organisation')
    } finally {
      setManagingBooks(null)
    }
  }

  const handleRemove = async (c: PartnerClientLink) => {
    if (!confirm(`Remove ${c.org_name || 'this client'}? Your access to their organisation will be revoked.`)) return
    setRemoving(c.id)
    try {
      await partnerApi.removeClient(c.id)
      setClients((prev) => prev.filter((x) => x.id !== c.id))
      toast.success('Client removed and access revoked')
    } catch {
      toast.error('Failed to remove client')
    } finally {
      setRemoving(null)
    }
  }

  const handleWithdraw = async (req: PartnerAccessRequest) => {
    if (!confirm(`Withdraw this access request to ${req.org_name}?`)) return
    setWithdrawing(req.id)
    try {
      await partnerApi.withdrawRequest(req.id)
      setAccessRequests((prev) =>
        prev.map((r) => r.id === req.id ? { ...r, status: 'withdrawn' as PartnerAccessRequestStatus } : r)
      )
      toast.success('Request withdrawn')
    } catch {
      toast.error('Failed to withdraw request')
    } finally {
      setWithdrawing(null)
    }
  }

  // ── Loading state ─────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={24} className="animate-spin text-brand-400" />
      </div>
    )
  }

  if (!profile) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <GraduationCap size={40} className="text-slate-600" />
        <p className="text-slate-400 text-sm">Partner profile not found.</p>
        <button onClick={() => navigate('/billing')} className="btn-primary text-sm">
          Set up Partner Account
        </button>
      </div>
    )
  }

  const tier = TIER_META[profile.tier] ?? TIER_META.starter
  const maxClients = profile.max_clients >= 999999 ? null : profile.max_clients

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5 max-w-6xl">

      {/* ── Header ── */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-purple-500/15 flex items-center justify-center shrink-0">
            <GraduationCap size={20} className="text-purple-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-white leading-none">Partner Dashboard</h1>
              <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${tier.cls}`}>
                {tier.label}
              </span>
            </div>
            {profile.firm_name && (
              <p className="text-xs text-slate-500 mt-0.5">{profile.firm_name}</p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {profile.referral_code && (
            <button
              onClick={() => { navigator.clipboard.writeText(profile.referral_code); toast.success('Referral code copied') }}
              className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 transition-colors"
            >
              <Copy size={11} />
              {profile.referral_code}
            </button>
          )}
          {profile.tier === 'starter' && !subscriptionExpired && (
            <button onClick={() => navigate('/billing')} className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 transition-colors">
              Upgrade Plan
            </button>
          )}
          <button
            onClick={() => navigate('/partner/report')}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white px-3 py-1.5 rounded-lg hover:bg-surface-700/50 transition-colors"
          >
            <BarChart3 size={13} /> Report
          </button>
          <button
            onClick={() => { bypassNextGets(); load() }}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white px-3 py-1.5 rounded-lg hover:bg-surface-700/50 transition-colors"
          >
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      {/* ── Subscription expired paywall ── */}
      {subscriptionExpired && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-5 flex flex-col sm:flex-row items-start sm:items-center gap-4">
          <div className="w-10 h-10 rounded-full bg-red-500/10 flex items-center justify-center shrink-0">
            <LockKeyhole size={18} className="text-red-400" />
          </div>
          <div className="flex-1 space-y-1">
            <p className="text-white font-semibold text-sm">Partner subscription required</p>
            <ul className="text-xs text-slate-400 space-y-0.5 list-disc list-inside">
              <li>Manage and switch to client organisations</li>
              <li>Track commission from client subscriptions</li>
              <li>Consolidated financial reporting across your portfolio</li>
            </ul>
          </div>
          <button onClick={() => navigate('/billing')} className="btn-primary shrink-0 text-sm">
            Subscribe to Partner Plan
          </button>
        </div>
      )}

      {/* ── KPI strip ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiTile
          label="Active Clients"
          value={activeClients.length}
          sub={maxClients ? `of ${maxClients} max` : undefined}
          icon={Users}
        />
        <KpiTile
          label="Revenue This Month"
          value={consolidated ? fmtMoney(consolidated.totals.total_revenue) : '—'}
          sub={consolidated ? `across ${consolidated.totals.client_count} clients` : 'Upgrade for insights'}
          icon={TrendingUp}
        />
        <KpiTile
          label="Outstanding Balance"
          value={consolidated ? fmtMoney(consolidated.totals.total_outstanding) : '—'}
          icon={DollarSign}
          accent={consolidated && consolidated.totals.total_outstanding > 0 ? 'text-red-400' : 'text-white'}
        />
        <KpiTile
          label="Commission Credits"
          value={commission ? fmtMoney(commission.available_balance) : fmtMoney(profile.total_commission_earned)}
          sub={commission?.pending_balance && commission.pending_balance > 0
            ? `+${fmtMoney(commission.pending_balance)} pending`
            : `${profile.commission_rate}% rate`}
          icon={DollarSign}
          accent="text-green-400"
        />
      </div>

      {/* ── Main content: clients + requests panel ── */}
      <div className="flex flex-col lg:flex-row gap-5">

        {/* ── Clients section ── */}
        <div className="flex-1 min-w-0 space-y-3">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                className="input pl-8 text-sm"
                placeholder="Search clients…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <button
              onClick={() => { setAddClientOpen(true); setAddClientTab('request') }}
              disabled={subscriptionExpired}
              className="btn-primary text-sm flex items-center gap-1.5 shrink-0"
            >
              <UserPlus size={13} /> Add Client
            </button>
          </div>

          {filteredClients.length === 0 ? (
            <div className="card text-center py-12">
              <Building2 size={32} className="text-slate-600 mx-auto mb-3" />
              {search ? (
                <p className="text-slate-400 text-sm">No clients match "{search}"</p>
              ) : (
                <>
                  <p className="text-slate-300 font-medium text-sm">No clients yet</p>
                  <p className="text-slate-500 text-xs mt-1 max-w-xs mx-auto">
                    Request access to an organisation, or ask a client to generate an invite token for you.
                  </p>
                  <button
                    onClick={() => { setAddClientOpen(true); setAddClientTab('request') }}
                    className="btn-primary text-sm mt-4 mx-auto"
                    disabled={subscriptionExpired}
                  >
                    <UserPlus size={13} /> Add your first client
                  </button>
                </>
              )}
            </div>
          ) : (
            <div className="card overflow-hidden p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700">
                    <th className="text-left text-xs text-slate-500 font-medium px-4 py-3">Organisation</th>
                    <th className="text-left text-xs text-slate-500 font-medium px-4 py-3 hidden md:table-cell">Linked</th>
                    <th className="text-right text-xs text-slate-500 font-medium px-4 py-3 hidden lg:table-cell">Revenue (mo)</th>
                    <th className="text-right text-xs text-slate-500 font-medium px-4 py-3 hidden lg:table-cell">Outstanding</th>
                    <th className="text-right text-xs text-slate-500 font-medium px-4 py-3">Commission</th>
                    <th className="px-4 py-3 w-px" />
                  </tr>
                </thead>
                <tbody>
                  {filteredClients.map((c) => {
                    const cc = consolidatedByOrgId[c.organisation]
                    return (
                      <tr key={c.id} className="border-b border-surface-700/50 last:border-0 hover:bg-surface-700/20 transition-colors">
                        <td className="px-4 py-3">
                          <p className="text-white font-medium leading-tight">{c.org_name || '—'}</p>
                          {cc?.overdue_count ? (
                            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-red-500/15 text-red-400 mt-0.5 inline-block">
                              {cc.overdue_count} overdue
                            </span>
                          ) : null}
                        </td>
                        <td className="px-4 py-3 text-slate-400 text-xs hidden md:table-cell">
                          {fmtDate(c.linked_at)}
                        </td>
                        <td className="px-4 py-3 text-right text-slate-300 text-xs hidden lg:table-cell">
                          {cc ? fmtMoney(cc.revenue_this_month) : '—'}
                        </td>
                        <td className="px-4 py-3 text-right hidden lg:table-cell">
                          {cc ? (
                            <span className={cc.outstanding_balance > 0 ? 'text-red-400 text-xs font-medium' : 'text-slate-500 text-xs'}>
                              {fmtMoney(cc.outstanding_balance)}
                            </span>
                          ) : <span className="text-slate-600 text-xs">—</span>}
                        </td>
                        <td className="px-4 py-3 text-right text-green-400 text-xs font-medium">
                          {fmtMoney(c.commission_earned)}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-1">
                            <button
                              onClick={() => handleManageBooks(c)}
                              disabled={!!managingBooks}
                              title="Switch to client's workspace"
                              className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg text-purple-400 hover:bg-purple-400/10 font-medium transition-colors"
                            >
                              {managingBooks === c.id
                                ? <Loader2 size={11} className="animate-spin" />
                                : <ExternalLink size={11} />}
                              Manage
                            </button>
                            <button
                              onClick={() => handleRemove(c)}
                              disabled={removing === c.id}
                              title="Remove client and revoke access"
                              className="p-1.5 rounded-lg text-slate-600 hover:text-red-400 hover:bg-red-400/10 transition-colors"
                            >
                              {removing === c.id
                                ? <Loader2 size={13} className="animate-spin" />
                                : <Trash2 size={13} />}
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── Access Requests panel ── */}
        <div className={`lg:w-72 shrink-0 ${subscriptionExpired ? 'opacity-50 pointer-events-none' : ''}`}>
          <div className="card space-y-3">
            <button
              onClick={() => setReqPanelOpen((v) => !v)}
              className="w-full flex items-center justify-between text-sm font-semibold text-white"
            >
              <span className="flex items-center gap-2">
                <ShieldCheck size={14} className="text-slate-400" />
                Access Requests
                {pendingRequests.length > 0 && (
                  <span className="bg-amber-500 text-black text-[10px] font-bold px-1.5 py-0.5 rounded-full leading-none">
                    {pendingRequests.length}
                  </span>
                )}
              </span>
              {reqPanelOpen ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
            </button>

            {reqPanelOpen && (
              <div className="space-y-2">
                {accessRequests.length === 0 ? (
                  <p className="text-xs text-slate-500 text-center py-4">No requests yet. Use "Add Client" to request access.</p>
                ) : (
                  <>
                    {/* Pending first */}
                    {pendingRequests.map((req) => (
                      <div key={req.id} className="rounded-lg bg-amber-500/5 border border-amber-500/20 px-3 py-2.5 space-y-1.5">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="text-white text-xs font-medium truncate">{req.org_name}</p>
                            <p className="text-[10px] text-slate-500">{fmtDate(req.created_at)}</p>
                          </div>
                          <span className="flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-400 shrink-0">
                            <Clock size={9} /> Pending
                          </span>
                        </div>
                        {req.request_message && (
                          <p className="text-[10px] text-slate-500 italic truncate">"{req.request_message}"</p>
                        )}
                        <button
                          onClick={() => handleWithdraw(req)}
                          disabled={withdrawing === req.id}
                          className="text-[10px] text-slate-500 hover:text-red-400 transition-colors"
                        >
                          {withdrawing === req.id ? <Loader2 size={10} className="animate-spin" /> : 'Withdraw'}
                        </button>
                      </div>
                    ))}

                    {/* Resolved (collapsed toggle) */}
                    {resolvedRequests.length > 0 && (
                      <div>
                        <button
                          onClick={() => setShowAllReqs((v) => !v)}
                          className="w-full text-[11px] text-slate-500 hover:text-slate-300 py-1 flex items-center justify-center gap-1 transition-colors"
                        >
                          {showAllReqs ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                          {showAllReqs ? 'Hide history' : `${resolvedRequests.length} historical request${resolvedRequests.length > 1 ? 's' : ''}`}
                        </button>
                        {showAllReqs && resolvedRequests.slice(0, 10).map((req) => {
                          const meta = STATUS_META[req.status] ?? STATUS_META.withdrawn
                          return (
                            <div key={req.id} className="rounded-lg border border-surface-600/50 px-3 py-2 flex items-center justify-between gap-2 mt-1.5">
                              <div className="min-w-0">
                                <p className="text-white text-xs truncate">{req.org_name}</p>
                                <p className="text-[10px] text-slate-500">{fmtDate(req.updated_at || req.created_at)}</p>
                              </div>
                              <span className={`flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full shrink-0 ${meta.cls}`}>
                                <meta.Icon size={9} /> {meta.label}
                              </span>
                            </div>
                          )
                        })}
                      </div>
                    )}

                    {/* Quick add link */}
                    <button
                      onClick={() => { setAddClientOpen(true); setAddClientTab('request') }}
                      className="w-full text-xs text-brand-400 hover:text-brand-300 py-1.5 border border-dashed border-surface-600 rounded-lg hover:border-brand-500/40 transition-colors flex items-center justify-center gap-1"
                    >
                      <Send size={11} /> New request
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Add Client Modal ── */}
      {addClientOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setAddClientOpen(false)} />
          <div className="relative card w-full max-w-lg p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <UserPlus size={16} className="text-brand-400" /> Add a Client Organisation
              </h2>
              <button onClick={() => setAddClientOpen(false)} className="text-slate-400 hover:text-white">
                <X size={18} />
              </button>
            </div>

            {/* Tab switcher */}
            <div className="flex rounded-xl bg-surface-800 border border-surface-700 p-1 gap-1">
              <button
                onClick={() => setAddClientTab('request')}
                className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold transition-colors ${
                  addClientTab === 'request'
                    ? 'bg-brand-500 text-white'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <Send size={11} /> Request Access
              </button>
              <button
                onClick={() => setAddClientTab('token')}
                className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold transition-colors ${
                  addClientTab === 'token'
                    ? 'bg-purple-500 text-white'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <Key size={11} /> Accept Invite Token
              </button>
            </div>

            {addClientTab === 'request' && (
              <div className="space-y-4">
                <p className="text-xs text-slate-400">
                  Enter the Organisation ID of the client. The account owner will receive a notification and must approve your request before you gain access.
                </p>
                <div>
                  <label className="label">Client's Organisation ID</label>
                  <input
                    className="input font-mono text-sm"
                    placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                    value={reqOrgId}
                    onChange={(e) => setReqOrgId(e.target.value)}
                    autoFocus
                  />
                  <p className="text-[10px] text-slate-500 mt-1">
                    Ask your client to copy their Organisation ID from Settings → General.
                  </p>
                </div>
                <div>
                  <label className="label">Message to owner <span className="text-slate-600">(optional)</span></label>
                  <input
                    className="input text-sm"
                    placeholder="e.g. Hi, I'm your accountant from BrightTax Ltd."
                    value={reqMessage}
                    onChange={(e) => setReqMessage(e.target.value)}
                    maxLength={300}
                  />
                </div>
                <div className="flex items-center justify-end gap-2 pt-1">
                  <button onClick={() => setAddClientOpen(false)} className="btn-ghost text-sm">Cancel</button>
                  <button
                    onClick={handleRequestAccess}
                    disabled={requesting || !reqOrgId.trim()}
                    className="btn-primary text-sm flex items-center gap-1.5"
                  >
                    {requesting ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
                    Send Request
                  </button>
                </div>
              </div>
            )}

            {addClientTab === 'token' && (
              <div className="space-y-4">
                <p className="text-xs text-slate-400">
                  If a client generated an invite token and sent it to you, paste it here for immediate access — no approval needed.
                </p>
                <div>
                  <label className="label">Invite Token</label>
                  <input
                    className="input font-mono text-sm"
                    placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                    value={inviteToken}
                    onChange={(e) => setInviteToken(e.target.value)}
                    autoFocus
                  />
                </div>
                <div className="flex items-center justify-end gap-2 pt-1">
                  <button onClick={() => setAddClientOpen(false)} className="btn-ghost text-sm">Cancel</button>
                  <button
                    onClick={handleAcceptToken}
                    disabled={acceptingToken || !inviteToken.trim()}
                    className="btn-primary text-sm flex items-center gap-1.5 bg-purple-500 hover:bg-purple-400"
                  >
                    {acceptingToken ? <Loader2 size={13} className="animate-spin" /> : <ChevronRight size={13} />}
                    Accept Token
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
