import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Loader2, AlertCircle, ShieldCheck } from 'lucide-react'
import toast from 'react-hot-toast'
import { api, authApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import AudityLogo from '@/components/AudityLogo'

export default function LoginPage() {
  const navigate = useNavigate()
  const { setAuth, setOrganisation, setOrganisations, rememberMe, setRememberMe } = useAuthStore()
  const [form, setForm] = useState({ email: '', password: '' })
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)

  // Email-not-verified banner
  const [showVerifyBanner, setShowVerifyBanner] = useState(false)
  const [resending, setResending] = useState(false)

  // MFA step
  const [mfaToken, setMfaToken] = useState<string | null>(null)
  const [mfaCode, setMfaCode] = useState('')
  const [mfaLoading, setMfaLoading] = useState(false)

  const handleResendVerification = async () => {
    setResending(true)
    try {
      await authApi.resendVerification(form.email)
      toast.success('Verification email sent! Check your inbox.')
    } catch {
      toast.error('Could not resend. Please try again.')
    } finally {
      setResending(false)
    }
  }

  const finishLogin = async (user: any, tokens: { access: string; refresh: string }) => {
    localStorage.setItem('finventory-session-start', String(Date.now()))
    localStorage.setItem('finventory-last-active', String(Date.now()))

    // Set the Authorization header FIRST so orgApi.list() can authenticate,
    // but do NOT call setAuth() yet — setAuth sets isAuthenticated:true which
    // causes ProtectedRoute to pass through and React mounts the Dashboard,
    // firing all its API calls before we have the org ID in the store.
    api.defaults.headers.common.Authorization = `Bearer ${tokens.access}`

    // Bootstrap the org context from the JWT payload BEFORE calling orgApi.list().
    // The RLS tenant_isolation policy requires app.current_org_id to match an
    // existing org row — it blocks all reads under the SENTINEL value.  The JWT
    // the server just issued already contains the user's memberships dict
    // {org_id: role}, so we decode it (no signature verification needed — the
    // server verified credentials before issuing it) to get the first org ID and
    // pre-set it as X-Organisation-ID.  Without this, orgApi.list() runs under
    // SENTINEL, the SELECT returns empty, and the app stays stuck on Onboarding.
    let bootstrapOrgId: string | null = null
    try {
      const b64 = tokens.access.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
      const payload = JSON.parse(atob(b64))
      const memberships: Record<string, string> = payload.memberships ?? {}
      bootstrapOrgId = Object.keys(memberships)[0] ?? null
    } catch { /* non-fatal — proceed without pre-set header */ }

    if (bootstrapOrgId) {
      api.defaults.headers.common['X-Organisation-ID'] = bootstrapOrgId
    }

    // Fetch orgs with org context already set (both header and ?org= param).
    // Pass Authorization + X-Organisation-ID explicitly on this request —
    // setAuth() hasn't run yet so Zustand tokens are empty; relying on
    // api.defaults alone risks AxiosHeaders.toJSON silently dropping them.
    const orgsRes = await api.get('/tenancy/organisations/', {
      headers: {
        Authorization: `Bearer ${tokens.access}`,
        ...(bootstrapOrgId ? { 'X-Organisation-ID': bootstrapOrgId } : {}),
      },
      params: bootstrapOrgId ? { org: bootstrapOrgId } : {},
    })
    const orgs = orgsRes.data.results ?? orgsRes.data

    // SECURITY: for superusers, orgApi.list() returns ALL orgs in the DB.
    // orgs[0] could be any tenant's org — never auto-assign it as active.
    // Use only the org the JWT explicitly identifies via bootstrapOrgId.
    // For regular users: fall back to orgs[0] (their only org) if bootstrapOrgId is missing.
    let firstOrg: any = null
    if (user.is_superuser) {
      firstOrg = bootstrapOrgId ? (orgs.find((o: any) => o.id === bootstrapOrgId) ?? { id: bootstrapOrgId }) : null
    } else {
      firstOrg = orgs[0] ?? null
      // Guard: if RLS returned empty but JWT confirmed membership, use minimal placeholder.
      // AppLayout will reload the full org on mount once tokens are in Zustand.
      if (!firstOrg && bootstrapOrgId) firstOrg = { id: bootstrapOrgId } as any
    }

    // NOW commit everything to the store in one synchronous batch.
    // React 18 batches these consecutive Zustand updates into a single render,
    // so when the Dashboard first mounts, organisation is already set.
    setAuth(user, tokens)
    setOrganisations(orgs)
    if (firstOrg) {
      setOrganisation(firstOrg)
      api.defaults.headers.common['X-Organisation-ID'] = firstOrg.id
    } else {
      // No orgs found and no JWT membership — clear any stale org left over from
      // a previous session to avoid sending a wrong X-Organisation-ID header.
      setOrganisation(null)
      delete api.defaults.headers.common['X-Organisation-ID']
    }

    // Diagnostic: verify the backend receives the org ID (non-blocking).
    if (firstOrg) {
      api.get('/auth/org-debug/').then(({ data }) => {
        const received = data.org_header ?? data.org_param ?? null
        if (!received) {
          toast.error(
            `⚠ Org header not reaching server. org_header=${data.org_header} org_param=${data.org_param} raw=${data.raw_org_id}`,
            { duration: 20000, id: 'org-debug' }
          )
        } else {
          toast.success(`Org context OK: ${received.slice(0, 8)}…`, { duration: 4000, id: 'org-debug' })
        }
      }).catch(() => { /* non-fatal diagnostic */ })
    }

    const onboardingDone = user.is_superuser || !!firstOrg
    toast.success(onboardingDone ? 'Welcome back!' : 'Signed in! Let\'s finish setting up your account.')
    // Superusers with no org memberships land on the platform admin page — they have
    // no personal org context and would get "organisation ID" errors on all tenant APIs.
    if (user.is_superuser && !firstOrg) {
      navigate('/platform-admin')
    } else {
      navigate(onboardingDone ? '/dashboard' : '/onboarding')
    }
  }

  const handleMFASubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!mfaToken) return
    setMfaLoading(true)
    try {
      const { data } = await authApi.mfaVerify(mfaToken, mfaCode)
      await finishLogin(data.user, data.tokens)
    } catch (err: any) {
      const data = err.response?.data
      // Handle envelope {error: {message}} format, plain {error: string}, or SimpleJWT {detail: string}
      const apiErr = data?.error
      const msg = typeof apiErr === 'string'
        ? apiErr
        : (apiErr?.message ?? (typeof data?.detail === 'string' ? 'MFA session expired. Please log in again.' : 'Invalid or expired code. Please try again.'))
      toast.error(msg)
    } finally {
      setMfaLoading(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setShowVerifyBanner(false)
    try {
      const { data } = await authApi.login(form.email, form.password)

      // MFA required — switch to OTP step
      if (data.mfa_required) {
        setMfaToken(data.mfa_token)
        setLoading(false)
        return
      }

      await finishLogin(
        data.user || { email: form.email, first_name: '', last_name: '', id: '', phone: '', is_verified: true },
        { access: data.access, refresh: data.refresh },
      )
    } catch (err: any) {
      if (!err.response) {
        toast.error('Cannot connect to server. Make sure the backend is running on port 8000.')
      } else {
        const url: string = err.config?.url ?? ''
        const status: number = err.response?.status ?? 0
        const apiErr = err.response?.data?.error
        const errCode = typeof apiErr === 'object' ? apiErr?.code : ''
        const errMsg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? err.response?.data?.detail ?? '')

        if (errCode === 'email_not_verified') {
          setShowVerifyBanner(true)
        } else if (url.includes('/auth/login/')) {
          if (status === 429) {
            toast.error(errMsg || 'Too many login attempts. Please wait a moment and try again.')
          } else {
            toast.error(errMsg || 'Invalid email or password.')
          }
        } else {
          toast.error(errMsg || `Failed to load workspace (${status}). Please try again.`)
        }
      }
    } finally {
      setLoading(false)
    }
  }

  // ── MFA verification screen ────────────────────────────────────────────────
  if (mfaToken) {
    return (
      <div className="min-h-screen bg-surface-950 flex items-center justify-center p-6">
        <div className="w-full max-w-md">
          <AudityLogo className="h-10 w-auto mb-8" />

          <div className="card">
            <div className="flex items-center gap-3 mb-5">
              <div className="w-10 h-10 bg-brand-500/15 rounded-xl flex items-center justify-center">
                <ShieldCheck size={20} className="text-brand-400" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-white">Two-factor authentication</h2>
                <p className="text-sm text-slate-400">Enter the code from your authenticator app</p>
              </div>
            </div>

            <form onSubmit={handleMFASubmit} className="space-y-5">
              <div>
                <label className="label">6-digit code</label>
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9a-fA-F]*"
                  maxLength={10}
                  className="input text-center text-2xl tracking-widest font-mono"
                  placeholder="000000"
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value.replace(/\s/g, ''))}
                  autoFocus
                  required
                />
                <p className="text-xs text-slate-500 mt-2">
                  Can't access your app? Enter one of your backup codes instead.
                </p>
              </div>

              <button type="submit" disabled={mfaLoading || mfaCode.length < 6} className="btn-primary w-full justify-center py-3">
                {mfaLoading ? <Loader2 size={18} className="animate-spin" /> : null}
                {mfaLoading ? 'Verifying…' : 'Verify'}
              </button>

              <button
                type="button"
                onClick={() => { setMfaToken(null); setMfaCode('') }}
                className="w-full text-center text-sm text-slate-400 hover:text-white transition-colors"
              >
                ← Back to sign in
              </button>
            </form>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-surface-950 flex">
      {/* Left panel */}
      <div className="force-dark hidden lg:flex lg:w-1/2 relative overflow-hidden bg-gradient-to-br from-surface-900 to-surface-950 items-center justify-center p-12">
        <div className="absolute top-0 left-0 w-96 h-96 bg-brand-500/10 rounded-full -translate-x-1/2 -translate-y-1/2 blur-3xl" />
        <div className="absolute bottom-0 right-0 w-80 h-80 bg-blue-500/10 rounded-full translate-x-1/2 translate-y-1/2 blur-3xl" />

        <div className="relative z-10 max-w-md">
          <AudityLogo className="h-12 w-auto mb-12" />

          <h2 className="text-4xl font-bold text-white leading-tight mb-4">
            Manage your<br />
            <span className="text-brand-400">empire</span><br />
            with precision
          </h2>
          <p className="text-slate-400 text-lg leading-relaxed">
            Track inventory, record sales, manage payroll, and file taxes — all from one platform.
          </p>

          <div className="mt-8 space-y-3">
            {['Real-time inventory tracking', 'Progressive tax engine', 'Payroll & statutory remittances', 'Credit management & aging', 'P&L and cash flow reports'].map((f) => (
              <div key={f} className="flex items-center gap-3 text-slate-300">
                <div className="w-1.5 h-1.5 bg-brand-400 rounded-full shrink-0" />
                {f}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right panel — form */}
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-md">
          <AudityLogo className="h-10 w-auto mb-8 lg:hidden" />

          <h2 className="text-3xl font-bold text-white mb-2">Sign in</h2>
          <p className="text-slate-400 mb-8">
            Don't have an account?{' '}
            <Link to="/register" className="text-brand-400 hover:text-brand-300 font-medium">Create one</Link>
          </p>

          {/* Email-not-verified banner */}
          {showVerifyBanner && (
            <div className="mb-5 p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl flex gap-3">
              <AlertCircle size={18} className="text-amber-400 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-amber-300 font-medium">Email not verified</p>
                <p className="text-xs text-amber-400/80 mt-0.5">Check your inbox for a verification link.</p>
                <button
                  onClick={handleResendVerification}
                  disabled={resending}
                  className="text-xs text-amber-300 hover:text-amber-200 underline mt-1.5 flex items-center gap-1"
                >
                  {resending ? <Loader2 size={11} className="animate-spin" /> : null}
                  {resending ? 'Sending…' : 'Resend verification email'}
                </button>
              </div>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="label">Email address</label>
              <input
                type="email"
                value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                placeholder="you@company.com"
                required
                className="input"
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="label !mb-0">Password</label>
                <Link to="/forgot-password" className="text-xs text-brand-400 hover:text-brand-300 font-medium">
                  Forgot password?
                </Link>
              </div>
              <div className="relative">
                <input
                  type={showPw ? 'text' : 'password'}
                  value={form.password}
                  onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                  placeholder="••••••••••"
                  required
                  className="input pr-12"
                />
                <button
                  type="button"
                  onClick={() => setShowPw((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                >
                  {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <label className="flex items-center gap-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                className="w-4 h-4 rounded accent-brand-500"
              />
              <span className="text-sm text-slate-400">Remember me on this device</span>
            </label>

            <button type="submit" disabled={loading} className="btn-primary w-full justify-center py-3">
              {loading ? <Loader2 size={18} className="animate-spin" /> : null}
              {loading ? 'Signing in…' : 'Sign in'}
            </button>

            <p className="text-center text-sm text-slate-500">
              Team member?{' '}
              <button type="button" onClick={() => navigate('/staff-login')} className="text-brand-400 hover:text-brand-300 font-medium">
                Staff sign in →
              </button>
            </p>
          </form>
        </div>
      </div>
    </div>
  )
}
