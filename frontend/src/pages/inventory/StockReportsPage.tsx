import { useState, useEffect } from 'react'
import {
  ClipboardCheck, BarChart2, ArrowLeftRight, AlertTriangle,
  CheckCircle, XCircle, TrendingDown, FileText, FileDown, Table2,
  Pencil, Check, X as XIcon, Loader2,
} from 'lucide-react'
import { stockReportApi, inventoryApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import type { Organisation } from '@/types'
import toast from 'react-hot-toast'
import DateInput from '@/components/DateInput'
// @ts-ignore
import autoTable from 'jspdf-autotable'
import jsPDF from 'jspdf'
import { saveBlobFile } from '@/lib/saveBlobFile'

type ReportTab = 'availability' | 'usage' | 'transfers' | 'stock_card'

interface AvailabilityRow {
  id: string
  sku: string
  name: string
  category: string | null
  unit_of_measure: string
  quantity_on_hand: number
  min_safety_level: number
  max_safety_level: number | null
  reorder_quantity: number
  quantity_in_pack: number
  cost_price: number
  selling_price: number
  status: 'ok' | 'low' | 'out_of_stock' | 'overstocked'
  warehouses: { warehouse: string; qty: number }[]
}

interface UsageRow {
  id: string
  sku: string
  name: string
  unit_of_measure: string
  total_used: number
}

interface UsageTransaction {
  date: string
  product_name: string
  product_sku: string
  warehouse: string
  quantity: number
  unit_cost: string
  invoice_no: string
  customer: string
  batch_number: string
  sold_by: string
  notes: string
}

interface TransferRow {
  id: string
  date: string
  movement_type: string
  movement_label: string
  product_name: string
  product_sku: string
  warehouse: string
  quantity: number
  unit_cost: string
  reference: string
  supplier: string
  batch_number: string
  batch_expiry: string
  received_by: string
  notes: string
}

interface StockCardRow {
  date: string
  warehouse: string
  in: number | null
  out: number | null
  balance: number
  unit_cost: string
  invoice_no: string
  batch_number: string
  remark: string
  created_by: string
}

const STATUS_BADGE: Record<string, string> = {
  ok: 'badge-green',
  low: 'badge-amber',
  out_of_stock: 'badge-red',
  overstocked: 'badge-blue',
}

const STATUS_LABEL: Record<string, string> = {
  ok: 'In Stock',
  low: 'Low Stock',
  out_of_stock: 'Out of Stock',
  overstocked: 'Overstocked',
}

const MOVEMENT_LABEL: Record<string, string> = {
  purchase: 'Purchase',
  purchase_in: 'Purchase In',
  transfer_in: 'Transfer In',
  transfer_out: 'Transfer Out',
  sale_out: 'Sale Out',
  adjustment_in: 'Adjustment In',
  adjustment_out: 'Adjustment Out',
}

// ── Export helpers ─────────────────────────────────────────────────────────────

async function exportCSV(headers: string[], rows: (string | number | null)[][], filename: string) {
  const csv = [headers, ...rows]
    .map((r) => r.map((v) => `"${String(v ?? '').replace(/"/g, '""')}"`).join(','))
    .join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  await saveBlobFile(blob, filename)
}

function buildDocBase(org?: Organisation | null) {
  const hexToRgb = (hex?: string): [number,number,number] => {
    const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
    if (!m) return [249, 115, 22]; return [parseInt(m[1],16), parseInt(m[2],16), parseInt(m[3],16)]
  }
  return {
    BRAND: hexToRgb(org?.brand_color) as [number,number,number],
    DARK:  [30, 30, 30] as [number,number,number],
    MUTED: [100, 100, 100] as [number,number,number],
    tmpl:  org?.invoice_template ?? 'classic',
    displayName: org?.invoice_company_name?.trim() || org?.name || 'Audity',
    orgAddress: org?.address,
    orgEmail: org?.email,
    orgPhone: org?.phone,
    pdfFont: (org?.company_name_font?.toLowerCase().includes('times') ? 'times'
      : org?.company_name_font?.toLowerCase().includes('courier') ? 'courier' : 'helvetica') as string,
  }
}

async function exportAvailabilityPDF(rows: AvailabilityRow[], org?: Organisation | null) {
  const { applyDocHeader, templateHeadFill } = await import('@/lib/pdfUtils')
  const { BRAND, DARK, MUTED, tmpl, displayName, orgAddress, orgEmail, orgPhone, pdfFont } = buildDocBase(org)
  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()
  const y = applyDocHeader(doc, {
    tmpl, pageW, BRAND, DARK, MUTED, displayName, orgAddress, orgEmail, orgPhone, pdfFont,
    docTitle: 'STOCK AVAILABILITY',
    metaRows: [['Exported', new Date().toLocaleDateString()]],
  })
  autoTable(doc, {
    startY: y,
    head: [['SKU', 'Product', 'Unit', 'On Hand', 'Min', 'Max', 'Qty/Pack', 'Status']],
    body: rows.map((r) => [r.sku, r.name, r.unit_of_measure, r.quantity_on_hand, r.min_safety_level, r.max_safety_level ?? '—', r.quantity_in_pack, STATUS_LABEL[r.status]]),
    styles: { fontSize: 8 }, headStyles: { fillColor: templateHeadFill(tmpl, BRAND), textColor: [255,255,255], fontStyle: 'bold' },
    showHead: 'everyPage',
  })
  await saveBlobFile(doc.output('blob'), 'stock-availability.pdf')
}

async function exportAvailabilityCSV(rows: AvailabilityRow[]) {
  await exportCSV(
    ['SKU', 'Product', 'Unit', 'On Hand', 'Min Level', 'Max Level', 'Qty/Pack', 'Status'],
    rows.map((r) => [r.sku, r.name, r.unit_of_measure, r.quantity_on_hand, r.min_safety_level, r.max_safety_level ?? '', r.quantity_in_pack, STATUS_LABEL[r.status]]),
    'stock-availability.csv'
  )
}

async function exportUsagePDF(rows: UsageRow[], txRows: UsageTransaction[], org?: Organisation | null) {
  const { applyDocHeader, templateHeadFill } = await import('@/lib/pdfUtils')
  const { BRAND, DARK, MUTED, tmpl, displayName, orgAddress, orgEmail, orgPhone, pdfFont } = buildDocBase(org)
  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()
  let y = applyDocHeader(doc, {
    tmpl, pageW, BRAND, DARK, MUTED, displayName, orgAddress, orgEmail, orgPhone, pdfFont,
    docTitle: 'STOCK USAGE REPORT',
    metaRows: [['Exported', new Date().toLocaleDateString()]],
  })
  autoTable(doc, {
    startY: y,
    head: [['#', 'SKU', 'Product', 'Unit', 'Total Used']],
    body: rows.map((r, i) => [i + 1, r.sku, r.name, r.unit_of_measure, r.total_used]),
    styles: { fontSize: 8 }, headStyles: { fillColor: templateHeadFill(tmpl, BRAND), textColor: [255,255,255], fontStyle: 'bold' },
    showHead: 'everyPage',
  })
  if (txRows.length > 0) {
    y = (doc as any).lastAutoTable.finalY + 8
    doc.setFontSize(9).setTextColor(100).text('Transaction Breakdown', 14, y)
    autoTable(doc, {
      startY: y + 3,
      head: [['Date', 'Product', 'Warehouse', 'Qty', 'Unit Cost', 'Invoice', 'Customer', 'Batch', 'Sold By']],
      body: txRows.map((r) => [r.date, r.product_name, r.warehouse, r.quantity, r.unit_cost || '—', r.invoice_no || '—', r.customer || '—', r.batch_number || '—', r.sold_by || '—']),
      styles: { fontSize: 7 }, headStyles: { fillColor: templateHeadFill(tmpl, BRAND), textColor: [255,255,255], fontStyle: 'bold' },
      showHead: 'everyPage',
    })
  }
  await saveBlobFile(doc.output('blob'), 'stock-usage.pdf')
}

async function exportUsageCSV(rows: UsageRow[], txRows: UsageTransaction[]) {
  await exportCSV(['SKU', 'Product', 'Unit', 'Total Used'], rows.map((r) => [r.sku, r.name, r.unit_of_measure, r.total_used]), 'stock-usage-summary.csv')
  if (txRows.length > 0) {
    await exportCSV(
      ['Date', 'Product', 'SKU', 'Warehouse', 'Qty', 'Unit Cost', 'Invoice No', 'Customer', 'Batch', 'Sold By', 'Notes'],
      txRows.map((r) => [r.date, r.product_name, r.product_sku, r.warehouse, r.quantity, r.unit_cost, r.invoice_no, r.customer, r.batch_number, r.sold_by, r.notes]),
      'stock-usage-transactions.csv'
    )
  }
}

async function exportTransfersPDF(rows: TransferRow[], org?: Organisation | null) {
  const { applyDocHeader, templateHeadFill } = await import('@/lib/pdfUtils')
  const { BRAND, DARK, MUTED, tmpl, displayName, orgAddress, orgEmail, orgPhone, pdfFont } = buildDocBase(org)
  const doc = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'landscape' })
  const pageW = doc.internal.pageSize.getWidth()
  const y = applyDocHeader(doc, {
    tmpl, pageW, BRAND, DARK, MUTED, displayName, orgAddress, orgEmail, orgPhone, pdfFont,
    docTitle: 'STOCK TRANSFER & RECEIPT REPORT',
    metaRows: [['Exported', new Date().toLocaleDateString()]],
  })
  autoTable(doc, {
    startY: y,
    head: [['Date', 'Type', 'Product', 'SKU', 'Warehouse', 'Qty', 'Unit Cost', 'Supplier', 'Batch', 'Expiry', 'Reference', 'Received By', 'Notes']],
    body: rows.map((r) => [r.date, r.movement_label || r.movement_type, r.product_name, r.product_sku, r.warehouse, r.quantity, r.unit_cost || '—', r.supplier || '—', r.batch_number || '—', r.batch_expiry || '—', r.reference || '—', r.received_by || '—', r.notes || '']),
    styles: { fontSize: 7 }, headStyles: { fillColor: templateHeadFill(tmpl, BRAND), textColor: [255,255,255], fontStyle: 'bold' },
    showHead: 'everyPage',
  })
  await saveBlobFile(doc.output('blob'), 'stock-transfers.pdf')
}

async function exportTransfersCSV(rows: TransferRow[]) {
  await exportCSV(
    ['Date', 'Type', 'Product', 'SKU', 'Warehouse', 'Qty', 'Unit Cost', 'Supplier', 'Batch No', 'Batch Expiry', 'Reference', 'Received By', 'Notes'],
    rows.map((r) => [r.date, r.movement_label || r.movement_type, r.product_name, r.product_sku, r.warehouse, r.quantity, r.unit_cost, r.supplier, r.batch_number, r.batch_expiry, r.reference, r.received_by, r.notes]),
    'stock-transfers.csv'
  )
}

async function exportStockCardPDF(rows: StockCardRow[], productName: string, productSku: string, org?: Organisation | null) {
  const { applyDocHeader, templateHeadFill } = await import('@/lib/pdfUtils')
  const { BRAND, DARK, MUTED, tmpl, displayName, orgAddress, orgEmail, orgPhone, pdfFont } = buildDocBase(org)
  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  const pageW = doc.internal.pageSize.getWidth()
  const y = applyDocHeader(doc, {
    tmpl, pageW, BRAND, DARK, MUTED, displayName, orgAddress, orgEmail, orgPhone, pdfFont,
    docTitle: 'STOCK CARD',
    metaRows: [['Product', productName], ['SKU', productSku], ['Exported', new Date().toLocaleDateString()]],
  })
  autoTable(doc, {
    startY: y,
    head: [['Date', 'Warehouse', 'IN', 'OUT', 'BALANCE', 'Unit Cost', 'Invoice No', 'Batch', 'Remark', 'By']],
    body: rows.map((r) => [r.date, r.warehouse, r.in ?? '', r.out ?? '', r.balance, r.unit_cost || '—', r.invoice_no, r.batch_number || '—', r.remark, r.created_by]),
    styles: { fontSize: 7.5 }, headStyles: { fillColor: templateHeadFill(tmpl, BRAND), textColor: [255,255,255], fontStyle: 'bold' },
    showHead: 'everyPage',
  })
  await saveBlobFile(doc.output('blob'), `stock-card-${productSku}.pdf`)
}

async function exportStockCardCSV(rows: StockCardRow[], productSku: string) {
  await exportCSV(
    ['Date', 'Warehouse', 'IN', 'OUT', 'BALANCE', 'Unit Cost', 'Invoice No', 'Batch No', 'Remark', 'By'],
    rows.map((r) => [r.date, r.warehouse, r.in ?? '', r.out ?? '', r.balance, r.unit_cost, r.invoice_no, r.batch_number, r.remark, r.created_by]),
    `stock-card-${productSku}.csv`
  )
}

// ──────────────────────────────────────────────────────────────────────────────

export default function StockReportsPage() {
  const { organisation } = useAuthStore()
  const [tab, setTab] = useState<ReportTab>('availability')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)

  const [availability, setAvailability] = useState<AvailabilityRow[]>([])
  const [usage, setUsage] = useState<UsageRow[]>([])
  const [usageTransactions, setUsageTransactions] = useState<UsageTransaction[]>([])
  const [showUsageTx, setShowUsageTx] = useState(false)
  const [transfers, setTransfers] = useState<TransferRow[]>([])
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editVals, setEditVals] = useState<{ min: string; max: string; qty_per_pack: string }>({ min: '', max: '', qty_per_pack: '' })
  const [saving, setSaving] = useState(false)

  // Stock card state
  const [cardProduct, setCardProduct] = useState('')
  const [cardRows, setCardRows] = useState<StockCardRow[]>([])
  const [cardProductName, setCardProductName] = useState('')
  const [cardProductSku, setCardProductSku] = useState('')
  const [products, setProducts] = useState<{ id: string; name: string; sku: string }[]>([])

  useEffect(() => {
    const fetchProds = () => {
      inventoryApi.products({ page_size: 500 }).then(({ data }) => {
        const list = (data.results ?? data) as { id: string; name: string; sku: string }[]
        if (list.length > 0) setProducts(list)
      }).catch(() => {})
    }
    fetchProds()
    // Retry when reconnecting after an offline period
    window.addEventListener('online', fetchProds)
    return () => window.removeEventListener('online', fetchProds)
  }, [])

  const toISO = (dd: string) => {
    if (!dd) return ''
    const [d, m, y] = dd.split('/')
    if (!d || !m || !y) return dd
    return `${y}-${m}-${d}`
  }

  const runReport = async () => {
    setLoading(true)
    setLoaded(false)
    try {
      const params: Record<string, string> = {}
      if (dateFrom) params.date_from = toISO(dateFrom)
      if (dateTo) params.date_to = toISO(dateTo)

      if (tab === 'availability') {
        const { data } = await stockReportApi.availability(params)
        setAvailability(data)
      } else if (tab === 'usage') {
        const { data } = await stockReportApi.usage(params)
        setUsage(data.summary ?? data)
        setUsageTransactions(data.transactions ?? [])
        setShowUsageTx(false)
      } else if (tab === 'transfers') {
        const { data } = await stockReportApi.transfers(params)
        setTransfers(data)
      } else {
        if (!cardProduct) { toast.error('Select a product first'); setLoading(false); return }
        const { data } = await stockReportApi.stockCard({ ...params, product_id: cardProduct })
        setCardRows(data.rows)
        setCardProductName(data.product.name)
        setCardProductSku(data.product.sku)
      }
      setLoaded(true)
    } catch {
      toast.error('Failed to load report')
    } finally {
      setLoading(false)
    }
  }

  const handleTabChange = (t: ReportTab) => {
    setTab(t)
    setLoaded(false)
    setStatusFilter('all')
    setEditingId(null)
  }

  const startEdit = (row: AvailabilityRow) => {
    setEditingId(row.id)
    setEditVals({
      min: String(row.min_safety_level),
      max: row.max_safety_level != null ? String(row.max_safety_level) : '',
      qty_per_pack: String(row.quantity_in_pack),
    })
  }

  const saveEdit = async (row: AvailabilityRow) => {
    setSaving(true)
    try {
      const payload: Record<string, unknown> = { reorder_level: parseInt(editVals.min) || 0, quantity_in_pack: parseFloat(editVals.qty_per_pack) || 1 }
      if (editVals.max !== '') payload.max_stock_level = parseInt(editVals.max)
      else payload.max_stock_level = null
      await inventoryApi.updateProduct(row.id, payload)
      setAvailability((prev) => prev.map((r) => r.id === row.id ? {
        ...r,
        min_safety_level: parseInt(editVals.min) || 0,
        max_safety_level: editVals.max !== '' ? parseInt(editVals.max) : null,
        quantity_in_pack: parseFloat(editVals.qty_per_pack) || 1,
      } : r))
      setEditingId(null)
      toast.success('Product updated')
    } catch {
      toast.error('Failed to update product')
    } finally {
      setSaving(false)
    }
  }

  const stats = {
    ok: availability.filter((r) => r.status === 'ok').length,
    low: availability.filter((r) => r.status === 'low').length,
    out: availability.filter((r) => r.status === 'out_of_stock').length,
    over: availability.filter((r) => r.status === 'overstocked').length,
  }
  const filteredAvailability =
    statusFilter === 'all' ? availability : availability.filter((r) => r.status === statusFilter)

  const TABS: { id: ReportTab; label: string; icon: React.ElementType }[] = [
    { id: 'availability', label: 'Stock Availability', icon: ClipboardCheck },
    { id: 'usage', label: 'Usage Report', icon: BarChart2 },
    { id: 'transfers', label: 'Transfer Report', icon: ArrowLeftRight },
    { id: 'stock_card', label: 'Stock Card', icon: FileText },
  ]

  const ExportBar = ({ onPDF, onCSV }: { onPDF: () => void; onCSV: () => void }) => (
    <div className="flex gap-2">
      <button onClick={onPDF} className="btn-ghost text-xs flex items-center gap-1.5 py-1.5 px-3">
        <FileDown size={14} /> PDF
      </button>
      <button onClick={onCSV} className="btn-ghost text-xs flex items-center gap-1.5 py-1.5 px-3">
        <Table2 size={14} /> Excel
      </button>
    </div>
  )

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <ClipboardCheck size={20} className="text-brand-400" />
          Stock Reports
        </h1>
        <p className="text-sm text-slate-400 mt-0.5">
          Availability, usage, transfer history, and stock card. Use date range to backdate reports.
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex flex-wrap gap-1 bg-surface-800 border border-surface-700 rounded-xl p-1 w-fit">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => handleTabChange(t.id)}
            className={[
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
              tab === t.id
                ? 'bg-brand-500 text-white shadow'
                : 'text-slate-400 hover:text-slate-200',
            ].join(' ')}
          >
            <t.icon size={15} />
            {t.label}
          </button>
        ))}
      </div>

      {/* Date controls */}
      <div className="card flex flex-wrap items-end gap-4">
        {tab === 'stock_card' && (
          <div className="w-full sm:w-64">
            <label className="label">Product</label>
            <select className="input" value={cardProduct} onChange={(e) => setCardProduct(e.target.value)}>
              <option value="">— Select product —</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>
              ))}
            </select>
          </div>
        )}
        <div>
          <label className="label">From</label>
          <DateInput value={dateFrom} onChange={setDateFrom} placeholder="DD/MM/YYYY" />
        </div>
        <div>
          <label className="label">To</label>
          <DateInput value={dateTo} onChange={setDateTo} placeholder="DD/MM/YYYY" />
        </div>
        <button
          onClick={runReport}
          disabled={loading}
          className="btn-primary flex items-center gap-2"
        >
          {loading ? 'Loading…' : 'Run Report'}
        </button>
        {loaded && tab === 'availability' && (
          <p className="text-xs text-slate-500 self-end pb-2">
            {availability.length} products
          </p>
        )}
      </div>

      {/* Results */}
      {!loaded && !loading && (
        <div className="card text-center py-12 text-slate-500 text-sm">
          {tab === 'stock_card' ? 'Select a product and click Run Report.' : 'Select a date range (optional) and click Run Report.'}
        </div>
      )}

      {loading && (
        <div className="card text-center py-12 text-slate-400 text-sm">Loading…</div>
      )}

      {/* ── Availability ── */}
      {loaded && tab === 'availability' && (
        <div className="space-y-4">
          {/* Summary tiles */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: 'In Stock', value: stats.ok, icon: CheckCircle, color: 'text-emerald-400', filter: 'ok' },
              { label: 'Low Stock', value: stats.low, icon: AlertTriangle, color: 'text-amber-400', filter: 'low' },
              { label: 'Out of Stock', value: stats.out, icon: XCircle, color: 'text-red-400', filter: 'out_of_stock' },
              { label: 'Overstocked', value: stats.over, icon: TrendingDown, color: 'text-blue-400', filter: 'overstocked' },
            ].map((s) => (
              <button
                key={s.filter}
                onClick={() => setStatusFilter(statusFilter === s.filter ? 'all' : s.filter)}
                className={[
                  'card flex items-center gap-3 cursor-pointer hover:border-brand-500/40 transition-all text-left',
                  statusFilter === s.filter ? 'ring-2 ring-brand-500/50 border-brand-500/40' : '',
                ].join(' ')}
              >
                <s.icon size={20} className={s.color} />
                <div>
                  <p className="text-lg font-bold text-white">{s.value}</p>
                  <p className="text-xs text-slate-400">{s.label}</p>
                </div>
              </button>
            ))}
          </div>

          <div className="flex justify-end">
            <ExportBar onPDF={() => exportAvailabilityPDF(filteredAvailability, organisation)} onCSV={() => exportAvailabilityCSV(filteredAvailability)} />
          </div>

          {/* Table */}
          <div className="card overflow-x-auto p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-700 text-xs text-slate-400 uppercase tracking-wider">
                  <th className="px-4 py-3 text-left">SKU / Product</th>
                  <th className="px-4 py-3 text-right">On Hand</th>
                  <th className="px-4 py-3 text-right">Min Level</th>
                  <th className="px-4 py-3 text-right">Max Level</th>
                  <th className="px-4 py-3 text-right">Qty/Pack</th>
                  <th className="px-4 py-3 text-left">Warehouses</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-center w-20"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-700/50">
                {filteredAvailability.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-slate-500">
                      No products match this filter.
                    </td>
                  </tr>
                ) : (
                  filteredAvailability.map((row) => {
                    const isEditing = editingId === row.id
                    return (
                    <tr key={row.id} className={`transition-colors ${isEditing ? 'bg-surface-700/50' : 'hover:bg-surface-700/30'}`}>
                      <td className="px-4 py-3">
                        <p className="font-medium text-white">{row.name}</p>
                        <p className="text-xs text-slate-500">{row.sku} · {row.unit_of_measure}</p>
                      </td>
                      <td className={[
                        'px-4 py-3 text-right font-bold',
                        row.status === 'out_of_stock' ? 'text-red-400' :
                        row.status === 'low' ? 'text-amber-400' : 'text-white',
                      ].join(' ')}>
                        {row.quantity_on_hand}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {isEditing ? (
                          <input type="number" className="input py-1 px-2 text-right w-20 text-sm" value={editVals.min} onChange={(e) => setEditVals((v) => ({ ...v, min: e.target.value }))} />
                        ) : (
                          <span className="text-slate-400">{row.min_safety_level}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {isEditing ? (
                          <input type="number" className="input py-1 px-2 text-right w-20 text-sm" placeholder="—" value={editVals.max} onChange={(e) => setEditVals((v) => ({ ...v, max: e.target.value }))} />
                        ) : (
                          <span className="text-slate-400">{row.max_safety_level ?? <span className="text-slate-600">—</span>}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {isEditing ? (
                          <input type="number" className="input py-1 px-2 text-right w-20 text-sm" value={editVals.qty_per_pack} onChange={(e) => setEditVals((v) => ({ ...v, qty_per_pack: e.target.value }))} />
                        ) : (
                          <span className="text-slate-400">{row.quantity_in_pack}</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {row.warehouses.length === 0 ? (
                          <span className="text-slate-600 text-xs">None</span>
                        ) : (
                          <div className="space-y-0.5">
                            {row.warehouses.map((w, i) => (
                              <p key={i} className="text-xs text-slate-400">
                                {w.warehouse}: <span className="text-slate-300">{w.qty}</span>
                              </p>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={STATUS_BADGE[row.status] + ' text-xs'}>
                          {STATUS_LABEL[row.status]}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        {isEditing ? (
                          <div className="flex items-center gap-1 justify-center">
                            <button onClick={() => saveEdit(row)} disabled={saving} className="p-1 rounded hover:bg-emerald-500/20 text-emerald-400 disabled:opacity-50">
                              {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                            </button>
                            <button onClick={() => setEditingId(null)} className="p-1 rounded hover:bg-red-500/20 text-red-400">
                              <XIcon size={14} />
                            </button>
                          </div>
                        ) : (
                          <button onClick={() => startEdit(row)} className="p-1 rounded hover:bg-surface-600 text-slate-500 hover:text-slate-300">
                            <Pencil size={13} />
                          </button>
                        )}
                      </td>
                    </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Usage ── */}
      {loaded && tab === 'usage' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex gap-2">
              <button
                onClick={() => setShowUsageTx(false)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${!showUsageTx ? 'bg-brand-500/20 text-brand-400 border border-brand-500/40' : 'text-slate-400 hover:bg-surface-700'}`}
              >Summary</button>
              <button
                onClick={() => setShowUsageTx(true)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${showUsageTx ? 'bg-brand-500/20 text-brand-400 border border-brand-500/40' : 'text-slate-400 hover:bg-surface-700'}`}
              >Transactions ({usageTransactions.length})</button>
            </div>
            <ExportBar onPDF={() => exportUsagePDF(usage, usageTransactions, organisation)} onCSV={() => exportUsageCSV(usage, usageTransactions)} />
          </div>

          {!showUsageTx ? (
            <div className="card overflow-x-auto p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700 text-xs text-slate-400 uppercase tracking-wider">
                    <th className="px-4 py-3 text-left">#</th>
                    <th className="px-4 py-3 text-left">SKU / Product</th>
                    <th className="px-4 py-3 text-left">Unit</th>
                    <th className="px-4 py-3 text-right">Total Used</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-700/50">
                  {usage.length === 0 ? (
                    <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-500">No sales movements in this period.</td></tr>
                  ) : usage.map((row, i) => (
                    <tr key={row.id} className="hover:bg-surface-700/30 transition-colors">
                      <td className="px-4 py-3 text-slate-600 text-xs">{i + 1}</td>
                      <td className="px-4 py-3"><p className="font-medium text-white">{row.name}</p><p className="text-xs text-slate-500">{row.sku}</p></td>
                      <td className="px-4 py-3 text-slate-400">{row.unit_of_measure}</td>
                      <td className="px-4 py-3 text-right font-bold text-white">{row.total_used}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="card overflow-x-auto p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700 text-xs text-slate-400 uppercase tracking-wider">
                    <th className="px-4 py-3 text-left whitespace-nowrap">Date</th>
                    <th className="px-4 py-3 text-left">Product</th>
                    <th className="px-4 py-3 text-left">Warehouse</th>
                    <th className="px-4 py-3 text-right whitespace-nowrap">Qty</th>
                    <th className="px-4 py-3 text-right whitespace-nowrap">Unit Cost</th>
                    <th className="px-4 py-3 text-left whitespace-nowrap">Invoice</th>
                    <th className="px-4 py-3 text-left">Customer</th>
                    <th className="px-4 py-3 text-left">Batch</th>
                    <th className="px-4 py-3 text-left whitespace-nowrap">Sold By</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-700/50">
                  {usageTransactions.length === 0 ? (
                    <tr><td colSpan={9} className="px-4 py-8 text-center text-slate-500">No transactions in this period.</td></tr>
                  ) : usageTransactions.map((row, i) => (
                    <tr key={i} className="hover:bg-surface-700/30 transition-colors">
                      <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">{row.date}</td>
                      <td className="px-4 py-3"><p className="text-white text-xs font-medium">{row.product_name}</p><p className="text-slate-500 text-xs">{row.product_sku}</p></td>
                      <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">{row.warehouse}</td>
                      <td className="px-4 py-3 text-right font-semibold text-red-400 text-xs">{row.quantity}</td>
                      <td className="px-4 py-3 text-right text-slate-400 text-xs">{row.unit_cost || '—'}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs font-mono">{row.invoice_no || '—'}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs">{row.customer || <span className="text-slate-600">Walk-in</span>}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs">{row.batch_number || '—'}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">{row.sold_by || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Transfers ── */}
      {loaded && tab === 'transfers' && (
        <div className="space-y-3">
          <div className="flex justify-end">
            <ExportBar onPDF={() => exportTransfersPDF(transfers, organisation)} onCSV={() => exportTransfersCSV(transfers)} />
          </div>
          <div className="card overflow-x-auto p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-700 text-xs text-slate-400 uppercase tracking-wider">
                  <th className="px-4 py-3 text-left whitespace-nowrap">Date</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Type</th>
                  <th className="px-4 py-3 text-left">Product</th>
                  <th className="px-4 py-3 text-left">Warehouse</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap">Qty</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap">Unit Cost</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Supplier</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Batch / Expiry</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Reference</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Received By</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-700/50">
                {transfers.length === 0 ? (
                  <tr><td colSpan={10} className="px-4 py-8 text-center text-slate-500">No stock transfers or receipts in this period.</td></tr>
                ) : transfers.map((row) => (
                  <tr key={row.id} className="hover:bg-surface-700/30 transition-colors">
                    <td className="px-4 py-3 text-slate-400 whitespace-nowrap text-xs">{row.date}</td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        row.movement_type === 'purchase_in' ? 'bg-emerald-500/15 text-emerald-400'
                        : row.movement_type === 'transfer_in' ? 'bg-brand-500/15 text-brand-400'
                        : 'bg-amber-500/15 text-amber-400'
                      }`}>{row.movement_label || MOVEMENT_LABEL[row.movement_type] || row.movement_type}</span>
                    </td>
                    <td className="px-4 py-3 min-w-[140px]">
                      <p className="font-medium text-white text-xs">{row.product_name}</p>
                      <p className="text-xs text-slate-500">{row.product_sku}</p>
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">{row.warehouse}</td>
                    <td className="px-4 py-3 text-right font-bold text-white text-xs whitespace-nowrap">{row.quantity}</td>
                    <td className="px-4 py-3 text-right text-slate-400 text-xs whitespace-nowrap">{row.unit_cost || '—'}</td>
                    <td className="px-4 py-3 text-xs">
                      {row.supplier ? <span className="text-emerald-400">{row.supplier}</span> : <span className="text-slate-600">—</span>}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {row.batch_number ? (
                        <p className="text-slate-300">{row.batch_number}</p>
                      ) : null}
                      {row.batch_expiry ? <p className="text-slate-500 text-xs">{row.batch_expiry}</p> : (!row.batch_number && <span className="text-slate-600">—</span>)}
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs font-mono whitespace-nowrap">{row.reference || '—'}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">{row.received_by || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Stock Card ── */}
      {loaded && tab === 'stock_card' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-white">{cardProductName} <span className="text-slate-500 font-mono text-xs ml-1">{cardProductSku}</span></p>
            <ExportBar
              onPDF={() => exportStockCardPDF(cardRows, cardProductName, cardProductSku, organisation)}
              onCSV={() => exportStockCardCSV(cardRows, cardProductSku)}
            />
          </div>
          <div className="card overflow-x-auto p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-700 text-xs text-slate-400 uppercase tracking-wider">
                  <th className="px-4 py-3 text-left whitespace-nowrap">Date</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Warehouse</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap text-emerald-400">IN</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap text-red-400">OUT</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap">Balance</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap">Unit Cost</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Invoice</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Batch</th>
                  <th className="px-4 py-3 text-left">Remark</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">By</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-700/50">
                {cardRows.length === 0 ? (
                  <tr><td colSpan={10} className="px-4 py-8 text-center text-slate-500">No stock movements found for this product in the selected period.</td></tr>
                ) : cardRows.map((row, i) => (
                  <tr key={i} className="hover:bg-surface-700/30 transition-colors">
                    <td className="px-4 py-3 text-slate-400 whitespace-nowrap text-xs">{row.date}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">{row.warehouse}</td>
                    <td className="px-4 py-3 text-right font-semibold text-emerald-400">
                      {row.in != null ? row.in : <span className="text-slate-700">—</span>}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold text-red-400">
                      {row.out != null ? row.out : <span className="text-slate-700">—</span>}
                    </td>
                    <td className="px-4 py-3 text-right font-bold text-white">{row.balance}</td>
                    <td className="px-4 py-3 text-right text-slate-400 text-xs whitespace-nowrap">{row.unit_cost || '—'}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs font-mono whitespace-nowrap">{row.invoice_no || '—'}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs">{row.batch_number || '—'}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs">{row.remark}</td>
                    <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">{row.created_by || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {cardRows.length > 0 && (
            <div className="card flex items-center justify-between py-3">
              <span className="text-sm text-slate-400">Closing Balance</span>
              <span className="text-lg font-bold text-white">{cardRows[cardRows.length - 1].balance}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
