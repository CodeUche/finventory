import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Loader2, AlertCircle, ShieldCheck, WifiOff } from 'lucide-react'
import toast from 'react-hot-toast'
import { api, authApi, bypassNextGets } from '@/services/api'
import { offlineCache } from '@/lib/offlineCache'
import { useAuthStore } from '@/store/authStore'
import { identifyUser } from '@/lib/analytics'
import { tryOfflineLogin, storeVerifier, hasVerifierStored } from '@/lib/offlineVerifier'
import AuthShell from '@/components/auth/AuthShell'

export default function LoginPage() {
  const navigate = useNavigate()
  const { initSession, setOrganisation, startOfflineSession } = useAuthStore()
  const [form, setForm] = useState({ email: '', password: '' })
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  // True while running the ~0.5 s PBKDF2 derivation for offline login
  const [offlineChecking, setOfflineChecking] = useState(false)
  // True if a verifier blob is stored (shown as a hint on the login form)
  const [offlineAvailable, setOfflineAvailable] = useState(false)

  useEffect(() => {
    setOfflineAvailable(hasVerifierStored())
  }, [])

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

  const finishLogin = async (
    user: any,
    tokens: { access: string; refresh: string },
    loginOrgs?: any[],
  ) => {
    // Hard guard: abort immediately if tokens are malformed.
    if (!tokens?.access || !tokens?.refresh || typeof tokens.access !== 'string' || !tokens.access.includes('.')) {
      throw new Error('Authentication failed. Please check your connection and try again.')
    }

    localStorage.setItem('finventory-session-start', String(Date.now()))
    localStorage.setItem('finventory-last-active', String(Date.now()))

    // Set Authorization header so any fallback fetch below can authenticate.
    api.defaults.headers.common.Authorization = `Bearer ${tokens.access}`

    // --- Fast path: server included organisations in the login response ---
    // This is the primary path. It requires no extra network round-trip and has
    // no dependency on RLS session variables, pgBouncer mode, or JWT decoding.
    let orgs: any[] = loginOrgs ?? []

    // --- Fallback: fetch organisations separately (legacy / offline edge-case) ---
    if (orgs.length === 0 && !user.is_superuser) {
      // Decode JWT to get bootstrapOrgId for RLS context header.
      let bootstrapOrgId: string | null = null
      try {
        const b64 = tokens.access.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
        const payload = JSON.parse(atob(b64))
        const memberships: Record<string, string> = payload.memberships ?? {}
        bootstrapOrgId = Object.keys(memberships)[0] ?? null
      } catch { /* non-fatal */ }

      if (bootstrapOrgId) {
        api.defaults.headers.common['X-Organisation-ID'] = bootstrapOrgId
        setOrganisation({ id: bootstrapOrgId } as any)
      }

      await offlineCache.invalidatePrefix('/tenancy/organisations/')
      bypassNextGets(3000)

      try {
        const orgsRes = await api.get('/tenancy/organisations/', {
          headers: {
            Authorization: `Bearer ${tokens.access}`,
            ...(bootstrapOrgId ? { 'X-Organisation-ID': bootstrapOrgId } : {}),
          },
          params: bootstrapOrgId ? { org: bootstrapOrgId } : {},
        })
        orgs = orgsRes.data.results ?? orgsRes.data ?? []
      } catch {
        // Network failure on the fallback fetch — orgs stays empty.
        // The guard below will use bootstrapOrgId as a minimal placeholder.
      }

      // Last-resort guard: JWT confirmed membership but fetch returned empty.
      if (orgs.length === 0 && bootstrapOrgId) {
        orgs = [{ id: bootstrapOrgId }]
      }
    }

    // For superusers orgApi.list returns ALL orgs — pick only the JWT-identified one.
    let firstOrg: any = null
    if (user.is_superuser) {
      let bootstrapOrgId: string | null = null
      try {
        const b64 = tokens.access.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
        const payload = JSON.parse(atob(b64))
        const memberships: Record<string, string> = payload.memberships ?? {}
        bootstrapOrgId = Object.keys(memberships)[0] ?? null
      } catch { /* non-fatal */ }
      firstOrg = bootstrapOrgId ? (orgs.find((o: any) => o.id === bootstrapOrgId) ?? { id: bootstrapOrgId }) : null
    } else {
      firstOrg = orgs[0] ?? null
    }

    // Wipe stale membership cache from a previous session.
    offlineCache.invalidatePrefix('/tenancy/organisations/my_membership/').catch(() => {})
    offlineCache.invalidatePrefix('/tenancy/memberships/').catch(() => {})

    // Atomic commit — single set() so ProtectedRoute never sees isAuthenticated=true
    // with organisation=null (which caused /onboarding redirects in the past).
    initSession(user, tokens, firstOrg, orgs)
    identifyUser(user, firstOrg)
    if (firstOrg) {
      api.defaults.headers.common['X-Organisation-ID'] = firstOrg.id
    } else {
      delete api.defaults.headers.common['X-Organisation-ID']
    }

    const onboardingDone = user.is_superuser || !!firstOrg
    toast.success(onboardingDone ? 'Welcome back!' : 'Signed in! Let\'s finish setting up your account.')
    if (user.is_superuser && !firstOrg) {
      navigate('/platform-admin')
    } else {
      navigate(onboardingDone ? '/dashboard' : '/onboarding')
    }
  }

  // Issue (or rotate) the offline verifier after a successful login.
  // Called with the plaintext password the user just typed — it must never
  // be stored after this call returns.  Non-fatal: a failure just means
  // offline login won't be available until the next successful online login.
  const issueOfflineVerifier = async (password: string) => {
    try {
      const deviceLabel = (() => {
        try {
          const ua = navigator.userAgent
          if (ua.includes('Windows')) return 'Windows Desktop'
          if (ua.includes('Mac')) return 'Mac Desktop'
          if (ua.includes('Linux')) return 'Linux Desktop'
        } catch { /* ignore */ }
        return 'Audity Desktop'
      })()
      const { data } = await authApi.issueOfflineVerifier(password, deviceLabel)
      if (data?.verifier) {
        await storeVerifier(data.verifier)
        setOfflineAvailable(true)
      }
    } catch {
      // Non-fatal: rate-limited, MFA, or network issue — skip silently
    }
  }

  const handleMFASubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!mfaToken) return
    setMfaLoading(true)
    try {
      const { data } = await authApi.mfaVerify(mfaToken, mfaCode)
      await finishLogin(data.user, data.tokens, data.organisations)
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
    const { email, password } = form
    try {
      const { data } = await authApi.login(email, password)

      // MFA required — switch to OTP step
      if (data.mfa_required) {
        setMfaToken(data.mfa_token)
        setLoading(false)
        return
      }

      await finishLogin(
        data.user || { email, first_name: '', last_name: '', id: '', phone: '', is_verified: true },
        { access: data.access, refresh: data.refresh },
        data.organisations,
      )
      // Fire-and-forget: issue/rotate the offline verifier while the user is
      // navigating to the dashboard.  The password is passed here and nowhere
      // else — never stored after this function returns.
      issueOfflineVerifier(password)
    } catch (err: any) {
      if (!err.response) {
        // Network unreachable — try offline PBKDF2 verification (~0.5 s)
        setOfflineChecking(true)
        const result = await tryOfflineLogin(email, password)
        setOfflineChecking(false)
        if (result.ok) {
          startOfflineSession(result.blob)
          toast('Signed in offline. Your changes will sync when you reconnect.', {
            icon: '📡',
            duration: 5000,
          })
          navigate('/dashboard')
        } else if (result.reason === 'no_verifier') {
          toast.error('Cannot connect to server. Connect to the internet and try again.')
        } else if (result.reason === 'expired') {
          toast.error('Your offline access has expired. Please connect to the internet to sign in.')
        } else if (result.reason === 'too_many_attempts') {
          toast.error('Too many offline attempts. Please connect to the internet to sign in.')
        } else {
          const left = result.remaining ?? 0
          toast.error(`Incorrect password. ${left} offline attempt${left === 1 ? '' : 's'} remaining.`)
        }
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
      <AuthShell>
        <div className="au-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 22 }}>
            <div className="au-badge"><ShieldCheck size={22} /></div>
            <div>
              <h2 className="au-title" style={{ fontSize: 22 }}>Two-factor authentication</h2>
              <p className="au-sub" style={{ margin: '4px 0 0' }}>Enter the code from your authenticator app.</p>
            </div>
          </div>

          <form onSubmit={handleMFASubmit}>
            <div className="au-field">
              <label>6-digit code</label>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9a-fA-F]*"
                maxLength={10}
                className="au-input"
                style={{ textAlign: 'center', fontSize: 24, letterSpacing: '.3em', fontFamily: 'JetBrains Mono, monospace' }}
                placeholder="000000"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value.replace(/\s/g, ''))}
                autoFocus
                required
              />
              <p className="au-sub" style={{ fontSize: 12.5, margin: '8px 0 0' }}>
                Can't access your app? Enter one of your backup codes instead.
              </p>
            </div>

            <button type="submit" disabled={mfaLoading || mfaCode.length < 6} className="au-btn" style={{ marginTop: 18 }}>
              {mfaLoading ? <Loader2 size={18} className="animate-spin" /> : null}
              {mfaLoading ? 'Verifying…' : 'Verify'}
            </button>

            <p className="au-foot">
              <button type="button" className="au-link" onClick={() => { setMfaToken(null); setMfaCode('') }}>
                ← Back to sign in
              </button>
            </p>
          </form>
        </div>
      </AuthShell>
    )
  }

  // ── Sign-in screen ─────────────────────────────────────────────────────────
  return (
    <AuthShell>
      <div className="au-card">
        <div className="au-eyebrow">Welcome back</div>
        <h2 className="au-title">Sign in to Audity</h2>
        <p className="au-sub">Pick up exactly where you left off.</p>

        <div className="au-switch">
          <button type="button" className="on">Sign in</button>
          <button type="button" onClick={() => navigate('/register')}>Create account</button>
        </div>

        {/* Email-not-verified banner */}
        {showVerifyBanner && (
          <div className="au-alert">
            <AlertCircle size={18} style={{ color: '#E8B65A', flex: 'none', marginTop: 1 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{ fontSize: 13.5, fontWeight: 600, color: '#E8B65A' }}>Email not verified</p>
              <p className="au-sub" style={{ fontSize: 12.5, margin: '2px 0 0' }}>Check your inbox for a verification link.</p>
              <button
                onClick={handleResendVerification}
                disabled={resending}
                className="au-link"
                style={{ fontSize: 12.5, marginTop: 6, display: 'inline-flex', alignItems: 'center', gap: 4 }}
              >
                {resending ? <Loader2 size={11} className="animate-spin" /> : null}
                {resending ? 'Sending…' : 'Resend verification email'}
              </button>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="au-field">
            <label>Work email</label>
            <input
              type="email"
              value={form.email}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              placeholder="you@company.com"
              required
              className="au-input"
            />
          </div>

          <div className="au-field">
            <div className="au-field-head">
              <label>Password</label>
              <Link to="/forgot-password" className="au-link" style={{ fontSize: 12.5 }}>Forgot password?</Link>
            </div>
            <div className="au-pw">
              <input
                type={showPw ? 'text' : 'password'}
                value={form.password}
                onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                placeholder="••••••••••"
                required
                className="au-input"
              />
              <button type="button" className="au-eye" onClick={() => setShowPw((v) => !v)} aria-label="Toggle password visibility">
                {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </div>

          {offlineAvailable && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, margin: '8px 0 0', opacity: 0.75 }}>
              <WifiOff size={13} style={{ color: '#94a3b8', flex: 'none' }} />
              <span style={{ fontSize: 12, color: '#94a3b8' }}>
                Offline access available — works without internet if server is unreachable.
              </span>
            </div>
          )}

          <button
            type="submit"
            disabled={loading || offlineChecking}
            className="au-btn"
            style={{ marginTop: 18 }}
          >
            {(loading || offlineChecking) ? <Loader2 size={18} className="animate-spin" /> : null}
            {offlineChecking ? 'Verifying offline…' : loading ? 'Signing in…' : 'Sign in'}
          </button>

          <p className="au-foot">
            Team member?{' '}
            <button type="button" onClick={() => navigate('/staff-login')} className="au-link">
              Staff sign in →
            </button>
          </p>
        </form>
      </div>
    </AuthShell>
  )
}
