/**
 * Register — the dedicated till surface.
 *
 * Deliberately narrower than the back-office sale screen, following the split
 * every major POS uses (Square, Shopify, Odoo): one shared sale engine, two
 * surfaces. A cashier gets scan → tender → next and nothing else. No cost
 * price, no margin, no price editing, no credit sales, no navigation to wander
 * into. The fuller screen at /sales/new stays for owners raising an invoice.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertTriangle, Banknote, CreditCard, Landmark, Loader2, LogOut, Minus, Plus,
  Printer, Search, ShoppingCart, Trash2, Wallet, X,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { inventoryApi, salesApi, tillApi } from '@/services/api'
import { printReceipt } from '@/lib/receipt'
import type { ReceiptData } from '@/lib/receipt'
import { useReceiptDefaults } from '@/hooks/useReceiptDefaults'
import { formatCurrency, formatDate } from '@/lib/utils'
import { useAuthStore } from '@/store/authStore'
import type { Product } from '@/types'

interface ModOption { id: string; name: string; price_delta: string; is_default: boolean; is_active: boolean }
interface ModGroup {
  id: string; name: string; is_required: boolean
  min_choices: number; max_choices: number; options: ModOption[]
}

// A line key folds in the chosen options, so "Jollof — Large" and
// "Jollof — Regular" sit as two separate rows rather than merging.
interface Line {
  key: string
  product: Product
  quantity: number
  unit_price: number
  optionIds: string[]
  modifierNames: string[]
}
interface HeldBasket { id: string; label: string; at: string; lines: Line[] }

const lineKey = (productId: string, optionIds: string[]) =>
  `${productId}::${[...optionIds].sort().join(',')}`

/** Tenders a cashier may take. Credit is absent on purpose — extending credit
 *  is an owner decision, not something to do at a busy counter.
 *  `settingsKey` maps to Organisation.enabled_payment_types (Settings →
 *  Payments → Accepted Tender Types) — the on-the-wire `key` values (e.g.
 *  'pos' for card) stay unchanged since till reconciliation already keys
 *  off them. */
const TENDERS = [
  { key: 'cash', label: 'Cash', icon: Banknote, settingsKey: 'cash' },
  { key: 'pos', label: 'Card', icon: CreditCard, settingsKey: 'card' },
  { key: 'bank_transfer', label: 'Transfer', icon: Landmark, settingsKey: 'bank_transfer' },
  { key: 'wallet', label: 'Wallet', icon: Wallet, settingsKey: 'wallet' },
] as const

export default function PosRegisterPage() {
  const navigate = useNavigate()
  const { user, organisation } = useAuthStore()
  const cashierName = user ? `${user.first_name} ${user.last_name}`.trim() || user.email : ''
  const receiptDefaults = useReceiptDefaults()
  // Kept so a cashier can hand over a second copy without re-opening the
  // sale: the customer asks, the paper jams, the roll runs out mid-print.
  const [lastReceipt, setLastReceipt] = useState<ReceiptData | null>(null)

  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Product[]>([])
  const [busy, setBusy] = useState(false)
  const [lines, setLines] = useState<Line[]>([])
  const [tendered, setTendered] = useState('')
  const scanRef = useRef<HTMLInputElement>(null)

  // The scan box owns focus: a cashier never clicks into it, they just scan.
  const refocus = () => { window.setTimeout(() => scanRef.current?.focus(), 0) }
  useEffect(() => { refocus() }, [])

  // ── Till ────────────────────────────────────────────────────────────────
  const [tillOpen, setTillOpen] = useState<boolean | null>(null)
  useEffect(() => {
    tillApi.current().then(({ data }) => setTillOpen(!!data.open)).catch(() => setTillOpen(null))
  }, [])

  // ── Catalogue ───────────────────────────────────────────────────────────
  const [catalogue, setCatalogue] = useState<Product[]>([])
  useEffect(() => {
    inventoryApi.sellableProducts({ is_active: true, page_size: 60 })
      .then(({ data }) => setCatalogue(data.results ?? data))
      .catch(() => { /* the scan box still works without tiles */ })
  }, [])

  useEffect(() => {
    if (!query.trim()) { setResults([]); return }
    const t = setTimeout(async () => {
      try {
        const { data } = await inventoryApi.sellableProducts({ search: query, is_active: true })
        setResults(data.results ?? data)
      } catch { /* silent — scanning still works */ }
    }, 200)
    return () => clearTimeout(t)
  }, [query])

  // ── Modifiers ───────────────────────────────────────────────────────────
  // Cached per product: most menus reuse "Size" / "Extras" across many items,
  // so this avoids a round trip on every single add.
  const modifierCache = useRef<Map<string, ModGroup[]>>(new Map())
  const [picking, setPicking] = useState<{ product: Product; groups: ModGroup[] } | null>(null)
  const [picked, setPicked] = useState<Record<string, string[]>>({})

  const loadGroups = async (product: Product): Promise<ModGroup[]> => {
    const cached = modifierCache.current.get(product.id)
    if (cached) return cached
    try {
      const { data } = await inventoryApi.modifierGroupsFor(product.id)
      const groups: ModGroup[] = data.results ?? []
      modifierCache.current.set(product.id, groups)
      return groups
    } catch {
      return []   // a lookup failure must never block a sale
    }
  }

  const addLine = (product: Product, optionIds: string[], modifierNames: string[], delta: number) => {
    const key = lineKey(product.id, optionIds)
    setLines((prev) => {
      const found = prev.find((l) => l.key === key)
      if (found) {
        return prev.map((l) => l.key === key ? { ...l, quantity: l.quantity + 1 } : l)
      }
      return [...prev, {
        key, product, quantity: 1,
        unit_price: parseFloat(product.selling_price) + delta,
        optionIds, modifierNames,
      }]
    })
  }

  // ── Basket ──────────────────────────────────────────────────────────────
  const add = async (product: Product) => {
    const groups = await loadGroups(product)
    if (groups.length === 0) {
      addLine(product, [], [], 0)
      setQuery(''); setResults([]); refocus()
      return
    }
    // Pre-select each group's default option, so a cashier who agrees with the
    // defaults can just press Add without touching anything.
    const defaults: Record<string, string[]> = {}
    for (const g of groups) {
      const def = g.options.find((o) => o.is_default && o.is_active)
      defaults[g.id] = def ? [def.id] : []
    }
    setPicked(defaults)
    setPicking({ product, groups })
    setQuery(''); setResults([])
  }

  const toggleOption = (group: ModGroup, optionId: string) => {
    setPicked((prev) => {
      const current = prev[group.id] ?? []
      const isSingle = group.max_choices === 1
      if (isSingle) {
        return { ...prev, [group.id]: current.includes(optionId) ? [] : [optionId] }
      }
      const has = current.includes(optionId)
      if (has) return { ...prev, [group.id]: current.filter((id) => id !== optionId) }
      if (group.max_choices && current.length >= group.max_choices) {
        toast.error(`Choose up to ${group.max_choices} from ${group.name}`)
        return prev
      }
      return { ...prev, [group.id]: [...current, optionId] }
    })
  }

  const confirmPicking = () => {
    if (!picking) return
    const missing = picking.groups.find(
      (g) => g.is_required && (picked[g.id] ?? []).length < Math.max(1, g.min_choices),
    )
    if (missing) { toast.error(`Please choose ${missing.name.toLowerCase()}`); return }

    const allIds = picking.groups.flatMap((g) => picked[g.id] ?? [])
    const names: string[] = []
    let delta = 0
    for (const g of picking.groups) {
      for (const id of (picked[g.id] ?? [])) {
        const opt = g.options.find((o) => o.id === id)
        if (opt) { names.push(opt.name); delta += parseFloat(opt.price_delta) || 0 }
      }
    }
    addLine(picking.product, allIds, names, delta)
    setPicking(null)
    refocus()
  }

  const setQty = (key: string, qty: number) =>
    setLines((prev) => prev.map((l) => l.key === key ? { ...l, quantity: qty } : l)
      .filter((l) => l.quantity > 0))

  const removeLine = (key: string) => setLines((prev) => prev.filter((l) => l.key !== key))

  const total = useMemo(
    () => lines.reduce((sum, l) => sum + l.unit_price * l.quantity, 0),
    [lines],
  )
  const change = Math.max(0, (parseFloat(tendered) || 0) - total)

  /** A scanner types fast and sends Enter — read the element, not React state. */
  const onScan = async (code: string) => {
    const q = code.trim()
    if (!q) return
    setBusy(true)
    try {
      const { data } = await inventoryApi.sellableProducts({ search: q, is_active: true })
      const found: Product[] = data.results ?? data
      const exact = found.find(
        (p) => p.barcode?.toLowerCase() === q.toLowerCase() || p.sku?.toLowerCase() === q.toLowerCase(),
      )
      if (exact) return add(exact)
      if (found.length === 1) return add(found[0])
      setResults(found)
      if (found.length === 0) toast.error(`Nothing found for "${q}"`)
    } catch {
      toast.error('Could not look that up')
    } finally { setBusy(false) }
  }

  // ── Held baskets ────────────────────────────────────────────────────────
  const HELD_KEY = `audity-register-held-${organisation?.id ?? 'none'}`
  const [held, setHeld] = useState<HeldBasket[]>(() => {
    try { return JSON.parse(localStorage.getItem(HELD_KEY) || '[]') } catch { return [] }
  })
  const saveHeld = (next: HeldBasket[]) => {
    setHeld(next)
    try { localStorage.setItem(HELD_KEY, JSON.stringify(next)) } catch { /* quota */ }
  }
  const newId = () => {
    try {
      if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
    } catch { /* older Android WebView on POS terminals */ }
    return `h-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  }
  const hold = () => {
    if (lines.length === 0) { toast.error('Nothing to hold'); return }
    saveHeld([...held, {
      id: newId(), label: `${lines.length} item${lines.length === 1 ? '' : 's'}`,
      at: new Date().toISOString(), lines,
    }])
    setLines([]); setTendered(''); toast.success('Basket held'); refocus()
  }
  const resume = (id: string) => {
    const b = held.find((x) => x.id === id)
    if (!b) return
    if (lines.length) { toast.error('Finish or hold the current basket first'); return }
    setLines(b.lines); saveHeld(held.filter((x) => x.id !== id)); refocus()
  }

  // ── Take payment ────────────────────────────────────────────────────────
  const takePayment = async (method: string) => {
    if (lines.length === 0) { toast.error('Basket is empty'); return }
    setBusy(true)
    try {
      const { data } = await salesApi.create({
        payment_method: method,
        amount_paid: total.toFixed(2),
        amount_tendered: method === 'cash' && tendered ? tendered : null,
        items: lines.map((l) => ({
          product: l.product.id,
          quantity: String(l.quantity),
          // The base selling price, NOT unit_price — unit_price already
          // includes the modifier delta, and the backend recomputes that
          // delta itself from optionIds. Sending the modified price as the
          // base would double-count it.
          unit_price: l.product.selling_price,
          modifiers: l.optionIds,
        })),
      })
      toast.success(method === 'cash' && change > 0 ? `Change ${formatCurrency(change)}` : 'Paid')

      const receipt: ReceiptData = {
        ...receiptDefaults,
        invoiceNumber: data?.invoice_number ?? '',
        date: formatDate(data?.issue_date ?? new Date().toISOString()),
        cashier: cashierName,
        lines: lines.map((l) => ({
          name: l.product.name, qty: l.quantity,
          unit_price: l.unit_price, line_total: l.unit_price * l.quantity,
          modifiers: l.modifierNames,
        })),
        subtotal: total, total,
        payments: [{ method, amount: total }],
        amountTendered: method === 'cash' && tendered ? tendered : undefined,
        change: method === 'cash' && tendered ? change : undefined,
        firsIrn: data?.firs_irn,
        qrCodeBase64: data?.firs_qr_code,
      } as ReceiptData
      setLastReceipt(receipt)
      void printReceipt(receipt)

      setLines([]); setTendered(''); refocus()
    } catch (err) {
      const apiErr = (err as { response?: { data?: { error?: unknown } } })?.response?.data?.error
      toast.error(typeof apiErr === 'string' ? apiErr : 'Could not complete the sale')
    } finally { setBusy(false) }
  }

  const tiles = query.trim() ? results : catalogue
  const enabledTenders = TENDERS.filter((t) => (organisation?.enabled_payment_types ?? TENDERS.map((x) => x.settingsKey)).includes(t.settingsKey))

  return (
    // Full screen, no sidebar — the register owns the device.
    <div className="fixed inset-0 z-40 flex flex-col bg-surface-950">
      <header className="flex items-center gap-3 border-b border-surface-700 bg-surface-900 px-4 py-2.5">
        <ShoppingCart size={17} className="text-brand-400" />
        <span className="font-semibold text-white">Register</span>
        <span className="text-xs text-slate-500">{organisation?.name}</span>
        <span className="ml-auto text-xs text-slate-400">{cashierName}</span>
        {tillOpen === false && (
          <span className="flex items-center gap-1.5 rounded-full border border-amber-500/40 px-2.5 py-1 text-[11px] text-amber-300">
            <AlertTriangle size={11} /> No till open
          </span>
        )}
        <button
          onClick={() => navigate('/pos/till')}
          className="btn-ghost px-2.5 py-1 text-[11px]" title="Till and cash-up"
        >
          <Wallet size={13} />
        </button>
        <button
          onClick={() => navigate('/dashboard')}
          className="btn-ghost px-2.5 py-1 text-[11px]" title="Leave the register"
        >
          <LogOut size={13} />
        </button>
      </header>

      <div className="grid flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[1fr_360px]">
        {/* ── Catalogue ─────────────────────────────────────────────── */}
        <section className="flex flex-col overflow-hidden p-4">
          <div className="relative mb-3">
            <Search size={17} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            {busy && <Loader2 size={14} className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-brand-400" />}
            <input
              ref={scanRef}
              className="input py-3 pl-10 text-base"
              placeholder="Scan barcode or search…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') { e.preventDefault(); onScan(e.currentTarget.value) }
              }}
            />
          </div>

          {held.length > 0 && (
            <div className="mb-3 flex flex-wrap gap-2">
              {held.map((b) => (
                <button
                  key={b.id} onClick={() => resume(b.id)}
                  className="rounded-lg border border-surface-600 px-3 py-1.5 text-xs text-slate-300 hover:border-brand-500"
                >
                  Resume {b.label}
                </button>
              ))}
            </div>
          )}

          <div className="grid flex-1 auto-rows-min grid-cols-2 gap-2.5 overflow-y-auto sm:grid-cols-3 xl:grid-cols-4">
            {tiles.map((p) => (
              <button
                key={p.id} onClick={() => add(p)}
                className="flex min-h-[76px] flex-col justify-between rounded-xl border border-surface-700 bg-surface-800 p-3 text-left transition-colors hover:border-brand-500"
              >
                <span className="text-[13px] font-semibold leading-tight text-white">{p.name}</span>
                {/* Selling price only — a cashier never sees cost or margin. */}
                <span className="font-mono text-[13px] text-slate-300">
                  {formatCurrency(p.selling_price)}
                </span>
              </button>
            ))}
            {tiles.length === 0 && (
              <p className="col-span-full py-10 text-center text-sm text-slate-500">
                {query.trim() ? 'Nothing matches that' : 'No products yet'}
              </p>
            )}
          </div>
        </section>

        {/* ── Basket ────────────────────────────────────────────────── */}
        <aside className="flex flex-col overflow-hidden border-t border-surface-700 bg-surface-900 lg:border-l lg:border-t-0">
          <div className="flex items-center gap-2 border-b border-surface-700 px-4 py-2.5">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Basket</span>
            <span className="text-xs text-slate-500">{lines.length} item{lines.length === 1 ? '' : 's'}</span>
            <button onClick={hold} className="btn-ghost ml-auto px-2.5 py-1 text-[11px]">Hold</button>
          </div>

          <div className="flex-1 overflow-y-auto px-4">
            {lines.length === 0 ? (
              <p className="py-12 text-center text-sm text-slate-600">Scan an item to begin</p>
            ) : lines.map((l) => (
              <div key={l.key} className="border-b border-surface-800 py-2.5">
                <div className="flex items-start gap-2">
                  <div className="flex-1">
                    <span className="text-[13px] font-semibold text-white">{l.product.name}</span>
                    {l.modifierNames.length > 0 && (
                      <span className="block text-[11px] italic text-slate-500">
                        {l.modifierNames.join(', ')}
                      </span>
                    )}
                  </div>
                  <span className="font-mono text-[13px] text-white">
                    {formatCurrency(l.unit_price * l.quantity)}
                  </span>
                  <button
                    onClick={() => removeLine(l.key)}
                    className="text-slate-600 hover:text-red-400" aria-label="Remove"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
                <div className="mt-1.5 flex items-center gap-2">
                  <button onClick={() => setQty(l.key, l.quantity - 1)} className="btn-ghost p-1"><Minus size={12} /></button>
                  {/* Decimal: weighed goods are rung up as 1.42 kg. */}
                  <input
                    className="input w-20 py-1 text-center text-xs" inputMode="decimal"
                    value={l.quantity}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value)
                      if (!isNaN(v) && v > 0) setQty(l.key, v)
                    }}
                  />
                  <button onClick={() => setQty(l.key, l.quantity + 1)} className="btn-ghost p-1"><Plus size={12} /></button>
                  <span className="ml-auto font-mono text-[11px] text-slate-500">
                    @ {formatCurrency(l.unit_price)}
                  </span>
                </div>
              </div>
            ))}
          </div>

          <div className="border-t border-surface-700 p-4">
            <div className="mb-3 flex items-baseline justify-between">
              <span className="text-sm text-slate-400">Total</span>
              <span className="font-mono text-3xl font-bold text-white">{formatCurrency(total)}</span>
            </div>

            <input
              className="input mb-2 text-right font-mono" inputMode="decimal"
              placeholder="Cash tendered (optional)"
              value={tendered} onChange={(e) => setTendered(e.target.value)}
            />
            {change > 0 && (
              <p className="mb-2 text-right text-sm text-emerald-400">
                Change <span className="font-mono font-bold">{formatCurrency(change)}</span>
              </p>
            )}

            <div className="grid grid-cols-2 gap-2">
              {enabledTenders.map((t) => (
                <button
                  key={t.key} onClick={() => takePayment(t.key)} disabled={busy || lines.length === 0}
                  className="flex flex-col items-center gap-1 rounded-xl bg-brand-500 py-3 text-xs font-semibold text-white disabled:opacity-40"
                >
                  <t.icon size={15} />{t.label}
                </button>
              ))}
            </div>

            {lastReceipt && lines.length === 0 && (
              <button
                onClick={() => void printReceipt(lastReceipt)}
                className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl border border-surface-700 py-2.5 text-xs font-semibold text-slate-300 hover:border-surface-500 hover:text-white"
                title={`Print another copy of ${lastReceipt.invoiceNumber}`}
              >
                <Printer size={14} /> Print receipt again
                <span className="font-mono text-[10px] text-slate-500">{lastReceipt.invoiceNumber}</span>
              </button>
            )}

            {lines.length > 0 && (
              <button
                onClick={() => { setLines([]); setTendered(''); refocus() }}
                className="btn-ghost mt-2 w-full py-2 text-xs text-slate-500"
              >
                <X size={12} /> Clear basket
              </button>
            )}
          </div>
        </aside>
      </div>

      {/* ── Modifier picker ─────────────────────────────────────────── */}
      {picking && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70" onClick={() => setPicking(null)} />
          <div className="relative flex max-h-[85vh] w-full max-w-md flex-col rounded-2xl bg-surface-900 border border-surface-700">
            <div className="flex items-center gap-2 border-b border-surface-700 px-5 py-3.5">
              <h2 className="font-semibold text-white">{picking.product.name}</h2>
              <button onClick={() => setPicking(null)} className="ml-auto text-slate-400" aria-label="Close">
                <X size={18} />
              </button>
            </div>

            <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
              {picking.groups.map((g) => (
                <div key={g.id}>
                  <div className="mb-2 flex items-center gap-2">
                    <span className="text-sm font-semibold text-white">{g.name}</span>
                    {g.is_required && <span className="text-[10px] uppercase tracking-wide text-amber-400">Required</span>}
                    {!g.is_required && g.max_choices !== 1 && (
                      <span className="text-[11px] text-slate-500">
                        pick up to {g.max_choices || 'any'}
                      </span>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    {g.options.filter((o) => o.is_active).map((o) => {
                      const on = (picked[g.id] ?? []).includes(o.id)
                      const delta = parseFloat(o.price_delta) || 0
                      return (
                        <button
                          key={o.id} onClick={() => toggleOption(g, o.id)}
                          className={`flex w-full items-center justify-between rounded-xl border px-3.5 py-2.5 text-left text-sm ${
                            on ? 'border-brand-500 bg-brand-500/10 text-white' : 'border-surface-700 text-slate-300'
                          }`}
                        >
                          <span>{o.name}</span>
                          <span className="font-mono text-xs text-slate-400">
                            {delta !== 0 ? `${delta > 0 ? '+' : ''}${formatCurrency(delta)}` : '—'}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>

            <div className="border-t border-surface-700 p-4">
              <button onClick={confirmPicking} className="btn-primary w-full py-2.5 justify-center">
                Add to basket
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
