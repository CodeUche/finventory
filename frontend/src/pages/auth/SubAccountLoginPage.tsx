import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Loader2, Users } from 'lucide-react'
import toast from 'react-hot-toast'
import { api, authApi, orgApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'

export default function SubAccountLoginPage() {
  const navigate = useNavigate()
  const { setAuth, setOrganisation, setOrganisations } = useAuthStore()
  const [form, setForm] = useState({ username: '', org_slug: '', password: '' })
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const { data } = await authApi.staffLogin(form.username.trim().toLowerCase(), form.org_slug.trim().toLowerCase(), form.password)

      localStorage.setItem('finventory-session-start', String(Date.now()))
      localStorage.setItem('finventory-last-active', String(Date.now()))
      setAuth(data.user, { access: data.access, refresh: data.refresh })
      api.defaults.headers.common.Authorization = `Bearer ${data.access}`

      const orgsRes = await orgApi.list()
      const orgs = orgsRes.data.results ?? orgsRes.data
      setOrganisations(orgs)
      if (orgs.length > 0) setOrganisation(orgs[0])

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
    <div className="min-h-screen bg-surface-950 flex">
      {/* Left panel */}
      <div className="force-dark hidden lg:flex lg:w-1/2 relative overflow-hidden bg-gradient-to-br from-surface-900 to-surface-950 items-center justify-center p-12">
        <div className="absolute top-0 left-0 w-96 h-96 bg-brand-500/10 rounded-full -translate-x-1/2 -translate-y-1/2 blur-3xl" />
        <div className="absolute bottom-0 right-0 w-80 h-80 bg-blue-500/10 rounded-full translate-x-1/2 translate-y-1/2 blur-3xl" />
        <div className="relative z-10 max-w-md">
          <div className="flex items-center gap-3 mb-12">
            <div className="w-12 h-12 rounded-full bg-white overflow-hidden flex items-center justify-center flex-shrink-0">
              <img src="/audity-logo.png" alt="Audity" className="w-10 h-10 object-contain" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">Audity</h1>
              <p className="text-slate-400 text-sm">Business Suite</p>
            </div>
          </div>
          <h2 className="text-4xl font-bold text-white leading-tight mb-4">
            Staff<br />
            <span className="text-brand-400">access portal</span>
          </h2>
          <p className="text-slate-400 text-lg leading-relaxed">
            Sign in with the credentials your administrator sent you. Your access level is managed by your workspace owner.
          </p>
          <div className="mt-8 space-y-3">
            {[
              'Access is controlled by your administrator',
              'Your account is linked to your workspace',
              'Contact your admin to reset your password',
              'Your workspace subscription governs your access',
            ].map((f) => (
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
          <div className="flex items-center gap-3 mb-8 lg:hidden">
            <div className="w-10 h-10 rounded-full bg-white overflow-hidden flex items-center justify-center flex-shrink-0">
              <img src="/audity-logo.png" alt="Audity" className="w-8 h-8 object-contain" />
            </div>
            <h1 className="text-xl font-bold text-white">Audity</h1>
          </div>

          <div className="flex items-center gap-3 mb-2">
            <div className="w-9 h-9 bg-brand-500/15 rounded-xl flex items-center justify-center">
              <Users size={18} className="text-brand-400" />
            </div>
            <h2 className="text-3xl font-bold text-white">Staff sign in</h2>
          </div>
          <p className="text-slate-400 mb-8">
            Owner or manager?{' '}
            <a href="/login" className="text-brand-400 hover:text-brand-300 font-medium" onClick={(e) => { e.preventDefault(); navigate('/login') }}>
              Sign in here
            </a>
          </p>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="label">Username</label>
              <input
                type="text"
                autoComplete="username"
                value={form.username}
                onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
                placeholder="e.g. john"
                required
                className="input"
              />
              <p className="text-xs text-slate-500 mt-1.5">The username your administrator gave you (part before the @)</p>
            </div>

            <div>
              <label className="label">Workspace</label>
              <input
                type="text"
                autoComplete="organization"
                value={form.org_slug}
                onChange={(e) => setForm((f) => ({ ...f, org_slug: e.target.value }))}
                placeholder="e.g. acme-corp"
                required
                className="input"
              />
              <p className="text-xs text-slate-500 mt-1.5">Your company's workspace identifier (shown in your credentials email)</p>
            </div>

            <div>
              <label className="label">Password</label>
              <div className="relative">
                <input
                  type={showPw ? 'text' : 'password'}
                  autoComplete="current-password"
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

            <button type="submit" disabled={loading} className="btn-primary w-full justify-center py-3">
              {loading ? <Loader2 size={18} className="animate-spin" /> : null}
              {loading ? 'Signing in…' : 'Sign in to workspace'}
            </button>
          </form>

          <p className="text-xs text-slate-600 text-center mt-8">
            Forgot your credentials? Contact your workspace administrator.
          </p>
        </div>
      </div>
    </div>
  )
}
