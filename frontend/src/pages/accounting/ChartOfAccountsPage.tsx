import { useEffect, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, X, BookOpen, Edit2, Trash2, Loader2, Download, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
import { accountingApi, bypassNextGets } from '@/services/api'
import { formatCurrency } from '@/lib/utils'
import type { Account } from '@/types'

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
    if (!confirm('Seed default Chart of Accounts? This will add standard Nigerian accounting accounts.')) return
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
    if (!confirm(`Delete account "${a.name}"?`)) return
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
                {['Code', 'Account Name', 'Type', 'Balance', 'System', 'Actions'].map((h) => (
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
                <tr key={a.id} className="table-row">
                  <td className="px-5 py-3.5 font-mono text-slate-400">{a.code}</td>
                  <td className="px-5 py-3.5 text-white font-medium">{a.name}</td>
                  <td className="px-5 py-3.5"><span className={TYPE_BADGE[a.account_type]}>{a.account_type}</span></td>
                  <td className="px-5 py-3.5 text-right font-mono text-white">{formatCurrency(a.balance)}</td>
                  <td className="px-5 py-3.5">{a.is_system ? <span className="badge-blue">System</span> : <span className="text-slate-600">—</span>}</td>
                  <td className="px-5 py-3.5">
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

        const downloadCSV = () => {
          const header = 'Code,Account,Type,Debit,Credit\n'
          const body = rows.map((r) => `${r.code},"${r.name}",${r.type},${r.debit.toFixed(2)},${r.credit.toFixed(2)}`).join('\n')
          const totals = `\n,TOTAL,,${totalDebit.toFixed(2)},${totalCredit.toFixed(2)}`
          const blob = new Blob([header + body + totals], { type: 'text/csv' })
          const a = document.createElement('a'); a.href = URL.createObjectURL(blob)
          a.download = `trial-balance-${new Date().toISOString().split('T')[0]}.csv`; a.click()
        }

        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowTrialBalance(false)} />
            <div className="relative card w-full max-w-2xl p-6 space-y-4 overflow-y-auto max-h-[85vh]">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-bold text-white">Trial Balance</h2>
                <div className="flex items-center gap-2">
                  {rows.length > 0 && (
                    <button onClick={downloadCSV} className="flex items-center gap-1.5 text-xs text-brand-400 hover:text-brand-300 transition-colors">
                      <Download size={13} /> Export CSV
                    </button>
                  )}
                  <button onClick={() => setShowTrialBalance(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
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
