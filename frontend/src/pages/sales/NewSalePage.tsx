import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, Loader2, Minus, Plus, Search, ShoppingCart, Trash2, User, UserCheck, Warehouse, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { customerApi, inventoryApi, locationApi, salesApi, tillApi } from '@/services/api'
import { printReceipt } from '@/lib/receipt'
import { formatCurrency, formatDate, stripCommas } from '@/lib/utils'
import AmountInput from '@/components/AmountInput'
import EditableTotal from '@/components/EditableTotal'
import { useNotifications } from '@/contexts/NotificationsContext'
import { useAuthStore } from '@/store/authStore'
import { FieldTooltip } from '@/components/FieldTooltip'
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
  const { user, organisation } = useAuthStore()

  const currentUserName = user ? `${user.first_name} ${user.last_name}`.trim() || user.email : ''

  // ── Product search ─────────────────────────────────────────────────────────
  const [productQuery, setProductQuery] = useState('')
  const [products, setProducts] = useState<Product[]>([])
  const [showProductDrop, setShowProductDrop] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)
  const searchWrapRef = useRef<HTMLDivElement>(null)

  // Close dropdown when clicking outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (searchWrapRef.current && !searchWrapRef.current.contains(e.target as Node)) {
        setShowProductDrop(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    if (!productQuery.trim()) { setProducts([]); setShowProductDrop(false); return }
    let cancelled = false
    const t = setTimeout(async () => {
      try {
        const { data } = await inventoryApi.products({ search: productQuery, is_active: true })
        if (!cancelled) {
          setProducts(data.results ?? data)
          setShowProductDrop(true)
        }
      } catch (err: any) {
        if (!cancelled) {
          const msg = err?.response?.data?.error?.message ?? err?.response?.data?.error ?? null
          if (msg) toast.error(msg)
        }
      }
    }, 200)
    return () => { cancelled = true; clearTimeout(t) }
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
      prev.map((c) => (c.product.id === id ? { ...c, quantity: Math.max(1, c.quantity + delta) } : c))
    )
  }

  const updateQtyDirect = (id: string, raw: string) => {
    // Decimal, not integer: anything sold by weight (meat, rice from a sack,
    // fabric by the yard) is rung up as 1.42 kg, and rounding it to 1 or 2
    // over- or under-charges the customer on every single sale.
    const v = parseFloat(raw)
    if (!isNaN(v) && v > 0) {
      setCart((prev) => prev.map((c) => (c.product.id === id ? { ...c, quantity: v } : c)))
    }
  }

  // ── Barcode scanning ──────────────────────────────────────────────────────
  // A scanner is a keyboard that types fast and presses Enter. We look the code
  // up as an exact barcode/SKU first and drop it straight in the basket; only
  // if nothing matches exactly do we fall back to the search dropdown, so a
  // scan never makes the cashier pick from a list.
  const [scanning, setScanning] = useState(false)
  const [showHeld, setShowHeld] = useState(false)
  // Remembered per device — a counter till wants a receipt every time, a
  // back-office user raising an invoice almost never does.
  const [autoPrint, setAutoPrint] = useState<boolean>(() => {
    try { return localStorage.getItem('audity-pos-autoprint') !== '0' } catch { return true }
  })
  const toggleAutoPrint = () => setAutoPrint((v) => {
    const next = !v
    try { localStorage.setItem('audity-pos-autoprint', next ? '1' : '0') } catch { /* non-fatal */ }
    return next
  })

  // ── Till awareness ────────────────────────────────────────────────────────
  // Cash taken with no till open cannot be counted at end of shift, so say so
  // once rather than letting the shortfall surface at close.
  const [tillOpen, setTillOpen] = useState<boolean | null>(null)
  useEffect(() => {
    tillApi.current()
      .then(({ data }) => setTillOpen(!!data.open))
      .catch(() => setTillOpen(null))
  }, [])

  const handleScan = async (code: string) => {
    const query = code.trim()
    if (!query) return
    setScanning(true)
    try {
      const { data } = await inventoryApi.products({ search: query, is_active: true })
      const found: Product[] = data.results ?? data
      const exact = found.find(
        (p) => p.barcode?.toLowerCase() === query.toLowerCase()
            || p.sku?.toLowerCase() === query.toLowerCase(),
      )
      if (exact) {
        addToCart(exact)
        return
      }
      if (found.length === 1) { addToCart(found[0]); return }
      // Ambiguous — show the list rather than guess which item was scanned.
      setProducts(found)
      setShowProductDrop(found.length > 0)
      if (found.length === 0) toast.error(`Nothing found for "${query}"`)
    } catch {
      toast.error('Could not look that up')
    } finally { setScanning(false) }
  }

  // ── Held baskets ──────────────────────────────────────────────────────────
  // A customer forgets their wallet; the queue behind them shouldn't wait.
  // Kept on the device so a held basket survives a refresh and works offline.
  const HELD_KEY = `audity-held-baskets-${organisation?.id ?? 'none'}`
  interface HeldBasket { id: string; label: string; at: string; cart: CartItem[] }
  const [held, setHeld] = useState<HeldBasket[]>(() => {
    try { return JSON.parse(localStorage.getItem(HELD_KEY) || '[]') } catch { return [] }
  })

  const persistHeld = (next: HeldBasket[]) => {
    setHeld(next)
    try { localStorage.setItem(HELD_KEY, JSON.stringify(next)) } catch { /* quota — non-fatal */ }
  }

  // crypto.randomUUID needs a secure context and is missing from the older
  // Android WebViews on cheap POS terminals — which is exactly where this runs.
  const basketId = () => {
    try {
      if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
    } catch { /* fall through */ }
    return `held-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  }

  const holdBasket = () => {
    if (cart.length === 0) { toast.error('Nothing to hold'); return }
    const label = selectedCustomer?.name || `${cart.length} item${cart.length === 1 ? '' : 's'}`
    persistHeld([...held, { id: basketId(), label, at: new Date().toISOString(), cart }])
    setCart([])
    toast.success('Basket held')
    searchRef.current?.focus()
  }

  const resumeBasket = (id: string) => {
    const basket = held.find((b) => b.id === id)
    if (!basket) return
    if (cart.length > 0) { toast.error('Finish or hold the current basket first'); return }
    setCart(basket.cart)
    persistHeld(held.filter((b) => b.id !== id))
    toast.success('Basket resumed')
  }

  const discardBasket = (id: string) => persistHeld(held.filter((b) => b.id !== id))

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
  const [locations, setLocations] = useState<{ id: string; name: string }[]>([])
  const [selectedLocation, setSelectedLocation] = useState<string>('')

  useEffect(() => {
    inventoryApi.warehouses().then(({ data }) => {
      const list: WarehouseType[] = data.results ?? data
      setWarehouses(list)
      const def = list.find((w) => w.is_default) ?? list[0]
      if (def) setSelectedWarehouse(def.id)
    }).catch(() => {})
    // Load sales locations (optional)
    locationApi.list({ is_active: true }).then(({ data }) => {
      setLocations(data.results ?? data)
    }).catch(() => {})
  }, [])


  // ── Payment ───────────────────────────────────────────────────────────────
  const [paymentMethod, setPaymentMethod] = useState('cash')
  const [amountPaid, setAmountPaid] = useState('')
  const [applyCredit, setApplyCredit] = useState(false)
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const customerStoreCredit = parseFloat(selectedCustomer?.store_credit ?? '0')
  const creditApplied = applyCredit && customerStoreCredit > 0
    ? Math.min(customerStoreCredit, grandTotal)
    : 0
  const effectiveBalanceDue = grandTotal - creditApplied

  const tenderedNum = parseFloat(stripCommas(amountPaid)) || 0
  const changeGiven = tenderedNum > effectiveBalanceDue ? tenderedNum - effectiveBalanceDue : 0
  const balanceDue  = tenderedNum > 0 && tenderedNum < effectiveBalanceDue ? effectiveBalanceDue - tenderedNum : 0

  // Reset apply-credit if customer changes or no credit
  useEffect(() => {
    if (!selectedCustomer || customerStoreCredit <= 0) setApplyCredit(false)
  }, [selectedCustomer, customerStoreCredit])

  const buildPayload = (isProforma = false) => {
    const rawTendered = parseFloat(stripCommas(amountPaid)) || effectiveBalanceDue
    const actualPaid = Math.min(rawTendered, effectiveBalanceDue)
    const isCredit = paymentMethod === 'credit'
    return {
      customer_id: selectedCustomer?.id ?? null,
      warehouse_id: selectedWarehouse,
      location_id: selectedLocation || null,
      payment_method: paymentMethod,
      amount_paid: isCredit || isProforma ? '0' : actualPaid.toFixed(2),
      amount_tendered: !isCredit && !isProforma && rawTendered > 0 ? rawTendered.toFixed(2) : null,
      credit_applied: isProforma ? '0' : creditApplied.toFixed(2),
      notes,
      sold_by: currentUserName,
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
    if (!selectedWarehouse) { toast.error('Select a location first'); return }
    if (paymentMethod === 'credit' && !selectedCustomer && !isProforma) {
      toast.error('Select a customer for credit sales'); return
    }
    const zeroPriceItem = cart.find((c) => c.unit_price <= 0)
    if (zeroPriceItem) {
      toast.error(`"${zeroPriceItem.product.name}" has a zero or negative price — please correct it before saving`)
      return
    }
    setSubmitting(true)
    try {
      const { data: created } = await salesApi.create(buildPayload(isProforma))
      toast.success(isProforma ? 'Proforma invoice created!' : 'Sale recorded!')
      refetchAlerts()

      // Hand the customer their receipt before leaving the screen. Skipped for
      // a proforma, which is a quote and not proof of payment.
      if (!isProforma && created?.id && autoPrint) {
        printReceipt({
          merchant: organisation?.invoice_company_name || organisation?.name || 'Receipt',
          address: organisation?.address,
          phone: organisation?.phone,
          tin: organisation?.tax_id,
          invoiceNumber: created.invoice_number ?? '',
          date: formatDate(created.issue_date ?? new Date().toISOString()),
          cashier: currentUserName,
          customer: selectedCustomer?.name,
          lines: cart.map((c) => ({
            name: c.product.name,
            qty: c.quantity,
            unit_price: c.unit_price,
            line_total: c.unit_price * c.quantity * (1 - c.discount_percent / 100),
          })),
          subtotal, discount: discountTotal, total: grandTotal,
          payments: paymentMethod === 'credit' ? [] : [{ method: paymentMethod, amount: grandTotal }],
          amountTendered: tenderedNum || undefined,
          change: tenderedNum ? Math.max(0, tenderedNum - grandTotal) : undefined,
          firsIrn: created.firs_irn,
          qrCodeBase64: created.firs_qr_code,
        })
      }
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
          {tillOpen === false && (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200/90 flex gap-2.5 items-start">
              <AlertTriangle size={15} className="shrink-0 mt-0.5" />
              <span>
                No till is open, so cash taken now won't appear in an end-of-day count.{' '}
                <button onClick={() => navigate('/pos/till')} className="underline hover:text-white">
                  Open a till
                </button>.
              </span>
            </div>
          )}
          {/* Product search */}
          <div className="card p-4">
            <div className="flex items-center gap-2 mb-3">
              <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Scan or search
              </p>
              {scanning && <Loader2 size={12} className="animate-spin text-brand-400" />}
              <div className="ml-auto flex items-center gap-2">
                <button
                  type="button" onClick={toggleAutoPrint}
                  className={`btn-ghost px-2.5 py-1 text-[11px] ${autoPrint ? 'text-brand-400' : 'text-slate-500'}`}
                  title={autoPrint ? 'A receipt prints after each sale' : 'No receipt is printed'}
                >
                  Receipt {autoPrint ? 'on' : 'off'}
                </button>
                <button
                  type="button" onClick={holdBasket}
                  className="btn-ghost px-2.5 py-1 text-[11px]"
                  title="Park this basket and serve the next customer"
                >
                  Hold basket
                </button>
                {held.length > 0 && (
                  <button
                    type="button" onClick={() => setShowHeld((v) => !v)}
                    className="btn-ghost px-2.5 py-1 text-[11px] text-brand-400"
                  >
                    Resume ({held.length})
                  </button>
                )}
              </div>
            </div>

            {showHeld && held.length > 0 && (
              <div className="mb-3 rounded-xl border border-surface-600 divide-y divide-surface-700">
                {held.map((b) => (
                  <div key={b.id} className="flex items-center gap-2 px-3 py-2">
                    <span className="text-sm text-white flex-1 truncate">{b.label}</span>
                    <span className="text-[11px] text-slate-500">{formatDate(b.at)}</span>
                    <button
                      onClick={() => { resumeBasket(b.id); setShowHeld(false) }}
                      className="btn-ghost px-2 py-1 text-[11px] text-brand-400"
                    >
                      Resume
                    </button>
                    <button
                      onClick={() => discardBasket(b.id)}
                      className="btn-ghost p-1 text-slate-500 hover:text-red-400"
                      title="Discard"
                    >
                      <X size={13} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="relative" ref={searchWrapRef}>
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                ref={searchRef}
                className="input pl-9"
                placeholder="Scan barcode, or type a name / SKU…"
                value={productQuery}
                onChange={(e) => setProductQuery(e.target.value)}
                onFocus={() => products.length > 0 && setShowProductDrop(true)}
                onKeyDown={(e) => {
                  // A scanner ends its burst with Enter — treat that as a scan.
                  // Read the value off the element, NOT off React state: a
                  // hardware scanner types and sends Enter within a couple of
                  // milliseconds, faster than React flushes, so state can still
                  // hold the previous value and the scan would be dropped.
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    handleScan(e.currentTarget.value)
                  }
                }}
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
                        <p className="text-xs text-slate-400">
                          {p.sku} · {p.unit_of_measure} · Stock: {p.total_stock}
                          {(p as any).quantity_incoming > 0 && (
                            <span className="ml-1 text-blue-400"> · +{(p as any).quantity_incoming} incoming</span>
                          )}
                        </p>
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
                            className="w-7 h-7 rounded-lg bg-surface-700 hover:bg-surface-600 flex items-center justify-center transition-colors flex-shrink-0"
                          >
                            <Minus size={12} className="text-slate-300" />
                          </button>
                          <input
                            type="number"
                            className="input text-xs py-1 px-1 text-center w-14 font-semibold"
                            value={item.quantity}
                            onChange={(e) => updateQtyDirect(item.product.id, e.target.value)}
                            onFocus={(e) => e.target.select()}
                            min="1"
                            step="1"
                          />
                          <button
                            onClick={() => updateQty(item.product.id, 1)}
                            className="w-7 h-7 rounded-lg bg-surface-700 hover:bg-surface-600 flex items-center justify-center transition-colors flex-shrink-0"
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
                        <p className="text-xs text-slate-500 mb-1 flex items-center gap-1">Discount % <FieldTooltip text="Enter a percentage to reduce this item's price. E.g. 10 means the customer gets 10% off. Leave 0 for full price." /></p>
                        <input
                          type="number"
                          className="input text-xs py-1.5 px-2"
                          value={item.discount_percent}
                          onChange={(e) => updateDiscount(item.product.id, e.target.value)}
                          onFocus={(e) => e.target.select()}
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

        {/* ── Right: Location + Customer + Payment + Summary ── */}
        <div className="space-y-4">
          {/* Location selector */}
          <div className="card p-4 space-y-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-2">
              <Warehouse size={14} />
              Warehouse (Stock)
              <FieldTooltip text="The warehouse stock will be deducted from." />
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
            {/* Sales location (branch/store) — optional */}
            {locations.length > 0 && (
              <>
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-2 pt-1">
                  Sales Location (Branch)
                  <FieldTooltip text="The branch or store where this sale is happening. Optional." />
                </p>
                <select
                  className="input"
                  value={selectedLocation}
                  onChange={(e) => setSelectedLocation(e.target.value)}
                >
                  <option value="">— No specific location —</option>
                  {locations.map((l) => (
                    <option key={l.id} value={l.id}>{l.name}</option>
                  ))}
                </select>
              </>
            )}
          </div>

          {/* Customer */}
          <div className="card p-4 space-y-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1">
              Customer (optional)
              <FieldTooltip text="Attach a customer to track their purchase history, apply store credit, and generate a named invoice. Leave blank for walk-in cash sales." />
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
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1">
              Payment Method
              <FieldTooltip text="How the customer is paying. Choose 'Credit' if they are paying later — the invoice will stay open until settled. Cash/POS/Transfer marks it as paid immediately." />
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
                <label className="text-xs text-slate-400 mb-1 flex items-center gap-1">Amount Tendered <FieldTooltip text="The amount of cash the customer physically gives you. If more than the total, the change due will be shown automatically." /></label>
                <AmountInput
                  className="input"
                  placeholder={formatCurrency(effectiveBalanceDue)}
                  value={amountPaid}
                  onChange={(v) => setAmountPaid(v)}
                />
              </div>
            )}

            {/* Store credit checkbox — shown only when customer has credit */}
            {selectedCustomer && customerStoreCredit > 0 && !isNaN(customerStoreCredit) && (
              <label className="flex items-start gap-3 cursor-pointer select-none bg-emerald-500/5 border border-emerald-500/20 rounded-xl p-3 hover:bg-emerald-500/10 transition-colors">
                <input
                  type="checkbox"
                  checked={applyCredit}
                  onChange={(e) => setApplyCredit(e.target.checked)}
                  className="mt-0.5 accent-emerald-500"
                />
                <div>
                  <p className="text-sm font-medium text-emerald-300">Apply Store Credit</p>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {formatCurrency(customerStoreCredit)} available · deducts {formatCurrency(Math.min(customerStoreCredit, grandTotal))} from balance
                  </p>
                </div>
              </label>
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
              <div className="border-t border-surface-700 pt-2 text-base">
                <EditableTotal
                  total={grandTotal}
                  valueClass="text-white font-semibold"
                  lines={cart.map((c) => ({ quantity: c.quantity, unitPrice: c.unit_price, discountPercent: c.discount_percent }))}
                  onApply={(prices) => setCart((prev) => prev.map((c, i) => ({ ...c, unit_price: prices[i] })))}
                />
              </div>
              {creditApplied > 0 && (
                <>
                  <div className="flex justify-between text-emerald-400">
                    <span>Store Credit Applied</span>
                    <span>− {formatCurrency(creditApplied)}</span>
                  </div>
                  <div className="border-t border-surface-700 pt-2 flex justify-between text-white font-bold text-base">
                    <span>Balance Due</span>
                    <span className="text-brand-400">{formatCurrency(effectiveBalanceDue)}</span>
                  </div>
                </>
              )}
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

          {/* Sold By */}
          <div className="card p-4 space-y-2">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1">
              <UserCheck size={13} />
              Sold By
            </label>
            <div className="input bg-surface-800 text-slate-400 cursor-not-allowed select-none">
              {currentUserName}
            </div>
          </div>

          {/* Notes */}
          <div className="card p-4">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1 mb-2">
              Notes <FieldTooltip text="Add any message or instructions to print on the invoice — e.g. delivery address, payment terms, or a thank-you note. Visible to the customer." />
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
              {submitting ? 'Processing…' : `Confirm Sale · ${formatCurrency(effectiveBalanceDue)}`}
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
