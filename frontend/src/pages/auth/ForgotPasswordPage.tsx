import { useState } from 'react'
import { Link } from 'react-router-dom'
import AuthShell from '@/components/auth/AuthShell'
import { ArrowLeft, Loader2, Eye, EyeOff, CheckCircle, CheckCircle2, XCircle } from 'lucide-react'

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
  const strengthColor = pwStrength <= 1 ? '#FF3336' : pwStrength <= 3 ? '#FECB01' : '#13CC00'

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

  const title = step === 'done' ? 'Password reset!' : step === 'email' ? 'Forgot password?' : 'Enter reset code'
  const subtitle = step === 'done'
    ? 'Your password has been updated. You can now sign in with your new password.'
    : step === 'email'
      ? "Enter the email linked to your Audity account and we'll send you a 6-digit code."
      : `Enter the 6-digit code sent to ${email}, then choose a new password. The code expires in 15 minutes.`

  return (
    <AuthShell title={title} subtitle={subtitle}>
      {step === 'done' ? (
        <>
          <div style={{ display: 'flex', justifyContent: 'center', margin: '4px 0 18px', color: 'var(--link)' }}>
            <CheckCircle size={44} />
          </div>
          <Link to="/login" className="au-btn" style={{ textDecoration: 'none' }}>Go to Sign in</Link>
        </>
      ) : step === 'email' ? (
        <form onSubmit={handleRequestCode}>
          <div className="au-field">
            <label>Email address</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com" required autoFocus className="au-input" />
          </div>
          <button type="submit" disabled={loading || !email} className="au-btn">
            {loading ? <Loader2 size={16} className="animate-spin" /> : null}
            Send reset code
          </button>
          <p className="au-foot">
            <Link to="/login" className="au-link" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <ArrowLeft size={14} /> Back to sign in
            </Link>
          </p>
        </form>
      ) : (
        <form onSubmit={handleConfirm}>
          <div className="au-field">
            <label>6-digit code</label>
            <input type="text" value={code} inputMode="numeric"
              onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              placeholder="123456" maxLength={6} required autoFocus className="au-input"
              style={{ textAlign: 'center', fontSize: 20, letterSpacing: '.3em', fontFamily: "'Roboto Mono', monospace" }} />
          </div>

          <div className="au-field">
            <label>New password</label>
            <div className="au-pw">
              <input type={showPw ? 'text' : 'password'} value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)} placeholder="Create a strong password"
                required className="au-input" />
              <button type="button" className="au-eye" onClick={() => setShowPw((v) => !v)} aria-label="Toggle password visibility">
                {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            {newPassword.length > 0 && (
              <>
                <div style={{ display: 'flex', gap: 4, marginTop: 10 }}>
                  {PW_CRITERIA.map((_, i) => (
                    <div key={i} style={{ height: 4, flex: 1, borderRadius: 4, background: i < pwStrength ? strengthColor : 'var(--soft-bd)' }} />
                  ))}
                </div>
                <div style={{ marginTop: 12, padding: 12, borderRadius: 12, background: 'var(--soft-bg)', border: '1px solid var(--soft-bd)' }}>
                  <p style={{ fontSize: 12, fontWeight: 500, color: 'var(--ink)', marginBottom: 8 }}>Password requirements:</p>
                  {PW_CRITERIA.map((c, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4, fontSize: 12, color: pwMet[i] ? 'var(--link)' : 'var(--muted)' }}>
                      {pwMet[i] ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                      <span>{c.label}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          <div className="au-field">
            <label>Confirm new password</label>
            <input type={showPw ? 'text' : 'password'} value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)} placeholder="Repeat password" required className="au-input" />
          </div>

          <button type="submit" disabled={loading || code.length !== 6 || !newPassword || !confirmPassword} className="au-btn">
            {loading ? <Loader2 size={16} className="animate-spin" /> : null}
            Reset password
          </button>

          <div className="au-row" style={{ marginTop: 18, marginBottom: 0 }}>
            <button type="button" onClick={() => setStep('email')} className="au-link" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <ArrowLeft size={14} /> Change email
            </button>
            <button type="button" onClick={handleRequestCode} disabled={loading} className="au-link">Resend code</button>
          </div>
        </form>
      )}
    </AuthShell>
  )
}
