import { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react'
import toast from 'react-hot-toast'
import { billApi, inventoryApi, payrollApi, salesApi } from '@/services/api'
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

interface NotificationsCtx {
  alerts: StockAlert[]
  overdueAlerts: OverdueAlert[]
  expiryAlerts: ExpiryAlert[]
  billDueAlerts: BillDueAlert[]
  payrollPendingAlerts: PayrollPendingAlert[]
  count: number
  dismiss: (id: string) => void
  dismissAll: () => void
  dismissOverdue: (id: string) => void
  dismissExpiry: (id: string) => void
  dismissBillDue: (id: string) => void
  dismissPayrollPending: (id: string) => void
  refetch: () => void
}

const Ctx = createContext<NotificationsCtx>({
  alerts: [],
  overdueAlerts: [],
  expiryAlerts: [],
  billDueAlerts: [],
  payrollPendingAlerts: [],
  count: 0,
  dismiss: () => {},
  dismissAll: () => {},
  dismissOverdue: () => {},
  dismissExpiry: () => {},
  dismissBillDue: () => {},
  dismissPayrollPending: () => {},
  refetch: () => {},
})

export function NotificationsProvider({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const [alerts, setAlerts] = useState<StockAlert[]>([])
  const [overdueAlerts, setOverdueAlerts] = useState<OverdueAlert[]>([])
  const [expiryAlerts, setExpiryAlerts] = useState<ExpiryAlert[]>([])
  const [billDueAlerts, setBillDueAlerts] = useState<BillDueAlert[]>([])
  const [payrollPendingAlerts, setPayrollPendingAlerts] = useState<PayrollPendingAlert[]>([])
  const prevIdsRef   = useRef<Set<string>>(new Set())
  const firstPollRef = useRef(true)
  const today = new Date().toISOString().split('T')[0]

  // tomorrow's date as YYYY-MM-DD
  const tomorrow = new Date(Date.now() + 86400000).toISOString().split('T')[0]

  const poll = useCallback(async () => {
    if (!isAuthenticated) return
    try {
      const [stockData, overdueData, batchData, billDueData, payrollData] = await Promise.allSettled([
        inventoryApi.lowStock(),
        salesApi.invoices({ status: 'overdue', page_size: 20 }),
        inventoryApi.batches({ page_size: 200 }),
        billApi.list({ due_date: tomorrow, status: 'approved', page_size: 50 }),
        payrollApi.runs(),
      ])

      if (stockData.status === 'fulfilled') {
        const items: StockAlert[] = (stockData.value.data.results ?? stockData.value.data).map((i: any) => ({
          id: i.id,
          product_name: i.product_name,
          product_sku: i.product_sku,
          warehouse_name: i.warehouse_name,
          quantity_available: i.quantity_available,
        }))

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
        const overdue: OverdueAlert[] = invoices.map((inv: any) => ({
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
        const due: BillDueAlert[] = bills.map((b: any) => ({
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
          .filter((r: any) => r.status === 'processing')
          .map((r: any) => ({
            id: r.id,
            run_number: r.run_number,
            period_year: r.period_year,
            period_month: r.period_month,
            total_net: r.total_net,
          }))
        setPayrollPendingAlerts(pending)
      }
    } catch {
      // Silently ignore poll failures
    }
  }, [isAuthenticated])

  useEffect(() => {
    if (!isAuthenticated) return
    poll()
    const interval = setInterval(poll, 30_000)
    return () => clearInterval(interval)
  }, [isAuthenticated, poll])

  const dismiss = useCallback((id: string) => {
    setAlerts((prev) => prev.filter((a) => a.id !== id))
    prevIdsRef.current.delete(id)
  }, [])

  const dismissAll = useCallback(() => {
    setAlerts([])
    setOverdueAlerts([])
    setBillDueAlerts([])
    setPayrollPendingAlerts([])
    prevIdsRef.current = new Set()
  }, [])

  const dismissOverdue = useCallback((id: string) => {
    setOverdueAlerts((prev) => prev.filter((a) => a.id !== id))
  }, [])

  const dismissExpiry = useCallback((id: string) => {
    setExpiryAlerts((prev) => prev.filter((a) => a.id !== id))
  }, [])

  const dismissBillDue = useCallback((id: string) => {
    setBillDueAlerts((prev) => prev.filter((a) => a.id !== id))
  }, [])

  const dismissPayrollPending = useCallback((id: string) => {
    setPayrollPendingAlerts((prev) => prev.filter((a) => a.id !== id))
  }, [])

  const refetch = useCallback(() => { poll() }, [poll])

  const count =
    alerts.length + overdueAlerts.length + expiryAlerts.length +
    billDueAlerts.length + payrollPendingAlerts.length

  return (
    <Ctx.Provider value={{
      alerts, overdueAlerts, expiryAlerts, billDueAlerts, payrollPendingAlerts,
      count, dismiss, dismissAll, dismissOverdue, dismissExpiry,
      dismissBillDue, dismissPayrollPending, refetch,
    }}>
      {children}
    </Ctx.Provider>
  )
}

export function useNotifications() {
  return useContext(Ctx)
}
