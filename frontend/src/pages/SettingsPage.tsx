import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { User, Building2, Shield, Loader2, Camera, CreditCard, CheckCircle, Mail, Lock, Unlock, LandmarkIcon, UsersRound, UserPlus, X, ChevronDown, ChevronUp, Bot, Layout, Copy, Trash2, ShieldCheck, Key, Clock, XCircle, Send, Globe, AlertTriangle, Wifi, WifiOff, RefreshCw, Activity, FileText, GitBranch } from 'lucide-react'
import toast from 'react-hot-toast'
import { authApi, orgApi, paymentGatewayApi, accountingApi, teamApi, tauriFetch, partnerApi, einvoicingApi } from '@/services/api'
import type { FirsConfig, FirsStats, FirsSubmission, SandboxProgress, GoLiveChecklist } from '@/types'
import type { AxiosError } from 'axios'
import { useAuthStore } from '@/store/authStore'
import { FEATURES } from '@/lib/featureFlags'
import {
  getTimeoutPreference,
  setTimeoutPreference,
  type TimeoutOption,
} from '@/hooks/useInactivityTimeout'
import type { PaymentGatewayConfig, FinancialPeriod, TeamMember, ModuleKey, AccessLevel, PartnerAccessRequest, PartnerClientLink } from '@/types'

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
  { key: 'settings', label: 'Settings (Company / Billing)' },
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

// Derive max members from the plan name; backend enforces the real limit.
function getPlanMaxMembers(planName: string | null): number {
  if (!planName) return 3
  if (planName.includes('enterprise')) return 999
  if (planName.includes('business')) return 5
  if (planName.includes('professional')) return 3
  return 1 // free / unknown
}

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

type Tab = 'profile' | 'company' | 'security' | 'payments' | 'email' | 'periods' | 'team' | 'invoice_templates' | 'ai' | 'access' | 'whitelabel' | 'firs' | 'gl_mapping'

export default function SettingsPage() {
  const navigate = useNavigate()
  const { user, organisation, updateUser, updateOrganisation, memberRole, modulePermissions, planModules, planName } = useAuthStore()
  // Owners, admins, and superusers have full settings access
  const isOwner = memberRole === 'owner' || memberRole === 'admin' || user?.is_superuser === true
  // Sub-accounts need explicit 'settings' module permission to access org settings tabs
  const hasSettingsPerm = isOwner || ((): boolean => {
    const lvl = modulePermissions?.['settings'] ?? 'none'
    return lvl !== 'none'
  })()
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
    brand_color: organisation?.brand_color ?? '#f97316',
    invoice_company_name: organisation?.invoice_company_name ?? '',
    company_name_font: organisation?.company_name_font ?? 'helvetica',
    company_name_font_color: organisation?.company_name_font_color ?? '#1e293b',
    company_name_font_size: organisation?.company_name_font_size ?? 14,
    company_name_font_bold: organisation?.company_name_font_bold ?? true,
    company_name_font_italic: organisation?.company_name_font_italic ?? false,
    company_name_font_underline: organisation?.company_name_font_underline ?? false,
    show_company_name_on_pdf: organisation?.show_company_name_on_pdf ?? true,
    invoice_template: organisation?.invoice_template ?? 'classic',
    pension_provider: organisation?.pension_provider ?? '',
    ai_custom_context: organisation?.ai_custom_context ?? '',
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
  const [logoRemoved, setLogoRemoved] = useState(false)
  const logoRef = useRef<HTMLInputElement>(null)
  const [stampFile, setStampFile] = useState<File | null>(null)
  const [stampPreview, setStampPreview] = useState<string | null>(organisation?.company_stamp ?? null)
  const [stampRemoved, setStampRemoved] = useState(false)
  const stampRef = useRef<HTMLInputElement>(null)
  const [savingCompany, setSavingCompany] = useState(false)

  // ─── Load existing org/user images as data URLs (Tauri <img> can't reach http://localhost:8000 directly)
  useEffect(() => {
    const loadDataUrl = async (url: string | null | undefined): Promise<string | null> => {
      if (!url) return null
      try {
        const res = await tauriFetch(url)
        const blob = await res.blob()
        return await new Promise<string>((resolve, reject) => {
          const r = new FileReader()
          r.onloadend = () => resolve(r.result as string)
          r.onerror = reject
          r.readAsDataURL(blob)
        })
      } catch { return null }
    }
    if (organisation?.logo && !logoFile && !logoRemoved)
      loadDataUrl(organisation.logo).then((d) => { if (d) setLogoPreview(d) })
    if (organisation?.company_stamp && !stampFile && !stampRemoved)
      loadDataUrl(organisation.company_stamp).then((d) => { if (d) setStampPreview(d) })
    if (user?.avatar && !avatarFile)
      loadDataUrl(user.avatar).then((d) => { if (d) setAvatarPreview(d) })
  }, [organisation?.logo, organisation?.company_stamp, user?.avatar])

  // ─── Security state ─────────────────────────────────────────────────────────
  const [timeout, setTimeoutState] = useState<TimeoutOption>(getTimeoutPreference())

  // MFA state
  const [mfaStep, setMfaStep] = useState<'idle' | 'setup' | 'confirm' | 'backup' | 'disable'>('idle')
  const [mfaQr, setMfaQr] = useState('')
  const [mfaSecret, setMfaSecret] = useState('')
  const [mfaCode, setMfaCode] = useState('')
  const [mfaDisablePassword, setMfaDisablePassword] = useState('')
  const [mfaLoading, setMfaLoading] = useState(false)
  const [backupCodes, setBackupCodes] = useState<string[]>([])
  const [mfaEnabled, setMfaEnabled] = useState(user?.mfa_enabled ?? false)
  const [mfaSecretCopied, setMfaSecretCopied] = useState(false)

  const handleMFASetup = async () => {
    setMfaLoading(true)
    try {
      const { data } = await authApi.mfaSetup()
      setMfaQr(data.qr_data_url)
      // Extract the secret from the provisioning URI for manual entry
      const match = data.provisioning_uri?.match(/[?&]secret=([^&]+)/)
      setMfaSecret(match ? match[1] : '')
      setMfaStep('setup')
    } catch (err: any) {
      const msg = err.response?.data?.error?.message ?? 'Failed to start MFA setup.'
      toast.error(msg)
    } finally {
      setMfaLoading(false)
    }
  }

  const handleMFAConfirm = async () => {
    setMfaLoading(true)
    try {
      const { data } = await authApi.mfaConfirmSetup(mfaCode)
      setBackupCodes(data.backup_codes)
      setMfaEnabled(true)
      updateUser({ mfa_enabled: true })  // sync to persisted store
      setMfaStep('backup')
      setMfaCode('')
    } catch (err: any) {
      const msg = err.response?.data?.error?.message ?? 'Invalid code. Try again.'
      toast.error(msg)
    } finally {
      setMfaLoading(false)
    }
  }

  const handleMFADisable = async () => {
    setMfaLoading(true)
    try {
      await authApi.mfaDisable(mfaCode, mfaDisablePassword)
      setMfaEnabled(false)
      updateUser({ mfa_enabled: false })  // sync to persisted store
      setMfaStep('idle')
      setMfaCode('')
      setMfaDisablePassword('')
      toast.success('MFA disabled.')
    } catch (err: any) {
      const msg = err.response?.data?.error?.message ?? 'Invalid code or password.'
      toast.error(msg)
    } finally {
      setMfaLoading(false)
    }
  }

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
  const [subaccountForm, setSubaccountForm] = useState({ username: '', password: '', role: 'staff', first_name: '', last_name: '', notify_email: '' })
  const [showSubaccountForm, setShowSubaccountForm] = useState(false)
  const [creatingSubaccount, setCreatingSubaccount] = useState(false)
  const [expandedMember, setExpandedMember] = useState<string | null>(null)
  // draft permissions per membership id: { module → access_level }
  const [draftPerms, setDraftPerms] = useState<Record<string, Record<ModuleKey, AccessLevel>>>({})
  const [savingPerms, setSavingPerms] = useState<string | null>(null)
  // Deactivate confirmation modal
  const [deactivateTarget, setDeactivateTarget] = useState<TeamMember | null>(null)
  const [deactivating, setDeactivating] = useState(false)
  // Email invite state
  const [showInviteForm, setShowInviteForm] = useState(false)
  const [inviteForm, setInviteForm] = useState({ email: '', role: 'staff' as string })
  const [invitePerms, setInvitePerms] = useState<Record<ModuleKey, AccessLevel>>({} as Record<ModuleKey, AccessLevel>)
  const [sendingInvite, setSendingInvite] = useState(false)
  const [pendingInvitations, setPendingInvitations] = useState<{ id: string; email: string; role: string; status: string; created_at: string; expires_at: string }[]>([])
  const [cancellingInvite, setCancellingInvite] = useState<string | null>(null)

  // Accountant Access tab state
  const [partnerRequests, setPartnerRequests] = useState<PartnerAccessRequest[]>([])
  const [partnerLinks, setPartnerLinks] = useState<PartnerClientLink[]>([])
  const [accessLoading, setAccessLoading] = useState(false)

  // GL Mapping state
  const [glMapping, setGlMapping] = useState<Record<string, any> | null>(null)
  const [glAccounts, setGlAccounts] = useState<any[]>([])
  const [glMappingSaving, setGlMappingSaving] = useState(false)

  // FIRS state lives in the FirsTab sub-component (see bottom of this file)
  const [approvingReq, setApprovingReq] = useState<string | null>(null)
  const [rejectingReq, setRejectingReq] = useState<string | null>(null)
  const [revokingLink, setRevokingLink] = useState<string | null>(null)
  const [inviteEmail, setInviteEmail] = useState('')
  const [generatingInvite, setGeneratingInvite] = useState(false)
  const [generatedToken, setGeneratedToken] = useState<{ token: string; partner_email: string } | null>(null)

  useEffect(() => {
    if (activeTab === 'payments') {
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
    if (activeTab === 'email' && organisation?.id) {
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
    if (activeTab === 'periods') {
      setLoadingPeriods(true)
      accountingApi.periods().then(({ data }) => {
        setPeriods(Array.isArray(data) ? data : data.results ?? [])
      }).catch(() => toast.error('Failed to load periods')).finally(() => setLoadingPeriods(false))
    }
    if (activeTab === 'team') {
      setLoadingTeam(true)
      Promise.all([
        teamApi.members(),
        organisation?.id ? orgApi.listInvitations(organisation.id) : Promise.resolve({ data: [] }),
      ]).then(([membersRes, inviteRes]) => {
        const members: TeamMember[] = Array.isArray(membersRes.data) ? membersRes.data : membersRes.data.results ?? []
        setTeamMembers(members)
        const drafts: Record<string, Record<ModuleKey, AccessLevel>> = {}
        members.forEach((m) => {
          const map: Record<ModuleKey, AccessLevel> = {} as Record<ModuleKey, AccessLevel>
          ALL_MODULES.forEach(({ key }) => { map[key] = 'edit' })
          m.module_permissions.forEach((p) => { map[p.module] = p.access_level })
          drafts[m.id] = map
        })
        setDraftPerms(drafts)
        const invitations = Array.isArray(inviteRes.data) ? inviteRes.data : inviteRes.data.results ?? []
        setPendingInvitations(invitations.filter((inv: { status: string }) => inv.status === 'pending'))
      }).catch(() => toast.error('Failed to load team data')).finally(() => setLoadingTeam(false))
    }
    // whitelabel and firs tabs have their own internal useEffect — no load needed here
    if (activeTab === 'access' && organisation?.id) {
      setAccessLoading(true)
      Promise.allSettled([
        orgApi.listPartnerRequests(organisation.id),
        orgApi.listPartnerAccess(organisation.id),
      ]).then(([reqRes, linkRes]) => {
        if (reqRes.status === 'fulfilled') {
          const d = reqRes.value.data
          setPartnerRequests(Array.isArray(d) ? d : d.results ?? [])
        }
        if (linkRes.status === 'fulfilled') {
          const d = linkRes.value.data
          setPartnerLinks(Array.isArray(d) ? d : d.results ?? [])
        }
      }).finally(() => setAccessLoading(false))
    }
    if (activeTab === 'gl_mapping' && organisation?.id) {
      Promise.allSettled([
        accountingApi.getAccountMapping(),
        accountingApi.accounts(),
      ]).then(([mapRes, acctRes]) => {
        if (mapRes.status === 'fulfilled') setGlMapping(mapRes.value.data)
        if (acctRes.status === 'fulfilled') {
          const d = acctRes.value.data
          setGlAccounts(Array.isArray(d) ? d : d.results ?? [])
        }
      })
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

  const handleStampChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setStampFile(file)
    setStampPreview(URL.createObjectURL(file))
    setStampRemoved(false)
  }

  const saveProfile = async () => {
    setSavingProfile(true)
    try {
      // Send text fields as JSON (avoids Tauri IPC FormData → URL-encoded bug)
      let { data } = await authApi.updateProfile({
        first_name: profile.first_name,
        last_name: profile.last_name,
        phone: profile.phone,
      })
      // Upload avatar as raw binary via dedicated endpoint
      if (avatarFile) {
        const resp = await authApi.uploadAvatar(avatarFile)
        if (resp.ok) data = await resp.json()
        setAvatarFile(null)
      }
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
      if (logoRemoved) {
        await orgApi.removeLogo(organisation.id)
        setLogoRemoved(false)
      }
      if (stampRemoved) {
        await orgApi.removeStamp(organisation.id)
        setStampRemoved(false)
      }

      // Always send text fields as JSON — this reliably works with the Tauri
      // HTTP adapter. FormData without file blobs gets serialised as URL-encoded
      // by the IPC bridge, which DRF rejects (no FormParser in parser_classes).
      const textPayload = {
        name: company.name,
        country: company.country,
        currency: company.currency,
        tax_id: company.tax_id,
        registration_number: company.registration_number,
        address: company.address,
        phone: company.phone,
        email: company.email,
        bank_name: company.bank_name,
        bank_account_number: company.bank_account_number,
        bank_account_name: company.bank_account_name,
        bank_sort_code: company.bank_sort_code,
        brand_color: company.brand_color,
        invoice_company_name: company.invoice_company_name,
        company_name_font: company.company_name_font,
        company_name_font_color: company.company_name_font_color,
        company_name_font_size: company.company_name_font_size,
        company_name_font_bold: company.company_name_font_bold,
        company_name_font_italic: company.company_name_font_italic,
        company_name_font_underline: company.company_name_font_underline,
        show_company_name_on_pdf: company.show_company_name_on_pdf,
        invoice_template: company.invoice_template,
        pension_provider: company.pension_provider ?? '',
        ai_custom_context: company.ai_custom_context ?? '',
      }

      // Always send text fields as JSON (Tauri's IPC serialises FormData as
      // URL-encoded, not multipart — so files are uploaded via a separate
      // binary POST endpoint that avoids FormData entirely).
      let { data } = await orgApi.update(organisation.id, textPayload)

      // Upload logo / stamp as raw binary through dedicated endpoints
      if (logoFile) {
        const resp = await orgApi.uploadLogo(organisation.id, logoFile)
        if (resp.ok) data = await resp.json()
        setLogoFile(null)
      }
      if (stampFile) {
        const resp = await orgApi.uploadStamp(organisation.id, stampFile)
        if (resp.ok) data = await resp.json()
        setStampFile(null)
      }

      updateOrganisation(data)
      toast.success('Company settings saved')
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: { message?: string } | string } } })?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to save company settings')
      toast.error(msg)
    } finally {
      setSavingCompany(false)
    }
  }

  const saveTemplate = async (templateValue: string) => {
    if (!organisation?.id) return
    try {
      const { data } = await orgApi.update(organisation.id, { invoice_template: templateValue })
      updateOrganisation(data)
      toast.success('Template saved')
    } catch {
      toast.error('Failed to save template')
    }
  }

  const saveAIContext = async () => {
    if (!organisation?.id) return
    setSavingCompany(true)
    try {
      const { data } = await orgApi.update(organisation.id, { ai_custom_context: company.ai_custom_context ?? '' })
      updateOrganisation(data)
      toast.success('AI context saved')
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: { message?: string } | string } } })?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to save AI context')
      toast.error(msg)
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
      const emailNote = subaccountForm.notify_email ? ` · credentials sent to ${subaccountForm.notify_email}` : ''
      toast.success(`Sub-account ${subaccountForm.username}@${organisation.slug} created${emailNote}`)
      setShowSubaccountForm(false)
      setSubaccountForm({ username: '', password: '', role: 'staff', first_name: '', last_name: '', notify_email: '' })
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

  const handleSendInvite = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!organisation?.id || !inviteForm.email) return
    setSendingInvite(true)
    try {
      const modulePermsPayload: Record<string, string> = {}
      ALL_MODULES.forEach(({ key }) => {
        if (invitePerms[key] && invitePerms[key] !== 'edit') modulePermsPayload[key] = invitePerms[key]
      })
      const { data } = await orgApi.invite(organisation.id, {
        email: inviteForm.email,
        role: inviteForm.role,
        module_permissions: Object.keys(modulePermsPayload).length > 0 ? modulePermsPayload : {},
      })
      toast.success(`Invitation sent to ${inviteForm.email}`)
      setShowInviteForm(false)
      setInviteForm({ email: '', role: 'staff' })
      setInvitePerms({} as Record<ModuleKey, AccessLevel>)
      setPendingInvitations((prev) => [data, ...prev])
    } catch (err: unknown) {
      const axiosErr = err as AxiosError<{ error?: { message?: string } | string }>
      const apiErr = axiosErr?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to send invitation')
      toast.error(msg)
    } finally {
      setSendingInvite(false)
    }
  }

  const handleCancelInvite = async (invitationId: string) => {
    if (!organisation?.id) return
    setCancellingInvite(invitationId)
    try {
      await orgApi.cancelInvitation(organisation.id, invitationId)
      setPendingInvitations((prev) => prev.filter((inv) => inv.id !== invitationId))
      toast.success('Invitation cancelled')
    } catch {
      toast.error('Failed to cancel invitation')
    } finally {
      setCancellingInvite(null)
    }
  }

  const handleDeactivate = (m: TeamMember) => {
    setDeactivateTarget(m)
  }

  const confirmDeactivate = async (permanent: boolean) => {
    if (!deactivateTarget) return
    setDeactivating(true)
    try {
      if (permanent) {
        await teamApi.deleteMember(deactivateTarget.id)
        toast.success(`${deactivateTarget.user_full_name || deactivateTarget.user_email} permanently removed`)
        setTeamMembers((prev) => prev.filter((tm) => tm.id !== deactivateTarget.id))
      } else {
        await teamApi.updateMember(deactivateTarget.id, { is_active: false })
        toast.success('Member deactivated')
        setTeamMembers((prev) => prev.map((tm) => tm.id === deactivateTarget.id ? { ...tm, is_active: false } : tm))
      }
      setDeactivateTarget(null)
    } catch {
      toast.error(permanent ? 'Failed to remove member' : 'Failed to deactivate member')
    } finally {
      setDeactivating(false)
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

  // ── Partner Access Handlers ─────────────────────────────────────────────────
  const handleApprovePartner = async (reqId: string) => {
    if (!organisation?.id) return
    setApprovingReq(reqId)
    try {
      const { data } = await orgApi.approvePartnerRequest(organisation.id, reqId)
      setPartnerRequests((prev) => prev.map((r) => r.id === reqId ? data : r))
      const linkRes = await orgApi.listPartnerAccess(organisation.id)
      setPartnerLinks(Array.isArray(linkRes.data) ? linkRes.data : linkRes.data.results ?? [])
      toast.success('Partner access approved')
    } catch (err: any) {
      const msg = err?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Failed to approve')
    } finally {
      setApprovingReq(null)
    }
  }

  const handleRejectPartner = async (reqId: string) => {
    const reason = window.prompt('Reason for rejection (optional):') ?? ''
    if (!organisation?.id) return
    setRejectingReq(reqId)
    try {
      const { data } = await orgApi.rejectPartnerRequest(organisation.id, reqId, reason)
      setPartnerRequests((prev) => prev.map((r) => r.id === reqId ? data : r))
      toast.success('Request rejected')
    } catch (err: any) {
      const msg = err?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Failed to reject')
    } finally {
      setRejectingReq(null)
    }
  }

  const handleRevokePartnerAccess = async (linkId: string) => {
    if (!organisation?.id) return
    if (!confirm('Revoke this accountant\'s access? They will lose access to this organisation immediately.')) return
    setRevokingLink(linkId)
    try {
      await orgApi.revokePartnerAccess(organisation.id, linkId)
      setPartnerLinks((prev) => prev.filter((l) => l.id !== linkId))
      toast.success('Partner access revoked')
    } catch {
      toast.error('Failed to revoke access')
    } finally {
      setRevokingLink(null)
    }
  }

  const handleGenerateInvite = async () => {
    if (!organisation?.id || !inviteEmail.trim()) { toast.error('Enter the accountant\'s email address'); return }
    setGeneratingInvite(true)
    try {
      const { data } = await orgApi.generatePartnerInvite(organisation.id, inviteEmail.trim())
      setGeneratedToken({ token: data.token, partner_email: data.partner_email })
      setInviteEmail('')
    } catch (err: any) {
      const msg = err?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Failed to generate invite')
    } finally {
      setGeneratingInvite(false)
    }
  }

  const activeNonOwners = teamMembers.filter((m) => m.is_active && m.role !== 'owner')
  const MAX_MEMBERS = getPlanMaxMembers(planName)

  const allTabs: { id: Tab; label: string; icon: React.ElementType; ownerOnly?: boolean; requiresSettings?: boolean; requiresPlan?: string }[] = [
    { id: 'profile',           label: 'Profile',    icon: User },
    { id: 'company',           label: 'Company',    icon: Building2,  requiresSettings: true },
    { id: 'security',          label: 'Security',   icon: Shield },
    { id: 'team',              label: 'Team',       icon: UsersRound, ownerOnly: true, requiresPlan: 'team' },
    { id: 'payments',          label: 'Payments',   icon: CreditCard, requiresSettings: true },
    { id: 'email',             label: 'Email',      icon: Mail,       ownerOnly: true },
    { id: 'periods',           label: 'Periods',    icon: Lock,       requiresSettings: true, requiresPlan: 'accounting' },
    { id: 'gl_mapping',        label: 'GL Mapping', icon: GitBranch,  requiresSettings: true, requiresPlan: 'accounting' },
    { id: 'invoice_templates', label: 'Templates',  icon: Layout,     ownerOnly: true },
    { id: 'ai',                label: 'AI',         icon: Bot,        ownerOnly: true },
    { id: 'access',            label: 'Accountant Access', icon: ShieldCheck, ownerOnly: true },
    { id: 'whitelabel',        label: 'White-label',       icon: Globe,        ownerOnly: true },
    { id: 'firs',              label: 'FIRS',              icon: Shield,       ownerOnly: true },
  ]
  const tabs = allTabs.filter((t) => {
    if (t.ownerOnly && !isOwner) return false
    if (t.requiresSettings && !hasSettingsPerm) return false
    if (t.requiresPlan && planModules !== null && !planModules.includes(t.requiresPlan) && !user?.is_superuser) return false
    return true
  })

  // If current tab is no longer visible (permissions changed), reset to profile
  const validTabIds = tabs.map((t) => t.id)
  const activeTab = validTabIds.includes(tab) ? tab : 'profile'

  return (
    <>
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-slate-400 text-sm">Manage your account and organisation</p>
      </div>

      {/* Tab bar */}
      <div className="flex flex-wrap gap-1 p-1 bg-surface-800 border border-surface-700 rounded-xl w-fit max-w-full">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            title={t.label}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === t.id
                ? 'bg-brand-500 text-white'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <t.icon size={15} />
            <span className="hidden sm:inline">{t.label}</span>
          </button>
        ))}
      </div>

      {/* ── Profile ── */}
      {activeTab === 'profile' && (
        <div className="card p-6 space-y-6 max-w-3xl">
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
      {activeTab === 'company' && (
        <div className="card p-6 space-y-6 max-w-3xl">
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
              <p className="text-xs text-slate-500 mt-0.5">
                Workspace ID:{' '}
                <button
                  onClick={() => { navigator.clipboard.writeText(organisation?.slug ?? ''); toast.success('Workspace ID copied') }}
                  className="font-mono text-brand-400 hover:text-brand-300 inline-flex items-center gap-1"
                  title="Click to copy"
                >
                  {organisation?.slug} <Copy size={10} />
                </button>
              </p>
              <p className="text-xs text-slate-500 mt-0.5">
                Organisation ID:{' '}
                <button
                  onClick={() => { navigator.clipboard.writeText(organisation?.id ?? ''); toast.success('Organisation ID copied') }}
                  className="font-mono text-slate-400 hover:text-slate-300 inline-flex items-center gap-1 break-all text-left"
                  title="Click to copy — share this with your accountant partner"
                >
                  {organisation?.id} <Copy size={10} className="shrink-0" />
                </button>
              </p>
              <div className="flex items-center gap-3 mt-1">
                <button onClick={() => logoRef.current?.click()} className="text-xs text-brand-400 hover:text-brand-300">
                  Change logo
                </button>
                {logoPreview && (
                  <button
                    type="button"
                    onClick={() => { setLogoPreview(null); setLogoFile(null); setLogoRemoved(true) }}
                    className="text-xs text-red-400 hover:text-red-300 transition-colors"
                  >
                    Remove logo
                  </button>
                )}
              </div>
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
          <div className={`relative ${!isOwner ? 'opacity-60' : ''}`}>
            <div className="flex items-center gap-2 mb-3">
              <LandmarkIcon size={16} className="text-brand-400" />
              <h3 className="text-sm font-semibold text-white">Banking Details</h3>
              <span className="text-xs text-slate-500">— automatically included in invoices</span>
              {!isOwner && <Lock size={13} className="text-slate-500 ml-1" />}
            </div>
            {!isOwner && (
              <div className="mb-3 flex items-center gap-2 text-xs text-slate-500 bg-surface-800 border border-surface-700 rounded-lg px-3 py-2">
                <Lock size={12} className="shrink-0" />
                Only the owner account has the privilege to access this section.
              </div>
            )}
            <div className={`grid grid-cols-2 gap-4 ${!isOwner ? 'pointer-events-none select-none' : ''}`}>
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

          {/* Default Pension Provider */}
          <div className="card p-6 space-y-4">
            <div>
              <h3 className="text-base font-semibold text-white mb-1">Default Pension Provider</h3>
              <p className="text-sm text-slate-400">Sets your default PFA for payroll statutory remittance guidance. Can be changed per run.</p>
            </div>
            <select
              className="input"
              value={company.pension_provider}
              onChange={(e) => setCompany((c: typeof company) => ({ ...c, pension_provider: e.target.value }))}
            >
              <option value="">— Not set —</option>
              {[
                'ARM Pension Managers', 'AXA Mansard Pensions', 'Crusader Sterling Pensions',
                'FCMB Pensions', 'Fidelity Pension Managers', 'First Guarantee Pension',
                'Leadway Pensure', 'Meristem Pensions', 'Nigerian University Pension Management',
                'NLPC Pension Fund Administrators', 'OAK Pensions', 'PAL Pensions (Pensions Alliance Ltd)',
                'Premium Pension', 'Radix Pension Managers', 'Sigma Pensions',
                'Stanbic IBTC Pension Managers', 'Trustfund Pensions', 'Veritas Glanvills Pensions',
              ].map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>

          <button onClick={saveCompany} disabled={savingCompany} className="btn-primary">
            {savingCompany ? <><Loader2 size={16} className="animate-spin" /> Saving…</> : 'Save Company Settings'}
          </button>
        </div>
      )}

      {/* ── Financial Periods ── */}
      {activeTab === 'periods' && (
        <div className="card p-6 space-y-5 max-w-3xl">
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
      {activeTab === 'team' && (
        <div className="space-y-5 max-w-3xl">
          {/* Workspace ID — staff use this to log in */}
          <div className="card p-5 border border-brand-500/20 bg-brand-500/5">
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-xl bg-brand-500/15 flex items-center justify-center flex-shrink-0">
                <Shield size={17} className="text-brand-400" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-white">Your Workspace ID</p>
                <p className="text-xs text-slate-400 mt-0.5">
                  Share this with your staff. They enter it in the{' '}
                  <strong className="text-slate-300">Staff Login</strong> portal together with their username and password.
                </p>
                <div className="mt-3 flex items-center gap-2">
                  <div className="flex-1 bg-surface-900 border border-surface-600 rounded-lg px-3 py-2 font-mono text-sm text-brand-300 select-all truncate">
                    {organisation?.slug}
                  </div>
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(organisation?.slug ?? '')
                      toast.success('Workspace ID copied')
                    }}
                    className="btn-secondary px-3 py-2 shrink-0"
                    title="Copy workspace ID"
                  >
                    <Copy size={14} />
                  </button>
                </div>
                <p className="text-xs text-slate-500 mt-2">
                  Staff login format: <span className="font-mono text-slate-400">username</span>
                  {' '}+{' '}
                  <span className="font-mono text-brand-400">{organisation?.slug}</span>
                  {' '}+{' '}
                  <span className="font-mono text-slate-400">password</span>
                  {' '}at the <strong className="text-slate-300">Staff Sign In</strong> page.
                </p>
              </div>
            </div>
          </div>

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
                  <span className={
                    activeNonOwners.length > MAX_MEMBERS ? 'text-red-400 font-semibold' :
                    activeNonOwners.length >= MAX_MEMBERS ? 'text-amber-400' : 'text-slate-400'
                  }>
                    {activeNonOwners.length} / {MAX_MEMBERS} slots used
                    {activeNonOwners.length > MAX_MEMBERS && ' — over limit, deactivate a member'}
                  </span>
                </p>
              </div>
              {planModules !== null && !planModules.includes('team') && !user?.is_superuser ? (
                <button onClick={() => navigate('/billing')} className="btn-secondary text-sm text-amber-400 border-amber-500/30 hover:border-amber-400/50 shrink-0 flex items-center gap-1.5">
                  <UserPlus size={14} /> Upgrade to Add Members
                </button>
              ) : activeNonOwners.length < MAX_MEMBERS ? (
                <div className="flex gap-2 shrink-0">
                  <button onClick={() => { setShowInviteForm((v) => !v); setShowSubaccountForm(false) }} className="btn-secondary flex items-center gap-1.5">
                    <Mail size={14} /> Invite by Email
                  </button>
                  <button onClick={() => { setShowSubaccountForm((v) => !v); setShowInviteForm(false) }} className="btn-primary flex items-center gap-1.5">
                    <UserPlus size={14} /> Add Member
                  </button>
                </div>
              ) : null}
            </div>

            {/* Email invite form */}
            {showInviteForm && (
              <form onSubmit={handleSendInvite} className="mt-4 p-4 rounded-xl bg-brand-500/5 border border-brand-500/20 space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-sm font-semibold text-white">Invite by Email</span>
                    <p className="text-xs text-slate-500 mt-0.5">The invitee will receive an email with accept/decline options.</p>
                  </div>
                  <button type="button" onClick={() => setShowInviteForm(false)} className="btn-ghost p-1"><X size={14} /></button>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="col-span-2">
                    <label className="label">Email address *</label>
                    <input
                      type="email" required className="input" placeholder="partner@example.com"
                      value={inviteForm.email}
                      onChange={(e) => setInviteForm({ ...inviteForm, email: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className="label">Role *</label>
                    <select className="input" value={inviteForm.role} onChange={(e) => setInviteForm({ ...inviteForm, role: e.target.value })}>
                      <option value="admin">Admin</option>
                      <option value="manager">Manager</option>
                      <option value="accountant">Accountant</option>
                      <option value="staff">Staff</option>
                      <option value="viewer">Viewer (read-only)</option>
                    </select>
                  </div>
                </div>
                {/* Module permissions (optional override) */}
                <details className="text-xs">
                  <summary className="cursor-pointer text-slate-400 hover:text-slate-300 select-none py-1">
                    Set per-module access (optional — defaults to full edit for all modules)
                  </summary>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    {ALL_MODULES.map(({ key, label }) => (
                      <div key={key} className="flex items-center justify-between gap-2">
                        <span className="text-slate-400 truncate">{label}</span>
                        <select
                          className="input py-1 text-xs w-28 shrink-0"
                          value={invitePerms[key] ?? 'edit'}
                          onChange={(e) => setInvitePerms((p) => ({ ...p, [key]: e.target.value as AccessLevel }))}
                        >
                          <option value="edit">Full Edit</option>
                          <option value="write">Write</option>
                          <option value="view">View Only</option>
                          <option value="none">No Access</option>
                        </select>
                      </div>
                    ))}
                  </div>
                </details>
                <div className="flex justify-end gap-2">
                  <button type="button" onClick={() => setShowInviteForm(false)} className="btn-secondary text-sm">Cancel</button>
                  <button type="submit" disabled={sendingInvite} className="btn-primary text-sm">
                    {sendingInvite ? <Loader2 size={14} className="animate-spin" /> : <><Mail size={13} /> Send Invitation</>}
                  </button>
                </div>
              </form>
            )}

            {/* Sub-account creation form */}
            {showSubaccountForm && (
              <form onSubmit={handleCreateSubaccount} className="mt-4 p-4 rounded-xl bg-surface-700 border border-surface-600 space-y-3">
                <div className="flex items-center justify-between mb-1">
                  <div>
                    <span className="text-sm font-medium text-white">Create Sub-Account</span>
                    <p className="text-xs text-slate-500 mt-0.5">
                      Login email: <span className="text-brand-400 font-mono">{subaccountForm.username || 'username'}@{organisation?.slug}</span>
                    </p>
                  </div>
                  <button type="button" onClick={() => setShowSubaccountForm(false)} className="btn-ghost p-1"><X size={14} /></button>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="label">First Name</label>
                    <input
                      className="input" placeholder="e.g. John"
                      value={subaccountForm.first_name}
                      onChange={(e) => setSubaccountForm({ ...subaccountForm, first_name: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className="label">Last Name</label>
                    <input
                      className="input" placeholder="e.g. Doe"
                      value={subaccountForm.last_name}
                      onChange={(e) => setSubaccountForm({ ...subaccountForm, last_name: e.target.value })}
                    />
                  </div>
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
                    <label className="label">Personal Email <span className="text-slate-500 font-normal">(optional — to send login credentials)</span></label>
                    <input
                      type="email" className="input" placeholder="e.g. john@gmail.com"
                      value={subaccountForm.notify_email}
                      onChange={(e) => setSubaccountForm({ ...subaccountForm, notify_email: e.target.value })}
                    />
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

          {/* Pending invitations */}
          {pendingInvitations.length > 0 && (
            <div className="card p-5 space-y-3">
              <h4 className="text-sm font-semibold text-white flex items-center gap-2">
                <Mail size={15} className="text-amber-400" />
                Pending Invitations
              </h4>
              {pendingInvitations.map((inv) => (
                <div key={inv.id} className="flex items-center justify-between gap-3 p-3 rounded-xl bg-surface-700/50 border border-amber-500/20">
                  <div className="min-w-0">
                    <p className="text-sm text-white font-medium truncate">{inv.email}</p>
                    <p className="text-xs text-slate-500 capitalize">{inv.role} · Sent {new Date(inv.created_at).toLocaleDateString()}</p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="badge-orange">Pending</span>
                    <button
                      onClick={() => handleCancelInvite(inv.id)}
                      disabled={cancellingInvite === inv.id}
                      className="btn-ghost p-1.5 text-slate-400 hover:text-red-400"
                      title="Cancel invitation"
                    >
                      {cancellingInvite === inv.id ? <Loader2 size={13} className="animate-spin" /> : <X size={13} />}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

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
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-white font-medium text-sm truncate">{m.user_full_name || '—'}</p>
                        {organisation?.slug && m.user_email.endsWith(`@${organisation.slug}`) && (
                          <span className="text-xs bg-brand-500/15 text-brand-400 px-1.5 py-0.5 rounded-md shrink-0">sub-account</span>
                        )}
                        {FEATURES.PARTNER_CHANNEL && m.partner_firm_name && (
                          <span className="text-xs bg-purple-500/15 text-purple-400 px-1.5 py-0.5 rounded-md shrink-0">
                            Accountant · {m.partner_firm_name}
                          </span>
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
                          <>
                            <button
                              onClick={() => handleReactivate(m)}
                              disabled={activeNonOwners.length >= MAX_MEMBERS}
                              title={activeNonOwners.length >= MAX_MEMBERS ? `Slot limit reached (${MAX_MEMBERS}/${MAX_MEMBERS}). Deactivate another member first.` : 'Reactivate member'}
                              className="text-xs text-slate-500 hover:text-green-400 px-2 py-1 rounded-lg hover:bg-green-500/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:text-slate-500 disabled:hover:bg-transparent"
                            >
                              Reactivate
                            </button>
                            <button
                              onClick={() => { setDeactivateTarget(m) }}
                              title="Permanently delete member"
                              className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                            >
                              <Trash2 size={14} />
                            </button>
                          </>
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
                                className="input text-xs py-1 px-2 w-auto"
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
      {activeTab === 'payments' && (
        <div className="space-y-6 max-w-3xl">
          {!isOwner && (
            <div className="flex items-center gap-3 p-4 rounded-xl bg-surface-800 border border-surface-700 text-sm text-slate-400">
              <Lock size={16} className="text-slate-500 shrink-0" />
              <span>Only the owner account has the privilege to access this section.</span>
            </div>
          )}
          {/* Paystack */}
          <div className={`card p-6 space-y-5 ${!isOwner ? 'opacity-60 pointer-events-none select-none' : ''}`}>
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
          <div className={`card p-6 opacity-60 ${!isOwner ? 'pointer-events-none select-none' : ''}`}>
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
      {activeTab === 'security' && (
        <div className="space-y-4 max-w-3xl">
          {/* Inactivity Timeout */}
          <div className="card p-6 space-y-4">
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

          {/* Two-Factor Authentication */}
          <div className="card p-6 space-y-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-brand-500/15 rounded-xl flex items-center justify-center">
                  <Shield size={20} className="text-brand-400" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-white">Two-Factor Authentication (MFA)</h3>
                  <p className="text-sm text-slate-400">Works with Google Authenticator, Microsoft Authenticator, Authy, and any TOTP app</p>
                </div>
              </div>
              <span className={mfaEnabled ? 'badge-green' : 'badge-slate'}>
                {mfaEnabled ? 'Enabled' : 'Disabled'}
              </span>
            </div>

            {/* Idle — show enable or disable button */}
            {mfaStep === 'idle' && (
              <>
                {!mfaEnabled ? (
                  <div className="space-y-3">
                    <p className="text-sm text-slate-400">
                      Add an extra layer of security. After enabling, you'll need both your password and a 6-digit code from your authenticator app to sign in.
                    </p>
                    <button onClick={handleMFASetup} disabled={mfaLoading} className="btn-primary">
                      {mfaLoading ? <Loader2 size={16} className="animate-spin mr-2" /> : null}
                      Enable MFA
                    </button>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <p className="text-sm text-slate-400">MFA is active. You'll be prompted for a code on each login.</p>
                    <button onClick={() => setMfaStep('disable')} className="btn-secondary text-red-400 hover:text-red-300 border-red-500/30 hover:border-red-500/50">
                      Disable MFA
                    </button>
                  </div>
                )}
              </>
            )}

            {/* Step 1 — show QR code */}
            {mfaStep === 'setup' && (
              <div className="space-y-4">
                {/* App recommendations */}
                <div className="bg-surface-800 border border-surface-700 rounded-xl p-4 text-sm space-y-2">
                  <p className="font-medium text-white">Step 1 — Install an authenticator app</p>
                  <p className="text-slate-400 text-xs">Use any free TOTP app — they all work:</p>
                  <div className="grid grid-cols-2 gap-1.5 text-xs text-slate-300">
                    {[
                      'Google Authenticator',
                      'Microsoft Authenticator',
                      'Authy',
                      '1Password',
                      'Bitwarden',
                      'Any TOTP-compatible app',
                    ].map((app) => (
                      <span key={app} className="flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full bg-brand-400 shrink-0" />
                        {app}
                      </span>
                    ))}
                  </div>
                </div>

                {/* QR code */}
                <div className="bg-surface-800 border border-surface-700 rounded-xl p-4 space-y-3">
                  <p className="text-sm font-medium text-white">Step 2 — Scan this QR code</p>
                  {mfaQr && (
                    <div className="flex justify-center">
                      <div className="bg-white p-3 rounded-xl inline-block">
                        <img src={mfaQr} alt="MFA QR code" className="w-52 h-52" />
                      </div>
                    </div>
                  )}

                  {/* Manual secret fallback */}
                  {mfaSecret && (
                    <div className="mt-3">
                      <p className="text-xs text-slate-400 mb-1.5">Can't scan? Enter this key manually in your app:</p>
                      <div className="flex items-center gap-2 bg-surface-700 rounded-xl px-3 py-2">
                        <code className="flex-1 text-xs font-mono text-brand-300 tracking-wider break-all">{mfaSecret}</code>
                        <button
                          type="button"
                          onClick={() => {
                            navigator.clipboard.writeText(mfaSecret)
                            setMfaSecretCopied(true)
                            setTimeout(() => setMfaSecretCopied(false), 2000)
                          }}
                          className="text-xs text-slate-400 hover:text-white shrink-0 px-2 py-1 rounded-lg hover:bg-surface-600 transition-colors"
                        >
                          {mfaSecretCopied ? '✓ Copied' : 'Copy'}
                        </button>
                      </div>
                      <p className="text-xs text-slate-500 mt-1">Select "Time-based" (TOTP) when entering manually.</p>
                    </div>
                  )}
                </div>

                {/* Code entry */}
                <div className="bg-surface-800 border border-surface-700 rounded-xl p-4 space-y-3">
                  <p className="text-sm font-medium text-white">Step 3 — Enter the 6-digit code</p>
                  <input
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    className="input text-center tracking-widest font-mono text-lg"
                    placeholder="000000"
                    value={mfaCode}
                    onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ''))}
                    autoFocus
                  />
                </div>

                <div className="flex gap-3">
                  <button onClick={handleMFAConfirm} disabled={mfaLoading || mfaCode.length < 6} className="btn-primary flex-1">
                    {mfaLoading ? <Loader2 size={16} className="animate-spin mr-2" /> : null}
                    Confirm & Enable
                  </button>
                  <button onClick={() => { setMfaStep('idle'); setMfaCode(''); setMfaQr(''); setMfaSecret('') }} className="btn-secondary">
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Step 2 — backup codes */}
            {mfaStep === 'backup' && (
              <div className="space-y-4">
                <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl">
                  <p className="text-sm font-semibold text-amber-300 mb-1">Save your backup codes</p>
                  <p className="text-xs text-amber-400/80">These are one-time use codes. If you lose access to your authenticator, use one of these. They won't be shown again.</p>
                </div>
                <div className="bg-surface-800 border border-surface-700 rounded-xl p-4 font-mono text-sm">
                  <div className="grid grid-cols-2 gap-2">
                    {backupCodes.map((code, i) => (
                      <span key={i} className="text-green-400">{code}</span>
                    ))}
                  </div>
                </div>
                <button
                  onClick={() => navigator.clipboard.writeText(backupCodes.join('\n')).then(() => toast.success('Copied!'))}
                  className="btn-secondary w-full"
                >
                  Copy all codes
                </button>
                <button onClick={() => setMfaStep('idle')} className="btn-primary w-full">
                  Done — I've saved my codes
                </button>
              </div>
            )}

            {/* Disable confirmation */}
            {mfaStep === 'disable' && (
              <div className="space-y-4">
                <p className="text-sm text-slate-400">Enter your current password and authenticator code (or a backup code) to confirm disabling MFA.</p>
                <div>
                  <label className="label">Current password</label>
                  <input
                    type="password"
                    className="input"
                    placeholder="Your account password"
                    value={mfaDisablePassword}
                    onChange={(e) => setMfaDisablePassword(e.target.value)}
                  />
                </div>
                <div>
                  <label className="label">Authenticator code</label>
                  <input
                    type="text"
                    inputMode="numeric"
                    maxLength={10}
                    className="input text-center tracking-widest font-mono text-lg"
                    placeholder="000000"
                    value={mfaCode}
                    onChange={(e) => setMfaCode(e.target.value.replace(/\s/g, ''))}
                  />
                </div>
                <div className="flex gap-3">
                  <button onClick={handleMFADisable} disabled={mfaLoading || mfaCode.length < 6 || !mfaDisablePassword} className="btn-primary flex-1 bg-red-600 hover:bg-red-700">
                    {mfaLoading ? <Loader2 size={16} className="animate-spin mr-2" /> : null}
                    Disable MFA
                  </button>
                  <button onClick={() => { setMfaStep('idle'); setMfaCode(''); setMfaDisablePassword('') }} className="btn-secondary">
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Email / SMTP ── */}
      {activeTab === 'email' && (
        <div className="card p-6 space-y-5 max-w-3xl">
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

      {/* ── Invoice Templates ────────────────────────────────────────────── */}
      {activeTab === 'invoice_templates' && (
        <div className="grid grid-cols-2 gap-6 items-start">
          {/* ── Left: template picker ───────────────────────── */}
          <div className="space-y-5">
          <div className="card p-5 space-y-4">
            <div>
              <h3 className="text-base font-semibold text-white mb-1">Invoice Layout Template</h3>
              <p className="text-sm text-slate-400">Choose the global PDF template for invoices, delivery notes, and quotes.</p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              {([
                {
                  value: 'classic',
                  label: 'Classic',
                  desc: 'Bold coloured header with company name. Traditional business layout.',
                  preview: (
                    <svg viewBox="0 0 160 110" className="w-full" xmlns="http://www.w3.org/2000/svg">
                      {/* Header bar */}
                      <rect x="0" y="0" width="160" height="30" fill="#f97316" rx="3"/>
                      <rect x="8" y="8" width="60" height="6" rx="2" fill="white" opacity="0.9"/>
                      <rect x="8" y="17" width="35" height="3" rx="1.5" fill="white" opacity="0.6"/>
                      <rect x="110" y="8" width="40" height="5" rx="1.5" fill="white" opacity="0.7"/>
                      <rect x="120" y="16" width="30" height="3" rx="1.5" fill="white" opacity="0.5"/>
                      {/* Invoice label */}
                      <rect x="8" y="38" width="30" height="4" rx="2" fill="#f97316" opacity="0.8"/>
                      {/* Info rows */}
                      <rect x="8" y="48" width="55" height="2.5" rx="1.2" fill="#94a3b8"/>
                      <rect x="8" y="54" width="40" height="2.5" rx="1.2" fill="#94a3b8"/>
                      <rect x="100" y="48" width="52" height="2.5" rx="1.2" fill="#94a3b8"/>
                      <rect x="100" y="54" width="38" height="2.5" rx="1.2" fill="#94a3b8"/>
                      {/* Table header */}
                      <rect x="8" y="63" width="144" height="8" rx="2" fill="#f97316" opacity="0.15"/>
                      <rect x="12" y="65.5" width="30" height="2.5" rx="1" fill="#f97316" opacity="0.7"/>
                      <rect x="115" y="65.5" width="18" height="2.5" rx="1" fill="#f97316" opacity="0.7"/>
                      <rect x="138" y="65.5" width="10" height="2.5" rx="1" fill="#f97316" opacity="0.7"/>
                      {/* Table rows */}
                      {[0,1,2].map(i => (
                        <g key={i}>
                          <rect x="8" y={76 + i*9} width="144" height="7" rx="1" fill={i%2===0?"#1e293b":"transparent"} opacity="0.4"/>
                          <rect x="12" y={78 + i*9} width="45" height="2" rx="1" fill="#94a3b8"/>
                          <rect x="118" y={78 + i*9} width="14" height="2" rx="1" fill="#94a3b8"/>
                          <rect x="138" y={78 + i*9} width="12" height="2" rx="1" fill="#94a3b8"/>
                        </g>
                      ))}
                      {/* Total */}
                      <rect x="100" y="104" width="52" height="4" rx="2" fill="#f97316" opacity="0.3"/>
                      <rect x="104" y="105.5" width="20" height="1.5" rx="1" fill="#f97316" opacity="0.8"/>
                      <rect x="138" y="105.5" width="12" height="1.5" rx="1" fill="#f97316" opacity="0.8"/>
                    </svg>
                  ),
                },
                {
                  value: 'modern',
                  label: 'Modern',
                  desc: 'Clean minimal header, generous white space. Contemporary style.',
                  preview: (
                    <svg viewBox="0 0 160 110" className="w-full" xmlns="http://www.w3.org/2000/svg">
                      {/* Top accent line */}
                      <rect x="0" y="0" width="160" height="4" fill="#f97316" rx="2"/>
                      {/* Company name large */}
                      <rect x="8" y="12" width="70" height="7" rx="2" fill="#1e293b"/>
                      <rect x="8" y="22" width="45" height="3" rx="1.5" fill="#94a3b8"/>
                      {/* INVOICE right aligned */}
                      <rect x="110" y="10" width="42" height="8" rx="2" fill="#f97316" opacity="0.15"/>
                      <rect x="114" y="12.5" width="34" height="3" rx="1.5" fill="#f97316" opacity="0.9"/>
                      <rect x="120" y="19" width="28" height="2" rx="1" fill="#94a3b8"/>
                      {/* Divider */}
                      <line x1="8" y1="32" x2="152" y2="32" stroke="#e2e8f0" strokeWidth="0.8"/>
                      {/* Bill to / info */}
                      <rect x="8" y="38" width="25" height="2.5" rx="1" fill="#f97316" opacity="0.7"/>
                      <rect x="8" y="44" width="55" height="2" rx="1" fill="#94a3b8"/>
                      <rect x="8" y="49" width="40" height="2" rx="1" fill="#94a3b8"/>
                      <rect x="100" y="38" width="25" height="2.5" rx="1" fill="#94a3b8"/>
                      <rect x="100" y="44" width="40" height="2" rx="1" fill="#94a3b8"/>
                      {/* Table */}
                      <line x1="8" y1="60" x2="152" y2="60" stroke="#e2e8f0" strokeWidth="0.8"/>
                      <rect x="8" y="63" width="30" height="2" rx="1" fill="#f97316" opacity="0.7"/>
                      <rect x="118" y="63" width="14" height="2" rx="1" fill="#f97316" opacity="0.7"/>
                      <rect x="138" y="63" width="14" height="2" rx="1" fill="#f97316" opacity="0.7"/>
                      <line x1="8" y1="68" x2="152" y2="68" stroke="#e2e8f0" strokeWidth="0.8"/>
                      {[0,1,2].map(i => (
                        <g key={i}>
                          <rect x="8" y={72 + i*9} width="45" height="2" rx="1" fill="#94a3b8"/>
                          <rect x="118" y={72 + i*9} width="14" height="2" rx="1" fill="#94a3b8"/>
                          <rect x="138" y={72 + i*9} width="14" height="2" rx="1" fill="#94a3b8"/>
                          <line x1="8" y1={77 + i*9} x2="152" y2={77 + i*9} stroke="#e2e8f0" strokeWidth="0.5"/>
                        </g>
                      ))}
                      {/* Total */}
                      <rect x="100" y="103" width="52" height="5" rx="2" fill="#f97316" opacity="0.12"/>
                      <rect x="104" y="105" width="18" height="2" rx="1" fill="#f97316"/>
                      <rect x="136" y="105" width="14" height="2" rx="1" fill="#f97316"/>
                    </svg>
                  ),
                },
                {
                  value: 'minimal',
                  label: 'Minimal',
                  desc: 'No header background. Just the essentials — clean and fast.',
                  preview: (
                    <svg viewBox="0 0 160 110" className="w-full" xmlns="http://www.w3.org/2000/svg">
                      {/* Company name */}
                      <rect x="8" y="8" width="55" height="5" rx="2" fill="#1e293b"/>
                      <rect x="8" y="16" width="35" height="2.5" rx="1" fill="#94a3b8"/>
                      {/* INVOICE word */}
                      <rect x="8" y="26" width="22" height="4" rx="2" fill="#1e293b"/>
                      <rect x="100" y="26" width="52" height="3" rx="1.5" fill="#94a3b8"/>
                      <rect x="100" y="32" width="40" height="2.5" rx="1" fill="#94a3b8"/>
                      {/* Simple line */}
                      <line x1="8" y1="40" x2="152" y2="40" stroke="#1e293b" strokeWidth="1.5"/>
                      {/* Bill to */}
                      <rect x="8" y="46" width="55" height="2" rx="1" fill="#94a3b8"/>
                      <rect x="8" y="51" width="40" height="2" rx="1" fill="#94a3b8"/>
                      {/* Table header: dark bg */}
                      <rect x="8" y="58" width="144" height="8" rx="1" fill="#1e293b"/>
                      <rect x="12" y="60.5" width="28" height="2" rx="1" fill="white" opacity="0.8"/>
                      <rect x="116" y="60.5" width="14" height="2" rx="1" fill="white" opacity="0.8"/>
                      <rect x="136" y="60.5" width="12" height="2" rx="1" fill="white" opacity="0.8"/>
                      {[0,1,2].map(i => (
                        <g key={i}>
                          <rect x="8" y={70 + i*9} width="45" height="2" rx="1" fill="#94a3b8"/>
                          <rect x="118" y={70 + i*9} width="14" height="2" rx="1" fill="#94a3b8"/>
                          <rect x="138" y={70 + i*9} width="14" height="2" rx="1" fill="#94a3b8"/>
                          <line x1="8" y1={75 + i*9} x2="152" y2={75 + i*9} stroke="#e2e8f0" strokeWidth="0.4"/>
                        </g>
                      ))}
                      <line x1="8" y1="99" x2="152" y2="99" stroke="#1e293b" strokeWidth="1"/>
                      <rect x="104" y="103" width="18" height="2" rx="1" fill="#1e293b"/>
                      <rect x="136" y="103" width="14" height="2" rx="1" fill="#1e293b"/>
                    </svg>
                  ),
                },
                {
                  value: 'professional',
                  label: 'Professional',
                  desc: 'Two-column header with logo on left and details on right. Formal.',
                  preview: (
                    <svg viewBox="0 0 160 110" className="w-full" xmlns="http://www.w3.org/2000/svg">
                      {/* Header: brand-color left (~46%) | light right */}
                      <rect x="0" y="0" width="74" height="36" fill={company.brand_color || '#f97316'}/>
                      <rect x="75" y="0" width="85" height="36" fill="#f8fafc"/>
                      {/* Left: logo placeholder + company */}
                      <rect x="8" y="6" width="14" height="14" rx="2" fill="rgba(255,255,255,0.2)"/>
                      <rect x="8" y="23" width="50" height="3" rx="1.5" fill="white" opacity="0.85"/>
                      <rect x="8" y="28" width="38" height="2" rx="1" fill="white" opacity="0.55"/>
                      {/* Right: INVOICE word + meta rows */}
                      <rect x="115" y="5" width="30" height="5" rx="1.5" fill="#1e293b"/>
                      <rect x="80" y="14" width="22" height="2" rx="1" fill="#94a3b8"/>
                      <rect x="115" y="14" width="30" height="2" rx="1" fill="#1e293b"/>
                      <rect x="80" y="19" width="22" height="2" rx="1" fill="#94a3b8"/>
                      <rect x="115" y="19" width="30" height="2" rx="1" fill="#1e293b"/>
                      <rect x="80" y="24" width="22" height="2" rx="1" fill="#94a3b8"/>
                      <rect x="115" y="24" width="22" height="2" rx="1" fill="#1e293b"/>
                      {/* Bill to */}
                      <rect x="8" y="43" width="22" height="3" rx="1.5" fill={company.brand_color || '#f97316'} opacity="0.8"/>
                      <rect x="8" y="50" width="55" height="2" rx="1" fill="#94a3b8"/>
                      <rect x="8" y="55" width="40" height="2" rx="1" fill="#94a3b8"/>
                      {/* Table header with brand color */}
                      <rect x="8" y="64" width="144" height="7" rx="2" fill={company.brand_color || '#f97316'}/>
                      <rect x="12" y="66.5" width="30" height="2" rx="1" fill="white" opacity="0.8"/>
                      <rect x="115" y="66.5" width="14" height="2" rx="1" fill="white" opacity="0.8"/>
                      <rect x="138" y="66.5" width="10" height="2" rx="1" fill="white" opacity="0.8"/>
                      {[0,1,2].map(i => (
                        <g key={i}>
                          <rect x="8" y={75 + i*9} width="144" height="7" rx="1" fill={i%2===0?"#f8fafc":"white"}/>
                          <rect x="12" y={77.5 + i*9} width="45" height="2" rx="1" fill="#94a3b8"/>
                          <rect x="118" y={77.5 + i*9} width="12" height="2" rx="1" fill="#94a3b8"/>
                          <rect x="139" y={77.5 + i*9} width="11" height="2" rx="1" fill="#94a3b8"/>
                        </g>
                      ))}
                      {/* Total box: brand color */}
                      <rect x="96" y="102" width="56" height="7" rx="2" fill={company.brand_color || '#f97316'}/>
                      <rect x="100" y="104.5" width="18" height="2" rx="1" fill="white" opacity="0.8"/>
                      <rect x="136" y="104.5" width="12" height="2" rx="1" fill="white" opacity="0.9"/>
                    </svg>
                  ),
                },
              ] as { value: string; label: string; desc: string; preview: React.ReactNode }[]).map((tmpl) => (
                <button
                  key={tmpl.value}
                  onClick={() => {
                    setCompany((c: typeof company) => ({ ...c, invoice_template: tmpl.value }))
                    saveTemplate(tmpl.value)
                  }}
                  className={`text-left rounded-xl border-2 transition-all overflow-hidden ${
                    company.invoice_template === tmpl.value
                      ? 'border-brand-500'
                      : 'border-surface-700 hover:border-surface-500'
                  }`}
                >
                  {/* Preview area */}
                  <div className={`p-3 ${company.invoice_template === tmpl.value ? 'bg-brand-500/5' : 'bg-surface-900/60'}`}>
                    <div className="bg-white rounded-lg overflow-hidden shadow-sm">
                      {tmpl.preview}
                    </div>
                  </div>
                  {/* Label */}
                  <div className="px-4 py-3 flex items-center justify-between">
                    <div>
                      <p className="text-sm font-semibold text-white">{tmpl.label}</p>
                      <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">{tmpl.desc}</p>
                    </div>
                    {company.invoice_template === tmpl.value && (
                      <span className="ml-3 shrink-0 text-xs font-medium text-brand-400 bg-brand-500/15 px-2 py-0.5 rounded-full">Active</span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Brand Accent Color */}
          <div className="card p-5 space-y-4">
            <div>
              <h3 className="text-base font-semibold text-white mb-1">Brand &amp; Accent Color</h3>
              <p className="text-xs text-slate-500">Used as the header and accent color across all invoices and PDFs</p>
            </div>
            <div className="flex items-center gap-3">
              <input
                type="color"
                value={company.brand_color}
                onChange={(e) => setCompany({ ...company, brand_color: e.target.value })}
                className="w-10 h-10 rounded-lg border border-surface-600 cursor-pointer bg-transparent p-0.5"
              />
              <input
                className="input w-32 font-mono text-sm"
                value={company.brand_color}
                maxLength={7}
                placeholder="#f97316"
                onChange={(e) => {
                  const v = e.target.value
                  if (/^#[0-9a-fA-F]{0,6}$/.test(v)) setCompany({ ...company, brand_color: v })
                }}
              />
              <div className="w-10 h-10 rounded-lg border border-surface-600" style={{ backgroundColor: company.brand_color }} />
              <button type="button" onClick={() => setCompany({ ...company, brand_color: '#f97316' })} className="text-xs text-slate-500 hover:text-slate-300">Reset</button>
            </div>
          </div>

          {/* Company Font */}
          <div className="card p-5 space-y-4">
            <div>
              <h3 className="text-base font-semibold text-white mb-1">Company Name &amp; Font</h3>
              <p className="text-xs text-slate-500">Controls how your company name appears on all invoices and PDFs</p>
            </div>
            <div>
              <label className="label">Invoice Company Name</label>
              <p className="text-xs text-slate-500 mb-2">Override the name shown on invoices. Leave blank to use the organisation name.</p>
              <input
                className="input w-full max-w-md"
                value={company.invoice_company_name}
                placeholder={company.name || 'Your Company Name'}
                onChange={(e) => setCompany({ ...company, invoice_company_name: e.target.value })}
              />
              <label className="flex items-center gap-2 mt-3 cursor-pointer select-none w-fit">
                <input
                  type="checkbox"
                  checked={company.show_company_name_on_pdf ?? true}
                  onChange={(e) => setCompany({ ...company, show_company_name_on_pdf: e.target.checked })}
                  className="accent-brand-500 w-4 h-4"
                />
                <span className="text-sm text-slate-300">Show company name on invoices and PDFs</span>
                <span className="text-xs text-slate-500">(uncheck to show logo only)</span>
              </label>
            </div>
            <div>
              <label className="label">Font</label>
              <p className="text-xs text-slate-500 mb-2">
                Font, size and style for the company name on PDFs.
                <span className="text-slate-600 ml-1">(PDF output uses the nearest standard font — Helvetica / Times / Courier)</span>
              </p>
              <div className="space-y-3">
                <div className="flex items-center gap-3 flex-wrap">
                  <select
                    className="input w-52"
                    value={company.company_name_font}
                    onChange={(e) => setCompany({ ...company, company_name_font: e.target.value })}
                  >
                    <optgroup label="── Sans-Serif ──">
                      <option value="helvetica">Helvetica / Arial</option>
                      <option value="Inter">Inter</option>
                      <option value="Roboto">Roboto</option>
                      <option value="Open Sans">Open Sans</option>
                      <option value="Lato">Lato</option>
                      <option value="Montserrat">Montserrat</option>
                      <option value="Poppins">Poppins</option>
                      <option value="Raleway">Raleway</option>
                      <option value="Nunito">Nunito</option>
                      <option value="Ubuntu">Ubuntu</option>
                      <option value="Source Sans 3">Source Sans Pro</option>
                      <option value="Oswald">Oswald</option>
                    </optgroup>
                    <optgroup label="── Serif ──">
                      <option value="times">Times New Roman</option>
                      <option value="Georgia">Georgia</option>
                      <option value="Playfair Display">Playfair Display</option>
                      <option value="Merriweather">Merriweather</option>
                      <option value="Lora">Lora</option>
                      <option value="Libre Baskerville">Libre Baskerville</option>
                      <option value="EB Garamond">EB Garamond</option>
                      <option value="Crimson Text">Crimson Text</option>
                      <option value="Cinzel">Cinzel</option>
                      <option value="Cormorant Garamond">Cormorant Garamond</option>
                      <option value="Spectral">Spectral</option>
                    </optgroup>
                    <optgroup label="── Display / Title ──">
                      <option value="Bebas Neue">Bebas Neue</option>
                    </optgroup>
                    <optgroup label="── Monospace ──">
                      <option value="courier">Courier New</option>
                      <option value="JetBrains Mono">JetBrains Mono</option>
                      <option value="Fira Code">Fira Code</option>
                    </optgroup>
                  </select>
                  <div className="flex items-center gap-2">
                    <input
                      type="color"
                      value={company.company_name_font_color}
                      onChange={(e) => setCompany({ ...company, company_name_font_color: e.target.value })}
                      className="w-9 h-9 rounded-lg border border-surface-600 cursor-pointer bg-transparent p-0.5"
                      title="Company name font color"
                    />
                    <span className="text-xs text-slate-500">Color</span>
                  </div>
                </div>
                <div className="flex items-center gap-4 flex-wrap">
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-slate-400">Size (pt)</label>
                    <input
                      type="number"
                      min={8}
                      max={72}
                      className="input w-16 text-center"
                      value={company.company_name_font_size}
                      onChange={(e) => setCompany({ ...company, company_name_font_size: Math.max(8, Math.min(72, parseInt(e.target.value) || 14)) })}
                    />
                  </div>
                  <label className="flex items-center gap-1.5 cursor-pointer select-none">
                    <input type="checkbox" checked={company.company_name_font_bold}
                      onChange={(e) => setCompany({ ...company, company_name_font_bold: e.target.checked })}
                      className="accent-brand-500 w-4 h-4" />
                    <span className="text-xs font-bold text-slate-300">Bold</span>
                  </label>
                  <label className="flex items-center gap-1.5 cursor-pointer select-none">
                    <input type="checkbox" checked={company.company_name_font_italic}
                      onChange={(e) => setCompany({ ...company, company_name_font_italic: e.target.checked })}
                      className="accent-brand-500 w-4 h-4" />
                    <span className="text-xs italic text-slate-300">Italic</span>
                  </label>
                  <label className="flex items-center gap-1.5 cursor-pointer select-none">
                    <input type="checkbox" checked={company.company_name_font_underline}
                      onChange={(e) => setCompany({ ...company, company_name_font_underline: e.target.checked })}
                      className="accent-brand-500 w-4 h-4" />
                    <span className="text-xs underline text-slate-300">Underline</span>
                  </label>
                </div>
                {(() => {
                  const fontMap: Record<string, string> = {
                    helvetica: 'Arial, sans-serif', times: 'Georgia, serif', courier: '"Courier New", monospace',
                    Inter: 'Inter, sans-serif', Roboto: 'Roboto, sans-serif', 'Open Sans': '"Open Sans", sans-serif',
                    Lato: 'Lato, sans-serif', Montserrat: 'Montserrat, sans-serif', Poppins: 'Poppins, sans-serif',
                    Raleway: 'Raleway, sans-serif', Nunito: 'Nunito, sans-serif', Ubuntu: 'Ubuntu, sans-serif',
                    'Source Sans 3': '"Source Sans 3", sans-serif', Oswald: 'Oswald, sans-serif',
                    Georgia: 'Georgia, serif', 'Playfair Display': '"Playfair Display", serif',
                    Merriweather: 'Merriweather, serif', Lora: 'Lora, serif',
                    'Libre Baskerville': '"Libre Baskerville", serif', 'EB Garamond': '"EB Garamond", serif',
                    'Crimson Text': '"Crimson Text", serif', Cinzel: 'Cinzel, serif',
                    'Cormorant Garamond': '"Cormorant Garamond", serif', Spectral: 'Spectral, serif',
                    'Bebas Neue': '"Bebas Neue", cursive',
                    'JetBrains Mono': '"JetBrains Mono", monospace', 'Fira Code': '"Fira Code", monospace',
                  }
                  const ff = fontMap[company.company_name_font] ?? 'Arial, sans-serif'
                  const displayName = company.invoice_company_name?.trim() || company.name || 'Your Company Name'
                  const brandRgb = company.brand_color
                  return (
                    <div className="mt-2 rounded-xl border border-surface-600 overflow-hidden bg-white shadow-sm">
                      <div className="h-2" style={{ backgroundColor: brandRgb }} />
                      <div className="px-5 py-4 flex items-start justify-between bg-white">
                        <div>
                          <p style={{
                            fontFamily: ff,
                            fontSize: `${Math.round(company.company_name_font_size * 0.85)}px`,
                            fontWeight: company.company_name_font_bold ? 700 : 400,
                            fontStyle: company.company_name_font_italic ? 'italic' : 'normal',
                            textDecoration: company.company_name_font_underline ? 'underline' : 'none',
                            color: company.company_name_font_color,
                          }}>
                            {displayName}
                          </p>
                          <p className="text-[9px] mt-1" style={{ color: '#888' }}>123 Business Street, Lagos, Nigeria</p>
                        </div>
                        <div className="text-right">
                          <p style={{ color: brandRgb, fontWeight: 800, fontSize: '18px' }}>INVOICE</p>
                          <p className="text-[9px] mt-1" style={{ color: '#888' }}>INV-0001</p>
                        </div>
                      </div>
                      <div className="px-5 pb-2">
                        <span className="text-[9px] text-slate-400 italic">↑ Preview of how your company name will appear</span>
                      </div>
                    </div>
                  )
                })()}
              </div>
            </div>
          </div>

          {/* Company Stamp */}
          <div className="card p-6 space-y-4">
            <div>
              <h3 className="text-base font-semibold text-white mb-1">Company Stamp / Seal</h3>
              <p className="text-sm text-slate-400">Optional digital stamp added to all invoices and delivery notes. Use a transparent PNG for best results.</p>
            </div>
            <div className="flex items-start gap-4">
              {(stampPreview && !stampRemoved) ? (
                <div className="relative group">
                  <img src={stampPreview} alt="Company stamp" className="w-24 h-24 object-contain rounded-xl border border-surface-600 bg-white p-1" />
                  <button
                    type="button"
                    onClick={() => { setStampPreview(null); setStampFile(null); setStampRemoved(true) }}
                    className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-red-500 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <X size={12} className="text-white" />
                  </button>
                </div>
              ) : (
                <div
                  onClick={() => stampRef.current?.click()}
                  className="w-24 h-24 rounded-xl border-2 border-dashed border-surface-600 hover:border-brand-500 flex flex-col items-center justify-center gap-1 cursor-pointer transition-colors"
                >
                  <Camera size={20} className="text-slate-500" />
                  <span className="text-xs text-slate-500">Upload stamp</span>
                </div>
              )}
              <div className="flex-1 space-y-2">
                <input ref={stampRef} type="file" accept="image/*" className="hidden" onChange={handleStampChange} />
                <button type="button" onClick={() => stampRef.current?.click()} className="btn-secondary text-sm">
                  {(stampPreview && !stampRemoved) ? 'Change Stamp' : 'Choose Image'}
                </button>
                {(stampPreview && !stampRemoved) && (
                  <button type="button" onClick={() => { setStampPreview(null); setStampFile(null); setStampRemoved(true) }} className="block text-xs text-red-400 hover:text-red-300">
                    Remove stamp
                  </button>
                )}
                <p className="text-xs text-slate-500">PNG with transparent background recommended · Max 2MB</p>
              </div>
            </div>
          </div>

          <button onClick={saveCompany} disabled={savingCompany} className="btn-primary flex items-center gap-2 disabled:opacity-50">
            {savingCompany ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle size={15} />}
            Save Template Settings
          </button>
          </div>{/* end left column */}

          {/* ── Right: full A4 preview ──────────────────────── */}
          <div className="sticky top-4">
            <p className="text-xs text-slate-500 uppercase tracking-wider font-medium mb-3">Live Preview</p>
            <div className="rounded-xl overflow-hidden shadow-2xl border border-surface-700 bg-white" style={{ fontFamily: 'Arial, sans-serif' }}>
              {/* CLASSIC */}
              {company.invoice_template === 'classic' && (
                <div style={{ fontSize: 11, color: '#1e293b' }}>
                  <div style={{ background: company.brand_color || '#f97316', padding: '20px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ width: 48, height: 48, background: 'rgba(255,255,255,0.25)', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 8, fontSize: 9, color: 'rgba(255,255,255,0.8)', fontWeight: 600 }}>LOGO</div>
                      <div style={{ color: 'white', fontWeight: 700, fontSize: 16 }}>Acme Business Ltd</div>
                      <div style={{ color: 'rgba(255,255,255,0.75)', fontSize: 10, marginTop: 2 }}>12 Marina Street, Lagos Island</div>
                      <div style={{ color: 'rgba(255,255,255,0.75)', fontSize: 10 }}>info@acmebiz.ng · 0801 234 5678</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ color: 'white', fontWeight: 800, fontSize: 22, letterSpacing: 2 }}>INVOICE</div>
                      <div style={{ color: 'rgba(255,255,255,0.85)', fontSize: 10, marginTop: 4 }}>#INV-0042</div>
                      <div style={{ color: 'rgba(255,255,255,0.75)', fontSize: 10 }}>Date: 22 Mar 2026</div>
                      <div style={{ color: 'rgba(255,255,255,0.75)', fontSize: 10 }}>Due: 21 Apr 2026</div>
                    </div>
                  </div>
                  <div style={{ padding: '16px 24px', display: 'flex', justifyContent: 'space-between' }}>
                    <div>
                      <div style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', color: '#94a3b8', marginBottom: 4 }}>Bill To</div>
                      <div style={{ fontWeight: 600 }}>Global Ventures Ltd</div>
                      <div style={{ color: '#64748b', fontSize: 10 }}>45 Broad St, Victoria Island</div>
                      <div style={{ color: '#64748b', fontSize: 10 }}>Lagos, Nigeria</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', color: '#94a3b8', marginBottom: 4 }}>Payment Terms</div>
                      <div style={{ fontSize: 10, color: '#64748b' }}>Net 30 days</div>
                      <div style={{ fontSize: 9, color: '#94a3b8', marginTop: 6 }}>TIN: 12345678-0001</div>
                    </div>
                  </div>
                  <div style={{ margin: '0 24px' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                      <thead>
                        <tr style={{ background: company.brand_color || '#f97316' }}>
                          {['Description', 'Qty', 'Unit Price', 'Total'].map(h => (
                            <th key={h} style={{ color: 'white', padding: '7px 8px', textAlign: h === 'Description' ? 'left' : 'right', fontWeight: 600, fontSize: 9 }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {[['Web Design Service', '1', '₦150,000', '₦150,000'], ['SEO Optimisation', '3', '₦25,000', '₦75,000'], ['Monthly Hosting', '12', '₦8,500', '₦102,000'], ['SSL Certificate', '1', '₦12,000', '₦12,000']].map(([d, q, u, t], i) => (
                          <tr key={i} style={{ background: i % 2 === 0 ? '#f8fafc' : 'white' }}>
                            <td style={{ padding: '6px 8px' }}>{d}</td>
                            <td style={{ padding: '6px 8px', textAlign: 'right' }}>{q}</td>
                            <td style={{ padding: '6px 8px', textAlign: 'right' }}>{u}</td>
                            <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 600 }}>{t}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div style={{ padding: '12px 24px', display: 'flex', justifyContent: 'flex-end' }}>
                    <div style={{ minWidth: 180 }}>
                      {[['Subtotal', '₦339,000'], ['VAT (7.5%)', '₦25,425']].map(([l, v]) => (
                        <div key={l} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', color: '#64748b', fontSize: 10 }}>
                          <span>{l}</span><span>{v}</span>
                        </div>
                      ))}
                      <div style={{ display: 'flex', justifyContent: 'space-between', background: company.brand_color || '#f97316', color: 'white', padding: '7px 10px', borderRadius: 6, marginTop: 6, fontWeight: 700, fontSize: 12 }}>
                        <span>Total</span><span>₦364,425</span>
                      </div>
                    </div>
                  </div>
                  <div style={{ background: '#f8fafc', borderTop: '1px solid #e2e8f0', padding: '10px 24px', fontSize: 9, color: '#94a3b8', display: 'flex', justifyContent: 'space-between' }}>
                    <span>Bank: First Bank · Acme Business Ltd · 3012345678</span>
                    <span>Thank you for your business!</span>
                  </div>
                </div>
              )}

              {/* MODERN */}
              {company.invoice_template === 'modern' && (
                <div style={{ fontSize: 11, color: '#1e293b' }}>
                  {/* 4px brand accent bar */}
                  <div style={{ height: 4, background: company.brand_color || '#f97316' }} />
                  {/* Header: company left, INVOICE + info-box right */}
                  <div style={{ padding: '16px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ width: 40, height: 40, background: '#f1f5f9', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 6, fontSize: 8, color: '#94a3b8', fontWeight: 600, border: '1px dashed #cbd5e1' }}>LOGO</div>
                      <div style={{ fontWeight: 700, fontSize: 14 }}>Acme Business Ltd</div>
                      <div style={{ color: '#64748b', fontSize: 9, marginTop: 2 }}>12 Marina Street, Lagos Island</div>
                      <div style={{ color: '#64748b', fontSize: 9 }}>info@acmebiz.ng</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ color: company.brand_color || '#f97316', fontWeight: 800, fontSize: 22, letterSpacing: 3 }}>INVOICE</div>
                      {/* Floating rounded info box — matches jsPDF roundedRect */}
                      <div style={{ background: '#f8fafc', borderRadius: 6, padding: '6px 10px', marginTop: 4, fontSize: 9 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 20 }}><span style={{ color: '#94a3b8' }}>Number</span><strong style={{ color: '#1e293b' }}>#INV-0042</strong></div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 20, marginTop: 3 }}><span style={{ color: '#94a3b8' }}>Date</span><strong style={{ color: '#1e293b' }}>22 Mar 2026</strong></div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 20, marginTop: 3 }}><span style={{ color: '#94a3b8' }}>Status</span><strong style={{ color: '#1e293b' }}>PAID</strong></div>
                      </div>
                    </div>
                  </div>
                  {/* Brand-color divider line — matches doc.line(...BRAND...) */}
                  <div style={{ height: 1, background: company.brand_color || '#f97316', margin: '0 24px 12px' }} />
                  {/* Bill To */}
                  <div style={{ padding: '0 24px 10px' }}>
                    <div style={{ fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: company.brand_color || '#f97316', marginBottom: 3 }}>Bill To</div>
                    <div style={{ fontWeight: 600 }}>Global Ventures Ltd</div>
                    <div style={{ color: '#64748b', fontSize: 9 }}>45 Broad St, Victoria Island, Lagos</div>
                  </div>
                  <div style={{ margin: '0 24px' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                      <thead>
                        <tr style={{ background: company.brand_color || '#f97316' }}>
                          {['Description', 'Qty', 'Unit Price', 'Total'].map(h => (
                            <th key={h} style={{ color: 'white', padding: '6px 4px', textAlign: h === 'Description' ? 'left' : 'right', fontWeight: 600, fontSize: 9 }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {[['Web Design Service', '1', '₦150,000', '₦150,000'], ['SEO Optimisation', '3', '₦25,000', '₦75,000'], ['Monthly Hosting', '12', '₦8,500', '₦102,000'], ['SSL Certificate', '1', '₦12,000', '₦12,000']].map(([d, q, u, t], i) => (
                          <tr key={i} style={{ background: i % 2 === 0 ? '#f8f8f8' : 'white' }}>
                            <td style={{ padding: '6px 4px' }}>{d}</td>
                            <td style={{ padding: '6px 4px', textAlign: 'right', color: '#64748b' }}>{q}</td>
                            <td style={{ padding: '6px 4px', textAlign: 'right', color: '#64748b' }}>{u}</td>
                            <td style={{ padding: '6px 4px', textAlign: 'right', fontWeight: 600 }}>{t}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div style={{ padding: '12px 24px 16px', display: 'flex', justifyContent: 'flex-end' }}>
                    <div style={{ minWidth: 190 }}>
                      {[['Subtotal', '₦339,000'], ['VAT (7.5%)', '₦25,425']].map(([l, v]) => (
                        <div key={l} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', color: '#64748b', fontSize: 10 }}>
                          <span>{l}</span><span>{v}</span>
                        </div>
                      ))}
                      <div style={{ display: 'flex', justifyContent: 'space-between', background: company.brand_color || '#f97316', color: 'white', padding: '7px 10px', borderRadius: 6, marginTop: 6, fontWeight: 700, fontSize: 12 }}>
                        <span>Total</span><span>₦364,425</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* MINIMAL */}
              {company.invoice_template === 'minimal' && (
                <div style={{ fontSize: 11, color: '#1e293b', padding: '24px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
                    <div>
                      <div style={{ width: 44, height: 44, background: '#f1f5f9', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 8, fontSize: 9, color: '#94a3b8', fontWeight: 600, border: '1px dashed #cbd5e1' }}>LOGO</div>
                      <div style={{ fontWeight: 700, fontSize: 14 }}>Acme Business Ltd</div>
                      <div style={{ color: '#64748b', fontSize: 10 }}>12 Marina Street, Lagos Island</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontWeight: 800, fontSize: 18, letterSpacing: 2, color: '#1e293b' }}>INVOICE</div>
                      <div style={{ fontSize: 10, color: '#64748b', marginTop: 4 }}>#INV-0042</div>
                      <div style={{ fontSize: 10, color: '#64748b' }}>22 Mar 2026</div>
                      <div style={{ fontSize: 10, color: '#64748b' }}>Due: 21 Apr 2026</div>
                    </div>
                  </div>
                  <div style={{ borderTop: '2px solid #1e293b', borderBottom: '1px solid #e2e8f0', padding: '10px 0', marginBottom: 12, display: 'flex', justifyContent: 'space-between' }}>
                    <div>
                      <div style={{ fontSize: 9, fontWeight: 700, textTransform: 'uppercase', color: '#1e293b', marginBottom: 3 }}>Bill To</div>
                      <div style={{ fontWeight: 600 }}>Global Ventures Ltd</div>
                      <div style={{ color: '#64748b', fontSize: 10 }}>45 Broad St, Victoria Island</div>
                    </div>
                  </div>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
                    <thead>
                      <tr style={{ background: '#1e293b' }}>
                        {['Description', 'Qty', 'Unit Price', 'Total'].map(h => (
                          <th key={h} style={{ color: 'white', padding: '5px 4px', textAlign: h === 'Description' ? 'left' : 'right', fontWeight: 700, fontSize: 9, textTransform: 'uppercase' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {[['Web Design Service', '1', '₦150,000', '₦150,000'], ['SEO Optimisation', '3', '₦25,000', '₦75,000'], ['Monthly Hosting', '12', '₦8,500', '₦102,000'], ['SSL Certificate', '1', '₦12,000', '₦12,000']].map(([d, q, u, t], i) => (
                        <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                          <td style={{ padding: '6px 4px' }}>{d}</td>
                          <td style={{ padding: '6px 4px', textAlign: 'right', color: '#64748b' }}>{q}</td>
                          <td style={{ padding: '6px 4px', textAlign: 'right', color: '#64748b' }}>{u}</td>
                          <td style={{ padding: '6px 4px', textAlign: 'right', fontWeight: 600 }}>{t}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div style={{ borderTop: '2px solid #1e293b', marginTop: 8, paddingTop: 8, display: 'flex', justifyContent: 'flex-end' }}>
                    <div style={{ minWidth: 180 }}>
                      {[['Subtotal', '₦339,000'], ['VAT (7.5%)', '₦25,425']].map(([l, v]) => (
                        <div key={l} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', color: '#64748b', fontSize: 10 }}><span>{l}</span><span>{v}</span></div>
                      ))}
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 800, fontSize: 13, marginTop: 6, paddingTop: 6, borderTop: '1px solid #1e293b' }}>
                        <span>Total</span><span>₦364,425</span>
                      </div>
                    </div>
                  </div>
                  <div style={{ marginTop: 16, fontSize: 9, color: '#94a3b8', borderTop: '1px solid #e2e8f0', paddingTop: 8 }}>
                    Bank: First Bank · Acme Business Ltd · 3012345678
                  </div>
                </div>
              )}

              {/* PROFESSIONAL */}
              {company.invoice_template === 'professional' && (
                <div style={{ fontSize: 11, color: '#1e293b' }}>
                  {/* Split header: brand-color left (~46%) | light right */}
                  <div style={{ display: 'flex' }}>
                    <div style={{ background: company.brand_color || '#f97316', width: '46%', padding: '20px 18px', minHeight: 110 }}>
                      <div style={{ width: 40, height: 40, background: 'rgba(255,255,255,0.2)', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 8, fontSize: 8, color: 'rgba(255,255,255,0.8)', fontWeight: 600 }}>LOGO</div>
                      <div style={{ color: 'white', fontWeight: 700, fontSize: 13 }}>Acme Business Ltd</div>
                      <div style={{ color: 'rgba(255,255,255,0.75)', fontSize: 9, marginTop: 3 }}>12 Marina Street, Lagos</div>
                      <div style={{ color: 'rgba(255,255,255,0.75)', fontSize: 9 }}>info@acmebiz.ng</div>
                    </div>
                    <div style={{ flex: 1, background: '#f8fafc', padding: '16px 18px' }}>
                      <div style={{ fontWeight: 800, fontSize: 16, letterSpacing: 2, color: '#1e293b', textAlign: 'right' }}>INVOICE</div>
                      <div style={{ fontSize: 9, color: '#64748b', marginTop: 6, lineHeight: 1.9 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#94a3b8' }}>Invoice No.</span><strong style={{ color: '#1e293b' }}>#INV-0042</strong></div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#94a3b8' }}>Date</span><strong style={{ color: '#1e293b' }}>22 Mar 2026</strong></div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#94a3b8' }}>Payment</span><strong style={{ color: '#1e293b' }}>Cash</strong></div>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#94a3b8' }}>Status</span><strong style={{ color: '#1e293b' }}>PAID</strong></div>
                      </div>
                    </div>
                  </div>
                  {/* Bill To */}
                  <div style={{ padding: '10px 18px', background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                    <div style={{ fontSize: 8, fontWeight: 700, textTransform: 'uppercase', color: company.brand_color || '#f97316', marginBottom: 3 }}>Bill To</div>
                    <div style={{ fontWeight: 600, fontSize: 10 }}>Global Ventures Ltd</div>
                    <div style={{ color: '#64748b', fontSize: 9 }}>45 Broad St, Victoria Island, Lagos</div>
                  </div>
                  <div style={{ padding: '0 18px 4px' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, marginTop: 8 }}>
                      <thead>
                        <tr style={{ background: company.brand_color || '#f97316' }}>
                          {['Description', 'Qty', 'Unit Price', 'Total'].map(h => (
                            <th key={h} style={{ color: 'white', padding: '7px 6px', textAlign: h === 'Description' ? 'left' : 'right', fontWeight: 600, fontSize: 9 }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {[['Web Design Service', '1', '₦150,000', '₦150,000'], ['SEO Optimisation', '3', '₦25,000', '₦75,000'], ['Monthly Hosting', '12', '₦8,500', '₦102,000'], ['SSL Certificate', '1', '₦12,000', '₦12,000']].map(([d, q, u, t], i) => (
                          <tr key={i} style={{ background: i % 2 === 0 ? '#f8fafc' : 'white' }}>
                            <td style={{ padding: '6px 6px' }}>{d}</td>
                            <td style={{ padding: '6px 6px', textAlign: 'right', color: '#64748b' }}>{q}</td>
                            <td style={{ padding: '6px 6px', textAlign: 'right', color: '#64748b' }}>{u}</td>
                            <td style={{ padding: '6px 6px', textAlign: 'right', fontWeight: 600 }}>{t}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div style={{ padding: '10px 18px 16px', display: 'flex', justifyContent: 'flex-end' }}>
                    <div style={{ minWidth: 185 }}>
                      {[['Subtotal', '₦339,000'], ['VAT (7.5%)', '₦25,425']].map(([l, v]) => (
                        <div key={l} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', color: '#64748b', fontSize: 10 }}><span>{l}</span><span>{v}</span></div>
                      ))}
                      <div style={{ display: 'flex', justifyContent: 'space-between', background: company.brand_color || '#f97316', color: 'white', padding: '7px 10px', borderRadius: 6, marginTop: 6, fontWeight: 700, fontSize: 12 }}>
                        <span>Total</span><span>₦364,425</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
            <p className="text-xs text-slate-600 mt-2 text-center">Preview uses dummy data · Brand colour applied from Company tab</p>
          </div>
        </div>
      )}

      {/* ── AI Assistant ─────────────────────────────────────────────────── */}
      {activeTab === 'ai' && (
        <div className="space-y-6 max-w-3xl">
          <div className="card p-6 space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-brand-500/20 flex items-center justify-center">
                <Bot size={20} className="text-brand-400" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-white">AI Financial Assistant</h3>
                <p className="text-sm text-slate-400">Powered by Groq · Trained on your live financial data</p>
              </div>
            </div>
          </div>

          <div className="card p-6 space-y-4">
            <div>
              <h3 className="text-base font-semibold text-white mb-1">Business Context</h3>
              <p className="text-sm text-slate-400 mb-3">
                Describe your business to personalise AI responses. Include industry, type of business, key goals, and anything the AI should know.
              </p>
              <textarea
                className="input resize-none w-full"
                rows={6}
                placeholder={`Example:\nWe are a wholesale food distribution company based in Lagos. We sell to retailers and supermarkets. Our main costs are logistics and procurement. We want to grow revenue by 30% this year and reduce our overdue invoices.\n\nFocus on cash flow, overdue customers, and profitability advice.`}
                value={company.ai_custom_context}
                onChange={(e) => setCompany((c: typeof company) => ({ ...c, ai_custom_context: e.target.value }))}
                maxLength={2000}
              />
              <p className="text-xs text-slate-500 mt-1 text-right">{(company.ai_custom_context ?? '').length}/2000</p>
            </div>
            <button onClick={saveAIContext} disabled={savingCompany} className="btn-primary flex items-center gap-2 disabled:opacity-50">
              {savingCompany ? <Loader2 size={15} className="animate-spin" /> : <CheckCircle size={15} />}
              Save AI Context
            </button>
          </div>

          <div className="card p-6 space-y-3">
            <h3 className="text-base font-semibold text-white">Quick Test</h3>
            <p className="text-sm text-slate-400">Go to the Dashboard and click <strong className="text-brand-400">Explain My Money</strong> to open the AI assistant.</p>
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <Bot size={13} className="text-brand-400" />
              Ask things like: "Am I making profit?", "Where am I losing money?", "How is my cash flow?"
            </div>
          </div>
        </div>
      )}

      {/* ── GL Mapping Tab ───────────────────────────────────────────────── */}
      {activeTab === 'gl_mapping' && (
        <div className="space-y-6 max-w-3xl">
          <div>
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <GitBranch size={18} className="text-brand-400" /> Account Mapping
            </h2>
            <p className="text-sm text-slate-400 mt-1">
              Map GL roles to your chart of accounts. These are used for automatic journal posting.
            </p>
          </div>
          {!glMapping ? (
            <div className="flex justify-center py-8"><Loader2 size={24} className="animate-spin text-slate-400" /></div>
          ) : (
            <div className="space-y-3">
              {[
                { role: 'revenue_account',         label: 'Revenue Account',          hint: 'Sales/revenue credited on invoice' },
                { role: 'cogs_account',             label: 'Cost of Goods Sold',       hint: 'Debited on sale for product cost' },
                { role: 'inventory_account',        label: 'Inventory Account',        hint: 'Credited on sale (stock reduction)' },
                { role: 'accounts_receivable',      label: 'Accounts Receivable',      hint: 'Debited for credit sales' },
                { role: 'cash_account',             label: 'Cash Account',             hint: 'Debited on cash payments received' },
                { role: 'bank_account',             label: 'Bank Account',             hint: 'Debited on bank/POS payments' },
                { role: 'accounts_payable',         label: 'Accounts Payable',         hint: 'Credited on bill approval' },
                { role: 'vat_output_account',       label: 'VAT Output (Payable)',     hint: 'Credited on VAT collected' },
                { role: 'vat_input_account',        label: 'VAT Input (Recoverable)',  hint: 'Debited on VAT paid to suppliers' },
                { role: 'paye_account',             label: 'PAYE Payable',             hint: 'Credited on payroll run' },
                { role: 'pension_account',          label: 'Pension Payable',          hint: 'Credited on payroll run' },
                { role: 'wht_account',              label: 'WHT / NHF Payable',        hint: 'Withholding tax liability' },
                { role: 'salary_expense_account',   label: 'Salaries & Wages',         hint: 'Debited on payroll run' },
                { role: 'general_expense_account',  label: 'General Expenses',         hint: 'Debited on expense recording' },
                { role: 'bank_charges_account',     label: 'Bank Charges',             hint: 'Bank fees expense account' },
              ].map(({ role, label, hint }) => {
                const currentId = glMapping[`${role}_id`] ?? null
                const suggestion = glMapping[`${role}_suggestion`]
                return (
                  <div key={role} className="rounded-lg bg-slate-800 border border-slate-700 px-4 py-3 flex flex-col sm:flex-row sm:items-center gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-white">{label}</p>
                      <p className="text-xs text-slate-500">{hint}</p>
                      {!currentId && suggestion && (
                        <p className="text-xs text-amber-400 mt-0.5">Suggested: {suggestion.code} – {suggestion.name}</p>
                      )}
                    </div>
                    <select
                      className="w-full sm:w-64 bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-brand-500"
                      value={currentId ?? ''}
                      onChange={(e) => {
                        const val = e.target.value || null
                        setGlMapping((prev: any) => ({
                          ...prev,
                          [`${role}_id`]: val,
                          [`${role}_name`]: glAccounts.find((a: any) => a.id === val)?.name ?? null,
                        }))
                      }}
                    >
                      <option value="">— Not mapped —</option>
                      {glAccounts.map((a: any) => (
                        <option key={a.id} value={a.id}>{a.code} – {a.name}</option>
                      ))}
                    </select>
                  </div>
                )
              })}
              <button
                onClick={async () => {
                  setGlMappingSaving(true)
                  try {
                    const payload: Record<string, string | null> = {}
                    const roles = ['revenue_account','cogs_account','inventory_account','accounts_receivable','cash_account','bank_account','accounts_payable','vat_output_account','vat_input_account','paye_account','pension_account','wht_account','salary_expense_account','general_expense_account','bank_charges_account']
                    roles.forEach((r) => { payload[r] = glMapping?.[`${r}_id`] ?? null })
                    const res = await accountingApi.updateAccountMapping(payload)
                    setGlMapping(res.data)
                    toast.success('Account mapping saved')
                  } catch {
                    toast.error('Failed to save mapping')
                  } finally {
                    setGlMappingSaving(false)
                  }
                }}
                disabled={glMappingSaving}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium disabled:opacity-50"
              >
                {glMappingSaving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
                Save Mapping
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── Accountant Access Tab ─────────────────────────────────────────── */}
      {activeTab === 'access' && (
        <div className="space-y-6 max-w-3xl">
          <div>
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <ShieldCheck size={18} className="text-brand-400" /> Accountant Access
            </h2>
            <p className="text-sm text-slate-400 mt-1">
              Control which accounting firms or accountants can view and manage your books. All access requires your explicit approval.
            </p>
          </div>

          {accessLoading ? (
            <div className="flex items-center justify-center py-12"><Loader2 size={22} className="animate-spin text-brand-400" /></div>
          ) : (
            <>
              {/* Generate invite token */}
              <div className="card p-5 space-y-3 border border-purple-500/20 bg-purple-500/5">
                <h3 className="text-sm font-semibold text-purple-300 flex items-center gap-2"><Key size={14} /> Invite an Accountant</h3>
                <p className="text-xs text-slate-400">
                  Generate a one-time token and share it with your accountant. They paste it in their Partner Dashboard to gain instant access — no approval step needed.
                </p>
                <div className="flex gap-2">
                  <input
                    className="input flex-1"
                    type="email"
                    placeholder="accountant@firm.com"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                  />
                  <button onClick={handleGenerateInvite} disabled={generatingInvite} className="btn-primary text-sm flex items-center gap-1.5 shrink-0">
                    {generatingInvite ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />} Generate Token
                  </button>
                </div>
                {generatedToken && (
                  <div className="p-3 rounded-lg bg-surface-800 border border-surface-600 space-y-2">
                    <p className="text-xs text-slate-400">Share this token with <strong className="text-white">{generatedToken.partner_email}</strong>:</p>
                    <div className="flex items-center gap-2">
                      <code className="flex-1 text-xs font-mono text-brand-300 bg-surface-700 px-3 py-2 rounded-lg break-all">{generatedToken.token}</code>
                      <button
                        onClick={() => { navigator.clipboard.writeText(generatedToken.token); toast.success('Token copied!') }}
                        className="p-2 rounded-lg hover:bg-surface-600 text-slate-400 hover:text-white transition-colors shrink-0"
                        title="Copy token"
                      >
                        <Copy size={14} />
                      </button>
                    </div>
                    <p className="text-xs text-amber-400/70">Single-use · Does not expire · Keep it confidential</p>
                    <button onClick={() => setGeneratedToken(null)} className="text-xs text-slate-500 hover:text-slate-300">Dismiss</button>
                  </div>
                )}
              </div>

              {/* Pending access requests */}
              {partnerRequests.filter((r) => r.status === 'pending').length > 0 && (
                <div className="card p-5 space-y-3">
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                    <Clock size={14} className="text-amber-400" />
                    Pending Requests
                    <span className="bg-amber-500 text-black text-[10px] font-bold px-1.5 py-0.5 rounded-full leading-none">
                      {partnerRequests.filter((r) => r.status === 'pending').length}
                    </span>
                  </h3>
                  <div className="space-y-2">
                    {partnerRequests.filter((r) => r.status === 'pending').map((req) => (
                      <div key={req.id} className="flex items-start justify-between gap-3 p-3 rounded-lg bg-surface-800 border border-amber-500/20">
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-white">{req.partner_firm_name || req.partner_email}</p>
                          <p className="text-xs text-slate-400">{req.partner_email} · {req.partner_tier} tier</p>
                          {req.request_message && <p className="text-xs text-slate-400 italic mt-1">"{req.request_message}"</p>}
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <button
                            onClick={() => handleApprovePartner(req.id)}
                            disabled={approvingReq === req.id}
                            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-green-500/10 text-green-400 hover:bg-green-500/20 transition-colors font-medium"
                          >
                            {approvingReq === req.id ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle size={11} />} Approve
                          </button>
                          <button
                            onClick={() => handleRejectPartner(req.id)}
                            disabled={rejectingReq === req.id}
                            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors font-medium"
                          >
                            {rejectingReq === req.id ? <Loader2 size={11} className="animate-spin" /> : <XCircle size={11} />} Reject
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Active partner links */}
              <div className="card p-5 space-y-3">
                <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                  <CheckCircle size={14} className="text-green-400" /> Active Accountant Access
                </h3>
                {partnerLinks.length === 0 ? (
                  <p className="text-sm text-slate-500">No accountants currently have access to this organisation.</p>
                ) : (
                  <div className="space-y-2">
                    {partnerLinks.map((link) => (
                      <div key={link.id} className="flex items-center justify-between gap-3 p-3 rounded-lg bg-surface-800 border border-surface-600">
                        <div>
                          <p className="text-sm font-medium text-white">{link.org_name}</p>
                          <p className="text-xs text-slate-400">Linked {new Date(link.linked_at).toLocaleDateString('en-NG', { day: '2-digit', month: 'short', year: 'numeric' })}</p>
                        </div>
                        <button
                          onClick={() => handleRevokePartnerAccess(link.id)}
                          disabled={revokingLink === link.id}
                          className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg text-red-400 hover:bg-red-400/10 transition-colors font-medium"
                        >
                          {revokingLink === link.id ? <Loader2 size={11} className="animate-spin" /> : <XCircle size={11} />} Revoke Access
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Request history */}
              {partnerRequests.filter((r) => r.status !== 'pending').length > 0 && (
                <div className="card p-5 space-y-3">
                  <h3 className="text-sm font-semibold text-white text-slate-400">Request History</h3>
                  <div className="space-y-1.5">
                    {partnerRequests.filter((r) => r.status !== 'pending').map((req) => (
                      <div key={req.id} className="flex items-center justify-between gap-3 p-3 rounded-lg bg-surface-800/50">
                        <div>
                          <p className="text-sm text-slate-300">{req.partner_firm_name || req.partner_email}</p>
                          {req.rejection_reason && <p className="text-xs text-red-400/70 italic">"{req.rejection_reason}"</p>}
                        </div>
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                          req.status === 'approved' ? 'bg-green-500/10 text-green-400' :
                          req.status === 'rejected' ? 'bg-red-500/10 text-red-400' :
                          'bg-slate-500/10 text-slate-400'
                        }`}>{req.status}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>

    {/* Member remove / delete modal */}
    {deactivateTarget && (
      <div className="fixed inset-0 z-[80] flex items-center justify-center p-4">
        <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setDeactivateTarget(null)} />
        <div className="relative card w-full max-w-sm p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold text-white">
              {deactivateTarget.is_active ? 'Remove Team Member' : 'Delete Member'}
            </h2>
            <button onClick={() => setDeactivateTarget(null)} className="text-slate-400 hover:text-white"><X size={18} /></button>
          </div>
          <p className="text-sm text-slate-400">
            {deactivateTarget.is_active
              ? <>How do you want to remove <span className="font-semibold text-white">{deactivateTarget.user_full_name || deactivateTarget.user_email}</span>?</>
              : <>Permanently delete <span className="font-semibold text-white">{deactivateTarget.user_full_name || deactivateTarget.user_email}</span>? This cannot be undone.</>
            }
          </p>
          <div className="space-y-2">
            {/* Only show deactivate option for currently active members */}
            {deactivateTarget.is_active && (
              <button
                onClick={() => confirmDeactivate(false)}
                disabled={deactivating}
                className="w-full flex flex-col items-start px-4 py-3 rounded-xl border border-surface-600 bg-surface-700/40 hover:bg-surface-700/80 text-left transition-colors disabled:opacity-50"
              >
                <span className="text-sm font-semibold text-white">Temporarily Deactivate</span>
                <span className="text-xs text-slate-400 mt-0.5">Revokes access but keeps the record. Frees up a slot for someone else.</span>
              </button>
            )}
            <button
              onClick={() => confirmDeactivate(true)}
              disabled={deactivating}
              className="w-full flex flex-col items-start px-4 py-3 rounded-xl border border-red-500/30 bg-red-500/5 hover:bg-red-500/10 text-left transition-colors disabled:opacity-50"
            >
              <span className="text-sm font-semibold text-red-400 flex items-center gap-1.5"><Trash2 size={14} /> Permanently Delete</span>
              <span className="text-xs text-slate-400 mt-0.5">Removes all access and data. This action cannot be undone.</span>
            </button>
          </div>
          {deactivating && (
            <div className="flex justify-center py-1">
              <Loader2 size={18} className="animate-spin text-brand-400" />
            </div>
          )}
        </div>
      </div>
    )}
      {/* ── White-label Tab ──────────────────────────────────────────────── */}
      {activeTab === 'whitelabel' && (
        <WhiteLabelTab />
      )}

      {/* ── FIRS e-invoicing Tab ─────────────────────────────────────────── */}
      {activeTab === 'firs' && (
        <FirsTab />
      )}
    </>
  )
}

// ── White-label Settings ──────────────────────────────────────────────────────

function WhiteLabelTab() {
  const { planName } = useAuthStore()
  const isAgency = planName?.includes('agency') ?? false

  const [config, setConfig] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [verifying, setVerifying] = useState(false)
  const [form, setForm] = useState({
    custom_domain: '', brand_name: '', logo_url: '', favicon_url: '',
    primary_color: '#f97316', login_tagline: '',
  })

  useEffect(() => {
    partnerApi.getWhiteLabel()
      .then((r) => {
        setConfig(r.data)
        setForm({
          custom_domain: r.data.custom_domain ?? '',
          brand_name: r.data.brand_name ?? '',
          logo_url: r.data.logo_url ?? '',
          favicon_url: r.data.favicon_url ?? '',
          primary_color: r.data.primary_color ?? '#f97316',
          login_tagline: r.data.login_tagline ?? '',
        })
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      const r = await partnerApi.saveWhiteLabel(form)
      setConfig(r.data)
      toast.success('White-label config saved')
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Failed to save'
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const handleVerify = async () => {
    setVerifying(true)
    try {
      const r = await partnerApi.verifyDomain()
      toast.success(r.data.message ?? 'Domain verified!')
      setConfig((c: any) => ({ ...c, is_domain_verified: true }))
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Verification failed'
      toast.error(typeof msg === 'string' ? msg : 'Verification failed — check DNS record and try again')
    } finally {
      setVerifying(false)
    }
  }

  if (!isAgency) {
    return (
      <div className="card p-6 text-center space-y-3 max-w-md">
        <Globe size={28} className="mx-auto text-slate-500" />
        <p className="text-sm font-semibold text-white">Agency plan required</p>
        <p className="text-xs text-slate-400">White-label domain configuration is available on the Partner Agency plan.</p>
      </div>
    )
  }

  if (loading) return <div className="flex justify-center py-12"><Loader2 size={20} className="animate-spin text-brand-400" /></div>

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="card p-6 space-y-5">
        <h2 className="text-sm font-semibold text-white flex items-center gap-2"><Globe size={16} className="text-brand-400" /> White-label Configuration</h2>

        {/* Domain */}
        <div className="space-y-1">
          <label className="text-xs text-slate-400">Custom Domain</label>
          <div className="flex gap-2">
            <input
              className="input flex-1 text-sm"
              placeholder="portal.yourfirm.com"
              value={form.custom_domain}
              onChange={(e) => setForm((f) => ({ ...f, custom_domain: e.target.value }))}
            />
            <button
              onClick={handleVerify}
              disabled={verifying || !config?.custom_domain}
              className="btn-ghost text-xs flex items-center gap-1.5 px-3"
            >
              {verifying ? <Loader2 size={12} className="animate-spin" /> : null}
              Verify
            </button>
          </div>
          <div className="flex items-center gap-2 text-xs mt-1">
            {config?.is_domain_verified
              ? <span className="text-green-400 flex items-center gap-1"><CheckCircle size={12} /> Verified</span>
              : <span className="text-amber-400">Not verified</span>}
            {config?.ssl_active
              ? <span className="text-green-400 flex items-center gap-1"><CheckCircle size={12} /> SSL active</span>
              : <span className="text-slate-500">SSL pending (platform admin enables)</span>}
          </div>
        </div>

        {/* DNS instructions */}
        {config?.dns_instructions && (
          <div className="bg-surface-700/40 rounded-xl p-4 space-y-2 text-xs font-mono text-slate-300">
            <p className="text-slate-400 font-sans font-semibold text-xs not-italic">DNS Records to add:</p>
            <p><span className="text-slate-500">TXT </span>{config.dns_instructions.txt_name}</p>
            <p className="text-brand-400 pl-4 break-all">{config.dns_instructions.txt_value}</p>
            <p className="mt-2"><span className="text-slate-500">CNAME </span>{config.dns_instructions.cname_name}</p>
            <p className="text-brand-400 pl-4">{config.dns_instructions.cname_value}</p>
          </div>
        )}

        {/* Branding */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-slate-400 block mb-1">Brand Name</label>
            <input className="input w-full text-sm" placeholder="Smith Accounting" value={form.brand_name} onChange={(e) => setForm((f) => ({ ...f, brand_name: e.target.value }))} />
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">Primary Colour</label>
            <div className="flex gap-2 items-center">
              <input type="color" value={form.primary_color} onChange={(e) => setForm((f) => ({ ...f, primary_color: e.target.value }))} className="w-10 h-9 rounded cursor-pointer border border-surface-600 bg-transparent" />
              <input className="input flex-1 text-sm font-mono" value={form.primary_color} onChange={(e) => setForm((f) => ({ ...f, primary_color: e.target.value }))} />
            </div>
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">Logo URL</label>
            <input className="input w-full text-sm" placeholder="https://…" value={form.logo_url} onChange={(e) => setForm((f) => ({ ...f, logo_url: e.target.value }))} />
          </div>
          <div>
            <label className="text-xs text-slate-400 block mb-1">Favicon URL</label>
            <input className="input w-full text-sm" placeholder="https://…" value={form.favicon_url} onChange={(e) => setForm((f) => ({ ...f, favicon_url: e.target.value }))} />
          </div>
          <div className="col-span-2">
            <label className="text-xs text-slate-400 block mb-1">Login Tagline</label>
            <input className="input w-full text-sm" placeholder="Your finances, handled." value={form.login_tagline} onChange={(e) => setForm((f) => ({ ...f, login_tagline: e.target.value }))} />
          </div>
        </div>

        <button onClick={handleSave} disabled={saving} className="btn-primary flex items-center gap-1.5 text-sm">
          {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
          Save Branding
        </button>
      </div>
    </div>
  )
}

// ── FIRS E-Invoicing Settings Tab ─────────────────────────────────────────────
// Rendered inside SettingsPage's {activeTab === 'firs' && <FirsTab />}.
// Kept as a separate component so it has its own isolated state and avoids
// re-rendering the rest of SettingsPage when FIRS state changes.
function FirsTab() {
  const { organisation } = useAuthStore()
  const [firsConfig, setFirsConfig] = useState<FirsConfig | null>(null)
  const [firsStats, setFirsStats] = useState<FirsStats | null>(null)
  const [firsSubmissions, setFirsSubmissions] = useState<FirsSubmission[]>([])
  const [firsLoading, setFirsLoading] = useState(true)
  const [firsSaving, setFirsSaving] = useState(false)
  const [firsTesting, setFirsTesting] = useState(false)
  const [firsTestResult, setFirsTestResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [firsForm, setFirsForm] = useState({
    tin: '',
    business_name: '',
    app_api_key: '',
    use_sandbox: true,
    app_base_url: 'https://api.digitax.tech/ng/v1',
    is_enrolled: false,
  })
  // Phase 7: sandbox certification + go-live checklist state
  const [sandboxProgress, setSandboxProgress] = useState<SandboxProgress | null>(null)
  const [goLiveChecklist, setGoLiveChecklist] = useState<GoLiveChecklist | null>(null)
  const [sandboxRunning, setSandboxRunning] = useState<'pass' | 'fail' | null>(null)

  const refreshSandboxData = () => {
    Promise.allSettled([
      einvoicingApi.sandboxProgress(),
      einvoicingApi.goLiveChecklist(),
    ]).then(([progRes, checkRes]) => {
      if (progRes.status === 'fulfilled') setSandboxProgress(progRes.value.data)
      if (checkRes.status === 'fulfilled') setGoLiveChecklist(checkRes.value.data)
    }).catch(() => null)
  }

  useEffect(() => {
    setFirsLoading(true)
    Promise.allSettled([
      einvoicingApi.getConfig(),
      einvoicingApi.stats(),
      einvoicingApi.submissions({ page_size: 10 }),
      einvoicingApi.sandboxProgress(),
      einvoicingApi.goLiveChecklist(),
    ]).then(([cfgRes, statsRes, subsRes, progRes, checkRes]) => {
      if (cfgRes.status === 'fulfilled') {
        const cfg: FirsConfig = cfgRes.value.data
        setFirsConfig(cfg)
        setFirsForm({
          tin:           cfg.tin ?? '',
          business_name: cfg.business_name ?? '',
          app_api_key:   '',
          use_sandbox:   cfg.use_sandbox,
          app_base_url:  cfg.app_base_url ?? 'https://api.digitax.tech/ng/v1',
          is_enrolled:   cfg.is_enrolled,
        })
      }
      if (statsRes.status === 'fulfilled') setFirsStats(statsRes.value.data)
      if (subsRes.status === 'fulfilled') {
        const d = subsRes.value.data
        setFirsSubmissions(Array.isArray(d) ? d : d.results ?? [])
      }
      if (progRes.status === 'fulfilled') setSandboxProgress(progRes.value.data)
      if (checkRes.status === 'fulfilled') setGoLiveChecklist(checkRes.value.data)
    }).finally(() => setFirsLoading(false))
  }, [organisation?.id])

  return (
    <div className="space-y-6 max-w-3xl">

          {/* Header + enrollment badge */}
          <div className="card p-6">
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div>
                <h2 className="font-bold text-white text-base">FIRS E-Invoicing Compliance</h2>
                <p className="text-slate-400 text-xs mt-0.5">
                  Connect Audity to DigiTax (Namiri Technology Ltd) as your NITDA-accredited
                  System Integrator for FIRS mandatory e-invoicing.
                </p>
              </div>
              {firsLoading ? (
                <Loader2 size={16} className="animate-spin text-slate-400" />
              ) : firsConfig?.is_enrolled ? (
                <span className={`flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full ${
                  firsConfig.use_sandbox
                    ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                    : 'bg-green-500/20 text-green-300 border border-green-500/30'
                }`}>
                  <CheckCircle size={12} />
                  {firsConfig.use_sandbox ? 'ENROLLED — SANDBOX' : 'ENROLLED — LIVE'}
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full bg-slate-700 text-slate-400 border border-slate-600">
                  <AlertTriangle size={12} />
                  Not Enrolled
                </span>
              )}
            </div>
          </div>

          {/* Credentials form */}
          <div className="card p-6 space-y-5">
            <h3 className="text-sm font-semibold text-white">DigiTax Credentials</h3>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-slate-400 block mb-1">TIN (Tax ID)</label>
                <input
                  className="input w-full text-sm"
                  placeholder="12345678-0001"
                  value={firsForm.tin}
                  onChange={(e) => setFirsForm((f) => ({ ...f, tin: e.target.value }))}
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 block mb-1">Registered Business Name</label>
                <input
                  className="input w-full text-sm"
                  placeholder="Acme Enterprises Ltd"
                  value={firsForm.business_name}
                  onChange={(e) => setFirsForm((f) => ({ ...f, business_name: e.target.value }))}
                />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 block mb-1">
                  DigiTax API Key
                  {firsConfig?.has_api_key && (
                    <span className="ml-2 text-green-400 font-normal">● key is stored</span>
                  )}
                </label>
                <input
                  className="input w-full text-sm font-mono"
                  type="password"
                  placeholder={firsConfig?.has_api_key ? '••••••••••••••••••••••• (leave blank to keep existing)' : 'api_key_…'}
                  value={firsForm.app_api_key}
                  onChange={(e) => setFirsForm((f) => ({ ...f, app_api_key: e.target.value }))}
                  autoComplete="new-password"
                />
                <p className="text-xs text-slate-500 mt-1">
                  Your DigiTax x-api-key. Stored encrypted at rest and never returned in API responses.
                </p>
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 block mb-1">Base URL</label>
                <input
                  className="input w-full text-sm font-mono"
                  value={firsForm.app_base_url}
                  onChange={(e) => setFirsForm((f) => ({ ...f, app_base_url: e.target.value }))}
                />
              </div>
            </div>

            {/* Sandbox toggle */}
            <div className="flex items-center gap-3 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg">
              <button
                onClick={() => setFirsForm((f) => ({ ...f, use_sandbox: !f.use_sandbox }))}
                className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 transition-colors focus:outline-none ${
                  firsForm.use_sandbox ? 'bg-amber-500 border-amber-500' : 'bg-slate-600 border-slate-600'
                }`}
              >
                <span className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                  firsForm.use_sandbox ? 'translate-x-4' : 'translate-x-0'
                }`} />
              </button>
              <div>
                <p className="text-sm font-medium text-white">
                  {firsForm.use_sandbox ? 'Sandbox mode (safe for testing)' : 'Production mode (live submissions)'}
                </p>
                <p className="text-xs text-slate-400">
                  {firsForm.use_sandbox
                    ? 'Submissions go to DigiTax sandbox — no real FIRS records created.'
                    : 'All submissions are sent to FIRS production. Cannot be undone.'}
                </p>
              </div>
            </div>

            {/* Enrollment toggle */}
            <div className="flex items-center gap-3 p-3 bg-surface-700/40 border border-surface-600 rounded-lg">
              <button
                onClick={() => setFirsForm((f) => ({ ...f, is_enrolled: !f.is_enrolled }))}
                className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 transition-colors focus:outline-none ${
                  firsForm.is_enrolled ? 'bg-green-500 border-green-500' : 'bg-slate-600 border-slate-600'
                }`}
              >
                <span className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                  firsForm.is_enrolled ? 'translate-x-4' : 'translate-x-0'
                }`} />
              </button>
              <div>
                <p className="text-sm font-medium text-white">
                  {firsForm.is_enrolled ? 'FIRS submission enabled' : 'FIRS submission disabled'}
                </p>
                <p className="text-xs text-slate-400">
                  When enabled, confirmed invoices are automatically submitted to FIRS via DigiTax.
                </p>
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex items-center gap-3 flex-wrap">
              <button
                onClick={async () => {
                  setFirsSaving(true)
                  try {
                    const payload: Record<string, unknown> = {
                      tin:          firsForm.tin,
                      business_name: firsForm.business_name,
                      use_sandbox:  firsForm.use_sandbox,
                      app_base_url: firsForm.app_base_url,
                      is_enrolled:  firsForm.is_enrolled,
                    }
                    // Only send the key if the field has a value (blank = keep existing)
                    if (firsForm.app_api_key.trim()) payload.app_api_key = firsForm.app_api_key.trim()
                    const { data } = await einvoicingApi.updateConfig(payload)
                    setFirsConfig(data)
                    setFirsForm((f) => ({ ...f, app_api_key: '' }))
                    toast.success('FIRS settings saved')
                  } catch {
                    toast.error('Failed to save FIRS settings')
                  } finally {
                    setFirsSaving(false)
                  }
                }}
                disabled={firsSaving}
                className="btn-primary flex items-center gap-1.5 text-sm"
              >
                {firsSaving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
                Save Settings
              </button>

              <button
                onClick={async () => {
                  setFirsTesting(true)
                  setFirsTestResult(null)
                  try {
                    const { data } = await einvoicingApi.testConnection()
                    setFirsTestResult({ ok: data.ok, message: data.message ?? 'Connection successful' })
                    if (data.ok) toast.success('DigiTax connection successful')
                    else toast.error('DigiTax connection failed')
                    // Refresh config to show updated last_test_at
                    einvoicingApi.getConfig().then(({ data: cfg }) => setFirsConfig(cfg)).catch(() => null)
                  } catch (err: unknown) {
                    const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error ?? 'Test failed'
                    setFirsTestResult({ ok: false, message: msg })
                    toast.error('DigiTax connection failed')
                  } finally {
                    setFirsTesting(false)
                  }
                }}
                disabled={firsTesting || !firsConfig?.has_api_key}
                className="btn-secondary flex items-center gap-1.5 text-sm"
                title={!firsConfig?.has_api_key ? 'Save an API key first' : undefined}
              >
                {firsTesting
                  ? <Loader2 size={14} className="animate-spin" />
                  : firsTestResult?.ok
                  ? <Wifi size={14} className="text-green-400" />
                  : firsTestResult?.ok === false
                  ? <WifiOff size={14} className="text-red-400" />
                  : <RefreshCw size={14} />
                }
                Test Connection
              </button>
            </div>

            {/* Test result feedback */}
            {firsTestResult && (
              <div className={`flex items-start gap-2 p-3 rounded-lg text-sm ${
                firsTestResult.ok
                  ? 'bg-green-500/10 border border-green-500/20 text-green-300'
                  : 'bg-red-500/10 border border-red-500/20 text-red-300'
              }`}>
                {firsTestResult.ok
                  ? <CheckCircle size={14} className="mt-0.5 flex-shrink-0" />
                  : <XCircle size={14} className="mt-0.5 flex-shrink-0" />
                }
                {firsTestResult.message}
              </div>
            )}

            {firsConfig?.last_test_at && (
              <p className="text-xs text-slate-500 flex items-center gap-1">
                <Clock size={10} />
                Last tested: {new Date(firsConfig.last_test_at).toLocaleString()}
                {' — '}
                {firsConfig.last_test_ok
                  ? <span className="text-green-400">OK</span>
                  : <span className="text-red-400">Failed</span>
                }
              </p>
            )}
          </div>

          {/* Submission stats */}
          {firsStats && (
            <div className="card p-6 space-y-4">
              <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                <Activity size={14} />
                Submission Statistics
              </h3>
              <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
                {[
                  { label: 'Total',     value: firsStats.total,     color: 'text-white' },
                  { label: 'Cleared',   value: firsStats.cleared,   color: 'text-green-400' },
                  { label: 'Submitted', value: firsStats.submitted, color: 'text-blue-400' },
                  { label: 'Pending',   value: firsStats.pending,   color: 'text-amber-400' },
                  { label: 'Failed',    value: firsStats.failed,    color: 'text-red-400' },
                  { label: 'Bypassed',  value: firsStats.bypassed,  color: 'text-slate-400' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="bg-surface-700/40 rounded-lg p-3 text-center">
                    <p className={`text-xl font-bold ${color}`}>{value}</p>
                    <p className="text-xs text-slate-500 mt-0.5">{label}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Phase 7: Sandbox Certification — shown only while in sandbox mode */}
          {firsConfig?.use_sandbox && firsConfig?.is_enrolled && (
            <div className="card p-6 space-y-5">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                    <Shield size={14} className="text-amber-400" />
                    Sandbox Certification (FIRS Requirement)
                  </h3>
                  <p className="text-xs text-slate-400 mt-0.5">
                    FIRS requires 50 successful (pass) and 50 failed submissions before granting
                    production access. Run both batches here to complete sandbox certification.
                  </p>
                </div>
                {sandboxProgress?.certification_ready && (
                  <span className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full bg-green-500/20 text-green-300 border border-green-500/30 shrink-0">
                    <CheckCircle size={12} />
                    Certified
                  </span>
                )}
              </div>

              {/* Progress bars */}
              <div className="space-y-3">
                {/* Pass progress */}
                <div>
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-slate-400">Pass Tests</span>
                    <span className={`font-semibold ${sandboxProgress?.passes_complete ? 'text-green-400' : 'text-white'}`}>
                      {sandboxProgress?.pass_count ?? 0} / {sandboxProgress?.required_passes ?? 50}
                      {sandboxProgress?.passes_complete && ' ✓'}
                    </span>
                  </div>
                  <div className="h-2 bg-surface-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-green-500 rounded-full transition-all duration-500"
                      style={{ width: `${Math.min(100, ((sandboxProgress?.pass_count ?? 0) / (sandboxProgress?.required_passes ?? 50)) * 100)}%` }}
                    />
                  </div>
                </div>
                {/* Fail progress */}
                <div>
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-slate-400">Fail Tests</span>
                    <span className={`font-semibold ${sandboxProgress?.fails_complete ? 'text-green-400' : 'text-white'}`}>
                      {sandboxProgress?.fail_count ?? 0} / {sandboxProgress?.required_fails ?? 50}
                      {sandboxProgress?.fails_complete && ' ✓'}
                    </span>
                  </div>
                  <div className="h-2 bg-surface-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-red-500 rounded-full transition-all duration-500"
                      style={{ width: `${Math.min(100, ((sandboxProgress?.fail_count ?? 0) / (sandboxProgress?.required_fails ?? 50)) * 100)}%` }}
                    />
                  </div>
                </div>
              </div>

              {/* Run buttons */}
              <div className="flex items-center gap-3 flex-wrap">
                <button
                  disabled={sandboxRunning !== null || !firsConfig?.has_api_key}
                  onClick={async () => {
                    setSandboxRunning('pass')
                    try {
                      await einvoicingApi.sandboxRun('pass', 50)
                      toast.success('Pass batch queued — submissions running in the background')
                      // Poll for progress update after a short delay
                      setTimeout(() => { refreshSandboxData() }, 3000)
                    } catch {
                      toast.error('Failed to start pass batch')
                    } finally {
                      setSandboxRunning(null)
                    }
                  }}
                  className="btn-secondary flex items-center gap-1.5 text-sm"
                  title={!firsConfig?.has_api_key ? 'Save an API key first' : undefined}
                >
                  {sandboxRunning === 'pass'
                    ? <Loader2 size={13} className="animate-spin" />
                    : <CheckCircle size={13} className="text-green-400" />
                  }
                  Run 50 Pass Tests
                </button>
                <button
                  disabled={sandboxRunning !== null || !firsConfig?.has_api_key}
                  onClick={async () => {
                    setSandboxRunning('fail')
                    try {
                      await einvoicingApi.sandboxRun('fail', 50)
                      toast.success('Fail batch queued — submissions running in the background')
                      setTimeout(() => { refreshSandboxData() }, 3000)
                    } catch {
                      toast.error('Failed to start fail batch')
                    } finally {
                      setSandboxRunning(null)
                    }
                  }}
                  className="btn-secondary flex items-center gap-1.5 text-sm"
                >
                  {sandboxRunning === 'fail'
                    ? <Loader2 size={13} className="animate-spin" />
                    : <XCircle size={13} className="text-red-400" />
                  }
                  Run 50 Fail Tests
                </button>
                <button
                  onClick={refreshSandboxData}
                  className="p-2 rounded hover:bg-surface-700 text-slate-400 hover:text-white"
                  title="Refresh progress"
                >
                  <RefreshCw size={13} />
                </button>
              </div>

              {/* Recent test runs */}
              {sandboxProgress?.recent_runs && sandboxProgress.recent_runs.length > 0 && (
                <div className="pt-2 border-t border-surface-700">
                  <p className="text-xs text-slate-500 mb-2">Recent test runs</p>
                  <div className="space-y-1">
                    {sandboxProgress.recent_runs.map((run) => (
                      <div key={run.id} className="flex items-center justify-between text-xs py-1">
                        <span className="text-slate-400 capitalize">{run.mode} batch</span>
                        <span className={`px-1.5 py-0.5 rounded font-medium ${
                          run.outcome === 'complete' ? 'bg-green-500/20 text-green-300' :
                          run.outcome === 'error'    ? 'bg-red-500/20 text-red-300' :
                          'bg-amber-500/20 text-amber-300'
                        }`}>{run.outcome}</span>
                        <span className="text-slate-500">{run.completed_count}/{run.target_count}</span>
                        <span className="text-slate-600">
                          {run.started_at ? new Date(run.started_at).toLocaleDateString() : '—'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Phase 7: Go-Live Checklist */}
          <div className="card p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                <Shield size={14} />
                Production Go-Live Checklist
              </h3>
              <button
                onClick={refreshSandboxData}
                className="p-1.5 rounded hover:bg-surface-700 text-slate-400 hover:text-white"
                title="Refresh checklist"
              >
                <RefreshCw size={12} />
              </button>
            </div>

            {firsLoading ? (
              <div className="space-y-2">
                {[...Array(4)].map((_, i) => (
                  <div key={i} className="h-8 bg-surface-700 rounded animate-pulse" />
                ))}
              </div>
            ) : goLiveChecklist ? (
              <>
                {goLiveChecklist.production_ready && (
                  <div className="flex items-center gap-2 p-3 bg-green-500/10 border border-green-500/20 rounded-lg text-green-300 text-sm font-medium">
                    <CheckCircle size={16} />
                    All requirements met — ready to switch to production!
                    <span className="text-xs font-normal text-green-400/70 ml-1">
                      (Disable sandbox mode in credentials to go live)
                    </span>
                  </div>
                )}
                <div className="space-y-2">
                  {Object.entries(goLiveChecklist.checks).map(([key, item]) => (
                    <div key={key} className="flex items-start gap-2.5 py-1.5">
                      {item.pass
                        ? <CheckCircle size={14} className="text-green-400 mt-0.5 shrink-0" />
                        : <XCircle    size={14} className="text-red-400 mt-0.5 shrink-0" />
                      }
                      <div>
                        <p className="text-xs font-medium text-white">
                          {key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                        </p>
                        <p className={`text-xs ${item.pass ? 'text-slate-500' : 'text-amber-400'}`}>
                          {item.detail}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="text-slate-500 text-sm">Could not load checklist</p>
            )}
          </div>

          {/* Recent submissions */}
          <div className="card p-6 space-y-4">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <FileText size={14} />
              Recent Submissions
              <button
                onClick={() => {
                  einvoicingApi.submissions({ page_size: 10 }).then(({ data }) => {
                    setFirsSubmissions(Array.isArray(data) ? data : data.results ?? [])
                  }).catch(() => null)
                }}
                className="ml-auto text-slate-500 hover:text-white p-1 rounded"
                title="Refresh"
              >
                <RefreshCw size={12} />
              </button>
            </h3>
            {firsLoading ? (
              <div className="space-y-2">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="h-10 bg-surface-700 rounded animate-pulse" />
                ))}
              </div>
            ) : firsSubmissions.length === 0 ? (
              <p className="text-slate-500 text-sm py-4 text-center">No submissions yet</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-500 border-b border-surface-700">
                      <th className="text-left py-2 font-medium">Invoice</th>
                      <th className="text-left py-2 font-medium">Customer</th>
                      <th className="text-left py-2 font-medium">Type</th>
                      <th className="text-left py-2 font-medium">Status</th>
                      <th className="text-left py-2 font-medium">IRN</th>
                      <th className="text-left py-2 font-medium">Attempts</th>
                      <th className="text-left py-2 font-medium">Date</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-700/40">
                    {firsSubmissions.map((sub) => (
                      <tr key={sub.id} className="hover:bg-surface-700/20">
                        <td className="py-2 font-mono text-brand-400">
                          {sub.invoice_number || '—'}
                          {sub.is_sandbox_test && (
                            <span className="ml-1 text-[9px] font-bold px-1 py-0.5 bg-amber-500/20 text-amber-400 rounded">
                              TEST
                            </span>
                          )}
                        </td>
                        <td className="py-2 text-slate-300">{sub.customer_name || '—'}</td>
                        <td className="py-2 text-slate-400">{sub.transaction_type}</td>
                        <td className="py-2">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                            sub.status === 'cleared'   ? 'bg-green-500/20 text-green-300' :
                            sub.status === 'submitted' ? 'bg-blue-500/20 text-blue-300' :
                            sub.status === 'failed'    ? 'bg-red-500/20 text-red-300' :
                            sub.status === 'bypassed'  ? 'bg-slate-500/20 text-slate-400' :
                            'bg-amber-500/20 text-amber-300'
                          }`}>
                            {sub.status}
                          </span>
                        </td>
                        <td className="py-2 font-mono text-slate-400 max-w-[120px] truncate" title={sub.irn}>
                          {sub.irn || '—'}
                        </td>
                        <td className="py-2 text-slate-500 text-center">{sub.attempt_count}</td>
                        <td className="py-2 text-slate-500">
                          {sub.created_at ? new Date(sub.created_at).toLocaleDateString() : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
  )
}
