import { useEffect, useState, Fragment, useRef } from 'react'
import { confirmDialog, promptDialog } from '@/lib/dialog'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, X, BookMarked, Loader2, ChevronDown, ChevronUp, Trash2, Edit2, RotateCcw, RefreshCw, Upload, Send, CheckCircle, XCircle, Minus } from 'lucide-react'
import toast from 'react-hot-toast'
import { accountingApi, bypassNextGets } from '@/services/api'
import { formatCurrency, formatDate, formatAmountInput, stripCommas } from '@/lib/utils'
import AmountInput from '@/components/AmountInput'
import type { JournalEntry, Account } from '@/types'
import DateInput from '@/components/DateInput'

const APPROVAL_BADGE: Record<string, string> = {
  pending: 'badge-yellow', approved: 'badge-green', rejected: 'badge-red', none: '',
}

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
  const [showImport, setShowImport] = useState(false)
  const [signEntry, setSignEntry] = useState<JournalEntry | null>(null)
  const [filterFrom, setFilterFrom] = useState('')
  const [filterTo, setFilterTo] = useState('')
  const [filterStatus, setFilterStatus] = useState('')

  // Preview of the reference the backend will auto-assign to the next entry.
  const nextReference = (() => {
    let max = 0
    for (const e of entries) {
      const m = /(\d+)\s*$/.exec(e.reference || '')
      if (m) max = Math.max(max, parseInt(m[1], 10))
    }
    return `JE-${String(max + 1).padStart(5, '0')}`
  })()

  const toISO = (dd: string) => {
    if (!dd) return ''
    const [d, m, y] = dd.split('/'); return d && m && y ? `${y}-${m}-${d}` : dd
  }

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      const f = toISO(filterFrom), t = toISO(filterTo)
      if (f) params.date_from = f
      if (t) params.date_to = t
      if (filterStatus) params.status = filterStatus
      const [jRes, aRes] = await Promise.allSettled([accountingApi.journal(params), accountingApi.accounts()])
      if (jRes.status === 'fulfilled') {
        const data = jRes.value.data.results ?? jRes.value.data
        setEntries(Array.isArray(data) ? data : [])
      } else {
        toast.error('Failed to load journal entries')
      }
      if (aRes.status === 'fulfilled') {
        const raw = aRes.value.data.results ?? aRes.value.data
        const accts: Account[] = Array.isArray(raw) ? raw : []
        setAccounts(accts)
        if (accts.length === 0) toast.error('No chart of accounts found. Ask a superuser to reseed the COA for this organisation.')
      } else {
        toast.error('Failed to load chart of accounts')
      }
    } catch (e) {
      console.error('Journal load error:', e)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useDataRefresh(load)

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
      (e.lines ?? []).length > 0
        ? (e.lines ?? []).map((l) => ({
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
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr as { message?: string })?.message
      toast.error(msg || 'Failed to save journal entry')
    } finally { setSaving(false) }
  }

  const handlePost = async (id: string) => {
    if (!(await confirmDialog('Post this journal entry? It will be locked and cannot be edited.'))) return
    setActionLoading(id + '-post')
    try {
      await accountingApi.postJournalEntry(id)
      toast.success('Entry posted')
    } catch (err: any) {
      const msg: unknown = err?.response?.data?.error
      // 400 "Already posted" means a concurrent request (sync replay, double-click)
      // already succeeded — treat it as success so the user isn't misled.
      if (typeof msg === 'string' && msg.toLowerCase().includes('already posted')) {
        toast.success('Entry posted')
      } else {
        const detail = typeof msg === 'string' ? msg : (msg as any)?.message
        toast.error(detail ?? 'Failed to post entry')
      }
    } finally {
      setActionLoading(null)
      load()
    }
  }

  const handleDelete = async (e: JournalEntry) => {
    if (!(await confirmDialog(`Delete draft entry "${e.reference}"? This cannot be undone.`))) return
    setActionLoading(e.id + '-delete')
    try { await accountingApi.deleteJournalEntry(e.id); toast.success('Entry deleted'); load() }
    catch { toast.error('Cannot delete — entry may be in use') }
    finally { setActionLoading(null) }
  }

  const handleReverse = async (e: JournalEntry) => {
    if (!(await confirmDialog(`Create a reversing entry for "${e.reference}"?\n\nThis will create a new draft entry with all debits and credits flipped. You can review and post it.`))) return
    setActionLoading(e.id + '-reverse')
    try {
      await accountingApi.reverseJournalEntry(e.id)
      toast.success('Reversing entry created as draft — review and post when ready')
      load()
    } catch { toast.error('Failed to create reversing entry') }
    finally { setActionLoading(null) }
  }

  const handleSubmitApproval = async (e: JournalEntry) => {
    setActionLoading(e.id + '-submit')
    try { await accountingApi.submitJournalForApproval(e.id); toast.success('Submitted for approval'); load() }
    catch { toast.error('Failed to submit') }
    finally { setActionLoading(null) }
  }

  const handleApprove = async (e: JournalEntry) => {
    const post = await confirmDialog('Approve this journal entry and post it to the ledger now?')
    setActionLoading(e.id + '-approve')
    try {
      await accountingApi.approveJournalEntry(e.id, { post })
      toast.success(post ? 'Approved and posted' : 'Approved')
      load()
    } catch { toast.error('Failed to approve') }
    finally { setActionLoading(null) }
  }

  const handleReject = async (e: JournalEntry) => {
    const note = await promptDialog('Reason for rejection (optional):')
    if (note === null) return
    setActionLoading(e.id + '-reject')
    try { await accountingApi.rejectJournalEntry(e.id, { note }); toast.success('Entry rejected'); load() }
    catch { toast.error('Failed to reject') }
    finally { setActionLoading(null) }
  }

  const updateLine = (i: number, field: keyof JournalLineForm, value: string) => {
    setLines(lines.map((l, idx) => {
      if (idx !== i) return l
      const updated = { ...l, [field]: value }
      if (field === 'debit' && value) updated.credit = ''
      if (field === 'credit' && value) updated.debit = ''
      return updated
    }))
  }

  const entryTotalDebit = (entry: JournalEntry) =>
    (entry.lines ?? []).reduce((s, l) => s + parseFloat(l.debit || '0'), 0)

  const exportJournalCSV = async () => {
    const { saveBlobFile } = await import('@/lib/saveBlobFile')
    const rows: string[] = ['Reference,Date,Description,Status,Account,Line Description,Debit,Credit']
    for (const e of entries) {
      for (const l of (e.lines ?? [])) {
        rows.push(`${e.reference},${e.entry_date},"${(e.description || '').replace(/"/g, '""')}",${e.status},${l.account_code} ${l.account_name},"${(l.description || '').replace(/"/g, '""')}",${l.debit},${l.credit}`)
      }
    }
    await saveBlobFile(new Blob([rows.join('\n')], { type: 'text/csv' }), `journal-report-${new Date().toISOString().slice(0, 10)}.csv`)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Journal Entries</h1>
          <p className="text-slate-400 text-sm">{entries.length} entries</p>
        </div>
        <div className="flex items-center gap-2 sm:ml-auto">
          <button onClick={() => { bypassNextGets(); load() }} disabled={loading} className="btn-ghost p-2 text-slate-400 hover:text-white" title="Refresh">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <button className="btn-ghost flex items-center gap-2 text-sm" onClick={() => setShowImport(true)}>
            <Upload size={14} /> Import
          </button>
          <button className="btn-primary" onClick={openCreate}>
            <Plus size={16} /> New Journal Entry
          </button>
        </div>
      </div>

      {/* Info banner */}
      <div className="rounded-xl border border-slate-700/50 bg-surface-800/40 px-4 py-3 text-xs text-slate-400 flex items-start gap-2">
        <span className="text-amber-400 mt-0.5">ℹ</span>
        <span>
          <strong className="text-slate-300">Draft</strong> entries can be edited or deleted.
          <strong className="text-slate-300"> Posted</strong> entries are locked — use <strong className="text-slate-300">Reverse</strong> to create a correcting entry (accounting best practice).
        </span>
      </div>

      {/* Journal report filter bar */}
      <div className="card p-3 flex flex-wrap items-end gap-2">
        <div>
          <label className="text-[11px] text-slate-500 block mb-1">From</label>
          <DateInput value={filterFrom} onChange={setFilterFrom} />
        </div>
        <div>
          <label className="text-[11px] text-slate-500 block mb-1">To</label>
          <DateInput value={filterTo} onChange={setFilterTo} />
        </div>
        <div>
          <label className="text-[11px] text-slate-500 block mb-1">Status</label>
          <select className="input py-2" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
            <option value="">All</option>
            <option value="draft">Draft</option>
            <option value="posted">Posted</option>
          </select>
        </div>
        <button onClick={() => { bypassNextGets(); load() }} className="btn-ghost text-sm">Apply</button>
        {(filterFrom || filterTo || filterStatus) && (
          <button onClick={() => { setFilterFrom(''); setFilterTo(''); setFilterStatus(''); bypassNextGets(); setTimeout(load, 0) }} className="text-xs text-brand-400 hover:underline">Clear</button>
        )}
        {entries.length > 0 && (
          <button onClick={exportJournalCSV} className="btn-ghost flex items-center gap-2 text-sm ml-auto"><Upload size={14} className="rotate-180" /> Export CSV</button>
        )}
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
                <Fragment key={e.id}>
                  <tr className="table-row">
                    <td className="px-4 py-3.5">
                      <button onClick={() => setExpandedRow(expandedRow === e.id ? null : e.id)} className="text-slate-400 hover:text-white">
                        {expandedRow === e.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>
                    </td>
                    <td className="px-4 py-3.5 font-mono text-brand-400">{e.reference}</td>
                    <td className="px-4 py-3.5 text-slate-400">{formatDate(e.entry_date)}</td>
                    <td className="px-4 py-3.5 text-slate-300 max-w-xs truncate">{e.description}</td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-1.5">
                        <span className={e.status === 'posted' ? 'badge-green' : 'badge-yellow'}>{e.status}</span>
                        {e.approval_status && e.approval_status !== 'none' && (
                          <span className={APPROVAL_BADGE[e.approval_status]} title={e.approval_note || ''}>{e.approval_status}</span>
                        )}
                        {(e.signature || e.attachment) && (
                          <span title={`Signed${e.signed_by_name ? ` by ${e.signed_by_name}` : ''}`}><Edit2 size={12} className="text-brand-400" /></span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3.5 font-mono text-white">{formatCurrency(String(entryTotalDebit(e)))}</td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {e.status === 'draft' && (
                          <>
                            {e.approval_status !== 'pending' && (
                              <button
                                onClick={() => handleSubmitApproval(e)}
                                disabled={actionLoading === e.id + '-submit'}
                                title="Submit for approval"
                                className="text-xs px-2.5 py-1 rounded-lg bg-sky-500/15 text-sky-400 hover:bg-sky-500/25 transition-colors flex items-center gap-1 disabled:opacity-50"
                              >
                                {actionLoading === e.id + '-submit' ? <Loader2 size={11} className="animate-spin" /> : <><Send size={11} /> Submit</>}
                              </button>
                            )}
                            {e.approval_status === 'pending' && (
                              <>
                                <button onClick={() => handleApprove(e)} disabled={actionLoading === e.id + '-approve'}
                                  title="Approve" className="text-xs px-2.5 py-1 rounded-lg bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 flex items-center gap-1 disabled:opacity-50">
                                  {actionLoading === e.id + '-approve' ? <Loader2 size={11} className="animate-spin" /> : <><CheckCircle size={11} /> Approve</>}
                                </button>
                                <button onClick={() => handleReject(e)} disabled={actionLoading === e.id + '-reject'}
                                  title="Reject" className="text-xs px-2.5 py-1 rounded-lg bg-red-500/15 text-red-400 hover:bg-red-500/25 flex items-center gap-1 disabled:opacity-50">
                                  {actionLoading === e.id + '-reject' ? <Loader2 size={11} className="animate-spin" /> : <><XCircle size={11} /> Reject</>}
                                </button>
                              </>
                            )}
                            <button
                              onClick={() => handlePost(e.id)}
                              disabled={actionLoading === e.id + '-post'}
                              className="text-xs px-2.5 py-1 rounded-lg bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors disabled:opacity-50"
                            >
                              {actionLoading === e.id + '-post' ? <Loader2 size={11} className="animate-spin" /> : 'Post'}
                            </button>
                            <button onClick={() => setSignEntry(e)} title="E-sign / attach document" className="p-1.5 text-slate-500 hover:text-brand-400 hover:bg-surface-600 rounded-lg transition-colors">
                              <Upload size={13} />
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
                          <>
                            <button onClick={() => setSignEntry(e)} title="E-sign / attach document" className="p-1.5 text-slate-500 hover:text-brand-400 hover:bg-surface-600 rounded-lg transition-colors">
                              <Upload size={13} />
                            </button>
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
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                  {expandedRow === e.id && (
                    <tr className="bg-surface-900/50">
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
                            {(e.lines ?? []).map((l) => (
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
                </Fragment>
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
              <div className="flex items-center gap-3">
                <h2 className="text-lg font-bold text-white">{editId ? 'Edit Journal Entry' : 'New Journal Entry'}</h2>
                <span className="font-mono text-xs px-2 py-1 rounded-lg bg-surface-800 text-brand-400 border border-surface-700">
                  {editId ? (entries.find((x) => x.id === editId)?.reference ?? '') : `${nextReference} (auto)`}
                </span>
              </div>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Description <span className="text-red-400">*</span></label>
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
                          <AmountInput className="input py-1.5 text-sm" placeholder="0.00" value={line.debit} onChange={(v) => updateLine(i, 'debit', v)} />
                        </td>
                        <td className="px-2 py-1.5">
                          <AmountInput className="input py-1.5 text-sm" placeholder="0.00" value={line.credit} onChange={(v) => updateLine(i, 'credit', v)} />
                        </td>
                        <td className="px-2 py-1.5">
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => setLines(lines.flatMap((l, idx) => idx === i ? [l, { ...BLANK_LINE }] : [l]))}
                              title="Add line below"
                              className="p-1 rounded text-emerald-400 hover:bg-emerald-500/10 transition-colors"
                            >
                              <Plus size={14} />
                            </button>
                            <button
                              onClick={() => setLines(lines.length > 2 ? lines.filter((_, idx) => idx !== i) : lines)}
                              disabled={lines.length <= 2}
                              title={lines.length <= 2 ? 'At least two lines required' : 'Remove line'}
                              className={`p-1 rounded transition-colors ${lines.length <= 2 ? 'text-slate-700 cursor-not-allowed' : 'text-red-400 hover:bg-red-500/10'}`}
                            >
                              <Minus size={14} />
                            </button>
                          </div>
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

      {showImport && (
        <ImportJournalModal
          accounts={accounts}
          onClose={() => setShowImport(false)}
          onDone={() => { setShowImport(false); bypassNextGets(); load() }}
        />
      )}
      {signEntry && (
        <SignJournalModal
          entry={signEntry}
          onClose={() => setSignEntry(null)}
          onDone={() => { setSignEntry(null); bypassNextGets(); load() }}
        />
      )}
    </div>
  )
}

// ── Import Journal Entries modal ─────────────────────────────────────────────
function ImportJournalModal({ accounts, onClose, onDone }: {
  accounts: Account[]
  onClose: () => void
  onDone: () => void
}) {
  const [rows, setRows] = useState<{ date: string; description: string; account: string; debit: string; credit: string }[]>([])
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const byCode = new Map(accounts.map((a) => [a.code, a.id]))

  const parseCsv = (text: string) => {
    const lines = text.split(/\r?\n/).filter((l) => l.trim())
    if (!lines.length) return
    const start = /date/i.test(lines[0]) && /debit/i.test(lines[0]) ? 1 : 0
    const parsed = lines.slice(start).map((line) => {
      const [date = '', description = '', account = '', debit = '', credit = ''] = line.split(',').map((c) => c.trim().replace(/^"|"$/g, ''))
      return { date, description, account, debit, credit }
    }).filter((r) => r.account)
    setRows(parsed)
  }

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; if (!f) return
    const reader = new FileReader()
    reader.onload = () => parseCsv(String(reader.result || ''))
    reader.readAsText(f)
  }

  const doImport = async () => {
    // Group consecutive rows by (date, description) into one entry.
    const groups: Record<string, typeof rows> = {}
    for (const r of rows) {
      const key = `${r.date}|${r.description}`
      ;(groups[key] ||= []).push(r)
    }
    const entries = Object.entries(groups).map(([key, grp]) => {
      const [date, description] = key.split('|')
      return {
        entry_date: date || undefined,
        description: description || 'Imported entry',
        lines: grp.map((r) => ({
          account: byCode.get(r.account) || r.account,
          debit: parseFloat(stripCommas(r.debit) || '0') || 0,
          credit: parseFloat(stripCommas(r.credit) || '0') || 0,
        })),
      }
    })
    if (!entries.length) { toast.error('Nothing to import'); return }
    setBusy(true)
    try {
      const { data } = await accountingApi.importJournalEntries({ entries })
      const errs = (data.errors ?? []) as { row: number; error: string }[]
      toast[errs.length ? 'error' : 'success'](`Imported ${data.created} entries as drafts${errs.length ? `, ${errs.length} failed` : ''}`)
      if (data.created) onDone()
    } catch {
      toast.error('Import failed')
    } finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative card w-full max-w-2xl p-6 space-y-4 max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-white">Import Journal Entries</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={20} /></button>
        </div>
        <p className="text-xs text-slate-400">
          CSV columns: <span className="font-mono text-slate-300">Date, Description, Account Code, Debit, Credit</span>.
          Rows sharing the same date + description become one balanced entry. Imported as <strong>drafts</strong> for review.
        </p>
        <div className="flex gap-2 items-center">
          <input ref={fileRef} type="file" accept=".csv,text/csv" onChange={onFile} className="hidden" />
          <button onClick={() => fileRef.current?.click()} className="btn-ghost flex items-center gap-2 text-sm"><Upload size={14} /> Choose CSV</button>
          {rows.length > 0 && <span className="text-sm text-slate-400">{rows.length} line(s) parsed</span>}
        </div>
        {rows.length > 0 && (
          <div className="border border-surface-700 rounded-lg overflow-hidden max-h-64 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="bg-surface-800 sticky top-0"><tr>{['Date', 'Description', 'Account', 'Debit', 'Credit'].map((h) => <th key={h} className="px-2 py-1.5 text-left text-slate-400">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-surface-700">
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td className="px-2 py-1 text-slate-400">{r.date}</td>
                    <td className="px-2 py-1 text-slate-300">{r.description}</td>
                    <td className={`px-2 py-1 font-mono ${byCode.has(r.account) ? 'text-slate-300' : 'text-red-400'}`}>{r.account}</td>
                    <td className="px-2 py-1 text-right font-mono text-white">{r.debit}</td>
                    <td className="px-2 py-1 text-right font-mono text-white">{r.credit}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex gap-3">
          <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white text-sm" onClick={onClose}>Close</button>
          <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={doImport} disabled={busy || !rows.length}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : 'Import as Drafts'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── E-Sign / attach document modal ───────────────────────────────────────────
function SignJournalModal({ entry, onClose, onDone }: {
  entry: JournalEntry
  onClose: () => void
  onDone: () => void
}) {
  const [signature, setSignature] = useState(entry.signature || '')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const submit = async () => {
    if (!signature.trim() && !file) { toast.error('Type a signature or attach a document'); return }
    setBusy(true)
    try {
      const fd = new FormData()
      if (signature.trim()) fd.append('signature', signature.trim())
      if (file) fd.append('attachment', file)
      await accountingApi.signJournalEntry(entry.id, fd)
      toast.success('Signature / document saved')
      onDone()
    } catch { toast.error('Failed to save') }
    finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative card w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-white">E-Sign / Attach — {entry.reference}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={20} /></button>
        </div>
        <div>
          <label className="text-xs text-slate-400 mb-1 block">Signature (type your full name)</label>
          <input className="input" placeholder="e.g. Jane Doe" value={signature} onChange={(e) => setSignature(e.target.value)} />
        </div>
        <div>
          <label className="text-xs text-slate-400 mb-1 block">Supporting Document (optional)</label>
          <input ref={fileRef} type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="hidden" />
          <button onClick={() => fileRef.current?.click()} className="btn-ghost flex items-center gap-2 text-sm w-full justify-center">
            <Upload size={14} /> {file ? file.name : 'Choose file…'}
          </button>
          {entry.attachment && !file && <p className="text-[11px] text-slate-500 mt-1">A document is already attached.</p>}
        </div>
        <div className="flex gap-3">
          <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white text-sm" onClick={onClose}>Cancel</button>
          <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={submit} disabled={busy}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
