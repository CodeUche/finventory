import { useEffect, useMemo, useRef, useState } from 'react'
import { confirmDialog } from '@/lib/dialog'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, X, BookOpen, Edit2, Trash2, Loader2, Download, RefreshCw, ChevronRight, AlertTriangle, ChevronDown, Upload, Layers, Scale, Lock, Search, Users, Truck, Package, HelpCircle } from 'lucide-react'
import toast from 'react-hot-toast'
import { accountingApi, customerApi, supplierApi, inventoryApi, bypassNextGets } from '@/services/api'
import { formatCurrency, formatDate, formatAmountInput, stripCommas } from '@/lib/utils'
import { saveBlobFile } from '@/lib/saveBlobFile'
import DateInput from '@/components/DateInput'
import { useAuthStore } from '@/store/authStore'
import type { Account, AccountLedger, AccountSubType, AccountTaxonomyGroup } from '@/types'

const TYPE_BADGE: Record<string, string> = {
  asset: 'badge-green',
  liability: 'badge-red',
  equity: 'badge-blue',
  revenue: 'badge-orange',
  expense: 'badge-yellow',
  cogs: 'badge-slate',
}

// Display labels for the raw account_type slugs used across the page.
const TYPE_LABEL: Record<string, string> = {
  all: 'All',
  asset: 'Asset',
  liability: 'Liability',
  equity: 'Equity',
  revenue: 'Revenue',
  expense: 'Expense',
  cogs: 'Cogs',
}
const typeLabel = (t: string) => TYPE_LABEL[t] ?? t

interface AccountForm {
  code: string
  name: string
  account_type: string
  account_group: string
  sub_type: string
  parent: string
  description: string
  normal_balance: 'debit' | 'credit'
  is_active: boolean
  allow_posting: boolean
  is_control_account: boolean
  is_sub_account: boolean
  opening_balance: string
  opening_balance_date: string
}

const BLANK: AccountForm = {
  code: '', name: '', account_type: 'asset', account_group: '', sub_type: '', parent: '',
  description: '', normal_balance: 'debit', is_active: true, allow_posting: true,
  is_control_account: false, is_sub_account: false, opening_balance: '', opening_balance_date: '',
}

export default function ChartOfAccountsPage() {
  const { organisation } = useAuthStore()
  const [accounts, setAccounts] = useState<Account[]>([])
  const [summary, setSummary] = useState<{ total: number; by_type: Record<string, number> } | null>(null)
  const [loading, setLoading] = useState(true)
  const [seeding, setSeeding] = useState(false)

  const [showModal, setShowModal] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState<AccountForm>(BLANK)
  const [saving, setSaving] = useState(false)
  const [attachmentFile, setAttachmentFile] = useState<File | null>(null)
  const [origOpening, setOrigOpening] = useState<{ bal: string; date: string }>({ bal: '', date: '' })
  const [showCodes, setShowCodes] = useState(true)

  const [showTrialBalance, setShowTrialBalance] = useState(false)
  const [trialBalance, setTrialBalance] = useState<Record<string, unknown> | null>(null)
  const [loadingTB, setLoadingTB] = useState(false)
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [showExportMenu, setShowExportMenu] = useState(false)
  const exportRef = useRef<HTMLDivElement>(null)

  // Taxonomy (account groups + sub-types) for dependent dropdowns
  const [taxonomy, setTaxonomy] = useState<AccountTaxonomyGroup[]>([])
  // Secondary modals
  const [showImport, setShowImport] = useState(false)
  const [showSubTypes, setShowSubTypes] = useState(false)
  const [showOpening, setShowOpening] = useState(false)

  // Ledger drill-down
  const [ledgerAccount, setLedgerAccount] = useState<Account | null>(null)
  const [ledger, setLedger] = useState<AccountLedger | null>(null)
  const [ledgerLoading, setLedgerLoading] = useState(false)
  const [ledgerFrom, setLedgerFrom] = useState('')
  const [ledgerTo, setLedgerTo] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const [list, counts] = await Promise.all([
        accountingApi.accounts(),
        accountingApi.accountsSummary().catch(() => null),
      ])
      setAccounts(list.data.results ?? list.data)
      setSummary(counts?.data ?? null)
    } catch { toast.error('Failed to load accounts') }
    finally { setLoading(false) }
  }

  const loadTaxonomy = async () => {
    try {
      const { data } = await accountingApi.accountTaxonomy()
      setTaxonomy(data.groups ?? [])
    } catch { /* non-fatal */ }
  }

  useEffect(() => { load(); loadTaxonomy() }, [])
  useDataRefresh(load)

  // Sub-types available for the currently-selected group in the account form
  const groupSpec = useMemo(
    () => taxonomy.find((g) => g.group === form.account_group),
    [taxonomy, form.account_group],
  )

  const handleSeed = async () => {
    if (!(await confirmDialog('Seed default Chart of Accounts? This will add standard Nigerian accounting accounts.'))) return
    setSeeding(true)
    try {
      await accountingApi.seedCoa()
      toast.success('Chart of Accounts seeded successfully')
      load()
    } catch { toast.error('Failed to seed COA') }
    finally { setSeeding(false) }
  }

  const editingAccount = editId ? accounts.find((a) => a.id === editId) ?? null : null

  const openCreate = () => {
    setEditId(null); setForm(BLANK); setAttachmentFile(null)
    setOrigOpening({ bal: '', date: '' }); setShowModal(true)
  }
  const openEdit = (a: Account) => {
    setEditId(a.id)
    setAttachmentFile(null)
    const bal = a.opening_balance ? String(a.opening_balance) : ''
    const date = a.opening_balance_date ?? ''
    setOrigOpening({ bal, date })
    setForm({
      code: a.code, name: a.name, account_type: a.account_type,
      account_group: a.account_group ?? '', sub_type: a.sub_type ?? '',
      parent: a.parent ?? '', description: a.description,
      normal_balance: (a.normal_balance || (['asset', 'expense', 'cogs'].includes(a.account_type) ? 'debit' : 'credit')) as 'debit' | 'credit',
      is_active: a.is_active, allow_posting: a.allow_posting ?? true,
      is_control_account: a.is_control_account ?? false,
      is_sub_account: !!a.parent,
      opening_balance: bal,
      opening_balance_date: date,
    })
    setShowModal(true)
  }

  const toISOd = (dd: string) => {
    if (!dd) return ''
    const [d, m, y] = dd.split('/'); return d && m && y ? `${y}-${m}-${d}` : dd
  }

  // When the user picks a group header, sync the base account_type + normal side
  // and clear a now-invalid sub-type.
  const onGroupChange = (group: string) => {
    const spec = taxonomy.find((g) => g.group === group)
    setForm((f) => ({
      ...f,
      account_group: group,
      account_type: spec?.base_account_type ?? f.account_type,
      normal_balance: spec ? (['asset', 'expense', 'cogs'].includes(spec.base_account_type) ? 'debit' : 'credit') : f.normal_balance,
      sub_type: '',
    }))
  }

  const handleSave = async () => {
    if (!form.code.trim()) { toast.error('Account code is required'); return }
    if (!form.name.trim()) { toast.error('Account name is required'); return }
    setSaving(true)
    try {
      const fields: Record<string, unknown> = {
        code: form.code, name: form.name, account_type: form.account_type,
        account_group: form.account_group, description: form.description,
        normal_balance: form.normal_balance, is_active: form.is_active,
        allow_posting: form.allow_posting, is_control_account: form.is_control_account,
        parent: form.is_sub_account ? (form.parent || null) : null,
        sub_type: form.sub_type || null,
        opening_balance: form.opening_balance ? stripCommas(form.opening_balance) : null,
        opening_balance_date: form.opening_balance_date || null,
      }

      // When a file is attached we must send multipart/form-data.
      let body: unknown = fields
      if (attachmentFile) {
        const fd = new FormData()
        Object.entries(fields).forEach(([k, v]) => { if (v !== null && v !== undefined) fd.append(k, String(v)) })
        fd.append('attachment', attachmentFile)
        body = fd
      }

      let accountId = editId
      if (editId) {
        await accountingApi.updateAccount(editId, body as object)
        toast.success('Account updated')
      } else {
        const { data } = await accountingApi.createAccount(body as object)
        accountId = data.id
        toast.success('Account created')
      }

      // Post the opening balance to the ledger (Option 1) when it was set/changed
      // and an as-of date is present — reverses only this account's prior take-on.
      const openChanged = form.opening_balance !== origOpening.bal || form.opening_balance_date !== origOpening.date
      const openAmt = form.opening_balance ? stripCommas(form.opening_balance) : ''
      if (accountId && openChanged && openAmt && parseFloat(openAmt) > 0 && form.opening_balance_date) {
        await accountingApi.setAccountOpeningBalance(accountId, {
          amount: openAmt, side: form.normal_balance, as_of_date: toISOd(form.opening_balance_date),
        })
        toast.success('Opening balance posted to the ledger')
      }

      setShowModal(false)
      load()
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : ((apiErr as { message?: string })?.message ?? 'Failed to save account')
      toast.error(msg)
    }
    finally { setSaving(false) }
  }

  const handleDelete = async (a: Account) => {
    if (a.is_system) { toast.error('Cannot delete system accounts'); return }
    if (!(await confirmDialog(`Delete account "${a.name}"?`))) return
    try { await accountingApi.deleteAccount(a.id); toast.success('Account deleted'); load() }
    catch { toast.error('Cannot delete — account may have transactions') }
  }

  const handleTrialBalance = async () => {
    setLoadingTB(true)
    try {
      const { data } = await accountingApi.trialBalance()
      setTrialBalance(data)
      setShowTrialBalance(true)
    } catch { toast.error('Failed to load trial balance') }
    finally { setLoadingTB(false) }
  }

  const toISO = (dd: string) => {
    if (!dd) return undefined
    const [d, m, y] = dd.split('/')
    if (!d || !m || !y) return dd
    return `${y}-${m}-${d}`
  }

  const openLedger = async (account: Account) => {
    setLedgerAccount(account)
    setLedger(null)
    setLedgerLoading(true)
    try {
      const params: Record<string, string> = {}
      const f = toISO(ledgerFrom); const t = toISO(ledgerTo)
      if (f) params.date_from = f
      if (t) params.date_to = t
      const { data } = await accountingApi.accountLedger(account.id, params)
      setLedger(data as AccountLedger)
    } catch { toast.error('Failed to load ledger') }
    finally { setLedgerLoading(false) }
  }

  const refreshLedger = async () => {
    if (!ledgerAccount) return
    setLedgerLoading(true)
    try {
      const params: Record<string, string> = {}
      const f = toISO(ledgerFrom); const t = toISO(ledgerTo)
      if (f) params.date_from = f
      if (t) params.date_to = t
      const { data } = await accountingApi.accountLedger(ledgerAccount.id, params)
      setLedger(data as AccountLedger)
    } catch { toast.error('Failed to load ledger') }
    finally { setLedgerLoading(false) }
  }

  const TYPES = ['asset', 'liability', 'equity', 'revenue', 'expense', 'cogs'] as const
  // Prefer the server's counts; fall back to counting the loaded rows if the
  // summary call failed so the chips still show something sensible.
  const typeCounts = TYPES.reduce(
    (acc, t) => ({ ...acc, [t]: summary?.by_type?.[t] ?? accounts.filter((a) => a.account_type === t).length }),
    {} as Record<string, number>,
  )
  const totalCount = summary?.total ?? accounts.length
  const baseFiltered = typeFilter === 'all' ? accounts : accounts.filter((a) => a.account_type === typeFilter)

  // Order as a Master → Sub tree: each parent immediately followed by its
  // children, with a depth for indentation. Rolls up child balances to parents.
  const filteredAccounts = useMemo(() => {
    const byId = new Map(baseFiltered.map((a) => [a.id, a]))
    const childrenOf = (pid: string | null) =>
      baseFiltered.filter((a) => (a.parent ?? null) === pid).sort((x, y) => x.code.localeCompare(y.code))
    const ordered: (Account & { _depth: number; _rollup: number })[] = []
    const rollup = (a: Account): number => {
      const kids = childrenOf(a.id)
      const own = parseFloat(String(a.balance)) || 0
      return own + kids.reduce((s, k) => s + rollup(k), 0)
    }
    const walk = (a: Account, depth: number) => {
      ordered.push({ ...a, _depth: depth, _rollup: rollup(a) })
      childrenOf(a.id).forEach((k) => walk(k, depth + 1))
    }
    // Roots = accounts with no parent, or whose parent is filtered out.
    baseFiltered
      .filter((a) => !a.parent || !byId.has(a.parent))
      .sort((x, y) => x.code.localeCompare(y.code))
      .forEach((a) => walk(a, 0))
    return ordered
  }, [baseFiltered])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Chart of Accounts</h1>
          <p className="text-slate-400 text-sm">
            {typeFilter === 'all' ? `${totalCount} accounts` : `${filteredAccounts.length} ${typeLabel(typeFilter)} accounts`}
          </p>
        </div>
        <div className="sm:ml-auto flex gap-2 flex-wrap">
          <button onClick={() => { bypassNextGets(); load() }} disabled={loading} className="btn-ghost p-2 text-slate-400 hover:text-white" title="Refresh">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <button onClick={handleTrialBalance} disabled={loadingTB} className="btn-ghost flex items-center gap-2 text-sm">
            {loadingTB ? <Loader2 size={14} className="animate-spin" /> : null}
            Trial Balance
          </button>
          <button onClick={() => setShowCodes((v) => !v)} className="btn-ghost flex items-center gap-2 text-sm" title="Show or hide GL codes">
            {showCodes ? 'Hide Codes' : 'Show Codes'}
          </button>
          <button onClick={() => setShowOpening(true)} className="btn-ghost flex items-center gap-2 text-sm" title="Enter opening / take-on balances">
            <Scale size={14} /> Opening Balances
          </button>
          <button onClick={() => setShowSubTypes(true)} className="btn-ghost flex items-center gap-2 text-sm" title="Manage account sub-types">
            <Layers size={14} /> Sub Types
          </button>
          <button onClick={() => setShowImport(true)} className="btn-ghost flex items-center gap-2 text-sm" title="Import chart of accounts">
            <Upload size={14} /> Import
          </button>
          {accounts.length === 0 && (
            <button onClick={handleSeed} disabled={seeding} className="btn-ghost flex items-center gap-2 text-sm">
              {seeding ? <Loader2 size={14} className="animate-spin" /> : <BookOpen size={14} />}
              Seed Default COA
            </button>
          )}
          <button onClick={openCreate} className="btn-primary flex items-center gap-2">
            <Plus size={16} /> Add Account
          </button>
        </div>
      </div>

      {/* Type summary cards — click to filter */}
      <div className="grid grid-cols-3 lg:grid-cols-7 gap-3">
        <button
          onClick={() => setTypeFilter('all')}
          className={`card p-3 text-center transition-colors ${typeFilter === 'all' ? 'ring-2 ring-brand-500/60' : 'hover:bg-surface-700/50'}`}
        >
          <span className="badge-slate">{typeLabel('all')}</span>
          <p className="text-lg font-bold text-white mt-1">{totalCount}</p>
        </button>
        {TYPES.map((t) => (
          <button
            key={t}
            onClick={() => setTypeFilter(typeFilter === t ? 'all' : t)}
            className={`card p-3 text-center transition-colors ${typeFilter === t ? 'ring-2 ring-brand-500/60' : 'hover:bg-surface-700/50'}`}
          >
            <span className={TYPE_BADGE[t]}>{typeLabel(t)}</span>
            <p className="text-lg font-bold text-white mt-1">{typeCounts[t] ?? 0}</p>
          </button>
        ))}
      </div>
      {typeFilter !== 'all' && (
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <span>Showing <strong className="text-white">{filteredAccounts.length}</strong> {typeLabel(typeFilter)} accounts</span>
          <button onClick={() => setTypeFilter('all')} className="text-brand-400 hover:underline text-xs">Clear filter</button>
        </div>
      )}

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {[...(showCodes ? ['Code'] : []), 'Account Name', 'Type', 'Balance', 'Attach', 'System', 'Actions', ''].map((h, i) => (
                  <th key={`${h}-${i}`} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 6 }).map((_, j) => (
                      <td key={j} className="px-5 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-20" /></td>
                    ))}
                  </tr>
                ))
              ) : accounts.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-5 py-12 text-center">
                    <BookOpen size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500 mb-3">No accounts yet</p>
                    <button onClick={handleSeed} disabled={seeding} className="btn-primary text-sm">
                      {seeding ? 'Seeding…' : 'Seed Default Chart of Accounts'}
                    </button>
                  </td>
                </tr>
              ) : filteredAccounts.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-5 py-12 text-center text-slate-500">
                    No {typeLabel(typeFilter)} accounts yet.
                  </td>
                </tr>
              ) : filteredAccounts.map((a) => (
                <tr
                  key={a.id}
                  className={`table-row cursor-pointer ${a.is_active === false ? 'opacity-50' : ''}`}
                  onClick={() => openLedger(a)}
                >
                  {showCodes && (
                    <td className="px-5 py-3.5 font-mono text-slate-400" style={{ paddingLeft: 20 + a._depth * 22 }}>
                      {a._depth > 0 && <span className="text-slate-600 mr-1">└</span>}{a.code}
                    </td>
                  )}
                  <td className="px-5 py-3.5 text-white font-medium" style={!showCodes ? { paddingLeft: 20 + a._depth * 22 } : undefined}>
                    <span className="flex items-center gap-1.5">
                      {!showCodes && a._depth > 0 && <span className="text-slate-600">└</span>}
                      {a.name}
                      {a.is_control_account && <span title="Control account — no direct journals"><Lock size={12} className="text-amber-400" /></span>}
                      {a.sub_type_name && <span className="text-[10px] text-slate-500 border border-surface-600 rounded px-1">{a.sub_type_name}</span>}
                    </span>
                  </td>
                  <td className="px-5 py-3.5"><span className={TYPE_BADGE[a.account_type]}>{a.account_group || typeLabel(a.account_type)}</span></td>
                  <td className="px-5 py-3.5 text-right font-mono text-white">
                    {formatCurrency(a.balance)}
                    {Math.abs(a._rollup - (parseFloat(String(a.balance)) || 0)) > 0.01 && (
                      <span className="block text-[10px] text-slate-500">incl. subs {formatCurrency(a._rollup)}</span>
                    )}
                  </td>
                  <td className="px-5 py-3.5 text-center" onClick={(e) => e.stopPropagation()}>
                    {a.attachment
                      ? <a href={a.attachment} target="_blank" rel="noreferrer" title="View attachment" className="text-brand-400 hover:text-brand-300 inline-flex"><Upload size={14} /></a>
                      : <span className="text-slate-700">—</span>}
                  </td>
                  <td className="px-5 py-3.5">{a.is_system ? <span className="badge-blue">System</span> : <span className="text-slate-600">—</span>}</td>
                  <td className="px-5 py-3.5" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center gap-2">
                      <button onClick={() => openEdit(a)} className="p-1.5 text-slate-500 hover:text-white hover:bg-surface-600 rounded-lg transition-colors"><Edit2 size={14} /></button>
                      <button
                        onClick={() => handleDelete(a)}
                        disabled={a.is_system}
                        title={a.is_system ? 'System accounts cannot be deleted' : 'Delete account'}
                        className={`p-1.5 rounded-lg transition-colors ${a.is_system ? 'text-slate-700 cursor-not-allowed' : 'text-slate-500 hover:text-red-400 hover:bg-red-500/10'}`}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                  <td className="px-3 py-3.5 text-slate-600">
                    <ChevronRight size={14} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Account Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative card w-full max-w-md p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">{editId ? 'Edit Account' : 'Add Account'}</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <div className="grid grid-cols-2 gap-4 max-h-[65vh] overflow-y-auto pr-1">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Code *</label>
                <input className="input" placeholder="e.g. 1001" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Account Type *</label>
                {taxonomy.length > 0 ? (
                  <select className="input" value={form.account_group} onChange={(e) => onGroupChange(e.target.value)}>
                    <option value="">Select type…</option>
                    <optgroup label="Profit & Loss">
                      {taxonomy.filter((g) => g.statement === 'pl').map((g) => <option key={g.group} value={g.group}>{g.group}</option>)}
                    </optgroup>
                    <optgroup label="Balance Sheet">
                      {taxonomy.filter((g) => g.statement === 'bs').map((g) => <option key={g.group} value={g.group}>{g.group}</option>)}
                    </optgroup>
                  </select>
                ) : (
                  <select className="input" value={form.account_type} onChange={(e) => setForm({ ...form, account_type: e.target.value })}>
                    {TYPES.map((t) => <option key={t} value={t}>{typeLabel(t)}</option>)}
                  </select>
                )}
              </div>

              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Account Name *</label>
                <input className="input" placeholder="e.g. Cash and Cash Equivalents" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>

              {/* Account Sub Type — only sub-types linked to the selected group appear */}
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Account Sub Type</label>
                <select
                  className="input"
                  value={form.sub_type}
                  disabled={!groupSpec}
                  onChange={(e) => setForm({ ...form, sub_type: e.target.value })}
                >
                  <option value="">{groupSpec ? 'Select sub type…' : 'Select an account type first'}</option>
                  {groupSpec?.sub_types.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </div>

              {/* Normal balance switcher — before the amount, as requested */}
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Normal Balance</label>
                <div className="flex gap-2">
                  {(['debit', 'credit'] as const).map((side) => (
                    <button
                      key={side} type="button"
                      onClick={() => setForm({ ...form, normal_balance: side })}
                      className={`flex-1 py-2 rounded-lg text-sm border transition-colors ${form.normal_balance === side ? 'border-brand-500 bg-brand-500/10 text-white' : 'border-surface-600 text-slate-400 hover:text-white'}`}
                    >
                      {side === 'debit' ? 'Debit' : 'Credit'}
                    </button>
                  ))}
                </div>
              </div>

              {/* Current ledger balance — read-only (Option 1, p5) */}
              {editingAccount && (
                <div className="col-span-2">
                  <label className="text-xs text-slate-400 mb-1 block">Current Ledger Balance</label>
                  <input className="input opacity-70 cursor-not-allowed" readOnly disabled
                    value={formatCurrency(editingAccount.balance)} />
                </div>
              )}

              {/* Opening balance + date */}
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Opening Balance</label>
                <input
                  className="input" inputMode="decimal" placeholder="0.00"
                  value={form.opening_balance}
                  onChange={(e) => setForm({ ...form, opening_balance: formatAmountInput(e.target.value) })}
                />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">As of Date</label>
                <DateInput value={form.opening_balance_date} onChange={(v) => setForm({ ...form, opening_balance_date: v })} />
              </div>
              {!!form.opening_balance && stripCommas(form.opening_balance) !== '0' && (
                <p className="col-span-2 text-[11px] text-slate-500 -mt-2">
                  {form.opening_balance_date
                    ? <>Will be posted to the ledger as a {form.normal_balance} opening balance (offset to Take-On Suspense).</>
                    : <>Set an <strong>As of Date</strong> to post this opening balance to the ledger.</>}
                </p>
              )}

              {/* Attachment (p4 ATTACH column) */}
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Attachment</label>
                <label className="input flex items-center gap-2 cursor-pointer text-slate-400 hover:text-white">
                  <Upload size={14} />
                  <span className="truncate">{attachmentFile ? attachmentFile.name : (editingAccount?.attachment ? 'Replace attached document…' : 'Attach a document (optional)')}</span>
                  <input type="file" className="hidden" onChange={(e) => setAttachmentFile(e.target.files?.[0] ?? null)} />
                </label>
              </div>

              {/* Sub-account-of toggle + parent */}
              <div className="col-span-2 flex items-center gap-2">
                <input id="isSub" type="checkbox" checked={form.is_sub_account} onChange={(e) => setForm({ ...form, is_sub_account: e.target.checked })} />
                <label htmlFor="isSub" className="text-sm text-slate-300">Create as sub-account of another account</label>
              </div>
              {form.is_sub_account && (
                <div className="col-span-2">
                  <label className="text-xs text-slate-400 mb-1 block">Parent Account</label>
                  <select className="input" value={form.parent} onChange={(e) => setForm({ ...form, parent: e.target.value })}>
                    <option value="">Select parent…</option>
                    {accounts.filter((a) => a.id !== editId).map((a) => (
                      <option key={a.id} value={a.id}>{a.code} — {a.name}</option>
                    ))}
                  </select>
                </div>
              )}

              {/* Toggles: Active + Allow Journals (control-account lock) */}
              <div className="col-span-2 flex items-center justify-between rounded-lg border border-surface-700 px-3 py-2">
                <span className="text-sm text-slate-300">Active Account</span>
                <button type="button" onClick={() => setForm({ ...form, is_active: !form.is_active })}
                  className={`w-11 h-6 rounded-full transition-colors relative ${form.is_active ? 'bg-brand-500' : 'bg-surface-600'}`}>
                  <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-all ${form.is_active ? 'left-[22px]' : 'left-0.5'}`} />
                </button>
              </div>
              <div className="col-span-2 flex items-center justify-between rounded-lg border border-surface-700 px-3 py-2">
                <div className="pr-3">
                  <span className="text-sm text-slate-300 flex items-center gap-1.5">
                    Allow Journal Entries {!form.allow_posting && <Lock size={12} className="text-amber-400" />}
                    <span
                      className="text-slate-500 hover:text-slate-300 cursor-help"
                      title={
                        'ON  — anyone can post manual journal entries to this account.\n' +
                        'OFF — this account is a control account. It can only be updated from its ' +
                        'sub-ledger (invoices for AR, bills for AP, stock movements for Inventory), ' +
                        'never by a direct manual journal. This keeps the account total matching the ' +
                        'customer/supplier/stock detail. Automatic posting from sales, bills and ' +
                        'stock is unaffected either way.'
                      }
                    >
                      <HelpCircle size={13} />
                    </span>
                  </span>
                  <span className="text-[11px] text-slate-500">
                    {form.allow_posting
                      ? 'On: manual journals to this account are allowed.'
                      : 'Off (control account): updates only via its sub-ledger — no direct journals.'}
                  </span>
                </div>
                <button type="button" onClick={() => setForm({ ...form, allow_posting: !form.allow_posting })}
                  className={`w-11 h-6 rounded-full transition-colors relative shrink-0 ${form.allow_posting ? 'bg-brand-500' : 'bg-surface-600'}`}>
                  <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-all ${form.allow_posting ? 'left-[22px]' : 'left-0.5'}`} />
                </button>
              </div>

              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Description</label>
                <textarea className="input resize-none" rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </div>
            </div>
            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleSave} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : editId ? 'Save Changes' : 'Add Account'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Ledger Drill-Down Panel */}
      {ledgerAccount && (
        <div className="fixed inset-0 z-50 flex">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setLedgerAccount(null)} />
          <div className="relative ml-auto w-full max-w-3xl bg-surface-900 border-l border-surface-700 flex flex-col h-full shadow-2xl">
            {/* Header */}
            <div className="flex items-start justify-between p-5 border-b border-surface-700">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-slate-400 text-sm">{ledgerAccount.code}</span>
                  <span className={`${TYPE_BADGE[ledgerAccount.account_type]} text-xs`}>{ledgerAccount.account_type}</span>
                </div>
                <h2 className="text-lg font-bold text-white mt-0.5">{ledgerAccount.name}</h2>
                {ledger && (
                  <div className="flex gap-4 mt-1.5">
                    <div>
                      <span className="text-xs text-slate-500">GL Balance </span>
                      <span className="font-semibold text-white text-sm">{formatCurrency(ledger.closing_balance)}</span>
                    </div>
                    {ledger.inventory_value != null && (
                      <div className="flex items-center gap-1">
                        <span className="text-xs text-slate-500">Actual Inventory </span>
                        <span className="font-semibold text-emerald-400 text-sm">{formatCurrency(ledger.inventory_value)}</span>
                        {Math.abs(parseFloat(ledger.closing_balance) - parseFloat(ledger.inventory_value)) > 0.01 && (
                          <span title="GL balance differs from actual inventory value"><AlertTriangle size={12} className="text-amber-400 ml-1" /></span>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
              <button onClick={() => setLedgerAccount(null)} className="text-slate-400 hover:text-white mt-1"><X size={20} /></button>
            </div>

            {/* Date range filter */}
            <div className="flex items-end gap-3 px-5 py-3 border-b border-surface-700 bg-surface-800/50">
              <div>
                <label className="text-xs text-slate-500 block mb-1">From</label>
                <DateInput value={ledgerFrom} onChange={setLedgerFrom} placeholder="DD/MM/YYYY" className="w-32 text-sm" />
              </div>
              <div>
                <label className="text-xs text-slate-500 block mb-1">To</label>
                <DateInput value={ledgerTo} onChange={setLedgerTo} placeholder="DD/MM/YYYY" className="w-32 text-sm" />
              </div>
              <button
                onClick={refreshLedger}
                disabled={ledgerLoading}
                className="btn-primary py-1.5 px-4 text-sm flex items-center gap-2"
              >
                {ledgerLoading ? <Loader2 size={14} className="animate-spin" /> : null}
                Apply
              </button>
            </div>

            {/* Lines */}
            <div className="flex-1 overflow-y-auto">
              {ledgerLoading ? (
                <div className="flex items-center justify-center py-16">
                  <Loader2 size={24} className="animate-spin text-slate-500" />
                </div>
              ) : !ledger ? null : (
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-surface-800 z-10">
                    <tr className="border-b border-surface-700">
                      <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase">Date</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase">Ref</th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase">Description</th>
                      <th className="px-4 py-3 text-right text-xs font-semibold text-emerald-400 uppercase">Debit</th>
                      <th className="px-4 py-3 text-right text-xs font-semibold text-red-400 uppercase">Credit</th>
                      <th className="px-4 py-3 text-right text-xs font-semibold text-slate-400 uppercase">Balance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {/* Opening balance row */}
                    {parseFloat(ledger.opening_balance) !== 0 && (
                      <tr className="border-b border-surface-700/50 bg-surface-800/30">
                        <td className="px-4 py-2.5 text-xs text-slate-500 italic" colSpan={5}>Opening Balance</td>
                        <td className="px-4 py-2.5 text-right font-semibold text-slate-300 tabular-nums">
                          {formatCurrency(ledger.opening_balance)}
                        </td>
                      </tr>
                    )}
                    {ledger.lines.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="px-4 py-10 text-center text-slate-500 text-sm">
                          No posted journal entries for this account{ledgerFrom || ledgerTo ? ' in the selected period' : ''}.
                        </td>
                      </tr>
                    ) : (
                      ledger.lines.map((line, i) => (
                        <tr key={line.id} className={`border-b border-surface-700/40 transition-colors hover:bg-surface-700/30 ${i % 2 === 1 ? 'bg-surface-900/30' : ''}`}>
                          <td className="px-4 py-2.5 text-xs text-slate-400 whitespace-nowrap">{formatDate(line.date)}</td>
                          <td className="px-4 py-2.5 text-xs font-mono text-brand-400 whitespace-nowrap">{line.reference}</td>
                          <td className="px-4 py-2.5 text-xs text-slate-300 max-w-xs truncate" title={line.description}>{line.description || '—'}</td>
                          <td className="px-4 py-2.5 text-right tabular-nums text-emerald-400 text-xs">
                            {parseFloat(line.debit) > 0 ? formatCurrency(line.debit) : ''}
                          </td>
                          <td className="px-4 py-2.5 text-right tabular-nums text-red-400 text-xs">
                            {parseFloat(line.credit) > 0 ? formatCurrency(line.credit) : ''}
                          </td>
                          <td className="px-4 py-2.5 text-right tabular-nums font-medium text-white text-xs whitespace-nowrap">
                            {formatCurrency(line.balance)}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                  {ledger.lines.length > 0 && (
                    <tfoot>
                      <tr className="border-t-2 border-surface-600 bg-surface-800">
                        <td colSpan={5} className="px-4 py-3 text-sm font-semibold text-slate-300 text-right">Closing Balance</td>
                        <td className="px-4 py-3 text-right font-bold text-white tabular-nums">{formatCurrency(ledger.closing_balance)}</td>
                      </tr>
                    </tfoot>
                  )}
                </table>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Trial Balance Modal */}
      {showTrialBalance && trialBalance && (() => {
        // Backend returns: [{code, name, type, balance}] — plain array
        const rawRows = Array.isArray(trialBalance)
          ? (trialBalance as { code: string; name: string; type: string; balance: number }[])
          : []
        // Split balance into debit/credit by normal balance convention
        const DEBIT_TYPES = ['asset', 'expense', 'cogs']
        const rows = rawRows.map((r) => {
          const bal = parseFloat(String(r.balance)) || 0
          const isDebitNormal = DEBIT_TYPES.includes(r.type)
          const debit = isDebitNormal ? Math.max(0, bal) : Math.max(0, -bal)
          const credit = isDebitNormal ? Math.max(0, -bal) : Math.max(0, bal)
          return { ...r, debit, credit }
        })
        const totalDebit = rows.reduce((s, r) => s + r.debit, 0)
        const totalCredit = rows.reduce((s, r) => s + r.credit, 0)
        const balanced = Math.abs(totalDebit - totalCredit) < 0.01
        const dateStr = new Date().toISOString().split('T')[0]

        const exportCSV = async () => {
          const header = 'Code,Account,Type,Debit,Credit\n'
          const body = rows.map((r) => `${r.code},"${r.name}",${r.type},${r.debit.toFixed(2)},${r.credit.toFixed(2)}`).join('\n')
          const totals = `\n,TOTAL,,${totalDebit.toFixed(2)},${totalCredit.toFixed(2)}`
          const blob = new Blob([header + body + totals], { type: 'text/csv' })
          await saveBlobFile(blob, `trial-balance-${dateStr}.csv`)
        }

        const exportExcel = async () => {
          const { utils, write } = await import('xlsx')
          const wsData = [
            ['Code', 'Account', 'Type', 'Debit', 'Credit'],
            ...rows.map((r) => [r.code, r.name, r.type, r.debit, r.credit]),
            ['', 'TOTAL', '', totalDebit, totalCredit],
          ]
          const ws = utils.aoa_to_sheet(wsData)
          ws['!cols'] = [{ wch: 8 }, { wch: 36 }, { wch: 12 }, { wch: 16 }, { wch: 16 }]
          const wb = utils.book_new()
          utils.book_append_sheet(wb, ws, 'Trial Balance')
          const buf = write(wb, { type: 'array', bookType: 'xlsx' })
          await saveBlobFile(new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }), `trial-balance-${dateStr}.xlsx`)
        }

        const exportPDF = async () => {
          const { default: jsPDF } = await import('jspdf')
          const { default: autoTable } = await import('jspdf-autotable')
          const { applyDocHeader, buildTableStyle, addDocFooter, COLORS, resolveOrgLogo } = await import('@/lib/pdfUtils')

          const toRgb = (hex?: string): [number,number,number] => {
            const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
            if (!m) return [249, 115, 22]; return [parseInt(m[1],16), parseInt(m[2],16), parseInt(m[3],16)]
          }
          const BRAND = toRgb(organisation?.brand_color)
          const DARK = COLORS.DARK; const MUTED = COLORS.MUTED
          const tmpl = organisation?.invoice_template ?? 'classic'
          const pdfFont = organisation?.company_name_font?.toLowerCase().includes('times') ? 'times'
            : organisation?.company_name_font?.toLowerCase().includes('courier') ? 'courier' : 'helvetica'
          const isBold   = organisation?.company_name_font_bold !== false
          const isItalic = organisation?.company_name_font_italic === true
          const pdfStyle = isBold && isItalic ? 'bolditalic' : isBold ? 'bold' : isItalic ? 'italic' : 'normal'
          const fontSize = Math.max(8, Math.min(36, organisation?.company_name_font_size ?? 12))
          const nameColor: [number,number,number] = (() => {
            const c = organisation?.company_name_font_color
            if (!c || c === '#ffffff') return (tmpl === 'modern' || tmpl === 'minimal') ? DARK : COLORS.WHITE
            return toRgb(c)
          })()
          const displayName = organisation?.show_company_name_on_pdf === false
            ? '' : (organisation?.invoice_company_name?.trim() || organisation?.name || 'Audity')

          const logoData: string | null = await resolveOrgLogo(organisation?.logo)

          const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })
          doc.setLineHeightFactor(1.15)
          const pageW = doc.internal.pageSize.getWidth()

          const y = applyDocHeader(doc, {
            tmpl, pageW, BRAND, DARK, MUTED, logoData,
            displayName,
            orgAddress: organisation?.address,
            orgEmail:   organisation?.email,
            orgPhone:   organisation?.phone,
            pdfFont, fontSize, pdfStyle, nameColor,
            showCompanyName: organisation?.show_company_name_on_pdf !== false,
            companyFontUnderline: organisation?.company_name_font_underline,
            docTitle: 'TRIAL BALANCE',
            metaRows: [
              ['Generated', dateStr],
              ['Status', balanced ? 'Balanced ✓' : 'Not Balanced ⚠'],
            ],
          })

          const ts = buildTableStyle(BRAND, pdfFont)
          autoTable(doc, {
            ...ts,
            startY: y,
            head: [['Code', 'Account', 'Type', 'Debit', 'Credit']],
            body: rows.map((r) => [
              r.code, r.name, r.type,
              r.debit > 0 ? r.debit.toFixed(2) : '—',
              r.credit > 0 ? r.credit.toFixed(2) : '—',
            ]),
            foot: [['', 'TOTAL', '', totalDebit.toFixed(2), totalCredit.toFixed(2)]],
            ...ts,
            footStyles: { ...ts.headStyles, fontSize: 8 },
            columnStyles: {
              0: { cellWidth: 18, fontStyle: 'bold' as const },
              3: { halign: 'right' as const, cellWidth: 32 },
              4: { halign: 'right' as const, cellWidth: 32 },
            },
          })

          addDocFooter(doc, { orgName: displayName, docTitle: 'TRIAL BALANCE', BRAND, pdfFont })
          await saveBlobFile(doc.output('blob'), `trial-balance-${dateStr}.pdf`)
        }

        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => { setShowTrialBalance(false); setShowExportMenu(false) }} />
            <div className="relative card w-full max-w-2xl p-6 space-y-4 overflow-y-auto max-h-[85vh]">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-white">Trial Balance</h2>
                <div className="flex items-center gap-2">
                  {rows.length > 0 && (
                    <div className="relative" ref={exportRef}>
                      <button
                        onClick={() => setShowExportMenu((v) => !v)}
                        className="flex items-center gap-1.5 text-xs btn-ghost px-3 py-1.5"
                      >
                        <Download size={13} /> Export <ChevronDown size={11} />
                      </button>
                      {showExportMenu && (
                        <div className="absolute right-0 top-full mt-1 bg-surface-800 border border-surface-600 rounded-xl shadow-xl z-10 py-1 w-36">
                          {[
                            { label: 'CSV', fn: exportCSV },
                            { label: 'Excel (.xlsx)', fn: exportExcel },
                            { label: 'PDF', fn: exportPDF },
                          ].map(({ label, fn }) => (
                            <button
                              key={label}
                              onClick={() => { setShowExportMenu(false); fn() }}
                              className="w-full text-left px-4 py-2 text-sm text-slate-300 hover:bg-surface-700 hover:text-white transition-colors"
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  <button onClick={() => { setShowTrialBalance(false); setShowExportMenu(false) }} className="text-slate-400 hover:text-white"><X size={20} /></button>
                </div>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700">
                    <th className="py-2.5 text-left text-xs font-semibold text-slate-400 uppercase w-16">Code</th>
                    <th className="py-2.5 text-left text-xs font-semibold text-slate-400 uppercase">Account</th>
                    <th className="py-2.5 text-right text-xs font-semibold text-slate-400 uppercase">Debit</th>
                    <th className="py-2.5 text-right text-xs font-semibold text-slate-400 uppercase">Credit</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-700">
                  {rows.length > 0 ? rows.map((row, i) => (
                    <tr key={i} className="table-row">
                      <td className="py-2.5 font-mono text-xs text-slate-500">{row.code}</td>
                      <td className="py-2.5 text-slate-300">{row.name}</td>
                      <td className="py-2.5 text-right font-mono text-white">{row.debit > 0 ? formatCurrency(row.debit) : '—'}</td>
                      <td className="py-2.5 text-right font-mono text-white">{row.credit > 0 ? formatCurrency(row.credit) : '—'}</td>
                    </tr>
                  )) : (
                    <tr><td colSpan={4} className="py-4 text-slate-500 text-center">No posted journal entries yet</td></tr>
                  )}
                </tbody>
                {rows.length > 0 && (
                  <tfoot>
                    <tr className="border-t-2 border-surface-600 bg-surface-800/40">
                      <td colSpan={2} className="py-3 px-1 text-xs font-bold text-slate-300 uppercase tracking-wider">
                        TOTAL
                        {balanced
                          ? <span className="ml-2 text-green-400 font-semibold normal-case tracking-normal">✓ Balanced</span>
                          : <span className="ml-2 text-red-400 font-semibold normal-case tracking-normal">⚠ Not balanced</span>
                        }
                      </td>
                      <td className="py-3 text-right font-bold font-mono text-white">{formatCurrency(totalDebit)}</td>
                      <td className="py-3 text-right font-bold font-mono text-white">{formatCurrency(totalCredit)}</td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </div>
        )
      })()}

      {showImport && (
        <ImportAccountsModal
          taxonomy={taxonomy}
          onClose={() => setShowImport(false)}
          onDone={() => { setShowImport(false); bypassNextGets(); load() }}
        />
      )}
      {showSubTypes && (
        <SubTypesModal onClose={() => { setShowSubTypes(false); loadTaxonomy() }} />
      )}
      {showOpening && (
        <OpeningBalancesModal
          accounts={accounts}
          onClose={() => setShowOpening(false)}
          onDone={() => { setShowOpening(false); bypassNextGets(); load() }}
        />
      )}
    </div>
  )
}

// ── Import Accounts modal ────────────────────────────────────────────────────
function ImportAccountsModal({ taxonomy, onClose, onDone }: {
  taxonomy: AccountTaxonomyGroup[]
  onClose: () => void
  onDone: () => void
}) {
  const [rows, setRows] = useState<{ code: string; name: string; group: string; status: string }[]>([])
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const parseCsv = (text: string) => {
    const lines = text.split(/\r?\n/).filter((l) => l.trim())
    if (!lines.length) return
    // Skip a header row if it looks like one
    const start = /code/i.test(lines[0]) && /name/i.test(lines[0]) ? 1 : 0
    const parsed = lines.slice(start).map((line) => {
      const [code = '', name = '', group = ''] = line.split(',').map((c) => c.trim().replace(/^"|"$/g, ''))
      return { code, name, group, status: '' }
    }).filter((r) => r.code && r.name)
    setRows(parsed)
  }

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    const reader = new FileReader()
    reader.onload = () => parseCsv(String(reader.result || ''))
    reader.readAsText(f)
  }

  const doImport = async () => {
    if (!rows.length) { toast.error('Nothing to import'); return }
    setBusy(true)
    let ok = 0, fail = 0
    const next = [...rows]
    for (let i = 0; i < next.length; i++) {
      const r = next[i]
      const spec = taxonomy.find((g) => g.group.toLowerCase() === r.group.toLowerCase())
      const account_type = spec?.base_account_type ?? 'asset'
      try {
        await accountingApi.createAccount({
          code: r.code, name: r.name, account_type,
          account_group: spec?.group ?? '',
          normal_balance: ['asset', 'expense', 'cogs'].includes(account_type) ? 'debit' : 'credit',
        })
        r.status = 'ok'; ok++
      } catch (err) {
        const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
        r.status = typeof apiErr === 'string' ? apiErr : ((apiErr as { message?: string })?.message ?? 'failed'); fail++
      }
      setRows([...next])
    }
    setBusy(false)
    toast[fail ? 'error' : 'success'](`Imported ${ok} account(s)${fail ? `, ${fail} failed` : ''}`)
    if (ok && !fail) onDone()
  }

  const groupNames = taxonomy.map((g) => g.group).join(', ')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative card w-full max-w-2xl p-6 space-y-4 max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-white">Import Chart of Accounts</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={20} /></button>
        </div>
        <p className="text-xs text-slate-400">
          Upload a CSV with columns <span className="font-mono text-slate-300">Code, Name, Account Type</span>.
          Account Type must be one of: <span className="text-slate-300">{groupNames}</span>.
        </p>
        <div className="flex gap-2">
          <input ref={fileRef} type="file" accept=".csv,text/csv" onChange={onFile} className="hidden" />
          <button onClick={() => fileRef.current?.click()} className="btn-ghost flex items-center gap-2 text-sm">
            <Upload size={14} /> Choose CSV
          </button>
          {rows.length > 0 && <span className="text-sm text-slate-400 self-center">{rows.length} row(s) parsed</span>}
        </div>
        {rows.length > 0 && (
          <div className="border border-surface-700 rounded-lg overflow-hidden max-h-64 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-800 sticky top-0">
                <tr>{['Code', 'Name', 'Type', 'Status'].map((h) => <th key={h} className="px-3 py-2 text-left text-xs text-slate-400">{h}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-surface-700">
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td className="px-3 py-1.5 font-mono text-slate-400">{r.code}</td>
                    <td className="px-3 py-1.5 text-slate-200">{r.name}</td>
                    <td className="px-3 py-1.5 text-slate-400">{r.group}</td>
                    <td className="px-3 py-1.5 text-xs">
                      {r.status === 'ok' ? <span className="text-green-400">✓</span>
                        : r.status ? <span className="text-red-400" title={r.status}>✗</span>
                        : <span className="text-slate-600">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex gap-3">
          <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white text-sm" onClick={onClose}>Close</button>
          <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={doImport} disabled={busy || !rows.length}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : `Import ${rows.length || ''}`}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Sub Account Types management modal ───────────────────────────────────────
function SubTypesModal({ onClose }: { onClose: () => void }) {
  const [subs, setSubs] = useState<AccountSubType[]>([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState({ name: '', account_group: 'Cash & Cash Equivalent', base_account_type: 'asset' })
  const [saving, setSaving] = useState(false)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [pageSize, setPageSize] = useState(10)
  const [page, setPage] = useState(1)
  const GROUPS = [
    ['Income', 'revenue'], ['Cost of Sales', 'cogs'], ['Indirect Cost', 'expense'], ['Expenses', 'expense'],
    ['Asset', 'asset'], ['Cash & Cash Equivalent', 'asset'], ['Liabilities', 'liability'], ['Equity', 'equity'],
  ] as const

  const load = async () => {
    setLoading(true)
    try { const { data } = await accountingApi.accountSubTypes(); setSubs(data.results ?? data) }
    catch { toast.error('Failed to load sub-types') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const add = async () => {
    if (!form.name.trim()) { toast.error('Name is required'); return }
    setSaving(true)
    try {
      await accountingApi.createAccountSubType(form)
      toast.success('Sub-type added'); setForm({ ...form, name: '' }); load()
    } catch { toast.error('Failed to add sub-type') }
    finally { setSaving(false) }
  }
  const toggle = async (s: AccountSubType) => {
    try { await accountingApi.updateAccountSubType(s.id, { is_active: !s.is_active }); load() }
    catch { toast.error('Failed to update') }
  }
  const remove = async (s: AccountSubType) => {
    if (!(await confirmDialog(`Delete sub-type "${s.name}"?`))) return
    try { await accountingApi.deleteAccountSubType(s.id); toast.success('Deleted'); load() }
    catch { toast.error('In use or system — deactivate instead') }
  }

  const filtered = subs.filter((s) => {
    const q = search.trim().toLowerCase()
    return !q || s.name.toLowerCase().includes(q) || s.account_group.toLowerCase().includes(q)
  })
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const pageItems = filtered.slice((page - 1) * pageSize, page * pageSize)
  const deletable = filtered.filter((s) => !s.is_system)
  const allSelected = deletable.length > 0 && deletable.every((s) => selected.has(s.id))

  const toggleSelect = (id: string) => {
    setSelected((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }
  const toggleSelectAll = () => {
    setSelected(allSelected ? new Set() : new Set(deletable.map((s) => s.id)))
  }
  const bulkDelete = async () => {
    if (!selected.size) return
    if (!(await confirmDialog(`Delete ${selected.size} selected sub-type(s)? System/in-use ones are skipped.`))) return
    let ok = 0, fail = 0
    for (const id of selected) {
      try { await accountingApi.deleteAccountSubType(id); ok++ } catch { fail++ }
    }
    setSelected(new Set())
    toast[fail ? 'error' : 'success'](`Deleted ${ok}${fail ? `, skipped ${fail} (system/in use)` : ''}`)
    load()
  }
  const exportCsv = () => {
    const rows = [['Sub Type', 'Account Type', 'Base Type', 'Status'],
      ...filtered.map((s) => [s.name, s.account_group, s.base_account_type, s.is_active ? 'Active' : 'Inactive'])]
    const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    const a = document.createElement('a'); a.href = url; a.download = 'account-sub-types.csv'; a.click(); URL.revokeObjectURL(url)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative card w-full max-w-2xl p-6 space-y-4 max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-white">Account Sub Types</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={20} /></button>
        </div>
        <div className="grid grid-cols-12 gap-2 items-end">
          <div className="col-span-4">
            <label className="text-xs text-slate-400 mb-1 block">Account Type</label>
            <select className="input" value={form.account_group}
              onChange={(e) => { const g = GROUPS.find((x) => x[0] === e.target.value); setForm({ ...form, account_group: e.target.value, base_account_type: g?.[1] ?? 'asset' }) }}>
              {GROUPS.map(([g]) => <option key={g} value={g}>{g}</option>)}
            </select>
          </div>
          <div className="col-span-5">
            <label className="text-xs text-slate-400 mb-1 block">Account Sub Type</label>
            <input className="input" placeholder="e.g. Mobile Money" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="col-span-3">
            <button className="btn-primary w-full py-2.5 justify-center disabled:opacity-50" onClick={add} disabled={saving}>
              {saving ? <Loader2 size={16} className="animate-spin" /> : <><Plus size={14} /> Add</>}
            </button>
          </div>
        </div>

        {/* Toolbar: search / export / bulk delete / page size */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[160px]">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
            <input className="input pl-8 py-2" placeholder="Search sub types…" value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
          </div>
          <button onClick={exportCsv} className="btn-ghost flex items-center gap-1.5 text-sm"><Download size={14} /> Export</button>
          <button onClick={bulkDelete} disabled={!selected.size}
            className={`flex items-center gap-1.5 text-sm px-3 py-2 rounded-lg ${selected.size ? 'text-red-400 hover:bg-red-500/10' : 'text-slate-600 cursor-not-allowed'}`}>
            <Trash2 size={14} /> Delete{selected.size ? ` (${selected.size})` : ''}
          </button>
          <select className="input py-2 w-auto" value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1) }}>
            {[10, 20, 50].map((n) => <option key={n} value={n}>View {n}</option>)}
          </select>
        </div>

        <div className="border border-surface-700 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-surface-800">
              <tr>
                <th className="px-3 py-2 w-8"><input type="checkbox" checked={allSelected} onChange={toggleSelectAll} /></th>
                {['Sub Type', 'Account Type', 'Status', ''].map((h) => <th key={h} className="px-3 py-2 text-left text-xs text-slate-400 uppercase">{h}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-700">
              {loading ? (
                <tr><td colSpan={5} className="px-3 py-6 text-center text-slate-500"><Loader2 size={16} className="animate-spin inline" /></td></tr>
              ) : pageItems.length === 0 ? (
                <tr><td colSpan={5} className="px-3 py-6 text-center text-slate-500">No sub-types match.</td></tr>
              ) : pageItems.map((s) => (
                <tr key={s.id}>
                  <td className="px-3 py-2">
                    <input type="checkbox" disabled={s.is_system} checked={selected.has(s.id)} onChange={() => toggleSelect(s.id)} />
                  </td>
                  <td className="px-3 py-2 text-slate-200">{s.name}</td>
                  <td className="px-3 py-2 text-slate-400">{s.account_group}</td>
                  <td className="px-3 py-2">
                    <button onClick={() => toggle(s)} className={s.is_active ? 'badge-green' : 'badge-slate'}>{s.is_active ? 'Active' : 'Inactive'}</button>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => remove(s)} disabled={s.is_system} title={s.is_system ? 'System sub-type' : 'Delete'}
                      className={`p-1.5 rounded-lg ${s.is_system ? 'text-slate-700' : 'text-slate-500 hover:text-red-400 hover:bg-red-500/10'}`}>
                      <Trash2 size={13} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>{filtered.length} sub-type{filtered.length === 1 ? '' : 's'}</span>
          <div className="flex items-center gap-2">
            <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}
              className={`px-2 py-1 rounded ${page <= 1 ? 'text-slate-700' : 'hover:bg-surface-600 text-slate-300'}`}>Prev</button>
            <span>Page {page} / {totalPages}</span>
            <button disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}
              className={`px-2 py-1 rounded ${page >= totalPages ? 'text-slate-700' : 'hover:bg-surface-600 text-slate-300'}`}>Next</button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Opening Balances (Take-On) modal ─────────────────────────────────────────
/** Segmented Dr/Cr control shared by every Opening Balances tab. */
function SideToggle({ value, onChange, className = '' }: {
  value: OBSide
  onChange: (s: OBSide) => void
  className?: string
}) {
  return (
    <div className={`flex rounded-lg overflow-hidden border border-surface-600 ${className}`}>
      {(['debit', 'credit'] as const).map((s) => (
        <button key={s} type="button" onClick={() => onChange(s)}
          className={`flex-1 py-2 text-xs ${value === s ? 'bg-brand-500/20 text-white' : 'text-slate-400'}`}>
          {s === 'debit' ? 'Dr' : 'Cr'}
        </button>
      ))}
    </div>
  )
}

type OBTab = 'accounts' | 'customers' | 'suppliers' | 'items'
type OBSide = 'debit' | 'credit'
interface SubRow { id: string; label: string; amount: string; side: OBSide; accountLabel?: string }
interface ItemRow { product_id: string; label: string; quantity: string; unit_cost: string; side: OBSide; accountLabel?: string }

export function OpeningBalancesModal({ accounts, onClose, onDone }: {
  accounts: Account[]
  onClose: () => void
  onDone: () => void
}) {
  const postable = (Array.isArray(accounts) ? accounts : []).filter((a) => a.code !== '3900')
  const [tab, setTab] = useState<OBTab>('accounts')
  const [asOf, setAsOf] = useState('')
  const [busy, setBusy] = useState(false)

  // Accounts tab
  const [entries, setEntries] = useState<{ account: string; amount: string; side: 'debit' | 'credit' }[]>([
    { account: '', amount: '', side: 'debit' },
  ])
  const setRow = (i: number, patch: Partial<{ account: string; amount: string; side: 'debit' | 'credit' }>) =>
    setEntries((e) => e.map((r, idx) => idx === i ? { ...r, ...patch } : r))
  const addRow = (after?: number) => setEntries((e) => {
    const row = { account: '', amount: '', side: 'debit' as const }
    if (after === undefined) return [...e, row]
    return [...e.slice(0, after + 1), row, ...e.slice(after + 1)]
  })
  // Always leave one row behind, otherwise the form becomes unusable.
  const removeRow = (i: number) => setEntries((e) => (e.length <= 1 ? e : e.filter((_, idx) => idx !== i)))

  // Sub-ledger tabs
  const [customers, setCustomers] = useState<SubRow[]>([])
  const [suppliers, setSuppliers] = useState<SubRow[]>([])
  const [items, setItems] = useState<ItemRow[]>([])
  const [loadedSub, setLoadedSub] = useState(false)

  // Footer text names the account the org has actually mapped, not a hardcoded code.
  const [mapping, setMapping] = useState<Record<string, string | null> | null>(null)
  useEffect(() => {
    accountingApi.getAccountMapping()
      .then(({ data }) => setMapping(data))
      .catch(() => setMapping(null))
  }, [])
  const mapped = (role: string, fallback: string) => {
    const code = mapping?.[`${role}_code`]
    const name = mapping?.[`${role}_name`]
    return code ? `${code} ${name ?? ''}`.trim() : fallback
  }
  const defaultAccounts = {
    receivable: mapped('accounts_receivable', 'Accounts Receivable'),
    payable: mapped('accounts_payable', 'Accounts Payable'),
    inventory: mapped('inventory_account', 'Inventory'),
  }

  useEffect(() => {
    if (loadedSub) return
    if (tab !== 'customers' && tab !== 'suppliers' && tab !== 'items') return
    setLoadedSub(true)
    ;(async () => {
      try {
        const [c, s, p] = await Promise.all([
          customerApi.list({ page_size: 500 }),
          supplierApi.list({ page_size: 500 }),
          inventoryApi.products({ page_size: 500 }),
        ])
        type Party = { id: string; name: string }
        type Acct = { code?: string | null; name?: string | null }
        const acctLabel = (a: Acct) => (a.code ? `${a.code} — ${a.name}` : undefined)
        const cust = (c.data.results ?? c.data) as (Party & { receivable_account_code?: string | null; receivable_account_name?: string | null })[]
        const sup = (s.data.results ?? s.data) as (Party & { payable_account_code?: string | null; payable_account_name?: string | null })[]
        const prod = (p.data.results ?? p.data) as (Party & { sku?: string; cost_price?: string | number; inventory_account_code?: string | null; inventory_account_name?: string | null })[]
        setCustomers(cust.map((x) => ({
          id: x.id, label: x.name, amount: '', side: 'debit',
          accountLabel: acctLabel({ code: x.receivable_account_code, name: x.receivable_account_name }),
        })))
        setSuppliers(sup.map((x) => ({
          id: x.id, label: x.name, amount: '', side: 'credit',
          accountLabel: acctLabel({ code: x.payable_account_code, name: x.payable_account_name }),
        })))
        setItems(prod.map((x) => ({
          product_id: x.id, label: `${x.sku ? x.sku + ' — ' : ''}${x.name}`,
          quantity: '', unit_cost: x.cost_price ? String(x.cost_price) : '', side: 'debit',
          accountLabel: acctLabel({ code: x.inventory_account_code, name: x.inventory_account_name }),
        })))
      } catch { toast.error('Failed to load sub-ledgers') }
    })()
  }, [tab, loadedSub])

  const totals = entries.reduce((acc, r) => {
    const amt = parseFloat(stripCommas(r.amount) || '0') || 0
    if (r.side === 'debit') acc.debit += amt; else acc.credit += amt
    return acc
  }, { debit: 0, credit: 0 })
  const diff = totals.debit - totals.credit

  // Sub-ledger totals are signed so a Dr and a Cr row offset each other, matching
  // what the posted journal will net to.
  const signed = (amount: string, side: OBSide) => {
    const v = parseFloat(stripCommas(amount) || '0') || 0
    return side === 'debit' ? v : -v
  }
  const subTotal = (rows: SubRow[]) => rows.reduce((s, r) => s + signed(r.amount, r.side), 0)
  const itemsTotal = items.reduce(
    (s, r) => s + signed(String((parseFloat(stripCommas(r.quantity) || '0') || 0) * (parseFloat(stripCommas(r.unit_cost) || '0') || 0)), r.side),
    0,
  )

  const toISO = (dd: string) => {
    if (!dd) return ''
    const [d, m, y] = dd.split('/'); return d && m && y ? `${y}-${m}-${d}` : dd
  }

  const accountsPayload = () => entries
    .filter((r) => r.account && parseFloat(stripCommas(r.amount) || '0') > 0)
    .map((r) => ({ account: r.account, amount: stripCommas(r.amount), side: r.side }))

  const subledgerPayload = () => ({
    customers: customers.filter((r) => parseFloat(stripCommas(r.amount) || '0') > 0)
      .map((r) => ({ id: r.id, amount: stripCommas(r.amount), side: r.side })),
    suppliers: suppliers.filter((r) => parseFloat(stripCommas(r.amount) || '0') > 0)
      .map((r) => ({ id: r.id, amount: stripCommas(r.amount), side: r.side })),
    items: items.filter((r) => parseFloat(stripCommas(r.quantity) || '0') > 0)
      .map((r) => ({ product_id: r.product_id, quantity: stripCommas(r.quantity), unit_cost: stripCommas(r.unit_cost), side: r.side })),
  })

  const submit = async () => {
    const iso = toISO(asOf)
    if (!iso) { toast.error('As-of date is required'); return }
    // Post everything the user has entered, on every tab — not just the tab that
    // happens to be open when they press the button.
    const acct = accountsPayload()
    const sub = subledgerPayload()
    const hasSub = sub.customers.length || sub.suppliers.length || sub.items.length
    if (!acct.length && !hasSub) { toast.error('Enter at least one opening balance'); return }
    setBusy(true)
    try {
      if (acct.length) await accountingApi.setOpeningBalances({ as_of_date: iso, entries: acct })
      if (hasSub) await accountingApi.setSubledgerOpeningBalances({ as_of_date: iso, ...sub })
      toast.success('Opening balances posted')
      onDone()
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : ((apiErr as { message?: string })?.message ?? 'Failed to post opening balances'))
    } finally { setBusy(false) }
  }

  const TABS: { key: OBTab; label: string; icon: typeof Users }[] = [
    { key: 'accounts', label: 'Accounts', icon: BookOpen },
    { key: 'customers', label: 'Customers', icon: Users },
    { key: 'suppliers', label: 'Suppliers', icon: Truck },
    { key: 'items', label: 'Inventory', icon: Package },
  ]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative card w-full max-w-2xl p-6 space-y-4 max-h-[88vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-white">Opening Balances</h2>
            <p className="text-xs text-slate-400">Take-on balances from your previous accounting system</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={20} /></button>
        </div>

        <div className="w-48">
          <label className="text-xs text-slate-400 mb-1 block">As of Date *</label>
          <DateInput value={asOf} onChange={setAsOf} />
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-surface-700">
          {TABS.map(({ key, label, icon: Icon }) => (
            <button key={key} onClick={() => setTab(key)}
              className={`flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 -mb-px transition-colors ${tab === key ? 'border-brand-500 text-white' : 'border-transparent text-slate-400 hover:text-white'}`}>
              <Icon size={14} /> {label}
            </button>
          ))}
        </div>

        {/* Accounts tab */}
        {tab === 'accounts' && (
          <>
            <div className="space-y-2">
              {entries.map((r, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 items-center">
                  <select className="input col-span-5" value={r.account} onChange={(e) => setRow(i, { account: e.target.value })}>
                    <option value="">Select account…</option>
                    {postable.map((a) => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
                  </select>
                  <SideToggle className="col-span-3" value={r.side} onChange={(s) => setRow(i, { side: s })} />
                  <input className="input col-span-2" inputMode="decimal" placeholder="0.00" value={r.amount}
                    onChange={(e) => setRow(i, { amount: formatAmountInput(e.target.value) })} />
                  <div className="col-span-2 flex items-center justify-center gap-1">
                    <button onClick={() => addRow(i)} title="Add line below"
                      className="text-slate-500 hover:text-brand-400"><Plus size={16} /></button>
                    <button onClick={() => removeRow(i)} title="Remove line" disabled={entries.length <= 1}
                      className="text-slate-500 hover:text-red-400 disabled:opacity-30 disabled:hover:text-slate-500"><X size={16} /></button>
                  </div>
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between text-sm border-t border-surface-700 pt-3">
              <div className="text-slate-400">Total Debit <span className="font-mono text-white ml-1">{formatCurrency(totals.debit)}</span></div>
              <div className="text-slate-400">Total Credit <span className="font-mono text-white ml-1">{formatCurrency(totals.credit)}</span></div>
              <div className="text-slate-400">
                Difference <span className={`font-mono ml-1 ${Math.abs(diff) < 0.01 ? 'text-green-400' : 'text-amber-400'}`}>{formatCurrency(Math.abs(diff))}</span>
              </div>
            </div>
            {Math.abs(diff) >= 0.01 && (
              <p className="text-[11px] text-amber-400/90 flex items-center gap-1.5">
                <AlertTriangle size={12} /> The {formatCurrency(Math.abs(diff))} difference will be posted to <strong>Take-On Suspense</strong> so the entry balances.
              </p>
            )}
          </>
        )}

        {/* Customers / Suppliers tabs */}
        {(tab === 'customers' || tab === 'suppliers') && (
          <SubledgerList
            rows={tab === 'customers' ? customers : suppliers}
            setRows={tab === 'customers' ? setCustomers : setSuppliers}
            emptyLabel={tab === 'customers' ? 'No customers found.' : 'No suppliers found.'}
            noun={tab === 'customers' ? 'customer' : 'supplier'}
            total={subTotal(tab === 'customers' ? customers : suppliers)}
            postsTo={tab === 'customers' ? defaultAccounts.receivable : defaultAccounts.payable}
          />
        )}

        {/* Inventory items tab */}
        {tab === 'items' && (
          <div className="space-y-2">
            {items.length === 0 ? (
              <p className="text-sm text-slate-500 py-6 text-center">No products found.</p>
            ) : (
              <div className="max-h-72 overflow-y-auto space-y-1.5 pr-1">
                {items.map((r, i) => (
                  <div key={r.product_id} className="grid grid-cols-12 gap-2 items-center">
                    <span className="col-span-4 text-sm text-slate-300 truncate" title={r.accountLabel ? `${r.label} → ${r.accountLabel}` : r.label}>
                      {r.label}
                      {r.accountLabel && <span className="block text-[10px] text-slate-500 truncate">{r.accountLabel}</span>}
                    </span>
                    <SideToggle className="col-span-2" value={r.side}
                      onChange={(s) => setItems((arr) => arr.map((x, idx) => idx === i ? { ...x, side: s } : x))} />
                    <input className="input col-span-3" inputMode="decimal" placeholder="Qty" value={r.quantity}
                      onChange={(e) => setItems((arr) => arr.map((x, idx) => idx === i ? { ...x, quantity: formatAmountInput(e.target.value) } : x))} />
                    <input className="input col-span-3" inputMode="decimal" placeholder="Unit cost" value={r.unit_cost}
                      onChange={(e) => setItems((arr) => arr.map((x, idx) => idx === i ? { ...x, unit_cost: formatAmountInput(e.target.value) } : x))} />
                  </div>
                ))}
              </div>
            )}
            <div className="flex items-center justify-between text-sm border-t border-surface-700 pt-3">
              <span className="text-slate-400">
                Inventory value <span className="font-mono text-white ml-1">{formatCurrency(Math.abs(itemsTotal))}</span>
                <span className="ml-1 text-xs">{itemsTotal < 0 ? 'Cr' : 'Dr'}</span>
              </span>
              <span className="text-[11px] text-slate-500">Posts to {defaultAccounts.inventory}, offset to Take-On Suspense</span>
            </div>
          </div>
        )}

        <div className="flex gap-3">
          <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white text-sm" onClick={onClose}>Cancel</button>
          <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={submit} disabled={busy}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : 'Post Opening Balances'}
          </button>
        </div>
      </div>
    </div>
  )
}

function SubledgerList({ rows, setRows, emptyLabel, noun, total, postsTo }: {
  rows: SubRow[]
  setRows: (updater: (prev: SubRow[]) => SubRow[]) => void
  emptyLabel: string
  noun: string
  total: number
  postsTo: string
}) {
  const [q, setQ] = useState('')
  const filtered = rows.filter((r) => !q.trim() || r.label.toLowerCase().includes(q.trim().toLowerCase()))
  const patch = (id: string, p: Partial<SubRow>) =>
    setRows((arr) => arr.map((x) => x.id === id ? { ...x, ...p } : x))
  return (
    <div className="space-y-2">
      <div className="relative">
        <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
        <input className="input pl-8 py-2" placeholder={`Search ${noun}s…`} value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {rows.length === 0 ? (
        <p className="text-sm text-slate-500 py-6 text-center">{emptyLabel}</p>
      ) : (
        <div className="max-h-72 overflow-y-auto space-y-1.5 pr-1">
          {filtered.map((r) => (
            <div key={r.id} className="grid grid-cols-12 gap-2 items-center">
              <span className="col-span-5 text-sm text-slate-300 truncate" title={r.accountLabel ? `${r.label} → ${r.accountLabel}` : r.label}>
                {r.label}
                {r.accountLabel && <span className="block text-[10px] text-slate-500 truncate">{r.accountLabel}</span>}
              </span>
              <SideToggle className="col-span-3" value={r.side} onChange={(s) => patch(r.id, { side: s })} />
              <input className="input col-span-4" inputMode="decimal" placeholder="0.00" value={r.amount}
                onChange={(e) => patch(r.id, { amount: formatAmountInput(e.target.value) })} />
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center justify-between text-sm border-t border-surface-700 pt-3">
        <span className="text-slate-400">
          Net <span className="font-mono text-white ml-1">{formatCurrency(Math.abs(total))}</span>
          <span className="ml-1 text-xs">{total < 0 ? 'Cr' : 'Dr'}</span>
        </span>
        <span className="text-[11px] text-slate-500">
          {rows.some((r) => r.accountLabel)
            ? `Posts to each ${noun}'s own account (default ${postsTo}), offset to Take-On Suspense`
            : `Posts to ${postsTo}, offset to Take-On Suspense`}
        </span>
      </div>
    </div>
  )
}
