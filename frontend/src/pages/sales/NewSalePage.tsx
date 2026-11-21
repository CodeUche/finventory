/**
 * New sale & invoice — one page for a till sale, a credit sale, an invoice and a
 * proforma. Layout and wording follow the designer's "New sale & new invoice" screen.
 *
 * Two screens were merged here: the old New Sale (cart, hold/resume, receipt, tender and
 * change, till notice) and the old New Invoice (dates, fulfil later, delivery, VAT per line).
 * Both still post through salesApi.create and ALL the money maths still goes through
 * lib/saleMath, so a total is exactly what it was on either old screen.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Grid3x3, Loader2, Mail, Plus, Search, Trash2, Upload, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { customerApi, inventoryApi, locationApi, salesApi, savedMessage, taxApi, teamApi, tillApi } from '@/services/api'
import { printReceipt, formatReceiptTime } from '@/lib/receipt'
import { useReceiptDefaults } from '@/hooks/useReceiptDefaults'
import { formatCurrency, formatDate, normalizeAmountStr, stripCommas } from '@/lib/utils'
import { saleBreakdown, saleLine, type SaleLineInput } from '@/lib/saleMath'
import AmountInput from '@/components/AmountInput'
import DateInput from '@/components/DateInput'
import { useNotifications } from '@/contexts/NotificationsContext'
import { useAuthStore } from '@/store/authStore'
import { heldBasketsKey, slimCustomer, slimProduct } from '@/lib/localUserData'
import { alertDialog, confirmDialog, promptDialog } from '@/lib/dialog'
import { buildInvoicePDF } from '@/lib/invoicePdf'
import { saveBlobFile } from '@/lib/saveBlobFile'
import type { Customer, Invoice, Product, TaxClass, TeamMember, Warehouse as WarehouseType } from '@/types'

// ── Lines ────────────────────────────────────────────────────────────────────
interface Line {
  key: number
  product: Product | null
  qty: string
  price: string
  disc: string
  // VAT: starts from the product's own setting; a line may switch it off, pick another
  // class, or type a rate. Same rules as the old New Invoice screen.
  vatOn: boolean
  taxClass: string | null
  manualRate: string
}

let lineKey = 0
const blankLine = (): Line => ({
  key: ++lineKey, product: null, qty: '1', price: '', disc: '0', vatOn: false, taxClass: null, manualRate: '',
})
const lineFromProduct = (key: number, p: Product, qty = '1', price?: string, disc = '0'): Line => ({
  key, product: p, qty, price: price ?? normalizeAmountStr(p.selling_price), disc,
  vatOn: p.is_taxable, taxClass: p.tax_class, manualRate: '',
})

// A held basket is stored in the shape the old New Sale screen used, so baskets held
// before this page existed still resume.
interface HeldItem {
  product: Product
  quantity: number
  unit_price: number
  discount_percent: number
  vat?: { on: boolean; taxClass: string | null; manualRate: string }
}
interface HeldBasket { id: string; label: string; at: string; cart: HeldItem[]; customer?: Customer | null }
const OLD_BASKET_MS = 7 * 86400000

const today = new Date().toISOString().split('T')[0]
const inThirtyDays = new Date(Date.now() + 30 * 86400000).toISOString().split('T')[0]

const METHODS: { value: string; label: string }[] = [
  { value: 'cash', label: 'Cash' },
  { value: 'pos', label: 'Card / POS' },
  { value: 'bank_transfer', label: 'Bank transfer' },
]

// Paid-before-delivery and part-payment choices. Built and wired, but kept behind ONE switch
// so they can be turned off in a single place if the books team wants them held back.
// When on, money taken before delivery is held as a customer deposit until delivery.
const ENABLE_DEFERRED_PAYMENT_COMBOS = true

type Mode = 'sale' | 'invoice' | 'proforma'

export default function NewSalePage() {
  const navigate = useNavigate()
  const { refetch: refetchAlerts } = useNotifications()
  const { user, organisation } = useAuthStore()
  const receiptDefaults = useReceiptDefaults()
  const currentUserName = user ? `${user.first_name} ${user.last_name}`.trim() || user.email : ''

  // ── Customer ───────────────────────────────────────────────────────────────
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

  // ── Warehouse, branch, dates ───────────────────────────────────────────────
  const [warehouses, setWarehouses] = useState<WarehouseType[]>([])
  const [selectedWarehouse, setSelectedWarehouse] = useState('')
  const [locations, setLocations] = useState<{ id: string; name: string }[]>([])
  const [selectedLocation, setSelectedLocation] = useState('')
  const [issueDate, setIssueDate] = useState(today)
  const [dueDate, setDueDate] = useState(inThirtyDays)
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

  // ── VAT classes ────────────────────────────────────────────────────────────
  // Rates are empty when the business does not charge VAT, matching the server.
  const chargesVat = organisation?.charges_vat !== false
  const [taxClasses, setTaxClasses] = useState<TaxClass[]>([])
  useEffect(() => {
    if (!chargesVat) { setTaxClasses([]); return }
    taxApi.classes({ silentErrors: true }).then(({ data }) => {
      setTaxClasses(data.results ?? data)
    }).catch(() => {})
  }, [chargesVat])
  const taxRates: Record<string, number> = {}
  for (const c of taxClasses) taxRates[c.id] = parseFloat(c.rate) || 0

  // ── Items ──────────────────────────────────────────────────────────────────
  const [lines, setLines] = useState<Line[]>(() => [blankLine()])
  const updateLine = (key: number, patch: Partial<Line>) =>
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  const removeLine = (key: number) =>
    setLines((prev) => (prev.length <= 1 ? [blankLine()] : prev.filter((l) => l.key !== key)))
  const addBlankLine = () => setLines((prev) => [...prev, blankLine()])

  /** Put a product into the basket: add one to a line that already has it, else fill the
   *  first empty row, else add a row. */
  const addProduct = (p: Product) => {
    setLines((prev) => {
      const existing = prev.find((l) => l.product?.id === p.id)
      if (existing) {
        return prev.map((l) => (l === existing ? { ...l, qty: String((parseFloat(l.qty) || 0) + 1) } : l))
      }
      const empty = prev.find((l) => !l.product)
      if (empty) return prev.map((l) => (l === empty ? lineFromProduct(l.key, p) : l))
      return [...prev, lineFromProduct(++lineKey, p)]
    })
  }

  const filled = lines.filter((l) => l.product)
  const lineRate = (l: Line) => {
    // The VAT tick box is the master switch: unticked is always zero.
    if (!l.vatOn) return 0
    if (l.manualRate !== '') return parseFloat(l.manualRate) || 0
    return l.taxClass ? taxRates[l.taxClass] ?? 0 : 0
  }
  const toSaleLine = (l: Line): SaleLineInput => ({
    unitPrice: parseFloat(stripCommas(l.price)) || 0,
    quantity: parseFloat(l.qty) || 0,
    discountPercent: Math.min(100, Math.max(0, parseFloat(l.disc) || 0)),
    taxRate: lineRate(l),
    inclusive: l.product?.tax_type === 'inclusive',
  })
  const [adjustment, setAdjustment] = useState('')
  const [delivery, setDelivery] = useState('')
  // Signed number: "-500" or "+200". null means what was typed is not a number.
  const adjustmentClean = stripCommas(adjustment.replace(/\s/g, '')).replace('+', '')
  const adjustmentParsed: number | null = adjustmentClean === '' ? 0 : (/^-?\d*\.?\d+$|^-?\d+\.$/.test(adjustmentClean) ? Number(adjustmentClean) : null)
  const adjustmentNum = adjustmentParsed ?? 0
  const deliveryNum = parseFloat(stripCommas(delivery)) || 0
  // Every figure comes from one breakdown that follows the server step by step: the adjustment is spread
  // over the lines before VAT, so VAT, Item discounts and the total all move with it.
  const breakdown = saleBreakdown(filled.map(toSaleLine), deliveryNum, adjustmentNum)
  const amounts = breakdown.lines
  const subtotal = breakdown.subtotal
  const discountTotal = breakdown.discount
  const taxTotal = amounts.reduce((s, a, i) => s + (filled[i].product?.tax_type === 'inclusive' ? 0 : a.tax), 0)
  const taxIncluded = amounts.reduce((s, a, i) => s + (filled[i].product?.tax_type === 'inclusive' ? a.tax : 0), 0)
  const grandTotal = breakdown.total

  // ── Product search / scan box ──────────────────────────────────────────────
  const [productQuery, setProductQuery] = useState('')
  const [products, setProducts] = useState<Product[]>([])
  const [showProductDrop, setShowProductDrop] = useState(false)
  const [scanning, setScanning] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)
  const searchWrapRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (searchWrapRef.current && !searchWrapRef.current.contains(e.target as Node)) setShowProductDrop(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])
  useEffect(() => {
    if (!productQuery.trim()) { setProducts([]); setShowProductDrop(false); return }
    let cancelled = false
    const t = setTimeout(async () => {
      try {
        const { data } = await inventoryApi.sellableProducts({ search: productQuery, is_active: true })
        if (!cancelled) { setProducts(data.results ?? data); setShowProductDrop(true) }
      } catch (err: unknown) {
        if (!cancelled) {
          const d = (err as { response?: { data?: { error?: { message?: string } | string } } })?.response?.data
          const msg = typeof d?.error === 'string' ? d.error : d?.error?.message
          if (msg) toast.error(msg)
        }
      }
    }, 200)
    return () => { cancelled = true; clearTimeout(t) }
  }, [productQuery])

  const pickFromSearch = (p: Product) => {
    addProduct(p)
    setProductQuery('')
    setShowProductDrop(false)
    searchRef.current?.focus()
  }

  // A scanner is a keyboard that types fast and presses Enter. Look the code up as an exact
  // barcode/SKU first and drop it straight in; only if nothing matches exactly fall back to
  // the dropdown, so a scan never makes the cashier pick from a list.
  const handleScan = async (code: string) => {
    const query = code.trim()
    if (!query) {
      searchRef.current?.focus()
      toast('Ready — scan a barcode, or type a name or SKU.')
      return
    }
    setScanning(true)
    try {
      const { data } = await inventoryApi.sellableProducts({ search: query, is_active: true })
      const found: Product[] = data.results ?? data
      const exact = found.find(
        (p) => p.barcode?.toLowerCase() === query.toLowerCase() || p.sku?.toLowerCase() === query.toLowerCase(),
      )
      if (exact) { pickFromSearch(exact); return }
      if (found.length === 1) { pickFromSearch(found[0]); return }
      setProducts(found)
      setShowProductDrop(found.length > 0)
      if (found.length === 0) toast.error(`Nothing found for "${query}"`)
    } catch {
      toast.error('Could not look that up')
    } finally { setScanning(false) }
  }

  // DERIVED - not designer-approved: a keyboard-style scanner works without clicking the box.
  // When no field has the focus, a quick burst of keys ending in Enter is read as a scan.
  const scanBuf = useRef({ text: '', last: 0 })
  const handleScanRef = useRef(handleScan)
  useLayoutEffect(() => { handleScanRef.current = handleScan })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      const editable = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)
      if (editable || e.ctrlKey || e.metaKey || e.altKey) return
      const now = Date.now()
      const b = scanBuf.current
      if (now - b.last > 80) b.text = ''
      b.last = now
      if (e.key === 'Enter') {
        if (b.text.length >= 3) { e.preventDefault(); const code = b.text; b.text = ''; void handleScanRef.current(code) }
        b.text = ''
      } else if (e.key.length === 1) {
        b.text += e.key
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // ── Payment ────────────────────────────────────────────────────────────────
  const [payNow, setPayNow] = useState(true)
  const [paymentMethod, setPaymentMethod] = useState('cash')
  const [amountPaid, setAmountPaid] = useState('')
  const [applyCredit, setApplyCredit] = useState(false)
  const customerStoreCredit = parseFloat(selectedCustomer?.store_credit ?? '0')
  const creditApplied = applyCredit && customerStoreCredit > 0 ? Math.min(customerStoreCredit, grandTotal) : 0
  const effectiveBalanceDue = grandTotal - creditApplied
  const tenderedNum = parseFloat(stripCommas(amountPaid)) || 0
  const changeGiven = payNow && paymentMethod === 'cash' && tenderedNum > effectiveBalanceDue
    ? tenderedNum - effectiveBalanceDue : 0
  useEffect(() => {
    if (!selectedCustomer || customerStoreCredit <= 0) setApplyCredit(false)
  }, [selectedCustomer, customerStoreCredit])

  // No till open: cash taken now cannot be counted at end of shift.
  const [tillOpen, setTillOpen] = useState<boolean | null>(null)
  const [tillChecked, setTillChecked] = useState(false)
  useEffect(() => {
    tillApi.current().then(({ data }) => setTillOpen(!!data.open)).catch(() => setTillOpen(null)).finally(() => setTillChecked(true))
  }, [])

  // ── Fulfilment, notes, who sold ────────────────────────────────────────────
  // Default is "Fulfill now": that is what every till sale has always done. An invoice that
  // should wait for delivery picks "Fulfill later".
  // Starts on "Fulfill now" for every case. A credit sale with a customer used to deduct stock and post
  // to the ledger at once; starting it on "Fulfill later" silently changed that (checked on staging),
  // so an invoice that should wait for delivery needs one click on "Fulfill later".
  const [fulfilChoice, setFulfilChoice] = useState<'now' | 'later' | null>(null)
  const fulfil: 'now' | 'later' = fulfilChoice ?? 'now'
  const setFulfil = (v: 'now' | 'later') => setFulfilChoice(v)
  const [notes, setNotes] = useState('')
  const [soldBy, setSoldBy] = useState(currentUserName)
  useEffect(() => { if (!soldBy && currentUserName) setSoldBy(currentUserName) }, [currentUserName, soldBy])
  const [team, setTeam] = useState<string[]>([])
  useEffect(() => {
    teamApi.members({ silentErrors: true }).then(({ data }) => {
      const list: TeamMember[] = data.results ?? data
      setTeam(list.filter((m) => m.is_active).map((m) => m.user_full_name || m.user_email).filter(Boolean))
    }).catch(() => {})
  }, [])
  const soldByOptions = Array.from(new Set([currentUserName, ...team].filter(Boolean)))

  // Remembered per device — a counter till wants a receipt every time, a back-office user
  // raising an invoice almost never does.
  const [autoPrint, setAutoPrint] = useState<boolean>(() => {
    try { return localStorage.getItem('audity-pos-autoprint') !== '0' } catch { return true }
  })
  const toggleAutoPrint = (on: boolean) => {
    setAutoPrint(on)
    try { localStorage.setItem('audity-pos-autoprint', on ? '1' : '0') } catch { /* non-fatal */ }
  }

  // ── Held baskets ───────────────────────────────────────────────────────────
  const HELD_KEY = heldBasketsKey(organisation?.id, user?.id)
  // Baskets saved by an earlier version carry whole product and customer records (with cost price).
  // They are cut down as they are read, and the cut-down copy is written back.
  const [held, setHeld] = useState<HeldBasket[]>(() => {
    try {
      const raw = JSON.parse(localStorage.getItem(HELD_KEY) || '[]') as HeldBasket[]
      const slim = raw.map((b) => ({
        ...b,
        cart: b.cart.map((c) => ({ ...c, product: slimProduct(c.product) })),
        customer: b.customer ? slimCustomer(b.customer) : null,
      }))
      if (raw.length) { try { localStorage.setItem(HELD_KEY, JSON.stringify(slim)) } catch { /* non-fatal */ } }
      return slim
    } catch { return [] }
  })
  const [showHeld, setShowHeld] = useState(false)
  const persistHeld = (next: HeldBasket[]) => {
    setHeld(next)
    try { localStorage.setItem(HELD_KEY, JSON.stringify(next)) } catch { /* quota — non-fatal */ }
  }
  // crypto.randomUUID needs a secure context and is missing from older Android WebViews.
  const basketId = () => {
    try { if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID() } catch { /* fall through */ }
    return `held-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  }
  const holdBasket = () => {
    if (filled.length === 0) { say('Nothing to hold.'); return }
    const label = selectedCustomer?.name || `${filled.length} item${filled.length === 1 ? '' : 's'}`
    const cart: HeldItem[] = filled.map((l) => ({
      product: slimProduct(l.product as Product),
      quantity: parseFloat(l.qty) || 1,
      unit_price: parseFloat(stripCommas(l.price)) || 0,
      discount_percent: Math.min(100, Math.max(0, parseFloat(l.disc) || 0)),
      vat: { on: l.vatOn, taxClass: l.taxClass, manualRate: l.manualRate },
    }))
    persistHeld([...held, { id: basketId(), label, at: new Date().toISOString(), cart, customer: selectedCustomer ? slimCustomer(selectedCustomer) : null }])
    setLines([blankLine()])
    setSelectedCustomer(null); setCustomerQuery('')
    say('Basket held.', 'ok')
    searchRef.current?.focus()
  }
  const resumeBasket = (id: string) => {
    const basket = held.find((b) => b.id === id)
    if (!basket) return
    if (filled.length > 0) { say('Finish or hold the current basket first.'); return }
    setLines(basket.cart.map((c) => {
      const base = lineFromProduct(++lineKey, c.product, String(c.quantity), normalizeAmountStr(String(c.unit_price)), String(c.discount_percent))
      return c.vat ? { ...base, vatOn: c.vat.on, taxClass: c.vat.taxClass, manualRate: c.vat.manualRate } : base
    }))
    if (basket.customer) {
      setSelectedCustomer(basket.customer)
      // Only the name is kept on disk; credit and balances are read fresh.
      try { customerApi.get(basket.customer.id).then(({ data }) => setSelectedCustomer(data)).catch(() => {}) } catch { /* keep the cut-down copy */ }
    }
    persistHeld(held.filter((b) => b.id !== id))
    setShowHeld(false)
    say('Basket resumed.', 'ok')
  }
  const discardBasket = (id: string) => persistHeld(held.filter((b) => b.id !== id))

  // ── Submit ─────────────────────────────────────────────────────────────────
  const [submitting, setSubmitting] = useState<Mode | null>(null)
  // DERIVED - not designer-approved: plain messages shown on the page (read out by screen
  // readers) instead of only in a toast that disappears.
  const [notice, setNotice] = useState('')
  const say = (msg: string, kind: 'ok' | 'error' = 'error') => {
    setNotice(msg)
    if (kind === 'ok') toast.success(msg); else toast.error(msg)
  }
  // Synchronous guard: the disabled state lands a render late, and a double click once
  // created two paid invoices.
  const submittingRef = useRef(false)
  const [created, setCreated] = useState<Invoice | null>(null)
  const [emailing, setEmailing] = useState(false)
  const [exporting, setExporting] = useState(false)

  const buildPayload = (mode: Mode) => {
    const isProforma = mode === 'proforma'
    const isInvoice = mode === 'invoice'
    const isCredit = !payNow
    const rawTendered = tenderedNum || effectiveBalanceDue
    const actualPaid = Math.min(rawTendered, effectiveBalanceDue)
    return {
      customer_id: selectedCustomer?.id ?? null,
      warehouse_id: selectedWarehouse,
      location_id: selectedLocation || null,
      payment_method: isCredit ? 'credit' : paymentMethod,
      amount_paid: isCredit || isProforma ? '0' : actualPaid.toFixed(2),
      amount_tendered: !isCredit && !isProforma && rawTendered > 0 ? rawTendered.toFixed(2) : null,
      credit_applied: isProforma ? '0' : creditApplied.toFixed(2),
      notes,
      sold_by: soldBy || currentUserName,
      is_proforma: isProforma,
      // Signed: minus is a discount, plus an extra charge. Left out when zero so an ordinary
      // sale posts exactly as before.
      ...(adjustmentNum !== 0 && !isProforma ? { adjustment_amount: adjustmentNum.toFixed(2) } : {}),
      ...(isInvoice ? {
        issue_date: issueDate,
        due_date: dueDate || null,
        defer_fulfillment: fulfil === 'later',
        shipping_amount: deliveryNum.toFixed(4),
      } : {}),
      // A sale or proforma never carries the invoice-only fields; "fulfil later" on a
      // credit sale is the one thing it can ask for.
      ...(!isInvoice && !isProforma && fulfil === 'later' ? { defer_fulfillment: true } : {}),
      items: filled.map((l) => {
        // Only send a tax override when the line differs from the product's own default,
        // so an untouched line posts exactly as it always has.
        const p = l.product as Product
        const overridden = l.manualRate !== '' || l.taxClass !== p.tax_class || l.vatOn !== p.is_taxable
        return {
          product_id: p.id,
          quantity: parseFloat(l.qty) || 1,
          unit_price: (parseFloat(stripCommas(l.price)) || 0).toFixed(4),
          discount_percent: Math.min(100, Math.max(0, parseFloat(l.disc) || 0)).toFixed(2),
          ...(overridden ? {
            tax_class_id: !l.vatOn || l.manualRate !== '' ? null : (l.taxClass || null),
            tax_rate: !l.vatOn ? '0.00' : (l.manualRate !== '' ? (parseFloat(l.manualRate) || 0).toFixed(2) : null),
          } : {}),
        }
      }),
    }
  }

  /** The first thing that stops this action, or null when it can go ahead. */
  const blocker = (mode: Mode): string | null => {
    if (filled.length === 0) return 'Add at least one item to continue.'
    if (!selectedWarehouse) return 'Select a warehouse first.'
    if (filled.some((l) => (parseFloat(l.qty) || 0) <= 0)) return 'Quantity must be more than 0.'
    if (filled.some((l) => (parseFloat(stripCommas(l.price)) || 0) <= 0)) return 'Price must be more than 0.'
    if (filled.some((l) => (parseFloat(l.disc) || 0) > 100)) return 'Discount cannot be more than 100%.'
    if (adjustmentParsed === null) return 'Enter a number, like -500 or 200.'
    if (breakdown.adjustmentError === 'bigger-than-invoice') return 'Adjustment is bigger than the total.'
    if (breakdown.adjustmentError === 'line-below-zero') return 'That adjustment would take a line below zero. Reduce it.'
    if (breakdown.adjustmentError === 'no-value') return 'An adjustment needs items with a value to spread it across.'
    if (grandTotal <= 0) return 'The total must be more than zero.'
    if (mode !== 'proforma' && !ENABLE_DEFERRED_PAYMENT_COMBOS) {
      if (fulfil === 'later' && payNow) return 'Paying before delivery is switched off. Choose Fulfill now, or Credit · pay later.'
      if (fulfil === 'later' && !payNow) return 'Credit with Fulfill later is switched off. Choose Fulfill now.'
      if (payNow && tenderedNum > 0 && tenderedNum < effectiveBalanceDue) return 'Part payment is switched off. Enter the full amount.'
    }
    if (mode !== 'proforma' && !payNow && !selectedCustomer) return 'Pick a customer to sell on credit.'
    if (mode !== 'proforma' && payNow && paymentMethod !== 'cash' && tenderedNum > effectiveBalanceDue + 0.004) return 'Amount is more than the total.'
    if (mode === 'invoice') {
      if (!selectedCustomer) return 'Pick a customer to create an invoice.'
      if (dueDate && issueDate && dueDate < issueDate) return 'Due date cannot be before the issue date.'
    }
    if (mode === 'sale') {
      if (deliveryNum > 0) return 'Delivery is for invoices only. Clear it, or choose Create invoice.'
    }
    if (mode === 'proforma' && deliveryNum > 0) return 'Delivery is for invoices only. Clear it, or choose Create invoice.'
    return null
  }

  const errorMessage = (err: unknown, fallback: string): string => {
    const e = err as { response?: { data?: unknown; status?: number } }
    const data = e?.response?.data as Record<string, unknown> | undefined
    if (typeof data?.error === 'string') return data.error
    const nested = data?.error as { message?: string } | undefined
    if (nested?.message) return nested.message
    if (data && typeof data === 'object') {
      const firstKey = Object.keys(data)[0]
      if (firstKey) {
        const val = data[firstKey]
        return Array.isArray(val) ? String(val[0]) : String(val)
      }
    }
    if (!e?.response) return 'Network error — check your connection'
    // No readable body: say what the status means in plain words.
    const status = (e.response as { status?: number }).status
    if (status === 409) return 'This sale was already saved or has changed. Check Sales before trying again.'
    if (status === 429) return 'Too many requests just now. Wait a moment and try again.'
    return fallback
  }

  const handleSubmit = async (mode: Mode) => {
    const why = blocker(mode)
    if (why) { say(why); return }
    if (submittingRef.current) return
    submittingRef.current = true
    setSubmitting(mode)
    try {
      const res = await salesApi.create(buildPayload(mode))
      const made = res.data
      refetchAlerts()
      // Offline: the sale is only stored on this device and sent later, so there is no
      // saved invoice yet to show, email or print.
      if (/\(offline\)/.test(res.statusText ?? '')) {
        toast.success(savedMessage(res, mode === 'proforma' ? 'Proforma invoice created' : mode === 'invoice' ? 'Invoice created' : 'Sale recorded'))
        navigate('/sales')
        return
      }
      // The total on screen must be the total that was saved, to the kobo. Read it back.
      const savedTotal = parseFloat(made?.total_amount)
      if (made?.id && Number.isFinite(savedTotal) && Math.abs(savedTotal - grandTotal) > 0.004) {
        await alertDialog(
          `The saved total is ${formatCurrency(savedTotal)} but the screen showed ${formatCurrency(grandTotal)}. ` +
          `Please check ${made.invoice_number ?? 'the document'} in Sales before giving it to the customer.`,
          { title: 'Total differs from the screen' },
        )
      }
      if (mode === 'invoice') {
        toast.success('Invoice created!')
        setCreated(made)
        return
      }
      toast.success(mode === 'proforma' ? 'Proforma saved. No stock moved and no payment taken.' : 'Sale recorded!')
      // Hand the customer their receipt before leaving the screen. Skipped for a proforma,
      // which is a quote and not proof of payment.
      if (mode === 'sale' && made?.id && autoPrint) {
        const tendered = tenderedNum
        // The sale is already saved. If printing fails, say so; never undo or hide the sale.
        void Promise.resolve().then(() => printReceipt({
          ...receiptDefaults,
          invoiceNumber: made.invoice_number ?? '',
          date: formatDate(made.issue_date ?? new Date().toISOString()),
          time: formatReceiptTime(made.created_at ?? new Date().toISOString()),
          cashier: soldBy || currentUserName,
          customer: selectedCustomer?.name,
          lines: filled.map((l, i) => ({
            name: (l.product as Product).name,
            qty: parseFloat(l.qty) || 0,
            unit_price: parseFloat(stripCommas(l.price)) || 0,
            line_total: amounts[i].lineTotal,
            // Price there is before discount, so the sales-receipt layout can print it.
            gross_total: amounts[i].subtotal,
            discount: amounts[i].discount > 0 ? amounts[i].discount : undefined,
          })),
          // The saved invoice's own figures — what the customer was charged.
          subtotal: made.subtotal ?? subtotal,
          discount: made.discount_amount ?? discountTotal,
          tax: made.tax_amount ?? (taxTotal + taxIncluded),
          // VAT already inside VAT-inclusive prices: shown as information, not added.
          taxIncluded,
          total: made.total_amount ?? grandTotal,
          payments: !payNow ? [] : [{ method: paymentMethod, amount: made.amount_paid ?? grandTotal }],
          amountTendered: tendered || undefined,
          change: tendered ? Math.max(0, tendered - (parseFloat(made.total_amount) || grandTotal)) : undefined,
          firsIrn: made.firs_irn,
          qrCodeBase64: made.firs_qr_code,
        })).catch(() => toast.error('Receipt could not print. Sale is saved. Reprint from Sales.'))
      }
      navigate('/sales')
    } catch (err: unknown) {
      say(errorMessage(err, mode === 'invoice' ? 'Failed to create invoice' : 'Failed to record sale'))
    } finally {
      submittingRef.current = false
      setSubmitting(null)
    }
  }

  const startAnother = () => {
    setCreated(null)
    setLines([blankLine()])
    setSelectedCustomer(null); setCustomerQuery('')
    setAmountPaid(''); setNotes(''); setAdjustment(''); setDelivery('')
    setApplyCredit(false)
  }

  // ── Email / Export PDF (after the invoice exists) ──────────────────────────
  const makePdf = async (inv: Invoice) => {
    const a = useAuthStore.getState()
    const o = a.organisation
    return buildInvoicePDF(
      inv, o?.name ?? 'Audity', a.logoDataUrl ?? o?.logo, o?.address, o?.phone, o?.email,
      o?.bank_name, o?.bank_account_number, o?.bank_account_name, o?.bank_sort_code, o?.brand_color,
      o?.invoice_company_name, o?.company_name_font, o?.company_name_font_size, o?.company_name_font_bold,
      o?.company_name_font_italic, o?.company_name_font_underline, o?.company_name_font_color,
      o?.invoice_template, a.stampDataUrl ?? o?.company_stamp, o?.show_company_name_on_pdf ?? true,
    )
  }
  const loadFull = async (inv: Invoice): Promise<Invoice> => {
    try { return (await salesApi.invoice(inv.id)).data } catch { return inv }
  }
  const exportPdf = async () => {
    if (!created) return
    setExporting(true)
    try {
      const preview = await makePdf(await loadFull(created))
      const blob = await (await fetch(preview.url)).blob()
      await saveBlobFile(blob, preview.filename)
      URL.revokeObjectURL(preview.url)
    } catch { toast.error('Failed to generate PDF') }
    finally { setExporting(false) }
  }
  const emailInvoice = async () => {
    if (!created) return
    const to = await promptDialog(`Send invoice ${created.invoice_number} by email with the PDF attached.`, {
      title: 'Send invoice by email',
      placeholder: selectedCustomer?.name ? `${selectedCustomer.name}'s email, or type another` : 'customer@email.com',
      confirmText: 'Send',
      optional: true,
    })
    if (to === null) return
    setEmailing(true)
    try {
      let pdf_base64: string | undefined
      try {
        const preview = await makePdf(await loadFull(created))
        const bytes = new Uint8Array(await (await fetch(preview.url)).arrayBuffer())
        let binary = ''
        bytes.forEach((b) => { binary += String.fromCharCode(b) })
        pdf_base64 = btoa(binary)
        URL.revokeObjectURL(preview.url)
      } catch { /* send without the attachment if the PDF cannot be made */ }
      await salesApi.sendEmail(created.id, { to_email: to.trim() || undefined, pdf_base64 })
      toast.success('Invoice sent by email')
    } catch (err: unknown) {
      await alertDialog(errorMessage(err, 'Failed to send email'), { title: 'Email not sent' })
    } finally { setEmailing(false) }
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  const locked = created !== null
  const noWarehouses = warehouses.length === 0
  const invoiceBlock = blocker('invoice')
  const saleBlock = blocker('sale')
  const itemsBlock = filled.length === 0 ? 'Add at least one item to continue.' : null
  const busy = submitting !== null
  // One line that applies to both buttons; anything specific to one button shows under it.
  const hint = itemsBlock ?? (saleBlock !== null && saleBlock === invoiceBlock ? saleBlock : null)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">New sale &amp; invoice</h1>
        <p className="text-slate-400 text-sm mt-1">Add items once. Then create an invoice or complete a sale — all from here.</p>
      </div>

      {created && (
        <div className="ds-created" role="status">
          <span className="font-semibold">Invoice {created.invoice_number} created</span>
          <span>· Total {formatCurrency(created.total_amount)}</span>
          <span className="ml-auto flex gap-2">
            <button type="button" className="btn-secondary px-3 py-1.5 text-sm" onClick={() => navigate('/sales')}>View invoices</button>
            <button type="button" className="btn-primary px-3 py-1.5 text-sm" onClick={startAnother}>Start another</button>
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px] 2xl:grid-cols-[minmax(0,1fr)_380px] gap-6 items-start">
        {/* ── Left column ── */}
        <div className="space-y-6 min-w-0">
          {/* Customer & details */}
          <section className="card p-5 space-y-4" aria-labelledby="ns-customer">
            <h2 id="ns-customer" className="text-base font-semibold">Customer &amp; details</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="label mb-1 block" htmlFor="ns-customer-search">Customer</label>
                {selectedCustomer ? (
                  <div className="input flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold truncate">{selectedCustomer.name}</p>
                      <p className="text-xs text-slate-400 truncate">
                        {selectedCustomer.customer_type} · {selectedCustomer.phone}
                        {customerStoreCredit > 0 && <> · Credit {formatCurrency(selectedCustomer.available_credit)}</>}
                      </p>
                    </div>
                    <button type="button" disabled={locked}
                      onClick={() => { setSelectedCustomer(null); setCustomerQuery('') }}
                      className="ds-icon-btn" data-tone="bad" aria-label="Remove customer">
                      <X size={16} />
                    </button>
                  </div>
                ) : (
                  <div className="relative">
                    <input
                      id="ns-customer-search" className="input pe-10" placeholder="Search customer…" autoComplete="off"
                      value={customerQuery} disabled={locked}
                      onChange={(e) => setCustomerQuery(e.target.value)}
                      onFocus={() => customers.length > 0 && setShowCustomerDrop(true)}
                      onBlur={() => setTimeout(() => setShowCustomerDrop(false), 150)}
                    />
                    <Search size={18} className="absolute end-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
                    {showCustomerDrop && customers.length > 0 && (
                      <div className="absolute top-full mt-1 left-0 right-0 bg-surface-800 border border-surface-600 rounded-xl shadow-xl z-20 max-h-48 overflow-y-auto">
                        {customers.map((c) => (
                          <button key={c.id} type="button"
                            onMouseDown={() => { setSelectedCustomer(c); setCustomerQuery(''); setShowCustomerDrop(false) }}
                            className="w-full text-left px-4 py-3 hover:bg-surface-700 transition-colors">
                            <p className="text-sm font-medium">{c.name}</p>
                            <p className="text-xs text-slate-400">{c.customer_type} · {c.phone}</p>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
              <div>
                <label className="label mb-1 block" htmlFor="ns-warehouse">Warehouse (stock)</label>
                {noWarehouses ? (
                  <p className="text-sm ds-line-warn">
                    No warehouses found. <a href="/inventory/warehouses" className="underline">Add one first →</a>
                  </p>
                ) : (
                  <select id="ns-warehouse" className="input" value={selectedWarehouse} disabled={locked}
                    onChange={(e) => setSelectedWarehouse(e.target.value)}>
                    <option value="">Select warehouse…</option>
                    {warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}{w.is_default ? ' (default)' : ''}</option>)}
                  </select>
                )}
              </div>
            </div>
            <p className="text-sm text-slate-400">Required for an invoice or credit. Leave blank for a walk-in sale.</p>
            {!payNow && !selectedCustomer && <p className="text-sm ds-line-bad" role="alert">Pick a customer to sell on credit.</p>}

            {locations.length > 0 && (
              <div className="md:max-w-[50%]">
                <label className="label mb-1 block" htmlFor="ns-location">Sales location (branch)</label>
                <select id="ns-location" className="input" value={selectedLocation} disabled={locked}
                  onChange={(e) => setSelectedLocation(e.target.value)}>
                  <option value="">— No specific location —</option>
                  {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                </select>
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr] md:grid-cols-[1fr_1fr_1.1fr] gap-4 items-end">
              <div>
                <label className="label mb-1 block">Issue date</label>
                <DateInput value={issueDate} onChange={setIssueDate} disabled={locked} />
              </div>
              <div>
                <label className="label mb-1 block">Due date</label>
                <DateInput value={dueDate} onChange={setDueDate} disabled={locked} />
                {dueDate && issueDate && dueDate < issueDate && (
                  <p className="text-xs ds-line-bad mt-1" role="alert">Due date cannot be before the issue date.</p>
                )}
              </div>
              <div className="sm:col-span-2 md:col-span-1">
                <p className="text-sm font-medium ds-line-info">For invoices</p>
                <p className="text-xs text-slate-400">Dates apply when you choose Create invoice.</p>
              </div>
            </div>
          </section>

          {/* Items */}
          <section className="card p-5 space-y-4" aria-labelledby="ns-items">
            <h2 id="ns-items" className="text-base font-semibold">Items · {filled.length}</h2>

            <div className="flex items-center gap-3">
              <div className="relative flex-1" ref={searchWrapRef}>
                <input
                  ref={searchRef} className="input pe-10" disabled={locked} autoComplete="off"
                  aria-label="Scan barcode or search by name or SKU"
                  placeholder="Scan barcode or search by name / SKU…"
                  value={productQuery}
                  onChange={(e) => setProductQuery(e.target.value)}
                  onFocus={() => products.length > 0 && setShowProductDrop(true)}
                  onKeyDown={(e) => {
                    // A scanner ends its burst with Enter. Read the value off the element,
                    // NOT React state: the scanner sends Enter faster than React flushes.
                    if (e.key === 'Enter') { e.preventDefault(); handleScan(e.currentTarget.value) }
                  }}
                />
                {scanning
                  ? <Loader2 size={16} className="animate-spin absolute end-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  : <Grid3x3 size={18} className="absolute end-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />}
                {showProductDrop && products.length > 0 && (
                  <div className="absolute top-full mt-1 left-0 right-0 bg-surface-800 border border-surface-600 rounded-xl shadow-xl z-20 max-h-72 overflow-y-auto">
                    {products.map((p) => (
                      <button key={p.id} type="button" onMouseDown={() => pickFromSearch(p)}
                        className="w-full flex items-center justify-between px-4 py-3 hover:bg-surface-700 transition-colors text-left">
                        <div>
                          <p className="text-sm font-medium">{p.name}</p>
                          <p className="text-xs text-slate-400">
                            {p.sku} · {p.unit_of_measure} · Stock: {p.total_stock}
                          </p>
                        </div>
                        <span className="text-brand-400 font-semibold text-sm">{formatCurrency(p.selling_price)}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button type="button" className="ds-link-btn flex items-center gap-1.5 shrink-0" disabled={locked}
                onClick={() => handleScan(searchRef.current?.value ?? '')}>
                <Grid3x3 size={16} /> Scan
              </button>
            </div>

            <div className="ds-lines-wrap">
              <div className="ds-lines space-y-2">
                <div className="ds-lines-row ds-lines-head" role="row">
                  <span>Product</span><span>Qty</span><span>Unit price</span><span>Disc %</span><span>VAT</span><span className="text-right">Amount</span><span />
                </div>
                {lines.map((l, i) => {
                  const a = saleLine(toSaleLine(l))
                  return (
                    <div key={l.key} className="ds-lines-row" role="row">
                      <ProductCell line={l} disabled={locked}
                        onPick={(p) => updateLine(l.key, lineFromProduct(l.key, p, l.qty || '1', undefined, l.disc || '0'))}
                        onClear={() => updateLine(l.key, { product: null, price: '', vatOn: false, taxClass: null, manualRate: '' })} />
                      <input type="number" min="0" step="any" className="input" aria-label={`Quantity, line ${i + 1}`}
                        value={l.qty} disabled={locked} onFocus={(e) => e.target.select()}
                        onChange={(e) => updateLine(l.key, { qty: e.target.value })} />
                      <AmountInput className="input" placeholder="0.00" aria-label={`Unit price, line ${i + 1}`}
                        value={l.price} disabled={locked} onChange={(v) => updateLine(l.key, { price: v })} />
                      <input type="number" min="0" max="100" step="0.5" className="input" aria-label={`Discount percent, line ${i + 1}`}
                        value={l.disc} disabled={locked} onFocus={(e) => e.target.select()}
                        onChange={(e) => updateLine(l.key, { disc: e.target.value })} />
                      <VatCell line={l} classes={taxClasses} disabled={locked || !l.product}
                        vatAmount={a.tax} inclusive={l.product?.tax_type === 'inclusive'}
                        onChange={(patch) => updateLine(l.key, patch)} />
                      <div className="ds-amount" aria-label={`Amount, line ${i + 1}`}>
                        {l.product ? formatCurrency(a.subtotal - a.discount) : '0.00'}
                      </div>
                      <button type="button" className="ds-icon-btn mt-1" data-tone="bad" disabled={locked}
                        aria-label={`Remove line ${i + 1}`} onClick={() => removeLine(l.key)}>
                        <Trash2 size={16} />
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
            <div aria-live="polite">
              {filled.map((l, i) => {
                const msgs: string[] = []
                if ((parseFloat(l.qty) || 0) <= 0) msgs.push('Quantity must be more than 0.')
                if ((parseFloat(stripCommas(l.price)) || 0) <= 0) msgs.push('Price must be more than 0.')
                if ((parseFloat(l.disc) || 0) > 100) msgs.push('Discount cannot be more than 100%.')
                return msgs.length ? <p key={l.key} className="text-sm ds-line-bad">Line {i + 1}: {msgs.join(' ')}</p> : null
              })}
            </div>
            <button type="button" className="ds-link-btn flex items-center gap-1" onClick={addBlankLine} disabled={locked}>
              <Plus size={14} /> Add line
            </button>
          </section>

          {/* Payment */}
          <section className="card p-5 space-y-4" aria-labelledby="ns-payment">
            <h2 id="ns-payment" className="text-base font-semibold">Payment</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <button type="button" className="ds-opt" aria-pressed={payNow} disabled={locked} onClick={() => setPayNow(true)}>
                Record payment now
              </button>
              <button type="button" className="ds-opt" aria-pressed={!payNow} disabled={locked} onClick={() => setPayNow(false)}>
                Credit · pay later
              </button>
            </div>
            <p className="text-sm text-slate-400">
              Paying now records a payment. Choose credit to leave the balance outstanding; a customer is required.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {METHODS.map((m) => (
                <button key={m.value} type="button" className="ds-opt" disabled={locked || !payNow}
                  aria-pressed={payNow && paymentMethod === m.value} onClick={() => setPaymentMethod(m.value)}>
                  {m.label}
                </button>
              ))}
            </div>
            {payNow && tenderedNum > 0 && tenderedNum < effectiveBalanceDue - 0.004 && (
              <p className="text-sm ds-line-warn" role="status">{formatCurrency(effectiveBalanceDue - tenderedNum)} still owed</p>
            )}
            {payNow && paymentMethod !== 'cash' && tenderedNum > effectiveBalanceDue + 0.004 && (
              <p className="text-sm ds-line-bad" role="alert">Amount is more than the total.</p>
            )}
            {payNow && <div className="grid grid-cols-1 sm:grid-cols-[minmax(0,1fr)_auto] gap-4 items-end">
              <div>
                <label className="label mb-1 block" htmlFor="ns-tendered">Amount received / tendered (₦)</label>
                <AmountInput id="ns-tendered" className="input" placeholder={formatCurrency(effectiveBalanceDue).replace(/^[^\d-]+/, '')}
                  value={amountPaid} disabled={locked || !payNow} onChange={setAmountPaid} />
              </div>
              <div className="min-w-[120px]">
                <p className="text-xs uppercase tracking-wide text-slate-400">Change · cash only</p>
                <p className="text-lg font-semibold" data-testid="change">{formatCurrency(changeGiven)}</p>
              </div>
            </div>}

            {selectedCustomer && customerStoreCredit > 0 && !isNaN(customerStoreCredit) && (
              <label className="ds-check-card">
                <input type="checkbox" className="ds-check" checked={applyCredit} disabled={locked}
                  onChange={(e) => setApplyCredit(e.target.checked)} />
                <div>
                  <p className="text-sm font-medium ds-line-good">Apply store credit</p>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {formatCurrency(customerStoreCredit)} available · deducts {formatCurrency(Math.min(customerStoreCredit, grandTotal))} from the balance
                  </p>
                </div>
              </label>
            )}

            {tillOpen === null && tillChecked && <p className="text-sm text-slate-400" role="status">Till status unknown.</p>}
            {tillOpen === false && (
              <div className="ds-strip items-center" role="status">
                <AlertTriangle size={18} className="shrink-0" />
                <div className="flex-1">
                  <p className="font-medium">No till open — cash only</p>
                  <p className="text-xs">Open a till for cash. Card, transfer and credit are still available.</p>
                </div>
                <button type="button" onClick={() => navigate('/pos/till')}>Open till</button>
              </div>
            )}
          </section>

          {/* Notes & responsibility */}
          <section className="card p-5 space-y-4" aria-labelledby="ns-notes">
            <h2 id="ns-notes" className="text-base font-semibold">Notes &amp; responsibility</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="label mb-1 block" htmlFor="ns-note">Notes (optional)</label>
                <textarea id="ns-note" className="input resize-none" rows={5} maxLength={2000} disabled={locked}
                  placeholder="Add a note for this transaction…" value={notes} onChange={(e) => setNotes(e.target.value)} />
                {notes.length >= 2000 && <p className="text-xs ds-line-warn mt-1" role="status">Notes can be up to 2000 characters.</p>}
              </div>
              <div>
                <label className="label mb-1 block" htmlFor="ns-soldby">Issued / sold by</label>
                <select id="ns-soldby" className="input" value={soldBy} disabled={locked} onChange={(e) => setSoldBy(e.target.value)}>
                  {soldByOptions.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </div>
            </div>
          </section>
        </div>

        {/* ── Right column ── */}
        <div className="space-y-6 min-w-0">
          {/* Order summary */}
          <section className="card p-5 space-y-3" aria-labelledby="ns-summary">
            <h2 id="ns-summary" className="text-base font-semibold">Order summary</h2>
            <div className="ds-sum-row text-slate-400">
              <span>Subtotal · {filled.length} {filled.length === 1 ? 'item' : 'items'}</span>
              <span className="text-white">{formatCurrency(subtotal)}</span>
            </div>
            <div className="ds-sum-row text-slate-400">
              <span>Item discounts</span>
              <span className="text-white">{discountTotal > 0 ? '− ' : ''}{formatCurrency(discountTotal)}</span>
            </div>
            <div className="ds-sum-row text-slate-400">
              <span>VAT</span>
              <span className="text-white">{taxTotal > 0 ? '+ ' : ''}{formatCurrency(taxTotal)}</span>
            </div>
            {taxIncluded > 0 && (
              <div className="ds-sum-row text-xs text-slate-400">
                <span>VAT included in prices</span>
                <span>{formatCurrency(taxIncluded)}</span>
              </div>
            )}
            <div className="ds-sum-row pt-1">
              <label htmlFor="ns-adjust" className="text-slate-400">Total adjustment (₦)</label>
              <input id="ns-adjust" className="input text-left w-[120px]" placeholder="0.00" inputMode="decimal" disabled={locked}
                value={adjustment} onChange={(e) => setAdjustment(e.target.value.replace(/[^0-9.,+\-−]/g, '').replace('−', '-'))} />
            </div>
            <p className="ds-sum-note">Use − for a discount, + for an extra charge.</p>
            {adjustmentParsed === null && <p className="text-sm ds-line-bad" role="alert">Enter a number, like -500 or 200.</p>}
            {adjustmentParsed !== null && breakdown.adjustmentError === 'bigger-than-invoice' && (
              <p className="text-sm ds-line-bad" role="alert">Adjustment is bigger than the total.</p>
            )}
            {adjustmentParsed !== null && adjustmentNum !== 0 && (
              <div className="ds-sum-row text-slate-400">
                <span>Adjustment applied</span>
                <span className="text-white" data-testid="adjustment-signed">{adjustmentNum < 0 ? '-' : '+'}{formatCurrency(Math.abs(adjustmentNum))}</span>
              </div>
            )}
            <div className="ds-sum-row">
              <label htmlFor="ns-delivery" className="text-slate-400">
                Delivery / shipping (₦)
                <span className="block text-xs">Invoice only</span>
              </label>
              <AmountInput id="ns-delivery" className="input w-[120px]" placeholder="0.00" value={delivery} disabled={locked} onChange={setDelivery} />
            </div>
            <div className="ds-sum-row border-t border-surface-700 pt-3">
              <span className="font-medium">Grand total</span>
              <span className="ds-grand" data-testid="grand-total">{formatCurrency(grandTotal)}</span>
            </div>
            {creditApplied > 0 && (
              <div className="ds-sum-row ds-line-good">
                <span>Store credit applied</span><span>− {formatCurrency(creditApplied)}</span>
              </div>
            )}
          </section>

          {/* Fulfillment */}
          <section className="card p-5 space-y-3" aria-labelledby="ns-fulfil">
            <h2 id="ns-fulfil" className="text-base font-semibold">Fulfillment</h2>
            <label className="ds-radio-card">
              <input type="radio" name="fulfil" className="ds-radio" checked={fulfil === 'now'} disabled={locked} onChange={() => setFulfil('now')} />
              <span>
                <span className="block text-sm font-medium">Fulfill now</span>
                <span className="block text-xs text-slate-400">
                  Deduct stock from {warehouses.find((w) => w.id === selectedWarehouse)?.name ?? 'the warehouse'} and post to the ledger immediately.
                </span>
              </span>
            </label>
            <label className="ds-radio-card">
              <input type="radio" name="fulfil" className="ds-radio" checked={fulfil === 'later'} disabled={locked} onChange={() => setFulfil('later')} />
              <span>
                <span className="block text-sm font-medium">Fulfill later</span>
                <span className="block text-xs text-slate-400">Keep pending fulfillment until the items are delivered.</span>
              </span>
            </label>
            <p className="text-sm text-slate-400">Payment and fulfillment are separate. You can collect payment before delivery.</p>
            {ENABLE_DEFERRED_PAYMENT_COMBOS && fulfil === 'later' && payNow && (
              <p className="text-sm ds-line-info">This money is held as a customer deposit until you deliver.</p>
            )}
          </section>

          {/* Ready when you are */}
          <section className="card p-5 space-y-3" aria-labelledby="ns-ready">
            <h2 id="ns-ready" className="text-base font-semibold">Ready when you are</h2>
            <label className="flex items-center gap-3 cursor-pointer select-none">
              <input type="checkbox" className="ds-check" checked={autoPrint} onChange={(e) => toggleAutoPrint(e.target.checked)} />
              <span className="text-sm">Print receipt after sale</span>
            </label>
            <div>
              <p className="text-sm font-medium" data-testid="ready-hint">
                {hint ?? (locked ? 'Invoice created.' : 'Everything needed is filled in.')}
              </p>
              {!selectedCustomer && <p className="ds-ready-note">For an invoice, also select a customer.</p>}
            </div>
            <button type="button" className="btn-secondary w-full justify-center py-3 text-base"
              disabled={locked || busy || invoiceBlock !== null} onClick={() => handleSubmit('invoice')}>
              {submitting === 'invoice' ? 'Creating…' : 'Create invoice'}
            </button>
            <p className="ds-ready-note">Create a customer invoice with the dates and delivery charge above.</p>
            <button type="button" className="btn-primary w-full justify-center py-3 text-base"
              disabled={locked || busy || saleBlock !== null} onClick={() => handleSubmit('sale')}>
              {submitting === 'sale' ? 'Processing…' : 'Complete sale'}
            </button>
            <p className="ds-ready-note">Record a sale using your payment and fulfillment choices. Walk-ins welcome.</p>
            {!locked && saleBlock && saleBlock !== hint && <p className="text-sm ds-line-warn" role="status">{saleBlock}</p>}
            <hr className="border-surface-700" />
            <div className="grid grid-cols-2 gap-3">
              <button type="button" className="btn-secondary justify-center" disabled={locked || busy} onClick={holdBasket}>
                Hold basket
              </button>
              <button type="button" className="btn-secondary justify-center"
                disabled={locked || busy || filled.length === 0 || !selectedWarehouse || deliveryNum > 0}
                onClick={() => handleSubmit('proforma')}>
                {submitting === 'proforma' ? 'Saving…' : 'Save as proforma'}
              </button>
            </div>
            <p className="ds-ready-note">Not ready? Save your items without recording a payment or moving stock.</p>
            {held.length > 0 && (
              <div>
                <button type="button" className="ds-link-btn text-sm" aria-expanded={showHeld} onClick={() => setShowHeld((v) => !v)}>
                  Held ({held.length})
                </button>
                {showHeld && (
                  <div className="mt-2 ds-held">
                    {held.map((b) => (
                      <div key={b.id} className="ds-held-row">
                        <span className="text-sm flex-1 truncate">{b.label}</span>
                        <span className="text-xs text-slate-400">
                          {formatDate(b.at)}{Date.now() - new Date(b.at).getTime() > OLD_BASKET_MS ? ' · old' : ''}
                        </span>
                        <button type="button" className="ds-link-btn text-sm" onClick={() => resumeBasket(b.id)}>Resume</button>
                        <button type="button" className="ds-icon-btn" data-tone="bad" aria-label="Discard held basket" title="Discard"
                          onClick={async () => {
                            if (await confirmDialog(`Discard the held basket "${b.label}"?`, { confirmText: 'Discard', danger: true })) discardBasket(b.id)
                          }}>
                          <X size={13} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            <p className="text-sm min-h-[1.25rem]" role="status" aria-live="polite">{notice}</p>
          </section>

          {/* Email / Export PDF */}
          <section className="card p-4">
            <div className="grid grid-cols-2 gap-3">
              <button type="button" className="btn-ghost justify-center gap-2" disabled={!created || emailing} onClick={emailInvoice}
                title={created ? 'Email this invoice' : 'Available after you create an invoice.'}>
                {emailing ? <Loader2 size={16} className="animate-spin" /> : <Mail size={16} />} Email
              </button>
              <button type="button" className="btn-secondary justify-center gap-2" disabled={!created || exporting} onClick={exportPdf}
                title={created ? 'Save this invoice as a PDF' : 'Available after you create an invoice.'}>
                {exporting ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />} Export PDF
              </button>
            </div>
            {!created && <p className="ds-ready-note">Available after you create an invoice.</p>}
          </section>
        </div>
      </div>
    </div>
  )
}

// ── Product cell: a search box that becomes the product's name once picked ────
function ProductCell({ line, disabled, onPick, onClear }: {
  line: Line
  disabled: boolean
  onPick: (p: Product) => void
  onClear: () => void
}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Product[]>([])
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const handler = (e: MouseEvent) => { if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])
  useEffect(() => {
    const q = query.trim()
    if (!q) { setResults([]); return }
    let cancelled = false
    const t = setTimeout(async () => {
      try {
        const { data } = await inventoryApi.sellableProducts({ search: q, is_active: true })
        if (!cancelled) setResults(data.results ?? data)
      } catch { /* silent */ }
    }, 250)
    return () => { cancelled = true; clearTimeout(t) }
  }, [query])

  if (line.product) {
    return (
      <div className="input flex items-center justify-between gap-2 min-w-0" title={line.product.sku}>
        <span className="truncate text-sm">{line.product.name}</span>
        <button type="button" className="ds-icon-btn shrink-0" disabled={disabled} aria-label={`Change product ${line.product.name}`}
          onClick={() => { setQuery(''); onClear() }}>
          <X size={14} />
        </button>
      </div>
    )
  }
  return (
    <div className="relative" ref={wrap}>
      <input className="input" placeholder="Select product…" aria-label="Select product" disabled={disabled} autoComplete="off"
        value={query} onChange={(e) => { setQuery(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)} />
      {open && results.length > 0 && (
        <div className="absolute top-full mt-1 left-0 right-0 min-w-[240px] bg-surface-800 border border-surface-600 rounded-xl shadow-xl z-20 max-h-56 overflow-y-auto">
          {results.map((p) => (
            <button key={p.id} type="button" className="w-full flex items-center justify-between px-3 py-2 hover:bg-surface-700 transition-colors text-left"
              onMouseDown={() => { onPick(p); setQuery(''); setOpen(false) }}>
              <span className="text-sm truncate">{p.name}</span>
              <span className="text-xs text-brand-400 font-semibold ml-2 shrink-0">{formatCurrency(p.selling_price)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── VAT cell: tick box, plus the class / own-rate choice the old invoice screen had ──
function VatCell({ line, classes, disabled, vatAmount, inclusive, onChange }: {
  line: Line
  classes: TaxClass[]
  disabled: boolean
  vatAmount: number
  inclusive: boolean
  onChange: (patch: Partial<Line>) => void
}) {
  const p = line.product
  const setMode = (mode: string) => {
    if (mode === '__auto__') onChange({ taxClass: p?.tax_class ?? null, manualRate: '' })
    else if (mode === '__custom__') onChange({ manualRate: line.manualRate || '0' })
    else onChange({ taxClass: mode, manualRate: '' })
  }
  return (
    <div className="space-y-1">
      <label className="flex items-center gap-2 min-h-[42px] text-xs select-none">
        <input type="checkbox" className="ds-check" checked={line.vatOn} disabled={disabled}
          aria-label="Apply VAT to this line"
          onChange={(e) => onChange(e.target.checked
            ? { vatOn: true, taxClass: line.taxClass ?? p?.tax_class ?? null }
            : { vatOn: false })} />
        {line.vatOn && vatAmount > 0 && (
          <span className="text-slate-400" title={inclusive ? 'VAT already inside the price' : 'VAT added on top'}>
            {formatCurrency(vatAmount)}
          </span>
        )}
      </label>
      {line.vatOn && !disabled && classes.length > 0 && (
        <select className="input py-1 text-xs" aria-label="VAT rate for this line"
          value={line.manualRate !== '' ? '__custom__' : (line.taxClass ?? '__auto__')}
          onChange={(e) => setMode(e.target.value)}>
          <option value="__auto__">Auto (product)</option>
          {classes.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.rate}%)</option>)}
          <option value="__custom__">Custom %…</option>
        </select>
      )}
      {line.vatOn && line.manualRate !== '' && (
        <input type="number" min="0" max="100" step="0.01" className="input py-1 text-xs" placeholder="Rate %"
          aria-label="Own VAT rate" value={line.manualRate} disabled={disabled} onChange={(e) => onChange({ manualRate: e.target.value })} />
      )}
    </div>
  )
}
