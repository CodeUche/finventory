import { useEffect, useState } from 'react'
import { confirmDialog } from '@/lib/dialog'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, X, Receipt, Loader2, Search, Trash2, Edit2, Folder, RefreshCw } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import SortSelect from '@/components/SortSelect'
import YearFilter, { yearToDateParams } from '@/components/YearFilter'
import MonthFilter, { monthToDateParams, type ArchiveMonth } from '@/components/MonthFilter'
import ExportButton from '@/components/ExportButton'
import toast from 'react-hot-toast'
import { billApi, supplierApi, taxApi, bypassNextGets } from '@/services/api'
import { formatCurrency, formatDate, normalizeAmountStr, stripCommas } from '@/lib/utils'
import { EXPENSE_CATEGORIES } from '@/lib/categories'
import AmountInput from '@/components/AmountInput'
import type { Bill } from '@/types'
import DateInput from '@/components/DateInput'
import { FieldTooltip } from '@/components/FieldTooltip'
import { usePagination } from '@/hooks/usePagination'
import Pagination from '@/components/Pagination'

interface Supplier { id: string; name: string }
interface TaxClassOption { id: string; name: string; rate: string }
interface BillFolderOption { id: string; name: string }

const STATUS_BADGE: Record<string, string> = {
  draft: 'badge-slate',
  received: 'badge-yellow',
  approved: 'badge-orange',
  paid: 'badge-green',
  partially_paid: 'badge-blue',
  overdue: 'badge-red',
  voided: 'badge-slate',
}

interface BillLineForm { description: string; quantity: string; unit_cost: string; category_label: string; capitalise: boolean }
const BLANK_LINE: BillLineForm = { description: '', quantity: '1', unit_cost: '', category_label: '', capitalise: false }

interface BillForm {
  supplier: string
  customVendor: string
  folder: string
  reference: string
  issue_date: string
  due_date: string
  tax_percent: string
  tax_class_id: string
  notes: string
  status: string
}

interface PayForm {
  amount: string
  payment_date: string
  method: string
  reference: string
  notes: string
}

const today = new Date().toISOString().split('T')[0]
const inThirtyDays = new Date(Date.now() + 30 * 86400000).toISOString().split('T')[0]

const BLANK_BILL: BillForm = { supplier: '', customVendor: '', folder: '', reference: '', issue_date: today, due_date: inThirtyDays, tax_percent: '0', tax_class_id: '', notes: '', status: 'draft' }
const BLANK_PAY: PayForm = { amount: '', payment_date: today, method: 'cash', reference: '', notes: '' }

function agingBucket(dueDate: string): '0-30' | '31-60' | '61-90' | '90+' {
  const days = Math.floor((Date.now() - new Date(dueDate).getTime()) / 86400000)
  if (days <= 30) return '0-30'
  if (days <= 60) return '31-60'
  if (days <= 90) return '61-90'
  return '90+'
}

export default function BillsPage() {
  const [searchParams, setSearchParams] = useSearchParams()

  const [bills, setBills] = useState<Bill[]>([])
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [taxClasses, setTaxClasses] = useState<TaxClassOption[]>([])
  const [billFolders, setBillFolders] = useState<BillFolderOption[]>([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState('')
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState('-created_at')
  const [archiveYear, setArchiveYear] = useState<number | null>(null)
  const [archiveMonth, setArchiveMonth] = useState<ArchiveMonth | null>(null)
  const activeDateParams = archiveMonth ? monthToDateParams(archiveMonth) : yearToDateParams(archiveYear)
  const handleYearChange = (y: number | null) => { setArchiveYear(y); if (y !== null) setArchiveMonth(null) }
  const handleMonthChange = (m: ArchiveMonth | null) => { setArchiveMonth(m); if (m !== null) setArchiveYear(null) }

  const [showModal, setShowModal] = useState(false)
  const [editingBillId, setEditingBillId] = useState<string | null>(null)
  const [form, setForm] = useState<BillForm>(BLANK_BILL)
  const [lines, setLines] = useState<BillLineForm[]>([{ ...BLANK_LINE }])
  const [saving, setSaving] = useState(false)

  const [payBillId, setPayBillId] = useState<string | null>(null)
  const [payForm, setPayForm] = useState<PayForm>(BLANK_PAY)
  const [paying, setPaying] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = { ...activeDateParams }
      if (statusFilter) params.status = statusFilter
      if (search) params.search = search
      if (sortBy) params.ordering = sortBy
      const [bRes, sRes, tRes, fRes] = await Promise.all([
        billApi.list({ ...params, page_size: 5000 }),
        supplierApi.list(),
        taxApi.classes(),
        billApi.folders(),
      ])
      setBills(bRes.data.results ?? bRes.data)
      setSuppliers(sRes.data.results ?? sRes.data)
      setTaxClasses(tRes.data.results ?? tRes.data)
      setBillFolders(fRes.data.results ?? fRes.data)
    } catch { toast.error('Failed to load bills') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [statusFilter, search, sortBy, archiveYear, archiveMonth])
  useDataRefresh(load)

  // Auto-open new bill modal when navigated from folder page with ?openNew=1&folder=<id>
  useEffect(() => {
    if (searchParams.get('openNew') === '1' && billFolders.length > 0) {
      const folderId = searchParams.get('folder') ?? ''
      setEditingBillId(null)
      setForm({ ...BLANK_BILL, folder: folderId })
      setLines([{ ...BLANK_LINE }])
      setShowModal(true)
      // Remove params from URL so modal doesn't re-open on refresh
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, billFolders])

  // Compute line subtotal
  const lineSubtotal = lines.reduce((s, l) => {
    const qty = parseFloat(l.quantity) || 0
    const cost = parseFloat(stripCommas(l.unit_cost)) || 0
    return s + qty * cost
  }, 0)

  // Tax percent from selected class or manual entry
  const resolvedTaxPercent = parseFloat(form.tax_percent) || 0
  const computedTaxAmount = lineSubtotal * resolvedTaxPercent / 100

  const handleTaxClassChange = (classId: string) => {
    const tc = taxClasses.find((t) => t.id === classId)
    setForm((f) => ({
      ...f,
      tax_class_id: classId,
      tax_percent: tc ? tc.rate : f.tax_percent,
    }))
  }

  const openCreate = () => {
    setEditingBillId(null)
    setForm(BLANK_BILL)
    setLines([{ ...BLANK_LINE }])
    setShowModal(true)
  }

  // Deep-link from Dashboard Quick Actions: /bills?new=1 opens the New Bill modal.
  useEffect(() => {
    if (searchParams.get('new') === '1') {
      openCreate()
      searchParams.delete('new')
      setSearchParams(searchParams, { replace: true })
    }
  }, [])

  const openEdit = (b: Bill) => {
    setEditingBillId(b.id)
    const subtotal = parseFloat((b as any).subtotal ?? '0')
    const taxAmount = parseFloat(b.tax_amount ?? '0')
    const effectiveTaxPct = subtotal > 0 ? ((taxAmount / subtotal) * 100).toFixed(2) : '0'
    setForm({
      supplier: (b as any).supplier ?? '',
      customVendor: '',
      folder: (b as any).folder ?? '',
      reference: b.reference ?? '',
      issue_date: b.issue_date,
      due_date: b.due_date,
      tax_percent: effectiveTaxPct,
      tax_class_id: '',
      notes: (b as any).notes ?? '',
      status: b.status,
    })
    const existingItems: typeof BLANK_LINE[] = ((b as any).items ?? []).map((item: any) => ({
      description: item.description ?? '',
      quantity: String(item.quantity ?? '1'),
      unit_cost: normalizeAmountStr(String(item.unit_cost ?? '')),
      category_label: item.expense_category_name ?? '',
      capitalise: Boolean(item.capitalise),
    }))
    setLines(existingItems.length > 0 ? existingItems : [{ ...BLANK_LINE }])
    setShowModal(true)
  }

  const handleSave = async () => {
    if (!form.supplier) { toast.error('Select a vendor'); return }
    if (form.supplier === 'other' && !form.customVendor.trim()) { toast.error('Enter vendor name'); return }
    if (lines.some((l) => !l.description || !l.unit_cost)) { toast.error('Fill all line items'); return }
    setSaving(true)
    try {
      const payload = {
        supplier: form.supplier !== 'other' ? form.supplier : null,
        vendor_name: form.supplier === 'other' ? form.customVendor.trim() : undefined,
        folder: form.folder || null,
        reference: form.reference,
        issue_date: form.issue_date,
        due_date: form.due_date,
        tax_amount: computedTaxAmount,
        notes: form.notes,
        status: form.status,
        items: lines.map((l) => ({
          description: l.description,
          quantity: parseFloat(l.quantity) || 1,
          unit_cost: parseFloat(stripCommas(l.unit_cost)) || 0,
          ...(l.category_label ? { category_label: l.category_label } : {}),
          ...(l.capitalise ? { capitalise: true } : {}),
        })),
      }
      if (editingBillId) {
        await billApi.update(editingBillId, payload)
        toast.success('Bill updated')
      } else {
        await billApi.create(payload)
        toast.success('Bill created')
      }
      setShowModal(false)
      setForm(BLANK_BILL)
      setLines([{ ...BLANK_LINE }])
      load()
    } catch (err: unknown) {
      const apiErr = (err as { response?: { data?: { error?: { message?: string } | string } } })?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? (editingBillId ? 'Failed to update bill' : 'Failed to create bill'))
      toast.error(msg)
    }
    finally { setSaving(false) }
  }

  const handleApprove = async (id: string) => {
    try { await billApi.approve(id); toast.success('Bill approved'); load() }
    catch { toast.error('Failed to approve bill') }
  }

  const handleVoid = async (id: string) => {
    if (!(await confirmDialog('Void this bill?'))) return
    try { await billApi.void(id); toast.success('Bill voided'); load() }
    catch { toast.error('Failed to void bill') }
  }

  const handlePay = async () => {
    if (!payBillId || !payForm.amount) { toast.error('Enter amount'); return }
    setPaying(true)
    try {
      await billApi.pay(payBillId, { ...payForm, amount: parseFloat(stripCommas(payForm.amount)) })
      toast.success('Payment recorded')
      setPayBillId(null)
      setPayForm(BLANK_PAY)
      load()
    } catch { toast.error('Failed to record payment') }
    finally { setPaying(false) }
  }

  const updateLine = (i: number, field: keyof BillLineForm, value: string) => {
    setLines(lines.map((l, idx) => {
      if (idx !== i) return l
      const updated = { ...l, [field]: value }
      // Auto-fill description from category label when selected and description is empty
      if (field === 'category_label' && value && !l.description) {
        updated.description = value
      }
      return updated
    }))
  }

  const toggleCapitalise = (i: number) => {
    setLines(lines.map((l, idx) => (idx === i ? { ...l, capitalise: !l.capitalise } : l)))
  }

  // Summary
  const totalPayable = bills.filter((b) => b.status !== 'voided' && b.status !== 'paid').reduce((s, b) => s + parseFloat(b.amount_due), 0)
  const overdue = bills.filter((b) => b.status === 'overdue').reduce((s, b) => s + parseFloat(b.amount_due), 0)
  const now = new Date()
  const nextWeek = new Date(Date.now() + 7 * 86400000)
  const dueThisWeek = bills.filter((b) => {
    const d = new Date(b.due_date)
    return d >= now && d <= nextWeek && b.status !== 'paid' && b.status !== 'voided'
  }).reduce((s, b) => s + parseFloat(b.amount_due), 0)
  const paidThisMonth = bills.filter((b) => {
    const d = new Date(b.issue_date)
    return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear() && b.status === 'paid'
  }).reduce((s, b) => s + parseFloat(b.total_amount), 0)

  // AP Aging
  const unpaid = bills.filter((b) => b.status !== 'paid' && b.status !== 'voided' && b.status !== 'draft')
  const aging: Record<string, number> = { '0-30': 0, '31-60': 0, '61-90': 0, '90+': 0 }
  unpaid.forEach((b) => { aging[agingBucket(b.due_date)] += parseFloat(b.amount_due) })

  const summaryTiles = [
    { label: 'Total Payable', value: totalPayable, color: 'text-white', filter: '', hint: '' },
    { label: 'Overdue', value: overdue, color: 'text-red-400', filter: 'overdue', hint: 'Click to filter' },
    { label: 'Due This Week', value: dueThisWeek, color: 'text-orange-400', filter: 'approved', hint: 'Click to filter' },
    { label: 'Paid This Month', value: paidThisMonth, color: 'text-emerald-400', filter: 'paid', hint: 'Click to filter' },
  ]
  const { page, setPage, pageSize, setPageSize, totalPages, paged, total } = usePagination(bills)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Bills (Accounts Payable)</h1>
          <p className="text-slate-400 text-sm">{total} total bills</p>
        </div>
        <div className="flex items-center gap-2 sm:ml-auto">
          <button onClick={() => { bypassNextGets(); load() }} disabled={loading} className="btn-ghost p-2 text-slate-400 hover:text-white" title="Refresh">
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <Link to="/bills/folders" className="btn-secondary flex items-center gap-2">
            <Folder size={15} /> Folders
          </Link>
          <button className="btn-primary" onClick={openCreate}>
            <Plus size={16} /> New Bill
          </button>
        </div>
      </div>

      {/* Summary cards — clickable to filter */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {summaryTiles.map((t) => (
          <button
            key={t.label}
            onClick={() => t.filter ? setStatusFilter(statusFilter === t.filter ? '' : t.filter) : undefined}
            className={`card p-5 text-left transition-all ${t.filter ? 'cursor-pointer hover:border-brand-500/40' : 'cursor-default'} ${statusFilter === t.filter && t.filter ? 'ring-2 ring-brand-500' : ''}`}
          >
            <p className="text-xs text-slate-400">{t.label}</p>
            <p className={`text-xl font-bold mt-1 ${t.color}`}>{formatCurrency(t.value)}</p>
            {t.hint && <p className="text-xs text-slate-600 mt-0.5">{t.hint}</p>}
          </button>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input className="input pl-9" placeholder="Search supplier…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <SortSelect
          value={sortBy}
          onChange={setSortBy}
          options={[
            { label: 'Newest first', value: '-created_at' },
            { label: 'Oldest first', value: 'created_at' },
            { label: 'Amount ↓', value: '-total_amount' },
            { label: 'Amount ↑', value: 'total_amount' },
            { label: 'Due date ↑', value: 'due_date' },
          ]}
        />
        <select className="input max-w-xs" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All Statuses</option>
          {['draft', 'received', 'approved', 'paid', 'partially_paid', 'overdue', 'voided'].map((s) => (
            <option key={s} value={s}>{s.replace('_', ' ')}</option>
          ))}
        </select>
        {statusFilter && (
          <button onClick={() => setStatusFilter('')} className="btn-ghost text-sm px-3">
            <X size={14} /> Clear
          </button>
        )}
        <YearFilter selectedYear={archiveYear} onChange={handleYearChange} />
        <MonthFilter selectedMonth={archiveMonth} onChange={handleMonthChange} />
        <ExportButton endpoint="/bills/" filename="bills" params={activeDateParams} />
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Bill #', 'Supplier', 'Ref', 'Issue Date', 'Due Date', 'Total', 'Paid', 'Due', 'Status', 'Actions'].map((h) => (
                  <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 10 }).map((_, j) => (
                      <td key={j} className="px-4 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-16" /></td>
                    ))}
                  </tr>
                ))
              ) : total === 0 ? (
                <tr>
                  <td colSpan={10} className="px-4 py-12 text-center">
                    <Receipt size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No bills found</p>
                  </td>
                </tr>
              ) : paged.map((b) => (
                <tr key={b.id} className="table-row">
                  <td className="px-4 py-3.5 font-mono text-brand-400">{b.bill_number}</td>
                  <td className="px-4 py-3.5 text-slate-300">
                    {b.supplier_name}
                    {(b as any).folder_name && (
                      <p className="text-xs text-slate-500 flex items-center gap-1 mt-0.5">
                        <Folder size={10} />{(b as any).folder_name}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3.5 text-slate-400">
                    {b.reference || '—'}
                    {b.source_po_number && (
                      <p className="text-[10px] text-brand-400 mt-0.5" title="Auto-created from this Purchase Order — a reliable link, unlike Reference which is free text">
                        Linked PO: {b.source_po_number}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3.5 text-slate-400">{formatDate(b.issue_date)}</td>
                  <td className="px-4 py-3.5 text-slate-400">{formatDate(b.due_date)}</td>
                  <td className="px-4 py-3.5 text-white font-semibold">{formatCurrency(b.total_amount)}</td>
                  <td className="px-4 py-3.5 text-emerald-400">{formatCurrency(b.amount_paid)}</td>
                  <td className="px-4 py-3.5 text-red-400">{formatCurrency(b.amount_due)}</td>
                  <td className="px-4 py-3.5"><span className={STATUS_BADGE[b.status] ?? 'badge-slate'}>{b.status.replace('_', ' ')}</span></td>
                  <td className="px-4 py-3.5">
                    <div className="flex items-center gap-1.5">
                      {(b.status === 'draft' || b.status === 'received') && (
                        <button onClick={() => openEdit(b)} className="p-1 text-slate-500 hover:text-white transition-colors" title="Edit bill">
                          <Edit2 size={13} />
                        </button>
                      )}
                      {b.status === 'received' && (
                        <button onClick={() => handleApprove(b.id)} className="text-xs px-2.5 py-1 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 transition-colors">Approve</button>
                      )}
                      {(b.status === 'approved' || b.status === 'partially_paid' || b.status === 'overdue') && (
                        <button onClick={() => { setPayBillId(b.id); setPayForm({ ...BLANK_PAY, amount: normalizeAmountStr(b.amount_due) }) }} className="text-xs px-2.5 py-1 rounded-lg bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors">Pay</button>
                      )}
                      {b.status !== 'voided' && b.status !== 'paid' && (
                        <button onClick={() => handleVoid(b.id)} className="p-1 text-slate-500 hover:text-red-400 transition-colors"><Trash2 size={13} /></button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pagination page={page} totalPages={totalPages} pageSize={pageSize} total={total}
          onPage={setPage} onPageSize={setPageSize} />
      </div>

      {/* AP Aging */}
      <div className="card p-6">
        <h3 className="text-white font-semibold mb-4">AP Aging Analysis</h3>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {(['0-30', '31-60', '61-90', '90+'] as const).map((bucket, i) => (
            <div key={bucket} className={`p-4 rounded-xl border ${i === 0 ? 'border-emerald-500/30 bg-emerald-500/5' : i === 1 ? 'border-yellow-500/30 bg-yellow-500/5' : i === 2 ? 'border-orange-500/30 bg-orange-500/5' : 'border-red-500/30 bg-red-500/5'}`}>
              <p className="text-xs text-slate-400">{bucket} days</p>
              <p className={`text-lg font-bold mt-1 ${i === 0 ? 'text-emerald-400' : i === 1 ? 'text-yellow-400' : i === 2 ? 'text-orange-400' : 'text-red-400'}`}>
                {formatCurrency(aging[bucket])}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* New / Edit Bill Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative card w-full max-w-2xl p-6 space-y-5 overflow-y-auto max-h-[90vh]">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">{editingBillId ? 'Edit Bill' : 'New Bill'}</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Vendor *<FieldTooltip text="The supplier or company who sent you this bill. Select from your suppliers list, or enter a custom name." /></label>
                <select className="input" value={form.supplier} onChange={(e) => setForm({ ...form, supplier: e.target.value, customVendor: '' })}>
                  <option value="">— Select Vendor —</option>
                  <option value="other">Other / Custom Vendor</option>
                  {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
                {form.supplier === 'other' && (
                  <input
                    className="input mt-2"
                    placeholder="Enter vendor / supplier name"
                    value={form.customVendor}
                    onChange={(e) => setForm({ ...form, customVendor: e.target.value })}
                    autoFocus
                  />
                )}
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Reference<FieldTooltip text="The invoice number printed on the supplier's document. Write it here to match your records to theirs — useful if there's ever a dispute." /></label>
                <input className="input" placeholder="Invoice/PO ref" value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Issue Date<FieldTooltip text="The date printed on the supplier's invoice — when they say they raised the bill." /></label>
                <DateInput value={form.issue_date} onChange={(v) => setForm({ ...form, issue_date: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Due Date<FieldTooltip text="The deadline by which you must pay this bill. The app will flag overdue bills automatically." /></label>
                <DateInput value={form.due_date} onChange={(v) => setForm({ ...form, due_date: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Folder (optional)<FieldTooltip text="Organise bills into folders for easier management — e.g. 'Utilities', 'Rent', 'Suppliers'." /></label>
                <select className="input" value={form.folder} onChange={(e) => setForm({ ...form, folder: e.target.value })}>
                  <option value="">— No folder —</option>
                  {billFolders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Bill Status<FieldTooltip text="Draft = you haven't received the physical bill yet. Received = bill is in hand. Approved = authorised for payment." /></label>
                <select className="input" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  <option value="draft">Draft</option>
                  <option value="received">Received</option>
                  <option value="approved">Approved</option>
                </select>
              </div>

              {/* Smart Tax Field */}
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Tax Class or Rate %<FieldTooltip text="The VAT or tax charged by the supplier. Select a tax class or enter a percentage manually — e.g. 7.5 for 7.5% VAT." /></label>
                <div className="flex gap-2">
                  <select
                    className="input flex-1 text-sm"
                    value={form.tax_class_id}
                    onChange={(e) => handleTaxClassChange(e.target.value)}
                  >
                    <option value="">— Tax Class —</option>
                    {taxClasses.map((t) => (
                      <option key={t.id} value={t.id}>{t.name} ({parseFloat(t.rate).toFixed(1)}%)</option>
                    ))}
                  </select>
                  <div className="relative w-24 shrink-0">
                    <input
                      type="text" inputMode="decimal" className="input pr-6 text-sm" placeholder="0"
                      value={form.tax_percent}
                      onChange={(e) => setForm({ ...form, tax_percent: e.target.value, tax_class_id: '' })}
                    />
                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 text-xs">%</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Line Items */}
            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Line Items</p>
              {/* Column headers */}
              <div className="grid grid-cols-12 gap-2 px-3 mb-1">
                <div className="col-span-5 text-xs text-slate-500 flex items-center gap-1">Category <FieldTooltip text="What type of expense this bill is for — e.g. Rent, Utilities, Supplies. Used in reports." /></div>
                <div className="col-span-2 text-xs text-slate-500">Qty</div>
                <div className="col-span-4 text-xs text-slate-500 flex items-center gap-1">Unit Cost <FieldTooltip text="The total amount before tax on this bill line. Multiply by quantity to get the line subtotal." /></div>
              </div>
              <div className="space-y-3">
                {lines.map((line, i) => (
                  <div key={i} className="bg-surface-900/40 rounded-xl p-3 space-y-2">
                    <div className="grid grid-cols-12 gap-2 items-center">
                      <div className="col-span-5">
                        <select
                          className="input py-1.5 text-sm"
                          value={line.category_label}
                          onChange={(e) => updateLine(i, 'category_label', e.target.value)}
                        >
                          <option value="">— Category (optional) —</option>
                          {EXPENSE_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </div>
                      <div className="col-span-2">
                        <input type="number" min="1" className="input py-1.5 text-sm" placeholder="Qty" value={line.quantity} onChange={(e) => updateLine(i, 'quantity', e.target.value)} />
                      </div>
                      <div className="col-span-4">
                        <AmountInput className="input py-1.5 text-sm" placeholder="Unit Cost" value={line.unit_cost} onChange={(v) => updateLine(i, 'unit_cost', v)} />
                      </div>
                      <div className="col-span-1 flex justify-center">
                        <button onClick={() => setLines(lines.filter((_, idx) => idx !== i))} className="p-1 text-slate-500 hover:text-red-400 transition-colors"><Trash2 size={14} /></button>
                      </div>
                    </div>
                    <div className="text-xs text-slate-500 flex items-center gap-1 px-0.5 -mb-1">Description <FieldTooltip text="A short note about what this bill line is for. Helps you identify it later." /></div>
                    <input
                      className="input py-1.5 text-sm"
                      placeholder="Description"
                      value={line.description}
                      onChange={(e) => updateLine(i, 'description', e.target.value)}
                    />
                    <label className="mt-1.5 flex items-center gap-2 text-xs text-slate-400 cursor-pointer select-none">
                      <input type="checkbox" className="accent-brand-500" checked={line.capitalise} onChange={() => toggleCapitalise(i)} />
                      Capitalise as fixed asset
                      <FieldTooltip text="Books this line to Fixed Assets (1500) instead of an expense and creates an asset record on approval." />
                    </label>
                  </div>
                ))}
              </div>
              <button onClick={() => setLines([...lines, { ...BLANK_LINE }])} className="btn-ghost text-sm mt-2 flex items-center gap-1">
                <Plus size={13} /> Add Line
              </button>
            </div>

            {/* Totals summary */}
            {lineSubtotal > 0 && (
              <div className="text-sm space-y-1 border-t border-surface-700 pt-3">
                <div className="flex justify-between text-slate-400">
                  <span>Subtotal</span><span className="font-mono">{formatCurrency(lineSubtotal)}</span>
                </div>
                {resolvedTaxPercent > 0 && (
                  <div className="flex justify-between text-slate-400">
                    <span>Tax ({resolvedTaxPercent}%)</span><span className="font-mono">{formatCurrency(computedTaxAmount)}</span>
                  </div>
                )}
                <div className="flex justify-between text-white font-semibold border-t border-surface-700 pt-1">
                  <span>Total</span><span className="font-mono">{formatCurrency(lineSubtotal + computedTaxAmount)}</span>
                </div>
              </div>
            )}

            <div>
              <label className="text-xs text-slate-400 mb-1 block">Notes<FieldTooltip text="Any extra details about this bill — e.g. payment instructions, delivery terms, or dispute notes." /></label>
              <textarea className="input resize-none" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            </div>

            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleSave} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : (editingBillId ? 'Update Bill' : 'Create Bill')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Record Payment Modal */}
      {payBillId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setPayBillId(null)} />
          <div className="relative card w-full max-w-md p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Record Payment</h2>
              <button onClick={() => setPayBillId(null)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Amount *</label>
                <AmountInput className="input" value={payForm.amount} onChange={(v) => setPayForm({ ...payForm, amount: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Date</label>
                <DateInput value={payForm.payment_date} onChange={(v) => setPayForm({ ...payForm, payment_date: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Method</label>
                <select className="input" value={payForm.method} onChange={(e) => setPayForm({ ...payForm, method: e.target.value })}>
                  {[{ v: 'cash', l: 'Cash' }, { v: 'bank_transfer', l: 'Bank Transfer' }, { v: 'cheque', l: 'Cheque' }, { v: 'pos', l: 'POS' }].map(({ v, l }) => <option key={v} value={v}>{l}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Reference</label>
                <input className="input" value={payForm.reference} onChange={(e) => setPayForm({ ...payForm, reference: e.target.value })} />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Notes</label>
                <input className="input" value={payForm.notes} onChange={(e) => setPayForm({ ...payForm, notes: e.target.value })} />
              </div>
            </div>
            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setPayBillId(null)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handlePay} disabled={paying}>
                {paying ? <Loader2 size={16} className="animate-spin" /> : 'Record Payment'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
