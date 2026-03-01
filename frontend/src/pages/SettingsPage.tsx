import { useState, useRef, useEffect } from 'react'
import { User, Building2, Shield, Loader2, Camera, CreditCard, CheckCircle } from 'lucide-react'
import toast from 'react-hot-toast'
import { authApi, orgApi, paymentGatewayApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import {
  getTimeoutPreference,
  setTimeoutPreference,
  type TimeoutOption,
} from '@/hooks/useInactivityTimeout'
import type { PaymentGatewayConfig } from '@/types'

const TIMEOUT_OPTIONS: { value: TimeoutOption; label: string }[] = [
  { value: 'never', label: 'Never' },
  { value: '30m', label: '30 minutes' },
  { value: '1h', label: '1 hour' },
  { value: '4h', label: '4 hours (recommended)' },
]

type Tab = 'profile' | 'company' | 'security' | 'payments'

export default function SettingsPage() {
  const { user, organisation, updateUser, updateOrganisation } = useAuthStore()
  const [tab, setTab] = useState<Tab>('profile')

  // ─── Profile state ─────────────────────────────────────────────────────────
  const [profile, setProfile] = useState({
    first_name: user?.first_name ?? '',
    last_name: user?.last_name ?? '',
    phone: user?.phone ?? '',
  })
  const [avatarFile, setAvatarFile] = useState<File | null>(null)
  const [avatarPreview, setAvatarPreview] = useState<string | null>(user?.avatar ?? null)
  const avatarRef = useRef<HTMLInputElement>(null)
  const [savingProfile, setSavingProfile] = useState(false)

  // ─── Company state ──────────────────────────────────────────────────────────
  const [company, setCompany] = useState({
    name: organisation?.name ?? '',
    country: organisation?.country ?? '',
    currency: organisation?.currency ?? '',
    tax_id: organisation?.tax_id ?? '',
    registration_number: organisation?.registration_number ?? '',
    address: organisation?.address ?? '',
    phone: organisation?.phone ?? '',
    email: organisation?.email ?? '',
  })
  const [logoFile, setLogoFile] = useState<File | null>(null)
  const [logoPreview, setLogoPreview] = useState<string | null>(organisation?.logo ?? null)
  const logoRef = useRef<HTMLInputElement>(null)
  const [savingCompany, setSavingCompany] = useState(false)

  // ─── Security state ─────────────────────────────────────────────────────────
  const [timeout, setTimeoutState] = useState<TimeoutOption>(getTimeoutPreference())

  // ─── Payment Gateway state ───────────────────────────────────────────────────
  const [gatewayConfig, setGatewayConfig] = useState<PaymentGatewayConfig | null>(null)
  const [gatewayId, setGatewayId] = useState<string | null>(null)
  const [paystackForm, setPaystackForm] = useState({ public_key: '', secret_key: '', webhook_secret: '', is_active: false })
  const [savingGateway, setSavingGateway] = useState(false)

  useEffect(() => {
    if (tab === 'payments') {
      paymentGatewayApi.configs().then(({ data }) => {
        const configs = data.results ?? data
        const ps = configs.find((c: PaymentGatewayConfig) => c.provider === 'paystack')
        if (ps) {
          setGatewayConfig(ps)
          setGatewayId(ps.id)
          setPaystackForm({ public_key: ps.public_key, secret_key: '', webhook_secret: '', is_active: ps.is_active })
        }
      }).catch(() => {})
    }
  }, [tab])

  // ─── Handlers ───────────────────────────────────────────────────────────────
  const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setAvatarFile(file)
    setAvatarPreview(URL.createObjectURL(file))
  }

  const handleLogoChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setLogoFile(file)
    setLogoPreview(URL.createObjectURL(file))
  }

  const saveProfile = async () => {
    setSavingProfile(true)
    try {
      const fd = new FormData()
      fd.append('first_name', profile.first_name)
      fd.append('last_name', profile.last_name)
      fd.append('phone', profile.phone)
      if (avatarFile) fd.append('avatar', avatarFile)
      const { data } = await authApi.updateProfile(fd)
      updateUser(data)
      toast.success('Profile updated')
    } catch {
      toast.error('Failed to update profile')
    } finally {
      setSavingProfile(false)
    }
  }

  const saveCompany = async () => {
    if (!organisation?.id) return
    setSavingCompany(true)
    try {
      const fd = new FormData()
      Object.entries(company).forEach(([k, v]) => fd.append(k, v))
      if (logoFile) fd.append('logo', logoFile)
      const { data } = await orgApi.update(organisation.id, fd)
      updateOrganisation(data)
      toast.success('Company settings saved')
    } catch {
      toast.error('Failed to save company settings')
    } finally {
      setSavingCompany(false)
    }
  }

  const saveSecurity = () => {
    setTimeoutPreference(timeout)
    toast.success('Security settings saved')
  }

  const saveGateway = async () => {
    setSavingGateway(true)
    try {
      const payload = { provider: 'paystack', ...paystackForm }
      if (gatewayId) {
        await paymentGatewayApi.updateConfig(gatewayId, payload)
      } else {
        const { data } = await paymentGatewayApi.createConfig(payload)
        setGatewayId(data.id)
      }
      toast.success('Paystack settings saved')
    } catch {
      toast.error('Failed to save payment gateway settings')
    } finally {
      setSavingGateway(false)
    }
  }

  const tabs: { id: Tab; label: string; icon: React.ElementType }[] = [
    { id: 'profile', label: 'My Profile', icon: User },
    { id: 'company', label: 'Company', icon: Building2 },
    { id: 'security', label: 'Security', icon: Shield },
    { id: 'payments', label: 'Payments', icon: CreditCard },
  ]

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-slate-400 text-sm">Manage your account and organisation</p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 p-1 bg-surface-800 border border-surface-700 rounded-xl w-fit">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              tab === t.id
                ? 'bg-brand-500 text-white shadow-glow-orange'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <t.icon size={15} />
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Profile ── */}
      {tab === 'profile' && (
        <div className="card p-6 space-y-6">
          {/* Avatar */}
          <div className="flex items-center gap-5">
            <div className="relative group">
              <div className="w-20 h-20 rounded-2xl bg-brand-500 flex items-center justify-center overflow-hidden">
                {avatarPreview ? (
                  <img src={avatarPreview} alt="avatar" className="w-full h-full object-cover" />
                ) : (
                  <span className="text-2xl font-bold text-white">
                    {user?.first_name?.[0]}{user?.last_name?.[0]}
                  </span>
                )}
              </div>
              <button
                onClick={() => avatarRef.current?.click()}
                className="absolute inset-0 rounded-2xl bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center"
              >
                <Camera size={18} className="text-white" />
              </button>
              <input ref={avatarRef} type="file" accept="image/*" className="hidden" onChange={handleAvatarChange} />
            </div>
            <div>
              <p className="font-semibold text-white">{user?.first_name} {user?.last_name}</p>
              <p className="text-sm text-slate-400">{user?.email}</p>
              <button onClick={() => avatarRef.current?.click()} className="text-xs text-brand-400 hover:text-brand-300 mt-1">
                Change photo
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">First Name</label>
              <input className="input" value={profile.first_name} onChange={(e) => setProfile({ ...profile, first_name: e.target.value })} />
            </div>
            <div>
              <label className="label">Last Name</label>
              <input className="input" value={profile.last_name} onChange={(e) => setProfile({ ...profile, last_name: e.target.value })} />
            </div>
            <div className="col-span-2">
              <label className="label">Phone</label>
              <input className="input" value={profile.phone} onChange={(e) => setProfile({ ...profile, phone: e.target.value })} placeholder="+234…" />
            </div>
          </div>

          <button onClick={saveProfile} disabled={savingProfile} className="btn-primary">
            {savingProfile ? <><Loader2 size={16} className="animate-spin" /> Saving…</> : 'Save Profile'}
          </button>
        </div>
      )}

      {/* ── Company ── */}
      {tab === 'company' && (
        <div className="card p-6 space-y-6">
          {/* Logo */}
          <div className="flex items-center gap-5">
            <div className="relative group">
              <div className="w-20 h-20 rounded-2xl bg-surface-700 border border-surface-600 flex items-center justify-center overflow-hidden">
                {logoPreview ? (
                  <img src={logoPreview} alt="logo" className="w-full h-full object-cover" />
                ) : (
                  <Building2 size={28} className="text-slate-500" />
                )}
              </div>
              <button
                onClick={() => logoRef.current?.click()}
                className="absolute inset-0 rounded-2xl bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center"
              >
                <Camera size={18} className="text-white" />
              </button>
              <input ref={logoRef} type="file" accept="image/*" className="hidden" onChange={handleLogoChange} />
            </div>
            <div>
              <p className="font-semibold text-white">{organisation?.name}</p>
              <p className="text-sm text-slate-400">{organisation?.currency} · {organisation?.country}</p>
              <button onClick={() => logoRef.current?.click()} className="text-xs text-brand-400 hover:text-brand-300 mt-1">
                Change logo
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className="label">Company Name</label>
              <input className="input" value={company.name} onChange={(e) => setCompany({ ...company, name: e.target.value })} />
            </div>
            <div>
              <label className="label">Country</label>
              <input className="input" value={company.country} onChange={(e) => setCompany({ ...company, country: e.target.value })} />
            </div>
            <div>
              <label className="label">Currency</label>
              <input className="input" value={company.currency} onChange={(e) => setCompany({ ...company, currency: e.target.value })} placeholder="NGN" />
            </div>
            <div>
              <label className="label">Tax ID</label>
              <input className="input" value={company.tax_id} onChange={(e) => setCompany({ ...company, tax_id: e.target.value })} />
            </div>
            <div>
              <label className="label">Registration Number</label>
              <input className="input" value={company.registration_number} onChange={(e) => setCompany({ ...company, registration_number: e.target.value })} />
            </div>
            <div>
              <label className="label">Phone</label>
              <input className="input" value={company.phone} onChange={(e) => setCompany({ ...company, phone: e.target.value })} />
            </div>
            <div>
              <label className="label">Email</label>
              <input type="email" className="input" value={company.email} onChange={(e) => setCompany({ ...company, email: e.target.value })} />
            </div>
            <div className="col-span-2">
              <label className="label">Address</label>
              <textarea className="input resize-none" rows={2} value={company.address}
                onChange={(e) => setCompany({ ...company, address: e.target.value })} />
            </div>
          </div>

          <button onClick={saveCompany} disabled={savingCompany} className="btn-primary">
            {savingCompany ? <><Loader2 size={16} className="animate-spin" /> Saving…</> : 'Save Company Settings'}
          </button>
        </div>
      )}

      {/* ── Payments ── */}
      {tab === 'payments' && (
        <div className="space-y-6">
          {/* Paystack */}
          <div className="card p-6 space-y-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-blue-500/15 rounded-xl flex items-center justify-center">
                  <CreditCard size={20} className="text-blue-400" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-white">Paystack Integration</h3>
                  <p className="text-slate-400 text-xs">Accept payments via Paystack — Nigeria's leading payment gateway</p>
                </div>
              </div>
              {gatewayConfig?.is_active && (
                <div className="flex items-center gap-1.5 text-emerald-400 text-sm font-medium">
                  <CheckCircle size={15} /> Active
                </div>
              )}
            </div>

            <label className="flex items-center gap-3 p-3 rounded-xl border border-surface-700 cursor-pointer hover:border-brand-500/40 transition-colors">
              <input type="checkbox" className="w-4 h-4 accent-orange-500"
                checked={paystackForm.is_active}
                onChange={(e) => setPaystackForm({ ...paystackForm, is_active: e.target.checked })} />
              <div>
                <span className="text-sm text-white">Enable Paystack payments</span>
                <p className="text-xs text-slate-500">When enabled, you can generate payment links from invoices</p>
              </div>
            </label>

            <div className="space-y-4">
              <div>
                <label className="label">Public Key</label>
                <input className="input font-mono text-sm" placeholder="pk_live_xxxxxxxxxxxx or pk_test_xxxxxxxxxxxx"
                  value={paystackForm.public_key} onChange={(e) => setPaystackForm({ ...paystackForm, public_key: e.target.value })} />
              </div>
              <div>
                <label className="label">Secret Key</label>
                <input type="password" className="input font-mono text-sm" placeholder="sk_live_xxxxxxxxxxxx (leave blank to keep current)"
                  value={paystackForm.secret_key} onChange={(e) => setPaystackForm({ ...paystackForm, secret_key: e.target.value })} />
                <p className="text-xs text-slate-500 mt-1">Stored securely. Never displayed after saving.</p>
              </div>
              <div>
                <label className="label">Webhook Secret</label>
                <input type="password" className="input font-mono text-sm" placeholder="From Paystack dashboard → Webhooks"
                  value={paystackForm.webhook_secret} onChange={(e) => setPaystackForm({ ...paystackForm, webhook_secret: e.target.value })} />
              </div>
            </div>

            <button onClick={saveGateway} disabled={savingGateway} className="btn-primary">
              {savingGateway ? <><Loader2 size={16} className="animate-spin" /> Saving…</> : 'Save Paystack Settings'}
            </button>
          </div>

          {/* Flutterwave */}
          <div className="card p-6 opacity-60">
            <div className="flex items-center gap-3 mb-3">
              <div className="w-10 h-10 bg-orange-500/15 rounded-xl flex items-center justify-center">
                <CreditCard size={20} className="text-orange-400" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-white">Flutterwave Integration</h3>
                <p className="text-slate-400 text-xs">Coming soon — Pan-African payment gateway</p>
              </div>
              <span className="ml-auto badge-slate">Coming Soon</span>
            </div>
            <p className="text-slate-500 text-sm">Flutterwave integration is planned for the next release. It will support NGN, GHS, KES, USD and 20+ African currencies.</p>
          </div>

          <div className="p-4 rounded-xl bg-surface-800 border border-surface-700">
            <p className="text-slate-400 text-sm">
              <span className="text-white font-semibold">How payment links work:</span>{' '}
              Once configured, an orange "Send Payment Link" button appears on every invoice. Customers receive a Paystack checkout link and can pay instantly. Invoice auto-marks as paid on successful payment.
            </p>
          </div>
        </div>
      )}

      {/* ── Security ── */}
      {tab === 'security' && (
        <div className="card p-6 space-y-6">
          <div>
            <h3 className="text-base font-semibold text-white mb-1">Inactivity Timeout</h3>
            <p className="text-sm text-slate-400 mb-4">Automatically sign you out after a period of inactivity.</p>
            <div className="space-y-2">
              {TIMEOUT_OPTIONS.map((opt) => (
                <label key={opt.value} className="flex items-center gap-3 p-3 rounded-xl border border-surface-700 cursor-pointer hover:border-surface-600 transition-colors">
                  <input
                    type="radio"
                    name="timeout"
                    value={opt.value}
                    checked={timeout === opt.value}
                    onChange={() => setTimeoutState(opt.value)}
                    className="accent-brand-500"
                  />
                  <span className="text-sm text-white">{opt.label}</span>
                </label>
              ))}
            </div>
          </div>

          <button onClick={saveSecurity} className="btn-primary">
            Save Security Settings
          </button>
        </div>
      )}
    </div>
  )
}
