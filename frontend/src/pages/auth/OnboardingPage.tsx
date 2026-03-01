import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Building2, Zap } from 'lucide-react'
import toast from 'react-hot-toast'
import { orgApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'

const ACCOUNT_TYPES = [
  { value: 'business', label: 'Business', desc: 'Company, distributor, or retailer' },
  { value: 'personal', label: 'Personal', desc: 'Sole trader or individual' },
]

const PRESETS = [
  { country: 'NG', currency: 'NGN', flag: '🇳🇬', label: 'Nigeria' },
  { country: 'GH', currency: 'GHS', flag: '🇬🇭', label: 'Ghana' },
  { country: 'KE', currency: 'KES', flag: '🇰🇪', label: 'Kenya' },
  { country: 'ZA', currency: 'ZAR', flag: '🇿🇦', label: 'South Africa' },
  { country: 'US', currency: 'USD', flag: '🇺🇸', label: 'United States' },
  { country: 'GB', currency: 'GBP', flag: '🇬🇧', label: 'United Kingdom' },
]

export default function OnboardingPage() {
  const navigate = useNavigate()
  const { user, setOrganisation } = useAuthStore()

  const [form, setForm] = useState({
    name: '',
    account_type: 'business',
    country: 'NG',
    currency: 'NGN',
  })
  const [saving, setSaving] = useState(false)

  const selectPreset = (preset: typeof PRESETS[0]) => {
    setForm((f) => ({ ...f, country: preset.country, currency: preset.currency }))
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.name.trim()) { toast.error('Organisation name is required'); return }

    setSaving(true)
    try {
      const { data } = await orgApi.create(form)
      setOrganisation(data)
      toast.success(`Welcome to ${data.name}!`)
      navigate('/dashboard')
    } catch (err: any) {
      if (!err.response) {
        toast.error('Cannot connect to server.')
        return
      }
      const detail = err.response?.data?.error?.detail
      const msg = typeof detail === 'object' && detail
        ? Object.values(detail).flat().join(' ')
        : (err.response?.data?.error?.message ?? 'Failed to create organisation.')
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-surface-950 flex items-center justify-center p-6">
      <div className="w-full max-w-lg space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-brand-500 rounded-xl flex items-center justify-center shadow-glow-orange">
            <Zap size={20} className="text-white" />
          </div>
          <h1 className="text-xl font-bold text-white">Finventory</h1>
        </div>

        <div className="card">
          <div className="flex items-center gap-3 mb-1">
            <div className="w-10 h-10 bg-brand-500/15 rounded-xl flex items-center justify-center">
              <Building2 size={20} className="text-brand-400" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-white">Set up your workspace</h2>
              <p className="text-slate-400 text-sm">
                {user?.first_name ? `Hey ${user.first_name}! ` : ''}Create your organisation to get started.
              </p>
            </div>
          </div>

          <form onSubmit={handleCreate} className="mt-6 space-y-5">
            {/* Org name */}
            <div>
              <label className="label">Organisation name *</label>
              <input
                className="input"
                placeholder="e.g., Ola Liquor Distributors Ltd"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                required
                autoFocus
              />
            </div>

            {/* Account type */}
            <div>
              <label className="label">Account type</label>
              <div className="grid grid-cols-2 gap-3">
                {ACCOUNT_TYPES.map((t) => (
                  <button
                    key={t.value}
                    type="button"
                    onClick={() => setForm((f) => ({ ...f, account_type: t.value }))}
                    className={`p-3.5 rounded-xl border text-left transition-all ${
                      form.account_type === t.value
                        ? 'bg-brand-500/15 border-brand-500 text-white'
                        : 'border-surface-600 text-slate-400 hover:border-surface-500'
                    }`}
                  >
                    <p className="font-semibold text-sm">{t.label}</p>
                    <p className="text-xs mt-0.5 opacity-75">{t.desc}</p>
                  </button>
                ))}
              </div>
            </div>

            {/* Country / Currency presets */}
            <div>
              <label className="label">Country & Currency</label>
              <div className="grid grid-cols-3 gap-2">
                {PRESETS.map((p) => (
                  <button
                    key={p.country}
                    type="button"
                    onClick={() => selectPreset(p)}
                    className={`py-2 px-3 rounded-xl border text-xs font-medium flex items-center gap-2 transition-all ${
                      form.country === p.country
                        ? 'bg-brand-500/15 border-brand-500 text-white'
                        : 'border-surface-600 text-slate-400 hover:border-surface-500'
                    }`}
                  >
                    <span>{p.flag}</span>
                    <span className="truncate">{p.label}</span>
                  </button>
                ))}
              </div>
              <p className="text-xs text-slate-500 mt-2">
                Currency: <span className="text-slate-400 font-mono">{form.currency}</span>
                {' · '}Country code: <span className="text-slate-400 font-mono">{form.country}</span>
              </p>
            </div>

            <button
              type="submit"
              disabled={saving}
              className="btn-primary w-full justify-center py-3 mt-2 disabled:opacity-50"
            >
              {saving ? 'Creating workspace…' : 'Create workspace & go to dashboard →'}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-slate-600">
          You can add more organisations and invite team members after setup.
        </p>
      </div>
    </div>
  )
}
