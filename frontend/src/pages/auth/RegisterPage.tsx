import { useState, useEffect, useRef } from 'react'
import AudityLogo from '@/components/AudityLogo'
import { Link, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Loader2, CheckCircle2, XCircle, Mail } from 'lucide-react'
import toast from 'react-hot-toast'
import { api, authApi, orgApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'

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

  const strengthColor = pwStrength <= 1 ? 'bg-red-500' : pwStrength <= 3 ? 'bg-amber-500' : 'bg-green-500'

  // ── Check-your-email screen ──────────────────────────────────────────────────
  if (registered) {
    return (
      <div className="min-h-screen bg-surface-950 flex items-center justify-center p-6">
        <div className="w-full max-w-md">
          <AudityLogo className="h-10 w-auto mb-8" />

          <div className="card text-center space-y-5">
            <div className="w-16 h-16 bg-brand-500/15 rounded-full flex items-center justify-center mx-auto">
              <Mail size={28} className="text-brand-400" />
            </div>
            <div>
              <h2 className="text-2xl font-bold text-white mb-2">Check your email</h2>
              <p className="text-slate-400 text-sm leading-relaxed">
                We've sent a verification link to{' '}
                <span className="text-white font-medium">{form.email}</span>.
                Click the link to activate your account.
              </p>
            </div>
            <div className="bg-surface-800 border border-surface-700 rounded-xl p-4 text-left space-y-2">
              <p className="text-xs text-slate-400">Didn't receive it?</p>
              <ul className="text-xs text-slate-500 list-disc list-inside space-y-1">
                <li>Check your spam/junk folder</li>
                <li>Make sure you entered the right email</li>
                <li>The link expires in 24 hours</li>
              </ul>
            </div>
            <button
              onClick={handleResend}
              disabled={resending}
              className="btn-secondary w-full justify-center py-2.5"
            >
              {resending ? <Loader2 size={16} className="animate-spin mr-2" /> : null}
              {resending ? 'Sending…' : 'Resend verification email'}
            </button>
            <p className="text-sm text-slate-500">
              Already verified?{' '}
              <Link to="/login" className="text-brand-400 hover:text-brand-300 font-medium">Sign in</Link>
            </p>
          </div>
        </div>
      </div>
    )
  }

  // ── Registration form ────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-surface-950 flex items-center justify-center p-6">
      <div className="w-full max-w-lg">
        <AudityLogo className="h-10 w-auto mb-8" />

        <div className="card">
          <h2 className="text-2xl font-bold text-white mb-1">Create account</h2>
          <p className="text-slate-400 text-sm mb-6">
            Already have an account?{' '}
            <Link to="/login" className="text-brand-400 hover:text-brand-300 font-medium">Sign in</Link>
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="label">First name</label>
                <input className="input" value={form.first_name} onChange={update('first_name')} required placeholder="John" />
              </div>
              <div>
                <label className="label">Last name</label>
                <input className="input" value={form.last_name} onChange={update('last_name')} required placeholder="Doe" />
              </div>
            </div>

            <div>
              <label className="label">Email address</label>
              <input type="email" className="input" value={form.email} onChange={update('email')} required placeholder="john@company.com" />
            </div>

            <div>
              <label className="label">Phone number</label>
              <input type="tel" className="input" value={form.phone} onChange={update('phone')} placeholder="+234 800 000 0000" />
            </div>

            <div>
              <label className="label">Password</label>
              <div className="relative">
                <input
                  type={showPw ? 'text' : 'password'}
                  className="input pr-12"
                  value={form.password}
                  onChange={update('password')}
                  onFocus={() => setPwFocused(true)}
                  required
                  placeholder="Create a strong password"
                />
                <button type="button" onClick={() => setShowPw((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
                  {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>

              {form.password.length > 0 && (
                <div className="mt-2 flex gap-1">
                  {PW_CRITERIA.map((_, i) => (
                    <div key={i} className={`h-1 flex-1 rounded-full transition-colors ${i < pwStrength ? strengthColor : 'bg-surface-700'}`} />
                  ))}
                </div>
              )}

              {(pwFocused || form.password.length > 0) && (
                <div className="mt-3 p-3 bg-surface-800 rounded-xl border border-surface-700 space-y-1.5">
                  <p className="text-xs font-medium text-slate-400 mb-2">Password requirements:</p>
                  {PW_CRITERIA.map((c, i) => (
                    <div key={i} className="flex items-center gap-2">
                      {pwMet[i]
                        ? <CheckCircle2 size={13} className="text-green-400 shrink-0" />
                        : <XCircle size={13} className="text-slate-600 shrink-0" />
                      }
                      <span className={`text-xs ${pwMet[i] ? 'text-green-400' : 'text-slate-500'}`}>{c.label}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <label className="label">Confirm password</label>
              <input type={showPw ? 'text' : 'password'} className="input"
                value={form.password_confirm} onChange={update('password_confirm')}
                required placeholder="Repeat password" />
              {form.password_confirm.length > 0 && form.password !== form.password_confirm && (
                <p className="text-xs text-red-400 mt-1">Passwords do not match</p>
              )}
            </div>

            <button type="submit" disabled={loading} className="btn-primary w-full justify-center py-3 mt-2">
              {loading ? <Loader2 size={18} className="animate-spin" /> : null}
              {loading ? 'Creating account…' : 'Create account'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
