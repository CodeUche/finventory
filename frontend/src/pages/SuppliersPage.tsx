import { useEffect, useState } from 'react'
import { confirmDialog } from '@/lib/dialog'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, Search, Truck, X, Pencil, Loader2, Trash2, FileText, Download, Scale } from 'lucide-react'
import toast from 'react-hot-toast'
import { supplierApi, bypassNextGets } from '@/services/api'
import { usePagination } from '@/hooks/usePagination'
import Pagination from '@/components/Pagination'
import GLAccountSelect from '@/components/GLAccountSelect'
import AdjustOpeningBalanceModal from '@/components/AdjustOpeningBalanceModal'
import DateInput from '@/components/DateInput'
import AmountInput from '@/components/AmountInput'
import { formatCurrency, formatDate } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import { saveBlobFile } from '@/lib/saveBlobFile'

interface Supplier {
  id: string
  code: string
  name: string
  contact_person: string
  email: string
  phone: string
  address: string
  tax_id: string
  payment_terms_days: number
  notes: string
  payable_account?: string | null
  opening_balance?: string
  opening_balance_date?: string | null
  is_active: boolean
}

const BLANK = {
  name: '',
  contact_person: '',
  email: '',
  phone: '',
  address: '',
  tax_id: '',
  payment_terms_days: '30',
  notes: '',
  payable_account: '',
}

// A blank GL override means "use the organisation default" — send null, not "".
const toPayload = (f: typeof BLANK) => ({ ...f, payable_account: f.payable_account || null })

export default function SuppliersPage() {
  const { organisation } = useAuthStore()
  const [suppliers, setSuppliers] = useState<Supplier[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  const [showModal, setShowModal] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState({ ...BLANK })
  const [saving, setSaving] = useState(false)

  // Opening balance — only captured at creation time; adjusting it later goes
  // through the dedicated "Adjust Opening Balance" action (GL-safe, keeps the
  // ledger in sync — a raw PATCH to opening_balance is intentionally blocked).
  const todayIso = new Date().toISOString().split('T')[0]
  const [obAmount, setObAmount] = useState('')
  const [obDate, setObDate] = useState(todayIso)
  const [obSide, setObSide] = useState<'debit' | 'credit'>('credit')

  const [balanceParty, setBalanceParty] = useState<Supplier | null>(null)

  const [showStatement, setShowStatement] = useState(false)
  const [selected, setSelected] = useState<Supplier | null>(null)
  const [statementData, setStatementData] = useState<any>(null)
  const [loadingStmt, setLoadingStmt] = useState(false)
  const today = new Date().toISOString().split('T')[0]
  const [stmtFrom, setStmtFrom] = useState(`${today.slice(0, 8)}01`)
  const [stmtTo, setStmtTo] = useState(today)

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await supplierApi.list({ search: search || undefined, page_size: 5000 })
      setSuppliers(data.results ?? data)
    } catch {
      toast.error('Failed to load suppliers')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [search])
  useDataRefresh(load)

  const openCreate = () => {
    setEditId(null)
    setForm({ ...BLANK })
    setObAmount('')
    setObDate(todayIso)
    setObSide('credit')
    setShowModal(true)
  }

  const openEdit = (s: Supplier) => {
    setEditId(s.id)
    setForm({
      name: s.name,
      contact_person: s.contact_person ?? '',
      email: s.email ?? '',
      phone: s.phone ?? '',
      address: s.address ?? '',
      tax_id: s.tax_id ?? '',
      payment_terms_days: String(s.payment_terms_days ?? 30),
      notes: s.notes ?? '',
      payable_account: s.payable_account ?? '',
    })
    setShowModal(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) { toast.error('Supplier name is required'); return }
    setSaving(true)
    try {
      if (editId) {
        await supplierApi.update(editId, toPayload(form))
        toast.success('Supplier updated')
      } else {
        const { data: created } = await supplierApi.create(toPayload(form))
        const amt = parseFloat(obAmount.replace(/,/g, '')) || 0
        if (amt > 0) {
          await supplierApi.setOpeningBalance(created.id, { amount: amt, side: obSide, as_of_date: obDate })
        }
        toast.success('Supplier added')
      }
      setShowModal(false)
      // set-opening-balance is POST /suppliers/<id>/set-opening-balance/ — the
      // action-endpoint cache invalidation only strips one trailing segment,
      // landing on the item URL rather than the list URL, so the list GET
      // right below would otherwise still serve the pre-update cached list.
      bypassNextGets()
      load()
    } catch {
      toast.error(editId ? 'Failed to update supplier' : 'Failed to create supplier')
    } finally {
      setSaving(false)
    }
  }

  const upd = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  const openStatement = (s: Supplier) => {
    setSelected(s)
    setStatementData(null)
    setShowStatement(true)
    loadStatement(s.id)
  }

  const loadStatement = async (id: string, from = stmtFrom, to = stmtTo) => {
    setLoadingStmt(true)
    try {
      const { data } = await supplierApi.statement(id, { date_from: from, date_to: to })
      setStatementData(data)
    } catch { toast.error('Failed to load statement') }
    finally { setLoadingStmt(false) }
  }

  const downloadStatementPDF = async () => {
    if (!statementData || !selected) return
    const { jsPDF } = await import('jspdf')
    const { default: autoTable } = await import('jspdf-autotable')
    const { applyDocHeader, buildTableStyle, addDocFooter, pdfMoney, COLORS, TYPE, resolveOrgLogo } = await import('@/lib/pdfUtils')

    const doc = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'landscape' })
    doc.setLineHeightFactor(1.15)
    const pageW = doc.internal.pageSize.getWidth()

    const toRgb = (hex?: string): [number, number, number] => {
      const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
      if (!m) return [249, 115, 22]
      return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
    }
    const BRAND = toRgb(organisation?.brand_color) as [number, number, number]
    const DARK = COLORS.DARK
    const MUTED = COLORS.MUTED
    const LIGHT = COLORS.LIGHT
    const RULE = COLORS.RULE
    const tmpl = organisation?.invoice_template ?? 'classic'
    const logoData: string | null = await resolveOrgLogo(organisation?.logo)
    const pdfFont = 'helvetica'
    const displayName = organisation?.show_company_name_on_pdf === false
      ? '' : (organisation?.invoice_company_name?.trim() || organisation?.name || 'Audity')

    let y = applyDocHeader(doc, {
      tmpl, pageW, BRAND, DARK, MUTED,
      landscape: true,
      logoData,
      displayName,
      orgAddress: organisation?.address,
      orgEmail: organisation?.email,
      orgPhone: organisation?.phone,
      pdfFont,
      fontSize: 12,
      pdfStyle: 'bold',
      nameColor: (tmpl === 'modern' || tmpl === 'minimal') ? DARK : COLORS.WHITE,
      showCompanyName: organisation?.show_company_name_on_pdf !== false,
      docTitle: 'SUPPLIER STATEMENT',
      metaRows: [
        ['Supplier', selected.name],
        ['Ref', selected.code],
        ['Period', `${formatDate(stmtFrom)} – ${formatDate(stmtTo)}`],
        ['Generated', formatDate(new Date().toISOString().split('T')[0])],
      ],
    })

    const fmtMoney = pdfMoney
    const kpis = [
      { label: 'Total Billed', value: fmtMoney(parseFloat(statementData.summary.total_billed)), color: DARK },
      { label: 'Total Paid', value: fmtMoney(parseFloat(statementData.summary.total_paid)), color: COLORS.GREEN },
      { label: 'Balance Due', value: fmtMoney(parseFloat(statementData.summary.balance_due)),
        color: parseFloat(statementData.summary.balance_due) > 0 ? COLORS.RED : COLORS.GREEN },
    ] as const
    const kpiW = (pageW - 20) / 3
    kpis.forEach((k, i) => {
      const kx = 10 + i * kpiW
      doc.setFillColor(...LIGHT); doc.setDrawColor(...RULE); doc.setLineWidth(0.25)
      doc.roundedRect(kx, y, kpiW - 2, 22, 2, 2, 'FD')
      doc.setFontSize(TYPE.SMALL.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
      doc.text(k.label.toUpperCase(), kx + (kpiW - 2) / 2, y + 7, { align: 'center' })
      doc.setFontSize(TYPE.H2.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...k.color)
      doc.text(k.value, kx + (kpiW - 2) / 2, y + 16, { align: 'center' })
    })
    y += 26

    type Evt = { date: string; type: 'bill' | 'payment' | 'return'; data: any }
    const events: Evt[] = []
    for (const b of statementData.bills) events.push({ date: b.issue_date, type: 'bill', data: b })
    for (const p of statementData.payments) events.push({ date: p.payment_date, type: 'payment', data: p })
    for (const r of (statementData.returns ?? [])) events.push({ date: r.return_date, type: 'return', data: r })
    events.sort((a, b) => a.date.localeCompare(b.date))

    type Row = [string, string, string, string, string, string]
    const ledger: Row[] = []
    const debitRowIndices: number[] = []
    const creditRowIndices: number[] = []
    let runBalance = 0
    for (const e of events) {
      if (e.type === 'bill') {
        const b = e.data
        runBalance += parseFloat(b.total_amount)
        debitRowIndices.push(ledger.length)
        ledger.push([formatDate(e.date), b.bill_number, `Bill · ${b.status.replace('_', ' ')}`,
          fmtMoney(parseFloat(b.total_amount)), '', fmtMoney(runBalance)])
      } else if (e.type === 'payment') {
        const p = e.data
        runBalance -= parseFloat(p.amount)
        creditRowIndices.push(ledger.length)
        ledger.push([formatDate(e.date), p.bill_number || p.reference || '—', `Payment · ${p.method.replace('_', ' ')}`,
          '', fmtMoney(parseFloat(p.amount)), fmtMoney(runBalance)])
      } else {
        const r = e.data
        runBalance -= parseFloat(r.amount)
        creditRowIndices.push(ledger.length)
        ledger.push([formatDate(e.date), r.return_number, `Return · ${r.reason || 'goods returned'}`,
          '', fmtMoney(parseFloat(r.amount)), fmtMoney(runBalance)])
      }
    }
    ledger.push(['', '', 'GRAND TOTAL',
      fmtMoney(parseFloat(statementData.summary.total_billed)),
      fmtMoney(parseFloat(statementData.summary.total_paid) + parseFloat(statementData.summary.total_returns)),
      fmtMoney(parseFloat(statementData.summary.balance_due))])
    const grandTotalRowIndex = [ledger.length - 1]

    const ts = buildTableStyle(BRAND, pdfFont, { landscape: true })
    autoTable(doc, {
      ...ts,
      startY: y,
      head: [['Trans Date', 'Trans Ref', 'Description', 'Debit', 'Credit', 'Balance']],
      body: ledger,
      columnStyles: {
        0: { cellWidth: 30 },
        1: { cellWidth: 40, fontStyle: 'bold' as const },
        2: { cellWidth: 60 },
        3: { halign: 'right' as const, cellWidth: 40 },
        4: { halign: 'right' as const, cellWidth: 40 },
        5: { halign: 'right' as const, cellWidth: 45, fontStyle: 'bold' as const },
      },
      didParseCell: (data: any) => {
        if (grandTotalRowIndex.includes(data.row.index)) {
          data.cell.styles.fontStyle = 'bold'
          data.cell.styles.fillColor = LIGHT
        }
        if (data.section === 'body' && debitRowIndices.includes(data.row.index) && data.column.index === 3) {
          data.cell.styles.textColor = COLORS.RED
        }
        if (data.section === 'body' && creditRowIndices.includes(data.row.index) && data.column.index === 4) {
          data.cell.styles.textColor = COLORS.GREEN
        }
      },
    })

    addDocFooter(doc, {
      orgName: organisation?.name ?? 'Company',
      docTitle: 'SUPPLIER STATEMENT',
      docRef: `${formatDate(stmtFrom)} – ${formatDate(stmtTo)}`,
      BRAND,
      pdfFont,
      landscape: true,
    })

    await saveBlobFile(doc.output('blob'), `supplier-statement-${selected.code}-${stmtFrom}-${stmtTo}.pdf`)
  }

  const { page, setPage, pageSize, setPageSize, totalPages, paged, total } = usePagination(suppliers)

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Suppliers</h1>
          <p className="text-slate-400 text-sm">{total} supplier{total !== 1 ? 's' : ''}</p>
        </div>
        <button className="btn-primary sm:ml-auto" onClick={openCreate}>
          <Plus size={16} /> Add Supplier
        </button>
      </div>

      <div className="relative max-w-sm">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
        <input className="input pl-9" placeholder="Search by name or code…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Code', 'Name', 'Contact', 'Phone', 'Email', 'Payment Terms', ''].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 7 }).map((_, j) => (
                      <td key={j} className="px-5 py-3.5"><div className="h-4 bg-surface-700 rounded animate-pulse w-20" /></td>
                    ))}
                  </tr>
                ))
              ) : total === 0 ? (
                <tr><td colSpan={7} className="px-5 py-12 text-center">
                  <Truck size={32} className="mx-auto mb-2 text-slate-600" />
                  <p className="text-slate-500">No suppliers yet</p>
                </td></tr>
              ) : (
                paged.map((s) => (
                  <tr key={s.id} className="table-row">
                    <td className="px-5 py-3.5 font-mono text-xs text-brand-400">{s.code}</td>
                    <td className="px-5 py-3.5 font-medium text-white">{s.name}</td>
                    <td className="px-5 py-3.5 text-slate-400">{s.contact_person || '—'}</td>
                    <td className="px-5 py-3.5 text-slate-400">{s.phone || '—'}</td>
                    <td className="px-5 py-3.5 text-slate-400">{s.email || '—'}</td>
                    <td className="px-5 py-3.5 text-slate-400">
                      {s.payment_terms_days === 0 ? 'COD' : `Net ${s.payment_terms_days}d`}
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-1">
                        <button onClick={() => openStatement(s)} className="btn-ghost p-1.5 text-slate-400 hover:text-white" title="View statement">
                          <FileText size={14} />
                        </button>
                        <button onClick={() => setBalanceParty(s)} className="btn-ghost p-1.5 text-slate-400 hover:text-white" title="Adjust opening balance">
                          <Scale size={14} />
                        </button>
                        <button onClick={() => openEdit(s)} className="btn-ghost p-1.5 text-slate-400 hover:text-white">
                          <Pencil size={14} />
                        </button>
                        <button
                          onClick={async () => {
                            if (!(await confirmDialog(`Delete supplier "${s.name}"?`))) return
                            try { await supplierApi.delete(s.id); toast.success('Supplier deleted'); load() }
                            catch { toast.error('Cannot delete supplier — may have linked purchase orders') }
                          }}
                          className="btn-ghost p-1.5 text-slate-400 hover:text-red-400"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <Pagination page={page} totalPages={totalPages} pageSize={pageSize} total={total} onPage={setPage} onPageSize={setPageSize} />
      </div>

      {/* Create / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-lg shadow-2xl animate-slide-up max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-6 border-b border-surface-700">
              <h2 className="font-semibold text-white text-lg">{editId ? 'Edit Supplier' : 'New Supplier'}</h2>
              <button onClick={() => setShowModal(false)} className="btn-ghost p-1.5"><X size={18} /></button>
            </div>
            <div className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2">
                  <label className="label">Supplier Name *</label>
                  <input className="input" value={form.name} onChange={upd('name')} placeholder="e.g., ABC Distributors Ltd" />
                </div>
                <div>
                  <label className="label">Contact Person</label>
                  <input className="input" value={form.contact_person} onChange={upd('contact_person')} placeholder="Mr. John Doe" />
                </div>
                <div>
                  <label className="label">Payment Terms (days)</label>
                  <input type="number" className="input" value={form.payment_terms_days} onChange={upd('payment_terms_days')} min="0" />
                </div>
                <div>
                  <label className="label">Phone</label>
                  <input className="input" value={form.phone} onChange={upd('phone')} placeholder="+234…" />
                </div>
                <div>
                  <label className="label">Email</label>
                  <input type="email" className="input" value={form.email} onChange={upd('email')} placeholder="supplier@example.com" />
                </div>
                <div>
                  <label className="label">Tax ID / VAT Number</label>
                  <input className="input" value={form.tax_id} onChange={upd('tax_id')} />
                </div>
                <div className="col-span-2">
                  <label className="label">Address</label>
                  <textarea className="input resize-none" rows={2} value={form.address} onChange={upd('address')} />
                </div>
                <div className="col-span-2">
                  <label className="label">Notes</label>
                  <textarea className="input resize-none" rows={2} value={form.notes} onChange={upd('notes')} placeholder="Any additional notes…" />
                </div>
                <div className="col-span-2">
                  <label className="label">Payable Account</label>
                  <GLAccountSelect value={form.payable_account}
                    onChange={(v) => setForm((f) => ({ ...f, payable_account: v }))} />
                  <p className="text-[11px] text-slate-500 mt-1">
                    GL control account this supplier's balance posts to. Leave on the organisation default unless this supplier needs its own payable account.
                  </p>
                </div>
                {!editId && (
                  <>
                    <div>
                      <label className="label">Opening Balance</label>
                      <AmountInput className="input" placeholder="0.00" value={obAmount} onChange={setObAmount} />
                    </div>
                    <div>
                      <label className="label">Balance Type</label>
                      <select className="input" value={obSide} onChange={(e) => setObSide(e.target.value as 'debit' | 'credit')}>
                        <option value="credit">Credit — we owe them</option>
                        <option value="debit">Debit — we've prepaid</option>
                      </select>
                    </div>
                    <div className="col-span-2">
                      <label className="label">Opening Balance As At</label>
                      <DateInput value={obDate} onChange={setObDate} />
                    </div>
                  </>
                )}
              </div>
              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowModal(false)} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button type="button" onClick={handleSave} disabled={saving} className="btn-primary flex-1 justify-center">
                  {saving ? <Loader2 size={16} className="animate-spin" /> : (editId ? 'Save Changes' : 'Add Supplier')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Statement Modal */}
      {showStatement && selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-4xl shadow-2xl animate-slide-up max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-6 border-b border-surface-700">
              <div>
                <h2 className="font-semibold text-white text-lg">Supplier Statement</h2>
                <p className="text-slate-400 text-sm">{selected.name} · {selected.code}</p>
              </div>
              <div className="flex items-center gap-2">
                {statementData && (
                  <button onClick={downloadStatementPDF} className="btn-secondary text-xs">
                    <Download size={14} /> Export PDF
                  </button>
                )}
                <button onClick={() => setShowStatement(false)} className="btn-ghost p-1.5"><X size={18} /></button>
              </div>
            </div>
            <div className="p-6 space-y-5">
              <div className="flex flex-wrap items-end gap-3">
                <div>
                  <label className="label">From</label>
                  <input type="date" className="input" value={stmtFrom} onChange={(e) => setStmtFrom(e.target.value)} />
                </div>
                <div>
                  <label className="label">To</label>
                  <input type="date" className="input" value={stmtTo} onChange={(e) => setStmtTo(e.target.value)} />
                </div>
                <button onClick={() => loadStatement(selected.id)} className="btn-primary" disabled={loadingStmt}>
                  {loadingStmt ? <Loader2 size={16} className="animate-spin" /> : 'Apply'}
                </button>
              </div>

              {loadingStmt ? (
                <div className="py-12 text-center"><Loader2 size={24} className="animate-spin mx-auto text-slate-500" /></div>
              ) : !statementData ? null : (
                <>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {[
                      { label: 'Total Billed', value: formatCurrency(statementData.summary.total_billed), color: 'text-red-400', sub: `${statementData.bills.length} bill${statementData.bills.length !== 1 ? 's' : ''}` },
                      { label: 'VAT', value: formatCurrency(statementData.summary.total_tax ?? '0'), color: 'text-blue-400', sub: 'Input VAT on bills' },
                      { label: 'Total Paid', value: formatCurrency(statementData.summary.total_paid), color: 'text-green-400', sub: `${statementData.payments.length} payment${statementData.payments.length !== 1 ? 's' : ''}` },
                      { label: 'Outstanding', value: formatCurrency(statementData.summary.outstanding_balance), color: parseFloat(statementData.summary.outstanding_balance) > 0 ? 'text-amber-400' : 'text-green-400', sub: parseFloat(statementData.summary.outstanding_balance) > 0 ? 'Owed to supplier' : 'Settled' },
                    ].map((k) => (
                      <div key={k.label} className="rounded-xl border border-surface-700 bg-surface-900/40 p-3">
                        <p className="text-[11px] uppercase tracking-wide text-slate-500">{k.label}</p>
                        <p className={`text-lg font-bold ${k.color}`}>{k.value}</p>
                        <p className="text-[11px] text-slate-500">{k.sub}</p>
                      </div>
                    ))}
                  </div>

                  <div>
                    <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">Bills</p>
                    {statementData.bills.length === 0 ? (
                      <p className="text-sm text-slate-500">No bills in this period.</p>
                    ) : (
                      <div className="overflow-x-auto rounded-lg border border-surface-700">
                        <table className="w-full text-xs">
                          <thead><tr className="border-b border-surface-700 text-slate-400">
                            <th className="px-3 py-2 text-left">Bill #</th>
                            <th className="px-3 py-2 text-left">Reference</th>
                            <th className="px-3 py-2 text-left">Issue Date</th>
                            <th className="px-3 py-2 text-left">Status</th>
                            <th className="px-3 py-2 text-right">Total</th>
                            <th className="px-3 py-2 text-right">Due</th>
                          </tr></thead>
                          <tbody>
                            {statementData.bills.map((b: any) => (
                              <tr key={b.id} className="border-b border-surface-800 text-slate-300">
                                <td className="px-3 py-2 font-mono">{b.bill_number}</td>
                                <td className="px-3 py-2">{b.reference || '—'}</td>
                                <td className="px-3 py-2">{formatDate(b.issue_date)}</td>
                                <td className="px-3 py-2 capitalize">{b.status.replace('_', ' ')}</td>
                                <td className="px-3 py-2 text-right">{formatCurrency(b.total_amount)}</td>
                                <td className="px-3 py-2 text-right">{formatCurrency(b.amount_due)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>

                  <div>
                    <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">Payments</p>
                    {statementData.payments.length === 0 ? (
                      <p className="text-sm text-slate-500">No payments in this period.</p>
                    ) : (
                      <div className="overflow-x-auto rounded-lg border border-surface-700">
                        <table className="w-full text-xs">
                          <thead><tr className="border-b border-surface-700 text-slate-400">
                            <th className="px-3 py-2 text-left">Bill #</th>
                            <th className="px-3 py-2 text-left">Date</th>
                            <th className="px-3 py-2 text-left">Method</th>
                            <th className="px-3 py-2 text-right">Amount</th>
                          </tr></thead>
                          <tbody>
                            {statementData.payments.map((p: any) => (
                              <tr key={p.id} className="border-b border-surface-800 text-slate-300">
                                <td className="px-3 py-2 font-mono">{p.bill_number || '—'}</td>
                                <td className="px-3 py-2">{formatDate(p.payment_date)}</td>
                                <td className="px-3 py-2 capitalize">{p.method.replace('_', ' ')}</td>
                                <td className="px-3 py-2 text-right text-green-400">{formatCurrency(p.amount)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>

                  {(statementData.returns ?? []).length > 0 && (
                    <div>
                      <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">Returns</p>
                      <div className="overflow-x-auto rounded-lg border border-surface-700">
                        <table className="w-full text-xs">
                          <thead><tr className="border-b border-surface-700 text-slate-400">
                            <th className="px-3 py-2 text-left">Return #</th>
                            <th className="px-3 py-2 text-left">Date</th>
                            <th className="px-3 py-2 text-left">Reason</th>
                            <th className="px-3 py-2 text-right">Amount</th>
                          </tr></thead>
                          <tbody>
                            {statementData.returns.map((r: any) => (
                              <tr key={r.id} className="border-b border-surface-800 text-slate-300">
                                <td className="px-3 py-2 font-mono">{r.return_number}</td>
                                <td className="px-3 py-2">{formatDate(r.return_date)}</td>
                                <td className="px-3 py-2">{r.reason || '—'}</td>
                                <td className="px-3 py-2 text-right text-blue-400">{formatCurrency(r.amount)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {balanceParty && (
        <AdjustOpeningBalanceModal
          partyName={balanceParty.name}
          partyLabel="Supplier"
          currentBalance={parseFloat(balanceParty.opening_balance ?? '0') || 0}
          naturalSide="credit"
          onClose={() => setBalanceParty(null)}
          onSave={async (amount, side, asOfDate) => {
            try {
              await supplierApi.setOpeningBalance(balanceParty.id, { amount, side, as_of_date: asOfDate })
              toast.success('Opening balance updated')
              bypassNextGets()
              load()
            } catch {
              toast.error('Failed to update opening balance')
              throw new Error('set-opening-balance failed')
            }
          }}
        />
      )}
    </div>
  )
}
