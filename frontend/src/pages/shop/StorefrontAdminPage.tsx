/**
 * Storefront (merchant side) — set up the public page and work the orders
 * that arrive from it.
 *
 * Accepting an order is what turns it into a real sale; until then it sits
 * here and never touches the ledger.
 */

import { useEffect, useState } from 'react'
import {
  AlertTriangle, Check, Copy, ExternalLink, Loader2, RefreshCw, Store, X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { storefrontApi, bypassNextGets } from '@/services/api'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { confirmDialog } from '@/lib/dialog'
import { formatCurrency, formatDate, formatAmountInput, stripCommas } from '@/lib/utils'

interface Shop {
  id: string
  slug: string
  is_published: boolean
  headline: string
  about: string
  whatsapp: string
  delivery_note: string
  accent_colour: string
  accepts_orders: boolean
  minimum_order: string
  /** Null means no free-delivery rule is configured. */
  free_delivery_threshold: string | null
  fixed_delivery_charge: string
  hide_out_of_stock: boolean
  public_url: string
}

interface Order {
  id: string
  reference: string
  status: 'placed' | 'confirmed' | 'ready' | 'completed' | 'cancelled'
  status_label: string
  fulfilment: string
  customer_name: string
  customer_phone: string
  delivery_address: string
  note: string
  table_name: string
  total: string
  invoice_number: string
  items: { product_name: string; quantity: string; line_total: string }[]
  created_at: string
}

const STATUS_BADGE: Record<Order['status'], string> = {
  placed: 'badge-yellow', confirmed: 'badge-blue', ready: 'badge-orange',
  completed: 'badge-green', cancelled: 'badge-red',
}

export default function StorefrontAdminPage() {
  const [shop, setShop] = useState<Shop | null>(null)
  const [orders, setOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  // Delivery pricing inputs — controlled (unlike the plain text fields above)
  // so amounts get live comma formatting per project convention.
  const [deliveryCharge, setDeliveryCharge] = useState('')
  const [deliveryThreshold, setDeliveryThreshold] = useState('')
  useEffect(() => {
    if (!shop) return
    setDeliveryCharge(formatAmountInput(shop.fixed_delivery_charge || '0'))
    setDeliveryThreshold(shop.free_delivery_threshold != null ? formatAmountInput(shop.free_delivery_threshold) : '')
  }, [shop?.id, shop?.fixed_delivery_charge, shop?.free_delivery_threshold])

  const load = async () => {
    setLoading(true)
    try {
      const [s, o] = await Promise.all([
        storefrontApi.mine(),
        storefrontApi.orders({ page_size: 200 }),
      ])
      setShop(s.data)
      setOrders(o.data.results ?? o.data)
    } catch { toast.error('Could not load your storefront') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])
  useDataRefresh(load)

  const save = async (patch: Partial<Shop>) => {
    if (!shop) return
    setSaving(true)
    try {
      const { data } = await storefrontApi.update(shop.id, patch)
      setShop(data)
      toast.success('Saved')
    } catch (err) {
      const apiErr = (err as { response?: { data?: Record<string, unknown> } })?.response?.data
      const slugErr = Array.isArray(apiErr?.slug) ? String(apiErr.slug[0]) : null
      toast.error(slugErr || 'Could not save')
    } finally { setSaving(false) }
  }

  const accept = async (order: Order) => {
    const ok = await confirmDialog(
      `Accept order ${order.reference}? This creates a real sale for ${formatCurrency(order.total)}.`,
    )
    if (!ok) return
    setBusyId(order.id)
    try {
      await storefrontApi.accept(order.id)
      toast.success('Order accepted')
      bypassNextGets(); load()
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Could not accept the order')
    } finally { setBusyId(null) }
  }

  const setStatus = async (order: Order, status: string) => {
    setBusyId(order.id)
    try {
      await storefrontApi.setStatus(order.id, status)
      bypassNextGets(); load()
    } catch { toast.error('Could not update the order') }
    finally { setBusyId(null) }
  }

  const publicUrl = shop ? `${window.location.origin}/s/${shop.slug}` : ''
  const copyLink = () => {
    navigator.clipboard?.writeText(publicUrl)
    setCopied(true); window.setTimeout(() => setCopied(false), 1800)
  }

  const waiting = orders.filter((o) => o.status === 'placed')

  if (loading && !shop) {
    return <div className="card flex justify-center p-12"><Loader2 size={20} className="animate-spin text-slate-500" /></div>
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-bold text-white">Storefront</h1>
          <p className="text-sm text-slate-400">
            {waiting.length === 0
              ? 'No orders waiting'
              : `${waiting.length} order${waiting.length === 1 ? '' : 's'} waiting to be accepted`}
          </p>
        </div>
        <button
          onClick={() => { bypassNextGets(); load() }}
          className="btn-ghost p-2 text-slate-400 hover:text-white sm:ml-auto" title="Refresh"
        >
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {shop && (
        <div className="card space-y-4 p-6">
          <div className="flex items-center gap-2 border-b border-surface-700 pb-3">
            <Store size={16} className="text-brand-400" />
            <h2 className="text-base font-semibold text-white">Your shop page</h2>
            <span className={shop.is_published ? 'badge-green ml-auto' : 'badge-slate ml-auto'}>
              {shop.is_published ? 'Live' : 'Not published'}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-surface-600 bg-surface-800 p-3">
            <span className="font-mono text-sm text-white">{publicUrl}</span>
            <button onClick={copyLink} className="btn-ghost ml-auto text-xs">
              {copied ? <Check size={12} /> : <Copy size={12} />} {copied ? 'Copied' : 'Copy'}
            </button>
            <a href={`/s/${shop.slug}`} target="_blank" rel="noreferrer" className="btn-ghost text-xs">
              <ExternalLink size={12} /> Open
            </a>
          </div>

          {!shop.is_published && (
            <div className="flex gap-2.5 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200/90">
              <AlertTriangle size={15} className="mt-0.5 shrink-0" />
              <span>
                Your page is hidden. Publish it when you&rsquo;re ready — and remember only
                products you&rsquo;ve marked <strong>published</strong> will show.
              </span>
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label">Shop address</label>
              <div className="flex items-center gap-1">
                <span className="text-sm text-slate-500">/s/</span>
                <input
                  className="input" defaultValue={shop.slug}
                  onBlur={(e) => e.target.value !== shop.slug && save({ slug: e.target.value.trim().toLowerCase() })}
                />
              </div>
            </div>
            <div>
              <label className="label">Headline</label>
              <input
                className="input" defaultValue={shop.headline} placeholder="e.g. Provisions in Ikeja"
                onBlur={(e) => e.target.value !== shop.headline && save({ headline: e.target.value })}
              />
            </div>
            <div>
              <label className="label">WhatsApp number</label>
              <input
                className="input" defaultValue={shop.whatsapp} placeholder="2348030000000"
                onBlur={(e) => e.target.value !== shop.whatsapp && save({ whatsapp: e.target.value })}
              />
            </div>
            <div>
              <label className="label">Delivery note</label>
              <input
                className="input" defaultValue={shop.delivery_note} placeholder="Delivery within Ikeja"
                onBlur={(e) => e.target.value !== shop.delivery_note && save({ delivery_note: e.target.value })}
              />
            </div>
            <div>
              <label className="label">Delivery fee</label>
              <input
                className="input" inputMode="decimal" placeholder="0"
                value={deliveryCharge}
                onChange={(e) => setDeliveryCharge(formatAmountInput(e.target.value))}
                onBlur={() => {
                  const stripped = stripCommas(deliveryCharge) || '0'
                  if (stripped !== (shop.fixed_delivery_charge ?? '0')) save({ fixed_delivery_charge: stripped })
                }}
              />
              <p className="mt-1 text-[11px] text-slate-500">Flat charge added at checkout for delivery orders. Leave 0 to charge nothing.</p>
            </div>
            <div>
              <label className="label">Free delivery above</label>
              <input
                className="input" inputMode="decimal" placeholder="No free-delivery rule"
                value={deliveryThreshold}
                onChange={(e) => setDeliveryThreshold(formatAmountInput(e.target.value))}
                onBlur={() => {
                  const stripped = stripCommas(deliveryThreshold)
                  const newVal = stripped === '' ? null : stripped
                  if (newVal !== shop.free_delivery_threshold) save({ free_delivery_threshold: newVal })
                }}
              />
              <p className="mt-1 text-[11px] text-slate-500">Orders at or above this subtotal skip the delivery fee. Leave blank for none.</p>
            </div>
          </div>

          <div className="flex flex-wrap gap-4 pt-1">
            {([
              ['is_published', 'Published', 'Customers can reach the page'],
              ['accepts_orders', 'Taking orders', 'Turn off to browse only'],
              ['hide_out_of_stock', 'Hide sold-out items', 'Rather than showing them greyed out'],
            ] as const).map(([key, label, hint]) => (
              <label key={key} className="flex items-start gap-2 text-sm text-slate-300">
                <input
                  type="checkbox" className="mt-0.5 h-4 w-4 accent-brand-500"
                  checked={Boolean(shop[key])} disabled={saving}
                  onChange={(e) => save({ [key]: e.target.checked } as Partial<Shop>)}
                />
                <span>{label}<span className="block text-[11px] text-slate-500">{hint}</span></span>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* ── Orders ──────────────────────────────────────────────────────── */}
      <div className="card overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-surface-700">
                {['Placed', 'Reference', 'Customer', 'For', 'Total', 'Status', ''].map((h) => (
                  <th key={h} className="px-5 py-3.5 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {orders.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-5 py-12 text-center">
                    <Store size={28} className="mx-auto mb-2 text-slate-600" />
                    <p className="text-slate-500">No orders yet</p>
                  </td>
                </tr>
              ) : orders.map((o) => (
                <tr key={o.id} className="table-row">
                  <td className="px-5 py-3.5 text-slate-400">{formatDate(o.created_at)}</td>
                  <td className="px-5 py-3.5 font-mono text-white">{o.reference}</td>
                  <td className="px-5 py-3.5">
                    <span className="text-white">{o.customer_name}</span>
                    <span className="block text-[11px] text-slate-500">{o.customer_phone}</span>
                  </td>
                  <td className="px-5 py-3.5 text-slate-400">
                    {o.table_name ? `Table ${o.table_name}` : o.fulfilment}
                    {o.delivery_address && (
                      <span className="block truncate text-[11px] text-slate-500" title={o.delivery_address}>
                        {o.delivery_address}
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-3.5 text-right font-mono text-white">{formatCurrency(o.total)}</td>
                  <td className="px-5 py-3.5">
                    <span className={STATUS_BADGE[o.status]}>{o.status_label}</span>
                    {o.invoice_number && (
                      <span className="block text-[11px] text-slate-500">{o.invoice_number}</span>
                    )}
                  </td>
                  <td className="px-5 py-3.5">
                    <div className="flex items-center gap-1.5">
                      {o.status === 'placed' && (
                        <button
                          onClick={() => accept(o)} disabled={busyId === o.id}
                          className="btn-primary inline-flex items-center gap-1.5 px-3 py-1.5 text-xs"
                        >
                          {busyId === o.id ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                          Accept
                        </button>
                      )}
                      {o.status === 'confirmed' && (
                        <button onClick={() => setStatus(o, 'ready')} className="btn-ghost px-2.5 py-1 text-xs">
                          Mark ready
                        </button>
                      )}
                      {o.status === 'ready' && (
                        <button onClick={() => setStatus(o, 'completed')} className="btn-ghost px-2.5 py-1 text-xs">
                          Complete
                        </button>
                      )}
                      {o.status !== 'cancelled' && o.status !== 'completed' && (
                        <button
                          onClick={() => setStatus(o, 'cancelled')}
                          className="btn-ghost p-1.5 text-slate-500 hover:text-red-400" title="Cancel"
                        >
                          <X size={13} />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
