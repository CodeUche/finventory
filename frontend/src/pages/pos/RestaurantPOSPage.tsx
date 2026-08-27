import { useEffect, useMemo, useState, useCallback } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { ClipboardList, Plus, Minus, Trash2, ClipboardCheck, GitBranch, CreditCard, X, Loader2, Search } from 'lucide-react'
import toast from 'react-hot-toast'
import { inventoryApi, posApi } from '@/services/api'
import { formatCurrency } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'

interface Product { id: string; name: string; sku: string; selling_price: string | number }
interface Table { id: string; name: string; status: string; section: string }
interface CartLine { product: Product; quantity: number; unit_price: number }
interface Tender { method: string; amount: string }

const ALL_ORDER_TYPES = [
  { key: 'dine_in', label: 'Dine In', restaurantOnly: true },
  { key: 'pickup', label: 'Pickup / Counter' },
  { key: 'delivery', label: 'Delivery' },
  { key: 'room_service', label: 'Room Service', restaurantOnly: true },
]
// settingsKey maps each on-the-wire tender method to Organisation.enabled_payment_types
// (Settings → Payments → Accepted Tender Types). 'card' and 'pos' both mean
// "card payment" here — kept as separate wire values since that's what's
// already stored on past orders, but they toggle together.
const TENDER_METHODS: { value: string; settingsKey: string }[] = [
  { value: 'cash', settingsKey: 'cash' },
  { value: 'card', settingsKey: 'card' },
  { value: 'pos', settingsKey: 'card' },
  { value: 'bank_transfer', settingsKey: 'bank_transfer' },
  { value: 'wallet', settingsKey: 'wallet' },
]

export default function RestaurantPOSPage() {
  const organisation = useAuthStore((s) => s.organisation)
  const isRestaurant = (organisation as { business_type?: string } | null)?.business_type === 'restaurant'
  const orderTypes = ALL_ORDER_TYPES.filter((t) => isRestaurant || !t.restaurantOnly)
  const enabledTenderMethods = TENDER_METHODS.filter((m) =>
    (organisation?.enabled_payment_types ?? TENDER_METHODS.map((x) => x.settingsKey)).includes(m.settingsKey))
  const [products, setProducts] = useState<Product[]>([])
  const [tables, setTables] = useState<Table[]>([])
  const [search, setSearch] = useState('')
  const [orderType, setOrderType] = useState(isRestaurant ? 'dine_in' : 'pickup')

  // If the org isn't a restaurant, don't leave a hospitality-only order type selected.
  useEffect(() => {
    if (!isRestaurant && (orderType === 'dine_in' || orderType === 'room_service')) setOrderType('pickup')
  }, [isRestaurant, orderType])
  const [tableId, setTableId] = useState('')
  const [roomNumber, setRoomNumber] = useState('')
  const [cart, setCart] = useState<CartLine[]>([])
  const [serviceCharge, setServiceCharge] = useState('0')
  const [tip, setTip] = useState('0')
  const [orderId, setOrderId] = useState<string | null>(null)
  const [orderNumber, setOrderNumber] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const [payOpen, setPayOpen] = useState(false)
  const [tenders, setTenders] = useState<Tender[]>([{ method: 'cash', amount: '' }])

  const load = useCallback(async () => {
    try {
      const [p, t] = await Promise.all([inventoryApi.products(), posApi.tables({ is_active: true })])
      setProducts(p.data.results ?? p.data)
      setTables((t.data.results ?? t.data).filter((x: Table) => x.status !== 'occupied' || x.id === tableId))
    } catch {
      toast.error('Failed to load POS data')
    }
  }, [tableId])
  useEffect(() => { load() }, [load])
  useDataRefresh(load)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return q ? products.filter((p) => p.name.toLowerCase().includes(q) || p.sku?.toLowerCase().includes(q)) : products
  }, [search, products])

  const subtotal = cart.reduce((s, l) => s + l.quantity * l.unit_price, 0)
  const total = subtotal + (parseFloat(serviceCharge) || 0) + (parseFloat(tip) || 0)

  const addToCart = (p: Product) => {
    setCart((c) => {
      const i = c.findIndex((l) => l.product.id === p.id)
      if (i >= 0) { const n = [...c]; n[i] = { ...n[i], quantity: n[i].quantity + 1 }; return n }
      return [...c, { product: p, quantity: 1, unit_price: Number(p.selling_price) }]
    })
  }
  const setQty = (id: string, delta: number) =>
    setCart((c) => c.map((l) => l.product.id === id ? { ...l, quantity: Math.max(1, l.quantity + delta) } : l))
  const removeLine = (id: string) => setCart((c) => c.filter((l) => l.product.id !== id))

  const buildItems = () => cart.map((l) => ({
    product_id: l.product.id, quantity: l.quantity, unit_price: String(l.unit_price),
  }))

  const placeOrder = async (): Promise<string | null> => {
    if (cart.length === 0) { toast.error('Add items to the order'); return null }
    if (orderType === 'dine_in' && !tableId) { toast.error('Select a table'); return null }
    if (orderId) return orderId
    setBusy(true)
    try {
      const { data } = await posApi.createOrder({
        order_type: orderType, table: tableId || null, room_number: roomNumber,
        items: buildItems(), service_charge: serviceCharge, tip_amount: tip,
      })
      setOrderId(data.id); setOrderNumber(data.order_number)
      toast.success(`Order ${data.order_number} placed`)
      return data.id
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Failed to place order')
      return null
    } finally {
      setBusy(false)
    }
  }

  const sendToKitchen = async () => {
    const id = await placeOrder()
    if (!id) return
    try {
      await posApi.generateKot(id, orderType === 'dine_in' ? (tables.find((t) => t.id === tableId)?.section || '') : '')
      toast.success('Sent to kitchen (KOT printed)')
    } catch { toast.error('Failed to send to kitchen') }
  }

  const doSplitBill = async () => {
    const id = await placeOrder()
    if (!id) return
    try {
      const { data } = await posApi.splitBill(id, { mode: 'equal', n: 2 })
      const parts = data.splits.map((s: { amount: number }) => formatCurrency(s.amount)).join('  +  ')
      toast(`Split equally: ${parts}`, { icon: '🧾', duration: 5000 })
    } catch { toast.error('Failed to split bill') }
  }

  const resetOrder = () => {
    setCart([]); setOrderId(null); setOrderNumber(''); setServiceCharge('0'); setTip('0')
    setTableId(''); setRoomNumber(''); setTenders([{ method: 'cash', amount: '' }]); load()
  }

  const openPay = async () => {
    const id = await placeOrder()
    if (!id) return
    setTenders([{ method: 'cash', amount: String(total) }])
    setPayOpen(true)
  }

  const tendered = tenders.reduce((s, t) => s + (parseFloat(t.amount) || 0), 0)

  const completePayment = async () => {
    if (!orderId) return
    if (tendered <= 0) { toast.error('Enter payment amount'); return }
    setBusy(true)
    try {
      const { data } = await posApi.finalizeOrder(orderId, tenders.filter((t) => parseFloat(t.amount) > 0))
      toast.success(`Paid · Invoice ${data.invoice_number}`)
      setPayOpen(false); resetOrder()
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Payment failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="p-4 h-[calc(100vh-3.5rem)] flex flex-col lg:flex-row gap-4">
      {/* Products */}
      <div className="flex-1 flex flex-col min-h-0">
        <div className="flex items-center gap-2 mb-3">
          <h1 className="text-lg font-bold text-white flex items-center gap-2"><ClipboardList size={18} /> {isRestaurant ? 'Restaurant POS' : 'POS Orders'}</h1>
          <div className="relative ml-auto w-64 max-w-full">
            <Search size={14} className="absolute left-3 top-2.5 text-slate-400" />
            <input className="input w-full pl-8" placeholder="Search menu…" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-2 overflow-y-auto pr-1">
          {filtered.map((p) => (
            <button key={p.id} onClick={() => addToCart(p)}
              className="rounded-xl border border-surface-700 bg-surface-800/40 hover:bg-surface-800 p-3 text-left">
              <div className="text-sm font-medium text-white line-clamp-2">{p.name}</div>
              <div className="text-xs text-brand-400 mt-1">{formatCurrency(Number(p.selling_price))}</div>
            </button>
          ))}
          {filtered.length === 0 && <div className="col-span-full text-center text-slate-500 text-sm py-10">No products</div>}
        </div>
      </div>

      {/* Order panel */}
      <div className="w-full lg:w-96 flex flex-col rounded-xl border border-surface-700 bg-surface-900 min-h-0">
        <div className="p-3 border-b border-surface-700 space-y-2">
          <div className="flex flex-wrap gap-1">
            {orderTypes.map((t) => (
              <button key={t.key} onClick={() => setOrderType(t.key)} disabled={!!orderId}
                className={`text-xs px-2 py-1 rounded border ${orderType === t.key ? 'bg-brand-600/20 border-brand-500/40 text-white' : 'border-surface-600 text-slate-400'}`}>
                {t.label}
              </button>
            ))}
          </div>
          {orderType === 'dine_in' && (
            <select className="input w-full text-sm" value={tableId} onChange={(e) => setTableId(e.target.value)} disabled={!!orderId}>
              <option value="">Select table…</option>
              {tables.map((t) => <option key={t.id} value={t.id}>{t.name}{t.section ? ` · ${t.section}` : ''}</option>)}
            </select>
          )}
          {orderType === 'room_service' && (
            <input className="input w-full text-sm" placeholder="Room number" value={roomNumber}
              onChange={(e) => setRoomNumber(e.target.value)} disabled={!!orderId} />
          )}
          {orderNumber && <div className="text-xs text-slate-400">Order <span className="font-mono text-slate-200">{orderNumber}</span></div>}
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2 min-h-0">
          {cart.length === 0 ? (
            <div className="text-center text-slate-500 text-sm py-10">Tap products to add</div>
          ) : cart.map((l) => (
            <div key={l.product.id} className="flex items-center gap-2 text-sm">
              <div className="flex-1 min-w-0">
                <div className="text-slate-200 truncate">{l.product.name}</div>
                <div className="text-xs text-slate-500">{formatCurrency(l.unit_price)} × {l.quantity} = {formatCurrency(l.unit_price * l.quantity)}</div>
              </div>
              <button onClick={() => setQty(l.product.id, -1)} className="p-1 text-slate-400 hover:text-white"><Minus size={14} /></button>
              <span className="w-6 text-center text-white">{l.quantity}</span>
              <button onClick={() => setQty(l.product.id, 1)} className="p-1 text-slate-400 hover:text-white"><Plus size={14} /></button>
              <button onClick={() => removeLine(l.product.id)} className="p-1 text-red-400"><Trash2 size={14} /></button>
            </div>
          ))}
        </div>

        <div className="p-3 border-t border-surface-700 space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs text-slate-400">Service charge
              <input className="input w-full text-sm mt-0.5" value={serviceCharge} onChange={(e) => setServiceCharge(e.target.value)} inputMode="decimal" />
            </label>
            <label className="text-xs text-slate-400">Tip
              <input className="input w-full text-sm mt-0.5" value={tip} onChange={(e) => setTip(e.target.value)} inputMode="decimal" />
            </label>
          </div>
          <div className="flex justify-between text-sm text-slate-300"><span>Subtotal</span><span>{formatCurrency(subtotal)}</span></div>
          <div className="flex justify-between text-base font-bold text-white"><span>Total</span><span>{formatCurrency(total)}</span></div>
          <div className={`grid ${isRestaurant ? 'grid-cols-3' : 'grid-cols-2'} gap-2`}>
            {isRestaurant && (
              <button onClick={sendToKitchen} disabled={busy} className="btn-secondary text-xs flex items-center justify-center gap-1"><ClipboardCheck size={14} /> KOT</button>
            )}
            <button onClick={doSplitBill} disabled={busy} className="btn-secondary text-xs flex items-center justify-center gap-1"><GitBranch size={14} /> Split</button>
            <button onClick={openPay} disabled={busy} className="btn-primary text-xs flex items-center justify-center gap-1">
              {busy ? <Loader2 size={14} className="animate-spin" /> : <><CreditCard size={14} /> Pay</>}
            </button>
          </div>
          {orderId && <button onClick={resetOrder} className="w-full text-xs text-slate-500 hover:text-slate-300">New order</button>}
        </div>
      </div>

      {/* Payment modal */}
      {payOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setPayOpen(false)}>
          <div className="w-full max-w-md bg-surface-900 border border-surface-700 rounded-xl p-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-bold text-white">Payment · {formatCurrency(total)}</h2>
              <button onClick={() => setPayOpen(false)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <div className="space-y-2">
              {tenders.map((t, i) => (
                <div key={i} className="flex gap-2">
                  <select className="input w-32 text-sm" value={t.method}
                    onChange={(e) => setTenders((ts) => ts.map((x, j) => j === i ? { ...x, method: e.target.value } : x))}>
                    {enabledTenderMethods.map((m) => <option key={m.value} value={m.value}>{m.value.replace('_', ' ')}</option>)}
                  </select>
                  <input className="input flex-1 text-sm" placeholder="Amount" value={t.amount} inputMode="decimal"
                    onChange={(e) => setTenders((ts) => ts.map((x, j) => j === i ? { ...x, amount: e.target.value } : x))} />
                  {tenders.length > 1 && (
                    <button onClick={() => setTenders((ts) => ts.filter((_, j) => j !== i))} className="text-red-400 px-1"><X size={15} /></button>
                  )}
                </div>
              ))}
              <button onClick={() => setTenders((ts) => [...ts, { method: 'cash', amount: '' }])}
                className="text-xs text-brand-400 hover:underline">+ Add tender (split payment)</button>
              <div className="flex justify-between text-sm text-slate-300 pt-2 border-t border-surface-700">
                <span>Tendered</span><span className={tendered >= total ? 'text-green-400' : 'text-amber-400'}>{formatCurrency(tendered)}</span>
              </div>
              <button onClick={completePayment} disabled={busy} className="btn-primary w-full mt-1">
                {busy ? <Loader2 size={15} className="animate-spin mx-auto" /> : 'Complete Payment'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
