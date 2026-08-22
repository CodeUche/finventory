/**
 * Public storefront — the merchant's shop page.
 *
 * Runs with no login and no Audity chrome: it carries the merchant's name and
 * colour, not ours. A customer browses, fills a basket, leaves a phone number
 * and gets a reference they can quote.
 *
 * Reached at /s/<slug>, or /s/<slug>/t/<table> when a guest scans the QR code
 * on their table.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  AlertTriangle, Check, Loader2, Minus, Plus, ShoppingBag, Store, X,
} from 'lucide-react'
import {
  shopApi, shopError, type ShopInfo, type ShopOrder, type ShopProduct,
} from '@/services/shopApi'

interface Line { product: ShopProduct; qty: number }

const money = (currency: string, value: number | string) => {
  const n = Number(value || 0)
  const symbol = currency === 'NGN' ? '₦' : ''
  return `${symbol}${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export default function StorefrontPage() {
  const { slug = '', table } = useParams()
  const [params] = useSearchParams()

  const [shop, setShop] = useState<ShopInfo | null>(null)
  const [products, setProducts] = useState<ShopProduct[]>([])
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [category, setCategory] = useState('All')

  const [lines, setLines] = useState<Line[]>([])
  const [showBasket, setShowBasket] = useState(false)
  const [placing, setPlacing] = useState(false)
  const [problem, setProblem] = useState('')
  const [placed, setPlaced] = useState<ShopOrder | null>(null)

  const [form, setForm] = useState({
    customer_name: '', customer_phone: '', customer_email: '',
    fulfilment: table ? 'table' : 'pickup', delivery_address: '', note: '',
  })

  useEffect(() => {
    let cancelled = false
    Promise.all([shopApi.info(slug), shopApi.products(slug)])
      .then(([info, cat]) => {
        if (cancelled) return
        setShop(info.data)
        setProducts(cat.data.results)
      })
      .catch(() => { if (!cancelled) setNotFound(true) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [slug])

  // The merchant's colour drives the page, not Audity's.
  const accent = shop?.accent_colour || '#12694A'

  const categories = useMemo(() => {
    const set = new Set(products.map((p) => p.category_name).filter(Boolean))
    return ['All', ...Array.from(set)]
  }, [products])

  const shown = category === 'All'
    ? products
    : products.filter((p) => p.category_name === category)

  const add = useCallback((product: ShopProduct) => {
    setLines((prev) => {
      const found = prev.find((l) => l.product.id === product.id)
      if (found) return prev.map((l) => l.product.id === product.id ? { ...l, qty: l.qty + 1 } : l)
      return [...prev, { product, qty: 1 }]
    })
  }, [])

  const setQty = (id: string, qty: number) =>
    setLines((prev) => prev.map((l) => l.product.id === id ? { ...l, qty } : l).filter((l) => l.qty > 0))

  const subtotal = lines.reduce((s, l) => s + Number(l.product.selling_price) * l.qty, 0)
  const count = lines.reduce((s, l) => s + l.qty, 0)
  const minimum = Number(shop?.minimum_order || 0)

  // Client-side estimate only — the server recomputes this from its own
  // catalogue and settings, same as every other price on this page.
  const fixedDeliveryCharge = Number(shop?.fixed_delivery_charge || 0)
  const freeDeliveryThreshold = shop?.free_delivery_threshold != null ? Number(shop.free_delivery_threshold) : null
  const deliveryFee = form.fulfilment === 'delivery' && fixedDeliveryCharge > 0
    && (freeDeliveryThreshold === null || subtotal < freeDeliveryThreshold)
    ? fixedDeliveryCharge : 0
  const total = subtotal + deliveryFee

  const placeOrder = async () => {
    setProblem('')
    if (!form.customer_name.trim()) { setProblem('Please tell us your name.'); return }
    if (!form.customer_phone.trim()) { setProblem('Please add a phone number so we can reach you.'); return }
    setPlacing(true)
    try {
      const { data } = await shopApi.placeOrder(slug, {
        ...form,
        table_code: table ?? params.get('table') ?? '',
        items: lines.map((l) => ({ product: l.product.id, quantity: String(l.qty) })),
      })
      setPlaced(data)
      setLines([])
    } catch (err) {
      setProblem(shopError(err, 'Could not place your order. Please try again.'))
    } finally { setPlacing(false) }
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-white">
        <Loader2 className="animate-spin text-slate-400" size={26} />
      </div>
    )
  }

  if (notFound || !shop) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-white p-6">
        <div className="text-center">
          <Store size={34} className="mx-auto mb-3 text-slate-300" />
          <h1 className="text-lg font-semibold text-slate-800">This shop isn&rsquo;t available</h1>
          <p className="mt-1 text-sm text-slate-500">
            Check the link, or ask the seller for their current one.
          </p>
        </div>
      </div>
    )
  }

  // ── Order placed ────────────────────────────────────────────────────────
  if (placed) {
    return (
      <div className="min-h-screen bg-slate-50 p-6">
        <div className="mx-auto max-w-md rounded-2xl border border-slate-200 bg-white p-6 text-center">
          <div
            className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full"
            style={{ background: `${accent}1a`, color: accent }}
          >
            <Check size={22} />
          </div>
          <h1 className="text-lg font-bold text-slate-900">Order placed</h1>
          <p className="mt-1 text-sm text-slate-600">
            {shop.name} has your order. Keep this reference:
          </p>
          <p className="my-4 font-mono text-3xl font-bold tracking-widest text-slate-900">
            {placed.reference}
          </p>
          <div className="rounded-xl bg-slate-50 p-4 text-left text-sm">
            {placed.items.map((i) => (
              <div key={i.product_name} className="flex justify-between py-0.5 text-slate-600">
                <span>{i.product_name} × {Number(i.quantity)}</span>
                <span className="font-mono">{money(shop.currency, i.line_total)}</span>
              </div>
            ))}
            {/* The only thing that can separate total from subtotal today is
                the delivery fee — computed server-side in place_order(). */}
            {Number(placed.total) > Number(placed.subtotal) && (
              <div className="flex justify-between py-0.5 text-slate-600">
                <span>Delivery</span>
                <span className="font-mono">
                  {money(shop.currency, Number(placed.total) - Number(placed.subtotal))}
                </span>
              </div>
            )}
            <div className="mt-2 flex justify-between border-t border-slate-200 pt-2 font-semibold text-slate-900">
              <span>Total</span>
              <span className="font-mono">{money(shop.currency, placed.total)}</span>
            </div>
          </div>

          {shop.payment.bank_transfer && shop.payment.bank_accounts[0] && (
            <div className="mt-4 rounded-xl border border-slate-200 p-4 text-left">
              <p className="text-xs uppercase tracking-wider text-slate-500">Pay by transfer</p>
              <p className="mt-1 font-mono text-lg text-slate-900">
                {shop.payment.bank_accounts[0].account_number}
              </p>
              <p className="text-sm text-slate-600">
                {shop.payment.bank_accounts[0].bank_name} · {shop.payment.bank_accounts[0].account_name}
              </p>
              <p className="mt-2 text-xs text-slate-500">
                Use <strong>{placed.reference}</strong> as the narration so they can find it.
              </p>
            </div>
          )}

          {shop.whatsapp && (
            <a
              href={`https://wa.me/${shop.whatsapp.replace(/\D/g, '')}?text=${encodeURIComponent(`Hello, my order reference is ${placed.reference}`)}`}
              target="_blank" rel="noreferrer"
              className="mt-4 block rounded-xl py-3 text-sm font-semibold text-white"
              style={{ background: accent }}
            >
              Message {shop.name}
            </a>
          )}
          <a href={`/s/${slug}/order/${placed.reference}`} className="mt-3 block text-sm text-slate-500 underline">
            Track this order
          </a>
        </div>
      </div>
    )
  }

  // ── Shop ────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-white text-slate-900">
      <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur">
        {shop.logo
          ? <img src={shop.logo} alt="" className="h-9 w-9 rounded-lg object-cover" />
          : (
            <div
              className="flex h-9 w-9 items-center justify-center rounded-lg font-bold text-white"
              style={{ background: accent }}
            >
              {shop.name.charAt(0)}
            </div>
          )}
        <div className="min-w-0">
          <p className="truncate font-bold leading-tight">{shop.name}</p>
          <p className="truncate text-xs text-slate-500">
            {table ? `Table ${table}` : shop.headline || shop.delivery_note}
          </p>
        </div>
        <button
          onClick={() => setShowBasket(true)}
          className="ml-auto flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold text-white"
          style={{ background: accent }}
        >
          <ShoppingBag size={15} /> {count > 0 ? count : 'Basket'}
        </button>
      </header>

      {!shop.accepts_orders && (
        <div className="flex items-start gap-2 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          <span>{shop.name} isn&rsquo;t taking orders at the moment.</span>
        </div>
      )}

      {categories.length > 1 && (
        <div className="flex gap-2 overflow-x-auto px-4 py-3">
          {categories.map((c) => (
            <button
              key={c} onClick={() => setCategory(c)}
              className="whitespace-nowrap rounded-full border px-3.5 py-1.5 text-sm"
              style={category === c
                ? { background: accent, borderColor: accent, color: '#fff' }
                : { borderColor: '#e2e8f0', color: '#475569' }}
            >
              {c}
            </button>
          ))}
        </div>
      )}

      <main className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 lg:grid-cols-4">
        {shown.map((p) => (
          <article key={p.id} className="overflow-hidden rounded-xl border border-slate-200">
            <div className="flex h-24 items-center justify-center bg-slate-100 text-xs uppercase tracking-widest text-slate-400">
              {p.image ? <img src={p.image} alt="" className="h-full w-full object-cover" /> : p.name.slice(0, 12)}
            </div>
            <div className="p-3">
              <p className="text-sm font-semibold leading-tight">{p.name}</p>
              <p className="mt-1 font-mono text-sm">{money(shop.currency, p.selling_price)}</p>
              <button
                onClick={() => add(p)}
                disabled={!p.in_stock || !shop.accepts_orders}
                className="mt-2 w-full rounded-lg border py-1.5 text-xs font-semibold disabled:opacity-40"
                style={{ borderColor: accent, color: accent }}
              >
                {p.in_stock ? 'Add to basket' : 'Sold out'}
              </button>
            </div>
          </article>
        ))}
        {shown.length === 0 && (
          <p className="col-span-full py-16 text-center text-sm text-slate-500">
            Nothing here yet — check back soon.
          </p>
        )}
      </main>

      {/* ── Basket & checkout ──────────────────────────────────────────── */}
      {showBasket && (
        <div className="fixed inset-0 z-20 flex justify-end">
          <div className="absolute inset-0 bg-black/40" onClick={() => setShowBasket(false)} />
          <aside className="relative flex h-full w-full max-w-sm flex-col bg-white">
            <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-3">
              <h2 className="font-bold">Your basket</h2>
              <button onClick={() => setShowBasket(false)} className="ml-auto text-slate-400" aria-label="Close">
                <X size={18} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-4">
              {lines.length === 0 ? (
                <p className="py-16 text-center text-sm text-slate-500">Your basket is empty</p>
              ) : lines.map((l) => (
                <div key={l.product.id} className="flex items-center gap-3 border-b border-slate-100 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{l.product.name}</p>
                    <p className="font-mono text-xs text-slate-500">
                      {money(shop.currency, l.product.selling_price)}
                    </p>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button onClick={() => setQty(l.product.id, l.qty - 1)} className="rounded border border-slate-200 p-1"><Minus size={12} /></button>
                    <span className="w-6 text-center text-sm">{l.qty}</span>
                    <button onClick={() => setQty(l.product.id, l.qty + 1)} className="rounded border border-slate-200 p-1"><Plus size={12} /></button>
                  </div>
                </div>
              ))}

              {lines.length > 0 && (
                <div className="space-y-2 py-4">
                  <input
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    placeholder="Your name" value={form.customer_name}
                    onChange={(e) => setForm({ ...form, customer_name: e.target.value })}
                  />
                  <input
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    placeholder="Phone number" inputMode="tel" value={form.customer_phone}
                    onChange={(e) => setForm({ ...form, customer_phone: e.target.value })}
                  />
                  {!table && (
                    <div className="flex gap-2">
                      {(['pickup', 'delivery'] as const).map((f) => (
                        <button
                          key={f} onClick={() => setForm({ ...form, fulfilment: f })}
                          className="flex-1 rounded-lg border py-2 text-sm capitalize"
                          style={form.fulfilment === f
                            ? { background: accent, borderColor: accent, color: '#fff' }
                            : { borderColor: '#e2e8f0', color: '#475569' }}
                        >
                          {f}
                        </button>
                      ))}
                    </div>
                  )}
                  {form.fulfilment === 'delivery' && (
                    <textarea
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                      rows={2} placeholder="Where should we deliver?"
                      value={form.delivery_address}
                      onChange={(e) => setForm({ ...form, delivery_address: e.target.value })}
                    />
                  )}
                  <input
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    placeholder="Anything we should know? (optional)" value={form.note}
                    onChange={(e) => setForm({ ...form, note: e.target.value })}
                  />
                </div>
              )}
            </div>

            <div className="border-t border-slate-200 p-4">
              {form.fulfilment === 'delivery' && fixedDeliveryCharge > 0 && (
                <div className="mb-1 flex items-baseline justify-between text-sm text-slate-500">
                  <span>Delivery</span>
                  <span className="font-mono">
                    {deliveryFee > 0 ? money(shop.currency, deliveryFee) : 'Free'}
                  </span>
                </div>
              )}
              <div className="mb-3 flex items-baseline justify-between">
                <span className="text-sm text-slate-500">Total</span>
                <span className="font-mono text-2xl font-bold">{money(shop.currency, total)}</span>
              </div>
              {form.fulfilment === 'delivery' && fixedDeliveryCharge > 0 && deliveryFee > 0 && freeDeliveryThreshold !== null && (
                <p className="mb-2 text-xs text-slate-500">
                  Free delivery on orders over {money(shop.currency, freeDeliveryThreshold)}.
                </p>
              )}
              {minimum > 0 && subtotal < minimum && (
                <p className="mb-2 text-xs text-amber-700">
                  Orders start at {money(shop.currency, minimum)}.
                </p>
              )}
              {problem && (
                <p className="mb-2 flex items-start gap-1.5 text-xs text-red-600">
                  <AlertTriangle size={13} className="mt-0.5 shrink-0" />{problem}
                </p>
              )}
              <button
                onClick={placeOrder}
                disabled={placing || lines.length === 0 || !shop.accepts_orders || (minimum > 0 && subtotal < minimum)}
                className="w-full rounded-xl py-3 font-semibold text-white disabled:opacity-40"
                style={{ background: accent }}
              >
                {placing ? <Loader2 size={16} className="mx-auto animate-spin" /> : 'Place order'}
              </button>
              <p className="mt-2 text-center text-[11px] text-slate-400">
                You&rsquo;ll get a reference to track it. Payment is arranged with the seller.
              </p>
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
