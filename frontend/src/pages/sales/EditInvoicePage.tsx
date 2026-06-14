import { useEffect, useRef, useState, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Minus, Plus, Search, Trash2, User, AlertTriangle, Loader2, Info } from 'lucide-react'
import toast from 'react-hot-toast'
import { customerApi, inventoryApi, salesApi } from '@/services/api'
import { formatCurrency, stripCommas } from '@/lib/utils'
import AmountInput from '@/components/AmountInput'
import DateInput from '@/components/DateInput'
import type { Customer, Invoice, Product, Warehouse as WarehouseType } from '@/types'

interface CartItem {
  product: Product
  quantity: number
  unit_price: number
  discount_percent: number
}

const PAYMENT_METHODS = ['cash', 'pos', 'bank_transfer', 'credit']

const STATUS_LABELS: Record<string, string> = {
  draft:           'Draft',
  proforma:        'Proforma',
  confirmed:       'Confirmed',
  credit:          'Credit',
  partially_paid:  'Partially Paid',
  overdue:         'Overdue',
  paid:            'Paid',
  voided:          'Voided',
}

const LOCKED_STATUSES = new Set(['paid', 'voided'])

function isoToDDMMYYYY(iso: string) {
  if (!iso) return ''
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y}`
}

function ddmmyyyyToISO(dd: string) {
  if (!dd) return ''
  const [d, m, y] = dd.split('/')
  if (!d || !m || !y) return dd
  return `${y}-${m}-${d}`
}

export default function EditInvoicePage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const [invoice, setInvoice] = useState<Invoice | null>(null)
  const [loadingInvoice, setLoadingInvoice] = useState(true)

  // Product search
  const [productQuery, setProductQuery] = useState('')
  const [products, setProducts] = useState<Product[]>([])
  const [showProductDrop, setShowProductDrop] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!productQuery.trim()) { setProducts([]); return }
    const t = setTimeout(async () => {
      try {
        const { data } = await inventoryApi.products({ search: productQuery, is_active: true })
        setProducts(data.results ?? data)
        setShowProductDrop(true)
      } catch { /* silent */ }
    }, 280)
    return () => clearTimeout(t)
  }, [productQuery])

  // Customer search
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

  // Cart
  const [cart, setCart] = useState<CartItem[]>([])

  const addToCart = (product: Product) => {
    setCart((prev) => {
      const existing = prev.find((c) => c.product.id === product.id)
      if (existing) return prev.map((c) => c.product.id === product.id ? { ...c, quantity: c.quantity + 1 } : c)
      return [...prev, { product, quantity: 1, unit_price: parseFloat(product.selling_price), discount_percent: 0 }]
    })
    setProductQuery('')
    setShowProductDrop(false)
    searchRef.current?.focus()
  }

  const updateQty = (id: string, delta: number) =>
    setCart((prev) => prev.map((c) => c.product.id === id ? { ...c, quantity: Math.max(1, c.quantity + delta) } : c))

  const updatePrice = (id: string, price: string) =>
    setCart((prev) => prev.map((c) => c.product.id === id ? { ...c, unit_price: parseFloat(stripCommas(price)) || 0 } : c))

  const updateDiscount = (id: string, pct: string) => {
    const v = Math.min(100, Math.max(0, parseFloat(pct) || 0))
    setCart((prev) => prev.map((c) => c.product.id === id ? { ...c, discount_percent: v } : c))
  }

  const removeFromCart = (id: string) => setCart((prev) => prev.filter((c) => c.product.id !== id))

  // Totals
  const subtotal     = cart.reduce((s, c) => s + c.unit_price * c.quantity, 0)
  const discountTotal = cart.reduce((s, c) => s + (c.unit_price * c.quantity * c.discount_percent) / 100, 0)
  const grandTotal   = subtotal - discountTotal

  // Warehouses
  const [warehouses, setWarehouses] = useState<WarehouseType[]>([])
  const [selectedWarehouse, setSelectedWarehouse] = useState('')

  // Form fields
  const [paymentMethod, setPaymentMethod] = useState('cash')
  const [notes, setNotes]                 = useState('')
  const [issueDate, setIssueDate]         = useState('')
  const [dueDate, setDueDate]             = useState('')
  const [submitting, setSubmitting]       = useState(false)

  // Load invoice + warehouses
  const load = useCallback(async () => {
    if (!id) return
    setLoadingInvoice(true)
    try {
      const [invResp, whResp] = await Promise.all([
        salesApi.invoice(id),
        inventoryApi.warehouses(),
      ])
      const inv: Invoice = invResp.data
      const whs: WarehouseType[] = whResp.data.results ?? whResp.data

      setInvoice(inv)
      setWarehouses(whs)
      setSelectedWarehouse((inv as any).warehouse ?? (whs.find((w) => w.is_default) ?? whs[0])?.id ?? '')
      setNotes(inv.notes ?? '')
      setPaymentMethod((inv as any).payment_method ?? 'cash')
      setIssueDate(isoToDDMMYYYY(inv.issue_date ?? ''))
      setDueDate(isoToDDMMYYYY((inv as any).due_date ?? ''))

      // Pre-populate customer display
      if ((inv as any).customer_name) {
        setCustomerQuery((inv as any).customer_name)
      }
      // Set customer ID for submission
      if ((inv as any).customer) {
        try {
          const custResp = await customerApi.get((inv as any).customer)
          setSelectedCustomer(custResp.data)
          setCustomerQuery(custResp.data.name)
        } catch { /* walk-in */ }
      }

      // Pre-populate cart from invoice items
      const lineItems: CartItem[] = []
      for (const item of ((inv as any).items ?? [])) {
        try {
          const prodResp = await inventoryApi.product(item.product)
          lineItems.push({
            product: prodResp.data,
            quantity: parseFloat(item.quantity),
            unit_price: parseFloat(item.unit_price),
            discount_percent: parseFloat(item.discount_percent ?? '0'),
          })
        } catch { /* skip items whose product was deleted */ }
      }
      setCart(lineItems)
    } catch {
      toast.error('Failed to load invoice')
    } finally {
      setLoadingInvoice(false)
    }
  }, [id])

  useEffect(() => { load() }, [load])

  const handleSubmit = async () => {
    if (!invoice || !id) return
    if (cart.length === 0) { toast.error('Add at least one item'); return }

    setSubmitting(true)
    try {
      const payload: Record<string, unknown> = {
        items: cart.map((c) => ({
          product_id: c.product.id,
          quantity: c.quantity,
          unit_price: c.unit_price,
          discount_percent: c.discount_percent,
        })),
        notes,
        payment_method: paymentMethod,
        issue_date: ddmmyyyyToISO(issueDate) || undefined,
        due_date: ddmmyyyyToISO(dueDate) || undefined,
        warehouse_id: selectedWarehouse || undefined,
        customer_id: selectedCustomer?.id ?? null,
      }

      await salesApi.editLines(id, payload)
      toast.success('Invoice updated')
      navigate(`/sales`)
    } catch (err: any) {
      const apiErr = err?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : (apiErr?.message ?? 'Failed to update invoice'))
    } finally {
      setSubmitting(false)
    }
  }

  if (loadingInvoice) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={28} className="animate-spin text-slate-500" />
      </div>
    )
  }

  if (!invoice) return null

  const isLocked = LOCKED_STATUSES.has((invoice as any).status ?? '')

  return (
    <div className="max-w-5xl mx-auto space-y-5 pb-12">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button onClick={() => navigate('/sales')} className="btn-ghost p-2 -ml-2 text-slate-400 hover:text-white">
          <ArrowLeft size={18} />
        </button>
        <div>
          <h1 className="text-xl font-bold text-white">Edit Invoice {invoice.invoice_number}</h1>
          <p className="text-sm text-slate-400 capitalize">
            Status: <span className="text-slate-200">{STATUS_LABELS[(invoice as any).status] ?? (invoice as any).status}</span>
          </p>
        </div>
      </div>

      {/* Locked warning */}
      {isLocked ? (
        <div className="card border-red-500/40 bg-red-500/10 flex items-start gap-3">
          <AlertTriangle size={18} className="text-red-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-red-300">This invoice cannot be edited</p>
            <p className="text-xs text-red-400/80 mt-0.5">
              {(invoice as any).status === 'paid'
                ? 'Paid invoices are locked. Void this invoice and create a new one to make corrections.'
                : 'Voided invoices cannot be edited.'}
            </p>
          </div>
        </div>
      ) : (invoice as any).status === 'confirmed' || (invoice as any).status === 'partially_paid' ? (
        <div className="card border-amber-500/40 bg-amber-500/8 flex items-start gap-3">
          <Info size={16} className="text-amber-400 mt-0.5 shrink-0" />
          <p className="text-xs text-amber-300">
            Editing a confirmed invoice will reverse the original stock movements and apply new ones.
            Existing payment records are preserved.
          </p>
        </div>
      ) : null}

      {isLocked ? null : (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            {/* Left: product search + cart */}
            <div className="lg:col-span-2 space-y-4">

              {/* Product search */}
              <div className="card space-y-3">
                <h2 className="text-sm font-semibold text-slate-300">Line Items</h2>
                <div className="relative">
                  <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                  <input
                    ref={searchRef}
                    value={productQuery}
                    onChange={(e) => setProductQuery(e.target.value)}
                    placeholder="Search products to add…"
                    className="input pl-9"
                  />
                  {showProductDrop && products.length > 0 && (
                    <>
                      <div className="fixed inset-0 z-40" onClick={() => setShowProductDrop(false)} />
                      <div className="absolute z-50 top-full mt-1 w-full bg-surface-800 border border-surface-600 rounded-xl shadow-xl max-h-56 overflow-y-auto">
                        {products.map((p) => (
                          <button
                            key={p.id}
                            onClick={() => addToCart(p)}
                            className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-surface-700 text-sm text-left"
                          >
                            <span className="text-slate-200">{p.name} <span className="text-slate-500 text-xs ml-1">{p.sku}</span></span>
                            <span className="text-brand-400">{formatCurrency(p.selling_price)}</span>
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                </div>

                {/* Cart table */}
                {cart.length === 0 ? (
                  <p className="text-slate-600 text-sm text-center py-4">No items yet — search above to add</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-surface-700 text-xs text-slate-500 uppercase">
                          <th className="pb-2 text-left">Product</th>
                          <th className="pb-2 text-center w-28">Qty</th>
                          <th className="pb-2 text-right w-32">Unit Price</th>
                          <th className="pb-2 text-right w-20">Disc %</th>
                          <th className="pb-2 text-right w-28">Line Total</th>
                          <th className="pb-2 w-8" />
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-surface-700/40">
                        {cart.map((c) => {
                          const lineSubtotal = c.unit_price * c.quantity
                          const lineDiscount = lineSubtotal * c.discount_percent / 100
                          const lineTotal    = lineSubtotal - lineDiscount
                          return (
                            <tr key={c.product.id}>
                              <td className="py-2.5 pr-3">
                                <p className="font-medium text-white">{c.product.name}</p>
                                <p className="text-xs text-slate-500">{c.product.sku}</p>
                              </td>
                              <td className="py-2.5 text-center">
                                <div className="flex items-center justify-center gap-1">
                                  <button onClick={() => updateQty(c.product.id, -1)} className="p-1 rounded hover:bg-surface-600 text-slate-400"><Minus size={12} /></button>
                                  <span className="text-white w-6 text-center">{c.quantity}</span>
                                  <button onClick={() => updateQty(c.product.id, 1)} className="p-1 rounded hover:bg-surface-600 text-slate-400"><Plus size={12} /></button>
                                </div>
                              </td>
                              <td className="py-2.5 text-right">
                                <AmountInput
                                  value={String(c.unit_price)}
                                  onChange={(v) => updatePrice(c.product.id, v)}
                                  className="input text-right w-28 text-sm py-1.5"
                                />
                              </td>
                              <td className="py-2.5 text-right">
                                <input
                                  type="number"
                                  min="0" max="100"
                                  value={c.discount_percent}
                                  onChange={(e) => updateDiscount(c.product.id, e.target.value)}
                                  className="input text-right w-16 text-sm py-1.5"
                                />
                              </td>
                              <td className="py-2.5 text-right font-medium text-white">
                                {formatCurrency(lineTotal)}
                              </td>
                              <td className="py-2.5 text-right">
                                <button onClick={() => removeFromCart(c.product.id)} className="p-1 rounded hover:bg-red-500/20 text-slate-600 hover:text-red-400"><Trash2 size={13} /></button>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Totals */}
              {cart.length > 0 && (
                <div className="card space-y-2">
                  <div className="flex justify-between text-sm"><span className="text-slate-400">Subtotal</span><span className="text-white">{formatCurrency(subtotal)}</span></div>
                  {discountTotal > 0 && (
                    <div className="flex justify-between text-sm"><span className="text-slate-400">Discounts</span><span className="text-red-400">− {formatCurrency(discountTotal)}</span></div>
                  )}
                  <div className="flex justify-between font-bold text-base border-t border-surface-700 pt-2">
                    <span className="text-slate-300">Total</span>
                    <span className="text-emerald-400">{formatCurrency(grandTotal)}</span>
                  </div>
                </div>
              )}
            </div>

            {/* Right: metadata */}
            <div className="space-y-4">
              {/* Customer */}
              <div className="card space-y-3">
                <h2 className="text-sm font-semibold text-slate-300 flex items-center gap-2"><User size={14} /> Customer</h2>
                <div className="relative">
                  <input
                    value={customerQuery}
                    onChange={(e) => { setCustomerQuery(e.target.value); if (!e.target.value) { setSelectedCustomer(null) } }}
                    placeholder="Search customer…"
                    className="input text-sm"
                  />
                  {showCustomerDrop && customers.length > 0 && (
                    <>
                      <div className="fixed inset-0 z-40" onClick={() => setShowCustomerDrop(false)} />
                      <div className="absolute z-50 top-full mt-1 w-full bg-surface-800 border border-surface-600 rounded-xl shadow-xl max-h-44 overflow-y-auto">
                        {customers.map((cu) => (
                          <button
                            key={cu.id}
                            onClick={() => { setSelectedCustomer(cu); setCustomerQuery(cu.name); setShowCustomerDrop(false) }}
                            className="w-full px-4 py-2.5 text-sm text-left hover:bg-surface-700 text-slate-200"
                          >
                            {cu.name}
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                </div>
                {selectedCustomer && (
                  <button onClick={() => { setSelectedCustomer(null); setCustomerQuery('') }} className="text-xs text-red-400 hover:underline">Remove customer (walk-in)</button>
                )}
              </div>

              {/* Details */}
              <div className="card space-y-3">
                <h2 className="text-sm font-semibold text-slate-300">Details</h2>

                <div>
                  <label className="label">Warehouse</label>
                  <select className="input" value={selectedWarehouse} onChange={(e) => setSelectedWarehouse(e.target.value)}>
                    {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                  </select>
                </div>

                <div>
                  <label className="label">Payment Method</label>
                  <select className="input" value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value)}>
                    {PAYMENT_METHODS.map((m) => <option key={m} value={m}>{m.replace('_', ' ')}</option>)}
                  </select>
                </div>

                <div>
                  <label className="label">Issue Date</label>
                  <DateInput value={issueDate} onChange={setIssueDate} placeholder="DD/MM/YYYY" />
                </div>

                <div>
                  <label className="label">Due Date</label>
                  <DateInput value={dueDate} onChange={setDueDate} placeholder="DD/MM/YYYY" />
                </div>

                <div>
                  <label className="label">Notes</label>
                  <textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    rows={3}
                    className="input resize-none"
                    placeholder="Internal notes…"
                  />
                </div>
              </div>

              {/* Save */}
              <button
                onClick={handleSubmit}
                disabled={submitting || cart.length === 0}
                className="btn-primary w-full py-3 justify-center gap-2 flex items-center disabled:opacity-50"
              >
                {submitting ? <Loader2 size={16} className="animate-spin" /> : null}
                Save Changes
              </button>

              <button
                onClick={() => navigate('/sales')}
                className="w-full py-2.5 rounded-xl border border-surface-600 text-slate-400 hover:text-white text-sm transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
