import { useState, useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Loader2, CheckCircle2, XCircle, Mail } from 'lucide-react'
import toast from 'react-hot-toast'
import { api, authApi, orgApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import AuthShell from '@/components/auth/AuthShell'

const PW_CRITERIA = [
  { label: 'At least 10 characters', test: (p: string) => p.length >= 10 },
  { label: 'One uppercase letter (A–Z)', test: (p: string) => /[A-Z]/.test(p) },
  { label: 'One lowercase letter (a–z)', test: (p: string) => /[a-z]/.test(p) },
  { label: 'One number (0–9)', test: (p: string) => /\d/.test(p) },
  { label: 'One special character (!@#$…)', test: (p: string) => /[^A-Za-z0-9]/.test(p) },
]

export default function RegisterPage() {
  const navigate = useNavigate()
  const { initSession, setOrganisation } = useAuthStore()
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const [form, setForm] = useState({
    email: '', first_name: '', last_name: '', phone: '',
    password: '', password_confirm: '',
  })
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [pwFocused, setPwFocused] = useState(false)
  const [registered, setRegistered] = useState(false)
  const [resending, setResending] = useState(false)
  const [pollingToken, setPollingToken] = useState<string | null>(null)

  // Poll every 5s once on "check your email" screen — auto-advance when verified
  useEffect(() => {
    if (!registered) return
    pollRef.current = setInterval(async () => {
      try {
        const { data } = await authApi.checkVerification(form.email, pollingToken ?? undefined)
        if (data.verified) {
          clearInterval(pollRef.current!)
          // Set auth header so subsequent requests can authenticate
          api.defaults.headers.common.Authorization = `Bearer ${data.tokens.access}`
          // Bootstrap org from JWT memberships claim
          let bootstrapOrgId: string | null = null
          try {
            const b64 = data.tokens.access.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
            const payload = JSON.parse(atob(b64))
            bootstrapOrgId = Object.keys(payload.memberships ?? {})[0] ?? null
          } catch { /* non-fatal */ }
          if (bootstrapOrgId) {
            api.defaults.headers.common['X-Organisation-ID'] = bootstrapOrgId
            setOrganisation({ id: bootstrapOrgId } as any)
          }
          try {
            const orgsRes = await orgApi.list()
            const orgs = orgsRes.data.results ?? orgsRes.data
            const firstOrg = orgs[0] ?? (bootstrapOrgId ? { id: bootstrapOrgId } as any : null)
            initSession(data.user, data.tokens, firstOrg, orgs)
            if (firstOrg) api.defaults.headers.common['X-Organisation-ID'] = firstOrg.id
            navigate(firstOrg ? '/dashboard' : '/onboarding')
          } catch {
            initSession(data.user, data.tokens, null, [])
            navigate('/onboarding')
          }
        }
      } catch {
        // Non-fatal — keep polling
      }
    }, 5000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [registered]) // eslint-disable-line react-hooks/exhaustive-deps

  const pwMet = PW_CRITERIA.map(c => c.test(form.password))
  const pwValid = pwMet.every(Boolean)
  const pwStrength = pwMet.filter(Boolean).length

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!pwValid) {
      toast.error('Password does not meet all the requirements below.')
      return
    }
    if (form.password !== form.password_confirm) {
      toast.error('Passwords do not match.')
      return
    }
    setLoading(true)
    try {
      const { data } = await authApi.register(form)
      setPollingToken(data.polling_token ?? null)
      setRegistered(true)
    } catch (err: any) {
      if (!err.response) {
        toast.error('Cannot connect to server. Check your internet connection and try again.')
      }
      // Interceptor already shows the error toast for API errors — no duplicate needed
    } finally {
      setLoading(false)
    }
  }

  const handleResend = async () => {
    setResending(true)
    try {
      await authApi.resendVerification(form.email)
      toast.success('Verification email resent!')
    } catch {
      toast.error('Could not resend email. Please try again.')
    } finally {
      setResending(false)
    }
  }

  const update = (field: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [field]: e.target.value }))

  const strengthColor = pwStrength <= 1 ? '#ef4444' : pwStrength <= 3 ? '#E8B65A' : '#34C98A'

  // ── Check-your-email screen ──────────────────────────────────────────────────
  if (registered) {
    return (
      <AuthShell>
        <div className="au-card" style={{ textAlign: 'center' }}>
          <div className="au-badge au-badge-em" style={{ margin: '0 auto 18px', width: 60, height: 60, borderRadius: '50%' }}>
            <Mail size={26} />
          </div>
          <h2 className="au-title" style={{ fontSize: 26 }}>Check your email</h2>
          <p className="au-sub" style={{ margin: '10px 0 22px' }}>
            We've sent a verification link to{' '}
            <span style={{ color: 'var(--head)', fontWeight: 600 }}>{form.email}</span>.
            Click the link to activate your account.
          </p>
          <div className="au-soft" style={{ textAlign: 'left' }}>
            <p className="au-sub" style={{ fontSize: 12.5, fontWeight: 600, margin: '0 0 8px' }}>Didn't receive it?</p>
            <ul className="au-sub" style={{ fontSize: 12.5, margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
              <li>Check your spam/junk folder</li>
              <li>Make sure you entered the right email</li>
              <li>The link expires in 24 hours</li>
            </ul>
          </div>
          <button onClick={handleResend} disabled={resending} className="au-btn" style={{ marginTop: 20, background: 'var(--field-bg)', color: 'var(--ink)', border: '1px solid var(--field-bd)' }}>
            {resending ? <Loader2 size={16} className="animate-spin" /> : null}
            {resending ? 'Sending…' : 'Resend verification email'}
          </button>
          <p className="au-foot">
            Already verified? <Link to="/login" className="au-link">Sign in</Link>
          </p>
        </div>
      </AuthShell>
    )
  }

  // ── Registration form ────────────────────────────────────────────────────────
  return (
    <AuthShell>
      <div className="au-card au-card-wide">
        <div className="au-eyebrow">Get started</div>
        <h2 className="au-title">Create your workspace</h2>
        <p className="au-sub">Set up your books in minutes — free for 14 days.</p>

        <div className="au-switch">
          <button type="button" onClick={() => navigate('/login')}>Sign in</button>
          <button type="button" className="on">Create account</button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="au-grid2">
            <div className="au-field">
              <label>First name</label>
              <input className="au-input" value={form.first_name} onChange={update('first_name')} required placeholder="John" />
            </div>
            <div className="au-field">
              <label>Last name</label>
              <input className="au-input" value={form.last_name} onChange={update('last_name')} required placeholder="Doe" />
            </div>
          </div>

          <div className="au-field">
            <label>Email address</label>
            <input type="email" className="au-input" value={form.email} onChange={update('email')} required placeholder="john@company.com" />
          </div>

          <div className="au-field">
            <label>Phone number</label>
            <input type="tel" className="au-input" value={form.phone} onChange={update('phone')} placeholder="+234 800 000 0000" />
          </div>

          <div className="au-field">
            <label>Password</label>
            <div className="au-pw">
              <input
                type={showPw ? 'text' : 'password'}
                className="au-input"
                value={form.password}
                onChange={update('password')}
                onFocus={() => setPwFocused(true)}
                required
                placeholder="Create a strong password"
              />
              <button type="button" className="au-eye" onClick={() => setShowPw((v) => !v)} aria-label="Toggle password visibility">
                {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>

            {form.password.length > 0 && (
              <div style={{ marginTop: 8, display: 'flex', gap: 4 }}>
                {PW_CRITERIA.map((_, i) => (
                  <div key={i} style={{ height: 4, flex: 1, borderRadius: 4, transition: 'background .2s', background: i < pwStrength ? strengthColor : 'var(--field-bd)' }} />
                ))}
              </div>
            )}

            {(pwFocused || form.password.length > 0) && (
              <div className="au-soft" style={{ marginTop: 12 }}>
                <p className="au-sub" style={{ fontSize: 12, fontWeight: 600, margin: '0 0 8px' }}>Password requirements:</p>
                {PW_CRITERIA.map((c, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
                    {pwMet[i]
                      ? <CheckCircle2 size={13} style={{ color: '#34C98A', flex: 'none' }} />
                      : <XCircle size={13} style={{ color: 'var(--muted)', flex: 'none', opacity: .6 }} />}
                    <span style={{ fontSize: 12, color: pwMet[i] ? '#34C98A' : 'var(--muted)' }}>{c.label}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="au-field">
            <label>Confirm password</label>
            <input
              type={showPw ? 'text' : 'password'}
              className="au-input"
              value={form.password_confirm}
              onChange={update('password_confirm')}
              required
              placeholder="Repeat password"
            />
            {form.password_confirm.length > 0 && form.password !== form.password_confirm && (
              <p style={{ fontSize: 12, color: '#ef4444', marginTop: 6 }}>Passwords do not match</p>
            )}
          </div>

          <button type="submit" disabled={loading} className="au-btn" style={{ marginTop: 8 }}>
            {loading ? <Loader2 size={18} className="animate-spin" /> : null}
            {loading ? 'Creating account…' : 'Create account'}
          </button>
        </form>
      </div>
    </AuthShell>
  )
}
