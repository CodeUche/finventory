import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Loader2, Users, KeyRound } from 'lucide-react'
import toast from 'react-hot-toast'
import { api, authApi, bypassNextGets } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import { identifyUser } from '@/lib/analytics'
import AuthShell from '@/components/auth/AuthShell'
import type { AccessLevel, ModuleKey } from '@/types'

function extractMembership(data: any): { role: string; perms: Partial<Record<ModuleKey, AccessLevel>> } | null {
  if (!data?.membership?.role) return null
  const perms: Partial<Record<ModuleKey, AccessLevel>> = {}
  ;(data.membership.module_permissions ?? []).forEach((p: any) => {
    perms[p.module as ModuleKey] = p.access_level as AccessLevel
  })
  return { role: data.membership.role, perms }
}

export default function SubAccountLoginPage() {
  const navigate = useNavigate()
  const { initSession, setMembership } = useAuthStore()
  const [form, setForm] = useState({ username: '', org_slug: '', password: '' })
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)

  // Forced password change state
  const [showForceChange, setShowForceChange] = useState(false)
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [changingPw, setChangingPw] = useState(false)

  const handleForcePasswordChange = async () => {
    if (newPassword.length < 10) { toast.error('Password must be at least 10 characters'); return }
    if (newPassword !== confirmPassword) { toast.error('Passwords do not match'); return }
    setChangingPw(true)
    try {
      await authApi.changePassword(form.password, newPassword, confirmPassword)
      // The backend bumps token_version on password change, invalidating the old JWT.
      // Re-login with the new password to get fresh tokens before navigating.
      const { data } = await authApi.staffLogin(
        form.username.trim().toLowerCase(),
        form.org_slug.trim().toLowerCase(),
        newPassword,
      )
      const orgs: any[] = data.organisations ?? []
      const firstOrg = orgs[0] ?? null
      initSession(data.user, { access: data.access, refresh: data.refresh }, firstOrg, orgs)
      const mem = extractMembership(data)
      if (mem) setMembership(mem.role, mem.perms)
      api.defaults.headers.common.Authorization = `Bearer ${data.access}`
      if (firstOrg) api.defaults.headers.common['X-Organisation-ID'] = firstOrg.id
      bypassNextGets()
      toast.success('Password updated. Welcome!')
      navigate('/dashboard')
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to change password. Please try again.')
      toast.error(msg)
    } finally {
      setChangingPw(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const { data } = await authApi.staffLogin(form.username.trim().toLowerCase(), form.org_slug.trim().toLowerCase(), form.password)

      // Guard: if tokens are missing (should never happen after auth-URL exclusion fix,
      // but defence-in-depth catches any future regression before it reaches setAuth).
      if (!data?.access || !data?.refresh || typeof data.access !== 'string' || !data.access.includes('.')) {
        throw new Error('Authentication failed. Please check your connection and try again.')
      }

      localStorage.setItem('finventory-session-start', String(Date.now()))
      localStorage.setItem('finventory-last-active', String(Date.now()))
      api.defaults.headers.common.Authorization = `Bearer ${data.access}`

      // Use organisations returned directly from the login response.
      const orgs: any[] = data.organisations ?? []
      const firstOrg = orgs[0] ?? null

      // Atomic commit — single set() so ProtectedRoute never sees isAuthenticated=true
      // with organisation=null (the race condition that caused /onboarding redirects).
      initSession(data.user, { access: data.access, refresh: data.refresh }, firstOrg, orgs)
      const mem = extractMembership(data)
      if (mem) setMembership(mem.role, mem.perms)
      identifyUser(data.user, firstOrg)
      if (firstOrg) api.defaults.headers.common['X-Organisation-ID'] = firstOrg.id
      bypassNextGets(3000)

      if (data.user.must_change_password) {
        setShowForceChange(true)
        return
      }
      toast.success('Welcome back!')
      navigate('/dashboard')
    } catch (err: any) {
      if (!err.response) {
        toast.error('Cannot connect to server.')
      } else {
        const apiErr = err.response?.data?.error
        const errCode = typeof apiErr === 'object' ? apiErr?.code : ''
        const errMsg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Invalid credentials.')
        if (errCode === 'account_locked') {
          toast.error(errMsg)
        } else if (errCode === 'no_access') {
          toast.error(errMsg)
        } else if (errCode === 'subscription_inactive') {
          toast.error(errMsg)
        } else {
          toast.error(errMsg || 'Invalid username, workspace, or password.')
        }
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthShell
      headline={<>Your workspace, <em>your</em> access.</>}
      lead="Sign in with the credentials your administrator sent you. Your access level is managed by your workspace owner."
    >
      <div className="au-card">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
          <div className="au-badge" style={{ width: 38, height: 38, borderRadius: 11 }}><Users size={18} /></div>
          <h2 className="au-title" style={{ fontSize: 26 }}>Staff sign in</h2>
        </div>
        <p className="au-sub">
          Owner or manager?{' '}
          <button type="button" className="au-link" onClick={() => navigate('/login')}>Sign in here</button>
        </p>

        <form onSubmit={handleSubmit}>
          <div className="au-field">
            <label>Username</label>
            <input
              type="text"
              autoComplete="username"
              value={form.username}
              onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
              placeholder="e.g. john"
              required
              className="au-input"
            />
            <p className="au-sub" style={{ fontSize: 12, margin: '6px 0 0' }}>The username your administrator gave you (part before the @)</p>
          </div>

          <div className="au-field">
            <label>Workspace</label>
            <input
              type="text"
              autoComplete="organization"
              value={form.org_slug}
              onChange={(e) => setForm((f) => ({ ...f, org_slug: e.target.value }))}
              placeholder="e.g. acme-corp"
              required
              className="au-input"
            />
            <p className="au-sub" style={{ fontSize: 12, margin: '6px 0 0' }}>Your company's workspace identifier (shown in your credentials email)</p>
          </div>

          <div className="au-field">
            <label>Password</label>
            <div className="au-pw">
              <input
                type={showPw ? 'text' : 'password'}
                autoComplete="current-password"
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

          <button type="submit" disabled={loading} className="au-btn" style={{ marginTop: 18 }}>
            {loading ? <Loader2 size={18} className="animate-spin" /> : null}
            {loading ? 'Signing in…' : 'Sign in to workspace'}
          </button>
        </form>

        <p className="au-foot" style={{ fontSize: 12 }}>
          Forgot your credentials? Contact your workspace administrator.
        </p>
      </div>

      {/* Forced password change modal */}
      {showForceChange && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, background: 'rgba(0,0,0,.7)', backdropFilter: 'blur(4px)' }}>
          <div className="au-card" style={{ maxWidth: 420 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18 }}>
              <div className="au-badge" style={{ width: 40, height: 40, borderRadius: 11 }}><KeyRound size={20} /></div>
              <div>
                <h2 className="au-title" style={{ fontSize: 19 }}>Set your password</h2>
                <p className="au-sub" style={{ fontSize: 12, margin: '3px 0 0' }}>Your administrator requires you to change your password before continuing.</p>
              </div>
            </div>
            <div className="au-field">
              <label>New password</label>
              <input
                type="password"
                className="au-input"
                placeholder="At least 10 characters"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoFocus
              />
            </div>
            <div className="au-field">
              <label>Confirm password</label>
              <input
                type="password"
                className="au-input"
                placeholder="Repeat new password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
            </div>
            <button
              onClick={handleForcePasswordChange}
              disabled={changingPw || !newPassword || !confirmPassword}
              className="au-btn"
              style={{ marginTop: 8 }}
            >
              {changingPw ? <Loader2 size={16} className="animate-spin" /> : 'Set password & continue'}
            </button>
          </div>
        </div>
      )}
    </AuthShell>
  )
}
