import { useEffect, useState } from 'react'
import { Plus, X, BookMarked, Loader2, ChevronDown, ChevronUp, Trash2, Edit2, RotateCcw } from 'lucide-react'
import toast from 'react-hot-toast'
import { accountingApi } from '@/services/api'
import { formatCurrency, formatDate, formatAmountInput, stripCommas } from '@/lib/utils'
import type { JournalEntry, Account } from '@/types'
import DateInput from '@/components/DateInput'

interface JournalLineForm {
  account: string
  description: string
  debit: string
  credit: string
}

const BLANK_LINE: JournalLineForm = { account: '', description: '', debit: '', credit: '' }

interface JournalForm {
  description: string
  entry_date: string
}

const today = new Date().toISOString().split('T')[0]

export default function JournalPage() {
  const [entries, setEntries] = useState<JournalEntry[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedRow, setExpandedRow] = useState<string | null>(null)

  const [showModal, setShowModal] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState<JournalForm>({ description: '', entry_date: today })
  const [lines, setLines] = useState<JournalLineForm[]>([{ ...BLANK_LINE }, { ...BLANK_LINE }])
  const [saving, setSaving] = useState(false)

  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [jRes, aRes] = await Promise.all([accountingApi.journal(), accountingApi.accounts()])
      setEntries(jRes.data.results ?? jRes.data)
      setAccounts(aRes.data.results ?? aRes.data)
    } catch { toast.error('Failed to load journal entries') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const totalDebits = lines.reduce((s, l) => s + (parseFloat(stripCommas(l.debit)) || 0), 0)
  const totalCredits = lines.reduce((s, l) => s + (parseFloat(stripCommas(l.credit)) || 0), 0)
  const isBalanced = Math.abs(totalDebits - totalCredits) < 0.01 && totalDebits > 0

  const openCreate = () => {
    setEditId(null)
    setForm({ description: '', entry_date: today })
    setLines([{ ...BLANK_LINE }, { ...BLANK_LINE }])
    setShowModal(true)
  }

  const openEdit = (e: JournalEntry) => {
    setEditId(e.id)
    setForm({ description: e.description, entry_date: e.entry_date })
    setLines(
      e.lines.length > 0
        ? e.lines.map((l) => ({
            account: l.account as string,
            description: l.description || '',
            debit: parseFloat(l.debit) > 0 ? formatAmountInput(l.debit) : '',
            credit: parseFloat(l.credit) > 0 ? formatAmountInput(l.credit) : '',
          }))
        : [{ ...BLANK_LINE }, { ...BLANK_LINE }]
    )
    setShowModal(true)
  }

  const handleSave = async () => {
    if (!form.description.trim()) { toast.error('Description is required'); return }
    if (!isBalanced) { toast.error('Journal entry must be balanced (debits = credits)'); return }
    const validLines = lines.filter((l) => l.account && (parseFloat(stripCommas(l.debit)) > 0 || parseFloat(stripCommas(l.credit)) > 0))
    if (validLines.length < 2) { toast.error('At least 2 lines required'); return }
    setSaving(true)
    const payload = {
      ...form,
      lines: validLines.map((l) => ({
        account: l.account,
        description: l.description,
        debit: parseFloat(stripCommas(l.debit)) || 0,
        credit: parseFloat(stripCommas(l.credit)) || 0,
      })),
    }
    try {
      if (editId) {
        await accountingApi.updateJournalEntry(editId, payload)
        toast.success('Journal entry updated')
      } else {
        await accountingApi.createJournalEntry(payload)
        toast.success('Journal entry created')
      }
      setShowModal(false)
      load()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error
      toast.error(msg || 'Failed to save journal entry')
    } finally { setSaving(false) }
  }

  const handlePost = async (id: string) => {
    if (!confirm('Post this journal entry? It will be locked and cannot be edited.')) return
    setActionLoading(id + '-post')
    try { await accountingApi.postJournalEntry(id); toast.success('Entry posted'); load() }
    catch { toast.error('Failed to post entry') }
    finally { setActionLoading(null) }
  }

  const handleDelete = async (e: JournalEntry) => {
    if (!confirm(`Delete draft entry "${e.reference}"? This cannot be undone.`)) return
    setActionLoading(e.id + '-delete')
    try { await accountingApi.deleteJournalEntry(e.id); toast.success('Entry deleted'); load() }
    catch { toast.error('Cannot delete — entry may be in use') }
    finally { setActionLoading(null) }
  }

  const handleReverse = async (e: JournalEntry) => {
    if (!confirm(`Create a reversing entry for "${e.reference}"?\n\nThis will create a new draft entry with all debits and credits flipped. You can review and post it.`)) return
    setActionLoading(e.id + '-reverse')
    try {
      await accountingApi.reverseJournalEntry(e.id)
      toast.success('Reversing entry created as draft — review and post when ready')
      load()
    } catch { toast.error('Failed to create reversing entry') }
    finally { setActionLoading(null) }
  }

  const updateLine = (i: number, field: keyof JournalLineForm, value: string) => {
    setLines(lines.map((l, idx) => {
      if (idx !== i) return l
      const formatted = (field === 'debit' || field === 'credit') ? formatAmountInput(value) : value
      const updated = { ...l, [field]: formatted }
      if (field === 'debit' && value) updated.credit = ''
      if (field === 'credit' && value) updated.debit = ''
      return updated
    }))
  }

  const entryTotalDebit = (entry: JournalEntry) =>
    entry.lines.reduce((s, l) => s + parseFloat(l.debit || '0'), 0)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Journal Entries</h1>
          <p className="text-slate-400 text-sm">{entries.length} entries</p>
        </div>
        <button className="btn-primary sm:ml-auto" onClick={openCreate}>
          <Plus size={16} /> New Journal Entry
        </button>
      </div>

      {/* Info banner */}
      <div className="rounded-xl border border-slate-700/50 bg-surface-800/40 px-4 py-3 text-xs text-slate-400 flex items-start gap-2">
        <span className="text-amber-400 mt-0.5">ℹ</span>
        <span>
          <strong className="text-slate-300">Draft</strong> entries can be edited or deleted.
          <strong className="text-slate-300"> Posted</strong> entries are locked — use <strong className="text-slate-300">Reverse</strong> to create a correcting entry (accounting best practice).
        </span>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['', 'Reference', 'Date', 'Description', 'Status', 'Total Debit', 'Actions'].map((h) => (
                  <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 7 }).map((_, j) => (
                      <td key={j} className="px-4 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-16" /></td>
                    ))}
                  </tr>
                ))
              ) : entries.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center">
                    <BookMarked size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No journal entries yet</p>
                  </td>
                </tr>
              ) : entries.map((e) => (
                <>
                  <tr key={e.id} className="table-row">
                    <td className="px-4 py-3.5">
                      <button onClick={() => setExpandedRow(expandedRow === e.id ? null : e.id)} className="text-slate-400 hover:text-white">
                        {expandedRow === e.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>
                    </td>
                    <td className="px-4 py-3.5 font-mono text-brand-400">{e.reference}</td>
                    <td className="px-4 py-3.5 text-slate-400">{formatDate(e.entry_date)}</td>
                    <td className="px-4 py-3.5 text-slate-300 max-w-xs truncate">{e.description}</td>
                    <td className="px-4 py-3.5">
                      <span className={e.status === 'posted' ? 'badge-green' : 'badge-yellow'}>{e.status}</span>
                    </td>
                    <td className="px-4 py-3.5 font-mono text-white">{formatCurrency(String(entryTotalDebit(e)))}</td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-1.5">
                        {e.status === 'draft' && (
                          <>
                            <button
                              onClick={() => handlePost(e.id)}
                              disabled={actionLoading === e.id + '-post'}
                              className="text-xs px-2.5 py-1 rounded-lg bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors disabled:opacity-50"
                            >
                              {actionLoading === e.id + '-post' ? <Loader2 size={11} className="animate-spin" /> : 'Post'}
                            </button>
                            <button
                              onClick={() => openEdit(e)}
                              title="Edit draft entry"
                              className="p-1.5 text-slate-500 hover:text-white hover:bg-surface-600 rounded-lg transition-colors"
                            >
                              <Edit2 size={13} />
                            </button>
                            <button
                              onClick={() => handleDelete(e)}
                              disabled={actionLoading === e.id + '-delete'}
                              title="Delete draft entry"
                              className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors disabled:opacity-50"
                            >
                              {actionLoading === e.id + '-delete' ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                            </button>
                          </>
                        )}
                        {e.status === 'posted' && (
                          <button
                            onClick={() => handleReverse(e)}
                            disabled={actionLoading === e.id + '-reverse'}
                            title="Create reversing entry"
                            className="text-xs px-2.5 py-1 rounded-lg bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 transition-colors flex items-center gap-1 disabled:opacity-50"
                          >
                            {actionLoading === e.id + '-reverse'
                              ? <Loader2 size={11} className="animate-spin" />
                              : <><RotateCcw size={11} /> Reverse</>}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                  {expandedRow === e.id && (
                    <tr key={`${e.id}-lines`} className="bg-surface-900/50">
                      <td colSpan={7} className="px-6 py-4">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-surface-700">
                              <th className="pb-2 text-left text-slate-500 uppercase tracking-wider">Account</th>
                              <th className="pb-2 text-left text-slate-500 uppercase tracking-wider">Description</th>
                              <th className="pb-2 text-right text-slate-500 uppercase tracking-wider">Debit</th>
                              <th className="pb-2 text-right text-slate-500 uppercase tracking-wider">Credit</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-surface-700">
                            {e.lines.map((l) => (
                              <tr key={l.id}>
                                <td className="py-2 text-slate-300">{l.account_code} — {l.account_name}</td>
                                <td className="py-2 text-slate-500">{l.description || '—'}</td>
                                <td className="py-2 text-right font-mono text-white">{parseFloat(l.debit) > 0 ? formatCurrency(l.debit) : '—'}</td>
                                <td className="py-2 text-right font-mono text-white">{parseFloat(l.credit) > 0 ? formatCurrency(l.credit) : '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Create / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative card w-full max-w-3xl p-6 space-y-5 overflow-y-auto max-h-[90vh]">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">{editId ? 'Edit Journal Entry' : 'New Journal Entry'}</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Description *</label>
                <input className="input" placeholder="e.g. Monthly depreciation, correction entry…" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Entry Date</label>
                <DateInput value={form.entry_date} onChange={(v) => setForm({ ...form, entry_date: v })} />
              </div>
            </div>

            {/* Lines */}
            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Journal Lines</p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-700">
                      <th className="px-2 py-2 text-left text-xs text-slate-500">Account</th>
                      <th className="px-2 py-2 text-left text-xs text-slate-500">Description</th>
                      <th className="px-2 py-2 text-left text-xs text-slate-500">Debit</th>
                      <th className="px-2 py-2 text-left text-xs text-slate-500">Credit</th>
                      <th className="px-2 py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {lines.map((line, i) => (
                      <tr key={i}>
                        <td className="px-2 py-1.5">
                          <select className="input py-1.5 text-sm" value={line.account} onChange={(e) => updateLine(i, 'account', e.target.value)}>
                            <option value="">— Account —</option>
                            {accounts.map((a) => <option key={a.id} value={a.id}>{a.code} — {a.name}</option>)}
                          </select>
                        </td>
                        <td className="px-2 py-1.5">
                          <input className="input py-1.5 text-sm" placeholder="Note (optional)" value={line.description} onChange={(e) => updateLine(i, 'description', e.target.value)} />
                        </td>
                        <td className="px-2 py-1.5">
                          <input type="text" inputMode="decimal" className="input py-1.5 text-sm" placeholder="0.00" value={line.debit} onChange={(e) => updateLine(i, 'debit', e.target.value)} />
                        </td>
                        <td className="px-2 py-1.5">
                          <input type="text" inputMode="decimal" className="input py-1.5 text-sm" placeholder="0.00" value={line.credit} onChange={(e) => updateLine(i, 'credit', e.target.value)} />
                        </td>
                        <td className="px-2 py-1.5">
                          {lines.length > 2 && (
                            <button onClick={() => setLines(lines.filter((_, idx) => idx !== i))} className="p-1 text-slate-500 hover:text-red-400 transition-colors"><Trash2 size={14} /></button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button onClick={() => setLines([...lines, { ...BLANK_LINE }])} className="btn-ghost text-sm mt-2 flex items-center gap-1">
                <Plus size={13} /> Add Line
              </button>
            </div>

            {/* Balance indicator */}
            <div className={`flex items-center justify-between p-3 rounded-xl border ${isBalanced ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-red-500/30 bg-red-500/5'}`}>
              <div className="flex gap-6 text-sm">
                <span className="text-slate-400">Debits: <span className="text-white font-mono">{formatCurrency(String(totalDebits))}</span></span>
                <span className="text-slate-400">Credits: <span className="text-white font-mono">{formatCurrency(String(totalCredits))}</span></span>
              </div>
              <span className={`text-sm font-semibold ${isBalanced ? 'text-emerald-400' : 'text-red-400'}`}>
                {isBalanced ? 'Balanced ✓' : 'Unbalanced'}
              </span>
            </div>

            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleSave} disabled={saving || !isBalanced}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : editId ? 'Save Changes' : 'Save Journal Entry'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
