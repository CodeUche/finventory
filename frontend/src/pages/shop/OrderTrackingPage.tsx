/**
 * Public order tracking — /s/<slug>/order/<reference>.
 *
 * The reference is the only credential, so the page shows just enough for the
 * customer to know where their order stands and nothing that would matter if
 * the link were forwarded.
 */

import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Check, Clock, Loader2, Package, X } from 'lucide-react'
import { shopApi, type ShopInfo, type ShopOrder } from '@/services/shopApi'

const STEPS = [
  { key: 'placed', label: 'Placed', hint: 'The seller has your order' },
  { key: 'confirmed', label: 'Confirmed', hint: 'Being prepared' },
  { key: 'ready', label: 'Ready', hint: 'Ready for you' },
  { key: 'completed', label: 'Completed', hint: 'All done' },
] as const

const money = (currency: string, value: number | string) => {
  const symbol = currency === 'NGN' ? '₦' : ''
  return `${symbol}${Number(value || 0).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`
}

export default function OrderTrackingPage() {
  const { slug = '', reference = '' } = useParams()
  const [order, setOrder] = useState<ShopOrder | null>(null)
  const [shop, setShop] = useState<ShopInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [missing, setMissing] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = () => Promise.all([shopApi.info(slug), shopApi.order(slug, reference)])
      .then(([info, res]) => {
        if (cancelled) return
        setShop(info.data)
        setOrder(res.data)
      })
      .catch(() => { if (!cancelled) setMissing(true) })
      .finally(() => { if (!cancelled) setLoading(false) })

    load()
    // A customer leaves this open while they wait, so refresh quietly.
    const timer = window.setInterval(load, 20000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [slug, reference])

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-white">
        <Loader2 className="animate-spin text-slate-400" size={24} />
      </div>
    )
  }

  if (missing || !order || !shop) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-white p-6 text-center">
        <div>
          <Package size={32} className="mx-auto mb-3 text-slate-300" />
          <h1 className="text-lg font-semibold text-slate-800">We can&rsquo;t find that order</h1>
          <p className="mt-1 text-sm text-slate-500">Check the reference and try again.</p>
        </div>
      </div>
    )
  }

  const accent = shop.accent_colour || '#12694A'
  const cancelled = order.status === 'cancelled'
  const stepIndex = STEPS.findIndex((s) => s.key === order.status)

  return (
    <div className="min-h-screen bg-slate-50 p-4">
      <div className="mx-auto max-w-md space-y-4">
        <div className="rounded-2xl border border-slate-200 bg-white p-5">
          <p className="text-xs uppercase tracking-wider text-slate-500">{shop.name}</p>
          <p className="mt-1 font-mono text-2xl font-bold tracking-widest">{order.reference}</p>
          <p className="mt-1 text-sm text-slate-600">
            {order.fulfilment === 'delivery' ? 'For delivery'
              : order.fulfilment === 'table' ? 'Table service' : 'For pickup'}
          </p>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5">
          {cancelled ? (
            <div className="flex items-center gap-3 text-red-600">
              <X size={18} /><span className="font-semibold">This order was cancelled</span>
            </div>
          ) : STEPS.map((step, i) => {
            const done = i <= stepIndex
            return (
              <div key={step.key} className="flex items-start gap-3 py-2">
                <div
                  className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
                  style={done
                    ? { background: accent, color: '#fff' }
                    : { background: '#f1f5f9', color: '#94a3b8' }}
                >
                  {done ? <Check size={13} /> : <Clock size={13} />}
                </div>
                <div>
                  <p className={done ? 'text-sm font-semibold' : 'text-sm text-slate-400'}>
                    {step.label}
                  </p>
                  <p className="text-xs text-slate-500">{step.hint}</p>
                </div>
              </div>
            )
          })}
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5">
          {order.items.map((item) => (
            <div key={item.product_name} className="flex justify-between py-1 text-sm">
              <span className="text-slate-600">{item.product_name} × {Number(item.quantity)}</span>
              <span className="font-mono">{money(shop.currency, item.line_total)}</span>
            </div>
          ))}
          <div className="mt-2 flex justify-between border-t border-slate-200 pt-2 font-semibold">
            <span>Total</span>
            <span className="font-mono">{money(shop.currency, order.total)}</span>
          </div>
        </div>

        {shop.whatsapp && (
          <a
            href={`https://wa.me/${shop.whatsapp.replace(/\D/g, '')}?text=${encodeURIComponent(`Hello, about order ${order.reference}`)}`}
            target="_blank" rel="noreferrer"
            className="block rounded-xl py-3 text-center text-sm font-semibold text-white"
            style={{ background: accent }}
          >
            Message {shop.name}
          </a>
        )}
      </div>
    </div>
  )
}
