import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, FileText, Plus, Trash2, User, UserCheck, Warehouse, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { customerApi, inventoryApi, locationApi, salesApi, taxApi } from '@/services/api'
import { formatCurrency, normalizeAmountStr, stripCommas } from '@/lib/utils'
import AmountInput from '@/components/AmountInput'
import EditableTotal from '@/components/EditableTotal'
import DateInput from '@/components/DateInput'
import { useNotifications } from '@/contexts/NotificationsContext'
import { useAuthStore } from '@/store/authStore'
import { FieldTooltip } from '@/components/FieldTooltip'
import type { Customer, Product, TaxClass, Warehouse as WarehouseType } from '@/types'

interface InvoiceLine {
  product: string
  product_name: string
  quantity: string
  unit_price: string
  discount_percent: string
  is_taxable: boolean
  tax_class: string | null
  // The product's own defaults, kept aside so "Auto" can restore them after
  // a line has been overridden to a different class or a manual rate.
  product_is_taxable: boolean
  product_tax_class: string | null
  // Non-empty means the user typed a rate directly instead of picking a
  // TaxClass — takes priority over tax_class when computing/submitting.
  manual_tax_rate: string
}

const BLANK_LINE: InvoiceLine = {
  product: '', product_name: '', quantity: '1', unit_price: '', discount_percent: '0',
  is_taxable: false, tax_class: null,
  product_is_taxable: false, product_tax_class: null, manual_tax_rate: '',
}

const today = new Date().toISOString().split('T')[0]
const inThirtyDays = new Date(Date.now() + 30 * 86400000).toISOString().split('T')[0]

const PAYMENT_METHODS = ['cash', 'pos', 'bank_transfer']

export default function NewInvoicePage() {
  const navigate = useNavigate()
  const { refetch: refetchAlerts } = useNotifications()
  const { user } = useAuthStore()
  const currentUserName = user ? `${user.first_name} ${user.last_name}`.trim() || user.email : ''

  // ── Customer (required — an invoice always bills someone) ─────────────────
  const [customerQuery, setCustomerQuery] = useState('')
  const [customers, setCustomers] = useState<Customer[]>([])
  const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(null)
  const [showCustomerDrop, setShowCustomerDrop] = useState(false)

  useEffect(() => {
    if (!customerQuery.trim()) { setCustomers([]); return }
    const t = setTimeout(async () => {
      try {
        const { data } = await customerApi.list({ search: customerQuery })
        setCustomers(data.results ?? data)
        setShowCustomerDrop(true)
      } catch { /* silent */ }
    }, 280)
    return () => clearTimeout(t)
  }, [customerQuery])

  // ── Dates ───────────────────────────────────────────────────────────────
  const [issueDate, setIssueDate] = useState(today)
  const [dueDate, setDueDate] = useState(inThirtyDays)

  // ── Warehouse / location (stock the invoice will draw from once fulfilled) ─
  const [warehouses, setWarehouses] = useState<WarehouseType[]>([])
  const [selectedWarehouse, setSelectedWarehouse] = useState<string>('')
  const [locations, setLocations] = useState<{ id: string; name: string }[]>([])
  const [selectedLocation, setSelectedLocation] = useState<string>('')

  useEffect(() => {
    inventoryApi.warehouses().then(({ data }) => {
      const list: WarehouseType[] = data.results ?? data
      setWarehouses(list)
      const def = list.find((w) => w.is_default) ?? list[0]
      if (def) setSelectedWarehouse(def.id)
    }).catch(() => {})
    locationApi.list({ is_active: true }).then(({ data }) => {
      setLocations(data.results ?? data)
    }).catch(() => {})
  }, [])

  // ── Line items — searchable, same UX as Quotations ─────────────────────────
  const [lines, setLines] = useState<InvoiceLine[]>([{ ...BLANK_LINE }])
  const [productQueries, setProductQueries] = useState<string[]>([''])
  const [productResults, setProductResults] = useState<Product[][]>([[]])
  const [openProductDrop, setOpenProductDrop] = useState<number | null>(null)
  const lineSearchRefs = useRef<(HTMLDivElement | null)[]>([])

  const updateLine = (i: number, field: keyof InvoiceLine, value: string) => {
    setLines((prev) => prev.map((l, idx) => (idx === i ? { ...l, [field]: value } : l)))
  }

  const selectProduct = (i: number, p: Product) => {
    setLines((prev) => prev.map((l, idx) =>
      idx === i
        ? {
            ...l, product: p.id, product_name: p.name, unit_price: normalizeAmountStr(p.selling_price),
            is_taxable: p.is_taxable, tax_class: p.tax_class,
            product_is_taxable: p.is_taxable, product_tax_class: p.tax_class, manual_tax_rate: '',
          }
        : l
    ))
    setProductQueries((prev) => prev.map((q, idx) => (idx === i ? p.name : q)))
    setOpenProductDrop(null)
  }

  // ── VAT — mirrors the backend's SaleService._process_line_item calc exactly
  // (rate applied to the post-discount amount) so the preview never drifts
  // from what actually gets posted. Each line can also override the product's
  // default: pick a different configured TaxClass, or type a rate directly.
  const [taxClasses, setTaxClasses] = useState<TaxClass[]>([])
  const [taxRates, setTaxRates] = useState<Record<string, number>>({})
  useEffect(() => {
    taxApi.classes().then(({ data }) => {
      const list = data.results ?? data
      setTaxClasses(list)
      const map: Record<string, number> = {}
      for (const c of list) map[c.id] = parseFloat(c.rate)
      setTaxRates(map)
    }).catch(() => {})
  }, [])

  const setLineTaxMode = (i: number, mode: string) => {
    setLines((prev) => prev.map((l, idx) => {
      if (idx !== i) return l
      if (mode === '__auto__') return { ...l, tax_class: l.product_tax_class, manual_tax_rate: '' }
      if (mode === '__custom__') return { ...l, manual_tax_rate: l.manual_tax_rate || '0' }
      return { ...l, tax_class: mode, manual_tax_rate: '' }
    }))
  }
  const setLineManualRate = (i: number, value: string) => {
    setLines((prev) => prev.map((l, idx) => (idx === i ? { ...l, manual_tax_rate: value } : l)))
  }
  // The checkbox is the master on/off switch for VAT on a line — unticking it
  // always zeroes the line's tax regardless of what class/rate was chosen,
  // and re-ticking restores the product's own default rather than guessing
  // at whatever was last selected.
  const setLineVatEnabled = (i: number, enabled: boolean) => {
    setLines((prev) => prev.map((l, idx) => {
      if (idx !== i) return l
      if (!enabled) return { ...l, is_taxable: false }
      return { ...l, is_taxable: true, tax_class: l.tax_class ?? l.product_tax_class }
    }))
  }

  const addLine = () => {
    setLines((prev) => [...prev, { ...BLANK_LINE }])
    setProductQueries((prev) => [...prev, ''])
    setProductResults((prev) => [...prev, []])
  }

  const removeLine = (i: number) => {
    if (lines.length === 1) return
    setLines((prev) => prev.filter((_, idx) => idx !== i))
    setProductQueries((prev) => prev.filter((_, idx) => idx !== i))
    setProductResults((prev) => prev.filter((_, idx) => idx !== i))
  }

  useEffect(() => {
    const timers = productQueries.map((q, i) => {
      const trimmed = q.trim()
      if (!trimmed) {
        setProductResults((prev) => (prev[i]?.length ? prev.map((r, idx) => (idx === i ? [] : r)) : prev))
        return null
      }
      return setTimeout(async () => {
        try {
          const { data } = await inventoryApi.sellableProducts({ search: trimmed, is_active: true })
          setProductResults((prev) => prev.map((r, idx) => (idx === i ? (data.results ?? data) : r)))
        } catch { /* silent */ }
      }, 250)
    })
    return () => { timers.forEach((t) => { if (t) clearTimeout(t) }) }
  }, [productQueries])

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (openProductDrop === null) return
      const ref = lineSearchRefs.current[openProductDrop]
      if (ref && !ref.contains(e.target as Node)) setOpenProductDrop(null)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [openProductDrop])

  // ── Totals ──────────────────────────────────────────────────────────────
  const subtotal = lines.reduce((sum, l) => sum + (parseFloat(stripCommas(l.unit_price)) || 0) * (parseFloat(l.quantity) || 0), 0)
  const discountTotal = lines.reduce((sum, l) => {
    const lineTotal = (parseFloat(stripCommas(l.unit_price)) || 0) * (parseFloat(l.quantity) || 0)
    return sum + (lineTotal * (parseFloat(l.discount_percent) || 0)) / 100
  }, 0)
  // Line-items-only total (post-discount, pre-VAT) — this is what EditableTotal's
  // "edit total" back-solves unit prices against, since it has no notion of tax.
  const lineItemsTotal = subtotal - discountTotal
  const lineVat = (l: InvoiceLine) => {
    // The "Apply VAT" checkbox is the master switch — unticked always means
    // zero, regardless of what class/rate is still sitting in the fields.
    if (!l.is_taxable) return 0
    let rate = 0
    if (l.manual_tax_rate !== '') rate = parseFloat(l.manual_tax_rate) || 0
    else if (l.tax_class) rate = taxRates[l.tax_class] ?? 0
    else return 0
    const lineTotal = (parseFloat(stripCommas(l.unit_price)) || 0) * (parseFloat(l.quantity) || 0)
    const afterDiscount = lineTotal - (lineTotal * (parseFloat(l.discount_percent) || 0)) / 100
    return (afterDiscount * rate) / 100
  }
  const taxTotal = lines.reduce((sum, l) => sum + lineVat(l), 0)
  const [shippingAmount, setShippingAmount] = useState('')
  const shippingNum = parseFloat(stripCommas(shippingAmount)) || 0
  const grandTotal = lineItemsTotal + taxTotal + shippingNum

  // ── Fulfillment ─────────────────────────────────────────────────────────
  // Invoices bill the customer now; stock/GL posting is deferred until the
  // owner explicitly marks the order fulfilled — opt in here only if goods
  // are leaving the warehouse immediately (same moment as a POS sale).
  const [fulfillNow, setFulfillNow] = useState(false)

  // ── Payment ─────────────────────────────────────────────────────────────
  const [recordPaymentNow, setRecordPaymentNow] = useState(false)
  const [paymentMethod, setPaymentMethod] = useState('cash')
  const [amountPaid, setAmountPaid] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const tenderedNum = parseFloat(stripCommas(amountPaid)) || 0
  const actualPaid = recordPaymentNow ? Math.min(tenderedNum, grandTotal) : 0
  const balanceDue = grandTotal - actualPaid

  const buildPayload = () => ({
    customer_id: selectedCustomer?.id ?? null,
    warehouse_id: selectedWarehouse,
    location_id: selectedLocation || null,
    payment_method: recordPaymentNow ? paymentMethod : 'credit',
    amount_paid: recordPaymentNow ? actualPaid.toFixed(2) : '0',
    amount_tendered: recordPaymentNow && tenderedNum > 0 ? tenderedNum.toFixed(2) : null,
    credit_applied: '0',
    notes,
    sold_by: currentUserName,
    is_proforma: false,
    issue_date: issueDate,
    due_date: dueDate || null,
    defer_fulfillment: !fulfillNow,
    shipping_amount: shippingNum.toFixed(4),
    items: lines.map((l) => {
      // Only send a tax override when the line actually differs from the
      // product's own default — an untouched line stays on the exact same
      // path it always has (product.is_taxable/tax_class), so nothing about
      // existing invoices changes.
      const overridden = l.manual_tax_rate !== '' || l.tax_class !== l.product_tax_class || l.is_taxable !== l.product_is_taxable
      return {
        product_id: l.product,
        quantity: parseFloat(l.quantity) || 1,
        unit_price: (parseFloat(stripCommas(l.unit_price)) || 0).toFixed(4),
        discount_percent: (parseFloat(l.discount_percent) || 0).toFixed(2),
        ...(overridden ? {
          tax_class_id: !l.is_taxable || l.manual_tax_rate !== '' ? null : (l.tax_class || null),
          tax_rate: !l.is_taxable ? '0.00' : (l.manual_tax_rate !== '' ? (parseFloat(l.manual_tax_rate) || 0).toFixed(2) : null),
        } : {}),
      }
    }),
  })

  const handleSubmit = async () => {
    if (!selectedCustomer) { toast.error('Select a customer to bill'); return }
    if (!selectedWarehouse) { toast.error('Select a warehouse'); return }
    if (lines.some((l) => !l.product || !l.unit_price)) { toast.error('Fill in all line items'); return }
    const zeroPriceItem = lines.find((l) => (parseFloat(stripCommas(l.unit_price)) || 0) <= 0)
    if (zeroPriceItem) { toast.error('Every line item needs a price greater than zero'); return }
    setSubmitting(true)
    try {
      await salesApi.create(buildPayload())
      toast.success('Invoice created!')
      refetchAlerts()
      navigate('/sales')
    } catch (err: any) {
      const data = err?.response?.data
      let msg = 'Failed to create invoice'
      if (typeof data?.error === 'string') msg = data.error
      else if (data?.error?.message) msg = data.error.message
      else if (data && typeof data === 'object') {
        const firstKey = Object.keys(data)[0]
        if (firstKey) {
          const val = (data as any)[firstKey]
          msg = Array.isArray(val) ? String(val[0]) : String(val)
        }
      } else if (!err?.response) msg = 'Network error — check your connection'
      toast.error(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button onClick={() => navigate('/sales')} className="text-slate-400 hover:text-white transition-colors">
          <ArrowLeft size={20} />
        </button>
        <div>
          <h1 className="text-2xl font-bold text-white">New Invoice</h1>
          <p className="text-slate-400 text-sm">Bill a customer directly — no checkout required</p>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-6">
        {/* ── Left: Customer + Dates + Line items ── */}
        <div className="space-y-4">
          {/* Customer */}
          <div className="card p-4 space-y-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1">
              Customer *
              <FieldTooltip text="Who this invoice bills. Required — invoices always name a customer, unlike a walk-in POS sale." />
            </p>
            {selectedCustomer ? (
              <div className="flex items-center justify-between bg-surface-700 rounded-xl px-4 py-3">
                <div>
                  <p className="text-sm font-semibold text-white">{selectedCustomer.name}</p>
                  <p className="text-xs text-slate-400">{selectedCustomer.customer_type} · {selectedCustomer.phone}</p>
                </div>
                <button
                  onClick={() => { setSelectedCustomer(null); setCustomerQuery('') }}
                  className="text-slate-500 hover:text-red-400"
                >
                  <X size={16} />
                </button>
              </div>
            ) : (
              <div className="relative">
                <User size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  className="input pl-9"
                  placeholder="Search customer…"
                  value={customerQuery}
                  onChange={(e) => setCustomerQuery(e.target.value)}
                  onFocus={() => customers.length > 0 && setShowCustomerDrop(true)}
                />
                {showCustomerDrop && customers.length > 0 && (
                  <div className="absolute top-full mt-1 left-0 right-0 bg-surface-800 border border-surface-600 rounded-xl shadow-xl z-20 max-h-48 overflow-y-auto">
                    {customers.map((c) => (
                      <button
                        key={c.id}
                        onMouseDown={() => {
                          setSelectedCustomer(c)
                          setCustomerQuery('')
                          setShowCustomerDrop(false)
                        }}
                        className="w-full text-left px-4 py-3 hover:bg-surface-700 transition-colors"
                      >
                        <p className="text-sm font-medium text-white">{c.name}</p>
                        <p className="text-xs text-slate-400">{c.customer_type} · {c.phone}</p>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Dates */}
          <div className="card p-4 grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-slate-400 mb-1 block">Issue Date</label>
              <DateInput value={issueDate} onChange={setIssueDate} />
            </div>
            <div>
              <label className="text-xs text-slate-400 mb-1 block flex items-center gap-1">
                Due Date
                <FieldTooltip text="When payment is expected. The invoice shows as outstanding until paid or due-date extended." />
              </label>
              <DateInput value={dueDate} onChange={setDueDate} />
            </div>
          </div>

          {/* Line items */}
          <div className="card p-4">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Line Items</p>
            <div className="grid grid-cols-12 gap-2 mb-1">
              <span className="col-span-3 text-[11px] text-slate-400 uppercase">Product</span>
              <span className="col-span-2 text-[11px] text-slate-400 uppercase">Qty</span>
              <span className="col-span-2 text-[11px] text-slate-400 uppercase">Unit Price</span>
              <span className="col-span-2 text-[11px] text-slate-400 uppercase">Disc %</span>
              <span className="col-span-2 text-[11px] text-slate-400 uppercase">VAT</span>
            </div>
            <div className="space-y-2">
              {lines.map((line, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 items-start">
                  <div className="col-span-3 relative" ref={(el) => { lineSearchRefs.current[i] = el }}>
                    <input
                      className="input py-1.5 text-sm"
                      placeholder="Search product…"
                      value={productQueries[i] ?? ''}
                      onChange={(e) => {
                        const v = e.target.value
                        setProductQueries((prev) => prev.map((q, idx) => (idx === i ? v : q)))
                        if (!v.trim()) updateLine(i, 'product', '')
                      }}
                      onFocus={() => setOpenProductDrop(i)}
                    />
                    {openProductDrop === i && (productResults[i]?.length ?? 0) > 0 && (
                      <div className="absolute top-full mt-1 left-0 right-0 bg-surface-800 border border-surface-600 rounded-xl shadow-xl z-20 max-h-56 overflow-y-auto">
                        {productResults[i].map((p) => (
                          <button
                            key={p.id}
                            onMouseDown={() => selectProduct(i, p)}
                            className="w-full flex items-center justify-between px-3 py-2 hover:bg-surface-700 transition-colors text-left"
                          >
                            <span className="text-sm text-white truncate">{p.name}</span>
                            <span className="text-xs text-brand-400 font-semibold ml-2 shrink-0">{formatCurrency(p.selling_price)}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="col-span-2">
                    <input type="number" min="1" className="input py-1.5 text-sm" placeholder="Qty" value={line.quantity} onChange={(e) => updateLine(i, 'quantity', e.target.value)} />
                  </div>
                  <div className="col-span-2">
                    <AmountInput className="input py-1.5 text-sm" placeholder="Unit Price" value={line.unit_price} onChange={(v) => updateLine(i, 'unit_price', v)} />
                  </div>
                  <div className="col-span-2">
                    <input type="number" min="0" max="100" className="input py-1.5 text-sm" placeholder="Disc%" value={line.discount_percent} onChange={(e) => updateLine(i, 'discount_percent', e.target.value)} />
                  </div>
                  <div className="col-span-2 space-y-1">
                    <label className="flex items-center gap-1.5 text-xs text-slate-400 select-none">
                      <input
                        type="checkbox"
                        checked={line.is_taxable}
                        onChange={(e) => setLineVatEnabled(i, e.target.checked)}
                      />
                      Apply VAT
                    </label>
                    {line.is_taxable && (
                      <>
                        <select
                          className="input py-1.5 text-sm"
                          value={line.manual_tax_rate !== '' ? '__custom__' : (line.tax_class ?? '__auto__')}
                          onChange={(e) => setLineTaxMode(i, e.target.value)}
                        >
                          <option value="__auto__">Auto (product)</option>
                          {taxClasses.map((c) => (
                            <option key={c.id} value={c.id}>{c.name} ({c.rate}%)</option>
                          ))}
                          <option value="__custom__">Custom %…</option>
                        </select>
                        {line.manual_tax_rate !== '' && (
                          <input
                            type="number" min="0" max="100" step="0.01"
                            className="input py-1 text-xs"
                            placeholder="Rate %"
                            value={line.manual_tax_rate}
                            onChange={(e) => setLineManualRate(i, e.target.value)}
                          />
                        )}
                      </>
                    )}
                    <p className="text-[11px] text-slate-500 truncate">{formatCurrency(lineVat(line))}</p>
                  </div>
                  <div className="col-span-1 flex justify-center">
                    <button onClick={() => removeLine(i)} className="p-1 text-slate-500 hover:text-red-400 transition-colors" disabled={lines.length === 1}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <button onClick={addLine} className="btn-ghost text-sm mt-2 flex items-center gap-1">
              <Plus size={13} /> Add Line
            </button>
          </div>
        </div>

        {/* ── Right: Warehouse + Fulfillment + Payment + Summary ── */}
        <div className="space-y-4">
          {/* Warehouse */}
          <div className="card p-4 space-y-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-2">
              <Warehouse size={14} />
              Warehouse (Stock)
              <FieldTooltip text="The warehouse this order will be fulfilled from. Stock isn't deducted until you mark the invoice fulfilled, unless 'Fulfill now' is checked." />
            </p>
            {warehouses.length === 0 ? (
              <p className="text-xs text-amber-400">
                No warehouses found.{' '}
                <a href="/inventory/warehouses" className="underline hover:text-amber-300">Add one first →</a>
              </p>
            ) : (
              <select className="input" value={selectedWarehouse} onChange={(e) => setSelectedWarehouse(e.target.value)}>
                <option value="">Select warehouse…</option>
                {warehouses.map((w) => (
                  <option key={w.id} value={w.id}>{w.name}{w.is_default ? ' (default)' : ''}</option>
                ))}
              </select>
            )}
            {locations.length > 0 && (
              <>
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider pt-1">Sales Location (Branch)</p>
                <select className="input" value={selectedLocation} onChange={(e) => setSelectedLocation(e.target.value)}>
                  <option value="">— No specific location —</option>
                  {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                </select>
              </>
            )}
          </div>

          {/* Fulfillment */}
          <div className="card p-4">
            <label className="flex items-start gap-3 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={fulfillNow}
                onChange={(e) => setFulfillNow(e.target.checked)}
                className="mt-0.5 accent-brand-500"
              />
              <div>
                <p className="text-sm font-medium text-white">Fulfill now (deduct stock &amp; post to ledger immediately)</p>
                <p className="text-xs text-slate-400 mt-0.5">
                  Leave unchecked to bill the customer now and fulfill later — the invoice shows as "Pending Fulfillment" until you mark it shipped.
                </p>
                {!fulfillNow && (
                  <span className="inline-flex items-center gap-1 mt-2 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide bg-amber-500/20 text-amber-300">
                    Pending Fulfillment
                  </span>
                )}
              </div>
            </label>
          </div>

          {/* Payment */}
          <div className="card p-4 space-y-3">
            <label className="flex items-start gap-3 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={recordPaymentNow}
                onChange={(e) => setRecordPaymentNow(e.target.checked)}
                className="mt-0.5 accent-emerald-500"
              />
              <div>
                <p className="text-sm font-medium text-emerald-300">Customer is paying now</p>
                <p className="text-xs text-slate-400 mt-0.5">
                  Leave unchecked to bill on credit — the full amount stays outstanding until paid via Payment Information.
                </p>
              </div>
            </label>

            {recordPaymentNow && (
              <>
                <div className="grid grid-cols-3 gap-2">
                  {PAYMENT_METHODS.map((m) => (
                    <button
                      key={m}
                      onClick={() => setPaymentMethod(m)}
                      className={`py-2 rounded-xl text-sm font-medium capitalize transition-all border ${
                        paymentMethod === m
                          ? 'bg-brand-500/20 border-brand-500 text-brand-400'
                          : 'border-surface-600 text-slate-400 hover:border-surface-500'
                      }`}
                    >
                      {m === 'pos' ? 'Card / POS' : m.replace('_', ' ')}
                    </button>
                  ))}
                </div>
                <div>
                  <label className="text-xs text-slate-400 mb-1 block">Amount Received</label>
                  <AmountInput className="input" placeholder={formatCurrency(grandTotal)} value={amountPaid} onChange={setAmountPaid} />
                </div>
              </>
            )}
          </div>

          {/* Order summary */}
          <div className="card p-4 space-y-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Invoice Summary</p>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between text-slate-400">
                <span>Subtotal</span>
                <span>{formatCurrency(subtotal)}</span>
              </div>
              {discountTotal > 0 && (
                <div className="flex justify-between text-amber-400">
                  <span>Discount</span>
                  <span>− {formatCurrency(discountTotal)}</span>
                </div>
              )}
              <div className="text-base">
                <EditableTotal
                  total={lineItemsTotal}
                  valueClass="text-white font-semibold"
                  lines={lines.map((l) => ({
                    quantity: parseFloat(l.quantity) || 0,
                    unitPrice: parseFloat(stripCommas(l.unit_price)) || 0,
                    discountPercent: parseFloat(l.discount_percent) || 0,
                  }))}
                  onApply={(prices) => setLines((prev) => prev.map((l, i) => ({ ...l, unit_price: String(prices[i]) })))}
                />
              </div>
              {taxTotal > 0 && (
                <div className="flex justify-between text-blue-400">
                  <span>VAT</span>
                  <span>+ {formatCurrency(taxTotal)}</span>
                </div>
              )}
              <div className="flex justify-between items-center text-slate-400">
                <span>Delivery / Shipping <FieldTooltip text="Optional delivery or shipping charge, added on top of the line items and VAT." /></span>
                <AmountInput className="input py-1 text-sm text-right max-w-[140px]" placeholder="0.00" value={shippingAmount} onChange={setShippingAmount} />
              </div>
              <div className="border-t border-surface-700 pt-2 flex justify-between items-center font-bold text-base">
                <span className="text-white">Grand Total</span>
                <span className="text-brand-400">{formatCurrency(grandTotal)}</span>
              </div>
              {recordPaymentNow && tenderedNum > 0 && (
                <>
                  <div className="flex justify-between text-sm text-slate-400">
                    <span>Amount Paid</span>
                    <span className="text-white">{formatCurrency(actualPaid)}</span>
                  </div>
                  <div className="flex justify-between text-sm font-semibold">
                    <span className={balanceDue > 0 ? 'text-red-400' : 'text-emerald-400'}>Balance Due</span>
                    <span className={balanceDue > 0 ? 'text-red-400' : 'text-emerald-400'}>{formatCurrency(balanceDue)}</span>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Sold By */}
          <div className="card p-4 space-y-2">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1">
              <UserCheck size={13} /> Issued By
            </label>
            <div className="input bg-surface-800 text-slate-400 cursor-not-allowed select-none">{currentUserName}</div>
          </div>

          {/* Notes */}
          <div className="card p-4">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1 mb-2">
              Notes <FieldTooltip text="Payment terms, delivery instructions, or a message for the customer — printed on the invoice." />
            </label>
            <textarea className="input resize-none" rows={2} placeholder="Optional note…" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>

          {/* Submit */}
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="btn-primary w-full py-3.5 text-base disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            <FileText size={16} />
            {submitting ? 'Creating…' : `Create Invoice · ${formatCurrency(grandTotal)}`}
          </button>
        </div>
      </div>
    </div>
  )
}
