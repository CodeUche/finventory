import { useEffect, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { Plus, Search, Users, X, Pencil, Loader2, FileText, RefreshCw, Download, Trash2, MinusCircle, ChevronRight, Maximize2, Minimize2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { customerApi, tauriFetch } from '@/services/api'
import ExportButton from '@/components/ExportButton'
import { formatCurrency, formatDate, getStatusColor, getCurrencySymbol } from '@/lib/utils'
import DateInput from '@/components/DateInput'
import { FieldTooltip } from '@/components/FieldTooltip'
import { useAuthStore } from '@/store/authStore'
import { saveBlobFile } from '@/lib/saveBlobFile'
import type { Customer } from '@/types'

function creditScoreColor(score: number) {
  if (score <= 30) return { text: 'text-red-400', ring: '#ef4444', label: 'Poor' }
  if (score <= 50) return { text: 'text-orange-400', ring: '#f97316', label: 'Fair' }
  if (score <= 70) return { text: 'text-amber-400', ring: '#f59e0b', label: 'Avg' }
  if (score <= 85) return { text: 'text-emerald-300', ring: '#6ee7b7', label: 'Good' }
  return { text: 'text-emerald-400', ring: '#10b981', label: 'Excellent' }
}

function CreditScoreWheel({ score, size = 36 }: { score?: number; size?: number }) {
  if (score == null) return <span className="text-slate-600 text-xs">—</span>
  const c = creditScoreColor(score)
  const r = (size / 2) - 3
  const circ = 2 * Math.PI * r
  const dash = (score / 100) * circ
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#334155" strokeWidth="3" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth="3"
          strokeDasharray={`${dash} ${circ}`} stroke={c.ring} strokeLinecap="round" />
      </svg>
      <span className={`absolute text-[8px] font-bold ${c.text}`}>{score}</span>
    </div>
  )
}

const CUSTOMER_TYPES = [
  'retail',        // Walk-in / general customer
  'wholesale',     // Bulk buyer, periodic orders
  'distributor',   // Resells to third parties
  'corporate',     // Business/company account
  'client',        // Professional service client
  'passenger',     // Transport / hospitality
  'vip',           // Premium / priority customer
  'government',    // Government / public sector
  'ngo',           // Non-profit / NGO
]

interface NewCustomerForm {
  name: string
  customer_type: string
  email: string
  phone: string
  address: string
  credit_limit: string
}

const BLANK: NewCustomerForm = {
  name: '',
  customer_type: 'retail',
  email: '',
  phone: '',
  address: '',
  credit_limit: '0',
}

export default function CustomersPage() {
  const { organisation } = useAuthStore()
  const [customers, setCustomers] = useState<Customer[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('')

  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState<NewCustomerForm>(BLANK)
  const [saving, setSaving] = useState(false)

  const [selected, setSelected] = useState<Customer | null>(null)
  const [showEditModal, setShowEditModal] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [editForm, setEditForm] = useState<NewCustomerForm>(BLANK)

  // Statement
  const [showStatement, setShowStatement] = useState(false)
  const [statementData, setStatementData] = useState<any>(null)
  const [stmtFrom, setStmtFrom] = useState(() => {
    const d = new Date(); d.setDate(1); return d.toISOString().split('T')[0]
  })
  const [stmtTo, setStmtTo] = useState(() => new Date().toISOString().split('T')[0])
  const [loadingStmt, setLoadingStmt] = useState(false)
const [stmtMaximized, setStmtMaximized] = useState(false)

  // Debit modal
  const [showDebitModal, setShowDebitModal] = useState(false)
  const [debitForm, setDebitForm] = useState({ amount: '', reference: '', description: '', debit_date: new Date().toISOString().split('T')[0] })
  const [savingDebit, setSavingDebit] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await customerApi.list({ search, customer_type: typeFilter || undefined })
      setCustomers(data.results ?? data)
    } catch { toast.error('Failed to load customers') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [search, typeFilter])
  useDataRefresh(load)

  const handleCreate = async () => {
    if (!form.name.trim()) { toast.error('Customer name required'); return }
    setSaving(true)
    try {
      await customerApi.create(form)
      toast.success('Customer added')
      setShowModal(false)
      setForm(BLANK)
      load()
    } catch { toast.error('Failed to create customer') }
    finally { setSaving(false) }
  }

  const openEdit = (c: Customer) => {
    setEditId(c.id)
    setEditForm({
      name: c.name,
      customer_type: c.customer_type,
      email: c.email ?? '',
      phone: c.phone ?? '',
      address: c.address ?? '',
      credit_limit: c.credit_limit,
    })
    setShowEditModal(true)
  }

  const handleUpdate = async () => {
    if (!editForm.name.trim() || !editId) { toast.error('Customer name required'); return }
    setSaving(true)
    try {
      const updated = await customerApi.update(editId, editForm)
      toast.success('Customer updated')
      setShowEditModal(false)
      if (selected?.id === editId) setSelected({ ...selected, ...updated.data })
      load()
    } catch { toast.error('Failed to update customer') }
    finally { setSaving(false) }
  }

  const handleDelete = async (c: Customer) => {
    if (!confirm(`Delete customer "${c.name}"? This cannot be undone.`)) return
    try {
      await customerApi.delete(c.id)
      toast.success('Customer deleted')
      if (selected?.id === c.id) setSelected(null)
      load()
    } catch { toast.error('Cannot delete customer — they may have invoices or credits linked') }
  }

  const loadStatement = async (cId: string) => {
    setLoadingStmt(true)
    try {
      const { data } = await customerApi.statement(cId, { date_from: stmtFrom, date_to: stmtTo })
      setStatementData(data)
    } catch { toast.error('Failed to load statement') }
    finally { setLoadingStmt(false) }
  }

  const downloadStatementPDF = async () => {
    if (!statementData || !selected) return
    const { jsPDF } = await import('jspdf')
    const { default: autoTable } = await import('jspdf-autotable')
    const doc = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'landscape' })
    const sym = getCurrencySymbol()
    const pageW = doc.internal.pageSize.getWidth() // 297mm in landscape

    // Resolve brand color
    const brandRgb = (hex?: string): [number, number, number] => {
      const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
      if (!m) return [249, 115, 22]
      return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
    }
    const BRAND = brandRgb(organisation?.brand_color)
    const DARK: [number, number, number] = [30, 30, 30]
    const MUTED: [number, number, number] = [100, 100, 100]
    const tmpl = organisation?.invoice_template ?? 'classic'

    // Helper to fetch URL → base64 data URL (uses tauriFetch for Tauri compatibility)
    const fetchDataUrl = async (url: string): Promise<string | null> => {
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

    // Pre-load logo
    let logoData: string | null = null
    if (organisation?.logo) logoData = await fetchDataUrl(organisation.logo)

    // ── Font / style settings ──────────────────────────────────────────────────
    const hexToRgb = (hex?: string): [number, number, number] => {
      const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
      if (!m) return [30, 30, 30]
      return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
    }
    const pdfFont = organisation?.company_name_font?.toLowerCase().includes('times') ||
      ['Georgia','Playfair Display','Merriweather','Lora','Libre Baskerville','EB Garamond',
       'Crimson Text','Cinzel','Cormorant Garamond','Spectral'].includes(organisation?.company_name_font ?? '')
      ? 'times'
      : ['courier','JetBrains Mono','Fira Code'].includes(organisation?.company_name_font ?? '')
      ? 'courier' : 'helvetica'
    const isBold   = organisation?.company_name_font_bold !== false
    const isItalic = organisation?.company_name_font_italic === true
    const pdfStyle = isBold && isItalic ? 'bolditalic' : isBold ? 'bold' : isItalic ? 'italic' : 'normal'
    const fontSize = Math.max(8, Math.min(36, organisation?.company_name_font_size ?? 14))
    const nameColor: [number, number, number] = (() => {
      const c = organisation?.company_name_font_color
      if (!c || c === '#ffffff') return (tmpl === 'modern' || tmpl === 'minimal') ? DARK : [255, 255, 255]
      return hexToRgb(c)
    })()
    const { applyDocHeader, templateHeadFill } = await import('@/lib/pdfUtils')
    const displayName = organisation?.show_company_name_on_pdf === false
      ? '' : (organisation?.invoice_company_name?.trim() || organisation?.name || 'Audity')
    let y = applyDocHeader(doc, {
      tmpl, pageW, BRAND, DARK, MUTED,
      logoData,
      displayName,
      orgAddress: organisation?.address,
      orgEmail: organisation?.email,
      orgPhone: organisation?.phone,
      pdfFont,
      fontSize,
      pdfStyle,
      nameColor,
      companyFontUnderline: organisation?.company_name_font_underline,
      showCompanyName: organisation?.show_company_name_on_pdf !== false,
      docTitle: 'CUSTOMER STATEMENT',
      metaRows: [
        ['Customer',   selected.name],
        ['Ref',        selected.code],
        ['Period',     `${formatDate(stmtFrom)} – ${formatDate(stmtTo)}`],
        ['Generated',  formatDate(new Date().toISOString().split('T')[0])],
      ],
    })

    // Summary KPIs
    const kpis = [
      { label: 'Total Invoiced', value: `${sym}${parseFloat(statementData.summary.total_invoiced).toLocaleString('en', { minimumFractionDigits: 2 })}` },
      { label: 'Total Paid', value: `${sym}${parseFloat(statementData.summary.total_paid).toLocaleString('en', { minimumFractionDigits: 2 })}` },
      { label: 'Balance Due', value: `${sym}${parseFloat(statementData.summary.balance_due).toLocaleString('en', { minimumFractionDigits: 2 })}` },
    ]
    const kpiW = (pageW - 28) / 3
    kpis.forEach((k, i) => {
      const kx = 14 + i * kpiW
      doc.setFillColor(241, 245, 249)
      doc.roundedRect(kx, y, kpiW - 3, 22, 2, 2, 'F')
      doc.setFontSize(7)
      doc.setTextColor(100, 116, 139)
      doc.setFont('helvetica', 'normal')
      doc.text(k.label.toUpperCase(), kx + (kpiW - 3) / 2, y + 7, { align: 'center' })
      doc.setFontSize(11)
      doc.setFont('helvetica', 'bold')
      doc.setTextColor(i === 2 && parseFloat(statementData.summary.balance_due) > 0 ? 220 : 15, i === 2 && parseFloat(statementData.summary.balance_due) > 0 ? 38 : 40, i === 2 && parseFloat(statementData.summary.balance_due) > 0 ? 38 : 80)
      doc.text(k.value, kx + (kpiW - 3) / 2, y + 16, { align: 'center' })
    })
    y += 28

    // Build combined chronological ledger (with product line items expanded)
    const fmtMoney = (v: number) => `${sym}${v.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    // Columns: Trans Date | Trans Ref | Description | Product | Qty | Unit Cost | Sold By | Debit | Credit | Balance
    type LedgerRow = [string, string, string, string, string, string, string, string, string, string]
    const ledger: LedgerRow[] = []
    const itemRowIndices: number[] = []
    const debitRowIndices: number[] = []
    let runBalance = 0

    // Merge invoices (expanded to items), debits, payments — sorted by date
    type Event = { date: string; type: 'invoice' | 'payment' | 'debit'; data: any }
    const events: Event[] = []
    for (const inv of statementData.invoices) {
      events.push({ date: inv.issue_date, type: 'invoice', data: inv })
    }
    for (const p of statementData.payments) {
      events.push({ date: p.received_at ? String(p.received_at).split('T')[0] : '', type: 'payment', data: p })
    }
    for (const d of (statementData.debits ?? [])) {
      events.push({ date: d.debit_date, type: 'debit', data: d })
    }
    events.sort((a, b) => a.date.localeCompare(b.date))

    for (const e of events) {
      if (e.type === 'invoice') {
        const inv = e.data
        const invTotal = parseFloat(inv.total_amount)
        if (inv.items && inv.items.length > 0) {
          for (const item of inv.items) {
            runBalance += parseFloat(item.line_total)
            itemRowIndices.push(ledger.length)
            ledger.push([
              formatDate(e.date),
              inv.invoice_number,
              `Invoice · ${inv.status.replace('_', ' ')}`,
              item.product,
              item.qty,
              fmtMoney(parseFloat(item.unit_cost)),
              inv.sold_by || '—',
              fmtMoney(parseFloat(item.line_total)),
              '',
              fmtMoney(runBalance),
            ])
          }
        } else {
          runBalance += invTotal
          ledger.push([
            formatDate(e.date),
            inv.invoice_number,
            `Invoice · ${inv.status.replace('_', ' ')}`,
            '', '', '',
            inv.sold_by || '—',
            fmtMoney(invTotal),
            '',
            fmtMoney(runBalance),
          ])
        }
      } else if (e.type === 'payment') {
        const p = e.data
        runBalance -= parseFloat(p.amount)
        ledger.push([
          formatDate(e.date),
          p.invoice_number || p.reference || '—',
          `Payment · ${p.method.replace('_', ' ')}`,
          '', '', '', '',
          '',
          fmtMoney(parseFloat(p.amount)),
          fmtMoney(runBalance),
        ])
      } else {
        const d = e.data
        runBalance += parseFloat(d.amount)
        debitRowIndices.push(ledger.length)
        ledger.push([
          formatDate(e.date),
          d.reference || '—',
          d.description || 'Manual Debit',
          '', '', '', '',
          fmtMoney(parseFloat(d.amount)),
          '',
          fmtMoney(runBalance),
        ])
      }
    }

    // Grand Total row
    const totalCharged = parseFloat(statementData.summary.total_charged)
    const totalCredit = parseFloat(statementData.summary.total_paid)
    ledger.push(['', '', 'GRAND TOTAL', '', '', '', '', fmtMoney(totalCharged), fmtMoney(totalCredit), fmtMoney(totalCharged - totalCredit)])

    // Landscape A4: 297mm − 28mm margins = 269mm usable
    // Col widths: 20+32+32+44+10+28+28+26+28+28+28 wait — 10 cols, 269mm
    // 20+32+32+38+10+26+26+27+28+30 = 269mm
    autoTable(doc, {
      startY: y,
      head: [['Trans Date', 'Trans Ref', 'Description', 'Product', 'Qty', 'Unit Cost', 'Sold By', 'Debit', 'Credit', 'Balance']],
      body: ledger,
      styles: { fontSize: 7, cellPadding: 2.5, overflow: 'ellipsize' },
      headStyles: { fillColor: templateHeadFill(tmpl, BRAND), textColor: 255, fontStyle: 'bold', fontSize: 6.5 },
      columnStyles: {
        0: { cellWidth: 20 },
        1: { cellWidth: 32, fontStyle: 'bold', overflow: 'ellipsize' },
        2: { cellWidth: 32 },
        3: { cellWidth: 38 },
        4: { halign: 'right', cellWidth: 10 },
        5: { halign: 'right', cellWidth: 26 },
        6: { cellWidth: 27 },
        7: { halign: 'right', cellWidth: 28 },
        8: { halign: 'right', cellWidth: 28 },
        9: { halign: 'right', cellWidth: 28, fontStyle: 'bold' },
      },
      didParseCell: (data: any) => {
        if (data.row.index === ledger.length - 1) {
          data.cell.styles.fontStyle = 'bold'
          data.cell.styles.fillColor = [241, 245, 249]
        }
        if (itemRowIndices.includes(data.row.index)) {
          data.cell.styles.fillColor = [248, 252, 255]
        }
        if (debitRowIndices.includes(data.row.index)) {
          data.cell.styles.textColor = [185, 28, 28]
        }
      },
      alternateRowStyles: { fillColor: [248, 250, 252] },
      showHead: 'everyPage',
      margin: { left: 14, right: 14 },
    })
    y = (doc as any).lastAutoTable.finalY + 6

    // Footer on every page
    const pageCount = (doc.internal as any).getNumberOfPages()
    for (let i = 1; i <= pageCount; i++) {
      doc.setPage(i)
      const ph = doc.internal.pageSize.getHeight()
      doc.setFillColor(...BRAND)
      doc.rect(0, ph - 12, pageW, 12, 'F')
      doc.setFontSize(7)
      doc.setTextColor(255, 255, 255)
      doc.text(`Page ${i} of ${pageCount}`, pageW / 2, ph - 5, { align: 'center' })
      doc.text(organisation?.name ?? 'Company', 10, ph - 5)
      doc.text(`Statement: ${formatDate(stmtFrom)} — ${formatDate(stmtTo)}`, pageW - 10, ph - 5, { align: 'right' })
    }

    await saveBlobFile(doc.output('blob'), `statement-${selected.code}-${stmtFrom}-${stmtTo}.pdf`)
  }

  const handleRecordDebit = async () => {
    if (!selected || !debitForm.amount || !debitForm.debit_date) { toast.error('Amount and date required'); return }
    setSavingDebit(true)
    try {
      const [d, m, y] = debitForm.debit_date.includes('/') ? debitForm.debit_date.split('/') : [null, null, null]
      const isoDate = d ? `${y}-${m}-${d}` : debitForm.debit_date
      await customerApi.recordDebit(selected.id, { ...debitForm, debit_date: isoDate, amount: debitForm.amount })
      toast.success('Debit recorded')
      setShowDebitModal(false)
      setDebitForm({ amount: '', reference: '', description: '', debit_date: new Date().toISOString().split('T')[0] })
      // Refresh statement if open
      if (showStatement) loadStatement(selected.id)
    } catch (err: any) {
      const msg = err?.response?.data?.error
      toast.error(typeof msg === 'string' ? msg : 'Failed to record debit')
    } finally { setSavingDebit(false) }
  }

  const openStatement = (c: Customer) => {
    setSelected(c)
    setStatementData(null)
    setShowStatement(true)
    loadStatement(c.id)
  }

  const creditUtilPct = (c: Customer) => {
    const limit = parseFloat(c.credit_limit)
    const used = parseFloat(c.outstanding_balance)
    if (!limit) return 0
    return Math.min(100, (used / limit) * 100)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Customers</h1>
          <p className="text-slate-400 text-sm">{customers.length} customer{customers.length !== 1 ? 's' : ''}</p>
        </div>
        <div className="sm:ml-auto flex items-center gap-2">
          <ExportButton endpoint="/customers/" filename="customers" />
          <button className="btn-primary" onClick={() => setShowModal(true)}>
            <Plus size={16} /> New Customer
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            className="input pl-9"
            placeholder="Search name, email, phone…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select className="input max-w-xs" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="">All types</option>
          {CUSTOMER_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Customer', 'Type', 'Score', 'Phone', 'Credit Limit', 'Outstanding', 'Available', 'Credit Usage', ''].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 9 }).map((_, j) => (
                      <td key={j} className="px-5 py-3.5">
                        <div className="h-4 bg-surface-700 rounded animate-pulse w-20" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : customers.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-5 py-12 text-center">
                    <Users size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No customers yet</p>
                  </td>
                </tr>
              ) : (
                customers.map((c) => {
                  const pct = creditUtilPct(c)
                  return (
                    <tr key={c.id} className="table-row cursor-pointer" onClick={() => setSelected(c)}>
                      <td className="px-5 py-3.5">
                        <p className="font-medium text-white">{c.name}</p>
                        <p className="text-xs text-slate-500">{c.code}</p>
                      </td>
                      <td className="px-5 py-3.5">
                        <span className={getStatusColor(c.customer_type === 'retail' ? 'confirmed' : c.customer_type === 'wholesale' ? 'partially_paid' : 'credit')}>
                          {c.customer_type}
                        </span>
                      </td>
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-1.5">
                          <CreditScoreWheel score={c.credit_score} size={30} />
                          {c.credit_score != null && (
                            <span className={`text-[10px] font-medium ${creditScoreColor(c.credit_score).text}`}>
                              {creditScoreColor(c.credit_score).label}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-5 py-3.5 text-slate-400">{c.phone || '—'}</td>
                      <td className="px-5 py-3.5 text-slate-300">{formatCurrency(c.credit_limit)}</td>
                      <td className="px-5 py-3.5 text-red-400">{formatCurrency(c.outstanding_balance)}</td>
                      <td className="px-5 py-3.5 text-emerald-400">{formatCurrency(c.available_credit)}</td>
                      <td className="px-5 py-3.5 min-w-[120px]">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 h-1.5 bg-surface-700 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all ${
                                pct > 80 ? 'bg-red-500' : pct > 50 ? 'bg-amber-500' : 'bg-emerald-500'
                              }`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className="text-xs text-slate-500 w-8">{pct.toFixed(0)}%</span>
                        </div>
                      </td>
                      <td className="px-5 py-3.5">
                        {c.is_credit_blocked && (
                          <span className="badge-red text-[10px]">Blocked</span>
                        )}
                      </td>
                      <td className="px-5 py-3.5" onClick={(e) => e.stopPropagation()}>
                        <button
                          onClick={() => handleDelete(c)}
                          className="p-1.5 text-slate-600 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                          title="Delete customer"
                        >
                          <Trash2 size={13} />
                        </button>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Detail drawer */}
      {selected && (
        <div
          className="fixed inset-0 z-40 flex justify-end"
          onClick={() => setSelected(null)}
        >
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
          <aside
            className="relative w-full max-w-md bg-surface-900 border-l border-surface-700 shadow-2xl overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 space-y-5">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-xl font-bold text-white">{selected.name}</h2>
                  <p className="text-slate-400 text-sm">{selected.code} · {selected.customer_type}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => openStatement(selected)}
                    className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-brand-500/40 text-brand-400 hover:bg-brand-500/10 text-xs font-medium transition-colors"
                    title="View Statement"
                  >
                    <FileText size={13} /> Statement
                  </button>
                  <button onClick={() => openEdit(selected)} className="btn-ghost p-1.5 text-slate-400 hover:text-white" title="Edit">
                    <Pencil size={15} />
                  </button>
                  <button onClick={() => handleDelete(selected)} className="btn-ghost p-1.5 text-slate-400 hover:text-red-400" title="Delete">
                    <Trash2 size={15} />
                  </button>
                  <button onClick={() => setSelected(null)} className="btn-ghost p-1.5 text-slate-400 hover:text-white">
                    <X size={18} />
                  </button>
                </div>
              </div>

              {/* Stats */}
              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: 'Credit Limit', value: formatCurrency(selected.credit_limit), color: 'text-white' },
                  { label: 'Outstanding', value: formatCurrency(selected.outstanding_balance), color: 'text-red-400' },
                  { label: 'Available', value: formatCurrency(selected.available_credit), color: 'text-emerald-400' },
                  { label: 'Credit %', value: `${creditUtilPct(selected).toFixed(1)}%`, color: creditUtilPct(selected) > 80 ? 'text-red-400' : 'text-amber-400' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="bg-surface-800 rounded-xl p-4">
                    <p className="text-xs text-slate-500 mb-1">{label}</p>
                    <p className={`text-lg font-bold ${color}`}>{value}</p>
                  </div>
                ))}
                {/* Credit Score card — spans full width */}
                <div className="col-span-2 bg-surface-800 rounded-xl p-4 flex items-center gap-4">
                  <CreditScoreWheel score={selected.credit_score} size={52} />
                  <div>
                    <p className="text-xs text-slate-500 mb-0.5">Credit Score</p>
                    {selected.credit_score != null ? (
                      <>
                        <p className={`text-2xl font-bold ${creditScoreColor(selected.credit_score).text}`}>
                          {selected.credit_score}
                          <span className="text-sm font-normal text-slate-500"> / 100</span>
                        </p>
                        <p className={`text-xs font-medium ${creditScoreColor(selected.credit_score).text}`}>
                          {creditScoreColor(selected.credit_score).label}
                        </p>
                      </>
                    ) : (
                      <p className="text-slate-500 text-sm">No history</p>
                    )}
                  </div>
                </div>
              </div>

              {/* Info */}
              <div className="space-y-2 text-sm">
                {[
                  { label: 'Email', value: selected.email || '—' },
                  { label: 'Phone', value: selected.phone || '—' },
                  { label: 'Shipping Address', value: selected.address || '—' },
                  { label: 'Status', value: selected.is_credit_blocked ? 'Credit Blocked' : 'Active' },
                ].map(({ label, value }) => (
                  <div key={label} className="flex justify-between py-2 border-b border-surface-700">
                    <span className="text-slate-400">{label}</span>
                    <span className="text-white font-medium text-right max-w-[60%]">{value}</span>
                  </div>
                ))}
              </div>

              {/* Account actions */}
              <div className="pt-1">
                <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Account Actions</p>
                <button
                  onClick={() => setShowDebitModal(true)}
                  className="w-full flex items-center justify-between px-4 py-3 rounded-xl border border-orange-500/30 bg-orange-500/5 hover:bg-orange-500/10 transition-colors group"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-orange-500/15 flex items-center justify-center">
                      <MinusCircle size={15} className="text-orange-400" />
                    </div>
                    <div className="text-left">
                      <p className="text-sm font-medium text-white">Issue Debit Note</p>
                      <p className="text-[10px] text-slate-500">Raise a charge against this account</p>
                    </div>
                  </div>
                  <ChevronRight size={14} className="text-slate-500 group-hover:text-orange-400 transition-colors" />
                </button>
              </div>
            </div>
          </aside>
        </div>
      )}

      {/* Edit modal */}
      {showEditModal && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowEditModal(false)} />
          <div className="relative card w-full max-w-lg p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">Edit Customer</h2>
              <button onClick={() => setShowEditModal(false)} className="text-slate-400 hover:text-white">
                <X size={20} />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Full Name *<FieldTooltip text="The person or business name. This appears on all their invoices and account statements." /></label>
                <input className="input" value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Type<FieldTooltip text="Categorise your customer — Retail for individuals, Wholesale for bulk buyers, Corporate for businesses. Helps with filtering and pricing decisions." /></label>
                <select className="input" value={editForm.customer_type} onChange={(e) => setEditForm({ ...editForm, customer_type: e.target.value })}>
                  {CUSTOMER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Credit Limit<FieldTooltip text="The maximum amount this customer is allowed to owe you at any time. Set to 0 to block credit sales. The app warns you when they approach this limit." /></label>
                <input type="number" className="input" value={editForm.credit_limit} min="0"
                  onChange={(e) => setEditForm({ ...editForm, credit_limit: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Phone<FieldTooltip text="Customer's phone number. Shown on invoices and useful for follow-ups." /></label>
                <input className="input" value={editForm.phone} onChange={(e) => setEditForm({ ...editForm, phone: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Email<FieldTooltip text="Customer's email. Used to send invoices and payment links directly from the app." /></label>
                <input type="email" className="input" value={editForm.email} onChange={(e) => setEditForm({ ...editForm, email: e.target.value })} />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Shipping Address<FieldTooltip text="The customer's shipping/delivery address. Printed on invoices and delivery notes." /></label>
                <textarea className="input resize-none" rows={2} value={editForm.address}
                  onChange={(e) => setEditForm({ ...editForm, address: e.target.value })} />
              </div>
            </div>

            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm"
                onClick={() => setShowEditModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleUpdate} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Statement modal */}
      {showStatement && selected && (
        <div className={['fixed inset-0 z-[60] flex items-center justify-center', stmtMaximized ? '' : 'p-4'].join(' ')}>
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => { setShowStatement(false); setStmtMaximized(false) }} />
          <div className={[
            'relative bg-surface-900 border border-surface-700 shadow-2xl flex flex-col transition-all duration-200',
            stmtMaximized
              ? 'w-full h-full rounded-none'
              : 'w-full max-w-3xl max-h-[90vh] rounded-2xl',
          ].join(' ')}>
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-surface-700 shrink-0">
              <div>
                <h2 className="text-lg font-bold text-white">{selected.name} — Statement</h2>
                <p className="text-xs text-slate-500">{selected.code}</p>
              </div>
              <div className="flex items-center gap-2">
                {statementData && (
                  <button
                    onClick={downloadStatementPDF}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold transition-colors"
                    title="Export PDF"
                  >
                    <Download size={13} /> Export PDF
                  </button>
                )}
                <button
                  onClick={() => setStmtMaximized((v) => !v)}
                  className="btn-ghost p-2"
                  title={stmtMaximized ? 'Restore' : 'Expand'}
                >
                  {stmtMaximized ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
                </button>
                <button onClick={() => { setShowStatement(false); setStmtMaximized(false) }} className="btn-ghost p-2"><X size={18} /></button>
              </div>
            </div>
            {/* Date range controls */}
            <div className="px-6 pt-4 flex gap-3 items-end flex-wrap">
              <div>
                <label className="label text-xs">From</label>
                <DateInput value={stmtFrom} onChange={(v) => setStmtFrom(v)} />
              </div>
              <div>
                <label className="label text-xs">To</label>
                <DateInput value={stmtTo} onChange={(v) => setStmtTo(v)} />
              </div>
              <button
                onClick={() => loadStatement(selected.id)}
                disabled={loadingStmt}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-brand-500 text-white text-xs font-semibold hover:bg-brand-600 transition-colors disabled:opacity-60"
              >
                {loadingStmt ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                Refresh
              </button>
            </div>
            {/* Body */}
            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
              {loadingStmt ? (
                <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="h-10 bg-surface-800 rounded-lg animate-pulse" />
                ))}</div>
              ) : !statementData ? null : (
                <>
                  {/* Summary KPIs — row 1 */}
                  <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                    {[
                      { label: 'Total Invoiced', value: formatCurrency(statementData.summary.total_invoiced), color: 'text-red-400', sub: `${statementData.invoices.length} invoice${statementData.invoices.length !== 1 ? 's' : ''}` },
                      { label: 'Discounts Given', value: formatCurrency(statementData.summary.total_discounts ?? '0'), color: 'text-green-400', sub: 'Savings on invoices' },
                      { label: 'VAT Charged', value: formatCurrency(statementData.summary.total_tax ?? '0'), color: 'text-blue-400', sub: 'Tax on invoices' },
                      { label: 'Total Paid', value: formatCurrency(statementData.summary.total_paid), color: 'text-green-400', sub: `${statementData.payments.length} payment${statementData.payments.length !== 1 ? 's' : ''}` },
                      { label: 'Balance Due', value: formatCurrency(statementData.summary.balance_due), color: parseFloat(statementData.summary.balance_due) > 0 ? 'text-amber-400' : 'text-green-400', sub: parseFloat(statementData.summary.balance_due) > 0 ? 'Outstanding' : 'Settled' },
                    ].map(({ label, value, color, sub }) => (
                      <div key={label} className="bg-surface-800 rounded-xl p-3 text-center">
                        <p className="text-[10px] text-slate-500 mb-1 leading-tight">{label}</p>
                        <p className={`text-sm font-bold ${color}`}>{value}</p>
                        <p className="text-[10px] text-slate-600 mt-0.5">{sub}</p>
                      </div>
                    ))}
                  </div>

                  {/* Summary panels — Payment / Debit / Credit */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    {/* Payment Summary */}
                    <div className="bg-surface-800 rounded-xl p-3 space-y-2">
                      <p className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Payment Summary</p>
                      {statementData.payments.length === 0 ? (
                        <p className="text-[11px] text-slate-600">No payments recorded</p>
                      ) : (
                        <>
                          {Object.entries(statementData.summary.payment_by_method ?? {}).map(([method, amount]) => (
                            <div key={method} className="flex justify-between items-center">
                              <span className="text-[11px] text-slate-400 capitalize">{method}</span>
                              <span className="text-[11px] font-semibold text-green-400">{formatCurrency(amount as string)}</span>
                            </div>
                          ))}
                          <div className="flex justify-between items-center border-t border-surface-700 pt-1.5 mt-1">
                            <span className="text-[11px] text-slate-300 font-semibold">Total</span>
                            <span className="text-[11px] font-bold text-green-400">{formatCurrency(statementData.summary.total_paid)}</span>
                          </div>
                        </>
                      )}
                    </div>
                    {/* Debit Summary */}
                    <div className="bg-surface-800 rounded-xl p-3 space-y-2">
                      <p className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Debit Summary</p>
                      {(statementData.debits ?? []).length === 0 ? (
                        <p className="text-[11px] text-slate-600">No manual debits recorded</p>
                      ) : (
                        <>
                          {(statementData.debits ?? []).map((d: any) => (
                            <div key={d.id} className="flex justify-between items-start gap-2">
                              <span className="text-[11px] text-slate-400 truncate">{d.description || d.reference || 'Manual Debit'}</span>
                              <span className="text-[11px] font-semibold text-orange-400 whitespace-nowrap">{formatCurrency(d.amount)}</span>
                            </div>
                          ))}
                          <div className="flex justify-between items-center border-t border-surface-700 pt-1.5 mt-1">
                            <span className="text-[11px] text-slate-300 font-semibold">Total</span>
                            <span className="text-[11px] font-bold text-orange-400">{formatCurrency(statementData.summary.total_debits ?? '0')}</span>
                          </div>
                        </>
                      )}
                    </div>
                    {/* Credit / Returns Summary */}
                    <div className="bg-surface-800 rounded-xl p-3 space-y-2">
                      <p className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">Credit Summary</p>
                      {(statementData.returns ?? []).length === 0 ? (
                        <p className="text-[11px] text-slate-600">No returns or credits recorded</p>
                      ) : (
                        <>
                          {(statementData.returns ?? []).map((r: any) => (
                            <div key={r.id} className="flex justify-between items-start gap-2">
                              <span className="text-[11px] text-slate-400 truncate">{r.invoice_number} {r.reason ? `· ${r.reason}` : ''}</span>
                              <span className="text-[11px] font-semibold text-blue-400 whitespace-nowrap">{formatCurrency(r.amount)}</span>
                            </div>
                          ))}
                          <div className="flex justify-between items-center border-t border-surface-700 pt-1.5 mt-1">
                            <span className="text-[11px] text-slate-300 font-semibold">Total Returns</span>
                            <span className="text-[11px] font-bold text-blue-400">{formatCurrency(statementData.summary.total_returns ?? '0')}</span>
                          </div>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Combined transaction ledger */}
                  <div>
                    <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Transaction History</p>
                    {(() => {
                      type Evt = { date: string; type: 'invoice' | 'payment' | 'debit' | 'return'; data: any }
                      const events: Evt[] = []
                      for (const inv of statementData.invoices) events.push({ date: inv.issue_date, type: 'invoice', data: inv })
                      for (const p of statementData.payments) events.push({ date: p.received_at ? String(p.received_at).split('T')[0] : '', type: 'payment', data: p })
                      for (const d of (statementData.debits ?? [])) events.push({ date: d.debit_date, type: 'debit', data: d })
                      for (const r of (statementData.returns ?? [])) events.push({ date: r.created_at ? String(r.created_at).split('T')[0] : '', type: 'return', data: r })
                      events.sort((a, b) => a.date.localeCompare(b.date))
                      let balance = 0
                      return events.length === 0 ? (
                        <p className="text-slate-600 text-sm text-center py-4">No transactions in this period</p>
                      ) : (
                        <div className="overflow-x-auto rounded-lg border border-surface-700/50">
                          <table className="w-full text-xs" style={{ tableLayout: 'fixed', minWidth: '820px' }}>
                            <colgroup>
                              <col style={{ width: '7%' }}  />  {/* Date */}
                              <col style={{ width: '10%' }} />  {/* Reference */}
                              <col style={{ width: '20%' }} />  {/* Product / Description */}
                              <col style={{ width: '4%' }}  />  {/* Qty */}
                              <col style={{ width: '10%' }} />  {/* Unit Cost */}
                              <col style={{ width: '8%' }}  />  {/* Pay Method */}
                              <col style={{ width: '9%' }}  />  {/* Sold By */}
                              <col style={{ width: '10%' }} />  {/* Debit */}
                              <col style={{ width: '10%' }} />  {/* Credit */}
                              <col style={{ width: '12%' }} />  {/* Balance */}
                            </colgroup>
                            <thead>
                              <tr className="border-b-2 border-surface-700 bg-surface-800/60">
                                {[
                                  { h: 'Date',                  right: false },
                                  { h: 'Reference',             right: false },
                                  { h: 'Product / Description', right: false },
                                  { h: 'Qty',                   right: true  },
                                  { h: 'Unit Cost',             right: true  },
                                  { h: 'Pay Method',            right: false },
                                  { h: 'Sold By',               right: false },
                                  { h: 'Debit',                 right: true  },
                                  { h: 'Credit',                right: true  },
                                  { h: 'Balance',               right: true  },
                                ].map(({ h, right }) => (
                                  <th
                                    key={h}
                                    className={`px-2 py-2.5 text-slate-400 font-semibold text-[10px] uppercase tracking-wider overflow-hidden text-ellipsis whitespace-nowrap ${right ? 'text-right' : 'text-left'}`}
                                  >{h}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {events.map((e, ei) => {
                                if (e.type === 'invoice') {
                                  const inv = e.data
                                  const hasItems = inv.items && inv.items.length > 0
                                  const rows: JSX.Element[] = []
                                  if (hasItems) {
                                    for (const item of inv.items) {
                                      balance += parseFloat(item.line_total)
                                      const disc = parseFloat(item.discount_amount ?? '0')
                                      const vat  = parseFloat(item.tax_amount ?? '0')
                                      rows.push(
                                        <tr key={`item-${ei}-${item.product}`} className="border-b border-surface-700/40 hover:bg-surface-700/20 transition-colors">
                                          <td className="px-2 py-2.5 text-slate-400 whitespace-nowrap overflow-hidden">{formatDate(e.date)}</td>
                                          <td className="px-2 py-2.5 font-mono text-brand-400 text-[11px] overflow-hidden text-ellipsis whitespace-nowrap">{inv.invoice_number}</td>
                                          <td className="px-2 py-2.5 text-slate-300 overflow-hidden">
                                            <span className="font-medium block truncate">{item.product}</span>
                                            {(disc > 0 || vat > 0) && (
                                              <span className="text-[10px] text-slate-500 flex gap-1 flex-wrap">
                                                {disc > 0 && <span className="text-green-500">−{formatCurrency(disc)} disc</span>}
                                                {vat > 0  && <span className="text-blue-400">+{formatCurrency(vat)} VAT</span>}
                                              </span>
                                            )}
                                          </td>
                                          <td className="px-2 py-2.5 text-slate-400 text-right whitespace-nowrap">{item.qty}</td>
                                          <td className="px-2 py-2.5 text-slate-400 text-right whitespace-nowrap">{formatCurrency(parseFloat(item.unit_cost))}</td>
                                          <td className="px-2 py-2.5 text-slate-600 text-[11px]">—</td>
                                          <td className="px-2 py-2.5 text-slate-400 text-[11px] overflow-hidden text-ellipsis whitespace-nowrap">{inv.sold_by || '—'}</td>
                                          <td className="px-2 py-2.5 text-red-400 text-right whitespace-nowrap font-medium">{formatCurrency(parseFloat(item.line_total))}</td>
                                          <td className="px-2 py-2.5" />
                                          <td className={`px-2 py-2.5 text-right font-semibold whitespace-nowrap ${balance > 0 ? 'text-amber-400' : 'text-green-400'}`}>{formatCurrency(balance)}</td>
                                        </tr>
                                      )
                                    }
                                  } else {
                                    balance += parseFloat(inv.total_amount)
                                    rows.push(
                                      <tr key={`inv-${ei}`} className="border-b border-surface-700/40 hover:bg-surface-700/20">
                                        <td className="px-2 py-2.5 text-slate-400 whitespace-nowrap">{formatDate(e.date)}</td>
                                        <td className="px-2 py-2.5 font-mono text-brand-400 text-[11px] whitespace-nowrap">{inv.invoice_number}</td>
                                        <td className="px-2 py-2.5 text-slate-300 overflow-hidden text-ellipsis whitespace-nowrap">Invoice · <span className="capitalize">{inv.status.replace('_',' ')}</span></td>
                                        <td className="px-2 py-2.5" /><td className="px-2 py-2.5" /><td className="px-2 py-2.5" />
                                        <td className="px-2 py-2.5 text-slate-400 text-[11px] overflow-hidden text-ellipsis whitespace-nowrap">{inv.sold_by || '—'}</td>
                                        <td className="px-2 py-2.5 text-red-400 text-right whitespace-nowrap font-medium">{formatCurrency(parseFloat(inv.total_amount))}</td>
                                        <td className="px-2 py-2.5" />
                                        <td className={`px-2 py-2.5 text-right font-semibold whitespace-nowrap ${balance > 0 ? 'text-amber-400' : 'text-green-400'}`}>{formatCurrency(balance)}</td>
                                      </tr>
                                    )
                                  }
                                  return rows
                                } else if (e.type === 'payment') {
                                  const p = e.data
                                  balance -= parseFloat(p.amount)
                                  return (
                                    <tr key={`pay-${ei}`} className="border-b border-surface-700/40 hover:bg-surface-700/20 bg-emerald-500/[0.03]">
                                      <td className="px-2 py-2.5 text-slate-400 whitespace-nowrap">{formatDate(e.date)}</td>
                                      <td className="px-2 py-2.5 font-mono text-brand-400 text-[11px] whitespace-nowrap">{p.invoice_number || p.reference || '—'}</td>
                                      <td className="px-2 py-2.5 text-green-400 font-medium overflow-hidden text-ellipsis whitespace-nowrap">Payment received</td>
                                      <td className="px-2 py-2.5" /><td className="px-2 py-2.5" />
                                      <td className="px-2 py-2.5 text-slate-300 text-[11px] capitalize">{p.method.replace('_',' ')}</td>
                                      <td className="px-2 py-2.5" />
                                      <td className="px-2 py-2.5" />
                                      <td className="px-2 py-2.5 text-green-400 text-right whitespace-nowrap font-medium">{formatCurrency(parseFloat(p.amount))}</td>
                                      <td className={`px-2 py-2.5 text-right font-semibold whitespace-nowrap ${balance > 0 ? 'text-amber-400' : 'text-green-400'}`}>{formatCurrency(balance)}</td>
                                    </tr>
                                  )
                                } else if (e.type === 'return') {
                                  const r = e.data
                                  balance -= parseFloat(r.amount)
                                  return (
                                    <tr key={`ret-${ei}`} className="border-b border-surface-700/40 hover:bg-surface-700/20 bg-blue-500/[0.03]">
                                      <td className="px-2 py-2.5 text-slate-400 whitespace-nowrap">{formatDate(e.date)}</td>
                                      <td className="px-2 py-2.5 font-mono text-blue-400 text-[11px] whitespace-nowrap">{r.invoice_number || '—'}</td>
                                      <td className="px-2 py-2.5 text-blue-400 overflow-hidden text-ellipsis whitespace-nowrap">Credit Note{r.reason ? ` · ${r.reason}` : ''}</td>
                                      <td className="px-2 py-2.5" /><td className="px-2 py-2.5" /><td className="px-2 py-2.5" /><td className="px-2 py-2.5" />
                                      <td className="px-2 py-2.5" />
                                      <td className="px-2 py-2.5 text-blue-400 text-right whitespace-nowrap font-medium">{formatCurrency(parseFloat(r.amount))}</td>
                                      <td className={`px-2 py-2.5 text-right font-semibold whitespace-nowrap ${balance > 0 ? 'text-amber-400' : 'text-green-400'}`}>{formatCurrency(balance)}</td>
                                    </tr>
                                  )
                                } else {
                                  const d = e.data
                                  balance += parseFloat(d.amount)
                                  return (
                                    <tr key={`dbt-${ei}`} className="border-b border-surface-700/40 hover:bg-surface-700/20 bg-orange-500/[0.03]">
                                      <td className="px-2 py-2.5 text-slate-400 whitespace-nowrap">{formatDate(e.date)}</td>
                                      <td className="px-2 py-2.5 font-mono text-orange-400 text-[11px] whitespace-nowrap">{d.reference || '—'}</td>
                                      <td className="px-2 py-2.5 text-orange-400 overflow-hidden text-ellipsis whitespace-nowrap">{d.description || 'Manual Debit'}</td>
                                      <td className="px-2 py-2.5" /><td className="px-2 py-2.5" /><td className="px-2 py-2.5" /><td className="px-2 py-2.5" />
                                      <td className="px-2 py-2.5 text-orange-400 text-right whitespace-nowrap font-medium">{formatCurrency(parseFloat(d.amount))}</td>
                                      <td className="px-2 py-2.5" />
                                      <td className={`px-2 py-2.5 text-right font-semibold whitespace-nowrap ${balance > 0 ? 'text-amber-400' : 'text-green-400'}`}>{formatCurrency(balance)}</td>
                                    </tr>
                                  )
                                }
                              })}
                              {/* Grand total row */}
                              <tr className="border-t-2 border-surface-600 bg-surface-800/80">
                                <td colSpan={7} className="px-2 py-3 font-bold text-slate-300 text-right text-xs">Grand Total</td>
                                <td className="px-2 py-3 text-right font-bold text-red-400">{formatCurrency(parseFloat(statementData.summary.total_charged ?? statementData.summary.total_invoiced))}</td>
                                <td className="px-2 py-3 text-right font-bold text-green-400">{formatCurrency(parseFloat(statementData.summary.total_paid))}</td>
                                <td className={`px-2 py-3 text-right font-bold ${parseFloat(statementData.summary.balance_due) > 0 ? 'text-amber-400' : 'text-green-400'}`}>{formatCurrency(parseFloat(statementData.summary.balance_due))}</td>
                              </tr>
                            </tbody>
                          </table>
                        </div>
                      )
                    })()}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Record Debit modal */}
      {showDebitModal && selected && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowDebitModal(false)} />
          <div className="relative card w-full max-w-md p-6 space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold text-white">Record Manual Debit</h2>
                <p className="text-xs text-slate-500">{selected.name}</p>
              </div>
              <button onClick={() => setShowDebitModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Amount *</label>
                <input className="input" placeholder="0.00" value={debitForm.amount}
                  onChange={(e) => setDebitForm({ ...debitForm, amount: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Date *</label>
                <DateInput value={debitForm.debit_date} onChange={(v) => setDebitForm({ ...debitForm, debit_date: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Reference</label>
                <input className="input" placeholder="e.g. DEBIT-001" value={debitForm.reference}
                  onChange={(e) => setDebitForm({ ...debitForm, reference: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Description</label>
                <textarea className="input resize-none" rows={2} placeholder="Reason for debit charge…"
                  value={debitForm.description} onChange={(e) => setDebitForm({ ...debitForm, description: e.target.value })} />
              </div>
            </div>
            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm"
                onClick={() => setShowDebitModal(false)}>Cancel</button>
              <button className="flex-1 py-2.5 rounded-xl bg-orange-600 hover:bg-orange-700 text-white font-semibold text-sm disabled:opacity-50 flex items-center justify-center gap-2"
                onClick={handleRecordDebit} disabled={savingDebit}>
                {savingDebit ? <Loader2 size={16} className="animate-spin" /> : <MinusCircle size={16} />}
                {savingDebit ? 'Saving…' : 'Record Debit'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative card w-full max-w-lg p-6 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">New Customer</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white">
                <X size={20} />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Full Name *<FieldTooltip text="The person or business name. This appears on all their invoices and account statements." /></label>
                <input
                  className="input"
                  placeholder="e.g., Aisha Musa"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Type<FieldTooltip text="Categorise your customer — Retail for individuals, Wholesale for bulk buyers, Corporate for businesses. Helps with filtering and pricing decisions." /></label>
                <select className="input" value={form.customer_type} onChange={(e) => setForm({ ...form, customer_type: e.target.value })}>
                  {CUSTOMER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Credit Limit<FieldTooltip text="The maximum amount this customer is allowed to owe you at any time. Set to 0 to block credit sales. The app warns you when they approach this limit." /></label>
                <input
                  type="number"
                  className="input"
                  placeholder="0"
                  value={form.credit_limit}
                  onChange={(e) => setForm({ ...form, credit_limit: e.target.value })}
                  min="0"
                />
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Phone<FieldTooltip text="Customer's phone number. Shown on invoices and useful for follow-ups." /></label>
                <input
                  className="input"
                  placeholder="+234…"
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Email<FieldTooltip text="Customer's email. Used to send invoices and payment links directly from the app." /></label>
                <input
                  type="email"
                  className="input"
                  placeholder="customer@email.com"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </div>

              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Shipping Address<FieldTooltip text="The customer's shipping/delivery address. Printed on invoices and delivery notes." /></label>
                <textarea
                  className="input resize-none"
                  rows={2}
                  placeholder="e.g. 12 Adeola Hopewell St, Victoria Island, Lagos"
                  value={form.address}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
                />
              </div>
            </div>

            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowModal(false)}>
                Cancel
              </button>
              <button className="btn-primary flex-1 py-2.5 disabled:opacity-50" onClick={handleCreate} disabled={saving}>
                {saving ? 'Saving…' : 'Create Customer'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
