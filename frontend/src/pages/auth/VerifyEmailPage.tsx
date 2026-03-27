import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate, Link } from 'react-router-dom'
import { CheckCircle2, XCircle, Loader2, Mail } from 'lucide-react'
import { authApi, orgApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'

export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { setAuth, setOrganisation, setOrganisations } = useAuthStore()
  const token = searchParams.get('token') ?? ''

  const [state, setState] = useState<'loading' | 'success' | 'error'>('loading')
  const [errorMsg, setErrorMsg] = useState('')
  const [errorCode, setErrorCode] = useState('')
  const [email, setEmail] = useState('')
  const [resending, setResending] = useState(false)
  const [resent, setResent] = useState(false)

  useEffect(() => {
    if (!token) {
      setState('error')
      setErrorMsg('No verification token found in this link.')
      return
    }
    authApi.verifyEmail(token)
      .then(async ({ data }) => {
        setAuth(data.user, data.tokens)
        try {
          const orgsRes = await orgApi.list()
          const orgs = orgsRes.data.results ?? orgsRes.data
          setOrganisations(orgs)
          if (orgs.length > 0) setOrganisation(orgs[0])
          setState('success')
          setTimeout(() => navigate(orgs.length > 0 ? '/dashboard' : '/onboarding'), 2000)
        } catch {
          setState('success')
          setTimeout(() => navigate('/onboarding'), 2000)
        }
      })
      .catch((err) => {
        const apiErr = err.response?.data?.error
        const code = typeof apiErr === 'object' ? (apiErr?.code ?? '') : ''
        const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Verification failed. The link may have expired.')
        setErrorCode(code)
        setErrorMsg(msg)
        setState('error')
      })
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

  return (
    <div className="min-h-screen bg-surface-950 flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 rounded-full bg-white overflow-hidden flex items-center justify-center flex-shrink-0">
            <img src="/audity-logo.png" alt="Audity" className="w-8 h-8 object-contain" />
          </div>
          <h1 className="text-xl font-bold text-white">Audity</h1>
        </div>

        <div className="card text-center space-y-5">
          {state === 'loading' && (
            <>
              <Loader2 size={40} className="animate-spin text-brand-400 mx-auto" />
              <p className="text-white font-semibold text-lg">Verifying your email…</p>
              <p className="text-slate-400 text-sm">Just a moment.</p>
            </>
          )}

          {state === 'success' && (
            <>
              <div className="w-16 h-16 bg-green-500/15 rounded-full flex items-center justify-center mx-auto">
                <CheckCircle2 size={32} className="text-green-400" />
              </div>
              <p className="text-white font-bold text-xl">Email verified!</p>
              <p className="text-slate-400 text-sm">Redirecting you to your workspace…</p>
            </>
          )}

          {state === 'error' && (
            <>
              <div className="w-16 h-16 bg-red-500/15 rounded-full flex items-center justify-center mx-auto">
                <XCircle size={32} className="text-red-400" />
              </div>
              <p className="text-white font-bold text-xl">Verification failed</p>
              <p className="text-slate-400 text-sm">{errorMsg}</p>

              {errorCode === 'token_expired' && (
                <div className="space-y-3">
                  <div>
                    <label className="label text-left">Enter your email to get a new link</label>
                    <input
                      type="email"
                      className="input"
                      placeholder="you@company.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                    />
                  </div>
                  {resent ? (
                    <div className="flex items-center justify-center gap-2 text-green-400 text-sm">
                      <Mail size={16} />
                      New verification email sent! Check your inbox.
                    </div>
                  ) : (
                    <button
                      onClick={handleResend}
                      disabled={resending || !email}
                      className="btn-primary w-full justify-center py-2.5"
                    >
                      {resending ? <Loader2 size={16} className="animate-spin mr-2" /> : null}
                      {resending ? 'Sending…' : 'Send new verification link'}
                    </button>
                  )}
                </div>
              )}

              <Link to="/login" className="block text-sm text-brand-400 hover:text-brand-300 font-medium">
                ← Back to sign in
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
