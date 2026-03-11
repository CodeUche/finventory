import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Zap, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { authApi, orgApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'

export default function LoginPage() {
  const navigate = useNavigate()
  const { setAuth, setOrganisation, setOrganisations, rememberMe, setRememberMe } = useAuthStore()
  const [form, setForm] = useState({ email: '', password: '' })
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const { data } = await authApi.login(form.email, form.password)
      setAuth(data.user || { email: form.email, first_name: '', last_name: '', id: '', phone: '', is_verified: true }, {
        access: data.access,
        refresh: data.refresh,
      })

      // Fetch user's organisations
      const orgsRes = await orgApi.list()
      const orgs = orgsRes.data.results ?? orgsRes.data
      setOrganisations(orgs)
      if (orgs.length > 0) {
        setOrganisation(orgs[0])
        toast.success('Welcome back!')
        navigate('/dashboard')
      } else {
        toast.success('Signed in! Set up your workspace.')
        navigate('/onboarding')
      }
    } catch (err: any) {
      if (!err.response) {
        toast.error('Cannot connect to server. Make sure the backend is running on port 8000.')
        return
      }
      toast.error('Invalid email or password.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-surface-950 flex">
      {/* Left panel — branding */}
      <div className="hidden lg:flex lg:w-1/2 relative overflow-hidden bg-gradient-to-br from-surface-900 to-surface-950 items-center justify-center p-12">
        {/* Decorative circles */}
        <div className="absolute top-0 left-0 w-96 h-96 bg-brand-500/10 rounded-full -translate-x-1/2 -translate-y-1/2 blur-3xl" />
        <div className="absolute bottom-0 right-0 w-80 h-80 bg-blue-500/10 rounded-full translate-x-1/2 translate-y-1/2 blur-3xl" />

        <div className="relative z-10 max-w-md">
          <div className="flex items-center gap-3 mb-12">
            <div className="w-12 h-12 bg-brand-500 rounded-2xl flex items-center justify-center shadow-glow-orange">
              <Zap size={24} className="text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">Audity</h1>
              <p className="text-slate-400 text-sm">Business Suite</p>
            </div>
          </div>

          <h2 className="text-4xl font-bold text-white leading-tight mb-4">
            Manage your<br />
            <span className="text-brand-400">liquor empire</span><br />
            with precision
          </h2>
          <p className="text-slate-400 text-lg leading-relaxed">
            Track inventory, record sales, manage credit customers, and file taxes — all from one platform.
          </p>

          {/* Feature list */}
          <div className="mt-8 space-y-3">
            {['Real-time inventory tracking', 'Progressive tax engine', 'Credit management & aging', 'P&L and cash flow reports'].map((f) => (
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
          {/* Mobile logo */}
          <div className="flex items-center gap-3 mb-8 lg:hidden">
            <div className="w-10 h-10 bg-brand-500 rounded-xl flex items-center justify-center">
              <Zap size={20} className="text-white" />
            </div>
            <h1 className="text-xl font-bold text-white">Audity</h1>
          </div>

          <h2 className="text-3xl font-bold text-white mb-2">Sign in</h2>
          <p className="text-slate-400 mb-8">
            Don't have an account?{' '}
            <Link to="/register" className="text-brand-400 hover:text-brand-300 font-medium">Create one</Link>
          </p>

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
              <label className="label">Password</label>
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

            {/* Remember me */}
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
          </form>
        </div>
      </div>
    </div>
  )
}
