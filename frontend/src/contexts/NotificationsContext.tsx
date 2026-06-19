import { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react'
import toast from 'react-hot-toast'
import { billApi, customerApi, inventoryApi, orgApi, payrollApi, purchaseApi, salesApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'

export interface StockAlert {
  id: string
  product_name: string
  product_sku: string
  warehouse_name: string
  quantity_available: string
}

export interface OverdueAlert {
  id: string
  invoice_number: string
  customer_name: string | null
  amount_due: string
  due_date: string
  days_overdue: number
}

export interface ExpiryAlert {
  id: string
  batch_number: string
  product_name: string
  product_sku: string
  warehouse_name: string
  expiry_date: string
  days_to_expiry: number | null
  is_expired: boolean
}

export interface BillDueAlert {
  id: string
  bill_number: string
  supplier_name: string
  amount_due: string
  due_date: string
}

export interface PayrollPendingAlert {
  id: string
  run_number: string
  period_year: number
  period_month: number
  total_net: string
}

export interface CustomerDueAlert {
  id: string
  invoice_number: string
  customer_name: string | null
  amount_due: string
  due_date: string
  days_until_due: number
}

export interface CustomerOutstandingAlert {
  id: string
  customer_name: string
  outstanding_balance: string
}

export interface PartnerRequestAlert {
  id: string
  partner_email: string
  partner_firm_name: string
  org_name: string
  created_at: string
}

export interface EtaAlert {
  id: string
  po_number: string
  supplier_name: string
  expected_date: string
  days_overdue: number
  item_count: number
  total_amount: string
  tier: 'arriving_tomorrow' | 'due_today' | 'overdue'
}

interface NotificationsCtx {
  alerts: StockAlert[]
  overdueAlerts: OverdueAlert[]
  expiryAlerts: ExpiryAlert[]
  billDueAlerts: BillDueAlert[]
  payrollPendingAlerts: PayrollPendingAlert[]
  customerDueAlerts: CustomerDueAlert[]
  customerOutstandingAlerts: CustomerOutstandingAlert[]
  partnerRequestAlerts: PartnerRequestAlert[]
  etaAlerts: EtaAlert[]
  count: number
  dismiss: (id: string) => void
  dismissAll: () => void
  dismissOverdue: (id: string) => void
  dismissExpiry: (id: string) => void
  dismissBillDue: (id: string) => void
  dismissPayrollPending: (id: string) => void
  dismissCustomerDue: (id: string) => void
  dismissCustomerOutstanding: (id: string) => void
  dismissPartnerRequest: (id: string) => void
  dismissEta: (id: string) => void
  quickReceive: (id: string) => Promise<void>
  refetch: () => void
}

const Ctx = createContext<NotificationsCtx>({
  alerts: [],
  overdueAlerts: [],
  expiryAlerts: [],
  billDueAlerts: [],
  payrollPendingAlerts: [],
  customerDueAlerts: [],
  customerOutstandingAlerts: [],
  partnerRequestAlerts: [],
  etaAlerts: [],
  count: 0,
  dismiss: () => {},
  dismissAll: () => {},
  dismissOverdue: () => {},
  dismissExpiry: () => {},
  dismissBillDue: () => {},
  dismissPayrollPending: () => {},
  dismissCustomerDue: () => {},
  dismissCustomerOutstanding: () => {},
  dismissPartnerRequest: () => {},
  dismissEta: () => {},
  quickReceive: async () => {},
  refetch: () => {},
})

// IDs dismissed by the user this session — persisted to sessionStorage so
// they survive the 30s poll cycle but reset cleanly when the app restarts.
function loadDismissed(): Set<string> {
  try {
    const raw = sessionStorage.getItem('audity-dismissed-notifications')
    return new Set(raw ? (JSON.parse(raw) as string[]) : [])
  } catch { return new Set() }
}
function saveDismissed(ids: Set<string>) {
  try { sessionStorage.setItem('audity-dismissed-notifications', JSON.stringify([...ids])) } catch { /* ignore */ }
}

export function NotificationsProvider({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const organisationId = useAuthStore((s) => s.organisation?.id)
  const memberRole = useAuthStore((s) => s.memberRole)
  const [alerts, setAlerts] = useState<StockAlert[]>([])
  const [overdueAlerts, setOverdueAlerts] = useState<OverdueAlert[]>([])
  const [expiryAlerts, setExpiryAlerts] = useState<ExpiryAlert[]>([])
  const [billDueAlerts, setBillDueAlerts] = useState<BillDueAlert[]>([])
  const [payrollPendingAlerts, setPayrollPendingAlerts] = useState<PayrollPendingAlert[]>([])
  const [customerDueAlerts, setCustomerDueAlerts] = useState<CustomerDueAlert[]>([])
  const [customerOutstandingAlerts, setCustomerOutstandingAlerts] = useState<CustomerOutstandingAlert[]>([])
  const [partnerRequestAlerts, setPartnerRequestAlerts] = useState<PartnerRequestAlert[]>([])
  const [etaAlerts, setEtaAlerts] = useState<EtaAlert[]>([])
  const prevIdsRef    = useRef<Set<string>>(new Set())
  const dismissedRef  = useRef<Set<string>>(loadDismissed())
  const firstPollRef  = useRef(true)
  const today = new Date().toISOString().split('T')[0]

  // 7 days from now
  const in7Days = new Date(Date.now() + 7 * 86400000).toISOString().split('T')[0]

  const poll = useCallback(async () => {
    if (!isAuthenticated || !organisationId) return
    try {
      const [stockData, overdueData, batchData, billDueData, payrollData, customerDueData, etaData, customerOutstandingData] = await Promise.allSettled([
        inventoryApi.lowStock({ page_size: 20 }),
        salesApi.invoices({ status: 'overdue', page_size: 10 }),
        inventoryApi.batches({ page_size: 30 }),
        billApi.list({ due_date_from: today, due_date_to: in7Days, status: 'approved', page_size: 10 }),
        payrollApi.runs({ page_size: 5 }),
        // Invoices on credit / partially paid due within the next 7 days
        salesApi.invoices({ due_date_from: today, due_date_to: in7Days, page_size: 10 }),
        purchaseApi.etaAlerts(),
        // Customers with any outstanding balance yet to pay (account-level, not tied to a single invoice's due date)
        customerApi.list({ has_outstanding: true, ordering: '-outstanding_balance', page_size: 15 }),
      ])

      if (stockData.status === 'fulfilled') {
        const allItems: StockAlert[] = (stockData.value.data.results ?? stockData.value.data).map((i: any) => ({
          id: i.id,
          product_name: i.product_name,
          product_sku: i.product_sku,
          warehouse_name: i.warehouse_name,
          quantity_available: i.quantity_available,
        }))
        const items = allItems.filter((i) => !dismissedRef.current.has(i.id))

        if (firstPollRef.current) {
          firstPollRef.current = false
          if (items.length > 0) {
            toast(
              items.length === 1
                ? `⚠️ Low stock: ${items[0].product_name} (${items[0].quantity_available} left)`
                : `⚠️ ${items.length} products are low on stock`,
              { duration: 6000 },
            )
          }
        } else {
          const newItems = items.filter((i) => !prevIdsRef.current.has(i.id))
          newItems.forEach((item) => {
            toast(`⚠️ Low stock: ${item.product_name} (${item.quantity_available} left)`, {
              duration: 5000,
            })
          })
        }

        prevIdsRef.current = new Set(items.map((i) => i.id))
        setAlerts(items)
      }

      if (overdueData.status === 'fulfilled') {
        const invoices = overdueData.value.data.results ?? overdueData.value.data
        const overdue: OverdueAlert[] = invoices
          .filter((inv: any) => !dismissedRef.current.has(inv.id))
          .map((inv: any) => ({
            id: inv.id,
            invoice_number: inv.invoice_number,
            customer_name: inv.customer_name ?? null,
            amount_due: inv.amount_due,
            due_date: inv.due_date,
            days_overdue: Math.max(0, Math.floor((new Date(today).getTime() - new Date(inv.due_date).getTime()) / 86400000)),
          }))
        setOverdueAlerts(overdue)
      }

      if (batchData.status === 'fulfilled') {
        const batches = batchData.value.data.results ?? batchData.value.data
        const expiring: ExpiryAlert[] = batches
          .filter((b: any) => {
            if (!b.expiry_date) return false
            if (dismissedRef.current.has(b.id)) return false
            const daysLeft = b.days_to_expiry ?? Math.floor((new Date(b.expiry_date).getTime() - new Date(today).getTime()) / 86400000)
            return daysLeft <= 30
          })
          .map((b: any) => {
            const daysLeft = b.days_to_expiry ?? Math.floor((new Date(b.expiry_date).getTime() - new Date(today).getTime()) / 86400000)
            return {
              id: b.id,
              batch_number: b.batch_number,
              product_name: b.product_name,
              product_sku: b.product_sku,
              warehouse_name: b.warehouse_name,
              expiry_date: b.expiry_date,
              days_to_expiry: daysLeft,
              is_expired: daysLeft < 0,
            }
          })
        setExpiryAlerts(expiring)
      }

      // Bills due tomorrow
      if (billDueData.status === 'fulfilled') {
        const bills = billDueData.value.data.results ?? billDueData.value.data
        const due: BillDueAlert[] = bills
          .filter((b: any) => !dismissedRef.current.has(b.id))
          .map((b: any) => ({
            id: b.id,
            bill_number: b.bill_number,
            supplier_name: b.supplier_name ?? b.supplier ?? 'Unknown supplier',
            amount_due: b.amount_due ?? b.total,
            due_date: b.due_date,
          }))
        setBillDueAlerts(due)
      }

      // Payroll runs awaiting approval (status = processing)
      if (payrollData.status === 'fulfilled') {
        const runs = payrollData.value.data.results ?? payrollData.value.data
        const pending: PayrollPendingAlert[] = (runs as any[])
          .filter((r: any) => r.status === 'processing' && !dismissedRef.current.has(r.id))
          .map((r: any) => ({
            id: r.id,
            run_number: r.run_number,
            period_year: r.period_year,
            period_month: r.period_month,
            total_net: r.total_net,
          }))
        setPayrollPendingAlerts(pending)
      }

      // Partner access requests — only poll for owners/admins
      if (organisationId && (memberRole === 'owner' || memberRole === 'admin')) {
        try {
          const prRes = await orgApi.listPartnerRequests(organisationId)
          const reqs: any[] = prRes.data.results ?? prRes.data
          const pending: PartnerRequestAlert[] = reqs
            .filter((r: any) => r.status === 'pending' && !dismissedRef.current.has(`pr-${r.id}`))
            .map((r: any) => ({
              id: `pr-${r.id}`,
              partner_email: r.partner_email,
              partner_firm_name: r.partner_firm_name || '',
              org_name: r.org_name,
              created_at: r.created_at,
            }))
          setPartnerRequestAlerts(pending)
        } catch {
          // Silently ignore — not critical
        }
      }

      // Customer invoices due within 7 days (credit / partially_paid)
      if (customerDueData.status === 'fulfilled') {
        const invoices = customerDueData.value.data.results ?? customerDueData.value.data
        const due: CustomerDueAlert[] = (invoices as any[])
          .filter((inv: any) =>
            inv.due_date &&
            ['credit', 'partially_paid', 'confirmed'].includes(inv.status) &&
            !dismissedRef.current.has(`cdu-${inv.id}`)
          )
          .map((inv: any) => {
            const daysLeft = Math.ceil(
              (new Date(inv.due_date).getTime() - new Date(today).getTime()) / 86400000
            )
            return {
              id: `cdu-${inv.id}`,
              invoice_number: inv.invoice_number,
              customer_name: inv.customer_name ?? null,
              amount_due: inv.amount_due,
              due_date: inv.due_date,
              days_until_due: daysLeft,
            }
          })
        setCustomerDueAlerts(due)
      }

      // Customers with an outstanding balance yet to pay (account-level)
      if (customerOutstandingData.status === 'fulfilled') {
        const custs = customerOutstandingData.value.data.results ?? customerOutstandingData.value.data
        const outstanding: CustomerOutstandingAlert[] = (custs as any[])
          .filter((c: any) => !dismissedRef.current.has(`co-${c.id}`))
          .map((c: any) => ({
            id: `co-${c.id}`,
            customer_name: c.name,
            outstanding_balance: c.outstanding_balance,
          }))
        setCustomerOutstandingAlerts(outstanding)
      }

      // PO ETA alerts — arriving tomorrow, due today, overdue
      if (etaData.status === 'fulfilled') {
        const raw = etaData.value.data
        const mapPo = (tier: EtaAlert['tier']) => (po: any): EtaAlert => ({
          id: `eta-${po.id}`,
          po_number: po.po_number,
          supplier_name: po.supplier_name,
          expected_date: po.expected_date,
          days_overdue: po.days_overdue,
          item_count: po.item_count,
          total_amount: po.total_amount,
          tier,
        })
        const allEta: EtaAlert[] = [
          ...(raw.arriving_tomorrow ?? []).map(mapPo('arriving_tomorrow')),
          ...(raw.due_today ?? []).map(mapPo('due_today')),
          ...(raw.overdue ?? []).map(mapPo('overdue')),
        ].filter((a) => !dismissedRef.current.has(a.id))
        setEtaAlerts(allEta)
      }
    } catch {
      // Silently ignore poll failures
    }
  }, [isAuthenticated])

  // Clear all stale alerts immediately when the org or auth state changes so
  // a previous user's notifications are never visible under a different context.
  useEffect(() => {
    setAlerts([])
    setOverdueAlerts([])
    setExpiryAlerts([])
    setBillDueAlerts([])
    setPayrollPendingAlerts([])
    setCustomerDueAlerts([])
    setCustomerOutstandingAlerts([])
    setPartnerRequestAlerts([])
    setEtaAlerts([])
    prevIdsRef.current = new Set()
    firstPollRef.current = true
  }, [organisationId, isAuthenticated])

  useEffect(() => {
    if (!isAuthenticated || !organisationId) return
    poll()
    // Poll every 5 minutes — notification data (low stock, overdue invoices,
    // expiring batches) changes slowly. 30s was 6 API calls/30s = 720/hour.
    const POLL_MS = 5 * 60 * 1000
    let intervalId: ReturnType<typeof setInterval> | null = setInterval(poll, POLL_MS)

    // Pause polling when the tab/window is hidden, resume when visible
    const onVisibilityChange = () => {
      if (document.hidden) {
        if (intervalId) { clearInterval(intervalId); intervalId = null }
      } else {
        // Tab became visible — poll immediately then restart interval
        poll()
        if (!intervalId) intervalId = setInterval(poll, POLL_MS)
      }
    }
    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      if (intervalId) clearInterval(intervalId)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [isAuthenticated, organisationId, poll])

  const addDismissed = useCallback((id: string) => {
    dismissedRef.current.add(id)
    saveDismissed(dismissedRef.current)
  }, [])

  const dismiss = useCallback((id: string) => {
    addDismissed(id)
    setAlerts((prev) => prev.filter((a) => a.id !== id))
    prevIdsRef.current.delete(id)
  }, [addDismissed])

  const dismissAll = useCallback(() => {
    // Collect all current IDs before clearing state
    setAlerts((prev) => { prev.forEach((a) => addDismissed(a.id)); return [] })
    setOverdueAlerts((prev) => { prev.forEach((a) => addDismissed(a.id)); return [] })
    setExpiryAlerts((prev) => { prev.forEach((a) => addDismissed(a.id)); return [] })
    setBillDueAlerts((prev) => { prev.forEach((a) => addDismissed(a.id)); return [] })
    setPayrollPendingAlerts((prev) => { prev.forEach((a) => addDismissed(a.id)); return [] })
    setCustomerDueAlerts((prev) => { prev.forEach((a) => addDismissed(a.id)); return [] })
    setCustomerOutstandingAlerts((prev) => { prev.forEach((a) => addDismissed(a.id)); return [] })
    setPartnerRequestAlerts((prev) => { prev.forEach((a) => addDismissed(a.id)); return [] })
    setEtaAlerts((prev) => { prev.forEach((a) => addDismissed(a.id)); return [] })
    prevIdsRef.current = new Set()
  }, [addDismissed])

  const dismissOverdue = useCallback((id: string) => {
    addDismissed(id)
    setOverdueAlerts((prev) => prev.filter((a) => a.id !== id))
  }, [addDismissed])

  const dismissExpiry = useCallback((id: string) => {
    addDismissed(id)
    setExpiryAlerts((prev) => prev.filter((a) => a.id !== id))
  }, [addDismissed])

  const dismissBillDue = useCallback((id: string) => {
    addDismissed(id)
    setBillDueAlerts((prev) => prev.filter((a) => a.id !== id))
  }, [addDismissed])

  const dismissPayrollPending = useCallback((id: string) => {
    addDismissed(id)
    setPayrollPendingAlerts((prev) => prev.filter((a) => a.id !== id))
  }, [addDismissed])

  const dismissCustomerDue = useCallback((id: string) => {
    addDismissed(id)
    setCustomerDueAlerts((prev) => prev.filter((a) => a.id !== id))
  }, [addDismissed])

  const dismissCustomerOutstanding = useCallback((id: string) => {
    addDismissed(id)
    setCustomerOutstandingAlerts((prev) => prev.filter((a) => a.id !== id))
  }, [addDismissed])

  const dismissPartnerRequest = useCallback((id: string) => {
    addDismissed(id)
    setPartnerRequestAlerts((prev) => prev.filter((a) => a.id !== id))
  }, [addDismissed])

  const dismissEta = useCallback((id: string) => {
    addDismissed(id)
    setEtaAlerts((prev) => prev.filter((a) => a.id !== id))
  }, [addDismissed])

  const quickReceive = useCallback(async (id: string) => {
    // id is `eta-<uuid>` — strip prefix to get the real PO UUID
    const poId = id.replace(/^eta-/, '')
    try {
      await purchaseApi.quickReceive(poId)
      toast.success('Goods marked as received!')
      dismissEta(id)
      poll()
    } catch (err: any) {
      const msg = err?.response?.data?.error ?? 'Failed to receive goods'
      toast.error(typeof msg === 'string' ? msg : 'Failed to receive goods')
    }
  }, [dismissEta, poll])

  const refetch = useCallback(() => { poll() }, [poll])

  const count =
    alerts.length + overdueAlerts.length + expiryAlerts.length +
    billDueAlerts.length + payrollPendingAlerts.length + customerDueAlerts.length +
    customerOutstandingAlerts.length + partnerRequestAlerts.length + etaAlerts.length

  return (
    <Ctx.Provider value={{
      alerts, overdueAlerts, expiryAlerts, billDueAlerts, payrollPendingAlerts,
      customerDueAlerts, customerOutstandingAlerts, partnerRequestAlerts, etaAlerts,
      count, dismiss, dismissAll, dismissOverdue, dismissExpiry,
      dismissBillDue, dismissPayrollPending, dismissCustomerDue, dismissCustomerOutstanding, dismissPartnerRequest,
      dismissEta, quickReceive, refetch,
    }}>
      {children}
    </Ctx.Provider>
  )
}

export function useNotifications() {
  return useContext(Ctx)
}
