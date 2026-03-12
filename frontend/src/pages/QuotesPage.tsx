import { useEffect, useState } from 'react'
import { Plus, X, ClipboardList, Loader2, FileText, ChevronDown, ChevronUp, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { quoteApi, customerApi, inventoryApi } from '@/services/api'
import { formatCurrency, formatDate, formatAmountInput, stripCommas } from '@/lib/utils'
import type { Quote, Customer, Warehouse, Product } from '@/types'
import DateInput from '@/components/DateInput'
import YearFilter, { yearToDateParams } from '@/components/YearFilter'

type StatusFilter = 'all' | 'draft' | 'sent' | 'accepted' | 'rejected' | 'expired' | 'converted'

const STATUS_BADGE: Record<string, string> = {
  draft: 'badge-slate',
  sent: 'badge-blue',
  accepted: 'badge-green',
  rejected: 'badge-red',
  expired: 'badge-slate',
  converted: 'badge-orange',
}

interface QuoteLineForm {
  product: string
  product_name: string
  quantity: string
  unit_price: string
  discount_percent: string
}

const BLANK_LINE: QuoteLineForm = { product: '', product_name: '', quantity: '1', unit_price: '', discount_percent: '0' }

interface QuoteForm {
  customer: string
  warehouse: string
  status: string
  issue_date: string
  valid_until: string
  notes: string
  terms: string
}

const today = new Date().toISOString().split('T')[0]
const inTwoWeeks = new Date(Date.now() + 14 * 86400000).toISOString().split('T')[0]

const BLANK_FORM: QuoteForm = {
  customer: '', warehouse: '', status: 'draft', issue_date: today, valid_until: inTwoWeeks, notes: '', terms: '',
}

export default function QuotesPage() {
  const [quotes, setQuotes] = useState<Quote[]>([])
  const [customers, setCustomers] = useState<Customer[]>([])
  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [archiveYear, setArchiveYear] = useState<number | null>(null)

  const [showModal, setShowModal] = useState(false)
  const [form, setForm] = useState<QuoteForm>(BLANK_FORM)
  const [lines, setLines] = useState<QuoteLineForm[]>([{ ...BLANK_LINE }])
  const [saving, setSaving] = useState(false)
  const [expandedRow, setExpandedRow] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, string> = { ...yearToDateParams(archiveYear) }
      if (statusFilter !== 'all') params.status = statusFilter
      const [qRes, cRes, wRes, pRes] = await Promise.all([
        quoteApi.list(params),
        customerApi.list(),
        inventoryApi.warehouses(),
        inventoryApi.products(),
      ])
      setQuotes(qRes.data.results ?? qRes.data)
      setCustomers(cRes.data.results ?? cRes.data)
      setWarehouses(wRes.data.results ?? wRes.data)
      setProducts(pRes.data.results ?? pRes.data)
    } catch { toast.error('Failed to load quotes') }
    finally { setLoading(false) }
  }

  useEffect(() => {
    load()
    const interval = setInterval(load, 5 * 60 * 1000) // poll every 5 minutes for auto-expiry
    return () => clearInterval(interval)
  }, [statusFilter, archiveYear])

  const handleCreate = async () => {
    if (!form.warehouse) { toast.error('Select a warehouse'); return }
    if (lines.some((l) => !l.product || !l.unit_price)) { toast.error('Fill in all line items'); return }
    setSaving(true)
    try {
      await quoteApi.create({
        ...form,
        customer: form.customer || null,
        items: lines.map((l) => ({
          product_id: l.product,
          quantity: parseFloat(l.quantity) || 1,
          unit_price: parseFloat(stripCommas(l.unit_price)) || 0,
          discount_percent: parseFloat(l.discount_percent) || 0,
        })),
      })
      toast.success('Quote created')
      setShowModal(false)
      setForm(BLANK_FORM)
      setLines([{ ...BLANK_LINE }])
      load()
    } catch { toast.error('Failed to create quote') }
    finally { setSaving(false) }
  }

  const handleConvert = async (q: Quote) => {
    if (q.status === 'rejected') { toast.error('This quote was rejected and cannot be converted'); return }
    if (q.status === 'expired') { toast.error('This quote has expired. Please create a new quote'); return }
    if (!confirm(`Convert quote ${q.quote_number} to invoice?`)) return
    try {
      await quoteApi.convert(q.id)
      toast.success('Converted to invoice')
      load()
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      const msg = typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to convert quote')
      toast.error(msg)
    }
  }

  const handleSend = async (q: Quote) => {
    try {
      await quoteApi.send(q.id)
      toast.success('Quote marked as sent')
      load()
    } catch { toast.error('Failed to update quote') }
  }

  const updateLine = (i: number, field: keyof QuoteLineForm, value: string) => {
    setLines(lines.map((l, idx) => {
      if (idx !== i) return l
      const updated = { ...l, [field]: value }
      if (field === 'product') {
        const p = products.find((pr) => pr.id === value)
        if (p) { updated.product_name = p.name; updated.unit_price = formatAmountInput(p.selling_price) }
      }
      if (field === 'unit_price') updated.unit_price = formatAmountInput(value)
      return updated
    }))
  }

  const total = quotes.filter((q) => statusFilter === 'all' ? true : q.status === statusFilter).length
  const accepted = quotes.filter((q) => q.status === 'accepted').length
  const expired = quotes.filter((q) => q.status === 'expired').length
  const converted = quotes.filter((q) => q.status === 'converted').length
  const convRate = total > 0 ? Math.round((converted / total) * 100) : 0

  const filtered = statusFilter === 'all' ? quotes : quotes.filter((q) => q.status === statusFilter)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Quotes / Estimates</h1>
          <p className="text-slate-400 text-sm">{quotes.length} total quotes</p>
        </div>
        <button className="btn-primary sm:ml-auto" onClick={() => setShowModal(true)}>
          <Plus size={16} /> New Quote
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Total Quotes', value: quotes.length, color: 'text-white', bg: 'bg-brand-500/15' },
          { label: 'Accepted', value: accepted, color: 'text-emerald-400', bg: 'bg-emerald-500/15' },
          { label: 'Expired', value: expired, color: 'text-red-400', bg: 'bg-red-500/15' },
          { label: 'Conversion Rate', value: `${convRate}%`, color: 'text-blue-400', bg: 'bg-blue-500/15' },
        ].map((c) => (
          <div key={c.label} className="card p-5 flex items-center gap-4">
            <div className={`w-10 h-10 rounded-xl ${c.bg} flex items-center justify-center`}>
              <ClipboardList size={18} className={c.color} />
            </div>
            <div>
              <p className="text-xs text-slate-400">{c.label}</p>
              <p className={`text-xl font-bold ${c.color}`}>{c.value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Status filter tabs */}
      <div className="flex gap-1 p-1 bg-surface-800 rounded-xl w-fit flex-wrap">
        {(['all', 'draft', 'sent', 'accepted', 'rejected', 'expired', 'converted'] as StatusFilter[]).map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={statusFilter === s
              ? 'px-3 py-1.5 rounded-lg text-sm font-semibold bg-brand-500 text-white'
              : 'px-3 py-1.5 rounded-lg text-sm text-slate-400 hover:text-white transition-colors capitalize'}
          >
            {s === 'all' ? 'All' : s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <YearFilter selectedYear={archiveYear} onChange={setArchiveYear} />
      </div>

      {/* Table */}
      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['', 'Quote #', 'Customer', 'Issue Date', 'Valid Until', 'Amount', 'Status', 'Actions'].map((h) => (
                  <th key={h} className="px-4 py-3.5 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="table-row">
                    {Array.from({ length: 8 }).map((_, j) => (
                      <td key={j} className="px-4 py-3.5">
                        <div className="h-4 bg-surface-700 rounded animate-pulse w-16" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center">
                    <ClipboardList size={32} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No quotes found</p>
                  </td>
                </tr>
              ) : filtered.map((q) => {
                const isExpiringSoon = (q.status === 'draft' || q.status === 'sent') && q.valid_until < today
                return (
                <>
                  <tr key={q.id} className={`table-row ${isExpiringSoon ? 'border-l-2 border-amber-500/60' : ''}`}>
                    <td className="px-4 py-3.5">
                      <button onClick={() => setExpandedRow(expandedRow === q.id ? null : q.id)} className="text-slate-400 hover:text-white">
                        {expandedRow === q.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>
                    </td>
                    <td className="px-4 py-3.5 font-mono text-brand-400">{q.quote_number}</td>
                    <td className="px-4 py-3.5 text-slate-300">{q.customer_name ?? <span className="text-slate-500 italic">Walk-in</span>}</td>
                    <td className="px-4 py-3.5 text-slate-400">{formatDate(q.issue_date)}</td>
                    <td className="px-4 py-3.5 text-slate-400">{formatDate(q.valid_until)}</td>
                    <td className="px-4 py-3.5 font-semibold text-white">{formatCurrency(q.total_amount)}</td>
                    <td className="px-4 py-3.5">
                      <span className={STATUS_BADGE[q.status] ?? 'badge-slate'}>{q.status}</span>
                    </td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-1.5">
                        {q.status === 'draft' && (
                          <button onClick={() => handleSend(q)} className="text-xs px-2.5 py-1 rounded-lg bg-blue-500/15 text-blue-400 hover:bg-blue-500/25 transition-colors">
                            Send
                          </button>
                        )}
                        {(q.status === 'accepted' || q.status === 'sent') && (
                          <button onClick={() => handleConvert(q)} className="text-xs px-2.5 py-1 rounded-lg bg-brand-500/15 text-brand-400 hover:bg-brand-500/25 transition-colors">
                            Convert
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                  {expandedRow === q.id && (
                    <tr key={`${q.id}-detail`} className="bg-surface-900/50">
                      <td colSpan={8} className="px-6 py-4">
                        <div className="space-y-2">
                          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Line Items</p>
                          {q.items.map((item, idx) => (
                            <div key={idx} className="flex items-center gap-4 text-sm">
                              <span className="text-slate-300 flex-1">{item.product_name}</span>
                              <span className="text-slate-400">Qty: {item.quantity}</span>
                              <span className="text-slate-400">@ {formatCurrency(item.unit_price)}</span>
                              {parseFloat(item.discount_percent) > 0 && (
                                <span className="badge-yellow">{item.discount_percent}% off</span>
                              )}
                              <span className="text-white font-semibold">{formatCurrency(item.line_total)}</span>
                            </div>
                          ))}
                          <div className="border-t border-surface-700 pt-2 flex justify-end gap-8 text-sm">
                            <span className="text-slate-400">Subtotal: <span className="text-white">{formatCurrency(q.subtotal)}</span></span>
                            <span className="text-slate-400">Tax: <span className="text-white">{formatCurrency(q.tax_amount)}</span></span>
                            <span className="text-slate-400">Total: <span className="text-brand-400 font-bold">{formatCurrency(q.total_amount)}</span></span>
                          </div>
                          {q.notes && <p className="text-xs text-slate-500">Notes: {q.notes}</p>}
                          {isExpiringSoon && (
                            <p className="text-xs text-amber-400 font-medium mt-1">⚠ Valid until date has passed — this quote may have auto-expired</p>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* New Quote Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setShowModal(false)} />
          <div className="relative card w-full max-w-2xl p-6 space-y-5 overflow-y-auto max-h-[90vh]">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">New Quote</h2>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white"><X size={20} /></button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Customer (optional)</label>
                <select className="input" value={form.customer} onChange={(e) => setForm({ ...form, customer: e.target.value })}>
                  <option value="">Walk-in / No customer</option>
                  {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Warehouse *</label>
                <select className="input" value={form.warehouse} onChange={(e) => setForm({ ...form, warehouse: e.target.value })}>
                  <option value="">— Select —</option>
                  {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Status</label>
                <select className="input" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  <option value="draft">Draft</option>
                  <option value="sent">Sent</option>
                  <option value="accepted">Accepted</option>
                  <option value="rejected">Rejected</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Issue Date</label>
                <DateInput value={form.issue_date} onChange={(v) => setForm({ ...form, issue_date: v })} />
              </div>
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Valid Until</label>
                <DateInput value={form.valid_until} onChange={(v) => setForm({ ...form, valid_until: v })} />
              </div>
            </div>

            {/* Line items */}
            <div>
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Line Items</p>
              <div className="space-y-2">
                {lines.map((line, i) => (
                  <div key={i} className="grid grid-cols-12 gap-2 items-center">
                    <div className="col-span-4">
                      <select className="input py-1.5 text-sm" value={line.product} onChange={(e) => updateLine(i, 'product', e.target.value)}>
                        <option value="">— Product —</option>
                        {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                    </div>
                    <div className="col-span-2">
                      <input type="number" min="1" className="input py-1.5 text-sm" placeholder="Qty" value={line.quantity} onChange={(e) => updateLine(i, 'quantity', e.target.value)} />
                    </div>
                    <div className="col-span-3">
                      <input type="text" inputMode="decimal" className="input py-1.5 text-sm" placeholder="Unit Price" value={line.unit_price} onChange={(e) => updateLine(i, 'unit_price', e.target.value)} />
                    </div>
                    <div className="col-span-2">
                      <input type="number" min="0" max="100" className="input py-1.5 text-sm" placeholder="Disc%" value={line.discount_percent} onChange={(e) => updateLine(i, 'discount_percent', e.target.value)} />
                    </div>
                    <div className="col-span-1 flex justify-center">
                      <button onClick={() => setLines(lines.filter((_, idx) => idx !== i))} className="p-1 text-slate-500 hover:text-red-400 transition-colors">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              <button onClick={() => setLines([...lines, { ...BLANK_LINE }])} className="btn-ghost text-sm mt-2 flex items-center gap-1">
                <Plus size={13} /> Add Line
              </button>
            </div>

            <div>
              <label className="text-xs text-slate-400 mb-1 block">Notes</label>
              <textarea className="input resize-none" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} placeholder="Any notes for the customer…" />
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Terms & Conditions</label>
              <textarea className="input resize-none" rows={2} value={form.terms} onChange={(e) => setForm({ ...form, terms: e.target.value })} placeholder="Payment terms, delivery conditions…" />
            </div>

            <div className="flex gap-3 pt-1">
              <button className="flex-1 py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white hover:border-surface-500 transition-colors text-sm" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn-primary flex-1 py-2.5 justify-center disabled:opacity-50" onClick={handleCreate} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : <><FileText size={15} /> Create Quote</>}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
