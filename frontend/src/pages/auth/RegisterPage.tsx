import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Zap, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { authApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'

export default function RegisterPage() {
  const navigate = useNavigate()
  const { setAuth } = useAuthStore()
  const [form, setForm] = useState({
    email: '', first_name: '', last_name: '', phone: '',
    password: '', password_confirm: '',
  })
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (form.password !== form.password_confirm) {
      toast.error('Passwords do not match.')
      return
    }
    setLoading(true)
    try {
      const { data } = await authApi.register(form)
      setAuth(data.user, data.tokens)
      toast.success('Account created! Set up your workspace.')
      navigate('/onboarding')
    } catch (err: any) {
      if (!err.response) {
        toast.error('Cannot connect to server. Make sure the backend is running on port 8000.')
        return
      }
      const detail = err.response?.data?.error?.detail
      const msg = typeof detail === 'object' && detail
        ? Object.values(detail).flat().join(' ')
        : (err.response?.data?.error?.message ?? 'Registration failed. Please check your details.')
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }

  const update = (field: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [field]: e.target.value }))

  return (
    <div className="min-h-screen bg-surface-950 flex items-center justify-center p-6">
      <div className="w-full max-w-lg">
        <div className="flex items-center gap-3 mb-8">
          <div className="w-10 h-10 bg-brand-500 rounded-xl flex items-center justify-center shadow-glow-orange">
            <Zap size={20} className="text-white" />
          </div>
          <h1 className="text-xl font-bold text-white">Audity</h1>
        </div>

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
                  required
                  placeholder="At least 10 characters"
                />
                <button type="button" onClick={() => setShowPw((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
                  {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <div>
              <label className="label">Confirm password</label>
              <input type={showPw ? 'text' : 'password'} className="input"
                value={form.password_confirm} onChange={update('password_confirm')}
                required placeholder="Repeat password" />
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
