import { useEffect, useRef, useState } from 'react'
import { confirmDialog } from '@/lib/dialog'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, X, BookOpen, Edit2, Trash2, Loader2, Download, RefreshCw, ChevronRight, AlertTriangle, ChevronDown } from 'lucide-react'
import toast from 'react-hot-toast'
import { accountingApi, bypassNextGets } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'
import { saveBlobFile } from '@/lib/saveBlobFile'
import DateInput from '@/components/DateInput'
import { useAuthStore } from '@/store/authStore'
import type { Account, AccountLedger } from '@/types'

const TYPE_BADGE: Record<string, string> = {
  asset: 'badge-green',
  liability: 'badge-red',
  equity: 'badge-blue',
  revenue: 'badge-orange',
  expense: 'badge-yellow',
  cogs: 'badge-slate',
}

interface AccountForm {
  code: string
  name: string
  account_type: string
  parent: string
  description: string
}

const BLANK: AccountForm = { code: '', name: '', account_type: 'asset', parent: '', description: '' }

export default function ChartOfAccountsPage() {
  const { organisation } = useAuthStore()
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [seeding, setSeeding] = useState(false)

  const [showModal, setShowModal] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState<AccountForm>(BLANK)
  const [saving, setSaving] = useState(false)

  const [showTrialBalance, setShowTrialBalance] = useState(false)
  const [trialBalance, setTrialBalance] = useState<Record<string, unknown> | null>(null)
  const [loadingTB, setLoadingTB] = useState(false)
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [showExportMenu, setShowExportMenu] = useState(false)
  const exportRef = useRef<HTMLDivElement>(null)

  // Ledger drill-down
  const [ledgerAccount, setLedgerAccount] = useState<Account | null>(null)
  const [ledger, setLedger] = useState<AccountLedger | null>(null)
  const [ledgerLoading, setLedgerLoading] = useState(false)
  const [ledgerFrom, setLedgerFrom] = useState('')
  const [ledgerTo, setLedgerTo] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await accountingApi.accounts()
      setAccounts(data.results ?? data)
    } catch { toast.error('Failed to load accounts') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useDataRefresh(load)

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

  const openCreate = () => { setEditId(null); setForm(BLANK); setShowModal(true) }
  const openEdit = (a: Account) => {
    setEditId(a.id)
    setForm({ code: a.code, name: a.name, account_type: a.account_type, parent: a.parent ?? '', description: a.description })
    setShowModal(true)
  }

  const handleSave = async () => {
    if (!form.code.trim()) { toast.error('Account code is required'); return }
    if (!form.name.trim()) { toast.error('Account name is required'); return }
    setSaving(true)
    try {
      const payload = { ...form, parent: form.parent || null }
      if (editId) { await accountingApi.updateAccount(editId, payload); toast.success('Account updated') }
      else { await accountingApi.createAccount(payload); toast.success('Account created') }
      setShowModal(false)
      load()
    } catch { toast.error('Failed to save account') }
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
  const typeCounts = TYPES.reduce((acc, t) => ({ ...acc, [t]: accounts.filter((a) => a.account_type === t).length }), {} as Record<string, number>)
  const filteredAccounts = typeFilter === 'all' ? accounts : accounts.filter((a) => a.account_type === typeFilter)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Chart of Accounts</h1>
          <p className="text-slate-400 text-sm">
            {typeFilter === 'all' ? `${accounts.length} accounts` : `${filteredAccounts.length} ${typeFilter} accounts`}
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
          <span className="badge-slate">all</span>
          <p className="text-lg font-bold text-white mt-1">{accounts.length}</p>
        </button>
        {TYPES.map((t) => (
          <button
            key={t}
            onClick={() => setTypeFilter(typeFilter === t ? 'all' : t)}
            className={`card p-3 text-center transition-colors ${typeFilter === t ? 'ring-2 ring-brand-500/60' : 'hover:bg-surface-700/50'}`}
          >
            <span className={TYPE_BADGE[t]}>{t}</span>
            <p className="text-lg font-bold text-white mt-1">{typeCounts[t] ?? 0}</p>
          </button>
        ))}
      </div>
      {typeFilter !== 'all' && (
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <span>Showing <strong className="text-white">{filteredAccounts.length}</strong> {typeFilter} accounts</span>
          <button onClick={() => setTypeFilter('all')} className="text-brand-400 hover:underline text-xs">Clear filter</button>
        </div>
      )}

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Code', 'Account Name', 'Type', 'Balance', 'System', 'Actions', ''].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
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
                  <td colSpan={6} className="px-5 py-12 text-center">
                    <BookOpen size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500 mb-3">No accounts yet</p>
                    <button onClick={handleSeed} disabled={seeding} className="btn-primary text-sm">
                      {seeding ? 'Seeding…' : 'Seed Default Chart of Accounts'}
                    </button>
                  </td>
                </tr>
              ) : filteredAccounts.map((a) => (
                <tr
                  key={a.id}
                  className="table-row cursor-pointer"
                  onClick={() => openLedger(a)}
                >
                  <td className="px-5 py-3.5 font-mono text-slate-400">{a.code}</td>
                  <td className="px-5 py-3.5 text-white font-medium">{a.name}</td>
                  <td className="px-5 py-3.5"><span className={TYPE_BADGE[a.account_type]}>{a.account_type}</span></td>
                  <td className="px-5 py-3.5 text-right font-mono text-white">{formatCurrency(a.balance)}</td>
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
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Code *</label>
                <input className="input" placeholder="e.g. 1001" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Type *</label>
                <select className="input" value={form.account_type} onChange={(e) => setForm({ ...form, account_type: e.target.value })}>
                  {TYPES.map((t) => <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>)}
                </select>
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Account Name *</label>
                <input className="input" placeholder="e.g. Cash and Cash Equivalents" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Parent Account</label>
                <select className="input" value={form.parent} onChange={(e) => setForm({ ...form, parent: e.target.value })}>
                  <option value="">None (top-level)</option>
                  {accounts.filter((a) => a.id !== editId).map((a) => (
                    <option key={a.id} value={a.id}>{a.code} — {a.name}</option>
                  ))}
                </select>
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
    </div>
  )
}
