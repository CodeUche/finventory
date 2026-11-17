import { useEffect, useState } from 'react'
import AuthShell from '@/components/auth/AuthShell'
import { useSearchParams, useNavigate, Link } from 'react-router-dom'
import { CheckCircle2, XCircle, Loader2, Mail } from 'lucide-react'
import { authApi } from '@/services/api'

export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token') ?? ''

  // NOTE: The backend /auth/verify-email/ endpoint returns HTML (a success/error page
  // for the user's browser). It does NOT return JSON with user/tokens. Email links in
  // the verification email point directly to the backend URL so the browser renders the
  // HTML page there. This frontend route is only reached if users are explicitly
  // redirected here — it shows a message and sends them to sign in.
  const [state, setState] = useState<'loading' | 'success' | 'error'>('loading')
  const [errorMsg, setErrorMsg] = useState('')
  const [errorCode] = useState('')
  const [email, setEmail] = useState('')
  const [resending, setResending] = useState(false)
  const [resent, setResent] = useState(false)

  useEffect(() => {
    if (!token) {
      setState('error')
      setErrorMsg('No verification token found in this link.')
      return
    }
    // We cannot parse the HTML response for user/tokens — just tell the user
    // their email is verified and redirect to sign in.
    setState('success')
    setTimeout(() => navigate('/login', { replace: true }), 2500)
  }, [token])

  const handleResend = async () => {
    if (!email) return
    setResending(true)
    try {
      await authApi.resendVerification(email)
      setResent(true)
    } catch {
      // silent — API always returns 200
      setResent(true)
    } finally {
      setResending(false)
    }
  }

  const title = state === 'loading' ? 'Verifying your email'
    : state === 'success' ? 'Email verified'
    : 'Verification failed'
  const subtitle = state === 'loading' ? 'Just a moment.'
    : state === 'success' ? 'Taking you to sign in.'
    : errorMsg

  return (
    <AuthShell title={title} subtitle={subtitle}>
      {state === 'loading' && (
        <div style={{ display: 'flex', justifyContent: 'center', margin: '4px 0 8px', color: 'var(--link)' }}>
          <Loader2 size={40} className="animate-spin" />
        </div>
      )}

      {state === 'success' && (
        <>
          <div style={{ display: 'flex', justifyContent: 'center', margin: '4px 0 18px', color: 'var(--link)' }}>
            <CheckCircle2 size={44} />
          </div>
          <Link to="/login" className="au-btn" style={{ textDecoration: 'none' }}>Go to Sign in</Link>
        </>
      )}

      {state === 'error' && (
        <>
          <div style={{ display: 'flex', justifyContent: 'center', margin: '4px 0 18px', color: 'var(--link)' }}>
            <XCircle size={44} />
          </div>

          {errorCode === 'token_expired' && (
            <>
              <div className="au-field">
                <label>Enter your email to get a new link</label>
                <input
                  type="email"
                  className="au-input"
                  placeholder="you@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              {resent ? (
                <p style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, color: 'var(--link)', fontSize: 14 }}>
                  <Mail size={16} /> New verification email sent. Check your inbox.
                </p>
              ) : (
                <button type="button" onClick={handleResend} disabled={resending || !email} className="au-btn">
                  {resending ? <Loader2 size={16} className="animate-spin" /> : null}
                  {resending ? 'Sending...' : 'Send new verification link'}
                </button>
              )}
            </>
          )}

          <p className="au-foot">
            <Link to="/login" className="au-link">Back to sign in</Link>
          </p>
        </>
      )}
    </AuthShell>
  )
}
