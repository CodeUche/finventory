import { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react'
import toast from 'react-hot-toast'
import { inventoryApi } from '@/services/api'
import { useAuthStore } from '@/store/authStore'

export interface StockAlert {
  id: string
  product_name: string
  product_sku: string
  warehouse_name: string
  quantity_available: string
}

interface NotificationsCtx {
  alerts: StockAlert[]
  count: number
  dismiss: (id: string) => void
  dismissAll: () => void
}

const Ctx = createContext<NotificationsCtx>({
  alerts: [],
  count: 0,
  dismiss: () => {},
  dismissAll: () => {},
})

export function NotificationsProvider({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const [alerts, setAlerts] = useState<StockAlert[]>([])
  const prevIdsRef = useRef<Set<string>>(new Set())

  const poll = useCallback(async () => {
    if (!isAuthenticated) return
    try {
      const { data } = await inventoryApi.lowStock()
      const items: StockAlert[] = (data.results ?? data).map((i: any) => ({
        id: i.id,
        product_name: i.product_name,
        product_sku: i.product_sku,
        warehouse_name: i.warehouse_name,
        quantity_available: i.quantity_available,
      }))
      // Detect newly low-stock items since last poll
      const newItems = items.filter((i) => !prevIdsRef.current.has(i.id))
      if (newItems.length > 0 && prevIdsRef.current.size > 0) {
        // Only alert after the first poll (so we don't spam on app open)
        newItems.forEach((item) => {
          toast(`Low stock: ${item.product_name} (${item.quantity_available} left)`, {
            icon: '⚠️',
            duration: 5000,
          })
        })
      }
      prevIdsRef.current = new Set(items.map((i) => i.id))
      setAlerts(items)
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
    prevIdsRef.current = new Set()
  }, [])

  return (
    <Ctx.Provider value={{ alerts, count: alerts.length, dismiss, dismissAll }}>
      {children}
    </Ctx.Provider>
  )
}

export function useNotifications() {
  return useContext(Ctx)
}
