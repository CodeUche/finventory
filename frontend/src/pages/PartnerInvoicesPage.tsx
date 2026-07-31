import { useEffect, useState } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { confirmDialog } from '@/lib/dialog'
import {
  FileText, Plus, Send, CheckCircle, Trash2, Loader2,
  X, AlertCircle,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { partnerApi } from '@/services/api'
import type { PartnerClientLink } from '@/types'

// ── Types ────────────────────────────────────────────────────────────────────

interface InvoiceItem {
  id?: string
  description: string
  quantity: number
  unit_price: number
  total: number
  sort_order: number
}

interface PartnerInvoice {
  id: string
  invoice_number: string
  client_org: string
  client_org_name: string
  status: 'draft' | 'sent' | 'paid' | 'overdue' | 'void'
  issue_date: string
  due_date: string
  currency: string
  subtotal: number
  tax_rate: number
  tax_amount: number
  total: number
  paid_at: string | null
  payment_method: string
  notes: string
  items: InvoiceItem[]
  created_at: string
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  draft:   { label: 'Draft',   cls: 'bg-slate-500/15 text-slate-300' },
  sent:    { label: 'Sent',    cls: 'bg-blue-500/15 text-blue-300' },
  paid:    { label: 'Paid',    cls: 'bg-green-500/15 text-green-300' },
  overdue: { label: 'Overdue', cls: 'bg-red-500/15 text-red-300' },
  void:    { label: 'Void',    cls: 'bg-slate-500/10 text-slate-500' },
}

function fmtMoney(v: number, currency = 'NGN') {
  return `${currency === 'NGN' ? '₦' : currency}${Number(v).toLocaleString('en-NG', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

// ── New Invoice Modal ─────────────────────────────────────────────────────────

function NewInvoiceModal({
  clients,
  onClose,
  onCreated,
}: { clients: PartnerClientLink[]; onClose: () => void; onCreated: () => void }) {
  const [clientId, setClientId] = useState('')
  const [issueDate, setIssueDate] = useState(new Date().toISOString().slice(0, 10))
  const [dueDate, setDueDate] = useState('')
  const [taxRate, setTaxRate] = useState('0')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [items, setItems] = useState<{ description: string; quantity: string; unit_price: string }[]>([
    { description: '', quantity: '1', unit_price: '' },
  ])

  const subtotal = items.reduce((s, i) => s + (parseFloat(i.quantity) || 0) * (parseFloat(i.unit_price) || 0), 0)
  const taxAmount = subtotal * (parseFloat(taxRate) || 0) / 100
  const total = subtotal + taxAmount

  const addItem = () => setItems((p) => [...p, { description: '', quantity: '1', unit_price: '' }])
  const removeItem = (idx: number) => setItems((p) => p.filter((_, i) => i !== idx))
  const updateItem = (idx: number, field: string, val: string) =>
    setItems((p) => p.map((it, i) => (i === idx ? { ...it, [field]: val } : it)))

  const handleSave = async (status: 'draft' | 'sent') => {
    if (!clientId) { toast.error('Select a client'); return }
    if (!dueDate) { toast.error('Due date is required'); return }
    if (items.some((it) => !it.description || !it.unit_price)) {
      toast.error('All line items need a description and price'); return
    }
    setSaving(true)
    try {
      await partnerApi.createInvoice({
        client_org: clientId,
        issue_date: issueDate,
        due_date: dueDate,
        tax_rate: taxRate,
        notes,
        status,
        items: items.map((it, idx) => ({
          description: it.description,
          quantity: parseFloat(it.quantity) || 1,
          unit_price: parseFloat(it.unit_price) || 0,
          sort_order: idx,
        })),
      })
      toast.success(status === 'sent' ? 'Invoice created and sent!' : 'Draft saved')
      onCreated()
      onClose()
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Failed to create invoice'
      toast.error(typeof msg === 'string' ? msg : msg?.message ?? 'Failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
      <div className="bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-5 border-b border-surface-700">
          <h2 className="text-base font-semibold text-white flex items-center gap-2">
            <FileText size={16} className="text-brand-400" /> New Partner Invoice
          </h2>
          <button onClick={onClose} className="btn-ghost p-1"><X size={16} /></button>
        </div>

        <div className="p-5 space-y-4">
          {/* Client */}
          <div>
            <label className="text-xs text-slate-400 block mb-1">Client Organisation</label>
            <select className="input w-full" value={clientId} onChange={(e) => setClientId(e.target.value)}>
              <option value="">Select client…</option>
              {clients.map((c) => (
                <option key={c.id} value={c.organisation}>
                  {c.org_name}
                </option>
              ))}
            </select>
          </div>

          {/* Dates */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-slate-400 block mb-1">Issue Date</label>
              <input type="date" className="input w-full" value={issueDate} onChange={(e) => setIssueDate(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">Due Date</label>
              <input type="date" className="input w-full" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
            </div>
          </div>

          {/* Line items */}
          <div>
            <label className="text-xs text-slate-400 block mb-2">Line Items</label>
            <div className="space-y-2">
              {items.map((item, idx) => (
                <div key={idx} className="grid grid-cols-[1fr_80px_100px_28px] gap-2 items-center">
                  <input
                    className="input text-sm"
                    placeholder="Description"
                    value={item.description}
                    onChange={(e) => updateItem(idx, 'description', e.target.value)}
                  />
                  <input
                    className="input text-sm text-center"
                    placeholder="Qty"
                    value={item.quantity}
                    onChange={(e) => updateItem(idx, 'quantity', e.target.value)}
                  />
                  <input
                    className="input text-sm text-right"
                    placeholder="Unit price"
                    value={item.unit_price}
                    onChange={(e) => updateItem(idx, 'unit_price', e.target.value)}
                  />
                  <button onClick={() => removeItem(idx)} className="btn-ghost p-1 text-red-400" disabled={items.length === 1}>
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
            <button onClick={addItem} className="mt-2 text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1">
              <Plus size={12} /> Add line item
            </button>
          </div>

          {/* Tax + totals */}
          <div className="grid grid-cols-2 gap-3 items-end">
            <div>
              <label className="text-xs text-slate-400 block mb-1">Tax Rate (%)</label>
              <input type="text" className="input w-full" value={taxRate} onChange={(e) => setTaxRate(e.target.value)} placeholder="0" />
            </div>
            <div className="text-right space-y-1 text-sm">
              <div className="flex justify-between text-slate-400"><span>Subtotal</span><span>{fmtMoney(subtotal)}</span></div>
              {taxAmount > 0 && <div className="flex justify-between text-slate-400"><span>Tax ({taxRate}%)</span><span>{fmtMoney(taxAmount)}</span></div>}
              <div className="flex justify-between font-bold text-white"><span>Total</span><span>{fmtMoney(total)}</span></div>
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="text-xs text-slate-400 block mb-1">Notes (optional)</label>
            <textarea className="input w-full resize-none" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
        </div>

        <div className="flex gap-3 p-5 border-t border-surface-700">
          <button onClick={() => handleSave('draft')} disabled={saving} className="btn-ghost flex items-center gap-1.5 text-sm">
            {saving ? <Loader2 size={14} className="animate-spin" /> : null} Save Draft
          </button>
          <button onClick={() => handleSave('sent')} disabled={saving} className="btn-primary flex items-center gap-1.5 text-sm ml-auto">
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} Save & Send
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function PartnerInvoicesPage() {
  const [invoices, setInvoices] = useState<PartnerInvoice[]>([])
  const [clients, setClients] = useState<PartnerClientLink[]>([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [newOpen, setNewOpen] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [invRes, clientRes] = await Promise.allSettled([
        partnerApi.listInvoices(statusFilter ? { status: statusFilter } : undefined),
        partnerApi.clients(),
      ])
      if (invRes.status === 'fulfilled') setInvoices(invRes.value.data.results ?? invRes.value.data)
      if (clientRes.status === 'fulfilled') setClients(clientRes.value.data.results ?? clientRes.value.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [statusFilter]) // eslint-disable-line react-hooks/exhaustive-deps
  useDataRefresh(load)

  const handleMarkPaid = async (inv: PartnerInvoice) => {
    setActionLoading(inv.id)
    try {
      await partnerApi.markInvoicePaid(inv.id, { payment_method: 'bank_transfer' })
      toast.success(`Invoice ${inv.invoice_number} marked as paid`)
      load()
    } catch {
      toast.error('Failed to mark as paid')
    } finally {
      setActionLoading(null)
    }
  }

  const handleVoid = async (inv: PartnerInvoice) => {
    if (!(await confirmDialog(`Void invoice ${inv.invoice_number}?`))) return
    setActionLoading(inv.id)
    try {
      await partnerApi.voidInvoice(inv.id)
      toast.success('Invoice voided')
      load()
    } catch {
      toast.error('Failed to void invoice')
    } finally {
      setActionLoading(null)
    }
  }

  const FILTERS = ['', 'draft', 'sent', 'paid', 'overdue', 'void'] as const

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6 max-w-5xl mx-auto w-full">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <FileText size={20} className="text-brand-400" />
            Partner Invoices
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">Invoice your managed clients for professional services</p>
        </div>
        <button onClick={() => setNewOpen(true)} className="btn-primary flex items-center gap-1.5 text-sm">
          <Plus size={15} /> New Invoice
        </button>
      </div>

      {/* Status filter tabs */}
      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setStatusFilter(f)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              statusFilter === f
                ? 'bg-brand-500 text-white'
                : 'bg-surface-700/50 text-slate-400 hover:text-white'
            }`}
          >
            {f === '' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="card overflow-hidden p-0">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 size={24} className="animate-spin text-brand-400" />
          </div>
        ) : invoices.length === 0 ? (
          <div className="py-16 text-center">
            <AlertCircle size={32} className="mx-auto text-slate-600 mb-2" />
            <p className="text-sm text-slate-500">No invoices found.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-800/60">
                <tr>
                  <th className="px-4 py-2.5 text-xs font-semibold text-slate-400 uppercase tracking-wide text-left">Invoice #</th>
                  <th className="px-4 py-2.5 text-xs font-semibold text-slate-400 uppercase tracking-wide text-left">Client</th>
                  <th className="px-4 py-2.5 text-xs font-semibold text-slate-400 uppercase tracking-wide text-right">Amount</th>
                  <th className="px-4 py-2.5 text-xs font-semibold text-slate-400 uppercase tracking-wide text-center">Status</th>
                  <th className="px-4 py-2.5 text-xs font-semibold text-slate-400 uppercase tracking-wide text-right">Due</th>
                  <th className="px-4 py-2.5 text-xs font-semibold text-slate-400 uppercase tracking-wide text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-700/50">
                {invoices.map((inv) => {
                  const sm = STATUS_META[inv.status] ?? STATUS_META.draft
                  const busy = actionLoading === inv.id
                  return (
                    <tr key={inv.id} className="hover:bg-surface-700/30 transition-colors">
                      <td className="px-4 py-3 font-mono text-xs text-white">{inv.invoice_number}</td>
                      <td className="px-4 py-3 font-medium text-white">{inv.client_org_name}</td>
                      <td className="px-4 py-3 text-right font-mono text-xs text-white">{fmtMoney(inv.total, inv.currency)}</td>
                      <td className="px-4 py-3 text-center">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${sm.cls}`}>{sm.label}</span>
                      </td>
                      <td className="px-4 py-3 text-right text-xs text-slate-400">{inv.due_date}</td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          {inv.status !== 'paid' && inv.status !== 'void' && (
                            <button
                              onClick={() => handleMarkPaid(inv)}
                              disabled={busy}
                              className="btn-ghost p-1.5 text-green-400 hover:text-green-300"
                              title="Mark paid"
                            >
                              {busy ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle size={13} />}
                            </button>
                          )}
                          {inv.status !== 'paid' && inv.status !== 'void' && (
                            <button
                              onClick={() => handleVoid(inv)}
                              disabled={busy}
                              className="btn-ghost p-1.5 text-red-400 hover:text-red-300"
                              title="Void"
                            >
                              <Trash2 size={13} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {newOpen && (
        <NewInvoiceModal clients={clients} onClose={() => setNewOpen(false)} onCreated={load} />
      )}
    </div>
  )
}
