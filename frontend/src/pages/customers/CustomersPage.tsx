import { useEffect, useState } from 'react'
import { Plus, Search, Users, X, Pencil, Loader2, FileText, RefreshCw, Download, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { customerApi } from '@/services/api'
import { formatCurrency, formatDate, getStatusColor, getCurrencySymbol } from '@/lib/utils'
import DateInput from '@/components/DateInput'
import { useAuthStore } from '@/store/authStore'
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

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await customerApi.list({ search, customer_type: typeFilter || undefined })
      setCustomers(data.results ?? data)
    } catch { toast.error('Failed to load customers') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [search, typeFilter])

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
    const doc = new jsPDF({ unit: 'mm', format: 'a4' })
    const sym = getCurrencySymbol()
    const pageW = doc.internal.pageSize.getWidth()

    // Resolve brand color
    const brandRgb = (hex?: string): [number, number, number] => {
      const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
      if (!m) return [249, 115, 22]
      return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
    }
    const BRAND = brandRgb(organisation?.brand_color)

    // Helper to fetch URL → base64 data URL
    const fetchDataUrl = async (url: string): Promise<string | null> => {
      try {
        const res = await fetch(url)
        const blob = await res.blob()
        return await new Promise<string>((resolve, reject) => {
          const r = new FileReader()
          r.onloadend = () => resolve(r.result as string)
          r.onerror = reject
          r.readAsDataURL(blob)
        })
      } catch { return null }
    }

    let y = 8
    const HEADER_H = 42

    // ── Header: letterhead banner OR dark block ────────────────────────────────
    const useLetterhead = organisation?.use_letterhead && organisation?.letterhead
    const isImageLetterhead = useLetterhead && /\.(png|jpe?g|gif|webp|svg)(\?|$)/i.test(organisation!.letterhead!)

    if (isImageLetterhead) {
      const lhData = await fetchDataUrl(organisation!.letterhead!)
      if (lhData) {
        doc.addImage(lhData, 'PNG', 0, 0, pageW, 30)
        y = 32
        // Company name below banner
        doc.setFontSize(10)
        doc.setFont('helvetica', 'bold')
        doc.setTextColor(30, 41, 59)
        doc.text(organisation?.name ?? 'Company', 10, y + 6)
        doc.setFontSize(7.5)
        doc.setFont('helvetica', 'normal')
        doc.setTextColor(100, 116, 139)
        const subLines: string[] = []
        if (organisation?.address) subLines.push(organisation.address)
        if (organisation?.email) subLines.push(organisation.email)
        if (organisation?.phone) subLines.push(organisation.phone)
        subLines.forEach((line, idx) => doc.text(line, 10, y + 11 + idx * 4))
        // Title right
        doc.setFontSize(14)
        doc.setFont('helvetica', 'bold')
        doc.setTextColor(30, 41, 59)
        doc.text('CUSTOMER STATEMENT', pageW - 10, y + 6, { align: 'right' })
        doc.setFontSize(8)
        doc.setFont('helvetica', 'normal')
        doc.setTextColor(100, 116, 139)
        doc.text(`Period: ${formatDate(stmtFrom)} — ${formatDate(stmtTo)}`, pageW - 10, y + 13, { align: 'right' })
        y = y + 11 + subLines.length * 4 + 8
      } else {
        // letterhead URL failed to load — fall back to dark header block
        doc.setFillColor(15, 23, 42); doc.rect(0, 0, pageW, HEADER_H, 'F')
        doc.setFontSize(15); doc.setTextColor(255, 255, 255); doc.setFont('helvetica', 'bold')
        doc.text(organisation?.name ?? 'Company', 10, 13)
        doc.setFontSize(14); doc.text('CUSTOMER STATEMENT', pageW - 10, 13, { align: 'right' })
        y = HEADER_H + 8
      }
    } else {
      // Default: colored dark header block
      doc.setFillColor(15, 23, 42)
      doc.rect(0, 0, pageW, HEADER_H, 'F')

      // Load logo image if available
      let logoDataUrl: string | null = null
      if (organisation?.logo) logoDataUrl = await fetchDataUrl(organisation.logo)

      // Logo (left)
      if (logoDataUrl) doc.addImage(logoDataUrl, 'PNG', 10, 5, 32, 16)

      // Company name + details
      const nameY = logoDataUrl ? 26 : 13
      doc.setFontSize(logoDataUrl ? 10 : 15)
      doc.setTextColor(255, 255, 255)
      doc.setFont('helvetica', 'bold')
      doc.text(organisation?.name ?? 'Company', 10, nameY)
      doc.setFontSize(7.5)
      doc.setFont('helvetica', 'normal')
      doc.setTextColor(148, 163, 184)
      const subLines: string[] = []
      if (organisation?.address) subLines.push(organisation.address)
      if (organisation?.email) subLines.push(organisation.email)
      if (organisation?.phone) subLines.push(organisation.phone)
      if (organisation?.tax_id) subLines.push(`Tax ID: ${organisation.tax_id}`)
      subLines.forEach((line, idx) => doc.text(line, 10, nameY + 5 + idx * 4))

      // Title (right)
      doc.setFontSize(14)
      doc.setTextColor(255, 255, 255)
      doc.setFont('helvetica', 'bold')
      doc.text('CUSTOMER STATEMENT', pageW - 10, 13, { align: 'right' })
      doc.setFontSize(8)
      doc.setFont('helvetica', 'normal')
      doc.setTextColor(148, 163, 184)
      doc.text(`Period: ${formatDate(stmtFrom)} — ${formatDate(stmtTo)}`, pageW - 10, 20, { align: 'right' })
      doc.text(`Generated: ${formatDate(new Date().toISOString().split('T')[0])}`, pageW - 10, 26, { align: 'right' })

      y = HEADER_H + 8
    }
    // Customer block
    doc.setFontSize(10)
    doc.setFont('helvetica', 'bold')
    doc.setTextColor(30, 41, 59)
    doc.text('Bill To:', 14, y)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(9)
    doc.setTextColor(51, 65, 85)
    doc.text(selected.name, 14, y + 5)
    doc.text(selected.code, 14, y + 10)
    if (selected.email) doc.text(selected.email, 14, y + 15)
    if (selected.phone) doc.text(selected.phone, 14, y + 20)

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

    // Invoices table
    if (statementData.invoices.length > 0) {
      doc.setFontSize(9)
      doc.setFont('helvetica', 'bold')
      doc.setTextColor(30, 41, 59)
      doc.text('Invoices', 14, y)
      y += 4
      autoTable(doc, {
        startY: y,
        head: [['Invoice #', 'Date', 'Due Date', 'Total', 'Paid', 'Balance', 'Status']],
        body: statementData.invoices.map((inv: any) => [
          inv.invoice_number,
          formatDate(inv.issue_date),
          inv.due_date ? formatDate(inv.due_date) : '—',
          `${sym}${parseFloat(inv.total_amount).toLocaleString('en', { minimumFractionDigits: 2 })}`,
          `${sym}${parseFloat(inv.amount_paid).toLocaleString('en', { minimumFractionDigits: 2 })}`,
          `${sym}${parseFloat(inv.amount_due).toLocaleString('en', { minimumFractionDigits: 2 })}`,
          inv.status.replace('_', ' ').toUpperCase(),
        ]),
        styles: { fontSize: 8, cellPadding: 3 },
        headStyles: { fillColor: BRAND, textColor: 255, fontStyle: 'bold', fontSize: 7 },
        columnStyles: { 0: { fontStyle: 'bold' }, 6: { fontStyle: 'bold' } },
        alternateRowStyles: { fillColor: [248, 250, 252] },
        margin: { left: 14, right: 14 },
      })
      y = (doc as any).lastAutoTable.finalY + 6
    }

    // Payments table
    if (statementData.payments.length > 0) {
      doc.setFontSize(9)
      doc.setFont('helvetica', 'bold')
      doc.setTextColor(30, 41, 59)
      doc.text('Payments Received', 14, y)
      y += 4
      autoTable(doc, {
        startY: y,
        head: [['Invoice #', 'Date', 'Method', 'Amount']],
        body: statementData.payments.map((p: any) => [
          p.invoice_number,
          formatDate(p.received_at),
          p.method.replace('_', ' '),
          `${sym}${parseFloat(p.amount).toLocaleString('en', { minimumFractionDigits: 2 })}`,
        ]),
        styles: { fontSize: 8, cellPadding: 3 },
        headStyles: { fillColor: [5, 150, 105], textColor: 255, fontStyle: 'bold', fontSize: 7 },
        alternateRowStyles: { fillColor: [240, 253, 244] },
        margin: { left: 14, right: 14 },
      })
    }

    // Bank details block (if configured)
    const hasBankDetails = organisation?.bank_name || organisation?.bank_account_number
    if (hasBankDetails) {
      const finalY = (doc as any).lastAutoTable?.finalY ?? y
      const by = finalY + 8
      doc.setFillColor(241, 245, 249)
      doc.roundedRect(14, by, pageW - 28, 22, 2, 2, 'F')
      doc.setFontSize(7.5)
      doc.setFont('helvetica', 'bold')
      doc.setTextColor(30, 41, 59)
      doc.text('PAYMENT DETAILS', 18, by + 6)
      doc.setFont('helvetica', 'normal')
      doc.setTextColor(51, 65, 85)
      const bankParts: string[] = []
      if (organisation?.bank_name) bankParts.push(`Bank: ${organisation.bank_name}`)
      if (organisation?.bank_account_name) bankParts.push(`Account Name: ${organisation.bank_account_name}`)
      if (organisation?.bank_account_number) bankParts.push(`Account No: ${organisation.bank_account_number}`)
      if (organisation?.bank_sort_code) bankParts.push(`Sort Code: ${organisation.bank_sort_code}`)
      const midIdx = Math.ceil(bankParts.length / 2)
      bankParts.slice(0, midIdx).forEach((p, i) => doc.text(p, 18, by + 12 + i * 4))
      bankParts.slice(midIdx).forEach((p, i) => doc.text(p, pageW / 2, by + 12 + i * 4))
    }

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

    // Use blob URL instead of doc.save() — doc.save() is broken in Tauri WebView2
    const blob = doc.output('blob')
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `statement-${selected.code}-${stmtFrom}-${stmtTo}.pdf`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 30000)
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
        <button className="btn-primary sm:ml-auto" onClick={() => setShowModal(true)}>
          <Plus size={16} /> New Customer
        </button>
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
                  { label: 'Status', value: selected.is_credit_blocked ? 'Credit Blocked' : 'Active' },
                ].map(({ label, value }) => (
                  <div key={label} className="flex justify-between py-2 border-b border-surface-700">
                    <span className="text-slate-400">{label}</span>
                    <span className="text-white font-medium">{value}</span>
                  </div>
                ))}
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
                <label className="text-xs text-slate-400 mb-1 block">Full Name *</label>
                <input className="input" value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Type</label>
                <select className="input" value={editForm.customer_type} onChange={(e) => setEditForm({ ...editForm, customer_type: e.target.value })}>
                  {CUSTOMER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Credit Limit</label>
                <input type="number" className="input" value={editForm.credit_limit} min="0"
                  onChange={(e) => setEditForm({ ...editForm, credit_limit: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Phone</label>
                <input className="input" value={editForm.phone} onChange={(e) => setEditForm({ ...editForm, phone: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Email</label>
                <input type="email" className="input" value={editForm.email} onChange={(e) => setEditForm({ ...editForm, email: e.target.value })} />
              </div>
              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Address</label>
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
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowStatement(false)} />
          <div className="relative bg-surface-900 border border-surface-700 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-surface-700">
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
                <button onClick={() => setShowStatement(false)} className="btn-ghost p-2"><X size={18} /></button>
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
                  {/* Summary KPIs */}
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      { label: 'Total Invoiced', value: formatCurrency(statementData.summary.total_invoiced), color: 'text-white' },
                      { label: 'Total Paid', value: formatCurrency(statementData.summary.total_paid), color: 'text-green-400' },
                      { label: 'Balance Due', value: formatCurrency(statementData.summary.balance_due), color: parseFloat(statementData.summary.balance_due) > 0 ? 'text-red-400' : 'text-green-400' },
                    ].map(({ label, value, color }) => (
                      <div key={label} className="bg-surface-800 rounded-xl p-3 text-center">
                        <p className="text-xs text-slate-500 mb-1">{label}</p>
                        <p className={`text-base font-bold ${color}`}>{value}</p>
                      </div>
                    ))}
                  </div>

                  {/* Invoices */}
                  <div>
                    <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Invoices ({statementData.invoices.length})</p>
                    {statementData.invoices.length === 0 ? (
                      <p className="text-slate-600 text-sm text-center py-4">No invoices in this period</p>
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-surface-700">
                              {['Invoice #', 'Date', 'Total', 'Paid', 'Due', 'Status'].map((h) => (
                                <th key={h} className="px-3 py-2 text-left text-slate-400 font-medium">{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {statementData.invoices.map((inv: any) => (
                              <tr key={inv.id} className="border-b border-surface-700/50">
                                <td className="px-3 py-2 font-mono text-brand-400">{inv.invoice_number}</td>
                                <td className="px-3 py-2 text-slate-400">{formatDate(inv.issue_date)}</td>
                                <td className="px-3 py-2 text-white">{formatCurrency(inv.total_amount)}</td>
                                <td className="px-3 py-2 text-green-400">{formatCurrency(inv.amount_paid)}</td>
                                <td className="px-3 py-2 text-red-400">{formatCurrency(inv.amount_due)}</td>
                                <td className="px-3 py-2">
                                  <span className={getStatusColor(inv.status)}>{inv.status.replace('_', ' ')}</span>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>

                  {/* Payments */}
                  {statementData.payments.length > 0 && (
                    <div>
                      <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">Payments ({statementData.payments.length})</p>
                      <div className="space-y-1.5">
                        {statementData.payments.map((p: any) => (
                          <div key={p.id} className="flex items-center justify-between bg-surface-800 rounded-lg px-3 py-2">
                            <div>
                              <p className="text-xs font-medium text-white">{p.invoice_number}</p>
                              <p className="text-[10px] text-slate-500">{p.method.replace('_', ' ')} · {formatDate(p.received_at)}</p>
                            </div>
                            <p className="text-sm font-semibold text-green-400">{formatCurrency(p.amount)}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
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
                <label className="text-xs text-slate-400 mb-1 block">Full Name *</label>
                <input
                  className="input"
                  placeholder="e.g., Aisha Musa"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Type</label>
                <select className="input" value={form.customer_type} onChange={(e) => setForm({ ...form, customer_type: e.target.value })}>
                  {CUSTOMER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Credit Limit</label>
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
                <label className="text-xs text-slate-400 mb-1 block">Phone</label>
                <input
                  className="input"
                  placeholder="+234…"
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                />
              </div>

              <div>
                <label className="text-xs text-slate-400 mb-1 block">Email</label>
                <input
                  type="email"
                  className="input"
                  placeholder="customer@email.com"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </div>

              <div className="col-span-2">
                <label className="text-xs text-slate-400 mb-1 block">Address</label>
                <textarea
                  className="input resize-none"
                  rows={2}
                  placeholder="Street, City, State"
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
