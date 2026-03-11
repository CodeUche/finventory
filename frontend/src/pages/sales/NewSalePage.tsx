import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Minus, Plus, Search, ShoppingCart, Trash2, User, Warehouse, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { customerApi, inventoryApi, salesApi } from '@/services/api'
import { formatCurrency, formatAmountInput, stripCommas } from '@/lib/utils'
import { useNotifications } from '@/contexts/NotificationsContext'
import type { Customer, Product, Warehouse as WarehouseType } from '@/types'

interface CartItem {
  product: Product
  quantity: number
  unit_price: number
  discount_percent: number
}

const PAYMENT_METHODS = ['cash', 'pos', 'bank_transfer', 'credit']

export default function NewSalePage() {
  const navigate = useNavigate()
  const { refetch: refetchAlerts } = useNotifications()

  // ── Product search ─────────────────────────────────────────────────────────
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

  // ── Customer search ────────────────────────────────────────────────────────
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

  // ── Cart ───────────────────────────────────────────────────────────────────
  const [cart, setCart] = useState<CartItem[]>([])

  const addToCart = (product: Product) => {
    setCart((prev) => {
      const existing = prev.find((c) => c.product.id === product.id)
      if (existing) {
        return prev.map((c) =>
          c.product.id === product.id ? { ...c, quantity: c.quantity + 1 } : c,
        )
      }
      return [...prev, { product, quantity: 1, unit_price: parseFloat(product.selling_price), discount_percent: 0 }]
    })
    setProductQuery('')
    setShowProductDrop(false)
    searchRef.current?.focus()
  }

  const updateQty = (id: string, delta: number) => {
    setCart((prev) =>
      prev
        .map((c) => (c.product.id === id ? { ...c, quantity: Math.max(1, c.quantity + delta) } : c))
    )
  }

  const updatePrice = (id: string, price: string) => {
    setCart((prev) =>
      prev.map((c) => (c.product.id === id ? { ...c, unit_price: parseFloat(price) || 0 } : c)),
    )
  }

  const updateDiscount = (id: string, pct: string) => {
    const v = Math.min(100, Math.max(0, parseFloat(pct) || 0))
    setCart((prev) => prev.map((c) => (c.product.id === id ? { ...c, discount_percent: v } : c)))
  }

  const removeFromCart = (id: string) => setCart((prev) => prev.filter((c) => c.product.id !== id))

  // ── Totals ────────────────────────────────────────────────────────────────
  const subtotal = cart.reduce((sum, c) => sum + c.unit_price * c.quantity, 0)
  const discountTotal = cart.reduce(
    (sum, c) => sum + (c.unit_price * c.quantity * c.discount_percent) / 100,
    0,
  )
  const grandTotal = subtotal - discountTotal

  // ── Warehouses ────────────────────────────────────────────────────────────
  const [warehouses, setWarehouses] = useState<WarehouseType[]>([])
  const [selectedWarehouse, setSelectedWarehouse] = useState<string>('')

  useEffect(() => {
    inventoryApi.warehouses().then(({ data }) => {
      const list: WarehouseType[] = data.results ?? data
      setWarehouses(list)
      const def = list.find((w) => w.is_default) ?? list[0]
      if (def) setSelectedWarehouse(def.id)
    }).catch(() => {})
  }, [])

  // ── Payment ───────────────────────────────────────────────────────────────
  const [paymentMethod, setPaymentMethod] = useState('cash')
  const [amountPaid, setAmountPaid] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const tenderedNum = parseFloat(stripCommas(amountPaid)) || 0
  const changeGiven = tenderedNum > grandTotal ? tenderedNum - grandTotal : 0
  const balanceDue  = tenderedNum > 0 && tenderedNum < grandTotal ? grandTotal - tenderedNum : 0

  const buildPayload = (isProforma = false) => {
    const rawTendered = parseFloat(stripCommas(amountPaid)) || grandTotal
    const actualPaid = Math.min(rawTendered, grandTotal)
    const isCredit = paymentMethod === 'credit'
    return {
      customer_id: selectedCustomer?.id ?? null,
      warehouse_id: selectedWarehouse,
      payment_method: paymentMethod,
      amount_paid: isCredit || isProforma ? '0' : actualPaid.toFixed(2),
      amount_tendered: !isCredit && !isProforma && rawTendered > 0 ? rawTendered.toFixed(2) : null,
      notes,
      is_proforma: isProforma,
      items: cart.map((c) => ({
        product_id: c.product.id,
        quantity: c.quantity,
        unit_price: c.unit_price.toFixed(4),
        discount_percent: c.discount_percent.toFixed(2),
      })),
    }
  }

  const handleSubmit = async (isProforma = false) => {
    if (cart.length === 0) { toast.error('Add at least one product'); return }
    if (!selectedWarehouse) { toast.error('Select a warehouse first'); return }
    if (paymentMethod === 'credit' && !selectedCustomer && !isProforma) {
      toast.error('Select a customer for credit sales'); return
    }
    setSubmitting(true)
    try {
      await salesApi.create(buildPayload(isProforma))
      toast.success(isProforma ? 'Proforma invoice created!' : 'Sale recorded!')
      refetchAlerts()
      navigate('/sales')
    } catch (err: any) {
      const data = err?.response?.data
      let msg = 'Failed to record sale'
      if (typeof data?.error === 'string') {
        msg = data.error
      } else if (data?.error?.message) {
        msg = data.error.message
      } else if (data && typeof data === 'object') {
        const firstKey = Object.keys(data)[0]
        if (firstKey) {
          const val = (data as any)[firstKey]
          msg = Array.isArray(val) ? String(val[0]) : String(val)
        }
      } else if (!err?.response) {
        msg = 'Network error — check your connection'
      }
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
          <h1 className="text-2xl font-bold text-white">New Sale</h1>
          <p className="text-slate-400 text-sm">POS — add products and record payment</p>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-6">
        {/* ── Left: Product search + Cart ── */}
        <div className="space-y-4">
          {/* Product search */}
          <div className="card p-4">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
              Search Products
            </p>
            <div className="relative">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                ref={searchRef}
                className="input pl-9"
                placeholder="Product name or SKU…"
                value={productQuery}
                onChange={(e) => setProductQuery(e.target.value)}
                onFocus={() => products.length > 0 && setShowProductDrop(true)}
              />
              {showProductDrop && products.length > 0 && (
                <div className="absolute top-full mt-1 left-0 right-0 bg-surface-800 border border-surface-600 rounded-xl shadow-xl z-20 max-h-72 overflow-y-auto">
                  {products.map((p) => (
                    <button
                      key={p.id}
                      onMouseDown={() => addToCart(p)}
                      className="w-full flex items-center justify-between px-4 py-3 hover:bg-surface-700 transition-colors text-left"
                    >
                      <div>
                        <p className="text-sm font-medium text-white">{p.name}</p>
                        <p className="text-xs text-slate-400">{p.sku} · {p.unit_of_measure} · Stock: {p.total_stock}</p>
                      </div>
                      <span className="text-brand-400 font-semibold text-sm">{formatCurrency(p.selling_price)}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Cart items */}
          <div className="card p-0 overflow-hidden">
            <div className="px-5 py-4 border-b border-surface-700 flex items-center gap-2">
              <ShoppingCart size={16} className="text-brand-400" />
              <span className="font-semibold text-white">Cart</span>
              {cart.length > 0 && (
                <span className="ml-auto text-xs bg-brand-500/20 text-brand-400 px-2 py-0.5 rounded-full">
                  {cart.length} item{cart.length !== 1 ? 's' : ''}
                </span>
              )}
            </div>

            {cart.length === 0 ? (
              <div className="py-16 text-center">
                <ShoppingCart size={36} className="mx-auto mb-3 text-slate-700" />
                <p className="text-slate-500 text-sm">Your cart is empty</p>
                <p className="text-slate-600 text-xs mt-1">Search and add products above</p>
              </div>
            ) : (
              <div className="divide-y divide-surface-700">
                {cart.map((item) => (
                  <div key={item.product.id} className="px-5 py-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-white truncate">{item.product.name}</p>
                        <p className="text-xs text-slate-500">{item.product.sku}</p>
                      </div>
                      <button
                        onClick={() => removeFromCart(item.product.id)}
                        className="text-slate-600 hover:text-red-400 transition-colors flex-shrink-0"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>

                    <div className="mt-3 grid grid-cols-3 gap-3">
                      {/* Qty */}
                      <div>
                        <p className="text-xs text-slate-500 mb-1">Qty</p>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => updateQty(item.product.id, -1)}
                            className="w-7 h-7 rounded-lg bg-surface-700 hover:bg-surface-600 flex items-center justify-center transition-colors"
                          >
                            <Minus size={12} className="text-slate-300" />
                          </button>
                          <span className="w-8 text-center text-sm font-semibold text-white">
                            {item.quantity}
                          </span>
                          <button
                            onClick={() => updateQty(item.product.id, 1)}
                            className="w-7 h-7 rounded-lg bg-surface-700 hover:bg-surface-600 flex items-center justify-center transition-colors"
                          >
                            <Plus size={12} className="text-slate-300" />
                          </button>
                        </div>
                      </div>

                      {/* Unit price */}
                      <div>
                        <p className="text-xs text-slate-500 mb-1">Unit price</p>
                        <input
                          type="number"
                          className="input text-xs py-1.5 px-2"
                          value={item.unit_price}
                          onChange={(e) => updatePrice(item.product.id, e.target.value)}
                          min="0"
                          step="0.01"
                        />
                      </div>

                      {/* Discount % */}
                      <div>
                        <p className="text-xs text-slate-500 mb-1">Discount %</p>
                        <input
                          type="number"
                          className="input text-xs py-1.5 px-2"
                          value={item.discount_percent}
                          onChange={(e) => updateDiscount(item.product.id, e.target.value)}
                          min="0"
                          max="100"
                          step="0.5"
                        />
                      </div>
                    </div>

                    <div className="mt-2 flex justify-end">
                      <span className="text-sm font-semibold text-white">
                        {formatCurrency(
                          item.unit_price * item.quantity * (1 - item.discount_percent / 100),
                        )}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Right: Warehouse + Customer + Payment + Summary ── */}
        <div className="space-y-4">
          {/* Warehouse selector */}
          <div className="card p-4 space-y-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-2">
              <Warehouse size={14} />
              Warehouse
            </p>
            {warehouses.length === 0 ? (
              <p className="text-xs text-amber-400">
                No warehouses found.{' '}
                <a href="/inventory/warehouses" className="underline hover:text-amber-300">Add one first →</a>
              </p>
            ) : (
              <select
                className="input"
                value={selectedWarehouse}
                onChange={(e) => setSelectedWarehouse(e.target.value)}
              >
                <option value="">Select warehouse…</option>
                {warehouses.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}{w.is_default ? ' (default)' : ''}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Customer */}
          <div className="card p-4 space-y-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Customer (optional)
            </p>
            {selectedCustomer ? (
              <div className="flex items-center justify-between bg-surface-700 rounded-xl px-4 py-3">
                <div>
                  <p className="text-sm font-semibold text-white">{selectedCustomer.name}</p>
                  <p className="text-xs text-slate-400">{selectedCustomer.customer_type} · {selectedCustomer.phone}</p>
                  <p className="text-xs text-emerald-400 mt-0.5">
                    Credit: {formatCurrency(selectedCustomer.available_credit)}
                  </p>
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

          {/* Payment method */}
          <div className="card p-4 space-y-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Payment Method
            </p>
            <div className="grid grid-cols-2 gap-2">
              {PAYMENT_METHODS.map((m) => (
                <button
                  key={m}
                  onClick={() => setPaymentMethod(m)}
                  className={`py-2.5 rounded-xl text-sm font-medium capitalize transition-all border ${
                    paymentMethod === m
                      ? 'bg-brand-500/20 border-brand-500 text-brand-400'
                      : 'border-surface-600 text-slate-400 hover:border-surface-500'
                  }`}
                >
                  {m === 'pos' ? 'Card / POS' : m.replace('_', ' ')}
                </button>
              ))}
            </div>

            {paymentMethod !== 'credit' && (
              <div>
                <label className="text-xs text-slate-400 mb-1 block">Amount Tendered</label>
                <input
                  type="text"
                  inputMode="decimal"
                  className="input"
                  placeholder={formatCurrency(grandTotal)}
                  value={amountPaid}
                  onChange={(e) => setAmountPaid(formatAmountInput(e.target.value))}
                />
              </div>
            )}
          </div>

          {/* Order summary */}
          <div className="card p-4 space-y-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Order Summary
            </p>
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
              <div className="border-t border-surface-700 pt-2 flex justify-between text-white font-bold text-base">
                <span>Total</span>
                <span className="text-brand-400">{formatCurrency(grandTotal)}</span>
              </div>

              {/* Tendered / change / balance — only when a tendered amount is entered */}
              {paymentMethod !== 'credit' && tenderedNum > 0 && (
                <>
                  <div className="border-t border-surface-700/60 pt-2 flex justify-between text-sm text-slate-400">
                    <span>Tendered</span>
                    <span className="text-white">{formatCurrency(tenderedNum)}</span>
                  </div>
                  {changeGiven > 0 && (
                    <div className="flex justify-between text-sm font-semibold">
                      <span className="text-emerald-400">Change to Return</span>
                      <span className="text-emerald-400">{formatCurrency(changeGiven)}</span>
                    </div>
                  )}
                  {balanceDue > 0 && (
                    <div className="flex justify-between text-sm font-semibold">
                      <span className="text-red-400">Balance Still Owed</span>
                      <span className="text-red-400">{formatCurrency(balanceDue)}</span>
                    </div>
                  )}
                  {changeGiven === 0 && balanceDue === 0 && (
                    <div className="flex justify-between text-sm font-semibold">
                      <span className="text-emerald-400">Exact Amount</span>
                      <span className="text-emerald-400">✓ Paid in full</span>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          {/* Notes */}
          <div className="card p-4">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider block mb-2">
              Notes
            </label>
            <textarea
              className="input resize-none"
              rows={2}
              placeholder="Optional note…"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>

          {/* Submit */}
          <div className="space-y-2">
            <button
              onClick={() => handleSubmit(false)}
              disabled={submitting || cart.length === 0}
              className="btn-primary w-full py-3.5 text-base disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting ? 'Processing…' : `Confirm Sale · ${formatCurrency(grandTotal)}`}
            </button>
            <button
              onClick={() => handleSubmit(true)}
              disabled={submitting || cart.length === 0}
              className="w-full py-2.5 rounded-xl border border-slate-600 text-slate-300 hover:bg-surface-700 text-sm font-medium transition-colors disabled:opacity-50"
            >
              Save as Proforma Invoice
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
