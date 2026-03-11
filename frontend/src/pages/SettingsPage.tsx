import { useState, useRef, useEffect } from 'react'
import { User, Building2, Shield, Loader2, Camera, CreditCard, CheckCircle, Moon, Sun, Mail, Lock, Unlock, LandmarkIcon, UsersRound, UserPlus, X, ChevronDown, ChevronUp } from 'lucide-react'
import toast from 'react-hot-toast'
import { authApi, orgApi, paymentGatewayApi, accountingApi, teamApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import {
  getTimeoutPreference,
  setTimeoutPreference,
  type TimeoutOption,
} from '@/hooks/useInactivityTimeout'
import { getStoredTheme, setTheme, type Theme } from '@/hooks/useTheme'
import type { PaymentGatewayConfig, FinancialPeriod, TeamMember, ModuleKey, AccessLevel } from '@/types'

const ALL_MODULES: { key: ModuleKey; label: string }[] = [
  { key: 'sales', label: 'Sales / Invoices' },
  { key: 'purchases', label: 'Purchase Orders' },
  { key: 'bills', label: 'Bills / Payables' },
  { key: 'expenses', label: 'Expenses' },
  { key: 'inventory', label: 'Inventory' },
  { key: 'customers', label: 'Customers' },
  { key: 'suppliers', label: 'Suppliers' },
  { key: 'payroll', label: 'Payroll' },
  { key: 'reports', label: 'Reports' },
  { key: 'accounting', label: 'Accounting' },
  { key: 'tax', label: 'Tax' },
  { key: 'budget', label: 'Budget' },
  { key: 'quotes', label: 'Quotes' },
  { key: 'recurring', label: 'Recurring Invoices' },
]

const ACCESS_OPTIONS: { value: AccessLevel; label: string; color: string }[] = [
  { value: 'none', label: 'No Access', color: 'text-slate-500' },
  { value: 'view', label: 'View Only', color: 'text-blue-400' },
  { value: 'write', label: 'Enter & Save', color: 'text-green-400' },
  { value: 'edit', label: 'Full Edit', color: 'text-brand-400' },
]

const ROLE_BADGE: Record<string, string> = {
  owner: 'bg-purple-500/15 text-purple-400',
  admin: 'bg-brand-500/15 text-brand-400',
  manager: 'bg-blue-500/15 text-blue-400',
  accountant: 'bg-emerald-500/15 text-emerald-400',
  staff: 'bg-slate-500/15 text-slate-300',
  viewer: 'bg-slate-600/15 text-slate-400',
}

const MAX_MEMBERS = 3

// Full list of Nigerian banks (commercial, MFBs, mobile operators)
const NIGERIAN_BANKS = [
  // Commercial Banks
  { name: 'Access Bank', code: '044' },
  { name: 'Citibank Nigeria', code: '023' },
  { name: 'Ecobank Nigeria', code: '050' },
  { name: 'Fidelity Bank', code: '070' },
  { name: 'First Bank of Nigeria', code: '011' },
  { name: 'First City Monument Bank (FCMB)', code: '214' },
  { name: 'Guaranty Trust Bank (GTBank)', code: '058' },
  { name: 'Heritage Bank', code: '030' },
  { name: 'Keystone Bank', code: '082' },
  { name: 'Optimus Bank', code: '301' },
  { name: 'Polaris Bank', code: '076' },
  { name: 'Providus Bank', code: '101' },
  { name: 'Stanbic IBTC Bank', code: '221' },
  { name: 'Standard Chartered Bank', code: '068' },
  { name: 'Sterling Bank', code: '232' },
  { name: 'SunTrust Bank', code: '100' },
  { name: 'Titan Trust Bank', code: '102' },
  { name: 'Union Bank of Nigeria', code: '032' },
  { name: 'United Bank for Africa (UBA)', code: '033' },
  { name: 'Unity Bank', code: '215' },
  { name: 'Wema Bank', code: '035' },
  { name: 'Zenith Bank', code: '057' },
  // Digital / Fintech Banks
  { name: 'Carbon (OneFi)', code: '565' },
  { name: 'JAIZ Bank', code: '301' },
  { name: 'Kuda Microfinance Bank', code: '50211' },
  { name: 'Moniepoint Microfinance Bank', code: '50515' },
  { name: 'OPay (PayCom)', code: '100004' },
  { name: 'PalmPay', code: '999991' },
  { name: 'Sparkle Microfinance Bank', code: '51310' },
  { name: 'VFD Microfinance Bank', code: '566' },
  // Microfinance Banks
  { name: 'AB Microfinance Bank', code: '309' },
  { name: 'Accion MFB', code: '602' },
  { name: 'Covenant MFB', code: '551' },
  { name: 'LAPO Microfinance Bank', code: '501' },
  { name: 'NPF Microfinance Bank', code: '552' },
  // Mobile Money
  { name: 'MTN Mobile Money (MoMo PSB)', code: '120001' },
  { name: 'Airtel SmartCash PSB', code: '120004' },
  { name: '9 Payment Service Bank (9PSB)', code: '120005' },
].sort((a, b) => a.name.localeCompare(b.name))

const TIMEOUT_OPTIONS: { value: TimeoutOption; label: string }[] = [
  { value: 'never', label: 'Never' },
  { value: '30m', label: '30 minutes' },
  { value: '1h', label: '1 hour' },
  { value: '4h', label: '4 hours (recommended)' },
]

type Tab = 'profile' | 'company' | 'security' | 'payments' | 'email' | 'appearance' | 'periods' | 'team'

export default function SettingsPage() {
  const { user, organisation, updateUser, updateOrganisation, memberRole } = useAuthStore()
  const isOwner = !memberRole || memberRole === 'owner' || user?.is_superuser
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
    bank_name: organisation?.bank_name ?? '',
    bank_account_number: organisation?.bank_account_number ?? '',
    bank_account_name: organisation?.bank_account_name ?? '',
    bank_sort_code: organisation?.bank_sort_code ?? '',
  })

  // ─── Bank account resolve state ──────────────────────────────────────────────
  const [resolvingAccount, setResolvingAccount] = useState(false)

  const resolveAccountName = async (accountNumber: string, bankName: string) => {
    const bank = NIGERIAN_BANKS.find(b => b.name === bankName)
    if (!bank || accountNumber.length < 10) return
    setResolvingAccount(true)
    try {
      const { data } = await orgApi.resolveBankAccount(accountNumber, bank.code)
      if (data?.data?.account_name) {
        setCompany(c => ({ ...c, bank_account_name: data.data.account_name }))
        toast.success('Account name resolved')
      }
    } catch {
      // Silently ignore — user can type manually
    } finally {
      setResolvingAccount(false)
    }
  }

  // ─── Financial Periods state ─────────────────────────────────────────────────
  const [periods, setPeriods] = useState<FinancialPeriod[]>([])
  const [loadingPeriods, setLoadingPeriods] = useState(false)
  const [lockingPeriod, setLockingPeriod] = useState<string | null>(null)
  const [logoFile, setLogoFile] = useState<File | null>(null)
  const [logoPreview, setLogoPreview] = useState<string | null>(organisation?.logo ?? null)
  const logoRef = useRef<HTMLInputElement>(null)
  const [letterheadFile, setLetterheadFile] = useState<File | null>(null)
  const [letterheadPreview, setLetterheadPreview] = useState<string | null>(organisation?.letterhead ?? null)
  const letterheadRef = useRef<HTMLInputElement>(null)
  const [savingCompany, setSavingCompany] = useState(false)

  // ─── Security state ─────────────────────────────────────────────────────────
  const [timeout, setTimeoutState] = useState<TimeoutOption>(getTimeoutPreference())

  // ─── Appearance state ────────────────────────────────────────────────────────
  const [currentTheme, setCurrentTheme] = useState<Theme>(getStoredTheme())

  // ─── Email / SMTP state ──────────────────────────────────────────────────────
  const [emailForm, setEmailForm] = useState({
    smtp_host: 'smtp.gmail.com', smtp_port: '587', smtp_username: '',
    smtp_password: '', use_tls: true, from_name: '', from_email: '', is_active: false,
  })
  const [savingEmail, setSavingEmail] = useState(false)

  // ─── Payment Gateway state ───────────────────────────────────────────────────
  const [gatewayConfig, setGatewayConfig] = useState<PaymentGatewayConfig | null>(null)
  const [gatewayId, setGatewayId] = useState<string | null>(null)
  const [paystackForm, setPaystackForm] = useState({ public_key: '', secret_key: '', webhook_secret: '', is_active: false })
  const [savingGateway, setSavingGateway] = useState(false)

  // ─── Team state ──────────────────────────────────────────────────────────────
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([])
  const [loadingTeam, setLoadingTeam] = useState(false)
  const [subaccountForm, setSubaccountForm] = useState({ username: '', password: '', role: 'staff' })
  const [showSubaccountForm, setShowSubaccountForm] = useState(false)
  const [creatingSubaccount, setCreatingSubaccount] = useState(false)
  const [expandedMember, setExpandedMember] = useState<string | null>(null)
  // draft permissions per membership id: { module → access_level }
  const [draftPerms, setDraftPerms] = useState<Record<string, Record<ModuleKey, AccessLevel>>>({})
  const [savingPerms, setSavingPerms] = useState<string | null>(null)

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
    if (tab === 'email' && organisation?.id) {
      orgApi.getEmailConfig(organisation.id).then(({ data }) => {
        setEmailForm({
          smtp_host: data.smtp_host ?? 'smtp.gmail.com',
          smtp_port: String(data.smtp_port ?? 587),
          smtp_username: data.smtp_username ?? '',
          smtp_password: '',
          use_tls: data.use_tls ?? true,
          from_name: data.from_name ?? '',
          from_email: data.from_email ?? '',
          is_active: data.is_active ?? false,
        })
      }).catch(() => {})
    }
    if (tab === 'periods') {
      setLoadingPeriods(true)
      accountingApi.periods().then(({ data }) => {
        setPeriods(Array.isArray(data) ? data : data.results ?? [])
      }).catch(() => toast.error('Failed to load periods')).finally(() => setLoadingPeriods(false))
    }
    if (tab === 'team') {
      setLoadingTeam(true)
      teamApi.members().then(({ data }) => {
        const members: TeamMember[] = Array.isArray(data) ? data : data.results ?? []
        setTeamMembers(members)
        // Initialise draft permissions from existing records
        const drafts: Record<string, Record<ModuleKey, AccessLevel>> = {}
        members.forEach((m) => {
          const map: Record<ModuleKey, AccessLevel> = {} as Record<ModuleKey, AccessLevel>
          ALL_MODULES.forEach(({ key }) => { map[key] = 'edit' })
          m.module_permissions.forEach((p) => { map[p.module] = p.access_level })
          drafts[m.id] = map
        })
        setDraftPerms(drafts)
      }).catch(() => toast.error('Failed to load team members')).finally(() => setLoadingTeam(false))
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

  const handleLetterheadChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setLetterheadFile(file)
    setLetterheadPreview(URL.createObjectURL(file))
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
      if (letterheadFile) fd.append('letterhead', letterheadFile)
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

  const handleThemeChange = (theme: Theme) => {
    setTheme(theme)
    setCurrentTheme(theme)
    toast.success(`Switched to ${theme} mode`)
  }

  const saveEmail = async () => {
    if (!organisation?.id) return
    setSavingEmail(true)
    try {
      const payload: Record<string, string | number | boolean> = {
        smtp_host: emailForm.smtp_host,
        smtp_port: parseInt(emailForm.smtp_port) || 587,
        smtp_username: emailForm.smtp_username,
        use_tls: emailForm.use_tls,
        from_name: emailForm.from_name,
        from_email: emailForm.from_email,
        is_active: emailForm.is_active,
      }
      if (emailForm.smtp_password) payload.smtp_password = emailForm.smtp_password
      await orgApi.saveEmailConfig(organisation.id, payload)
      toast.success('Email settings saved')
    } catch {
      toast.error('Failed to save email settings')
    } finally {
      setSavingEmail(false)
    }
  }

  const handleLockToggle = async (period: FinancialPeriod) => {
    setLockingPeriod(period.id)
    try {
      if (period.is_locked) {
        await accountingApi.unlockPeriod(period.id)
        toast.success(`Period ${period.year}-${String(period.month).padStart(2, '0')} unlocked`)
      } else {
        await accountingApi.lockPeriod(period.id)
        toast.success(`Period ${period.year}-${String(period.month).padStart(2, '0')} locked`)
      }
      const { data } = await accountingApi.periods()
      setPeriods(Array.isArray(data) ? data : data.results ?? [])
    } catch {
      toast.error('Failed to update period lock')
    } finally {
      setLockingPeriod(null)
    }
  }

  const createPeriod = async () => {
    const now = new Date()
    try {
      await accountingApi.createPeriod({ year: now.getFullYear(), month: now.getMonth() + 1 })
      const { data } = await accountingApi.periods()
      setPeriods(Array.isArray(data) ? data : data.results ?? [])
      toast.success('Period created')
    } catch {
      toast.error('Period may already exist')
    }
  }

  const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

  const handleCreateSubaccount = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!organisation?.id) return
    setCreatingSubaccount(true)
    try {
      await orgApi.createSubaccount(organisation.id, subaccountForm)
      toast.success(`Sub-account ${subaccountForm.username}@${organisation.slug} created`)
      setShowSubaccountForm(false)
      setSubaccountForm({ username: '', password: '', role: 'staff' })
      const { data } = await teamApi.members()
      setTeamMembers(Array.isArray(data) ? data : data.results ?? [])
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: { message?: string } | string } } })?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to create sub-account')
      toast.error(msg)
    } finally {
      setCreatingSubaccount(false)
    }
  }

  const handleDeactivate = async (m: TeamMember) => {
    if (!confirm(`Deactivate ${m.user_full_name || m.user_email}? They will lose access immediately.`)) return
    try {
      await teamApi.updateMember(m.id, { is_active: false })
      toast.success('Member deactivated')
      setTeamMembers((prev) => prev.map((tm) => tm.id === m.id ? { ...tm, is_active: false } : tm))
    } catch {
      toast.error('Failed to deactivate member')
    }
  }

  const handleReactivate = async (m: TeamMember) => {
    try {
      await teamApi.updateMember(m.id, { is_active: true })
      toast.success('Member reactivated')
      setTeamMembers((prev) => prev.map((tm) => tm.id === m.id ? { ...tm, is_active: true } : tm))
    } catch {
      toast.error('Failed to reactivate member')
    }
  }

  const handleSavePermissions = async (memberId: string) => {
    setSavingPerms(memberId)
    try {
      const perms = draftPerms[memberId]
      const permissions = ALL_MODULES.map(({ key }) => ({ module: key, access_level: perms[key] ?? 'edit' }))
      const { data } = await teamApi.setPermissions(memberId, permissions)
      toast.success('Permissions saved')
      setTeamMembers((prev) => prev.map((m) => m.id === memberId ? data : m))
    } catch {
      toast.error('Failed to save permissions')
    } finally {
      setSavingPerms(null)
    }
  }

  const activeNonOwners = teamMembers.filter((m) => m.is_active && m.role !== 'owner')

  const tabs: { id: Tab; label: string; icon: React.ElementType }[] = [
    { id: 'profile', label: 'My Profile', icon: User },
    { id: 'company', label: 'Company', icon: Building2 },
    { id: 'team', label: 'Team', icon: UsersRound },
    { id: 'security', label: 'Security', icon: Shield },
    { id: 'payments', label: 'Payments', icon: CreditCard },
    { id: 'email', label: 'Email', icon: Mail },
    { id: 'periods', label: 'Periods', icon: Lock },
    { id: 'appearance', label: 'Appearance', icon: Moon },
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

          {/* Banking Details */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <LandmarkIcon size={16} className="text-brand-400" />
              <h3 className="text-sm font-semibold text-white">Banking Details</h3>
              <span className="text-xs text-slate-500">— automatically included in invoices</span>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="label">Bank Name</label>
                <select
                  className="input"
                  value={company.bank_name}
                  onChange={(e) => {
                    const bankName = e.target.value
                    const bank = NIGERIAN_BANKS.find(b => b.name === bankName)
                    setCompany({ ...company, bank_name: bankName, bank_sort_code: bank?.code ?? company.bank_sort_code })
                    if (company.bank_account_number.length >= 10) resolveAccountName(company.bank_account_number, bankName)
                  }}
                >
                  <option value="">Select bank…</option>
                  {NIGERIAN_BANKS.map(b => (
                    <option key={b.code + b.name} value={b.name}>{b.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Sort Code / Bank Code</label>
                <input className="input font-mono" placeholder="Auto-filled when bank selected" value={company.bank_sort_code}
                  onChange={(e) => setCompany({ ...company, bank_sort_code: e.target.value })} />
              </div>
              <div>
                <label className="label">Account Number</label>
                <input
                  className="input font-mono"
                  placeholder="10-digit NUBAN"
                  value={company.bank_account_number}
                  maxLength={10}
                  onChange={(e) => {
                    const num = e.target.value.replace(/\D/g, '')
                    setCompany({ ...company, bank_account_number: num })
                    if (num.length === 10 && company.bank_name) resolveAccountName(num, company.bank_name)
                  }}
                />
              </div>
              <div>
                <label className="label flex items-center gap-2">
                  Account Name
                  {resolvingAccount && <Loader2 size={12} className="animate-spin text-brand-400" />}
                  {!resolvingAccount && company.bank_account_name && <CheckCircle size={12} className="text-emerald-400" />}
                </label>
                <input className="input" placeholder="Auto-resolved or type manually" value={company.bank_account_name}
                  onChange={(e) => setCompany({ ...company, bank_account_name: e.target.value })} />
              </div>
            </div>
          </div>

          {/* Letterhead / Invoice Template */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Camera size={16} className="text-brand-400" />
              <h3 className="text-sm font-semibold text-white">Letterhead / Invoice Template</h3>
              <span className="text-xs text-slate-500">— appears at the top of invoices, statements &amp; PDFs</span>
            </div>
            <div className="flex items-start gap-5">
              {/* Preview box */}
              <div
                className="relative group w-48 h-20 rounded-xl border-2 border-dashed border-surface-600 bg-surface-700/30 flex items-center justify-center overflow-hidden cursor-pointer hover:border-brand-500/50 transition-colors shrink-0"
                onClick={() => letterheadRef.current?.click()}
              >
                {letterheadPreview ? (
                  <img src={letterheadPreview} alt="letterhead" className="w-full h-full object-contain" />
                ) : (
                  <div className="text-center text-slate-500">
                    <Camera size={20} className="mx-auto mb-1" />
                    <p className="text-xs">Click to upload</p>
                  </div>
                )}
                <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center rounded-xl">
                  <Camera size={18} className="text-white" />
                </div>
                <input
                  ref={letterheadRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={handleLetterheadChange}
                />
              </div>
              <div className="space-y-2 text-sm text-slate-400 pt-1">
                <p>Upload your company letterhead or a branded banner (PNG, JPG recommended).</p>
                <p className="text-xs">Ideal size: <span className="text-slate-300">1200 × 300 px</span> or similar wide banner format.</p>
                {letterheadPreview && (
                  <button
                    type="button"
                    onClick={() => { setLetterheadFile(null); setLetterheadPreview(null) }}
                    className="text-xs text-red-400 hover:text-red-300 transition-colors"
                  >
                    Remove letterhead
                  </button>
                )}
              </div>
            </div>
          </div>

          <button onClick={saveCompany} disabled={savingCompany} className="btn-primary">
            {savingCompany ? <><Loader2 size={16} className="animate-spin" /> Saving…</> : 'Save Company Settings'}
          </button>
        </div>
      )}

      {/* ── Financial Periods ── */}
      {tab === 'periods' && (
        <div className="card p-6 space-y-5">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-base font-semibold text-white">Financial Period Locking</h3>
              <p className="text-slate-400 text-xs mt-0.5">Lock periods to prevent new transactions from being posted to closed months</p>
            </div>
            {isOwner && (
              <button onClick={createPeriod} className="btn-primary text-sm">
                + Create Current Period
              </button>
            )}
          </div>

          {loadingPeriods ? (
            <div className="flex justify-center py-8"><Loader2 className="animate-spin text-slate-500" size={24} /></div>
          ) : periods.length === 0 ? (
            <div className="text-center py-8 text-slate-500">
              <Lock size={32} className="mx-auto mb-2 opacity-30" />
              <p className="text-sm">No financial periods created yet.</p>
              <p className="text-xs mt-1">Click "Create Current Period" to add the current month.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {periods.map((p) => (
                <div key={p.id} className={`flex items-center justify-between p-4 rounded-xl border ${p.is_locked ? 'border-red-500/30 bg-red-500/5' : 'border-surface-700'}`}>
                  <div>
                    <p className="text-white font-semibold">{MONTHS[p.month - 1]} {p.year}</p>
                    {p.is_locked && p.locked_by_name && (
                      <p className="text-xs text-slate-500">Locked by {p.locked_by_name}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={`text-xs font-medium px-2 py-1 rounded-lg ${p.is_locked ? 'bg-red-500/15 text-red-400' : 'bg-green-500/15 text-green-400'}`}>
                      {p.is_locked ? 'LOCKED' : 'OPEN'}
                    </span>
                    {isOwner && (
                      <button
                        onClick={() => handleLockToggle(p)}
                        disabled={lockingPeriod === p.id}
                        className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-colors disabled:opacity-50 ${
                          p.is_locked
                            ? 'border-green-500/30 text-green-400 hover:bg-green-500/10'
                            : 'border-red-500/30 text-red-400 hover:bg-red-500/10'
                        }`}
                      >
                        {lockingPeriod === p.id ? <Loader2 size={12} className="animate-spin" /> : p.is_locked ? <Unlock size={12} /> : <Lock size={12} />}
                        {p.is_locked ? 'Unlock' : 'Lock'}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Team Members ── */}
      {tab === 'team' && (
        <div className="space-y-5">
          {/* Header */}
          <div className="card p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-base font-semibold text-white">Team Members</h3>
                <p className="text-slate-400 text-xs mt-0.5">
                  Invite up to {MAX_MEMBERS} sub-accounts. Set per-module access for each member.
                  Owners and admins always have full access.
                </p>
                <p className="text-xs mt-2">
                  <span className={activeNonOwners.length >= MAX_MEMBERS ? 'text-red-400' : 'text-slate-400'}>
                    {activeNonOwners.length} / {MAX_MEMBERS} slots used
                  </span>
                </p>
              </div>
              {activeNonOwners.length < MAX_MEMBERS && (
                <button onClick={() => setShowSubaccountForm((v) => !v)} className="btn-primary shrink-0">
                  <UserPlus size={14} /> Add Member
                </button>
              )}
            </div>

            {/* Sub-account creation form */}
            {showSubaccountForm && (
              <form onSubmit={handleCreateSubaccount} className="mt-4 p-4 rounded-xl bg-surface-700 border border-surface-600 space-y-3">
                <div className="flex items-center justify-between mb-1">
                  <div>
                    <span className="text-sm font-medium text-white">Create Sub-Account</span>
                    <p className="text-xs text-slate-500 mt-0.5">
                      Login email will be: <span className="text-brand-400 font-mono">{subaccountForm.username || 'username'}@{organisation?.slug}</span>
                    </p>
                  </div>
                  <button type="button" onClick={() => setShowSubaccountForm(false)} className="btn-ghost p-1"><X size={14} /></button>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="label">Username *</label>
                    <input
                      required className="input" placeholder="e.g. john.doe"
                      value={subaccountForm.username}
                      onChange={(e) => setSubaccountForm({ ...subaccountForm, username: e.target.value.toLowerCase().replace(/\s+/g, '.') })}
                    />
                  </div>
                  <div>
                    <label className="label">Role</label>
                    <select className="input" value={subaccountForm.role} onChange={(e) => setSubaccountForm({ ...subaccountForm, role: e.target.value })}>
                      <option value="manager">Manager</option>
                      <option value="accountant">Accountant</option>
                      <option value="staff">Staff</option>
                      <option value="viewer">Viewer (read-only)</option>
                    </select>
                  </div>
                  <div className="col-span-2">
                    <label className="label">Password *</label>
                    <input
                      type="password" required className="input" placeholder="Set a strong password"
                      value={subaccountForm.password}
                      onChange={(e) => setSubaccountForm({ ...subaccountForm, password: e.target.value })}
                    />
                  </div>
                </div>
                <div className="flex justify-end gap-2">
                  <button type="button" onClick={() => setShowSubaccountForm(false)} className="btn-secondary text-sm">Cancel</button>
                  <button type="submit" disabled={creatingSubaccount} className="btn-primary text-sm">
                    {creatingSubaccount ? <Loader2 size={14} className="animate-spin" /> : <><UserPlus size={13} /> Create Account</>}
                  </button>
                </div>
              </form>
            )}
          </div>

          {/* Member list */}
          {loadingTeam ? (
            <div className="flex justify-center py-8"><Loader2 className="animate-spin text-slate-500" size={24} /></div>
          ) : teamMembers.length === 0 ? (
            <div className="card p-8 text-center">
              <UsersRound size={32} className="mx-auto mb-2 text-slate-600" />
              <p className="text-slate-400 text-sm">No team members yet. Invite someone to get started.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {teamMembers.map((m) => (
                <div key={m.id} className={`card overflow-hidden ${!m.is_active ? 'opacity-60' : ''}`}>
                  {/* Member header row */}
                  <div className="flex items-center gap-3 p-4">
                    <div className="w-9 h-9 rounded-xl bg-surface-700 flex items-center justify-center text-sm font-bold text-white shrink-0">
                      {(m.user_full_name || m.user_email)[0]?.toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-white font-medium text-sm truncate">{m.user_full_name || '—'}</p>
                        {organisation?.slug && m.user_email.endsWith(`@${organisation.slug}`) && (
                          <span className="text-xs bg-brand-500/15 text-brand-400 px-1.5 py-0.5 rounded-md shrink-0">sub-account</span>
                        )}
                      </div>
                      <p className="text-xs text-slate-500 truncate">{m.user_email}</p>
                    </div>
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-lg capitalize ${ROLE_BADGE[m.role] ?? 'bg-slate-700 text-slate-300'}`}>
                      {m.role}
                    </span>
                    {!m.is_active && <span className="text-xs text-red-400 bg-red-500/10 px-2 py-0.5 rounded-lg">Inactive</span>}

                    {/* Actions — only for non-owners */}
                    {m.role !== 'owner' && (
                      <div className="flex items-center gap-1">
                        {m.is_active ? (
                          <button onClick={() => handleDeactivate(m)} className="text-xs text-slate-500 hover:text-red-400 px-2 py-1 rounded-lg hover:bg-red-500/10 transition-colors">
                            Deactivate
                          </button>
                        ) : (
                          <button onClick={() => handleReactivate(m)} className="text-xs text-slate-500 hover:text-green-400 px-2 py-1 rounded-lg hover:bg-green-500/10 transition-colors">
                            Reactivate
                          </button>
                        )}
                        <button
                          onClick={() => setExpandedMember(expandedMember === m.id ? null : m.id)}
                          className="btn-ghost p-1.5 text-slate-500 hover:text-white"
                          title="Manage permissions"
                        >
                          {expandedMember === m.id ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
                        </button>
                      </div>
                    )}
                  </div>

                  {/* Permissions matrix — expanded */}
                  {expandedMember === m.id && m.role !== 'owner' && (
                    <div className="border-t border-surface-700 p-4 space-y-3">
                      <p className="text-xs text-slate-400 font-medium uppercase tracking-wider">Module Permissions</p>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {ALL_MODULES.map(({ key, label }) => {
                          const current = draftPerms[m.id]?.[key] ?? 'edit'
                          return (
                            <div key={key} className="flex items-center justify-between gap-2 py-1.5 px-3 rounded-lg bg-surface-800">
                              <span className="text-sm text-slate-300">{label}</span>
                              <select
                                className="bg-surface-700 border border-surface-600 text-xs rounded-lg px-2 py-1 text-white focus:outline-none focus:border-brand-500"
                                value={current}
                                onChange={(e) => setDraftPerms((prev) => ({
                                  ...prev,
                                  [m.id]: { ...prev[m.id], [key]: e.target.value as AccessLevel },
                                }))}
                              >
                                {ACCESS_OPTIONS.map((opt) => (
                                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                                ))}
                              </select>
                            </div>
                          )
                        })}
                      </div>
                      <div className="flex items-center justify-between pt-2">
                        <p className="text-xs text-slate-500">Changes apply on the member's next page load.</p>
                        <button
                          onClick={() => handleSavePermissions(m.id)}
                          disabled={savingPerms === m.id}
                          className="btn-primary text-sm"
                        >
                          {savingPerms === m.id ? <Loader2 size={14} className="animate-spin" /> : 'Save Permissions'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Info box */}
          <div className="p-4 rounded-xl bg-surface-800 border border-surface-700 text-sm text-slate-400">
            <p><span className="text-white font-semibold">How it works:</span> Invited members receive an email with a sign-up link. Once they join, you can restrict their access per module.
            Owners and admins always retain full access and cannot be restricted.</p>
          </div>
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

      {/* ── Email / SMTP ── */}
      {tab === 'email' && (
        <div className="card p-6 space-y-5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-brand-500/15 rounded-xl flex items-center justify-center">
              <Mail size={20} className="text-brand-400" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white">SMTP Email Settings</h3>
              <p className="text-slate-400 text-xs">Configure outgoing email to send invoices and quotes to customers</p>
            </div>
          </div>

          <label className="flex items-center gap-3 p-3 rounded-xl border border-surface-700 cursor-pointer hover:border-brand-500/40 transition-colors">
            <input type="checkbox" className="w-4 h-4 accent-orange-500"
              checked={emailForm.is_active}
              onChange={(e) => setEmailForm({ ...emailForm, is_active: e.target.checked })} />
            <div>
              <span className="text-sm text-white">Enable email sending</span>
              <p className="text-xs text-slate-500">When enabled, you can send invoices directly from the app</p>
            </div>
          </label>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">SMTP Host</label>
              <input className="input" placeholder="smtp.gmail.com" value={emailForm.smtp_host}
                onChange={(e) => setEmailForm({ ...emailForm, smtp_host: e.target.value })} />
            </div>
            <div>
              <label className="label">SMTP Port</label>
              <input type="text" inputMode="numeric" className="input" placeholder="587" value={emailForm.smtp_port}
                onChange={(e) => setEmailForm({ ...emailForm, smtp_port: e.target.value })} />
            </div>
            <div>
              <label className="label">Username / Email</label>
              <input className="input" placeholder="yourname@gmail.com" value={emailForm.smtp_username}
                onChange={(e) => setEmailForm({ ...emailForm, smtp_username: e.target.value })} />
            </div>
            <div>
              <label className="label">Password / App Password</label>
              <input type="password" className="input" placeholder="Leave blank to keep current"
                value={emailForm.smtp_password}
                onChange={(e) => setEmailForm({ ...emailForm, smtp_password: e.target.value })} />
              <p className="text-xs text-slate-500 mt-1">Use an App Password for Gmail.</p>
            </div>
            <div>
              <label className="label">From Name</label>
              <input className="input" placeholder="Your Business Name" value={emailForm.from_name}
                onChange={(e) => setEmailForm({ ...emailForm, from_name: e.target.value })} />
            </div>
            <div>
              <label className="label">From Email</label>
              <input type="email" className="input" placeholder="noreply@yourdomain.com" value={emailForm.from_email}
                onChange={(e) => setEmailForm({ ...emailForm, from_email: e.target.value })} />
            </div>
          </div>

          <label className="flex items-center gap-3 cursor-pointer">
            <input type="checkbox" className="w-4 h-4 accent-orange-500"
              checked={emailForm.use_tls}
              onChange={(e) => setEmailForm({ ...emailForm, use_tls: e.target.checked })} />
            <span className="text-sm text-slate-300">Use TLS/STARTTLS (recommended)</span>
          </label>

          <div className="p-3 rounded-xl bg-surface-800 border border-surface-700">
            <p className="text-slate-400 text-xs">
              <span className="text-white font-medium">Gmail tip:</span>{' '}
              Enable 2FA, then create an App Password at myaccount.google.com → Security → App Passwords. Use that as your password here.
            </p>
          </div>

          <button onClick={saveEmail} disabled={savingEmail} className="btn-primary">
            {savingEmail ? <><Loader2 size={16} className="animate-spin" /> Saving…</> : 'Save Email Settings'}
          </button>
        </div>
      )}

      {/* ── Appearance ── */}
      {tab === 'appearance' && (
        <div className="card p-6 space-y-6">
          <div>
            <h3 className="text-base font-semibold text-white mb-1">Theme</h3>
            <p className="text-sm text-slate-400 mb-4">Choose between dark and light mode. Your preference is saved locally.</p>
            <div className="grid grid-cols-2 gap-4">
              <button
                onClick={() => handleThemeChange('dark')}
                className={`flex flex-col items-center gap-3 p-5 rounded-2xl border-2 transition-all ${
                  currentTheme === 'dark'
                    ? 'border-brand-500 bg-brand-500/10'
                    : 'border-surface-700 hover:border-surface-600'
                }`}
              >
                <div className="w-14 h-14 rounded-2xl bg-surface-900 border border-surface-700 flex items-center justify-center">
                  <Moon size={26} className="text-slate-300" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-semibold text-white">Dark Mode</p>
                  <p className="text-xs text-slate-500 mt-0.5">Easy on the eyes</p>
                </div>
                {currentTheme === 'dark' && (
                  <CheckCircle size={16} className="text-brand-400" />
                )}
              </button>

              <button
                onClick={() => handleThemeChange('light')}
                className={`flex flex-col items-center gap-3 p-5 rounded-2xl border-2 transition-all ${
                  currentTheme === 'light'
                    ? 'border-brand-500 bg-brand-500/10'
                    : 'border-surface-700 hover:border-surface-600'
                }`}
              >
                <div className="w-14 h-14 rounded-2xl bg-slate-100 border border-slate-200 flex items-center justify-center">
                  <Sun size={26} className="text-amber-500" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-semibold text-white">Light Mode</p>
                  <p className="text-xs text-slate-500 mt-0.5">Bright and clear</p>
                </div>
                {currentTheme === 'light' && (
                  <CheckCircle size={16} className="text-brand-400" />
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
