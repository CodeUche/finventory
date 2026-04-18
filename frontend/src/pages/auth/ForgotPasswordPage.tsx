import { useState } from 'react'
import { Link } from 'react-router-dom'
import AudityLogo from '@/components/AudityLogo'
import { ArrowLeft, Loader2, Mail, KeyRound, Eye, EyeOff, CheckCircle, CheckCircle2, XCircle } from 'lucide-react'

const PW_CRITERIA = [
  { label: 'At least 10 characters', test: (p: string) => p.length >= 10 },
  { label: 'One uppercase letter (A–Z)', test: (p: string) => /[A-Z]/.test(p) },
  { label: 'One lowercase letter (a–z)', test: (p: string) => /[a-z]/.test(p) },
  { label: 'One number (0–9)', test: (p: string) => /\d/.test(p) },
  { label: 'One special character (!@#$…)', test: (p: string) => /[^A-Za-z0-9]/.test(p) },
]
import toast from 'react-hot-toast'
import { authApi } from '@/services/api'

type Step = 'email' | 'code' | 'done'

export default function ForgotPasswordPage() {
  const [step, setStep] = useState<Step>('email')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleRequestCode = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email) return
    setLoading(true)
    try {
      await authApi.requestPasswordReset(email.trim().toLowerCase())
      toast.success('Reset code sent — check your email')
      setStep('code')
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to send reset code')
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }

  const pwMet = PW_CRITERIA.map(c => c.test(newPassword))
  const pwValid = pwMet.every(Boolean)
  const pwStrength = pwMet.filter(Boolean).length
  const strengthColor = pwStrength <= 1 ? 'bg-red-500' : pwStrength <= 3 ? 'bg-amber-500' : 'bg-green-500'

  const handleConfirm = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!pwValid) {
      toast.error('Password does not meet all the requirements.')
      return
    }
    if (newPassword !== confirmPassword) {
      toast.error('Passwords do not match')
      return
    }
    setLoading(true)
    try {
      await authApi.confirmPasswordReset({
        email: email.trim().toLowerCase(),
        code: code.trim(),
        new_password: newPassword,
        confirm_password: confirmPassword,
      })
      setStep('done')
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Invalid or expired code')
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-surface-950 flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        {/* Logo */}
        <AudityLogo className="h-10 w-auto mb-8" />

        {step === 'done' ? (
          /* ── Success state ── */
          <div className="card text-center py-10">
            <div className="w-14 h-14 rounded-full bg-green-500/15 flex items-center justify-center mx-auto mb-4">
              <CheckCircle size={28} className="text-green-400" />
            </div>
            <h2 className="text-xl font-bold text-white mb-2">Password reset!</h2>
            <p className="text-slate-400 text-sm mb-6">
              Your password has been updated. You can now sign in with your new password.
            </p>
            <Link
              to="/login"
              className="btn-primary w-full flex items-center justify-center gap-2"
            >
              Go to Sign in
            </Link>
          </div>
        ) : step === 'email' ? (
          /* ── Step 1: Enter email ── */
          <div className="card">
            <div className="flex items-center gap-3 mb-1">
              <div className="w-10 h-10 rounded-xl bg-brand-500/10 flex items-center justify-center">
                <Mail size={18} className="text-brand-400" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-white">Forgot password?</h2>
                <p className="text-xs text-slate-500">We'll send a reset code to your email</p>
              </div>
            </div>

            <p className="text-slate-400 text-sm mt-4 mb-6">
              Enter the email address linked to your Audity account and we'll send you a 6-digit code.
            </p>

            <form onSubmit={handleRequestCode} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Email address</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  required
                  autoFocus
                  className="input w-full"
                />
              </div>

              <button
                type="submit"
                disabled={loading || !email}
                className="btn-primary w-full flex items-center justify-center gap-2"
              >
                {loading ? <Loader2 size={16} className="animate-spin" /> : null}
                Send reset code
              </button>
            </form>

            <p className="text-center text-sm text-slate-500 mt-5">
              <Link to="/login" className="text-brand-400 hover:text-brand-300 inline-flex items-center gap-1">
                <ArrowLeft size={13} /> Back to sign in
              </Link>
            </p>
          </div>
        ) : (
          /* ── Step 2: Enter OTP + new password ── */
          <div className="card">
            <div className="flex items-center gap-3 mb-1">
              <div className="w-10 h-10 rounded-xl bg-brand-500/10 flex items-center justify-center">
                <KeyRound size={18} className="text-brand-400" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-white">Enter reset code</h2>
                <p className="text-xs text-slate-500">Check your inbox at {email}</p>
              </div>
            </div>

            <p className="text-slate-400 text-sm mt-4 mb-6">
              Enter the 6-digit code from your email, then choose a new password. The code expires in 15 minutes.
            </p>

            <form onSubmit={handleConfirm} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">6-digit code</label>
                <input
                  type="text"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  placeholder="123456"
                  maxLength={6}
                  required
                  autoFocus
                  className="input w-full tracking-[0.3em] text-center text-lg font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">New password</label>
                <div className="relative">
                  <input
                    type={showPw ? 'text' : 'password'}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="Create a strong password"
                    required
                    className="input w-full pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                  >
                    {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
                {newPassword.length > 0 && (
                  <div className="mt-2 flex gap-1">
                    {PW_CRITERIA.map((_, i) => (
                      <div key={i} className={`h-1 flex-1 rounded-full transition-colors ${i < pwStrength ? strengthColor : 'bg-surface-700'}`} />
                    ))}
                  </div>
                )}
                {newPassword.length > 0 && (
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
                <label className="block text-xs font-medium text-slate-400 mb-1">Confirm new password</label>
                <input
                  type={showPw ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Repeat password"
                  required
                  className="input w-full"
                />
              </div>

              <button
                type="submit"
                disabled={loading || code.length !== 6 || !newPassword || !confirmPassword}
                className="btn-primary w-full flex items-center justify-center gap-2"
              >
                {loading ? <Loader2 size={16} className="animate-spin" /> : null}
                Reset password
              </button>
            </form>

            <div className="flex items-center justify-between mt-5 text-sm text-slate-500">
              <button
                onClick={() => setStep('email')}
                className="text-slate-400 hover:text-slate-300 inline-flex items-center gap-1"
              >
                <ArrowLeft size={13} /> Change email
              </button>
              <button
                onClick={handleRequestCode}
                disabled={loading}
                className="text-brand-400 hover:text-brand-300"
              >
                Resend code
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
